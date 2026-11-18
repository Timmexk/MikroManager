"""Live view: fast, in-memory measurements while somebody is watching.

The normal poller runs every 15 s and stores history in the database. That is fine for "the last 6
hours", but a chart that moves every 15 s (or shows 3-minute averages) feels like the past. While a
browser is asking for live data, this loop reads interface counters and CPU every LIVE_INTERVAL seconds
from the devices being watched, and pings the internet via the router every few ticks. The samples
live in a ring buffer in memory only. Nobody watching for LIVE_IDLE_AFTER seconds: the loop goes idle.
"""
import asyncio
import time
from collections import deque

from . import db
from .config import LIVE_IDLE_AFTER, LIVE_INTERVAL, LIVE_PING_EVERY, LIVE_WINDOW
from .poller import STATE, WAN_PING_TARGET, _ping
from .ros import Ros, RosError

_POINTS = max(10, int(LIVE_WINDOW / LIVE_INTERVAL) + 2)
_watch: dict[int, float] = {}           # device id -> watched until (timestamp)
_buf: dict[int, deque] = {}             # device id -> deque of samples
_lat: dict[int, deque] = {}             # router id -> deque of {ts, rtt, loss}
_counters: dict[int, dict] = {}         # device id -> {iface: (ts, rx, tx)}


def watch(dev_ids: list[int]) -> None:
    until = time.time() + LIVE_IDLE_AFTER
    for i in dev_ids:
        _watch[i] = until


def samples(dev_id: int, since: float = 0) -> list[dict]:
    return [p for p in _buf.get(dev_id, ()) if p["ts"] > since]


def pings(dev_id: int, since: float = 0) -> list[dict]:
    return [p for p in _lat.get(dev_id, ()) if p["ts"] > since]


async def _sample(dev: dict, tick: int) -> None:
    ros = Ros.for_device(dev)
    s = STATE.get(dev["id"]) or {}
    if s.get("online") is False:
        return
    try:
        res, ifaces = await asyncio.gather(ros.get("/system/resource", timeout=4), ros.get("/interface", timeout=4))
    except RosError:
        return
    now = time.time()
    prev, cur, rates = _counters.get(dev["id"], {}), {}, {}
    for i in ifaces or []:
        try:
            rx, tx = int(i.get("rx-byte", 0)), int(i.get("tx-byte", 0))
        except ValueError:
            continue
        cur[i["name"]] = (now, rx, tx)
        p = prev.get(i["name"])
        if p and now > p[0] and rx >= p[1] and tx >= p[2]:
            dt = now - p[0]
            rates[i["name"]] = ((rx - p[1]) * 8 / dt, (tx - p[2]) * 8 / dt)
    _counters[dev["id"]] = cur
    if not rates:
        return
    total = float(res.get("total-memory", 0) or 0)
    free = float(res.get("free-memory", 0) or 0)
    point = {"ts": round(now, 2), "cpu": float(res.get("cpu-load", 0) or 0),
             "mem": round(100 * (1 - free / total), 1) if total else None, "rates": rates}
    _buf.setdefault(dev["id"], deque(maxlen=_POINTS)).append(point)
    # fresher numbers for everything else that reads STATE (port map, interface table)
    s["rates"], s["live_ts"] = rates, now

    if (dev["role"] == "router" or dev["is_controller"]) and tick % LIVE_PING_EVERY == 0:
        r = await _ping(ros, WAN_PING_TARGET, count=2)
        if r:
            _lat.setdefault(dev["id"], deque(maxlen=max(10, _POINTS // LIVE_PING_EVERY + 2))).append(
                {"ts": round(now, 2), "rtt": r["avg"], "loss": r["loss"], "wan": s.get("wan")})


async def run() -> None:
    tick = 0
    while True:
        t0 = time.time()
        watched = [i for i, until in _watch.items() if until > t0]
        for gone in [i for i in _watch if i not in watched]:
            _watch.pop(gone, None)
            _counters.pop(gone, None)      # restart cleanly next time instead of one huge delta
        if watched:
            devs = [d for d in db.q("SELECT * FROM devices") if d["id"] in watched]
            await asyncio.gather(*(_sample(d, tick) for d in devs), return_exceptions=True)
            tick += 1
        await asyncio.sleep(max(0.2, LIVE_INTERVAL - (time.time() - t0)))
