"""Interfaces per device: list everything, change ports, PoE, bridge/VLAN membership and VLAN interfaces.

Every change goes through safe.apply(): steps that can cut off the device are guarded by an
undo scheduler on the device itself.
"""
import asyncio
import re

from . import cache, safe
from .poller import STATE
from .ros import Ros, truthy
from .safe import Op

SPEEDS_COPPER = ["10M-baseT-half", "10M-baseT-full", "100M-baseT-half", "100M-baseT-full", "1G-baseT-full",
                 "2.5G-baseT", "5G-baseT", "10G-baseT"]
SPEEDS_SFP = ["1G-baseX", "2.5G-baseX", "10G-baseSR-LR", "10G-baseCR", "25G-baseSR-LR", "25G-baseCR"]
FRAME_TYPES = ["admit-all", "admit-only-untagged-and-priority-tagged", "admit-only-vlan-tagged"]
POE_OUT = ["auto-on", "forced-on", "off"]
KIND = {"ether": "ether", "vlan": "vlan", "bridge": "bridge", "wifi": "wifi", "wlan": "wifi", "cap": "wifi",
        "pppoe-out": "pppoe", "lte": "lte", "wg": "wireguard", "wireguard": "wireguard", "bond": "bonding",
        "bonding": "bonding", "loopback": "other"}


def _split(v: str | None) -> list[str]:
    return [x for x in (v or "").split(",") if x]


def _ids(v: str | None) -> list[int]:
    """'10,20,100-102' -> [10, 20, 100, 101, 102]"""
    out = []
    for part in _split(v):
        if "-" in part:
            a, b = part.split("-", 1)
            if a.isdigit() and b.isdigit():
                out += list(range(int(a), int(b) + 1))
        elif part.isdigit():
            out.append(int(part))
    return out


async def fetch(dev: dict, fresh: bool = False) -> dict:
    """Raw interface menus of one device. Kept for a few seconds unless `fresh` (always fresh before a change)."""
    if not fresh:
        hit = cache.get(("ifaces", dev["id"]))
        if hit is not None:
            return hit
    return cache.put(("ifaces", dev["id"]), await _fetch(dev), 6)


async def _fetch(dev: dict) -> dict:
    ros = Ros.for_device(dev)
    paths = {"interface": "/interface", "ethernet": "/interface/ethernet", "poe": "/interface/ethernet/poe",
             "bridge": "/interface/bridge", "bport": "/interface/bridge/port", "bvlan": "/interface/bridge/vlan",
             "vlan": "/interface/vlan"}
    res = await asyncio.gather(*(ros.get(p) for p in paths.values()), return_exceptions=True)
    raw = {k: (r if isinstance(r, list) else []) for k, r in zip(paths, res)}
    if isinstance(res[0], Exception):
        raise res[0]
    return raw


def view(dev: dict, raw: dict) -> dict:
    s = STATE.get(dev["id"]) or {}
    rates, mon, poe_mon = s.get("rates") or {}, s.get("eth_mon") or {}, s.get("poe_mon") or {}
    eth = {e["name"]: e for e in raw["ethernet"]}
    poe = {p["name"]: p for p in raw["poe"]}
    bport = {p.get("interface"): p for p in raw["bport"]}
    vlan = {v["name"]: v for v in raw["vlan"]}
    bridges = {b["name"]: b for b in raw["bridge"]}
    tagged: dict[str, list[int]] = {}
    untagged: dict[str, list[int]] = {}
    for e in raw["bvlan"]:
        for port in _split(e.get("tagged")) + _split(e.get("current-tagged")):
            tagged.setdefault(port, [])
            tagged[port] = sorted(set(tagged[port]) | set(_ids(e.get("vlan-ids"))))
        for port in _split(e.get("untagged")) + _split(e.get("current-untagged")):
            untagged[port] = sorted(set(untagged.get(port, [])) | set(_ids(e.get("vlan-ids"))))
    out = []
    for i in raw["interface"]:
        name = i["name"]
        t = i.get("type", "")
        kind = "sfp" if t == "ether" and name.startswith(("sfp", "qsfp")) else KIND.get(t, "other")
        r = rates.get(name, (None, None))
        item = {"id": i[".id"], "name": name, "type": t, "kind": kind, "running": truthy(i.get("running", "false")),
                "disabled": truthy(i.get("disabled", "false")), "comment": i.get("comment"),
                "mtu": i.get("mtu") or i.get("actual-mtu"), "mac": i.get("mac-address"), "rx_bps": r[0], "tx_bps": r[1],
                "dynamic": truthy(i.get("dynamic", "false")), "wan": name == s.get("wan"),
                "slave": truthy(i.get("slave", "false"))}
        if name in eth:
            e, m = eth[name], mon.get(name, {})
            item["ether"] = {"id": e[".id"], "auto_negotiation": truthy(e.get("auto-negotiation", "true")),
                             "speed": e.get("speed"), "rate": m.get("rate") if m.get("status") == "link-ok" else None,
                             "speeds": SPEEDS_SFP if kind == "sfp" else SPEEDS_COPPER}
        if name in poe:
            p, pm = poe[name], poe_mon.get(name, {})
            item["poe"] = {"id": p[".id"], "out": p.get("poe-out"), "priority": p.get("poe-priority"),
                           "status": pm.get("poe-out-status"), "power": pm.get("poe-out-power")}
        if name in bport:
            b = bport[name]
            item["bridge_port"] = {"id": b[".id"], "bridge": b.get("bridge"), "pvid": int(b.get("pvid") or 1),
                                   "frame_types": b.get("frame-types") or "admit-all",
                                   "tagged": tagged.get(name, []), "untagged": untagged.get(name, []),
                                   "vlan_filtering": truthy((bridges.get(b.get("bridge")) or {}).get("vlan-filtering", "false"))}
        if name in vlan:
            v = vlan[name]
            item["vlan"] = {"id": v[".id"], "vlan_id": int(v.get("vlan-id") or 0), "parent": v.get("interface")}
        if name in bridges:
            b = bridges[name]
            item["bridge"] = {"vlan_filtering": truthy(b.get("vlan-filtering", "false")),
                              "ports": [p.get("interface") for p in raw["bport"] if p.get("bridge") == name]}
        out.append(item)
    order = ["ether", "sfp", "bridge", "vlan", "bonding", "wifi", "pppoe", "lte", "wireguard", "other"]
    out.sort(key=lambda x: (order.index(x["kind"]) if x["kind"] in order else 99, _natural(x["name"])))
    return {"interfaces": out, "bridges": list(bridges), "frame_types": FRAME_TYPES, "poe_out": POE_OUT,
            "safe_secs": safe.SAFE_SECS}


def _natural(name: str):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", name)]


def _bvlan_entry(raw: dict, bridge: str, vid: int) -> dict | None:
    """The static bridge-vlan row for exactly this one VLAN id on this bridge."""
    return next((e for e in raw["bvlan"] if e.get("bridge") == bridge and not truthy(e.get("dynamic", "false"))
                 and _ids(e.get("vlan-ids")) == [vid]), None)


def plan_port(raw: dict, name: str, body: dict) -> list[Op]:
    iface = next((i for i in raw["interface"] if i["name"] == name), None)
    if not iface:
        raise ValueError(f"Interface {name} bestaat niet op dit apparaat")
    ops: list[Op] = []

    gen = {}
    if "disabled" in body:
        gen["disabled"] = "yes" if body["disabled"] else "no"
    if "mtu" in body and str(body["mtu"]) != str(iface.get("mtu")):
        mtu = int(body["mtu"])
        if not 68 <= mtu <= 9216:
            raise ValueError("MTU moet tussen 68 en 9216 liggen")
        gen["mtu"] = str(mtu)
    if gen:
        ops.append(Op("/interface", "set", gen, iface[".id"], {k: iface.get(k, "no" if k == "disabled" else "")
                                                               for k in gen}, label="interface"))
    if "comment" in body and (body["comment"] or "") != (iface.get("comment") or ""):
        ops.append(Op("/interface", "set", {"comment": body["comment"] or ""}, iface[".id"],
                      {"comment": iface.get("comment") or ""}, risky=False, label="label"))

    eth = next((e for e in raw["ethernet"] if e["name"] == name), None)
    if eth and ("auto_negotiation" in body or "speed" in body):
        data = {}
        an = body.get("auto_negotiation", truthy(eth.get("auto-negotiation", "true")))
        if an != truthy(eth.get("auto-negotiation", "true")):
            data["auto-negotiation"] = "yes" if an else "no"
        if not an and body.get("speed") and body["speed"] != eth.get("speed"):
            if body["speed"] not in SPEEDS_COPPER + SPEEDS_SFP:
                raise ValueError("Onbekende snelheid")
            data["speed"] = body["speed"]
        if data:
            ops.append(Op("/interface/ethernet", "set", data, eth[".id"],
                          {k: eth.get(k) for k in data if eth.get(k) is not None}, label="snelheid"))

    poe = next((p for p in raw["poe"] if p["name"] == name), None)
    if poe and ("poe_out" in body or "poe_priority" in body):
        data = {}
        if body.get("poe_out") and body["poe_out"] != poe.get("poe-out"):
            if body["poe_out"] not in POE_OUT:
                raise ValueError("Onbekende PoE-stand")
            data["poe-out"] = body["poe_out"]
        if "poe_priority" in body and str(body["poe_priority"]) != str(poe.get("poe-priority")):
            pr = int(body["poe_priority"])
            if not 0 <= pr <= 99:
                raise ValueError("PoE-prioriteit moet tussen 0 en 99 liggen")
            data["poe-priority"] = str(pr)
        if data:
            ops.append(Op("/interface/ethernet/poe", "set", data, poe[".id"],
                          {k: poe.get(k) for k in data if poe.get(k) is not None},
                          risky=data.get("poe-out") == "off" or "poe-out" in data, label="PoE"))

    bp = next((p for p in raw["bport"] if p.get("interface") == name), None)
    if "bridge" in body:
        want = body["bridge"] or None
        if want and want not in {b["name"] for b in raw["bridge"]}:
            raise ValueError(f"Bridge {want} bestaat niet")
        if want and not bp:
            data = {"interface": name, "bridge": want, "pvid": str(int(body.get("pvid") or 1)),
                    "frame-types": body.get("frame_types") or "admit-all"}
            ops.append(Op("/interface/bridge/port", "add", data, find={"interface": name, "bridge": want},
                          label="bridge"))
            bp = None
        elif not want and bp:
            if truthy(bp.get("dynamic", "false")):
                raise ValueError(f"{name} is dynamisch aan de bridge toegevoegd en kan hier niet weg")
            ops.append(Op("/interface/bridge/port", "remove", ident=bp[".id"], old=dict(bp), label="bridge"))
            bp = None
        elif want and bp and bp.get("bridge") != want:
            ops.append(Op("/interface/bridge/port", "set", {"bridge": want}, bp[".id"], {"bridge": bp.get("bridge")},
                          label="bridge"))
    if bp:
        data = {}
        if "pvid" in body and int(body["pvid"] or 1) != int(bp.get("pvid") or 1):
            pv = int(body["pvid"])
            if not 1 <= pv <= 4094:
                raise ValueError("PVID moet tussen 1 en 4094 liggen")
            data["pvid"] = str(pv)
        if body.get("frame_types") and body["frame_types"] != (bp.get("frame-types") or "admit-all"):
            if body["frame_types"] not in FRAME_TYPES:
                raise ValueError("Onbekend frame-type")
            data["frame-types"] = body["frame_types"]
        if data:
            ops.append(Op("/interface/bridge/port", "set", data, bp[".id"],
                          {k: bp.get(k) for k in data if bp.get(k) is not None}, label="PVID/frames"))

    if "tagged" in body:
        bridge = (bp or {}).get("bridge") or body.get("bridge")
        if not bridge:
            raise ValueError("Tagged VLAN's kan alleen op een poort die in een bridge zit")
        want = sorted({int(v) for v in body["tagged"]})
        if any(not 1 <= v <= 4094 for v in want):
            raise ValueError("VLAN-ID's moeten tussen 1 en 4094 liggen")
        have = set()
        for e in raw["bvlan"]:
            if e.get("bridge") == bridge and not truthy(e.get("dynamic", "false")) and name in _split(e.get("tagged")):
                ids = _ids(e.get("vlan-ids"))
                have |= set(ids)
                drop = [v for v in ids if v not in want]
                if drop and len(drop) != len(ids):
                    raise ValueError(f"VLAN {e.get('vlan-ids')} staat in één regel op de bridge; pas die in WinBox aan "
                                     f"of haal alle VLAN's uit die regel tegelijk weg")
                if drop:
                    rest = [p for p in _split(e.get("tagged")) if p != name]
                    ops.append(Op("/interface/bridge/vlan", "set", {"tagged": ",".join(rest)}, e[".id"],
                                  {"tagged": e.get("tagged", "")}, label="tagged"))
        for vid in want:
            if vid in have:
                continue
            e = _bvlan_entry(raw, bridge, vid)
            if e:
                ops.append(Op("/interface/bridge/vlan", "set", {"tagged": ",".join(_split(e.get("tagged")) + [name])},
                              e[".id"], {"tagged": e.get("tagged", "")}, label="tagged"))
            else:
                ops.append(Op("/interface/bridge/vlan", "add", {"bridge": bridge, "vlan-ids": str(vid), "tagged": name},
                              find={"bridge": bridge, "vlan-ids": str(vid)}, label="tagged"))
    return ops


def plan_vlan(raw: dict, body: dict, current: str | None = None) -> list[Op]:
    names = {i["name"] for i in raw["interface"]}
    if current is not None:
        v = next((x for x in raw["vlan"] if x["name"] == current), None)
        if not v:
            raise ValueError(f"VLAN-interface {current} bestaat niet")
        if body.get("delete"):
            return [Op("/interface/vlan", "remove", ident=v[".id"], old=dict(v), label="vlan weg")]
        data = {}
        for key, rkey in (("name", "name"), ("vlan_id", "vlan-id"), ("interface", "interface"), ("mtu", "mtu"),
                          ("comment", "comment")):
            if key in body and body[key] is not None and str(body[key]) != str(v.get(rkey, "")):
                data[rkey] = str(body[key])
        if "disabled" in body and body["disabled"] != truthy(v.get("disabled", "false")):
            data["disabled"] = "yes" if body["disabled"] else "no"
        _check_vlan({**{"name": v["name"], "vlan-id": v.get("vlan-id"), "interface": v.get("interface")}, **data},
                    names - {current}, raw)
        risky = any(k in data for k in ("vlan-id", "interface", "disabled", "mtu", "name"))
        return [Op("/interface/vlan", "set", data, v[".id"], {k: v.get(k, "") for k in data}, risky=risky, label="vlan")]
    data = {"name": (body.get("name") or "").strip(), "vlan-id": str(body.get("vlan_id") or ""),
            "interface": body.get("interface") or ""}
    if body.get("comment"):
        data["comment"] = body["comment"]
    if body.get("mtu"):
        data["mtu"] = str(int(body["mtu"]))
    _check_vlan(data, names, raw)
    return [Op("/interface/vlan", "add", data, find={"name": data["name"]}, risky=False, label="vlan erbij")]


def _check_vlan(d: dict, other_names: set[str], raw: dict) -> None:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,30}", d.get("name") or ""):
        raise ValueError("Geef de VLAN-interface een naam (letters, cijfers, . _ -)")
    if d["name"] in other_names:
        raise ValueError(f"Er is al een interface met de naam {d['name']}")
    if not str(d.get("vlan-id", "")).isdigit() or not 1 <= int(d["vlan-id"]) <= 4094:
        raise ValueError("VLAN-ID moet tussen 1 en 4094 liggen")
    if d.get("interface") not in {i["name"] for i in raw["interface"]}:
        raise ValueError("Kies de interface waar het VLAN op komt (meestal de bridge)")
    clash = next((v for v in raw["vlan"] if v["name"] != d["name"] and v.get("interface") == d["interface"]
                  and str(v.get("vlan-id")) == str(d["vlan-id"])), None)
    if clash:
        raise ValueError(f"VLAN {d['vlan-id']} op {d['interface']} bestaat al ({clash['name']})")
