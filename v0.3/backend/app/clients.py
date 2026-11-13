"""Client list: DHCP leases + ARP + WiFi registration table + bridge host tables, merged by MAC.

Every client appears exactly once, keyed by MAC, at the place it is physically connected:
  wifi   -> the access point it is registered on (never also as wired on the router or a switch)
  wired  -> the edge port where it was learned (the deepest switch port, not the router's uplink port)
"""
import ipaddress
import re
import time

from . import cache, db, oui, wifi
from .config import tag
from .poller import STATE, uptime_seconds
from .ros import truthy

def block_comment() -> str:
    return f"{tag()}blocked"
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


def _split_pair(v) -> tuple[int, int]:
    """RouterOS "tx,rx" counters. The manual types them as a composite {tx, rx}; accept text and object form."""
    try:
        if isinstance(v, dict):
            return int(v.get("tx") or 0), int(v.get("rx") or 0)
        a, b = str(v or "0,0").replace("tx=", "").replace("rx=", "").split(",")[:2]
        return int(a), int(b)
    except (ValueError, TypeError):
        return 0, 0


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _text(v) -> str | None:
    """A value that RouterOS may return as text or as a list (e.g. band)."""
    if isinstance(v, (list, tuple)):
        v = ",".join(str(x) for x in v)
    return str(v) if v not in (None, "") else None


def site_clients(site_id: int) -> list[dict]:
    """The merged client list of a site. Rebuilt only when a poll brought new data or something was changed."""
    db.get_site(site_id)        # selects the site's naming prefix
    stamp = tuple((d["id"], (STATE.get(d["id"]) or {}).get("polls"), (STATE.get(d["id"]) or {}).get("live_ts"))
                  for d in db.site_devices(site_id))
    key = ("clients", site_id, cache.generation, stamp)
    hit = cache.get(key)
    if hit is not None:
        return hit
    return cache.put(key, _site_clients(site_id), 30)


def _site_clients(site_id: int) -> list[dict]:
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
                                        "rate_up": None, "paused": False, "schedule": None,
                                        "vendor": oui.lookup(mac), "random_mac": oui.is_random(mac),
                                        "block_ids": {}})

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
            sig = _num(r.get("signal"))
            # live rate of the radio link itself (AP tx = client download); covers all traffic, also local
            down, up = _num(r.get("tx-bits-per-second")), _num(r.get("rx-bits-per-second"))
            if down is not None and up is not None:
                c.update(rate_down=down, rate_up=up, rate_source="wifi")
            c["hostname"] = c["hostname"] or _text(r.get("dhcp-hostname"))
            c["ip"] = c["ip"] or _text(r.get("dhcp-address"))
            c.update(online=True, type="wifi", rx=tx, tx=rx, wifi={
                "ap": info.get("ap") or s.get("identity") or d["name"], "interface": r.get("interface"),
                "ssid": r.get("ssid") or info.get("ssid"), "band": _text(r.get("band")) or info.get("band"),
                "signal": int(sig) if sig is not None else None,
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
            if c.get("rate_source") != "wifi":      # wifi clients already have the rate of their radio link
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

    # Blocked: rejected on wifi (access list) and dropped in the router's firewall (wired).
    if ctrl:
        cs = STATE.get(ctrl["id"]) or {}
        for a in cs.get("wifi_acl") or []:
            if a.get("comment", "").startswith(block_comment()) and a.get("action") == "reject":
                c = get(a.get("mac-address"))
                if c:
                    c.update(blocked=True, block_id=a.get(".id"))
                    c["block_ids"].setdefault("/interface/wifi/access-list", []).append(a.get(".id"))
        for key, path in (("fw_filter", "/ip/firewall/filter"), ("fw6_filter", "/ipv6/firewall/filter")):
            for r in cs.get(key) or []:
                if r.get("comment", "").startswith(block_comment()) and r.get("src-mac-address"):
                    c = get(r.get("src-mac-address"))
                    if c:
                        c["blocked"] = True
                        c["block_ids"].setdefault(path, []).append(r.get(".id"))

    # Devices we have seen before but that are in no table right now (lease expired): keep them, as offline.
    seen = {r["mac"]: r for r in db.q("SELECT * FROM client_seen WHERE site_id=?", site_id)}
    for mac, r in seen.items():
        if mac not in clients and mac not in own:
            c = get(mac)
            if c:
                c.update(ip=r["ip"], hostname=r["hostname"], type=r["kind"] or "unknown", remembered=True)
    for mac, c in clients.items():
        r = seen.get(mac)
        c["seen"] = {"first": r["first_seen"], "last": r["last_seen"], "place": r["place"]} if r else None

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


# ---- history ----------------------------------------------------------------

_prev: dict[int, dict[str, tuple[bool, str | None]]] = {}     # site -> mac -> (online, place)


def place_of(c: dict) -> str | None:
    if c.get("wifi"):
        return f"{c['wifi']['ap']} ({c['wifi'].get('ssid') or 'wifi'})"
    if c.get("wired"):
        return f"{c['wired']['device']} {c['wired']['port']}"
    return None


def track(site_id: int) -> None:
    """Called after every poll round: remember who is there and write down what changed (online, offline,
    another access point). The first round after a start only takes stock; it does not log events."""
    now = time.time()
    cl = site_clients(site_id)
    prev = _prev.get(site_id)
    known = {r["mac"] for r in db.q("SELECT mac FROM client_seen WHERE site_id=?", site_id)}
    first_ever = not known
    cur: dict[str, tuple[bool, str | None]] = {}
    for c in cl:
        mac, place = c["mac"], place_of(c)
        cur[mac] = (c["online"], place)
        if not c["online"]:
            continue
        if mac in known:
            db.x("UPDATE client_seen SET last_seen=?, ip=COALESCE(?, ip), hostname=COALESCE(?, hostname), kind=?, place=? "
                 "WHERE site_id=? AND mac=?", now, c["ip"], c["hostname"], c["type"], place, site_id, mac)
        else:
            db.x("INSERT INTO client_seen (site_id, mac, first_seen, last_seen, ip, hostname, kind, place) VALUES (?,?,?,?,?,?,?,?)",
                 site_id, mac, now, now, c["ip"], c["hostname"], c["type"], place)
            if not first_ever:
                event(site_id, mac, "new", place)
                db.log(site_id, f"Nieuw apparaat op het netwerk: {c['display']}" + (f" ({c['vendor']})" if c.get("vendor") else "")
                       + (f", {place}" if place else ""))
    if prev is not None:
        for mac, (online, place) in cur.items():
            was = prev.get(mac)
            if was is None:
                if online and mac in known:
                    event(site_id, mac, "online", place)
            elif online and not was[0]:
                event(site_id, mac, "online", place)
            elif not online and was[0]:
                event(site_id, mac, "offline", was[1])
            elif online and place and was[1] and place != was[1]:
                event(site_id, mac, "roam", f"{was[1]} → {place}")
    _prev[site_id] = cur


def event(site_id: int, mac: str, kind: str, detail: str | None) -> None:
    db.x("INSERT INTO client_events (site_id, mac, ts, kind, detail) VALUES (?,?,?,?,?)", site_id, mac, time.time(), kind, detail)


def history(site_id: int, mac: str, limit: int = 50) -> list[dict]:
    return db.q("SELECT ts, kind, detail FROM client_events WHERE site_id=? AND mac=? ORDER BY id DESC LIMIT ?",
                site_id, mac.upper(), limit)


def forget(site_id: int, mac: str) -> None:
    for table in ("client_seen", "client_events", "client_names", "client_schedules"):
        db.x(f"DELETE FROM {table} WHERE site_id=? AND mac=?", site_id, mac.upper())
    _prev.get(site_id, {}).pop(mac.upper(), None)
