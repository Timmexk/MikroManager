"""End-to-end test: real MikroManager server against the simulated routers.

Run:  python tests/test_e2e.py      (from the backend/ folder)
Covers the full flow a new install goes through, without seeded data.
"""
import os
import subprocess
import sys
import tempfile
import time

import httpx

PORT = 18990
BASE = f"http://127.0.0.1:{PORT}"
MOCK = 18981
DEV = {"scheme": "http", "username": "tikcontrol", "password": "demo-pass", "host": "127.0.0.1"}
passed = 0


def check(cond, label):
    global passed
    if not cond:
        raise AssertionError(label)
    passed += 1
    print(f"  ok  {label}")


def wait(fn, label, timeout=40):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.5)
    raise AssertionError(f"timeout: {label}")


def main():
    data = tempfile.mkdtemp()
    env = {**os.environ, "TIKCONTROL_DEMO": "1", "TIKCONTROL_DEMO_SEED": "0", "TIKCONTROL_DATA": data,
           "TIKCONTROL_POLL": "2", "MOCK_REBOOT_SECS": "4", "TIKCONTROL_SAFE_SECS": "8", "TIKCONTROL_SAFE_CHECK_SECS": "4",
           "TIKCONTROL_LIVE_INTERVAL": "1", "TIKCONTROL_LIVE_PING_EVERY": "2", "MOCK_BASE_PORT": str(MOCK), "TIKCONTROL_STATIC": "/nonexistent"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"], env=env)
    c = httpx.Client(base_url=BASE, timeout=60)
    try:
        wait(lambda: _up(c), "server start")
        run(c)
        print(f"\n{passed} checks passed")
    finally:
        proc.terminate()
        proc.wait(10)


def _get_ok(cl, path):
    try:
        return cl.get(path).status_code == 200
    except httpx.HTTPError:
        return False


def _up(c):
    try:
        return c.get("/api/state").status_code == 200
    except httpx.HTTPError:
        return False


def run(c):
    print("auth")
    check(c.get("/api/state").json()["setup_needed"], "fresh install asks for setup")
    check(c.get("/api/sites").status_code == 401, "API is closed without a session")
    check(c.post("/api/setup", json={"username": "admin", "password": "kort"}).status_code == 400, "short password refused")
    check(c.post("/api/setup", json={"username": "admin", "password": "geheim-wachtwoord"}).status_code == 200, "setup")
    check(c.post("/api/setup", json={"username": "x", "password": "nog-een-wachtwoord"}).status_code == 400, "second setup refused")
    anon = httpx.Client(base_url=BASE)
    check(anon.post("/api/login", json={"username": "admin", "password": "fout"}).status_code == 401, "wrong password refused")
    check(anon.post("/api/login", json={"username": "admin", "password": "geheim-wachtwoord"}).status_code == 200, "login")

    print("sites and devices")
    sid = c.post("/api/sites", json={"name": "Thuis"}).json()["id"]
    r = c.post(f"/api/sites/{sid}/devices", json={**DEV, "port": MOCK, "password": "fout", "role": "router"})
    check(r.status_code == 400 and "geweigerd" in r.json()["detail"], "wrong router password gives a clear error")
    r = c.post(f"/api/sites/{sid}/devices", json={**DEV, "port": 1, "role": "router"})
    check(r.status_code == 502, "unreachable router reported as such")
    ids = {}
    for key, port, role in (("router", MOCK, "router"), ("crs", MOCK + 1, "switch"), ("hexpoe", MOCK + 2, "switch"),
                            ("ap1", MOCK + 3, "ap"), ("ap2", MOCK + 4, "ap")):
        d = c.post(f"/api/sites/{sid}/devices", json={**DEV, "port": port, "role": role}).json()
        ids[key] = d["id"]
    devs = c.get(f"/api/sites/{sid}/devices").json()
    check(len(devs) == 5 and all(d["online"] for d in devs), "five devices online")
    check(devs[0]["is_controller"] and devs[0]["board"] == "hAP ax^2", "first router becomes controller")
    check("password" not in str(devs).lower().replace("password_enc", ""), "no credentials in device list")
    det = c.get(f"/api/devices/{ids['hexpoe']}").json()
    check(sum(1 for p in det["ports"] if p["poe"] and p["poe"]["power"]) == 2 and det["poe_total"] > 10, "PoE draw per port")
    det = c.get(f"/api/devices/{ids['router']}").json()
    check(det["wan"] == "ether1" and any(p["wan"] for p in det["ports"]), "WAN port detected from default route")
    check(next(p for p in det["ports"] if p["name"] == "ether2")["speed"] == "1Gbps", "link speed")

    print("networks")
    n = c.get(f"/api/sites/{sid}/networks").json()
    check(len(n["networks"]) == 2 and n["bridge"]["vlan_filtering"], "existing networks listed, none managed")
    check(not any(x["managed"] for x in n["networks"]), "hand-made networks are not marked as managed")
    bad = c.post(f"/api/sites/{sid}/networks", json={"name": "Fout", "vlan_id": 30, "subnet": "192.168.88.128/25"})
    check(bad.status_code == 400 and "overlapt" in bad.json()["detail"], "overlapping subnet refused")
    r = c.post(f"/api/sites/{sid}/networks", json={"name": "IoT", "vlan_id": 30, "subnet": "192.168.30.0/24", "tagged_ports": ["ether2"]})
    check(r.status_code == 200 and len(r.json()["steps"]) == 6, "IoT network created in 6 steps")
    r = c.post(f"/api/sites/{sid}/networks", json={"name": "Gasten", "vlan_id": 40, "subnet": "192.168.40.0/24",
                                                   "tagged_ports": ["ether2"], "isolate": True, "interface_list": "LAN"})
    check(r.status_code == 200, "guest network with isolation")
    rt = httpx.Client(base_url=f"http://127.0.0.1:{MOCK}/rest", auth=("tikcontrol", "demo-pass"))
    fw = [f for f in rt.get("/ip/firewall/filter").json() if f["chain"] == "forward"]
    pos = next(i for i, f in enumerate(fw) if "isolatie" in f.get("comment", ""))
    check(fw[pos - 1]["action"] == "accept" and "established" in fw[pos - 1]["connection-state"], "isolation rule sits right after established accept")
    dup = c.post(f"/api/sites/{sid}/networks", json={"name": "Dubbel", "vlan_id": 40, "subnet": "192.168.50.0/24"})
    check(dup.status_code == 400, "duplicate VLAN refused")
    # rollback: a VLAN on a bridge that does not exist fails at step 1 and leaves nothing
    c.patch(f"/api/sites/{sid}", json={"settings": {"bridge": "bestaat-niet"}})
    before = len(rt.get("/ip/pool").json())
    r = c.post(f"/api/sites/{sid}/networks", json={"name": "Kapot", "vlan_id": 77, "subnet": "192.168.77.0/24"})
    check(r.status_code == 400 and len(rt.get("/ip/pool").json()) == before and not rt.get("/interface/vlan", params={"name": "tc-kapot"}).json(), "failed create rolls back")
    c.patch(f"/api/sites/{sid}", json={"settings": {"bridge": "bridge"}})

    print("wifi")
    w = c.get(f"/api/sites/{sid}/wifi").json()
    check(w["pending"]["count"] == 0 and w["controller"]["has_wifi_menu"], "nothing pending on a clean site")
    check(c.post(f"/api/sites/{sid}/wifi/wlans", json={"ssid": "Thuis", "passphrase": "kort"}).status_code == 400, "short passphrase refused")
    thuis = c.post(f"/api/sites/{sid}/wifi/wlans", json={"ssid": "Thuis", "passphrase": "correct-paard-batterij"}).json()
    c.post(f"/api/sites/{sid}/wifi/wlans", json={"ssid": "Thuis-IoT", "passphrase": "slimme-lampen", "security": "wpa2", "vlan_id": 30})
    gast = c.post(f"/api/sites/{sid}/wifi/wlans", json={"ssid": "Thuis-Gast", "passphrase": "welkom-bij-ons", "vlan_id": 40, "bands": ["5g"], "isolation": True}).json()
    plan = c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"]
    check(len(plan) == 17, f"plan has 17 steps (got {len(plan)})")
    check("correct-paard" not in str(plan), "passphrases are masked in the plan preview")
    check(not rt.get("/interface/wifi/security").json(), "preview changes nothing on the router")
    res = c.post(f"/api/sites/{sid}/wifi/apply").json()
    check(res["ok"] and res["remaining"] == 0, "apply succeeds")
    check(c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"] == [], "second plan is empty (idempotent)")
    sec = {s["name"]: s for s in rt.get("/interface/wifi/security").json()}
    check(sec["tc-thuis"]["authentication-types"] == "wpa2-psk,wpa3-psk" and sec["tc-thuis"]["ft"] == "true", "security profile on router")
    dp = {d["name"]: d for d in rt.get("/interface/wifi/datapath").json()}
    check(dp["tc-thuis-iot"]["vlan-id"] == "30" and "vlan-id" not in dp["tc-thuis"], "VLAN in datapath")
    rules = rt.get("/interface/wifi/provisioning").json()
    check([r["supported-bands"] for r in rules] == ["2ghz-ax", "5ghz-ax"], "two provisioning rules")
    check(rules[1]["slave-configurations"] == "tc-thuis-iot-5g,tc-thuis-gast-5g" and rules[0]["slave-configurations"] == "tc-thuis-iot-2g", "guest SSID only on 5 GHz")
    check(rt.get("/interface/wifi/capsman").json()["enabled"] == "true", "CAPsMAN enabled")

    print("adopting APs")
    aps = c.get(f"/api/sites/{sid}/wifi").json()["aps"]
    check(sum(1 for a in aps if a.get("adoptable")) == 2, "two APs waiting to be adopted")
    for k in ("ap1", "ap2"):
        check(c.post(f"/api/devices/{ids[k]}/adopt").status_code == 200, f"adopt {k}")
    aps = c.get(f"/api/sites/{sid}/wifi").json()["aps"]
    caps = [a for a in aps if not a["local"]]
    check(len(caps) == 2 and all(len(a["radios"]) == 2 and a["state"] == "Ok" and a["device_id"] for a in caps), "both APs joined with 2 radios each")
    r5 = next(r for r in caps[0]["radios"] if r["band"] == "5g")
    check(r5["ssids"] == ["Thuis", "Thuis-IoT", "Thuis-Gast"] and r5["channel"], "5 GHz radio carries three SSIDs")
    local = next(a for a in aps if a["local"])
    check(not any(r["managed"] for r in local["radios"]), "controller's own radios untouched until asked")
    check(c.post(f"/api/sites/{sid}/wifi/local-radios").status_code == 200, "take over local radios")
    local = next(a for a in c.get(f"/api/sites/{sid}/wifi").json()["aps"] if a["local"])
    check(all(r["managed"] for r in local["radios"]), "local radios now managed")

    print("clients")
    cl = wait(lambda: (x := c.get(f"/api/sites/{sid}/clients").json()) and sum(1 for i in x if i["online"]) >= 19 and x, "clients appear")
    check(len(cl) == 19, f"19 clients, no infrastructure MACs (got {len(cl)})")
    wifi_cl = [x for x in cl if x["type"] == "wifi"]
    check(len(wifi_cl) == 13 and all(x["wifi"]["ssid"] and x["wifi"]["ap"] and x["ip"] for x in wifi_cl), "wifi clients have SSID, AP and IP")
    iph = next(x for x in cl if x["hostname"] == "iPhone")
    check(iph["wifi"]["ap"] == "cAP-ax-woonkamer" and iph["wifi"]["band"].startswith("5ghz"), "client mapped to the right AP")
    nas = next(x for x in cl if x["hostname"] == "nas")
    check(nas["wired"]["device"] == "CRS310-kantoor" and nas["wired"]["port"] == "ether3", "wired client located on its edge port")
    c.post(f"/api/sites/{sid}/clients/{iph['mac']}/name", json={"name": "Telefoon Timothy"})
    c.post(f"/api/sites/{sid}/clients/{nas['mac']}/static", json={})
    cl = wait(lambda: (x := c.get(f"/api/sites/{sid}/clients").json()) and next(i for i in x if i["hostname"] == "nas")["static"] and x, "static lease")
    check(next(x for x in cl if x["mac"] == iph["mac"])["display"] == "Telefoon Timothy", "alias stored")
    tab = next(x for x in cl if x["hostname"] == "Galaxy-Tab-S9")
    check(c.post(f"/api/sites/{sid}/clients/{tab['mac']}/block", json={"blocked": True}).status_code == 200, "block client")
    cl = c.get(f"/api/sites/{sid}/clients").json()
    t = next(x for x in cl if x["mac"] == tab["mac"])
    check(t["blocked"] and not t["online"], "blocked client is off the air and flagged")
    c.post(f"/api/sites/{sid}/clients/{tab['mac']}/block", json={"blocked": False})
    check(not rt.get("/interface/wifi/access-list").json(), "unblock removes the access-list entry")

    print("clients: no doubles, IPv6, live rate, pause, schedule, wake-on-lan")
    cl = wait(lambda: (x := c.get(f"/api/sites/{sid}/clients").json()) and all(i["online"] for i in x) and x, "all online again")
    macs = [x["mac"] for x in cl]
    check(len(macs) == len(set(macs)), "every client appears once")
    check(all(bool(x["wifi"]) != bool(x["wired"]) for x in cl), "every client has exactly one place: an AP or a port")
    check(all(not x["wired"] or x["wired"]["device"] != "hAP-ax2-meterkast" for x in cl),
          "clients behind a switch or AP are not also listed on the router")
    iph = next(x for x in cl if x["mac"] == iph["mac"])
    check(len(iph["ipv6"]) == 1 and iph["ipv6"][0].startswith("2a02:"), "global IPv6 address shown, link-local left out")
    check(not next(x for x in cl if x["hostname"] == "shelly-plug-keuken")["ipv6"], "no IPv6 where the router has none")
    cl = wait(lambda: (x := c.get(f"/api/sites/{sid}/clients").json()) and all(i["rate_down"] is not None for i in x) and x,
              "live rates")
    check(next(x for x in cl if x["mac"] == iph["mac"])["rate_down"] > 0, "live download rate per client")
    check(c.post(f"/api/sites/{sid}/clients/{nas['mac']}/pause", json={"paused": True}).status_code == 200, "pause internet")
    kid = rt.get("/ip/kid-control", params={"name": "mm-pauze"}).json()
    check(kid and kid[0].get("paused") == "true", "pause profile exists on the router and is paused")
    n = wait(lambda: (x := next(i for i in c.get(f"/api/sites/{sid}/clients").json() if i["mac"] == nas["mac"]))["paused"]
             and x["rate_down"] == 0 and x, "paused client")
    check(n["paused"], "client shows as paused")
    r = c.post(f"/api/sites/{sid}/clients/{nas['mac']}/schedule", json={"from": "22:00", "to": "07:00"})
    check(r.status_code == 400, "schedule across midnight refused with a clear error")
    check(c.post(f"/api/sites/{sid}/clients/{nas['mac']}/schedule", json={"from": "07:00", "to": "22:30"}).status_code == 200,
          "schedule stored while paused")
    c.post(f"/api/sites/{sid}/clients/{nas['mac']}/pause", json={"paused": False})
    n = next(i for i in c.get(f"/api/sites/{sid}/clients").json() if i["mac"] == nas["mac"])
    check(not n["paused"] and n["schedule"] == {"from": "07:00", "to": "22:30"}, "resume falls back to the schedule")
    k = rt.get("/ip/kid-control", params={"name": "mm-tijd-0700-2230"}).json()
    check(k and k[0].get("mon") == "07:00-22:30" and k[0].get("sun") == "07:00-22:30", "schedule profile on the router")
    c.post(f"/api/sites/{sid}/clients/{nas['mac']}/schedule", json={})
    check(not [d for d in rt.get("/ip/kid-control/device").json() if d.get("dynamic") != "true"],
          "clearing the schedule removes the device entry")
    r = c.post(f"/api/sites/{sid}/clients/{nas['mac']}/wol")
    check(r.status_code == 200 and r.json()["interface"] == "bridge", "wake-on-lan sent on the client's interface")

    print("wifi changes")
    c.patch(f"/api/wlans/{thuis['id']}", json={"passphrase": "nieuw-wachtwoord-2026"})
    plan = c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"]
    check(len(plan) == 1 and plan[0]["op"] == "set", "password change is a single set, no re-provision")
    c.delete(f"/api/wlans/{gast['id']}")
    c.patch(f"/api/sites/{sid}", json={"settings": {"ch5_freq": "5180,5260", "ch2_width": "20mhz"}})
    plan = c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"]
    kinds = [o["op"] for o in plan]
    check(kinds.count("remove") == 3 and "reprovision" in kinds, "deleting an SSID removes its 3 objects and re-provisions")
    check(c.post(f"/api/sites/{sid}/wifi/apply").json()["ok"], "apply changes")
    check(rt.get("/interface/wifi/security/tc-thuis").json()["passphrase"] == "nieuw-wachtwoord-2026", "new passphrase on router")
    check(rt.get("/interface/wifi/channel/tc-ch-5g").json()["frequency"] == "5180,5260", "channel list set")
    c.patch(f"/api/sites/{sid}", json={"settings": {"ch5_freq": ""}})
    plan = c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"]
    check([o["op"] for o in plan] == ["unset"], "clearing the channel list is an unset")
    c.post(f"/api/sites/{sid}/wifi/apply")
    check("frequency" not in rt.get("/interface/wifi/channel/tc-ch-5g").json(), "frequency back to automatic")
    # hand-made objects survive
    rt.put("/interface/wifi/security", json={"name": "eigen-profiel", "authentication-types": "wpa2-psk", "passphrase": "handgemaakt"})
    c.post(f"/api/sites/{sid}/wifi/apply")
    check(rt.get("/interface/wifi/security/eigen-profiel").status_code == 200 and c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"] == [], "hand-made profile is left alone")

    print("transmit power per radio")
    def radio(mac):
        return next(r for a in c.get(f"/api/sites/{sid}/wifi").json()["aps"] for r in a["radios"] if r["mac"] == mac)
    caps = [a for a in c.get(f"/api/sites/{sid}/wifi").json()["aps"] if not a["local"]]
    r5 = next(r for r in caps[0]["radios"] if r["band"] == "5g")
    other = next(r for r in caps[1]["radios"] if r["band"] == "5g")
    check(r5["tx"]["mode"] == "high" and r5["tx"]["presets"]["low"] == 11, "radios start on high, presets known")
    check(c.post(f"/api/sites/{sid}/wifi/radios/{r5['mac']}", json={"mode": "manual", "power": 45}).status_code == 400,
          "impossible manual power refused")
    c.post(f"/api/sites/{sid}/wifi/radios/{r5['mac']}", json={"mode": "low"})
    plan = c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"]
    check(any("radio " + r5["mac"] in o["text"] for o in plan), "plan adds a provisioning rule for that one radio")
    check(c.post(f"/api/sites/{sid}/wifi/apply").json()["ok"], "apply transmit power")
    x = wait(lambda: (v := radio(r5["mac"])) and v["tx_power"] == "11" and v, "low power on the radio")
    check(x["tx"]["mode"] == "low" and x["ssids"] == r5["ssids"], "radio keeps all its SSIDs at low power")
    check(radio(other["mac"])["tx_power"] != "11", "other radios untouched")
    c.post(f"/api/sites/{sid}/wifi/radios/{r5['mac']}", json={"mode": "manual", "power": 14})
    c.post(f"/api/sites/{sid}/wifi/apply")
    check(wait(lambda: radio(r5["mac"])["tx_power"] == "14", "manual power"), "manual power in dBm")
    c.post(f"/api/sites/{sid}/wifi/radios/{r5['mac']}", json={"mode": "high"})
    c.post(f"/api/sites/{sid}/wifi/apply")
    check(not [p for p in rt.get("/interface/wifi/provisioning").json() if p.get("radio-mac")]
          and wait(lambda: radio(r5["mac"])["tx_power"] == "23", "back to high"), "high removes the radio rule again")

    print("backups")
    r = c.post(f"/api/sites/{sid}/backups").json()
    check(all(x.get("changed") for x in r), "first backup of all five devices (incl. file fallback on the switch)")
    check(not c.post(f"/api/devices/{ids['router']}/backups").json()["changed"], "unchanged config is not stored twice")
    c.post(f"/api/sites/{sid}/wifi/wlans", json={"ssid": "Werk", "passphrase": "kantoor-wifi-2026", "bands": ["5g"]})
    c.post(f"/api/sites/{sid}/wifi/apply")
    check(c.post(f"/api/devices/{ids['router']}/backups").json()["changed"], "changed config is stored")
    b = next(x for x in c.get(f"/api/sites/{sid}/backups").json() if x["device_id"] == ids["router"])["backups"]
    check(len(b) == 2, "two versions for the router")
    d = c.get(f"/api/backups/{b[0]['id']}/diff/{b[1]['id']}").json()
    check(d["added"] >= 3 and any("Werk" in l["text"] for l in d["lines"] if l["kind"] == "add"), "diff shows the new SSID")
    check("kantoor-wifi" not in c.get(f"/api/backups/{b[0]['id']}").json()["text"], "export without secrets by default")

    print("updates")
    u = c.post(f"/api/sites/{sid}/updates/check").json()["devices"]
    check(all(x["available"] and x["latest"] == "7.20.2" for x in u), "update found for all devices")
    check(next(x for x in u if x["id"] == ids["crs"])["firmware_pending"], "pending RouterBOOT firmware detected")
    job = c.post(f"/api/sites/{sid}/updates/all").json()
    check(job["total"] == 5 and c.post(f"/api/sites/{sid}/updates/all").status_code == 400, "update round started, second one refused")
    job = wait(lambda: (j := c.get(f"/api/sites/{sid}/updates").json()["job"]) and not j["running"] and j, "update round", 180)
    order = [s["device"] for s in job["steps"]]
    check(job["error"] is None and order[-1] == "hAP-ax2-meterkast" and set(order[:2]) == {"cAP-ax-woonkamer", "cAP-ax-overloop"}, "APs first, router last")
    u = wait(lambda: (x := c.get(f"/api/sites/{sid}/updates").json()["devices"]) and all(i["installed"] == "7.20.2" and not i["available"] for i in x) and x, "versions refreshed")
    check(True, "all devices on 7.20.2")
    c.post(f"/api/devices/{ids['crs']}/firmware")
    wait(lambda: not next(x for x in c.get(f"/api/sites/{sid}/updates").json()["devices"] if x["id"] == ids["crs"])["firmware_pending"], "firmware", 60)
    check(True, "firmware upgraded after reboot")
    act = [a["message"] for a in c.get(f"/api/sites/{sid}/activity").json()]
    check(any("offline" in a for a in act) and any("weer online" in a for a in act) and any("7.20.1 → 7.20.2" in a for a in act), "activity log recorded reboot and new version")

    print("interfaces")
    crs = httpx.Client(base_url=f"http://127.0.0.1:{MOCK + 1}/rest", auth=("tikcontrol", "demo-pass"), timeout=5)
    hx = httpx.Client(base_url=f"http://127.0.0.1:{MOCK + 2}/rest", auth=("tikcontrol", "demo-pass"), timeout=5)
    base = f"/api/devices/{ids['crs']}"
    v = c.get(f"{base}/interfaces").json()
    names = [i["name"] for i in v["interfaces"]]
    check(names[:3] == ["ether1", "ether2", "ether3"] and "sfp-sfpplus1" in names and "bridge" in names,
          "all interfaces listed, ports in natural order")
    e3 = next(i for i in v["interfaces"] if i["name"] == "ether3")
    check(e3["ether"]["auto_negotiation"] and e3["bridge_port"]["pvid"] == 1, "port shows speed and bridge settings")
    check(next(i for i in v["interfaces"] if i["name"] == "sfp-sfpplus1")["kind"] == "sfp", "SFP recognised")
    r = c.post(f"{base}/interfaces/ether3", json={"comment": "nas"})
    check(r.status_code == 200 and r.json()["steps"] == 1, "label saved")
    check(not crs.get("/system/scheduler").json(), "a label needs no safe mode (no scheduler)")
    r = c.post(f"{base}/interfaces/ether5", json={"auto_negotiation": False, "speed": "100M-baseT-full"})
    check(r.status_code == 200 and r.json()["applied"], "fixed speed applied")
    e5 = next(e for e in crs.get("/interface/ethernet").json() if e["name"] == "ether5")
    check(e5["auto-negotiation"] == "false" and e5["speed"] == "100M-baseT-full", "speed on the switch")
    check(not crs.get("/system/scheduler").json(), "undo scheduler removed after a safe change")
    check(c.post(f"{base}/interfaces/ether6", json={"mtu": 9000}).json()["applied"], "MTU applied")
    check(c.post(f"{base}/interfaces/ether6", json={"mtu": 20000}).status_code == 400, "impossible MTU refused")
    check(c.post(f"{base}/interfaces/ether7", json={"tagged": [10, 20]}).json()["applied"], "tagged VLANs on a port")
    bv = crs.get("/interface/bridge/vlan").json()
    check(sorted(e["vlan-ids"] for e in bv if "ether7" in e.get("tagged", "")) == ["10", "20"], "bridge VLAN rows made")
    c.post(f"{base}/interfaces/ether8", json={"tagged": [20]})
    c.post(f"{base}/interfaces/ether7", json={"tagged": [20]})
    bv = crs.get("/interface/bridge/vlan").json()
    check([e.get("tagged", "") for e in bv if e["vlan-ids"] == "20"] == ["ether7,ether8"]
          and not [e for e in bv if e["vlan-ids"] == "10" and "ether7" in e.get("tagged", "")],
          "VLAN 10 taken off ether7, VLAN 20 shared with ether8")
    r = c.post(f"{base}/vlans", json={"name": "vlan30-iot", "vlan_id": 30, "interface": "bridge", "comment": "IoT"})
    check(r.status_code == 200 and any(i["name"] == "vlan30-iot" for i in r.json()["view"]["interfaces"]), "VLAN interface added")
    check(c.post(f"{base}/vlans", json={"name": "dubbel", "vlan_id": 30, "interface": "bridge"}).status_code == 400,
          "same VLAN on the same parent refused")
    check(c.patch(f"{base}/vlans/vlan30-iot", json={"comment": "IoT-netwerk"}).json()["applied"], "VLAN interface changed")
    check(c.delete(f"{base}/vlans/vlan30-iot").json()["applied"] and not crs.get("/interface/vlan").json(),
          "VLAN interface removed")

    print("safe mode")
    t0 = time.time()
    r = c.post(f"{base}/interfaces/ether1", json={"disabled": True})
    check(r.status_code == 202 and not r.json()["applied"] and "CRS310-kantoor" in r.json()["lost"],
          "switching off the uplink is detected as a lock-out")
    wait(lambda: _get_ok(crs, "/system/resource"), "switch comes back by itself", timeout=30)
    e1 = next(i for i in crs.get("/interface").json() if i["name"] == "ether1")
    check(e1["disabled"] == "false" and time.time() - t0 >= 6, "the switch undid it on its own after the safe-mode time")
    check(not crs.get("/system/scheduler").json(), "undo scheduler removed itself")
    wait(lambda: all(d["online"] for d in c.get(f"/api/sites/{sid}/devices").json()), "devices behind the switch back online")
    r = c.post(f"/api/devices/{ids['hexpoe']}/interfaces/ether2", json={"poe_out": "off"})
    check(r.status_code == 202 and r.json()["lost"] == ["cAP-ax-woonkamer"] and r.json()["reverting_in"] == 0,
          "PoE off that cuts an access point is undone straight away")
    check(next(p for p in hx.get("/interface/ethernet/poe").json() if p["name"] == "ether2")["poe-out"] == "auto-on"
          and not hx.get("/system/scheduler").json(), "PoE back on, no scheduler left")
    r = c.post(f"/api/devices/{ids['hexpoe']}/interfaces/ether5", json={"poe_out": "off", "poe_priority": 3})
    check(r.status_code == 200 and r.json()["applied"], "PoE off on a port without managed devices behind it")
    r = c.post(f"{base}/interfaces/ether3", json={"pvid": 30})
    check(r.json()["applied"], "PVID on an edge port is fine")
    c.post(f"{base}/interfaces/ether3", json={"pvid": 1})
    wait(lambda: all(d["online"] for d in c.get(f"/api/sites/{sid}/devices").json()), "all devices online again")

    print("live view")
    first = c.get(f"/api/sites/{sid}/live").json()       # starts watching; returns stored history as fill
    t0 = first["now"]
    lv = wait(lambda: (x := c.get(f"/api/sites/{sid}/live", params={"since": t0}).json())
              and len(x["traffic"]) >= 4 and x["latency"] and x, "live samples", timeout=20)
    gaps = [b["ts"] - a["ts"] for a, b in zip(lv["traffic"], lv["traffic"][1:])]
    check(max(gaps) < 2.5 and all(p["rx"] is not None for p in lv["traffic"]), "WAN traffic sampled every second while watched")
    check(lv["latency"][-1]["rtt"] > 0 and lv["wan"] == "ether1", "live internet latency")
    check(all(v is not None for v in lv["cpu"].values()), "live CPU for every device")
    check(first["traffic"] and first["traffic"][0]["ts"] < t0 - 60, "first request fills the window with stored history")
    newer = c.get(f"/api/sites/{sid}/live", params={"since": lv["traffic"][-1]["ts"]}).json()["traffic"]
    check(all(p["ts"] > lv["traffic"][-1]["ts"] for p in newer), "only new samples after 'since'")
    dl = wait(lambda: (x := c.get(f"/api/devices/{ids['crs']}/live", params={"since": t0}).json()) and len(x["load"]) >= 2 and x,
              "device live")
    check("ether3" in dl["rates"] and dl["rates"]["ether3"]["rx"] > 0, "live rate per interface on the device page")

    print("overview and cleanup")
    o = c.get(f"/api/sites/{sid}/overview").json()
    check(o["devices"]["online"] == 5 and o["clients"]["wifi"] >= 12 and o["wan"]["interface"] == "ether1" and o["wan"]["history"], "overview")
    wq = o["wan_quality"]
    check([w["interface"] for w in wq["wans"]] == ["ether1", "lte1"] and wq["wans"][0]["active"] and not wq["wans"][1]["active"],
          "both WANs listed, active one first")
    check(wq["wans"][0]["ping"].get("internet") and wq["wans"][0]["ping"]["internet"]["avg"] > 0
          and wq["wans"][1]["ping"].get("gateway") and wq["wans"][1]["gateway"] == "10.64.0.1",
          "internet latency on the active WAN, gateway latency on the standby WAN")
    check(any(h["kind"] == "internet" and h["rtt"] for h in wq["history"]), "WAN latency history")
    check(c.delete(f"/api/sites/{sid}/networks/gasten").json()["removed"] >= 7, "managed network removed with all its parts")
    check(not [f for f in rt.get("/ip/firewall/filter").json() if "tc:" in f.get("comment", "")], "isolation rule gone")
    check(c.delete(f"/api/sites/{sid}/networks/bridge").status_code == 404, "hand-made network cannot be deleted")
    check(len(rt.get("/ip/address").json()) == 3, "LAN and WAN addresses untouched")


if __name__ == "__main__":
    main()
