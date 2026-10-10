"""WiFi: desired state (WLANs in our db) -> CAPsMAN configuration on the site controller.

Layout written to the controller (RouterOS 7.13+ `wifi` menu):

  /interface/wifi/security       tc-<slug>            auth types, passphrase, 802.11r
  /interface/wifi/datapath       tc-<slug>            bridge, vlan-id, client isolation
  /interface/wifi/channel        tc-ch-2g, tc-ch-5g   width, frequencies, DFS policy
  /interface/wifi/configuration  tc-<slug>-2g|-5g     ssid, country + the three above
  /interface/wifi/provisioning   comment tc:<band>:<drv>  master + slave configurations

Only objects whose name starts with "tc-" (or comment with "tc:") are ever
changed or removed; anything configured by hand is left alone.
"""
import re

from . import db, security
from .config import PREFIX, TAG
from .poller import STATE, snap
from .ros import Ros, RosError, truthy, yn

SEC, DP, CH, CFG, PROV = ("/interface/wifi/security", "/interface/wifi/datapath", "/interface/wifi/channel",
                          "/interface/wifi/configuration", "/interface/wifi/provisioning")
CAPSMAN, CAP, WIFI, RADIO = ("/interface/wifi/capsman", "/interface/wifi/cap", "/interface/wifi", "/interface/wifi/radio")
REMOTE_CAP = "/interface/wifi/capsman/remote-cap"
LABEL = {SEC: "beveiliging", DP: "datapath", CH: "kanaalprofiel", CFG: "configuratie", PROV: "provisioning-regel"}
NEW = {SEC: "Nieuwe", DP: "Nieuw", CH: "Nieuw", CFG: "Nieuwe"}

AUTH = {"open": "", "wpa2": "wpa2-psk", "wpa2wpa3": "wpa2-psk,wpa3-psk", "wpa3": "wpa3-psk"}
# Radios are matched by the newest standard they support; ax rules come first so
# an ax radio never falls through to the ac rule.
BANDS = {("2g", "ax"): "2ghz-ax", ("5g", "ax"): "5ghz-ax", ("2g", "ac"): "2ghz-n", ("5g", "ac"): "5ghz-ac"}
RULE_ORDER = [("2g", "ax"), ("5g", "ax"), ("2g", "ac"), ("5g", "ac")]


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:20] or "wlan"


def site_wlans(site_id: int) -> list[dict]:
    return db.q("SELECT * FROM wlans WHERE site_id=? ORDER BY position, id", site_id)


# ---- desired state ---------------------------------------------------------

def desired_state(settings: dict, wlans: list[dict]) -> dict:
    bridge = settings["bridge"]
    ac = bool(settings.get("ac_caps"))
    out = {SEC: {}, DP: {}, CH: {}, CFG: {}, PROV: []}
    active = [w for w in wlans if w["enabled"]]

    if active:
        ch2 = {"width": settings["ch2_width"], "comment": "TikControl 2.4 GHz"}
        ch5 = {"width": settings["ch5_width"], "skip-dfs-channels": settings["skip_dfs"], "comment": "TikControl 5 GHz"}
        if settings.get("ch2_freq"):
            ch2["frequency"] = settings["ch2_freq"].replace(" ", "")
        if settings.get("ch5_freq"):
            ch5["frequency"] = settings["ch5_freq"].replace(" ", "")
        out[CH] = {f"{PREFIX}ch-2g": ch2, f"{PREFIX}ch-5g": ch5}
        if ac:
            # wifi-qcom-ac cannot take a VLAN from the datapath (MikroTik docs);
            # those CAPs tag per interface with a bridge PVID instead.
            out[DP][f"{PREFIX}dp-ac"] = {"bridge": bridge, "comment": "TikControl ac-CAPs (geen VLAN)"}

    for w in active:
        name = PREFIX + w["slug"]
        ft = bool(w["ft"]) and w["security"] != "open"
        out[SEC][name] = {
            "authentication-types": AUTH[w["security"]],
            "passphrase": security.decrypt(w["passphrase_enc"]) if w["security"] != "open" else "",
            "ft": yn(ft), "ft-over-ds": yn(ft), "wps": "disable", "comment": w["ssid"],
        }
        out[DP][name] = {
            "bridge": bridge, "vlan-id": str(w["vlan_id"]) if w["vlan_id"] else "none",
            "client-isolation": yn(bool(w["isolation"])), "comment": w["ssid"],
        }
        for band in w["bands"].split(","):
            base = {"ssid": w["ssid"], "country": settings["country"], "security": name,
                    "channel": f"{PREFIX}ch-{band}", "hide-ssid": yn(bool(w["hidden"])), "comment": w["ssid"]}
            out[CFG][f"{name}-{band}"] = {**base, "datapath": name}
            if ac:
                out[CFG][f"{name}-{band}-ac"] = {**base, "datapath": f"{PREFIX}dp-ac"}

    for band, drv in RULE_ORDER:
        if drv == "ac" and not ac:
            continue
        cfgs = [f"{PREFIX}{w['slug']}-{band}" + ("-ac" if drv == "ac" else "") for w in active if band in w["bands"].split(",")]
        if cfgs:
            out[PROV].append({
                "action": "create-dynamic-enabled", "supported-bands": BANDS[(band, drv)],
                "master-configuration": cfgs[0], "slave-configurations": ",".join(cfgs[1:]),
                "comment": f"{TAG}{band}:{drv}",
            })
    return out


# ---- diff ------------------------------------------------------------------

def _norm(v) -> str:
    v = "" if v is None else str(v)
    low = v.lower()
    if low in ("yes", "true"):
        return "true"
    if low in ("no", "false"):
        return "false"
    if low == "none":
        return ""
    return ",".join(sorted(v.split(","))) if "," in v else v


# RouterOS may leave a property out of `print` when it still has its default.
DEFAULTS = {"ft": "false", "ft-over-ds": "false", "hide-ssid": "false", "client-isolation": "false",
            "skip-dfs-channels": "disabled", "vlan-id": ""}


def _changed(want: dict, have: dict) -> dict:
    return {k: v for k, v in want.items() if _norm(v) != _norm(have.get(k, DEFAULTS.get(k)))}


def _clean(data: dict) -> dict:
    """Drop empty optional values on add (RouterOS rejects e.g. slave-configurations="")."""
    return {k: v for k, v in data.items() if v != "" or k in ("passphrase", "authentication-types")}


async def build_plan(ros: Ros, settings: dict, wlans: list[dict]) -> list[dict]:
    want = desired_state(settings, wlans)
    ops: list[dict] = []
    have = {}
    for path in (SEC, DP, CH, CFG):
        have[path] = {r["name"]: r for r in await ros.get(path) if r.get("name", "").startswith(PREFIX)}
    rules = [r for r in await ros.get(PROV) if r.get("comment", "").startswith(TAG)]
    capsman = await ros.get(CAPSMAN)

    def secret(path, data):
        return {k: ("••••••••" if k == "passphrase" and v else v) for k, v in data.items()} if path == SEC else data

    # 1. create / update profiles; referenced ones first
    for path in (SEC, DP, CH, CFG):
        for name, data in want[path].items():
            cur = have[path].get(name)
            if cur is None:
                ops.append({"op": "add", "path": path, "data": {"name": name, **_clean(data)},
                            "text": f"{NEW[path]} {LABEL[path]} {name}", "show": secret(path, _clean(data))})
                continue
            diff = _changed(data, cur)
            unset = [k for k in ("frequency",) if path == CH and k in cur and k not in data]
            if diff:
                ops.append({"op": "set", "path": path, "id": cur[".id"], "data": diff,
                            "text": f"Wijzig {LABEL[path]} {name}", "show": secret(path, diff)})
            for k in unset:
                ops.append({"op": "unset", "path": path, "id": cur[".id"], "key": k,
                            "text": f"{LABEL[path].capitalize()} {name}: {k} terug naar automatisch"})

    # 2. provisioning rules. Order matters (ax before ac), so when the set of
    #    rules changes we rebuild our rules instead of patching in place.
    want_tags = [r["comment"] for r in want[PROV]]
    have_tags = [r["comment"] for r in rules]
    rules_touched = False
    if want_tags == have_tags:
        for w, h in zip(want[PROV], rules):
            diff = _changed(w, h)
            if diff:
                rules_touched = True
                ops.append({"op": "set", "path": PROV, "id": h[".id"], "data": diff,
                            "text": f"Wijzig provisioning-regel {w['supported-bands']}", "show": diff})
    else:
        rules_touched = True
        for h in rules:
            ops.append({"op": "remove", "path": PROV, "id": h[".id"],
                        "text": f"Verwijder provisioning-regel {h.get('supported-bands', '')}"})
        for w in want[PROV]:
            ops.append({"op": "add", "path": PROV, "data": _clean(w),
                        "text": f"Nieuwe provisioning-regel {w['supported-bands']}", "show": _clean(w)})

    # 3. remove profiles we no longer want; referencing ones first
    for path in (CFG, CH, DP, SEC):
        for name, cur in have[path].items():
            if name not in want[path]:
                ops.append({"op": "remove", "path": path, "id": cur[".id"], "text": f"Verwijder {LABEL[path]} {name}"})

    # 4. CAPsMAN itself
    if want[PROV] and not truthy(capsman.get("enabled", "false")):
        data = {"enabled": "yes", "interfaces": settings.get("capsman_interfaces") or settings["bridge"]}
        ops.append({"op": "cmd", "path": CAPSMAN + "/set", "data": data, "text": "CAPsMAN inschakelen", "show": data})

    # 5. Existing radios only pick up new/removed SSIDs after a re-provision.
    if rules_touched:
        ops.append({"op": "reprovision", "text": "AP's opnieuw provisionen (clients verbinden kort opnieuw)"})
    return ops


async def _reprovision(ros: Ros) -> int:
    n = 0
    for cap in await ros.get(REMOTE_CAP):
        await ros.cmd(REMOTE_CAP + "/provision", {"numbers": cap[".id"]})
        n += 1
    # Local radios of the controller that were handed over to us earlier.
    ifaces = {i["name"]: i for i in await ros.get(WIFI)}
    for radio in await ros.get(RADIO):
        iface = ifaces.get(radio.get("interface", ""))
        if not radio.get("cap") and iface and truthy(iface.get("dynamic", "false")):
            await ros.cmd(RADIO + "/provision", {"numbers": radio[".id"]})
            n += 1
    return n


async def apply_plan(ros: Ros, ops: list[dict]) -> list[dict]:
    """Run the plan in order; stop at the first error so nothing is half-referenced."""
    results = []
    for op in ops:
        try:
            if op["op"] == "add":
                await ros.add(op["path"], op["data"])
            elif op["op"] == "set":
                await ros.set(op["path"], op["id"], op["data"])
            elif op["op"] == "unset":
                await ros.cmd(op["path"] + "/unset", {".id": op["id"], "value-name": op["key"]})
            elif op["op"] == "remove":
                await ros.remove(op["path"], op["id"])
            elif op["op"] == "cmd":
                await ros.cmd(op["path"], op["data"])
            elif op["op"] == "reprovision":
                await _reprovision(ros)
            results.append({"text": op["text"], "ok": True})
        except RosError as e:
            results.append({"text": op["text"], "ok": False, "error": str(e)})
            break
    return results


def public_plan(ops: list[dict]) -> list[dict]:
    return [{"op": o["op"], "text": o["text"], "show": o.get("show")} for o in ops]


# ---- adopting an AP --------------------------------------------------------

async def adopt_ap(ap: Ros, controller_host: str | None, bridge: str | None = None) -> list[str]:
    """Turn a RouterOS device into a CAP of the site controller.

    Follows the CAP examples from the MikroTik WiFi manual: a local datapath that
    puts wifi interfaces in the AP's own bridge, every radio handed to CAPsMAN.
    """
    done = []
    bridges = [b["name"] for b in await ap.get("/interface/bridge")]
    if bridge is None:
        if len(bridges) != 1:
            raise RosError("Dit apparaat heeft niet precies één bridge; kies de bridge handmatig." if bridges
                           else "Dit apparaat heeft geen bridge. Maak er eerst een aan met de uplink-poort erin.")
        bridge = bridges[0]
    elif bridge not in bridges:
        raise RosError(f"Bridge '{bridge}' bestaat niet op dit apparaat")

    radios = [w for w in await ap.get(WIFI) if not w.get("master-interface")]
    if not radios:
        raise RosError("Geen wifi-interfaces gevonden (wifi-qcom of wifi-qcom-ac pakket vereist)")
    packages = {p.get("name") for p in await ap.get("/system/package")}
    ac_driver = "wifi-qcom-ac" in packages and "wifi-qcom" not in packages

    cap = {"enabled": "yes", "discovery-interfaces": bridge}
    if controller_host:
        cap["caps-man-addresses"] = controller_host
    if ac_driver:
        cap["slaves-static"] = "yes"
        for r in radios:
            await ap.set(WIFI, r[".id"], {"configuration.manager": "capsman", "disabled": "no"})
        done.append("wifi-qcom-ac: VLAN's stel je per interface in met een bridge-PVID op de AP zelf")
    else:
        dp_name = f"{PREFIX}cap"
        if not any(d.get("name") == dp_name for d in await ap.get(DP)):
            await ap.add(DP, {"name": dp_name, "bridge": bridge, "comment": "TikControl CAP"})
        cap["slaves-datapath"] = dp_name
        for r in radios:
            await ap.set(WIFI, r[".id"], {"configuration.manager": "capsman", "datapath": dp_name, "disabled": "no"})
    done.append(f"{len(radios)} radio('s) overgedragen aan CAPsMAN")
    await ap.cmd(CAP + "/set", cap)
    done.append(f"CAP-modus aan op bridge {bridge}")
    return done


async def release_ap(ap: Ros) -> None:
    await ap.cmd(CAP + "/set", {"enabled": "no"})
    for r in await ap.get(WIFI):
        if not r.get("master-interface"):
            await ap.set(WIFI, r[".id"], {"configuration.manager": "local"})


# ---- read model for the UI -------------------------------------------------

def _band(radio: dict) -> str:
    bands = radio.get("bands", "")
    return "6g" if bands.startswith("6ghz") else "5g" if bands.startswith("5ghz") else "2g"


def iface_map(s: dict) -> dict[str, dict]:
    """wifi interface name -> {ap, band, ssid, local} using radios and master links."""
    radios = {r.get("interface"): r for r in s.get("wifi_radios") or []}
    ifaces = {i["name"]: i for i in s.get("wifi_ifaces") or []}
    out = {}
    for name, i in ifaces.items():
        master = i.get("master-interface") or name
        radio = radios.get(master, {})
        cap = radio.get("cap", "")
        out[name] = {"ap": cap.split("@")[0] if cap else None, "local": not cap,
                     "band": _band(radio) if radio else None, "ssid": i.get("configuration.ssid") or i.get("ssid")}
    return out


def access_points(site_id: int) -> list[dict]:
    ctrl = db.controller(site_id)
    if not ctrl:
        return []
    s = STATE.get(ctrl["id"]) or snap(ctrl["id"])
    devs = db.site_devices(site_id)
    by_host = {d["host"]: d for d in devs}
    by_name = {(STATE.get(d["id"]) or {}).get("identity") or d["name"]: d for d in devs}
    ifaces = {i["name"]: i for i in s.get("wifi_ifaces") or []}
    mon = s.get("wifi_mon") or {}
    reg = s.get("wifi_reg") or []
    cfg_ssid = {f"{PREFIX}{w['slug']}-{b}{sfx}": w["ssid"]
                for w in site_wlans(site_id) for b in ("2g", "5g") for sfx in ("", "-ac")}

    def ssid_of(i: dict) -> str | None:
        return i.get("configuration.ssid") or cfg_ssid.get(i.get("configuration", ""))

    slaves: dict[str, list[dict]] = {}
    for i in ifaces.values():
        if i.get("master-interface"):
            slaves.setdefault(i["master-interface"], []).append(i)

    def radio_view(r: dict) -> dict:
        name = r.get("interface", "")
        i = ifaces.get(name, {})
        members = [name] + [x["name"] for x in slaves.get(name, [])]
        ssids = [x for x in [ssid_of(i)] + [ssid_of(x) for x in slaves.get(name, [])] if x]
        m = mon.get(name, {})
        return {"id": r.get(".id"), "mac": r.get("radio-mac"), "band": _band(r), "interface": name or None,
                "channel": m.get("channel"), "tx_power": m.get("tx-power"), "state": m.get("state"),
                "ssids": ssids, "clients": sum(1 for c in reg if c.get("interface") in members),
                "managed": bool(name) and str(i.get("configuration", "")).startswith(PREFIX),
                "dynamic": truthy(i.get("dynamic", "false"))}

    aps: dict[str, dict] = {}
    for cap in s.get("remote_caps") or []:
        ident = cap.get("identity", "?")
        dev = by_host.get(cap.get("address", "")) or by_name.get(ident)
        aps[ident] = {"name": ident, "address": cap.get("address"), "board": cap.get("board-name"),
                      "version": cap.get("version"), "state": cap.get("state"), "local": False,
                      "device_id": dev["id"] if dev else None, "radios": []}
    local = {"name": s.get("identity") or ctrl["name"], "address": ctrl["host"], "local": True,
             "board": (s.get("resource") or {}).get("board-name"), "version": (s.get("resource") or {}).get("version"),
             "state": "Lokaal", "device_id": ctrl["id"], "radios": []}
    for r in s.get("wifi_radios") or []:
        cap = r.get("cap", "")
        if not cap:
            local["radios"].append(radio_view(r))
        else:
            ident = cap.split("@")[0]
            aps.setdefault(ident, {"name": ident, "address": cap.split("@")[-1], "local": False, "state": "?",
                                   "device_id": None, "radios": []})["radios"].append(radio_view(r))
    out = ([local] if local["radios"] else []) + sorted(aps.values(), key=lambda a: a["name"])

    # APs we know as devices but that are not (yet) connected to CAPsMAN.
    seen = {a["device_id"] for a in out}
    for d in devs:
        if d["role"] == "ap" and d["id"] not in seen:
            ds = STATE.get(d["id"]) or {}
            cap_on = truthy((ds.get("wifi_cap") or {}).get("enabled", "false"))
            out.append({"name": ds.get("identity") or d["name"], "address": d["host"], "local": False,
                        "board": (ds.get("resource") or {}).get("board-name"),
                        "version": (ds.get("resource") or {}).get("version"),
                        "state": "Wacht op controller" if cap_on else "Niet gekoppeld",
                        "device_id": d["id"], "radios": [], "adoptable": bool(ds.get("online")) and not cap_on})
    return out
