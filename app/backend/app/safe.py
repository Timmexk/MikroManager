"""Safe mode for changes that can lock you out (port off, VLAN/bridge changes, speed, MTU, PoE).

RouterOS's own safe mode only exists inside an interactive console session, so MikroManager
builds the same thing with a dead man's switch on the device itself:

  1. arm:     add /system/scheduler "mm-terugdraai-<token>" that runs once, SAFE_SECS from now,
              with a script that undoes every step and then removes itself
  2. apply:   run the steps over REST
  3. confirm: check that the device still answers; if so, remove the scheduler

If the device is no longer reachable after step 2, nothing else is needed: the router runs the
script on its own and the old settings come back. A REST error halfway through step 2 is undone
straight away by the app.
"""
import asyncio
import datetime as dt
import secrets
from dataclasses import dataclass, field

from . import db
from .config import SAFE_CHECK_SECS, SAFE_SECS
from .ros import Ros, RosError

SCHED_PREFIX = "mm-terugdraai-"
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


@dataclass
class Op:
    """One REST step plus everything needed to undo it, both over REST and as a console command."""
    path: str                       # REST menu, e.g. /interface/ethernet
    action: str                     # set | add | remove
    data: dict = field(default_factory=dict)
    ident: str | None = None        # .id for set/remove
    old: dict = field(default_factory=dict)     # set: old values of the changed keys; remove: the whole record
    find: dict | None = None        # add: how to find the new item again (for the undo script)
    risky: bool = True
    label: str = ""

    def menu(self) -> str:
        return self.path.strip("/").replace("/", " ")


def q(v) -> str:
    s = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
    return f'"{s}"'


READONLY = {".id", "dynamic", "running", "slave", "inactive", "invalid", "default-name", "actual-mtu", "mac-address",
            "orig-mac-address", "last-link-up-time", "last-link-down-time", "link-downs", "rx-byte", "tx-byte",
            "rx-packet", "tx-packet", "fp-rx-byte", "fp-tx-byte", "type", "builtin", "hw", "status", "nextid",
            "debug-info", "trusted", "port-number", "hw-offload", "hw-offload-group", "role", "edge-port",
            "point-to-point-port", "external-fdb-status", "current-tagged", "current-untagged", "l2mtu", "max-l2mtu",
            "poe-out-status", "poe-out-voltage", "poe-out-current", "poe-out-power", "disabled"}


def _cli(v) -> str:
    return {"true": "yes", "false": "no"}.get(str(v), str(v))


def undo_command(op: Op) -> str:
    m = f"/{op.menu()}"
    if op.action == "set":
        pairs = " ".join(f"{k}={q(_cli(v))}" for k, v in op.old.items())
        return f"{m} set {op.ident} {pairs}" if pairs else ""
    if op.action == "add":
        where = " ".join(f"{k}={q(v)}" for k, v in (op.find or {}).items())
        return f"{m} remove [find {where}]"
    if op.action == "remove":
        keep = {k: v for k, v in op.old.items() if k not in READONLY and v not in ("", None)}
        if op.old.get("disabled") in ("true", "yes"):
            keep["disabled"] = "yes"
        return f"{m} add " + " ".join(f"{k}={q(_cli(v))}" for k, v in keep.items())
    return ""


def undo_script(ops: list[Op], sched_name: str) -> str:
    lines = [c for c in (undo_command(o) for o in reversed(ops)) if c]
    lines.append(f"/system scheduler remove [find name={q(sched_name)}]")
    return "\n".join(f":do {{ {l} }} on-error={{}}" if not l.startswith("/system scheduler") else l for l in lines)


def _fire_time(clock: dict, secs: int) -> tuple[str, str]:
    """Device clock + secs, in the date format the device itself uses (7.10+ ISO, older mmm/dd/yyyy)."""
    date, time = clock.get("date", ""), clock.get("time", "00:00:00")
    iso = len(date) == 10 and date[4] == "-"
    if iso:
        d = dt.datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M:%S")
    else:
        mon, day, year = date.split("/")
        d = dt.datetime(int(year), _MONTHS.index(mon.lower()[:3]) + 1, int(day), *map(int, time.split(":")))
    t = d + dt.timedelta(seconds=secs)
    new_date = t.strftime("%Y-%m-%d") if iso else f"{_MONTHS[t.month - 1]}/{t.day:02d}/{t.year}"
    return new_date, t.strftime("%H:%M:%S")


async def _arm(ros: Ros, ops: list[Op]) -> str:
    name = SCHED_PREFIX + secrets.token_hex(3)
    clock = await ros.get("/system/clock")
    date, time = _fire_time(clock if isinstance(clock, dict) else {}, SAFE_SECS)
    await ros.add("/system/scheduler", {"name": name, "start-date": date, "start-time": time, "interval": "0s",
                                        "on-event": undo_script(ops, name),
                                        "comment": "MikroManager veilige modus: draait een wijziging terug"})
    return name


async def _disarm(ros: Ros, name: str) -> None:
    rows = await ros.get("/system/scheduler", name=name)
    for r in rows or []:
        await ros.remove("/system/scheduler", r[".id"])


async def _undo_now(ros: Ros, done: list[tuple[Op, dict | None]]) -> None:
    for op, created in reversed(done):
        try:
            if op.action == "set" and op.old:
                await ros.set(op.path, op.ident, op.old)
            elif op.action == "add" and created and created.get(".id"):
                await ros.remove(op.path, created[".id"])
            elif op.action == "remove":
                keep = {k: v for k, v in op.old.items() if k not in READONLY}
                await ros.add(op.path, keep)
        except RosError:
            pass


async def _still_reachable(devs: list[dict]) -> list[dict]:
    """Devices from `devs` that do NOT answer twice in a row within SAFE_CHECK_SECS."""
    async def one(dev: dict) -> bool:
        ros = Ros.for_device(dev)
        end = asyncio.get_event_loop().time() + SAFE_CHECK_SECS
        ok_in_row = 0
        while asyncio.get_event_loop().time() < end:
            try:
                await ros._req("GET", "/system/resource", timeout=3)
                ok_in_row += 1
                if ok_in_row >= 2:
                    return True
            except RosError:
                ok_in_row = 0
            await asyncio.sleep(1)
        return False
    await asyncio.sleep(1.5)            # give link, STP and PoE a moment
    ok = await asyncio.gather(*(one(d) for d in devs))
    return [d for d, good in zip(devs, ok) if not good]


def _watch_list(dev: dict) -> list[dict]:
    """The changed device plus every other device of the site that is online right now:
    switching off a port or PoE can cut off an access point further down the line."""
    from .poller import STATE
    others = [d for d in db.site_devices(dev["site_id"]) if d["id"] != dev["id"] and (STATE.get(d["id"]) or {}).get("online")]
    return [dev] + others


async def apply(dev: dict, ops: list[Op], what: str) -> dict:
    """Apply ops; risky ones are guarded. Returns {"applied": bool, "reverting_in": secs|None}."""
    ops = [o for o in ops if o.action != "set" or o.data]
    if not ops:
        return {"applied": True, "reverting_in": None, "steps": 0}
    ros = Ros.for_device(dev)
    risky = any(o.risky for o in ops)
    watch = _watch_list(dev) if risky else []
    sched = await _arm(ros, ops) if risky else None
    done: list[tuple[Op, dict | None]] = []
    try:
        for op in ops:
            if op.action == "set":
                await ros.set(op.path, op.ident, op.data)
                done.append((op, None))
            elif op.action == "add":
                done.append((op, await ros.add(op.path, op.data)))
            elif op.action == "remove":
                await ros.remove(op.path, op.ident)
                done.append((op, None))
    except RosError as e:
        if e.unreachable and risky:
            db.log(dev["site_id"], f"{dev['name']}: na '{what}' niet meer bereikbaar; het apparaat draait het over "
                                   f"{SAFE_SECS} s zelf terug", "warn")
            return {"applied": False, "reverting_in": SAFE_SECS, "steps": len(ops)}
        await _undo_now(ros, done)
        if sched:
            try:
                await _disarm(ros, sched)
            except RosError:
                pass
        raise RosError(f"{e} (niets gewijzigd: eerdere stappen zijn teruggedraaid)", e.status)

    lost = await _still_reachable(watch) if risky else []
    if lost:
        names = ", ".join(d["name"] for d in lost)
        db.log(dev["site_id"], f"{dev['name']}: na '{what}' niet meer bereikbaar: {names}. {dev['name']} draait de "
                               f"wijziging over {SAFE_SECS} s zelf terug", "warn")
        if dev not in lost:
            # the device itself still answers: undo right away instead of waiting for the scheduler
            await _undo_now(ros, done)
            try:
                await _disarm(ros, sched)
            except RosError:
                pass
            return {"applied": False, "reverting_in": 0, "lost": [d["name"] for d in lost], "steps": len(ops)}
        return {"applied": False, "reverting_in": SAFE_SECS, "lost": [d["name"] for d in lost], "steps": len(ops)}
    if sched:
        await _disarm(ros, sched)
    db.log(dev["site_id"], f"{dev['name']}: {what}")
    return {"applied": True, "reverting_in": None, "steps": len(ops)}
