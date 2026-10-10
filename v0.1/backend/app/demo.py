"""Demo mode (TIKCONTROL_DEMO=1): simulated routers in-process plus a seeded site.

Lets you click through the whole UI before pointing TikControl at real hardware.
"""
import asyncio
import math
import os
import random
import shutil
import sys
import time
from pathlib import Path

from . import db, maint, networks, poller, security, wifi
from .config import DATA_DIR
from .ros import Ros, RosError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mock import mock_ros  # noqa: E402

SEED = os.environ.get("TIKCONTROL_DEMO_SEED", "1") != "0"
_server: mock_ros.MockServer | None = None


async def _wait_ready() -> None:
    for d in _server.world.devs.values():
        ros = Ros("127.0.0.1", d.port, "http", mock_ros.USER, mock_ros.PASSWORD)
        for _ in range(50):
            try:
                await ros.get("/system/identity")
                break
            except RosError:
                await asyncio.sleep(0.1)


def _add_device(site_id: int, key: str, role: str, controller: bool = False) -> dict:
    d = _server.world.devs[key]
    did = db.x(
        "INSERT INTO devices (site_id, name, host, port, scheme, verify_tls, username, password_enc, role, is_controller, created) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)", site_id, d.single["/system/identity"]["name"], "127.0.0.1", d.port, "http", 0,
        mock_ros.USER, security.encrypt(mock_ros.PASSWORD), role, int(controller), time.time())
    return db.q1("SELECT * FROM devices WHERE id=?", did)


async def seed() -> None:
    sid = db.x("INSERT INTO sites (name, settings) VALUES (?, '{}')", "Thuis (demo)")
    db.x("INSERT INTO sites (name, settings) VALUES (?, '{}')", "Tweede locatie (leeg)")
    site = db.get_site(sid)
    ctrl = _add_device(sid, "router", "router", True)
    devs = [ctrl, _add_device(sid, "crs", "switch"), _add_device(sid, "hexpoe", "switch"),
            _add_device(sid, "ap1", "ap"), _add_device(sid, "ap2", "ap")]
    ros = Ros.for_device(ctrl)

    for name, vlan, subnet, isolate in (("IoT", 30, "192.168.30.0/24", False), ("Gasten", 40, "192.168.40.0/24", True)):
        await networks.create_network(ros, "bridge", {"name": name, "vlan_id": vlan, "subnet": subnet, "isolate": isolate,
                                                      "tagged_ports": ["ether2"]}, await networks.list_networks(ros))

    for pos, (ssid, pw, vlan, bands, iso) in enumerate((("Thuis", "correct-paard-batterij", None, "2g,5g", 0),
                                                         ("Thuis-IoT", "slimme-lampen-2026", 30, "2g,5g", 0),
                                                         ("Thuis-Gast", "welkom-bij-ons", 40, "5g", 1))):
        db.x("INSERT INTO wlans (site_id, slug, ssid, passphrase_enc, security, vlan_id, bands, isolation, ft, position) "
             "VALUES (?,?,?,?,?,?,?,?,?,?)", sid, wifi.slugify(ssid), ssid, security.encrypt(pw),
             "wpa2" if vlan == 30 else "wpa2wpa3", vlan, bands, iso, 1, pos)
    await wifi.apply_plan(ros, await wifi.build_plan(ros, site["settings"], wifi.site_wlans(sid)))
    for ap in devs[3:]:
        await wifi.adopt_ap(Ros.for_device(ap), None)
    for r in await ros.get(wifi.RADIO):
        if not r.get("cap"):
            await ros.cmd(wifi.RADIO + "/provision", {"numbers": r[".id"]})

    # Six hours of plausible history so the charts are not empty on first load.
    now = time.time()
    for i in range(1440, 0, -1):
        ts = now - i * 15
        wave = 0.5 + 0.45 * math.sin(ts / 2400) + 0.25 * math.sin(ts / 310)
        db.x("INSERT INTO metrics (device_id, ts, cpu, mem, clients, rx_bps, tx_bps) VALUES (?,?,?,?,?,?,?)",
             ctrl["id"], ts, 14 + 8 * wave + random.uniform(-2, 2), 43 + random.uniform(-1, 1), 13,
             max(1e6, 38e6 * wave * random.uniform(0.75, 1.25)), max(2e5, 7e6 * wave * random.uniform(0.6, 1.3)))

    for d in devs:
        await poller.refresh_device(d)
        try:
            await maint.check_update(d)
            await maint.backup_device(d, "schedule")
        except RosError:
            pass
    db.log(sid, "Demo-site aangemaakt met gesimuleerde apparaten", "ok")


def reset_data() -> None:
    """The simulated routers forget everything on restart, so the demo database must too."""
    shutil.rmtree(DATA_DIR, ignore_errors=True)


async def start() -> list[asyncio.Task]:
    global _server
    _server = mock_ros.MockServer()
    _server.start()
    await _wait_ready()
    if SEED and not db.q1("SELECT 1 FROM sites"):
        await seed()
    return []
