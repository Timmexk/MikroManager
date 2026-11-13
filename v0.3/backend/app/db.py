"""Tiny SQLite layer. One connection, guarded by a lock; all queries are short."""
import json
import sqlite3
import threading
import time

import logging

from .config import DATA_DIR, DB_NAME, DEFAULT_SITE_SETTINGS, OLD_DB_NAME, OLD_PREFIX, use_prefix

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, pw_hash BLOB NOT NULL, salt BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sites (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, settings TEXT NOT NULL DEFAULT '{}', last_backup_day TEXT);
CREATE TABLE IF NOT EXISTS devices (
  id INTEGER PRIMARY KEY, site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
  name TEXT NOT NULL, host TEXT NOT NULL, port INTEGER NOT NULL, scheme TEXT NOT NULL DEFAULT 'https',
  verify_tls INTEGER NOT NULL DEFAULT 0, username TEXT NOT NULL, password_enc TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'router', is_controller INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS wlans (
  id INTEGER PRIMARY KEY, site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
  slug TEXT NOT NULL, ssid TEXT NOT NULL, passphrase_enc TEXT NOT NULL DEFAULT '',
  security TEXT NOT NULL DEFAULT 'wpa2wpa3', vlan_id INTEGER, bands TEXT NOT NULL DEFAULT '2g,5g',
  hidden INTEGER NOT NULL DEFAULT 0, isolation INTEGER NOT NULL DEFAULT 0, ft INTEGER NOT NULL DEFAULT 1,
  enabled INTEGER NOT NULL DEFAULT 1, position INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS client_names (
  site_id INTEGER NOT NULL, mac TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY (site_id, mac));
CREATE TABLE IF NOT EXISTS metrics (
  device_id INTEGER NOT NULL, ts REAL NOT NULL, cpu REAL, mem REAL, clients INTEGER, rx_bps REAL, tx_bps REAL);
CREATE INDEX IF NOT EXISTS metrics_idx ON metrics (device_id, ts);
CREATE TABLE IF NOT EXISTS client_seen (
  site_id INTEGER NOT NULL, mac TEXT NOT NULL, first_seen REAL NOT NULL, last_seen REAL NOT NULL,
  ip TEXT, hostname TEXT, kind TEXT, place TEXT, PRIMARY KEY (site_id, mac));
CREATE TABLE IF NOT EXISTS client_events (
  id INTEGER PRIMARY KEY, site_id INTEGER NOT NULL, mac TEXT NOT NULL, ts REAL NOT NULL, kind TEXT NOT NULL, detail TEXT);
CREATE INDEX IF NOT EXISTS client_events_idx ON client_events (site_id, mac, ts);
CREATE TABLE IF NOT EXISTS radio_settings (
  site_id INTEGER NOT NULL, radio_mac TEXT NOT NULL, tx_mode TEXT NOT NULL DEFAULT 'high', tx_power INTEGER,
  PRIMARY KEY (site_id, radio_mac));
CREATE TABLE IF NOT EXISTS client_schedules (
  site_id INTEGER NOT NULL, mac TEXT NOT NULL, start TEXT NOT NULL, stop TEXT NOT NULL, PRIMARY KEY (site_id, mac));
CREATE TABLE IF NOT EXISTS wan_quality (
  device_id INTEGER NOT NULL, ts REAL NOT NULL, wan TEXT NOT NULL, kind TEXT NOT NULL, rtt REAL, loss REAL);
CREATE INDEX IF NOT EXISTS wan_quality_idx ON wan_quality (device_id, ts);
CREATE TABLE IF NOT EXISTS backups (
  id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  ts REAL NOT NULL, filename TEXT NOT NULL, size INTEGER NOT NULL, sha TEXT NOT NULL,
  ros_version TEXT, trigger TEXT NOT NULL DEFAULT 'manual');
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY, site_id INTEGER, ts REAL NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL);
"""


def _carry_over_old_database() -> None:
    """0.1/0.2 kept their data in tikcontrol.db. Copy it once (the old file stays, so going back still works)."""
    new, old = DATA_DIR / DB_NAME, DATA_DIR / OLD_DB_NAME
    if new.exists() or not old.exists():
        return
    src = sqlite3.connect(old)
    dst = sqlite3.connect(new)
    try:
        src.backup(dst)          # consistent copy, also picks up what is still in the WAL
    finally:
        src.close()
        dst.close()
    logging.getLogger("mikromanager").info("Database %s overgenomen als %s", OLD_DB_NAME, DB_NAME)


def init() -> None:
    global _conn
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _carry_over_old_database()
    _conn = sqlite3.connect(DATA_DIR / DB_NAME, check_same_thread=False, isolation_level=None)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA foreign_keys=ON")
    _conn.executescript(SCHEMA)
    # columns added after a table first shipped
    for table, column, decl in (("radio_settings", "freq", "TEXT"), ("radio_settings", "width", "TEXT")):
        if column not in {r[1] for r in _conn.execute(f"PRAGMA table_info({table})")}:
            _conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def q(sql: str, *args) -> list[dict]:
    with _lock:
        return [dict(r) for r in _conn.execute(sql, args).fetchall()]


def q1(sql: str, *args) -> dict | None:
    rows = q(sql, *args)
    return rows[0] if rows else None


def x(sql: str, *args) -> int:
    with _lock:
        cur = _conn.execute(sql, args)
        return cur.lastrowid


# ---- helpers used in several modules ---------------------------------------

def site_settings(site: dict) -> dict:
    s = dict(DEFAULT_SITE_SETTINGS)
    try:
        s.update(json.loads(site.get("settings") or "{}"))
    except ValueError:
        pass
    s.setdefault("prefix", OLD_PREFIX)      # sites from before 0.3 named their router objects tc-…
    return s


def get_site(site_id: int) -> dict | None:
    """Load a site and select its naming prefix for the rest of this request or job."""
    site = q1("SELECT * FROM sites WHERE id=?", site_id)
    if site:
        site["settings"] = site_settings(site)
        use_prefix(site["settings"])
    return site


def site_devices(site_id: int) -> list[dict]:
    return q("SELECT * FROM devices WHERE site_id=? ORDER BY is_controller DESC, role='router' DESC, role='switch' DESC, name", site_id)


def controller(site_id: int) -> dict | None:
    return (q1("SELECT * FROM devices WHERE site_id=? AND is_controller=1", site_id)
            or q1("SELECT * FROM devices WHERE site_id=? AND role='router' ORDER BY id", site_id))


def log(site_id: int | None, message: str, level: str = "info") -> None:
    x("INSERT INTO activity (site_id, ts, level, message) VALUES (?,?,?,?)", site_id, time.time(), level, message)
    x("DELETE FROM activity WHERE id NOT IN (SELECT id FROM activity ORDER BY id DESC LIMIT 2000)")
