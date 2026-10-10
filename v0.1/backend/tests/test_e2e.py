"""End-to-end test: real TikControl server against the simulated routers.

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
           "TIKCONTROL_POLL": "2", "MOCK_REBOOT_SECS": "4", "MOCK_BASE_PORT": str(MOCK), "TIKCONTROL_STATIC": "/nonexistent"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"], env=env)
    c = httpx.Client(base_url=BASE, timeout=60)
    try:
        wait(lambda: _up(c), "server start")
        run(c)
        print(f"\n{passed} checks passed")
    finally:
        proc.terminate()
        proc.wait(10)


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

    print("overview and cleanup")
    o = c.get(f"/api/sites/{sid}/overview").json()
    check(o["devices"]["online"] == 5 and o["clients"]["wifi"] >= 12 and o["wan"]["interface"] == "ether1" and o["wan"]["history"], "overview")
    check(c.delete(f"/api/sites/{sid}/networks/gasten").json()["removed"] >= 7, "managed network removed with all its parts")
    check(not [f for f in rt.get("/ip/firewall/filter").json() if "tc:" in f.get("comment", "")], "isolation rule gone")
    check(c.delete(f"/api/sites/{sid}/networks/bridge").status_code == 404, "hand-made network cannot be deleted")
    check(len(rt.get("/ip/address").json()) == 3, "LAN and WAN addresses untouched")


if __name__ == "__main__":
    main()
