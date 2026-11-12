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

# Transmit power per radio. "high" = no limit: RouterOS uses the maximum the country allows for that channel
# (current-max-reg-power on the radio). Medium and low are relative to that maximum, like most controllers do:
# -6 dB is a quarter of the power, -12 dB a sixteenth.
TX_MODES = ("manual", "low", "medium", "high")
TX_STEP = {"medium": 6, "low": 12}
# Used only when the radio does not report current-max-reg-power: EU/ETSI EIRP limits for the
# lowest channels of the band (2.4 GHz 20 dBm, 5 GHz ch 36-64 23 dBm; ch 100-140 allows 30 dBm).
TX_FALLBACK_MAX = {"2g": 20, "5g": 23, "6g": 23}


def radio_tx(site_id: int) -> dict[str, dict]:
    return {r["radio_mac"].upper(): {"mode": r["tx_mode"], "power": r["tx_power"]}
            for r in db.q("SELECT * FROM radio_settings WHERE site_id=?", site_id)}


def radio_max(radio: dict) -> int:
    try:
        return int(float(radio.get("current-max-reg-power")))
    except (TypeError, ValueError):
        return TX_FALLBACK_MAX[_band(radio)]


def tx_dbm(mode: str, power: int | None, max_dbm: int) -> int | None:
    if mode == "manual":
        return min(power, max_dbm) if power else None
    if mode in TX_STEP:
        return max(1, max_dbm - TX_STEP[mode])
    return None


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:20] or "wlan"


def site_wlans(site_id: int) -> list[dict]:
    return db.q("SELECT * FROM wlans WHERE site_id=? ORDER BY position, id", site_id)


# ---- desired state ---------------------------------------------------------

def desired_state(settings: dict, wlans: list[dict], radios: list[dict] | None = None) -> dict:
    """radios: [{mac, band, ax, dbm}] for radios that get their own transmit power."""
    bridge = settings["bridge"]
    ac = bool(settings.get("ac_caps"))
    out = {SEC: {}, DP: {}, CH: {}, CFG: {}, PROV: []}
    active = [w for w in wlans if w["enabled"]]

    if active:
        ch2 = {"width": settings["ch2_width"], "comment": "MikroManager 2.4 GHz"}
        ch5 = {"width": settings["ch5_width"], "skip-dfs-channels": settings["skip_dfs"], "comment": "MikroManager 5 GHz"}
        if settings.get("ch2_freq"):
            ch2["frequency"] = settings["ch2_freq"].replace(" ", "")
        if settings.get("ch5_freq"):
            ch5["frequency"] = settings["ch5_freq"].replace(" ", "")
        out[CH] = {f"{PREFIX}ch-2g": ch2, f"{PREFIX}ch-5g": ch5}
        if ac:
            # wifi-qcom-ac cannot take a VLAN from the datapath (MikroTik docs);
            # those CAPs tag per interface with a bridge PVID instead.
            out[DP][f"{PREFIX}dp-ac"] = {"bridge": bridge, "comment": "MikroManager ac-CAPs (geen VLAN)"}

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

    # Per-radio transmit power: a provisioning rule for exactly that radio (radio-mac), placed before the
    # band rules, with its own copy of the master configuration carrying tx-power. Virtual SSIDs share the radio.
    for r in radios or []:
        drv = "ax" if r["ax"] or not ac else "ac"
        if r.get("local") and not settings.get("local_radios"):
            continue
        cfgs = [f"{PREFIX}{w['slug']}-{r['band']}" + ("-ac" if drv == "ac" else "") for w in active
                if r["band"] in w["bands"].split(",")]
        if not cfgs or r["dbm"] is None:
            continue
        own = f"{cfgs[0]}-r{r['mac'].replace(':', '')[-6:].lower()}"
        out[CFG][own] = {**out[CFG][cfgs[0]], "tx-power": str(r["dbm"]), "comment": f"{out[CFG][cfgs[0]]['comment']} ({r['mac']})"}
        if r.get("local"):
            continue        # the controller's own radios are never provisioned; they use the profile directly
        out[PROV].append({"action": "create-dynamic-enabled", "radio-mac": r["mac"], "master-configuration": own,
                          "slave-configurations": ",".join(cfgs[1:]), "comment": f"{TAG}radio:{r['mac']}"})

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


def tx_radios(site_id: int) -> list[dict]:
    """Radios of this site that have a transmit power other than "high", as input for desired_state()."""
    ctrl = db.controller(site_id)
    s = (STATE.get(ctrl["id"]) or {}) if ctrl else {}
    prefs = radio_tx(site_id)
    out = []
    for r in s.get("wifi_radios") or []:
        mac = (r.get("radio-mac") or "").upper()
        p = prefs.get(mac)
        if not p or p["mode"] == "high":
            continue
        out.append({"mac": mac, "band": _band(r), "ax": "ax" in (r.get("bands") or ""), "local": not r.get("cap"),
                    "dbm": tx_dbm(p["mode"], p["power"], radio_max(r))})
    return out


LOCAL_TAG = f"{TAG}local:"     # comment on the virtual interfaces we add to the controller's own radios
INLINE = ("configuration.", "security.", "datapath.", "channel.")
KEEP_INLINE = {"configuration.manager", "configuration.mode"}


def local_masters(radio_rows: list[dict], wifi_rows: list[dict]) -> list[tuple[dict, dict | None]]:
    """(radio, its interface) for every radio of the controller itself."""
    by_name = {i["name"]: i for i in wifi_rows}
    return [(r, by_name.get(r.get("interface", ""))) for r in radio_rows if not r.get("cap")]


def local_plan(settings: dict, wlans: list[dict], radios: list[dict] | None, radio_rows: list[dict],
               wifi_rows: list[dict]) -> list[dict]:
    """Steps that make the controller's own radios carry the site's SSIDs, the way the MikroTik CAPsMAN manual
    says to do it: set the same configuration profile on the local (static) interfaces yourself. CAPsMAN cannot
    manage its own interfaces, and provisioning them deletes and re-creates them (breaking bridge-port links)."""
    ops: list[dict] = []
    active = [w for w in wlans if w["enabled"]]
    own = {r["mac"]: r for r in radios or []}
    for radio, iface in local_masters(radio_rows, wifi_rows):
        if not iface or truthy(iface.get("dynamic", "false")):
            continue        # still in the provisioned state of an older version; the endpoint repairs that first
        band = _band(radio)
        cfgs = [f"{PREFIX}{w['slug']}-{band}" for w in active if band in w["bands"].split(",")]
        mac = (radio.get("radio-mac") or "").upper()
        master = cfgs[0] if cfgs else None
        if master and mac in own and own[mac]["dbm"] is not None:
            master = f"{master}-r{mac.replace(':', '')[-6:].lower()}"
        name = iface["name"]
        if master:
            data = {}
            if iface.get("configuration") != master:
                data["configuration"] = master
            if truthy(iface.get("disabled", "false")):
                data["disabled"] = "no"
            if data:
                ops.append({"op": "set", "path": WIFI, "id": iface[".id"], "data": data, "local": True,
                            "text": f"Eigen radio {name}: profiel {master}", "show": data})
            for k in [k for k in iface if k.startswith(INLINE) and k not in KEEP_INLINE]:
                ops.append({"op": "unset", "path": WIFI, "id": iface[".id"], "key": k, "local": True,
                            "text": f"Eigen radio {name}: eigen instelling {k} weg (het profiel geldt)"})
        elif str(iface.get("configuration", "")).startswith(PREFIX):
            ops.append({"op": "unset", "path": WIFI, "id": iface[".id"], "key": "configuration", "local": True,
                        "text": f"Eigen radio {name}: geen netwerken meer op deze band"})
        slaves = {i.get("comment", "")[len(LOCAL_TAG):]: i for i in wifi_rows
                  if i.get("master-interface") == name and i.get("comment", "").startswith(LOCAL_TAG)}
        for cfg in cfgs[1:]:
            if cfg not in slaves:
                data = {"master-interface": name, "configuration": cfg, "comment": LOCAL_TAG + cfg, "disabled": "no"}
                ops.append({"op": "add", "path": WIFI, "data": data, "local": True,
                            "text": f"Eigen radio {name}: virtuele interface voor {cfg}", "show": data})
        for cfg, i in slaves.items():
            if cfg not in cfgs[1:]:
                ops.append({"op": "remove", "path": WIFI, "id": i[".id"], "local": True,
                            "text": f"Eigen radio {name}: virtuele interface {i['name']} weg"})
    return ops


async def build_plan(ros: Ros, settings: dict, wlans: list[dict], radios: list[dict] | None = None) -> list[dict]:
    want = desired_state(settings, wlans, radios)
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
                            "text": f"Wijzig provisioning-regel {w.get('supported-bands') or w.get('radio-mac')}", "show": diff})
    else:
        rules_touched = True
        for h in rules:
            ops.append({"op": "remove", "path": PROV, "id": h[".id"],
                        "text": f"Verwijder provisioning-regel {h.get('supported-bands') or h.get('radio-mac', '')}"})
        for w in want[PROV]:
            ops.append({"op": "add", "path": PROV, "data": _clean(w),
                        "text": f"Nieuwe provisioning-regel {w.get('supported-bands') or 'radio ' + w['radio-mac']}",
                        "show": _clean(w)})

    # 2b. the controller's own radios (only after they were handed over in the UI)
    if settings.get("local_radios"):
        ops += local_plan(settings, wlans, radios, await ros.get(RADIO), await ros.get(WIFI))

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
    # The controller's own radios are never provisioned (see local_plan).
    return n


async def release_local(ros: Ros) -> list[str]:
    """Undo the provisioning of the controller's own radios that MikroManager 0.1/0.2 did with "Radio's overnemen".

    MikroTik CAPsMAN manual: "to regain control of local interfaces after provisioning, you will need to disable
    the matching provisioning rules and press "provision" again, which will return local interfaces to an
    unconfigured state." We re-enable our rules straight after, so the access points are not affected.
    """
    done = []
    radio_rows, wifi_rows = await ros.get(RADIO), await ros.get(WIFI)
    stuck = [r for r, i in local_masters(radio_rows, wifi_rows) if i and truthy(i.get("dynamic", "false"))]
    if not stuck:
        return done
    rules = [r for r in await ros.get(PROV) if r.get("comment", "").startswith(TAG) and not truthy(r.get("disabled", "false"))]
    for r in rules:
        await ros.set(PROV, r[".id"], {"disabled": "yes"})
    try:
        for r in stuck:
            await ros.cmd(RADIO + "/provision", {"numbers": r[".id"]})
        done.append(f"{len(stuck)} eigen radio('s) losgemaakt van de provisioning (staan nu onbeheerd)")
    finally:
        for r in rules:
            await ros.set(PROV, r[".id"], {"disabled": "no"})
    return done


async def unmanage_local(ros: Ros) -> list[str]:
    """Remove MikroManager's profiles and virtual interfaces from the controller's own radios."""
    done = []
    radio_rows, wifi_rows = await ros.get(RADIO), await ros.get(WIFI)
    for radio, iface in local_masters(radio_rows, wifi_rows):
        if not iface:
            continue
        for i in wifi_rows:
            if i.get("master-interface") == iface["name"] and i.get("comment", "").startswith(LOCAL_TAG):
                await ros.remove(WIFI, i[".id"])
                done.append(f"{i['name']} verwijderd")
        if str(iface.get("configuration", "")).startswith(PREFIX):
            await ros.cmd(WIFI + "/unset", {".id": iface[".id"], "value-name": "configuration"})
            done.append(f"{iface['name']}: profiel van MikroManager weg")
    return done


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
            await ap.add(DP, {"name": dp_name, "bridge": bridge, "comment": "MikroManager CAP"})
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
    prefs = radio_tx(site_id)

    def ssid_of(i: dict) -> str | None:
        cfg = re.sub(r"-r[0-9a-f]{6}$", "", i.get("configuration", ""))     # per-radio copy of a master configuration
        return i.get("configuration.ssid") or cfg_ssid.get(cfg)

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
                "dynamic": truthy(i.get("dynamic", "false")),
                "tx": {**(prefs.get((r.get("radio-mac") or "").upper()) or {"mode": "high", "power": None}),
                       "max": radio_max(r), "max_reported": r.get("current-max-reg-power") is not None,
                       "presets": {m: tx_dbm(m, None, radio_max(r)) for m in ("low", "medium")}},
                "local": not r.get("cap"), "provisioned_local": not r.get("cap") and truthy(i.get("dynamic", "false"))}

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
                        "state": "Wacht op controller" if cap_on else "Niet geadopteerd",
                        "device_id": d["id"], "radios": [], "adoptable": bool(ds.get("online")) and not cap_on})
    return out
