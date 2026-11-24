"""Maintenance: RouterOS / firmware updates and configuration back-ups with diff."""
import asyncio
import difflib
import hashlib
import re
import time
from datetime import datetime

from . import db
from .config import DATA_DIR
from .poller import STATE, refresh_device, snap
from .ros import Ros, RosError

JOBS: dict[int, dict] = {}     # site_id -> running/last "update everything" job
_TIMESTAMP = re.compile(r"^# (\d{4}-\d\d-\d\d|[a-z]{3}/\d\d/\d{4}) \d\d:\d\d:\d\d by RouterOS.*$", re.M)
ROLE_ORDER = {"ap": 0, "switch": 1, "router": 2}  # leaf devices first, the router last


# ---- updates ---------------------------------------------------------------

def update_info(dev: dict) -> dict:
    s = STATE.get(dev["id"]) or {}
    up = s.get("update") or {}
    rb = s.get("routerboard") or {}
    installed = up.get("installed-version") or (s.get("resource") or {}).get("version", "").split(" ")[0] or None
    latest = up.get("latest-version")
    fw_cur, fw_new = rb.get("current-firmware"), rb.get("upgrade-firmware")
    return {"id": dev["id"], "name": dev["name"], "role": dev["role"], "online": s.get("online"),
            "board": (s.get("resource") or {}).get("board-name"), "channel": up.get("channel"),
            "installed": installed, "latest": latest, "available": bool(latest and installed and latest != installed),
            "firmware": fw_cur, "firmware_target": fw_new,
            "firmware_pending": bool(fw_cur and fw_new and fw_cur != fw_new),
            "checked": s.get("update_checked"), "busy": s.get("busy")}


async def check_update(dev: dict) -> dict:
    ros = Ros.for_device(dev)
    await ros.cmd("/system/package/update/check-for-updates", {}, timeout=40)
    s = snap(dev["id"])
    s["update"] = await ros.get("/system/package/update")
    s["update_checked"] = time.time()
    return update_info(dev)


async def start_upgrade(dev: dict) -> None:
    """Download + install + reboot. The router drops the connection while it
    reboots, so a timeout here is expected and not an error."""
    ros = Ros.for_device(dev)
    snap(dev["id"])["busy"] = "RouterOS wordt bijgewerkt"
    db.log(dev["site_id"], f"{dev['name']}: RouterOS-update gestart")
    try:
        await ros.cmd("/system/package/update/install", {}, timeout=20)
    except RosError as e:
        if not e.unreachable:
            snap(dev["id"])["busy"] = None
            raise


async def upgrade_firmware(dev: dict) -> None:
    ros = Ros.for_device(dev)
    snap(dev["id"])["busy"] = "Firmware wordt bijgewerkt"
    db.log(dev["site_id"], f"{dev['name']}: RouterBOOT-firmware bijwerken en herstarten")
    try:
        await ros.cmd("/system/routerboard/upgrade", {}, timeout=20)
        await asyncio.sleep(2)
        await reboot(dev, log=False)
    except RosError:
        snap(dev["id"])["busy"] = None
        raise


async def reboot(dev: dict, log: bool = True) -> None:
    if log:
        db.log(dev["site_id"], f"{dev['name']}: herstart")
    try:
        await Ros.for_device(dev).cmd("/system/reboot", {}, timeout=8)
    except RosError as e:
        if not e.unreachable:
            raise


async def wait_for_version(dev: dict, target: str, timeout: float = 600) -> bool:
    deadline = time.time() + timeout
    ros = Ros.for_device(dev)
    await asyncio.sleep(5)
    while time.time() < deadline:
        try:
            res = await ros.get("/system/resource", timeout=5)
            if res.get("version", "").split(" ")[0] == target:
                return True
        except RosError:
            pass
        await asyncio.sleep(5)
    return False


async def _watch_single(dev: dict, target: str | None) -> None:
    try:
        ok = await wait_for_version(dev, target) if target else True
        if target and not ok:
            db.log(dev["site_id"], f"{dev['name']}: na de update niet teruggekomen op {target}", "error")
    finally:
        snap(dev["id"])["busy"] = None
        await refresh_device(dev)


def watch_upgrade(dev: dict, target: str | None) -> None:
    asyncio.create_task(_watch_single(dev, target))


# ---- update queue ------------------------------------------------------------
# A batch of devices updated one by one, in an order that never cuts off a device that still has to be done:
# access points first, then switches (deepest in the network first), the router last. Each device must come back
# on the new version before the next one starts; a failure stops the rest of the batch. A batch can wait for a
# time (for instance tonight at 03:00). The queue lives in the database, so a restart of MikroManager resumes it.

QUEUE_TICK = float(__import__("os").environ.get("MIKROMANAGER_QUEUE_TICK", "5"))
STATUS_LABEL = {"wacht": "wacht", "bezig": "bezig", "klaar": "klaar", "mislukt": "mislukt",
                "overgeslagen": "overgeslagen", "geannuleerd": "geannuleerd"}


def _depth(site_id: int) -> dict[int, int]:
    from . import clients
    links = clients.topology(site_id)
    out = {}
    for dev_id in links:
        d, cur, seen = 0, dev_id, set()
        while cur in links and cur not in seen:
            seen.add(cur)
            cur = links[cur]["parent"]
            d += 1
        out[dev_id] = d
    return out


def queue_devices(site_id: int, dev_ids: list[int], at: float | None, firmware: bool) -> str:
    if db.q1("SELECT 1 FROM update_queue WHERE site_id=? AND status IN ('wacht','bezig')", site_id):
        raise ValueError("Er staat al een update-ronde in de wachtrij")
    devs = [d for d in db.site_devices(site_id) if d["id"] in set(dev_ids)]
    if not devs:
        raise ValueError("Kies minstens één apparaat")
    depth = _depth(site_id)
    devs.sort(key=lambda d: (ROLE_ORDER.get(d["role"], 1), -depth.get(d["id"], 0), d["name"]))
    batch = f"{time.time():.6f}"
    for n, d in enumerate(devs):
        info = update_info(d)
        db.x("INSERT INTO update_queue (site_id, batch, device_id, position, firmware, scheduled_at, from_ver, to_ver) "
             "VALUES (?,?,?,?,?,?,?,?)", site_id, batch, d["id"], n, int(firmware), at, info["installed"], info["latest"])
    when = datetime.fromtimestamp(at).strftime("%d-%m %H:%M") if at else "nu"
    db.log(site_id, f"Update-ronde gepland ({when}): " + ", ".join(d["name"] for d in devs))
    return batch


def cancel_queue(site_id: int) -> int:
    n = len(db.q("SELECT id FROM update_queue WHERE site_id=? AND status='wacht'", site_id))
    db.x("UPDATE update_queue SET status='geannuleerd', finished=? WHERE site_id=? AND status='wacht'", time.time(), site_id)
    if n:
        db.log(site_id, f"Update-ronde geannuleerd ({n} apparaat/apparaten niet bijgewerkt)", "warn")
    return n


def job_view(site_id: int) -> dict | None:
    """The latest batch, in the shape the Maintenance page shows."""
    last = db.q1("SELECT batch FROM update_queue WHERE site_id=? ORDER BY id DESC LIMIT 1", site_id)
    if not last:
        return None
    rows = db.q("SELECT q.*, d.name FROM update_queue q LEFT JOIN devices d ON d.id=q.device_id "
                "WHERE q.site_id=? AND q.batch=? ORDER BY position", site_id, last["batch"])
    running = any(r["status"] in ("wacht", "bezig") for r in rows)
    failed = next((r for r in rows if r["status"] == "mislukt"), None)
    return {"running": running, "batch": last["batch"], "total": len(rows),
            "scheduled_at": rows[0]["scheduled_at"] if rows else None,
            "waiting_for_time": bool(rows and rows[0]["scheduled_at"] and rows[0]["scheduled_at"] > time.time()
                                     and all(r["status"] == "wacht" for r in rows)),
            "error": f"Gestopt bij {failed['name']}" if failed else None,
            "steps": [{"device": r["name"], "device_id": r["device_id"], "from": r["from_ver"], "to": r["to_ver"],
                       "status": r["status"], "error": r["error"], "firmware": bool(r["firmware"]),
                       "started": r["started"], "finished": r["finished"]} for r in rows]}


async def _run_one(row: dict) -> None:
    dev = db.q1("SELECT * FROM devices WHERE id=?", row["device_id"])
    now = time.time()
    if not dev:
        db.x("UPDATE update_queue SET status='overgeslagen', finished=?, error=? WHERE id=?", now, "apparaat verwijderd", row["id"])
        return
    db.x("UPDATE update_queue SET status='bezig', started=? WHERE id=?", now, row["id"])
    ok, error = True, None
    try:
        info = update_info(dev)
        if info["available"]:
            await start_upgrade(dev)
            ok = await wait_for_version(dev, info["latest"])
            if not ok:
                error = f"niet teruggekomen op {info['latest']}"
        snap(dev["id"])["busy"] = None
        await refresh_device(dev)
        if ok and row["firmware"]:
            await refresh_device(dev)
            if update_info(dev)["firmware_pending"]:
                await upgrade_firmware(dev)
                ok = await wait_for_version(dev, update_info(dev)["installed"] or info["latest"])
                if not ok:
                    error = "niet teruggekomen na de firmware-update"
    except RosError as e:
        ok, error = False, str(e)
    finally:
        snap(dev["id"])["busy"] = None
        try:
            await refresh_device(dev)
        except Exception:
            pass
    db.x("UPDATE update_queue SET status=?, finished=?, error=? WHERE id=?", "klaar" if ok else "mislukt", time.time(), error, row["id"])
    if not ok:
        # never continue to the devices above it (the router last) when one below failed
        db.x("UPDATE update_queue SET status='overgeslagen', finished=? WHERE site_id=? AND batch=? AND status='wacht'",
             time.time(), row["site_id"], row["batch"])
        db.log(row["site_id"], f"Update-ronde gestopt bij {dev['name']}: {error}", "error")
    elif not db.q1("SELECT 1 FROM update_queue WHERE site_id=? AND batch=? AND status='wacht'", row["site_id"], row["batch"]):
        n = len(db.q("SELECT id FROM update_queue WHERE batch=? AND site_id=? AND status='klaar'", row["batch"], row["site_id"]))
        db.log(row["site_id"], f"Update-ronde klaar: {n} apparaat/apparaten bijgewerkt", "ok")


_active: set[int] = set()


async def queue_tick() -> None:
    now = time.time()
    for row in db.q("SELECT * FROM update_queue WHERE status='wacht' AND (scheduled_at IS NULL OR scheduled_at <= ?) "
                    "ORDER BY site_id, position", now):
        if row["site_id"] in _active:
            continue
        if db.q1("SELECT 1 FROM update_queue WHERE site_id=? AND status='bezig'", row["site_id"]):
            continue
        _active.add(row["site_id"])

        async def go(r=row):
            try:
                await _run_one(r)
            finally:
                _active.discard(r["site_id"])
        asyncio.create_task(go())


async def queue_runner() -> None:
    # a batch that was running when MikroManager stopped: that device is checked again from the start
    db.x("UPDATE update_queue SET status='wacht' WHERE status='bezig'")
    while True:
        try:
            await queue_tick()
        except Exception:      # keep the runner alive
            import logging
            logging.getLogger("mikromanager").exception("update-wachtrij")
        await asyncio.sleep(QUEUE_TICK)


def start_site_upgrade(site_id: int) -> dict:
    devs = [d for d in db.site_devices(site_id) if update_info(d)["available"] and update_info(d)["online"]]
    if not devs:
        raise ValueError("Geen apparaten met een beschikbare update")
    queue_devices(site_id, [d["id"] for d in devs], None, False)
    asyncio.create_task(queue_tick())
    return job_view(site_id)


# ---- backups ---------------------------------------------------------------

async def fetch_export(ros: Ros, sensitive: bool) -> str:
    """Get `/export` as text. Preferred: `:execute ... as-string`. Fallback for
    older 7.x: export to a file and read it back through /file."""
    script = "/export show-sensitive" if sensitive else "/export"
    try:
        res = await ros.cmd("/execute", {"script": script, "as-string": ""}, timeout=90)
        text = res.get("ret") if isinstance(res, dict) else None
        if text and "/" in text:
            return text
    except RosError as e:
        if e.unreachable or e.status == 401:
            raise
    name = "mikromanager-export"
    args = {"file": name}
    if sensitive:
        args["show-sensitive"] = ""
    await ros.cmd("/export", args, timeout=90)
    await asyncio.sleep(2)
    files = await ros.get("/file", name=f"{name}.rsc")
    if not files:
        raise RosError("Export-bestand niet gevonden op de router")
    text = files[0].get("contents")
    await ros.remove("/file", files[0][".id"])
    if not text:
        raise RosError("Export is te groot om via REST te lezen op deze RouterOS-versie")
    return text


def _fingerprint(text: str) -> str:
    return hashlib.sha256(_TIMESTAMP.sub("", text).encode()).hexdigest()


def _path(row: dict):
    return DATA_DIR / "backups" / str(row["device_id"]) / row["filename"]


async def backup_device(dev: dict, trigger: str = "manual", sensitive: bool | None = None, keep: int | None = None) -> dict:
    site = db.get_site(dev["site_id"])
    st = site["settings"]
    text = await fetch_export(Ros.for_device(dev), st["backup_sensitive"] if sensitive is None else sensitive)
    sha = _fingerprint(text)
    last = db.q1("SELECT * FROM backups WHERE device_id=? ORDER BY ts DESC LIMIT 1", dev["id"])
    if last and last["sha"] == sha:
        return {"changed": False, "id": last["id"]}
    now = time.time()
    fname = datetime.fromtimestamp(now).strftime("%Y%m%d-%H%M%S") + ".rsc"
    folder = DATA_DIR / "backups" / str(dev["id"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / fname).write_text(text)
    version = ((STATE.get(dev["id"]) or {}).get("resource") or {}).get("version", "").split(" ")[0]
    bid = db.x("INSERT INTO backups (device_id, ts, filename, size, sha, ros_version, trigger) VALUES (?,?,?,?,?,?,?)",
               dev["id"], now, fname, len(text), sha, version, trigger)
    for old in db.q("SELECT * FROM backups WHERE device_id=? ORDER BY ts DESC LIMIT -1 OFFSET ?",
                    dev["id"], keep if keep is not None else st["backup_keep"]):
        delete_backup(old)
    return {"changed": True, "id": bid}


def delete_backup(row: dict) -> None:
    _path(row).unlink(missing_ok=True)
    db.x("DELETE FROM backups WHERE id=?", row["id"])


def read_backup(row: dict) -> str:
    p = _path(row)
    return p.read_text() if p.exists() else ""


def diff_backups(old: dict, new: dict) -> dict:
    a = _TIMESTAMP.sub("", read_backup(old)).splitlines()
    b = _TIMESTAMP.sub("", read_backup(new)).splitlines()
    lines, added, removed = [], 0, 0
    for line in difflib.unified_diff(a, b, lineterm="", n=2):
        if line.startswith(("---", "+++")):
            continue
        kind = "hunk" if line.startswith("@@") else "add" if line.startswith("+") else "del" if line.startswith("-") else "ctx"
        added += kind == "add"
        removed += kind == "del"
        lines.append({"kind": kind, "text": line[1:] if kind in ("add", "del", "ctx") else line})
    return {"lines": lines, "added": added, "removed": removed}


async def scheduled_backups() -> None:
    """Called from the poll loop; runs each site's nightly backup once per day."""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    for row in db.q("SELECT * FROM sites"):
        st = db.site_settings(row)
        if not st["backup_enabled"] or now.hour != int(st["backup_hour"]) or row.get("last_backup_day") == today:
            continue
        db.x("UPDATE sites SET last_backup_day=? WHERE id=?", today, row["id"])
        changed = failed = 0
        for dev in db.site_devices(row["id"]):
            try:
                changed += (await backup_device(dev, "schedule"))["changed"]
            except RosError as e:
                failed += 1
                db.log(row["id"], f"Back-up van {dev['name']} mislukt: {e}", "error")
        if changed or failed:
            db.log(row["id"], f"Nachtelijke back-up: {changed} gewijzigde configuratie(s) opgeslagen"
                   + (f", {failed} mislukt" if failed else ""), "error" if failed else "info")

