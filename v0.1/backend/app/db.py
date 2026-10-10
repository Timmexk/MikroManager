"""Tiny SQLite layer. One connection, guarded by a lock; all queries are short."""
import json
import sqlite3
import threading
import time

from .config import DATA_DIR, DEFAULT_SITE_SETTINGS

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
CREATE TABLE IF NOT EXISTS backups (
  id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  ts REAL NOT NULL, filename TEXT NOT NULL, size INTEGER NOT NULL, sha TEXT NOT NULL,
  ros_version TEXT, trigger TEXT NOT NULL DEFAULT 'manual');
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY, site_id INTEGER, ts REAL NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL);
"""


def init() -> None:
    global _conn
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(DATA_DIR / "tikcontrol.db", check_same_thread=False, isolation_level=None)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA foreign_keys=ON")
    _conn.executescript(SCHEMA)


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
    return s


def get_site(site_id: int) -> dict | None:
    site = q1("SELECT * FROM sites WHERE id=?", site_id)
    if site:
        site["settings"] = site_settings(site)
    return site


def site_devices(site_id: int) -> list[dict]:
    return q("SELECT * FROM devices WHERE site_id=? ORDER BY is_controller DESC, role='router' DESC, role='switch' DESC, name", site_id)


def controller(site_id: int) -> dict | None:
    return (q1("SELECT * FROM devices WHERE site_id=? AND is_controller=1", site_id)
            or q1("SELECT * FROM devices WHERE site_id=? AND role='router' ORDER BY id", site_id))


def log(site_id: int | None, message: str, level: str = "info") -> None:
    x("INSERT INTO activity (site_id, ts, level, message) VALUES (?,?,?,?)", site_id, time.time(), level, message)
    x("DELETE FROM activity WHERE id NOT IN (SELECT id FROM activity ORDER BY id DESC LIMIT 2000)")
