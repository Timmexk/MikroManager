"""Wifi check: follows the path of every wifi network from the radio to the DHCP server and says where it breaks.

The typical symptom on real hardware is "the SSID is there, but clients get no IP address". That is never a radio
problem; the frame does not reach a DHCP server. The path on a MikroTik is:

  radio interface -> bridge port (bridge + PVID) -> bridge VLAN table (bridge tagged) -> VLAN interface with an
  address -> DHCP server on that interface

Each step is checked against what the router reports. Where a fix is safe (cannot lock anyone out), the check
carries it and POST /wifi/check/fix runs it. Turning on vlan-filtering is never done here: that is a lock-out risk
and belongs on the Interfaces page with safe mode.
"""
from . import wifi
from .config import pfx
from .ros import Ros, RosError, truthy

PORT, BVLAN, VLAN = "/interface/bridge/port", "/interface/bridge/vlan", "/interface/vlan"


def _ids(text) -> set[int]:
    """'30', '30,40', '30-35' -> set of VLAN ids."""
    out: set[int] = set()
    for part in wifi._text(text).split(","):
        part = part.strip()
        if "-" in part:
            a, _, b = part.partition("-")
            if a.isdigit() and b.isdigit():
                out.update(range(int(a), int(b) + 1))
        elif part.isdigit():
            out.add(int(part))
    return out


def _names(text) -> list[str]:
    return [x.strip() for x in wifi._text(text).split(",") if x.strip()]


def _item(cid: str, ok: bool | None, text: str, detail: str = "", fix: dict | None = None, fix_label: str = "") -> dict:
    """ok: True = fine, False = breaks the path, None = worth a look."""
    return {"id": cid, "ok": ok, "text": text, "detail": detail, "fix": fix, "fix_label": fix_label if fix else ""}


async def collect(ros: Ros) -> dict:
    get = ros.get
    return {
        "bridges": {b["name"]: b for b in await get("/interface/bridge")},
        "ports": await get(PORT), "bvlans": await get(BVLAN), "vlans": await get(VLAN),
        "servers": await get("/ip/dhcp-server"), "addrs": await get("/ip/address"),
        "ifaces": {i["name"]: i for i in await get("/interface")},
        "wifi": await get(wifi.WIFI), "radios": await get(wifi.RADIO),
    }


def _local_ifaces(d: dict, cfg: str) -> list[dict]:
    """The router's own wifi interfaces that broadcast configuration `cfg` (master with the profile, or one of
    MikroManager's static virtual interfaces)."""
    masters = {r.get("interface") for r in d["radios"] if not r.get("cap")}
    out = []
    for i in d["wifi"]:
        conf = str(i.get("configuration", ""))
        if i["name"] in masters and (conf == cfg or conf.startswith(cfg + "-r")):
            out.append(i)
        elif i.get("comment", "") == wifi.local_tag() + cfg:
            out.append(i)
    return out


def check(d: dict, settings: dict, wlans: list[dict], caps: bool) -> dict:
    site_bridge = settings.get("bridge") or "bridge"
    general: list[dict] = []
    ssids: list[dict] = []

    # ---- general: bridge ports that point to an interface that no longer exists ----
    for p in d["ports"]:
        name = str(p.get("interface", ""))
        broken = name.startswith("*") or truthy(p.get("invalid", "false")) or name not in d["ifaces"]
        if broken and not truthy(p.get("dynamic", "false")):
            general.append(_item(
                f"port-invalid:{p['.id']}", False, f"Bridge-poort verwijst naar een interface die niet meer bestaat ({name})",
                "Gebeurt als de eigen radio's van de router ooit geprovisioned zijn: RouterOS verwijdert de interface en maakt "
                "een nieuwe aan, de oude bridge-poort blijft wees achter. Verwijderen is veilig.",
                {"op": "remove", "path": PORT, "id": p[".id"]}, "Verwijderen"))

    # ---- general: the router's own radios ----
    masters = [(r, next((i for i in d["wifi"] if i["name"] == r.get("interface")), None)) for r in d["radios"] if not r.get("cap")]
    for radio, iface in masters:
        if not iface:
            continue
        mgr = str(iface.get("configuration.manager", "local"))
        if mgr != "local":
            general.append(_item(
                f"manager:{iface['name']}", False, f"{iface['name']} wacht op CAPsMAN (configuration.manager={mgr})",
                "CAPsMAN kan de eigen radio's van het apparaat waarop hij draait niet beheren. Met manager=local krijgt "
                "de radio zijn profiel rechtstreeks.",
                {"op": "set", "path": wifi.WIFI, "id": iface[".id"], "data": {"configuration.manager": "local"}}, "Op local zetten"))
        if truthy(iface.get("dynamic", "false")):
            general.append(_item(f"provisioned:{iface['name']}", False,
                                 f"{iface['name']} is nog door CAPsMAN geprovisioned",
                                 "Gebruik 'Radio's overnemen' bij de router onder Access points: dat herstelt het eerst."))
    if masters and not any(i and str(i.get("configuration", "")).startswith(pfx()) for _r, i in masters):
        general.append(_item("local-unmanaged", None, "Geen van de eigen radio's van de router zendt de site-netwerken uit",
                             "Ze zenden uit wat er in RouterOS op staat (of wat je zelfstandig hebt ingesteld). Kies per radio "
                             "'Site-netwerken' als ze moeten meedoen met de access points (naadloos roamen)."))
    if site_bridge not in d["bridges"]:
        general.append(_item("site-bridge", False, f"De bridge '{site_bridge}' uit de radio-instellingen bestaat niet",
                             f"Bridges op de router: {', '.join(d['bridges']) or 'geen'}. Kies de juiste onder Radio-instellingen."))

    # ---- per wifi network ----
    for w in [w for w in wlans if w["enabled"]]:
        bridge = w.get("bridge") or site_bridge
        vid = w.get("vlan_id")
        items: list[dict] = []
        b = d["bridges"].get(bridge)
        target = f"VLAN {vid} op {bridge}" if vid else f"{bridge}, zonder VLAN"
        if not b:
            items.append(_item(f"bridge:{w['id']}", False, f"Bridge {bridge} bestaat niet",
                               "Het datapath stuurt de clients naar een bridge die er niet is. Kies het juiste netwerk."))
            ssids.append({"ssid": w["ssid"], "target": target, "scope": w.get("scope") or "all", "items": items})
            continue
        items.append(_item(f"bridge:{w['id']}", True, f"Bridge {bridge} bestaat"))
        filtering = truthy(b.get("vlan-filtering", "false"))
        net_iface = bridge
        if vid:
            items.append(_item(f"filtering:{w['id']}", filtering,
                               f"VLAN-filtering staat {'aan' if filtering else 'uit'} op {bridge}",
                               "" if filtering else "Zonder vlan-filtering verwerkt de bridge het VLAN-label van het datapath "
                               "niet, dus de clients bereiken de DHCP-server niet. Zet het aan onder Apparaten → Interfaces "
                               "(met veilige modus), pas als de bridge-VLAN-tabel hieronder klopt."))
            vif = next((v for v in d["vlans"] if str(v.get("vlan-id")) == str(vid) and v.get("interface") == bridge), None)
            if vif:
                net_iface = vif["name"]
                items.append(_item(f"vlanif:{w['id']}", True, f"VLAN-interface {vif['name']} (VLAN {vid}) op {bridge}"))
            else:
                items.append(_item(f"vlanif:{w['id']}", False, f"Geen VLAN-interface voor VLAN {vid} op {bridge}",
                                   "De router heeft dan geen poot in dit netwerk. Maak het aan onder Netwerken."))
                net_iface = None
            rows = [r for r in d["bvlans"] if r.get("bridge") == bridge and vid in _ids(r.get("vlan-ids"))]
            tagged = any(bridge in _names(r.get("tagged")) or bridge in _names(r.get("current-tagged")) for r in rows)
            if tagged:
                items.append(_item(f"bvlan:{w['id']}", True, f"VLAN {vid} staat in de bridge-VLAN-tabel met {bridge} tagged"))
            else:
                static = next((r for r in rows if not truthy(r.get("dynamic", "false"))), None)
                if static:
                    fix = {"op": "set", "path": BVLAN, "id": static[".id"],
                           "data": {"tagged": ",".join(_names(static.get("tagged")) + [bridge])}}
                else:
                    fix = {"op": "add", "path": BVLAN, "data": {"bridge": bridge, "vlan-ids": str(vid), "tagged": bridge,
                                                                "comment": f"MikroManager wifi {w['ssid']}"}}
                items.append(_item(f"bvlan:{w['id']}", False, f"{bridge} zelf is niet tagged lid van VLAN {vid}",
                                   "Dan komt verkeer uit dit VLAN niet bij de router (en zijn DHCP-server). "
                                   f"Oplossing: {bridge} als tagged toevoegen in de bridge-VLAN-tabel.", fix, "Toevoegen"))
        if net_iface:
            addr = [a for a in d["addrs"] if a.get("interface") == net_iface and not truthy(a.get("disabled", "false"))]
            srv = next((s for s in d["servers"] if s.get("interface") == net_iface), None)
            if addr:
                items.append(_item(f"addr:{w['id']}", True, f"Adres {addr[0]['address']} op {net_iface}"))
            if srv and truthy(srv.get("disabled", "false")):
                items.append(_item(f"dhcp:{w['id']}", False, f"DHCP-server {srv.get('name')} op {net_iface} staat uit", "",
                                   {"op": "set", "path": "/ip/dhcp-server", "id": srv[".id"], "data": {"disabled": "no"}}, "Aanzetten"))
            elif srv:
                items.append(_item(f"dhcp:{w['id']}", True, f"DHCP-server {srv.get('name')} op {net_iface}"))
            else:
                items.append(_item(f"dhcp:{w['id']}", None, f"Geen DHCP-server op {net_iface}",
                                   "Clients krijgen alleen een adres als een ander apparaat in dit netwerk DHCP doet."
                                   + ("" if addr else f" Er staat ook geen IP-adres op {net_iface}.")))

        # the router's own radios: is each interface really a port of the right bridge, with the right PVID?
        if wifi.on_local(w):
            want_pvid = str(vid) if vid else str(b.get("pvid", "1"))
            for band in w["bands"].split(","):
                cfg = f"{pfx()}{w['slug']}-{band}"
                for i in _local_ifaces(d, cfg):
                    name = i["name"]
                    ports = [p for p in d["ports"] if p.get("interface") == name]
                    p = ports[0] if ports else None
                    label = f"{name} ({'2,4' if band == '2g' else '5'} GHz)"
                    if not p:
                        items.append(_item(f"port:{name}", False, f"{label} zit in geen enkele bridge",
                                           "Zonder bridge-poort komen de clients nergens: geen DHCP, geen IP-adres.",
                                           {"op": "add", "path": PORT, "data": {"bridge": bridge, "interface": name, "pvid": want_pvid,
                                                                                "comment": "MikroManager wifi"}},
                                           f"Toevoegen aan {bridge}"))
                        continue
                    dyn = truthy(p.get("dynamic", "false"))
                    wrong_bridge = p.get("bridge") != bridge
                    wrong_pvid = (vid or filtering) and str(p.get("pvid", "1")) != want_pvid
                    if not wrong_bridge and not wrong_pvid:
                        items.append(_item(f"port:{name}", True, f"{label} in {bridge}"
                                           + (f" met PVID {want_pvid}" if vid or filtering else "")
                                           + (" (via het datapath)" if dyn else "")))
                    elif dyn:
                        items.append(_item(f"port:{name}", False, f"{label} zit in {p.get('bridge')} met PVID {p.get('pvid', '1')}",
                                           "Dit volgt uit het datapath: pas eerst de openstaande wifi-wijzigingen toe."))
                    else:
                        items.append(_item(
                            f"port:{name}", False,
                            f"{label} is een vaste bridge-poort in {p.get('bridge')} met PVID {p.get('pvid', '1')}",
                            f"Een vaste bridge-poort gaat voor het datapath. Verwacht: {bridge}, PVID {want_pvid}.",
                            {"op": "set", "path": PORT, "id": p[".id"], "data": {"bridge": bridge, "pvid": want_pvid}},
                            f"Naar {bridge}, PVID {want_pvid}"))
        if caps and wifi.on_caps(w) and w.get("bridge") and w["bridge"] != site_bridge:
            items.append(_item(f"capbridge:{w['id']}", None, "Aparte bridge zonder VLAN gaat niet naar de access points",
                               "Een CAP heeft één bridge; daar kan dit netwerk alleen met een VLAN heen. Zet 'Uitzenden op' "
                               "op alleen de router, of gebruik een VLAN."))
        ssids.append({"ssid": w["ssid"], "target": target, "scope": w.get("scope") or "all", "items": items})

    all_items = general + [i for s in ssids for i in s["items"]]
    return {"general": general, "ssids": ssids,
            "errors": sum(1 for i in all_items if i["ok"] is False),
            "warnings": sum(1 for i in all_items if i["ok"] is None),
            "fixable": sum(1 for i in all_items if i["fix"])}


def public(result: dict) -> dict:
    """Without the raw fix operations (the client only needs to know there is one)."""
    def strip(i):
        return {k: v for k, v in i.items() if k != "fix"} | {"fixable": bool(i["fix"])}
    return {**result, "general": [strip(i) for i in result["general"]],
            "ssids": [{**s, "items": [strip(i) for i in s["items"]]} for s in result["ssids"]]}


async def run_fix(ros: Ros, fix: dict) -> None:
    if fix["op"] == "add":
        await ros.add(fix["path"], fix["data"])
    elif fix["op"] == "set":
        await ros.set(fix["path"], fix["id"], fix["data"])
    elif fix["op"] == "remove":
        await ros.remove(fix["path"], fix["id"])
    else:
        raise RosError(f"onbekende reparatie {fix['op']}")
