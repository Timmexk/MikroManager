"""Client list: DHCP leases + ARP + WiFi registration table + bridge host tables, merged by MAC."""
from . import db, wifi
from .config import TAG
from .poller import STATE, uptime_seconds
from .ros import truthy

BLOCK_COMMENT = f"{TAG}blocked"


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
                                        "last_seen": None, "rx": 0, "tx": 0})

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
