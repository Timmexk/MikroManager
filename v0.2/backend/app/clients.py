"""Client list: DHCP leases + ARP + WiFi registration table + bridge host tables, merged by MAC.

Every client appears exactly once, keyed by MAC, at the place it is physically connected:
  wifi   -> the access point it is registered on (never also as wired on the router or a switch)
  wired  -> the edge port where it was learned (the deepest switch port, not the router's uplink port)
"""
import ipaddress
import re
import time

from . import db, wifi
from .config import TAG
from .poller import STATE, uptime_seconds
from .ros import truthy

BLOCK_COMMENT = f"{TAG}blocked"
PAUSE_KID = "mm-pauze"            # kid-control "kid" without allowed time: internet paused
SCHED_KID = "mm-tijd-"            # mm-tijd-0700-2200: internet only between these times
WIFI_GRACE = 90                   # seconds a client stays on its AP when that AP's poll fails

# MAC -> (timestamp, wifi info) of the last successful registration, so a client
# does not flip to "wired on the router" while its access point is briefly unreachable.
_last_wifi: dict[str, tuple[float, dict]] = {}

_RATE = re.compile(r"^\s*([\d.]+)\s*([kKMG]?)(?:bps|b/s)?\s*$")
_RATE_MUL = {"": 1, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}


def rate_bps(v) -> float | None:
    """'1.2Mbps' / '350kbps' / '0bps' / '12345' -> bits per second."""
    m = _RATE.match(str(v or ""))
    return float(m.group(1)) * _RATE_MUL[m.group(2)] if m else None


def global_ipv6(addr: str | None) -> bool:
    try:
        ip = ipaddress.ip_address((addr or "").split("%")[0])
    except ValueError:
        return False
    return ip.version == 6 and ip.is_global and not ip.is_multicast


def schedule_kid(start: str, end: str) -> str:
    return f"{SCHED_KID}{start.replace(':', '')}-{end.replace(':', '')}"


def parse_schedule_kid(name: str) -> dict | None:
    m = re.fullmatch(rf"{SCHED_KID}(\d{{2}})(\d{{2}})-(\d{{2}})(\d{{2}})", name or "")
    return {"from": f"{m[1]}:{m[2]}", "to": f"{m[3]}:{m[4]}"} if m else None


def _split_pair(v: str | None) -> tuple[int, int]:
    try:
        a, b = (v or "0,0").split(",")[:2]
        return int(a), int(b)
    except ValueError:
        return 0, 0


def site_clients(site_id: int) -> list[dict]:
    devs = db.site_devices(site_id)
    snaps = {d["id"]: STATE.get(d["id"]) or {} for d in devs}
    names = {r["mac"]: r["name"] for r in db.q("SELECT mac, name FROM client_names WHERE site_id=?", site_id)}
    ctrl = db.controller(site_id)

    # MACs of our own infrastructure never show up as clients.
    own: set[str] = set()
    for s in snaps.values():
        own.update(i.get("mac-address", "").upper() for i in s.get("interfaces") or [])
        own.update(h.get("mac-address", "").upper() for h in s.get("hosts") or [] if truthy(h.get("local", "false")))
        own.update(r.get("radio-mac", "").upper() for r in s.get("wifi_radios") or [])
    own.discard("")

    clients: dict[str, dict] = {}

    def get(mac: str) -> dict | None:
        mac = (mac or "").upper()
        if not mac or mac in own:
            return None
        return clients.setdefault(mac, {"mac": mac, "name": names.get(mac), "hostname": None, "ip": None,
                                        "online": False, "type": "unknown", "static": False, "lease_id": None,
                                        "lease_device": None, "wifi": None, "wired": None, "blocked": False,
                                        "last_seen": None, "rx": 0, "tx": 0, "ipv6": [], "rate_down": None,
                                        "rate_up": None, "paused": False, "schedule": None})

    for d in devs:
        for lease in snaps[d["id"]].get("leases") or []:
            c = get(lease.get("mac-address"))
            if not c:
                continue
            bound = lease.get("status") == "bound"
            if c["lease_id"] and not bound:
                continue  # keep the active lease when a MAC has several
            c.update(ip=lease.get("active-address") or lease.get("address"),
                     hostname=lease.get("host-name") or c["hostname"],
                     static=not truthy(lease.get("dynamic", "false")), lease_id=lease.get(".id"),
                     lease_device=d["id"], dhcp_server=lease.get("server"), comment=lease.get("comment"),
                     last_seen=lease.get("last-seen"), lease_bound=bound)
        for arp in snaps[d["id"]].get("arp") or []:
            c = clients.get((arp.get("mac-address") or "").upper())
            if c and not c["ip"]:
                c["ip"] = arp.get("address")

    by_identity = {snaps[d["id"]].get("identity") or d["name"]: d["id"] for d in devs}
    for d in devs:
        s = snaps[d["id"]]
        imap = wifi.iface_map(s)
        for r in s.get("wifi_reg") or []:
            c = get(r.get("mac-address"))
            if not c:
                continue
            info = imap.get(r.get("interface", ""), {})
            tx, rx = _split_pair(r.get("bytes"))  # RouterOS counts from the AP's side
            c.update(online=True, type="wifi", rx=tx, tx=rx, wifi={
                "ap": info.get("ap") or s.get("identity") or d["name"], "interface": r.get("interface"),
                "ssid": r.get("ssid") or info.get("ssid"), "band": r.get("band") or info.get("band"),
                "signal": int(r["signal"]) if str(r.get("signal", "")).lstrip("-").isdigit() else None,
                "tx_rate": r.get("tx-rate"), "rx_rate": r.get("rx-rate"),
                "uptime": uptime_seconds(r.get("uptime")), "reg_id": r.get(".id"), "device_id": d["id"],
                # the device the client is physically on (a CAP registers on the controller)
                "ap_device_id": by_identity.get(info.get("ap") or "", d["id"])})

    # A client whose access point did not answer this round keeps its wifi place for a
    # short while instead of showing up as wired on the router's uplink port.
    now = time.time()
    for mac, c in clients.items():
        if c["wifi"]:
            _last_wifi[mac] = (now, c["wifi"])
    for mac, (ts, info) in list(_last_wifi.items()):
        if now - ts > WIFI_GRACE:
            _last_wifi.pop(mac, None)
            continue
        c = clients.get(mac)
        ap_snap = snaps.get(info.get("device_id")) or {}
        if (c is None or not c["wifi"]) and ap_snap.get("online") is not True:
            c = c or get(mac)
            if c:
                c.update(online=True, type="wifi", wifi={**info, "stale": True})

    # Wired port: the port that has learned the fewest MACs is the edge port.
    # Ports that lead to another managed device (a MAC of our own gear was
    # learned there) and wifi interfaces are never edge ports; a MAC that is
    # only visible there is a wifi client's stale bridge entry, not a wired one.
    best: dict[str, tuple[int, dict]] = {}
    for d in devs:
        s = snaps[d["id"]]
        per_port: dict[str, int] = {}
        hosts = [h for h in s.get("hosts") or [] if not truthy(h.get("local", "false"))]
        skip = {i["name"] for i in s.get("interfaces") or [] if i.get("type") in ("wifi", "wlan", "cap")}
        for h in hosts:
            port = h.get("on-interface", "")
            per_port[port] = per_port.get(port, 0) + 1
            if (h.get("mac-address") or "").upper() in own:
                skip.add(port)
        for h in hosts:
            mac = (h.get("mac-address") or "").upper()
            port = h.get("on-interface", "")
            if port in skip:
                continue
            cand = (per_port[port], {"device": s.get("identity") or d["name"], "device_id": d["id"], "port": port,
                                     "shared": per_port[port] - 1})
            if mac not in best or cand[0] < best[mac][0]:
                best[mac] = cand
    for mac, (_, where) in best.items():
        c = clients.get(mac) or (get(mac) if mac not in own else None)
        if not c or c["wifi"]:
            continue
        c.update(online=True, type="wired", wired=where)

    # IPv6 (global only) from the router's neighbor table; live rate, pause and
    # schedule from kid-control. Only adds data to clients that already exist.
    for d in devs:
        s = snaps[d["id"]]
        for n in s.get("ipv6_nb") or []:
            c = clients.get((n.get("mac-address") or "").upper())
            if c and global_ipv6(n.get("address")) and n.get("status") not in ("failed", "noarp"):
                addr = n["address"].split("%")[0]
                if addr not in c["ipv6"]:
                    c["ipv6"].append(addr)
        for k in s.get("kid_dev") or []:
            c = clients.get((k.get("mac-address") or "").upper())
            if not c:
                continue
            down, up = rate_bps(k.get("rate-down")), rate_bps(k.get("rate-up"))
            if down is not None:
                c["rate_down"] = max(c["rate_down"] or 0, down)
            if up is not None:
                c["rate_up"] = max(c["rate_up"] or 0, up)
            user = k.get("user") or ""
            if not truthy(k.get("dynamic", "false")) and user:
                if user == PAUSE_KID:
                    c.update(paused=True, kid_device_id=k.get(".id"))
                elif parse_schedule_kid(user):
                    c.update(schedule=parse_schedule_kid(user), kid_device_id=k.get(".id"))
    for c in clients.values():
        c["ipv6"].sort()

    if ctrl:
        for a in (STATE.get(ctrl["id"]) or {}).get("wifi_acl") or []:
            if a.get("comment", "").startswith(BLOCK_COMMENT) and a.get("action") == "reject":
                c = get(a.get("mac-address"))
                if c:
                    c.update(blocked=True, block_id=a.get(".id"))

    out = list(clients.values())
    for c in out:
        c["display"] = c["name"] or c.get("comment") or c["hostname"] or c["mac"]
    out.sort(key=lambda c: (not c["online"], c["display"].lower()))
    return out


def clients_per_ap(clients: list[dict]) -> dict[int, int]:
    out: dict[int, int] = {}
    for c in clients:
        if c["wifi"]:
            out[c["wifi"]["ap_device_id"]] = out.get(c["wifi"]["ap_device_id"], 0) + 1
    return out
