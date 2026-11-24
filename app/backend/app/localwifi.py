"""Local wifi: radios that are set up on the device itself, without CAPsMAN and without the site's profiles.

Two kinds of devices have them:
  - a standalone access point: a MikroTik with wifi that is not a CAP (for example a hAP elsewhere in the house);
  - the controller itself, for a radio the user switched to "zelfstandig" (standalone).

Settings are written as inline properties on the wifi interface, the way the MikroTik manual shows it:
  /interface/wifi set wifi1 configuration.ssid=... security.authentication-types=... security.passphrase=...
  /interface/wifi add master-interface=wifi1 configuration.ssid=...      (an extra SSID)
Inline properties win over a configuration profile the interface may also use.

Also here: radio insight (monitor, registration table) and the two scans RouterOS offers. Both scans take the
radio off the air while they run ("Running a frequency scan will disconnect all connected clients").
"""
import re

from . import db, wifi
from .config import tag
from .poller import STATE
from .ros import Ros, RosError, truthy

WIFI = wifi.WIFI
AUTH = wifi.AUTH
AUTH_BACK = {",".join(sorted(v.split(","))) if v else "": k for k, v in AUTH.items()}
OWN_TAG = "own:"          # comment on extra SSIDs made while converting a router radio to standalone


def own_comment() -> str:
    return f"{tag()}{OWN_TAG}"


def _profiles(rows: dict[str, list[dict]]) -> dict[str, dict[str, dict]]:
    return {k: {r.get("name"): r for r in v} for k, v in rows.items()}


async def read_profiles(ros: Ros) -> dict[str, dict[str, dict]]:
    out = {}
    for key, path in (("cfg", wifi.CFG), ("sec", wifi.SEC), ("dp", wifi.DP), ("ch", wifi.CH)):
        try:
            out[key] = await ros.get(path)
        except RosError:
            out[key] = []
    return _profiles(out)


def effective(i: dict, prof: dict[str, dict[str, dict]]) -> dict:
    """What the interface really uses: inline values first, then its configuration profile and the profiles that
    one refers to."""
    cfg = prof["cfg"].get(i.get("configuration")) or {}

    def pick(part: str, key: str, cfg_key: str | None = None):
        if f"{part}.{key}" in i:
            return i[f"{part}.{key}"]
        if part == "configuration":
            return cfg.get(cfg_key or key)
        if f"{part}.{key}" in cfg:
            return cfg[f"{part}.{key}"]
        ref = i.get(part) or cfg.get(part)
        table = {"security": "sec", "datapath": "dp", "channel": "ch"}[part]
        return (prof[table].get(ref) or {}).get(key)

    auth = wifi._text(pick("security", "authentication-types"))
    key = ",".join(sorted(x for x in auth.split(",") if x))
    vlan = pick("datapath", "vlan-id")
    return {
        "ssid": pick("configuration", "ssid"), "hidden": truthy(pick("configuration", "hide-ssid") or "false"),
        "country": pick("configuration", "country"), "tx_power": pick("configuration", "tx-power"),
        "mode": pick("configuration", "mode") or "ap",
        "security": AUTH_BACK.get(key, "other"), "auth_raw": auth,
        "passphrase": pick("security", "passphrase") or "", "ft": truthy(pick("security", "ft") or "false"),
        "frequency": wifi._text(pick("channel", "frequency")), "width": pick("channel", "width") or "",
        "bridge": pick("datapath", "bridge") or "", "vlan_id": int(vlan) if str(vlan or "").isdigit() else None,
        "isolation": truthy(pick("datapath", "client-isolation") or "false"),
    }


def device_kind(dev: dict) -> str:
    """controller | cap | standalone | none (no wifi)."""
    s = STATE.get(dev["id"]) or {}
    if s.get("wifi_ifaces") is None:
        return "none"
    if dev.get("is_controller"):
        return "controller"
    if truthy((s.get("wifi_cap") or {}).get("enabled", "false")):
        return "cap"
    return "standalone"


async def device_wifi(dev: dict, site: dict) -> dict:
    """Radios of one device with their interfaces, effective settings and whether they may be edited here."""
    ros = Ros.for_device(dev)
    kind = device_kind(dev)
    radios, ifaces = await ros.get(wifi.RADIO), await ros.get(WIFI)
    prof = await read_profiles(ros)
    prefs = wifi.radio_tx(site["id"])
    s = STATE.get(dev["id"]) or {}
    mon = s.get("wifi_mon") or {}
    reg = s.get("wifi_reg") or []
    out = []
    for r in radios:
        if r.get("cap"):
            continue        # on a controller: radios of the access points, managed through CAPsMAN
        name = r.get("interface", "")
        master = next((i for i in ifaces if i["name"] == name), None)
        if not master:
            continue
        mac = (r.get("radio-mac") or "").upper()
        mode = wifi.local_mode(site["settings"], prefs.get(mac)) if kind == "controller" else ("own" if kind == "standalone" else "cap")
        own = mode == "own"
        site_managed = mode == "site"
        reason = None
        if kind == "controller" and mode == "none":
            reason = "MikroManager beheert deze radio niet. Kies 'Zelfstandig' om hem hier in te stellen, of 'Site-netwerken'."
        if kind == "cap":
            reason = "Dit apparaat is een CAP: de controller stelt de radio's in."
        elif truthy(master.get("dynamic", "false")):
            reason = "Deze radio is geprovisioned door CAPsMAN."
        elif site_managed:
            reason = "Deze radio zendt de netwerken van de site uit. Maak hem zelfstandig om hem hier los in te stellen."
        members = [master] + [i for i in ifaces if i.get("master-interface") == name]
        ports = {p.get("interface"): p for p in s.get("bridge_ports") or []}
        out.append({
            "mac": mac, "band": wifi._band(r), "interface": name, "radio_id": r.get(".id"),
            "channels": wifi.channels_of(r), "widths": wifi.WIDTHS[wifi._band(r)], "max": wifi.radio_max(r),
            "monitor": mon.get(name) or {}, "frequency": wifi._freq((mon.get(name) or {}).get("channel")),
            "editable": reason is None and own, "reason": reason, "own": own, "site_managed": site_managed, "mode": mode,
            "clients": sum(1 for c in reg if c.get("interface") in {m["name"] for m in members}),
            "interfaces": [{
                "id": i[".id"], "name": i["name"], "master": i is master, "disabled": truthy(i.get("disabled", "false")),
                "running": truthy(i.get("running", "false")), "profile": i.get("configuration") or None,
                "comment": i.get("comment") or "", **effective(i, prof),
                "port_bridge": (ports.get(i["name"]) or {}).get("bridge"), "port_pvid": (ports.get(i["name"]) or {}).get("pvid"),
            } for i in members],
        })
    return {"kind": kind, "radios": out, "bridges": [b["name"] for b in s.get("bridges") or []]}


def inline(body: dict, master: bool) -> tuple[dict, list[str]]:
    """Form fields -> inline properties to set, and properties to unset (empty = back to default)."""
    data: dict[str, str] = {}
    unset: list[str] = []
    if "ssid" in body:
        ssid = (body.get("ssid") or "").strip()
        if not 1 <= len(ssid.encode()) <= 32:
            raise ValueError("SSID moet 1 tot 32 tekens zijn")
        data["configuration.ssid"] = ssid
    if "security" in body:
        sec = body["security"]
        if sec not in AUTH:
            raise ValueError("Kies open, WPA2, WPA2 + WPA3 of WPA3")
        data["security.authentication-types"] = AUTH[sec]
        if sec != "open":
            pw = body.get("passphrase") or ""
            if not 8 <= len(pw) <= 63:
                raise ValueError("Wachtwoord moet 8 tot 63 tekens zijn")
            data["security.passphrase"] = pw
            data["security.ft"] = "yes" if body.get("ft") else "no"
            data["security.ft-over-ds"] = data["security.ft"]
    if "hidden" in body:
        data["configuration.hide-ssid"] = "yes" if body["hidden"] else "no"
    if "disabled" in body:
        data["disabled"] = "yes" if body["disabled"] else "no"
    if "bridge" in body:
        if body.get("bridge"):
            data["datapath.bridge"] = body["bridge"]
        else:
            unset.append("datapath.bridge")
    if "vlan_id" in body:
        v = body.get("vlan_id")
        if v in (None, ""):
            unset.append("datapath.vlan-id")
        else:
            if not 1 <= int(v) <= 4094:
                raise ValueError("VLAN-ID moet tussen 1 en 4094 liggen")
            data["datapath.vlan-id"] = str(int(v))
    if "isolation" in body:
        data["datapath.client-isolation"] = "yes" if body["isolation"] else "no"
    if master:
        if "country" in body and body.get("country"):
            data["configuration.country"] = body["country"]
        if "frequency" in body:
            f = str(body.get("frequency") or "").replace(" ", "")
            if f and not wifi.FREQ_LIST.match(f):
                raise ValueError("Kanaal: geef een of meer frequenties in MHz, bijvoorbeeld 5180")
            (data.__setitem__("channel.frequency", f) if f else unset.append("channel.frequency"))
        if "width" in body:
            w = body.get("width") or ""
            if w and w not in {x for ws in wifi.WIDTHS.values() for x in ws}:
                raise ValueError("Onbekende kanaalbreedte")
            (data.__setitem__("channel.width", w) if w else unset.append("channel.width"))
        if "tx_power" in body:
            p = body.get("tx_power")
            if p in (None, ""):
                unset.append("configuration.tx-power")
            else:
                if not 1 <= int(p) <= 30:
                    raise ValueError("Zendvermogen moet tussen 1 en 30 dBm liggen")
                data["configuration.tx-power"] = str(int(p))
    return data, unset


async def _unset(ros: Ros, iface_id: str, keys: list[str], have: dict) -> None:
    for k in keys:
        if k in have:
            try:
                await ros.cmd(WIFI + "/unset", {".id": iface_id, "value-name": k})
            except RosError:
                pass        # not set, or not settable on this version: nothing to undo


async def save_interface(ros: Ros, iface: dict, body: dict) -> None:
    data, unset = inline(body, not iface.get("master-interface"))
    if data:
        await ros.set(WIFI, iface[".id"], data)
    await _unset(ros, iface[".id"], unset, iface)


async def add_virtual(ros: Ros, master: dict, body: dict) -> dict:
    data, _ = inline({"hidden": False, "isolation": False, **body}, False)
    if "configuration.ssid" not in data or "security.authentication-types" not in data:
        raise ValueError("Vul een SSID en de beveiliging in")
    data.update({"master-interface": master["name"], "configuration.mode": "ap", "disabled": "no",
                 "comment": body.get("comment") or "MikroManager"})
    return await ros.add(WIFI, data)


async def make_own(ros: Ros, radio_iface: str) -> list[str]:
    """Turn a router radio that carries the site's networks into a standalone one that keeps broadcasting the
    same SSIDs: the effective settings of the profiles become inline properties, the profile reference goes,
    MikroManager's virtual interfaces get the 'own' mark so the site plan leaves them alone."""
    prof = await read_profiles(ros)
    ifaces = await ros.get(WIFI)
    master = next((i for i in ifaces if i["name"] == radio_iface), None)
    if not master:
        raise RosError(f"Interface {radio_iface} niet gevonden")
    members = [master] + [i for i in ifaces if i.get("master-interface") == radio_iface]
    done = []
    for i in members:
        e = effective(i, prof)
        if not i.get("configuration"):
            continue
        body = {"ssid": e["ssid"] or "MikroTik", "security": e["security"] if e["security"] != "other" else "wpa2wpa3",
                "passphrase": e["passphrase"], "ft": e["ft"], "hidden": e["hidden"], "isolation": e["isolation"],
                "bridge": e["bridge"], "vlan_id": e["vlan_id"]}
        if e["security"] == "open":
            body.pop("passphrase")
        data, _ = inline(body, False)
        if i is master:
            if e["country"]:
                data["configuration.country"] = e["country"]
            if e["tx_power"]:
                data["configuration.tx-power"] = str(e["tx_power"])
            if e["frequency"]:
                data["channel.frequency"] = e["frequency"]
            if e["width"]:
                data["channel.width"] = e["width"]
        else:
            data["comment"] = own_comment() + (e["ssid"] or i["name"])
        await ros.set(WIFI, i[".id"], data)
        await ros.cmd(WIFI + "/unset", {".id": i[".id"], "value-name": "configuration"})
        done.append(f"{i['name']}: {e['ssid']} staat nu op de interface zelf")
    return done


async def back_to_site(ros: Ros, radio_iface: str) -> list[str]:
    """Undo make_own: remove the extra SSIDs made standalone; the site plan sets the profiles again."""
    done = []
    for i in await ros.get(WIFI):
        if i.get("master-interface") == radio_iface and str(i.get("comment", "")).startswith(own_comment()):
            await ros.remove(WIFI, i[".id"])
            done.append(f"{i['name']} verwijderd")
    return done


# ---- insight ----------------------------------------------------------------

def clients_of(dev: dict, iface_names: set[str]) -> list[dict]:
    s = STATE.get(dev["id"]) or {}
    out = []
    for r in s.get("wifi_reg") or []:
        if r.get("interface") not in iface_names:
            continue
        tx, rx = r.get("tx-rate"), r.get("rx-rate")
        out.append({"mac": (r.get("mac-address") or "").upper(), "interface": r.get("interface"), "ssid": r.get("ssid"),
                    "signal": _int(r.get("signal")), "tx_rate": tx, "rx_rate": rx, "uptime": r.get("uptime"),
                    "band": r.get("band"), "auth": r.get("auth-type"), "host": r.get("dhcp-hostname"),
                    "ip": r.get("dhcp-address"),
                    "tx_bps": _int(r.get("tx-bits-per-second")), "rx_bps": _int(r.get("rx-bits-per-second"))})
    names = {r["mac"]: r["name"] for r in db.q("SELECT mac, name FROM client_names WHERE site_id=?", dev["site_id"])}
    for c in out:
        c["name"] = names.get(c["mac"]) or c["host"]
    out.sort(key=lambda c: -(c["signal"] or -200))
    return out


def _int(v):
    try:
        return int(float(str(v).split(",")[0]))
    except (TypeError, ValueError):
        return None


_NUM = re.compile(r"^-?\d+(\.\d+)?$")


def _scan_rows(rows) -> list[dict]:
    """REST returns the rows of the last round; keep only the ones with data and turn numbers into numbers."""
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        out.append({k: (float(v) if isinstance(v, str) and _NUM.match(v) else v) for k, v in r.items() if k != ".section"})
    return out


async def scan(ros: Ros, iface: str, kind: str, rounds: int = 1) -> list[dict]:
    """kind: 'networks' (scan: access points in range) or 'channels' (frequency-scan: load and noise per channel).
    The radio stops serving clients while it scans."""
    cmd = "/scan" if kind == "networks" else "/frequency-scan"
    rows = await ros.cmd(WIFI + cmd, {"numbers": iface, "rounds": str(max(1, min(3, rounds)))}, timeout=90)
    rows = _scan_rows(rows)
    if kind == "networks":
        best: dict[str, dict] = {}
        for r in rows:
            a = str(r.get("address", "")).upper()
            if a and (a not in best or (r.get("signal") or -200) > (best[a].get("signal") or -200)):
                best[a] = r
        rows = sorted(best.values(), key=lambda r: -(r.get("signal") or -200))
    else:
        rows.sort(key=lambda r: wifi._freq(r.get("channel")) or 0)
    return rows
