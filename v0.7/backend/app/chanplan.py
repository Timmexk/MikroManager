"""Automatic channel plan: give every managed radio a channel its neighbours do not use.

1. Every radio scans its surroundings once (`/interface/wifi/scan`, on the device that owns the radio). That shows
   the networks of the neighbours (with signal) and our own access points (by BSSID), so we know which of our
   radios hear each other and how busy each channel is.
2. Radios are handled busiest first. Each gets the channel with the lowest cost:
     - neighbours' networks on an overlapping channel, weighted by signal (a network at -60 dBm counts more than
       one at -85);
     - our own radios already placed on an overlapping channel, heavily when they hear each other;
     - a small extra for DFS channels (the radio waits 1-10 minutes for radar before it transmits) and a small
       bonus for staying on the current channel (no reason to move for a hair).
   "Overlapping" follows the channel width: with 80 MHz, 5180-5240 is one block.
3. Transmit power: radios that hear one of our other radios very strongly (stronger than -55 dBm) get the advice
   "medium", so clients roam to the nearer one instead of hanging on.

The plan is a proposal; applying it writes the channel (and optionally power) per radio and applies the wifi
settings like any other change.
"""
import time

from . import db, localwifi, wifi
from .poller import STATE
from .ros import Ros, RosError

CH24 = [2412, 2437, 2462]
DFS = (5260, 5720)


def _block(freq: int, width: str) -> tuple:
    """Frequencies that overlap share a block: 2.4 GHz always 1/6/11 separately (20 MHz), 5 GHz by width."""
    if freq < 3000:
        return ("2g", round((freq - 2412) / 25))
    size = 4 if "80" in width else 2 if "40" in width else 1
    if "160" in width:
        size = 8
    base = 5180 if freq < 5400 else 5500
    return ("5g", base, ((freq - base) // 20) // size)


def _weight(signal) -> float:
    try:
        s = float(signal)
    except (TypeError, ValueError):
        return 0.5
    return max(0.2, (s + 92) / 8)       # -60 dBm -> 4, -84 -> 1


def _freq(ch) -> int | None:
    try:
        return int(str(ch).split("/")[0].split(",")[0])
    except (TypeError, ValueError):
        return None


def managed_radios(site_id: int) -> list[dict]:
    """Radios the site manages (router radios on site networks, and the access points' radios)."""
    out = []
    for ap in wifi.access_points(site_id):
        for r in ap.get("radios") or []:
            if r.get("standalone") or (r.get("local") and r.get("local_mode") != "site"):
                continue
            if not r.get("mac"):
                continue
            out.append({"ap": ap["name"], "device_id": ap.get("device_id"), **r})
    return out


async def propose(site_id: int, measure: bool = True) -> dict:
    site = db.get_site(site_id)
    settings = site["settings"]
    radios = managed_radios(site_id)
    ctrl = db.controller(site_id)
    cs = (STATE.get(ctrl["id"]) or {}) if ctrl else {}
    # BSSID -> radio mac, for all our interfaces the controller knows (masters and virtual SSIDs)
    by_mac = {r["mac"].upper(): r["mac"].upper() for r in radios}
    ifaces = cs.get("wifi_ifaces") or []
    radio_of_iface = {r.get("interface"): (r.get("radio-mac") or "").upper() for r in cs.get("wifi_radios") or []}
    for i in ifaces:
        root = i.get("master-interface") or i.get("name")
        rm = radio_of_iface.get(root)
        if rm and i.get("mac-address"):
            by_mac[i["mac-address"].upper()] = rm

    heard: dict[str, list[dict]] = {}       # radio mac -> scan rows
    hears: dict[tuple[str, str], float] = {}  # (a, b) -> strongest signal a hears from b
    errors = []
    if measure:
        for r in radios:
            try:
                w = _where(site_id, r["mac"])
                if not w:
                    errors.append(f"{r['ap']} {wifi_band(r)}: access point niet als apparaat toegevoegd, niet gemeten")
                    continue
                rows = await localwifi.scan(Ros.for_device(w[0]), w[1], "networks")
            except RosError as e:
                errors.append(f"{r['ap']} {wifi_band(r)}: {e}")
                continue
            heard[r["mac"].upper()] = rows
            for row in rows:
                other = by_mac.get(str(row.get("address", "")).upper())
                if other and other != r["mac"].upper():
                    key = (r["mac"].upper(), other)
                    hears[key] = max(hears.get(key, -200), float(row.get("signal") or -200))

    def candidates(r: dict) -> list[int]:
        if r["band"] == "2g":
            return [c for c in CH24 if not r.get("channels") or c in r["channels"]]
        chans = r.get("channels") or [5180, 5200, 5220, 5240]
        if settings.get("skip_dfs") == "all":
            chans = [c for c in chans if not DFS[0] <= c <= DFS[1]]
        width = r.get("tx", {}).get("width") or settings.get("ch5_width") or ""
        seen, out = set(), []
        for c in chans:                     # one candidate per block: its lowest channel
            b = _block(c, width)
            if b not in seen:
                seen.add(b)
                out.append(c)
        return out

    placed: dict[str, int] = {}
    result = []
    order = sorted(radios, key=lambda r: (-(r.get("clients") or 0), r["ap"], r["band"]))
    for r in order:
        mac = r["mac"].upper()
        width = (r.get("tx") or {}).get("width") or (settings.get("ch2_width") if r["band"] == "2g" else settings.get("ch5_width")) or ""
        cur = r.get("frequency")
        best, best_cost, why = None, None, ""
        for c in candidates(r):
            blk = _block(c, width)
            ext = sum(_weight(row.get("signal")) for row in heard.get(mac, [])
                      if not by_mac.get(str(row.get("address", "")).upper())
                      and _freq(row.get("channel")) and _block(_freq(row.get("channel")), width) == blk)
            own = 0.0
            for other, f in placed.items():
                if _block(f, width) != blk:
                    continue
                s = max(hears.get((mac, other), -200), hears.get((other, mac), -200))
                own += 10 if s > -80 else 2
            cost = ext + own + (0.5 if DFS[0] <= c <= DFS[1] else 0) - (0.3 if cur and _block(cur, width) == blk else 0)
            if best_cost is None or cost < best_cost - 1e-9:
                best, best_cost = c, cost
                why = ("geen buren en geen eigen AP op dit kanaal" if ext == 0 and own == 0
                       else f"rustigste kanaal (buren {ext:.1f}, eigen AP's {own:.0f})")
        if best is None:
            continue
        placed[mac] = best
        strongest = max([s for (a, b), s in hears.items() if a == mac or b == mac] or [-200])
        tx_now = (r.get("tx") or {}).get("mode", "high")
        power = "medium" if strongest > -55 and tx_now == "high" else None
        result.append({"mac": r["mac"], "ap": r["ap"], "band": r["band"], "current": cur, "proposed": best,
                       "change": not cur or _block(cur, width) != _block(best, width) or (cur != best and r["band"] == "2g"),
                       "reason": why, "dfs": DFS[0] <= best <= DFS[1], "clients": r.get("clients") or 0,
                       "power_now": tx_now, "power_advice": power,
                       "power_reason": f"hoort een eigen AP op {strongest:.0f} dBm" if power else None,
                       "measured": mac in heard})
    db.log(site_id, f"Kanaalplan berekend voor {len(result)} radio's" + (f" ({len(heard)} gemeten)" if measure else ""))
    return {"radios": sorted(result, key=lambda x: (x["ap"], x["band"])), "errors": errors, "measured": bool(heard),
            "when": time.time()}


def wifi_band(r: dict) -> str:
    return "2,4 GHz" if r["band"] == "2g" else "5 GHz"


def _where(site_id: int, mac: str):
    """(device, interface name on that device) that owns this radio, for the scan."""
    mac = mac.upper()
    for d in db.site_devices(site_id):
        s = STATE.get(d["id"]) or {}
        for r in s.get("wifi_radios") or []:
            if (r.get("radio-mac") or "").upper() == mac and not r.get("cap") and r.get("interface"):
                return d, r["interface"]
    return None


async def apply(site_id: int, items: list[dict], with_power: bool) -> int:
    """Write the chosen channels (and power advice) as per-radio settings."""
    n = 0
    prefs = wifi.radio_tx(site_id)
    for it in items:
        mac = str(it["mac"]).upper()
        freq = str(int(it["proposed"]))
        p = prefs.get(mac) or {"mode": "high", "power": None, "width": "", "ssids": None, "off": False}
        mode = it.get("power_advice") if with_power and it.get("power_advice") else p["mode"]
        db.x("INSERT INTO radio_settings (site_id, radio_mac, tx_mode, tx_power, freq, width) VALUES (?,?,?,?,?,?) "
             "ON CONFLICT(site_id, radio_mac) DO UPDATE SET freq=excluded.freq, tx_mode=excluded.tx_mode",
             site_id, mac, mode, p.get("power"), freq, p.get("width") or "")
        n += 1
    return n
