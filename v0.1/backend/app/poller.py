"""Background poller: keeps an in-memory snapshot per device and a 24h metric history."""
import asyncio
import re
import time

from . import db
from .config import POLL_INTERVAL
from .ros import Ros, RosError, truthy

STATE: dict[int, dict] = {}

# Fetched on every poll (cheap, needed fresh).
FAST = {
    "health": "/system/health",
    "hosts": "/interface/bridge/host",
    "wifi_reg": "/interface/wifi/registration-table",
}
FAST_ROUTER = {
    "leases": "/ip/dhcp-server/lease",
    "arp": "/ip/arp",
}
# Fetched every SLOW_EVERY polls, or right after an action.
SLOW = {
    "routerboard": "/system/routerboard",
    "update": "/system/package/update",
    "packages": "/system/package",
    "ethernet": "/interface/ethernet",
    "bridges": "/interface/bridge",
    "bridge_ports": "/interface/bridge/port",
    "wifi_ifaces": "/interface/wifi",
    "wifi_radios": "/interface/wifi/radio",
    "wifi_cap": "/interface/wifi/cap",
    "remote_caps": "/interface/wifi/capsman/remote-cap",
    "wifi_acl": "/interface/wifi/access-list",
    "poe": "/interface/ethernet/poe",
}
SLOW_ROUTER = {"routes": "/ip/route"}
SLOW_EVERY = 4
RECHECK_UNSUPPORTED_EVERY = 40

_UPTIME = re.compile(r"(\d+)([wdhms])")
_UNIT = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}


def uptime_seconds(s: str | None) -> int:
    return sum(int(n) * _UNIT[u] for n, u in _UPTIME.findall(s or ""))


def snap(dev_id: int) -> dict:
    return STATE.setdefault(dev_id, {"online": None, "error": None, "last_seen": None, "polls": 0,
                                     "unsupported": set(), "want_slow": True, "rates": {}, "counters": {}})


def request_refresh(dev_id: int) -> None:
    snap(dev_id)["want_slow"] = True


async def _gather(ros: Ros, s: dict, paths: dict[str, str]) -> None:
    """Fetch several menus in parallel. A menu the device lacks (no wifi package,
    no PoE ...) is remembered so we don't keep asking for it."""
    todo = {k: p for k, p in paths.items() if p not in s["unsupported"]}
    results = await asyncio.gather(*(ros.get(p) for p in todo.values()), return_exceptions=True)
    for (key, path), res in zip(todo.items(), results):
        if isinstance(res, RosError):
            if not res.unreachable and res.status != 401:
                s["unsupported"].add(path)
            s[key] = None
        elif isinstance(res, Exception):
            s[key] = None
        else:
            s[key] = res


async def _monitor(ros: Ros, s: dict, key: str, path: str, names: list[str]) -> None:
    if not names or path in s["unsupported"]:
        s[key] = {}
        return
    try:
        res = await ros.cmd(path, {"numbers": ",".join(names), "once": ""}, timeout=10)
        rows = res if isinstance(res, list) else [res]
        s[key] = {r.get("name", names[i] if i < len(names) else ""): r for i, r in enumerate(rows) if isinstance(r, dict)}
    except RosError as e:
        if not e.unreachable:
            s["unsupported"].add(path)
        s[key] = {}


def _wan_interface(s: dict) -> str | None:
    for r in s.get("routes") or []:
        if r.get("dst-address") == "0.0.0.0/0" and truthy(r.get("active", "false")):
            gw = r.get("immediate-gw") or r.get("gateway") or ""
            return gw.split("%", 1)[1] if "%" in gw else (gw if not re.match(r"^[\d.]+$", gw) else None)
    return None


async def poll_device(dev: dict, slow: bool = False) -> None:
    s = snap(dev["id"])
    ros = Ros.for_device(dev)
    was_online = s["online"]
    now = time.time()
    try:
        res, ident, ifaces = await asyncio.gather(
            ros.get("/system/resource"), ros.get("/system/identity"), ros.get("/interface"))
    except RosError as e:
        s.update(online=False, error=str(e))
        if was_online:
            db.log(dev["site_id"], f"{dev['name']} is offline ({e})", "warn")
        return

    if was_online is False:
        db.log(dev["site_id"], f"{dev['name']} is weer online", "ok")
    old_version = (s.get("resource") or {}).get("version")
    if old_version and res.get("version") != old_version:
        db.log(dev["site_id"], f"{dev['name']}: RouterOS {old_version.split()[0]} → {res.get('version', '').split()[0]}", "ok")
    s.update(online=True, error=None, last_seen=now, resource=res,
             identity=(ident or {}).get("name"), interfaces=ifaces or [])

    # Per-interface throughput from byte counter deltas.
    rates, counters = {}, {}
    for i in ifaces or []:
        try:
            cur = (int(i.get("rx-byte", 0)), int(i.get("tx-byte", 0)))
        except ValueError:
            continue
        counters[i["name"]] = (now, *cur)
        prev = s["counters"].get(i["name"])
        if prev and now > prev[0] and cur[0] >= prev[1] and cur[1] >= prev[2]:
            dt = now - prev[0]
            rates[i["name"]] = ((cur[0] - prev[1]) * 8 / dt, (cur[1] - prev[2]) * 8 / dt)
    s["counters"], s["rates"] = counters, rates

    if s["polls"] % RECHECK_UNSUPPORTED_EVERY == 0:
        s["unsupported"] = set()
    is_router = dev["role"] == "router" or dev["is_controller"]
    slow = slow or s.pop("want_slow", False)
    s["want_slow"] = False

    paths = dict(FAST)
    if is_router:
        paths.update(FAST_ROUTER)
    if slow:
        paths.update(SLOW)
        if is_router:
            paths.update(SLOW_ROUTER)
    await _gather(ros, s, paths)

    if slow:
        eth = [e["name"] for e in s.get("ethernet") or [] if not truthy(e.get("disabled", "false"))]
        poe = [p["name"] for p in s.get("poe") or []]
        masters = [w["name"] for w in s.get("wifi_ifaces") or []
                   if not w.get("master-interface") and not truthy(w.get("disabled", "false"))]
        await asyncio.gather(
            _monitor(ros, s, "eth_mon", "/interface/ethernet/monitor", eth),
            _monitor(ros, s, "poe_mon", "/interface/ethernet/poe/monitor", poe),
            _monitor(ros, s, "wifi_mon", "/interface/wifi/monitor", masters))
        if is_router:
            s["wan"] = _wan_interface(s)

    s["polls"] += 1
    total = float(res.get("total-memory", 0) or 0)
    free = float(res.get("free-memory", 0) or 0)
    wan = s["rates"].get(s.get("wan") or "", (None, None))
    db.x("INSERT INTO metrics (device_id, ts, cpu, mem, clients, rx_bps, tx_bps) VALUES (?,?,?,?,?,?,?)",
         dev["id"], now, float(res.get("cpu-load", 0) or 0), round(100 * (1 - free / total), 1) if total else None,
         len(s.get("wifi_reg") or []), wan[0], wan[1])


async def _safe_poll(dev: dict, slow: bool) -> None:
    try:
        await poll_device(dev, slow)
    except Exception as e:  # a bug in one device's parsing must not stop the loop
        s = snap(dev["id"])
        s.update(online=False, error=f"Interne fout: {e}")


async def refresh_device(dev: dict) -> None:
    """Poll one device right now with the slow set (after config changes)."""
    await _safe_poll(dev, True)


async def run() -> None:
    from . import maint  # local import: maint needs STATE
    n = 0
    while True:
        t0 = time.time()
        devs = db.q("SELECT * FROM devices")
        for gone in set(STATE) - {d["id"] for d in devs}:
            STATE.pop(gone, None)
        await asyncio.gather(*(_safe_poll(d, n % SLOW_EVERY == 0) for d in devs))
        if n % 40 == 0:
            db.x("DELETE FROM metrics WHERE ts < ?", time.time() - 86400)
        try:
            await maint.scheduled_backups()
        except Exception as e:
            db.log(None, f"Geplande back-up mislukt: {e}", "error")
        n += 1
        await asyncio.sleep(max(1.0, POLL_INTERVAL - (time.time() - t0)))


def history(device_id: int, hours: float = 6, points: int = 120) -> list[dict]:
    """Downsampled metric history for charts (bucket averages)."""
    since = time.time() - hours * 3600
    bucket = max(POLL_INTERVAL, hours * 3600 / points)
    return db.q(
        "SELECT CAST(ts / ? AS INTEGER) * ? AS ts, AVG(cpu) cpu, AVG(mem) mem, MAX(clients) clients, "
        "AVG(rx_bps) rx, AVG(tx_bps) tx FROM metrics WHERE device_id=? AND ts>=? GROUP BY 1 ORDER BY 1",
        bucket, bucket, device_id, since)
