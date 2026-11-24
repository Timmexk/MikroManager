"""Diagnostics file: the raw answers of the RouterOS menus MikroManager reads, for troubleshooting.

MikroManager is developed against a simulator. When something looks wrong on real hardware, this file shows
what the router actually returned (field names, value formats), next to what MikroManager made of it.
Passwords and keys are always removed. With anonymous=True, MAC addresses, names, serial numbers and
public IP addresses are replaced by stable stand-ins as well, so the file can be shared.
"""
import asyncio
import hashlib
import ipaddress
import re
import time

from . import clients, db, wifi
from .config import VERSION
from .poller import STATE
from .ros import Ros, RosError

COMMON = ["/system/resource", "/system/routerboard", "/system/package", "/system/clock", "/interface",
          "/interface/ethernet", "/interface/ethernet/poe", "/interface/bridge", "/interface/bridge/port",
          "/interface/bridge/vlan", "/interface/vlan", "/interface/wifi", "/interface/wifi/radio",
          "/interface/wifi/registration-table", "/interface/wifi/configuration", "/interface/wifi/channel",
          "/interface/wifi/security", "/interface/wifi/datapath", "/interface/wifi/provisioning",
          "/interface/wifi/capsman", "/interface/wifi/capsman/remote-cap", "/interface/wifi/cap",
          "/interface/wifi/access-list"]
ROUTER = ["/ip/dhcp-server/lease", "/ip/arp", "/ipv6/neighbor", "/ip/kid-control", "/ip/kid-control/device",
          "/ip/route", "/ip/address", "/ip/dhcp-server"]

SECRET = re.compile(r"pass(word|phrase)?|secret|private-key|preshared|\bkey\b|psk", re.I)
NAMEY = {"host-name", "dhcp-hostname", "identity", "ssid", "configuration.ssid", "serial-number", "serial",
         "eap-identity", "eap-username", "common-name"}
MAC = re.compile(r"\b([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){2}):((?:[0-9A-Fa-f]{2}:){2}[0-9A-Fa-f]{2})\b")
IP4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _h(text: str, n: int = 6) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:n]


def _scrub(value, key: str, anonymous: bool):
    if isinstance(value, dict):
        return {k: _scrub(v, k, anonymous) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v, key, anonymous) for v in value]
    if not isinstance(value, str):
        return value
    if SECRET.search(key) and value:
        return "(verwijderd)"
    if not anonymous:
        return value
    if key in NAMEY or key == "comment":
        return f"naam-{_h(value, 4)}" if value else value

    def mac(m):
        tail = _h(m.group(0).upper())
        return f"{m.group(1)}:{tail[0:2]}:{tail[2:4]}:{tail[4:6]}".upper()

    def ip(m):
        try:
            a = ipaddress.ip_address(m.group(0))
        except ValueError:
            return m.group(0)
        return m.group(0) if a.is_private or a.is_loopback or a.is_link_local else f"publiek-ip-{_h(m.group(0), 4)}"
    return IP4.sub(ip, MAC.sub(mac, value))


async def _menus(dev: dict, paths: list[str]) -> dict:
    ros = Ros.for_device(dev)

    async def one(path: str):
        try:
            return await ros.get(path, timeout=10)
        except RosError as e:
            return {"error": str(e), "status": e.status}
    return dict(zip(paths, await asyncio.gather(*(one(p) for p in paths))))


async def collect(site_id: int, anonymous: bool) -> dict:
    site = db.get_site(site_id)
    devs = db.site_devices(site_id)
    out = {"mikromanager": VERSION, "made": time.strftime("%Y-%m-%d %H:%M:%S %z"), "anonymous": anonymous,
           "note": "Wachtwoorden en sleutels zijn verwijderd." + (" Namen, MAC-adressen en publieke IP-adressen zijn vervangen."
                                                                   if anonymous else " Bevat namen, MAC- en IP-adressen van je netwerk."),
           "site": {"settings": {k: v for k, v in site["settings"].items()}}, "devices": []}
    for d in devs:
        s = STATE.get(d["id"]) or {}
        is_router = d["role"] == "router" or d["is_controller"]
        entry = {"name": d["name"], "role": d["role"], "controller": bool(d["is_controller"]), "online": s.get("online"),
                 "error": s.get("error"), "unsupported_menus": sorted(s.get("unsupported") or []),
                 "wifi_monitor": s.get("wifi_mon"), "ethernet_monitor": s.get("eth_mon"), "wan": s.get("wan"),
                 "menus": await _menus(d, COMMON + (ROUTER if is_router else [])) if s.get("online") else {}}
        out["devices"].append(entry)
    out["mikromanager_view"] = {"clients": clients.site_clients(site_id), "access_points": wifi.access_points(site_id)}
    return _scrub(out, "", anonymous)
