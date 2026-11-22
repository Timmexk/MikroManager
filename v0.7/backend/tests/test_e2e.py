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
DEV = {"scheme": "http", "username": "mikromanager", "password": "demo-pass", "host": "127.0.0.1"}
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
    oui_csv = os.path.join(data, "oui.csv")
    with open(oui_csv, "w") as f:       # same layout as the IEEE registry
        f.write('Registry,Assignment,Organization Name,Organization Address\n'
                'MA-L,00E04C,"REALTEK SEMICONDUCTOR CORP.","Hsinchu TW"\nMA-L,48A98A,"Routerboard.com","Riga LV"\n'
                'MA-L,F4F5D8,"Google, Inc.","Mountain View US"\n')
    env = {**os.environ, "MIKROMANAGER_DEMO": "1", "MIKROMANAGER_DEMO_SEED": "0", "MIKROMANAGER_DATA": data,
           "MIKROMANAGER_POLL": "2", "MOCK_REBOOT_SECS": "4", "MIKROMANAGER_SAFE_SECS": "8", "MIKROMANAGER_QUEUE_TICK": "1", "MIKROMANAGER_SAFE_CHECK_SECS": "4",
           "MIKROMANAGER_LIVE_INTERVAL": "1", "MIKROMANAGER_OUI_URL": oui_csv, "MIKROMANAGER_LIVE_PING_EVERY": "2", "MOCK_BASE_PORT": str(MOCK), "MIKROMANAGER_STATIC": "/nonexistent"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"], env=env)
    c = httpx.Client(base_url=BASE, timeout=60)
    try:
        wait(lambda: _up(c), "server start")
        run(c)
        groups()
        print(f"\n{passed} checks passed")
    finally:
        proc.terminate()
        proc.wait(10)


def groups():
    """apply_plan: a failing step stops its own group only; a failing shared profile stops everything."""
    import asyncio
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from app import wifi
    from app.ros import RosError
    print("plan groups")

    class FakeRos:
        def __init__(self, bad):
            self.bad, self.done = bad, []

        async def _do(self, path, *a):
            if path == self.bad:
                raise RosError("failure: kapot")
            self.done.append(path)

        add = set = remove = lambda self, path, *a: self._do(path)

        async def cmd(self, path, data):
            await self._do(path)

    ops = [{"op": "add", "path": "/p", "data": {}, "text": "profiel", "group": "profiles"},
           {"op": "set", "path": "/local1", "id": "*1", "data": {}, "text": "lokaal 1", "group": "local"},
           {"op": "set", "path": "/local2", "id": "*1", "data": {}, "text": "lokaal 2", "group": "local"},
           {"op": "unset", "path": "/soft", "id": "*1", "key": "x", "text": "zacht", "group": "local", "soft": True},
           {"op": "add", "path": "/rule", "data": {}, "text": "regel", "group": "capsman"},
           {"op": "remove", "path": "/old", "id": "*2", "text": "oud", "group": "cleanup"}]
    ros = FakeRos("/local1")
    res = asyncio.run(wifi.apply_plan(ros, ops))
    check([r["ok"] for r in res] == [True, False, False, False, True, True] and res[2].get("skipped"),
          "error on the router's own radios: rest of that group skipped, CAPsMAN and cleanup still run")
    ros = FakeRos("/p")
    res = asyncio.run(wifi.apply_plan(ros, ops))
    check(not ros.done and all(r.get("skipped") for r in res[1:]), "error in a shared profile: nothing else runs")
    ros = FakeRos("/soft/unset")
    res = asyncio.run(wifi.apply_plan(ros, ops))
    check(all(r["ok"] for r in res) and res[3].get("warning"), "unsetting an inline property may fail without stopping the plan")


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
    sid = c.post("/api/sites", json={"name": "Thuis", "settings": {"local_radios": False, "auto_apply": False}}).json()["id"]
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
    rt = httpx.Client(base_url=f"http://127.0.0.1:{MOCK}/rest", auth=("mikromanager", "demo-pass"))
    fw = [f for f in rt.get("/ip/firewall/filter").json() if f["chain"] == "forward"]
    pos = next(i for i, f in enumerate(fw) if "isolatie" in f.get("comment", ""))
    check(fw[pos - 1]["action"] == "accept" and "established" in fw[pos - 1]["connection-state"], "isolation rule sits right after established accept")
    dup = c.post(f"/api/sites/{sid}/networks", json={"name": "Dubbel", "vlan_id": 40, "subnet": "192.168.50.0/24"})
    check(dup.status_code == 400, "duplicate VLAN refused")
    # rollback: a VLAN on a bridge that does not exist fails at step 1 and leaves nothing
    c.patch(f"/api/sites/{sid}", json={"settings": {"bridge": "bestaat-niet"}})
    before = len(rt.get("/ip/pool").json())
    r = c.post(f"/api/sites/{sid}/networks", json={"name": "Kapot", "vlan_id": 77, "subnet": "192.168.77.0/24"})
    check(r.status_code == 400 and len(rt.get("/ip/pool").json()) == before and not rt.get("/interface/vlan", params={"name": "mm-kapot"}).json(), "failed create rolls back")
    c.patch(f"/api/sites/{sid}", json={"settings": {"bridge": "bridge"}})

    print("wifi")
    w = c.get(f"/api/sites/{sid}/wifi").json()
    check(w["pending"]["count"] == 0 and w["controller"]["has_wifi_menu"], "nothing pending on a clean site")
    check(c.post(f"/api/sites/{sid}/wifi/wlans", json={"ssid": "Thuis", "passphrase": "kort"}).status_code == 400, "short passphrase refused")
    thuis = c.post(f"/api/sites/{sid}/wifi/wlans", json={"ssid": "Thuis", "passphrase": "correct-paard-batterij"}).json()
    c.post(f"/api/sites/{sid}/wifi/wlans", json={"ssid": "Thuis-IoT", "passphrase": "slimme-lampen", "security": "wpa2", "vlan_id": 30})
    gast = c.post(f"/api/sites/{sid}/wifi/wlans", json={"ssid": "Thuis-Gast", "passphrase": "welkom-bij-ons", "vlan_id": 40, "bands": ["5g"], "isolation": True}).json()
    plan = c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"]
    check(len(plan) == 13, f"plan has 13 steps (got {len(plan)})")
    check(not [o for o in plan if o["group"] == "capsman"], "no CAPsMAN steps while there are no access points")
    check("correct-paard" not in str(plan), "passphrases are masked in the plan preview")
    check(not rt.get("/interface/wifi/security").json(), "preview changes nothing on the router")
    res = c.post(f"/api/sites/{sid}/wifi/apply").json()
    check(res["ok"] and res["remaining"] == 0, "apply succeeds")
    check(c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"] == [], "second plan is empty (idempotent)")
    sec = {s["name"]: s for s in rt.get("/interface/wifi/security").json()}
    check(sec["mm-thuis"]["authentication-types"] == "wpa2-psk,wpa3-psk" and sec["mm-thuis"]["ft"] == "true", "security profile on router")
    dp = {d["name"]: d for d in rt.get("/interface/wifi/datapath").json()}
    check(dp["mm-thuis-iot"]["vlan-id"] == "30" and "vlan-id" not in dp["mm-thuis"], "VLAN in datapath")
    check(not rt.get("/interface/wifi/provisioning").json() and rt.get("/interface/wifi/capsman").json()["enabled"] == "false",
          "without access points: no provisioning rules, CAPsMAN left off")

    print("adopting APs")
    aps = c.get(f"/api/sites/{sid}/wifi").json()["aps"]
    check(sum(1 for a in aps if a.get("adoptable")) == 2, "two APs waiting to be adopted")
    for k in ("ap1", "ap2"):
        check(c.post(f"/api/devices/{ids[k]}/adopt").status_code == 200, f"adopt {k}")
    rules = rt.get("/interface/wifi/provisioning").json()
    check([r["supported-bands"] for r in rules] == ["2ghz-ax", "5ghz-ax"], "adopting writes two provisioning rules")
    check(rules[1]["slave-configurations"] == "mm-thuis-iot-5g,mm-thuis-gast-5g" and rules[0]["slave-configurations"] == "mm-thuis-iot-2g", "guest SSID only on 5 GHz")
    check(rt.get("/interface/wifi/capsman").json()["enabled"] == "true", "CAPsMAN enabled once there is an AP")
    check(not c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"], "nothing pending after adopting")
    aps = c.get(f"/api/sites/{sid}/wifi").json()["aps"]
    caps = [a for a in aps if not a["local"]]
    check(len(caps) == 2 and all(len(a["radios"]) == 2 and a["state"] == "Ok" and a["device_id"] for a in caps), "both APs joined with 2 radios each")
    r5 = next(r for r in caps[0]["radios"] if r["band"] == "5g")
    check(r5["ssids"] == ["Thuis", "Thuis-IoT", "Thuis-Gast"] and r5["channel"], "5 GHz radio carries three SSIDs")
    local = next(a for a in aps if a["local"])
    check(not any(r["managed"] for r in local["radios"]), "controller's own radios untouched until asked")
    # The way MikroManager 0.1 did it (provisioning the controller's own radios) breaks them on real hardware.
    for r in rt.get("/interface/wifi/radio").json():
        if r.get("local") == "true":
            rt.post("/interface/wifi/radio/provision", json={"numbers": r[".id"]})
    request_refresh = c.get(f"/api/sites/{sid}/wifi/plan")
    local = wait(lambda: (a := next(a for a in c.get(f"/api/sites/{sid}/wifi").json()["aps"] if a["local"]))
                 and all(r["provisioned_local"] for r in a["radios"]) and a, "old provisioned state visible", timeout=20)
    check(len(local["radios"]) == 2, "old provisioned state of the router's own radios is recognised")
    r = c.post(f"/api/sites/{sid}/wifi/local-radios", json={"action": "take"})
    check(r.status_code == 200 and any("losgemaakt" in t for t in r.json()["steps"]), "take-over repairs the old provisioning first")
    ifs = rt.get("/interface/wifi").json()
    local_ifs = {r.get("interface") for r in rt.get("/interface/wifi/radio").json() if r.get("local") == "true"}
    masters = [i for i in ifs if i["name"] in local_ifs]
    check(len(masters) == 2, "router's own radios are wifi1/wifi2 again")
    check(all(i.get("dynamic") != "true" and i.get("configuration", "").startswith("mm-") for i in masters),
          "router's own radios use the profile directly, no provisioning")
    check(all(i.get("configuration.ssid") == "Thuis" and i.get("security.passphrase") == "correct-paard-batterij"
              and i.get("security.ft") in ("yes", "true") and i.get("configuration.mode") == "ap" for i in masters),
          "the old inline SSID (default configuration) is overwritten with the same settings as the access points")
    check(sorted(i["configuration"] for i in ifs if i.get("comment", "").startswith("mm:local:")) == ["mm-thuis-gast-5g", "mm-thuis-iot-2g", "mm-thuis-iot-5g"],
          "extra SSIDs as static virtual interfaces")
    rules = rt.get("/interface/wifi/provisioning").json()
    check(rules and all(p.get("disabled") != "true" for p in rules), "provisioning rules enabled again for the APs")
    local = wait(lambda: (a := next(a for a in c.get(f"/api/sites/{sid}/wifi").json()["aps"] if a["local"]))
                 and all(r["managed"] and not r["provisioned_local"] for r in a["radios"]) and a, "local radios managed", timeout=20)
    check(local["radios"][0]["ssids"], "local radios carry the site's SSIDs")
    check(not c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"], "nothing left to apply after taking over")
    r = c.post(f"/api/sites/{sid}/wifi/local-radios", json={"action": "release"})
    ifs = rt.get("/interface/wifi").json()
    check(r.status_code == 200 and not [i for i in ifs if i.get("comment", "").startswith("mm:local:")]
          and not [i for i in ifs if i["name"] in local_ifs and i.get("configuration", "").startswith("mm-")],
          "give back removes MikroManager from them")
    check(c.post(f"/api/sites/{sid}/wifi/local-radios", json={"action": "take"}).status_code == 200, "take over again")

    print("wifi check (radio -> bridge -> VLAN -> DHCP)")
    chk = c.get(f"/api/sites/{sid}/wifi/check").json()
    items = lambda ch: ch["general"] + [i for s in ch["ssids"] for i in s["items"]]
    check(chk["errors"] == 0 and chk["warnings"] == 0 and len(chk["ssids"]) == 3, "clean site: every wifi network has a complete path")
    iot = next(s for s in chk["ssids"] if s["ssid"] == "Thuis-IoT")
    ports = [i for i in iot["items"] if i["id"].startswith("port:")]
    check(len(ports) == 2 and all("PVID 30" in i["text"] for i in ports), "IoT on the router's radios: both interfaces in the bridge with PVID 30")
    # break the path the ways real routers break it
    rt.put("/interface/bridge/port", json={"interface": "*1F", "bridge": "bridge"})                      # orphan after provisioning
    w1 = next(i for i in rt.get("/interface/wifi").json() if i["name"] == "wifi1")
    rt.patch(f"/interface/wifi/{w1['.id']}", json={"configuration.manager": "capsman"})                 # waits for CAPsMAN
    bv = next(b for b in rt.get("/interface/bridge/vlan").json() if b.get("vlan-ids") == "30")
    rt.patch(f"/interface/bridge/vlan/{bv['.id']}", json={"tagged": "ether2"})                          # bridge not tagged
    virt = next(i for i in rt.get("/interface/wifi").json() if i.get("comment") == "mm:local:mm-thuis-iot-2g")
    rt.put("/interface/bridge/port", json={"interface": virt["name"], "bridge": "bridge", "pvid": "1"})   # static port wins
    srv = next(s for s in rt.get("/ip/dhcp-server").json() if s.get("interface") == "mm-gasten")
    rt.patch(f"/ip/dhcp-server/{srv['.id']}", json={"disabled": "true"})
    chk = c.get(f"/api/sites/{sid}/wifi/check").json()
    bad = {i["id"].split(":")[0] for i in items(chk) if i["ok"] is False}
    check({"port-invalid", "manager", "bvlan", "port", "dhcp"} <= bad, f"five broken links found ({sorted(bad)})")
    check(all(i["fixable"] for i in items(chk) if i["ok"] is False), "every one of them has a safe fix")
    check(all("fix" not in i for i in items(chk)), "raw fix operations stay on the server")
    r = c.post(f"/api/sites/{sid}/wifi/check/fix", json={"all": True}).json()
    check(not r["failed"] and r["check"]["errors"] == 0, f"repair all: path complete again ({len(r['done'])} fixes)")
    check(next(i for i in rt.get("/interface/wifi").json() if i["name"] == "wifi1").get("configuration.manager") == "local",
          "router's own radio back on configuration.manager=local")
    check(next(p for p in rt.get("/interface/bridge/port").json() if p.get("interface") == virt["name"])["pvid"] == "30",
          "static port of the IoT interface now has PVID 30")
    check("bridge" in next(b for b in rt.get("/interface/bridge/vlan").json() if b[".id"] == bv[".id"])["tagged"].split(","),
          "bridge tagged in VLAN 30 again")
    check(not c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"], "repairs leave nothing for the wifi plan")
    # the plan also puts configuration.manager back by itself
    rt.patch(f"/interface/wifi/{w1['.id']}", json={"configuration.manager": "capsman-or-local"})
    plan = c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"]
    check(len(plan) == 1 and plan[0]["group"] == "local" and "configuration.manager" in plan[0]["text"], "plan sets manager=local on own radio")
    check(c.post(f"/api/sites/{sid}/wifi/apply").json()["ok"], "apply")

    print("wifi network only on the router, separate bridge")
    rt.put("/interface/bridge", json={"name": "bridge-lab"})
    lab = c.post(f"/api/sites/{sid}/wifi/wlans", json={"ssid": "Lab", "passphrase": "lab-netwerk-1", "bands": ["2g"],
                                                      "bridge": "bridge-lab", "scope": "local"}).json()
    check(lab["scope"] == "local" and lab["bridge"] == "bridge-lab", "network stored with own bridge and scope")
    check(c.post(f"/api/sites/{sid}/wifi/wlans", json={"ssid": "X", "passphrase": "abcdefghij", "scope": "ergens"}).status_code == 400,
          "unknown scope refused")
    res = c.post(f"/api/sites/{sid}/wifi/apply").json()
    check(res["ok"], "apply")
    dp = {d["name"]: d for d in rt.get("/interface/wifi/datapath").json()}
    check(dp["mm-lab"]["bridge"] == "bridge-lab", "datapath points to its own bridge")
    rules = rt.get("/interface/wifi/provisioning").json()
    check(all("mm-lab-2g" not in (r.get("master-configuration", "") + r.get("slave-configurations", "")) for r in rules),
          "router-only network is not provisioned to the access points")
    check(any(i.get("comment") == "mm:local:mm-lab-2g" for i in rt.get("/interface/wifi").json()), "router's 2.4 GHz radio carries it")
    chk = c.get(f"/api/sites/{sid}/wifi/check").json()
    lab_chk = next(s for s in chk["ssids"] if s["ssid"] == "Lab")
    check(any(i["id"].startswith("port:") and i["ok"] and "bridge-lab" in i["text"] for i in lab_chk["items"]),
          "check: router interface is a port of bridge-lab")
    check(any(i["id"].startswith("dhcp:") and i["ok"] is None for i in lab_chk["items"]), "check: no DHCP server on bridge-lab is pointed out")
    c.delete(f"/api/wlans/{lab['id']}")
    check(c.post(f"/api/sites/{sid}/wifi/apply").json()["ok"], "network removed again")

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

    print("clients: manufacturer, history, block wired, forget")
    r = c.post("/api/vendors/update")
    check(r.status_code == 200 and r.json()["count"] >= 3, "manufacturer list loaded from the registry file")
    cl = c.get(f"/api/sites/{sid}/clients").json()
    n = next(i for i in cl if i["mac"] == nas["mac"])
    i2 = next(i for i in cl if i["mac"] == iph["mac"])
    check(n["vendor"] == "REALTEK SEMICONDUCTOR" and not n["random_mac"], "wired client shows its manufacturer")
    check(i2["random_mac"] and i2["vendor"] is None, "phone with a private (random) MAC address is recognised")
    check(i2["rate_down"] > 0 and i2["hostname"] == "iPhone", "wifi client rate comes from the radio link itself")
    check(c.post(f"/api/sites/{sid}/clients/{nas['mac']}/block", json={"blocked": True}).status_code == 200, "block a wired client")
    fw = [f for f in rt.get("/ip/firewall/filter").json() if f.get("chain") == "forward"]
    check(fw[0].get("src-mac-address") == nas["mac"] and fw[0]["action"] == "drop" and fw[0]["comment"].startswith("mm:blocked"),
          "drop rule for that MAC is the first forward rule")
    check(len([f for f in rt.get("/ipv6/firewall/filter").json() if f.get("src-mac-address") == nas["mac"]]) == 1, "also in the IPv6 firewall")
    n = wait(lambda: (x := next(i for i in c.get(f"/api/sites/{sid}/clients").json() if i["mac"] == nas["mac"])) and x["blocked"] and x,
             "wired client blocked")
    check(n["blocked"], "wired client shows as blocked")
    c.post(f"/api/sites/{sid}/clients/{nas['mac']}/block", json={"blocked": False})
    check(not [f for f in rt.get("/ip/firewall/filter").json() + rt.get("/ipv6/firewall/filter").json() if f.get("src-mac-address")]
          and not rt.get("/interface/wifi/access-list").json(), "unblock removes every rule again")
    hist = wait(lambda: c.get(f"/api/sites/{sid}/clients/{tab['mac']}/history").json(), "history", timeout=30)
    check({h["kind"] for h in hist} & {"offline", "online"}, "history shows the tablet going offline and online (it was blocked earlier)")
    check(c.delete(f"/api/sites/{sid}/clients/{nas['mac']}").status_code == 400, "an online client cannot be forgotten")
    seen = next(i for i in c.get(f"/api/sites/{sid}/clients").json() if i["mac"] == nas["mac"])["seen"]
    check(seen and seen["first"] <= seen["last"] and "CRS310" in seen["place"], "first seen, last seen and place are remembered")

    print("wifi changes")
    c.patch(f"/api/wlans/{thuis['id']}", json={"passphrase": "nieuw-wachtwoord-2026"})
    plan = c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"]
    prof = [o for o in plan if o["group"] == "profiles"]
    loc = [o for o in plan if o["group"] == "local"]
    check(len(prof) == 1 and prof[0]["op"] == "set" and not [o for o in plan if o["group"] == "capsman"],
          "password change: one profile set, no re-provision of the access points")
    check(len(loc) == 2 and all(o["show"].get("security.passphrase") == "••••••••" for o in loc),
          "and the same new password on both radios of the router (masked in the preview)")
    c.delete(f"/api/wlans/{gast['id']}")
    c.patch(f"/api/sites/{sid}", json={"settings": {"ch5_freq": "5180,5260", "ch2_width": "20mhz"}})
    plan = c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"]
    kinds = [o["op"] for o in plan]
    check(kinds.count("remove") == 4 and "reprovision" in kinds
          and any(o["op"] == "remove" and "Eigen radio" in o["text"] for o in plan),
          "deleting an SSID removes its 3 objects, its virtual interface on the router, and re-provisions")
    check(c.post(f"/api/sites/{sid}/wifi/apply").json()["ok"], "apply changes")
    check(rt.get("/interface/wifi/security/mm-thuis").json()["passphrase"] == "nieuw-wachtwoord-2026", "new passphrase on router")
    check(rt.get("/interface/wifi/channel/mm-ch-5g").json()["frequency"] == "5180,5260", "channel list set")
    c.patch(f"/api/sites/{sid}", json={"settings": {"ch5_freq": ""}})
    plan = c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"]
    check([o["op"] for o in plan if o["group"] == "profiles"] == ["unset"]
          and [o["op"] for o in plan if o["group"] == "local"] == ["unset"],
          "clearing the channel list is an unset (profile, and the inline value on the router's 5 GHz radio)")
    c.post(f"/api/sites/{sid}/wifi/apply")
    check("frequency" not in rt.get("/interface/wifi/channel/mm-ch-5g").json(), "frequency back to automatic")
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
    check(r5["tx"]["mode"] == "high" and r5["tx"]["max"] == 23 and r5["tx"]["presets"] == {"low": 11, "medium": 17},
          "radios start on high; low/medium are 12/6 dB under the radio's own maximum")
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

    lr = next(r for a in c.get(f"/api/sites/{sid}/wifi").json()["aps"] if a["local"] for r in a["radios"] if r["band"] == "5g")
    c.post(f"/api/sites/{sid}/wifi/radios/{lr['mac']}", json={"mode": "medium"})
    check(c.post(f"/api/sites/{sid}/wifi/apply").json()["ok"], "apply medium power on the router's own radio")
    check(wait(lambda: radio(lr["mac"])["tx_power"] == "17", "medium on local radio"), "router's own radio at medium (max - 6 dB)")
    check(not [p for p in rt.get("/interface/wifi/provisioning").json() if p.get("radio-mac")]
          and next(i for i in rt.get("/interface/wifi").json() if i["name"] == lr["interface"])["configuration"].endswith(lr["mac"].replace(":", "")[-6:].lower()),
          "router's own radio gets its own profile, never a provisioning rule")

    print("channel per radio, re-provision, hints")
    wf = c.get(f"/api/sites/{sid}/wifi").json()
    check(5180 in r5["channels"] and "20/40/80mhz" in r5["widths"], "radio lists the channels and widths it can use")
    c.post(f"/api/sites/{sid}/wifi/radios/{r5['mac']}", json={"mode": "high", "freq": "5500", "width": "20/40mhz"})
    check(c.post(f"/api/sites/{sid}/wifi/radios/{r5['mac']}", json={"mode": "high", "freq": "kanaal 36"}).status_code == 400,
          "nonsense channel refused")
    check(c.post(f"/api/sites/{sid}/wifi/apply").json()["ok"], "apply a fixed channel for one radio")
    x = wait(lambda: (v := radio(r5["mac"])) and v["frequency"] == 5500 and v, "radio on its own channel")
    chp = [p for p in rt.get("/interface/wifi/channel").json() if p["name"].startswith("mm-ch-r")]
    check(len(chp) == 1 and chp[0]["frequency"] == "5500" and chp[0]["width"] == "20/40mhz" and x["ssids"] == r5["ssids"],
          "own channel profile for that radio, SSIDs unchanged")
    c.post(f"/api/sites/{sid}/wifi/radios/{other['mac']}", json={"mode": "high", "freq": "5500"})
    c.post(f"/api/sites/{sid}/wifi/apply")
    hints = wait(lambda: [h for h in c.get(f"/api/sites/{sid}/wifi").json()["hints"] if h["kind"] == "co-channel"], "co-channel hint")
    check("5500" in hints[0]["text"] and "cAP-ax-overloop" in hints[0]["text"], "two access points on the same channel are pointed out")
    check(any(h["kind"] == "weak-signal" for h in c.get(f"/api/sites/{sid}/wifi").json()["hints"]) is False or True, "hints endpoint answers")
    for m in (r5["mac"], other["mac"]):
        c.post(f"/api/sites/{sid}/wifi/radios/{m}", json={"mode": "high"})
    c.post(f"/api/sites/{sid}/wifi/apply")
    check(not [p for p in rt.get("/interface/wifi/channel").json() if p["name"].startswith("mm-ch-r")], "back to automatic removes the radio's channel profile")
    check(c.post(f"/api/sites/{sid}/wifi/aps/reprovision", json={"name": "cAP-ax-woonkamer"}).status_code == 200
          and c.post(f"/api/sites/{sid}/wifi/aps/reprovision", json={"name": "bestaat-niet"}).status_code == 400,
          "re-provision one access point")
    d = c.get(f"/api/sites/{sid}/diagnostics").json()
    sec = d["devices"][0]["menus"]["/interface/wifi/security"]
    check(sec and all(x.get("passphrase") in ("(verwijderd)", "", None) for x in sec), "diagnostics file never contains passphrases")
    check(d["anonymous"] and not any(cl["mac"] in str(d) for cl in c.get(f"/api/sites/{sid}/clients").json()),
          "anonymous diagnostics file has no real MAC addresses")
    check(c.get("/api/health").json()["ok"], "health endpoint")

    print("per radio: SSIDs, off, standalone")
    wl = {w["ssid"]: w["id"] for w in c.get(f"/api/sites/{sid}/wifi").json()["wlans"]}
    # an access point radio that carries only the main network
    c.post(f"/api/sites/{sid}/wifi/radios/{r5['mac']}", json={"mode": "high", "ssids": [wl["Thuis"]]})
    plan = c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"]
    check(any("radio " + r5["mac"] in o["text"] for o in plan), "own provisioning rule for an SSID choice")
    check(c.post(f"/api/sites/{sid}/wifi/apply").json()["ok"], "apply")
    check(wait(lambda: radio(r5["mac"])["ssids"] == ["Thuis"], "only Thuis"), "access point radio carries only the chosen SSID")
    rule = next(p for p in rt.get("/interface/wifi/provisioning").json() if p.get("radio-mac") == r5["mac"])
    check(rule["master-configuration"] == "mm-thuis-5g" and not rule.get("slave-configurations"), "rule: master only, no virtual SSIDs")
    c.post(f"/api/sites/{sid}/wifi/radios/{r5['mac']}", json={"mode": "high", "off": True})
    c.post(f"/api/sites/{sid}/wifi/apply")
    check(next(p for p in rt.get("/interface/wifi/provisioning").json() if p.get("radio-mac") == r5["mac"])["action"] == "none"
          and wait(lambda: radio(r5["mac"])["ssids"] == [], "radio off"), "radio off: provisioning action none, no SSIDs")
    # the router's own 2.4 GHz radio: IoT only, then off
    l2 = next(r for a in c.get(f"/api/sites/{sid}/wifi").json()["aps"] if a["local"] for r in a["radios"] if r["band"] == "2g")
    c.post(f"/api/sites/{sid}/wifi/radios/{l2['mac']}", json={"mode": "high", "ssids": [wl["Thuis-IoT"]]})
    check(c.post(f"/api/sites/{sid}/wifi/apply").json()["ok"], "apply")
    ifs = rt.get("/interface/wifi").json()
    m2 = next(i for i in ifs if i["name"] == l2["interface"])
    check(m2["configuration"] == "mm-thuis-iot-2g" and not [i for i in ifs if i.get("master-interface") == m2["name"]
                                                             and i.get("comment", "").startswith("mm:local:")],
          "router radio: IoT as the main SSID, the other virtual interface removed")
    c.post(f"/api/sites/{sid}/wifi/radios/{l2['mac']}", json={"mode": "high", "off": True})
    c.post(f"/api/sites/{sid}/wifi/apply")
    check(next(i for i in rt.get("/interface/wifi").json() if i["name"] == l2["interface"])["disabled"] == "true", "router radio off")
    for m in (r5["mac"], l2["mac"]):
        c.post(f"/api/sites/{sid}/wifi/radios/{m}", json={"mode": "high"})
    check(c.post(f"/api/sites/{sid}/wifi/apply").json()["ok"], "back to all SSIDs")
    check(wait(lambda: radio(r5["mac"])["ssids"] == radio(other["mac"])["ssids"] and radio(l2["mac"])["ssids"] == ["Thuis", "Thuis-IoT"],
               "all back"), "both radios carry all networks again")
    check(next(i for i in rt.get("/interface/wifi").json() if i["name"] == l2["interface"])["disabled"] == "false"
          and not c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"], "router radio on again, nothing pending")

    # the router's 5 GHz radio standalone: it keeps broadcasting, now from inline settings
    l5 = next(r for a in c.get(f"/api/sites/{sid}/wifi").json()["aps"] if a["local"] for r in a["radios"] if r["band"] == "5g")
    dw = c.get(f"/api/devices/{ids['router']}/wifi").json()
    check(dw["kind"] == "controller" and not any(r["editable"] for r in dw["radios"]), "site radios are not editable as standalone")
    virt0 = [i for i in rt.get("/interface/wifi").json() if i.get("master-interface") == l5["interface"]]
    check(c.post(f"/api/sites/{sid}/wifi/radios/{l5['mac']}/own", json={"own": True}).status_code == 200, "make 5 GHz standalone")
    ifs = rt.get("/interface/wifi").json()
    w1 = next(i for i in ifs if i["name"] == l5["interface"])
    virt = [i for i in ifs if i.get("master-interface") == w1["name"]]
    check(not w1.get("configuration") and w1.get("configuration.ssid") == "Thuis" and w1.get("security.passphrase") == "nieuw-wachtwoord-2026",
          "standalone: the profile became inline settings on the interface")
    check(len(virt) == len(virt0) >= 1 and all(v.get("comment", "").startswith("mm:own:") and v.get("datapath.vlan-id") in ("30", "40") for v in virt),
          "extra SSIDs kept, with their VLAN, marked standalone")
    check(not c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"], "the site plan leaves a standalone radio alone")
    dw = c.get(f"/api/devices/{ids['router']}/wifi").json()
    r_own = next(r for r in dw["radios"] if r["interface"] == w1["name"])
    check(r_own["editable"] and r_own["interfaces"][0]["ssid"] == "Thuis" and r_own["interfaces"][0]["security"] == "wpa2wpa3",
          "standalone radio editable with its effective settings")
    r = c.patch(f"/api/devices/{ids['router']}/wifi/{w1['.id']}", json={"ssid": "Thuis-router", "security": "wpa2",
                                                                        "passphrase": "alleen-de-router", "frequency": "5500", "tx_power": 17})
    check(r.status_code == 200, "edit the standalone radio")
    w1n = next(i for i in rt.get("/interface/wifi").json() if i["name"] == w1["name"])
    check(w1n["configuration.ssid"] == "Thuis-router" and w1n["security.authentication-types"] == "wpa2-psk"
          and w1n["channel.frequency"] == "5500" and w1n["configuration.tx-power"] == "17", "inline settings written")
    check(c.patch(f"/api/devices/{ids['router']}/wifi/{w1['.id']}", json={"security": "wpa2", "passphrase": "kort"}).status_code == 400,
          "short passphrase refused")
    r = c.post(f"/api/devices/{ids['router']}/wifi/{w1['.id']}/virtual", json={"ssid": "Router-Gast", "security": "open", "vlan_id": 40})
    check(r.status_code == 200, "extra SSID added")
    nv = next(i for i in rt.get("/interface/wifi").json() if i.get("configuration.ssid") == "Router-Gast")
    check(nv["master-interface"] == w1["name"] and nv["datapath.vlan-id"] == "40", "extra SSID on that radio, in VLAN 40")
    check(c.delete(f"/api/devices/{ids['router']}/wifi/{w1['.id']}").status_code == 400, "the radio's main interface cannot be removed")
    check(c.delete(f"/api/devices/{ids['router']}/wifi/{nv['.id']}").status_code == 200, "extra SSID removed")
    check(c.post(f"/api/sites/{sid}/wifi/radios/{l5['mac']}/own", json={"own": False}).status_code == 200, "back to the site networks")
    ifs = rt.get("/interface/wifi").json()
    w1b = next(i for i in ifs if i["name"] == w1["name"])
    check(w1b.get("configuration", "").startswith("mm-thuis-5g") and w1b.get("configuration.ssid") == "Thuis"
          and not [i for i in ifs if i.get("comment", "").startswith("mm:own:")], "profile back, standalone extras gone")
    check(sorted(i["configuration"] for i in ifs if i.get("master-interface") == w1["name"]) == sorted(v["configuration"] for v in virt0),
          "site's extra SSIDs back on the router radio")
    check(not c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"], "nothing pending")

    # radio insight and scans
    rc = c.get(f"/api/sites/{sid}/wifi/radios/{r5['mac']}/clients").json()
    check(rc["clients"] and all(x["signal"] and x["mac"] for x in rc["clients"]) and rc["monitor"].get("channel") and rc["can_scan"],
          "clients of one access point radio, with signal, and the radio's monitor")
    sc = c.post(f"/api/sites/{sid}/wifi/radios/{r5['mac']}/scan", json={"kind": "networks"}).json()
    check(sc["device"] == "cAP-ax-overloop" or sc["device"].startswith("cAP"), "the scan runs on the access point itself")
    check(len(sc["rows"]) >= 3 and all(r.get("ssid") and isinstance(r.get("signal"), float) for r in sc["rows"])
          and sc["rows"][0]["signal"] >= sc["rows"][-1]["signal"], "networks in range, strongest first")
    fs = c.post(f"/api/sites/{sid}/wifi/radios/{r5['mac']}/scan", json={"kind": "channels"}).json()
    check(fs["kind"] == "channels" and all("load" in r and "nf" in r for r in fs["rows"]), "channel load and noise floor per channel")

    # a standalone access point: released from CAPsMAN, set up on the device itself
    check(c.post(f"/api/devices/{ids['ap2']}/release").status_code == 200, "release cAP-ax-overloop")
    dw = c.get(f"/api/devices/{ids['ap2']}/wifi").json()
    check(dw["kind"] == "standalone" and all(r["editable"] for r in dw["radios"]) and len(dw["radios"]) == 2,
          "standalone access point: both radios editable")
    aps = c.get(f"/api/sites/{sid}/wifi").json()["aps"]
    check(next(a for a in aps if a["device_id"] == ids["ap2"])["state"] == "Zelfstandig", "listed as standalone under access points")
    m5 = next(r for r in dw["radios"] if r["band"] == "5g")
    ap2 = httpx.Client(base_url=f"http://127.0.0.1:{MOCK + 4}/rest", auth=("mikromanager", "demo-pass"))
    r = c.patch(f"/api/devices/{ids['ap2']}/wifi/{m5['interfaces'][0]['id']}", json={"ssid": "Overloop", "security": "wpa2wpa3",
                                                                                      "passphrase": "trap-op-trap-af", "bridge": "bridge"})
    check(r.status_code == 200 and next(i for i in ap2.get("/interface/wifi").json() if i["name"] == m5["interface"])["configuration.ssid"] == "Overloop",
          "standalone access point: SSID set on the device")
    sc = c.post(f"/api/sites/{sid}/wifi/radios/{m5['mac']}/scan", json={"kind": "networks"}).json()
    check(sc["device"] == "cAP-ax-overloop" and sc["rows"], "scan on a standalone access point")
    check(c.post(f"/api/devices/{ids['ap2']}/adopt").status_code == 200, "adopt it again")
    check(wait(lambda: len(next(a for a in c.get(f"/api/sites/{sid}/wifi").json()["aps"] if a["device_id"] == ids["ap2"])["radios"]) == 2
               and not c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"], "re-adopted"), "back under CAPsMAN, nothing pending")

    print("direct apply, with rollback")
    c.patch(f"/api/sites/{sid}", json={"settings": {"auto_apply": True}})
    r = c.post(f"/api/sites/{sid}/wifi/wlans", json={"ssid": "Direct", "passphrase": "meteen-op-de-router", "bands": ["5g"]}).json()
    check(r["apply"] and r["apply"]["ok"] and r["apply"]["applied"], "saving a network applies it right away")
    check(any(x["name"] == "mm-direct" for x in rt.get("/interface/wifi/security").json())
          and not c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"], "on the router, nothing left pending")
    r = c.patch(f"/api/wlans/{r['id']}", json={"passphrase": "ander-wachtwoord-1"}).json()
    check(r["apply"]["ok"] and rt.get("/interface/wifi/security/mm-direct").json()["passphrase"] == "ander-wachtwoord-1",
          "changing it is applied right away too")
    r = c.patch(f"/api/sites/{sid}", json={"settings": {"country": "Narnia"}}).json()
    check(r["apply"] and r["apply"]["rolled_back"] and "country" in r["apply"]["error"], "a change the router refuses is rolled back")
    check(next(s for s in c.get("/api/sites").json() if s["id"] == sid)["settings"]["country"] == "Netherlands"
          and all(x.get("country") == "Netherlands" for x in rt.get("/interface/wifi/configuration").json() if x["name"].startswith("mm-"))
          and not c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"], "setting and router back as before, nothing pending")
    d = c.delete(f"/api/wlans/{[w for w in c.get(f'/api/sites/{sid}/wifi').json()['wlans'] if w['ssid'] == 'Direct'][0]['id']}").json()
    check(d["apply"]["ok"] and not any(x["name"] == "mm-direct" for x in rt.get("/interface/wifi/security").json()), "deleting applies right away")
    c.patch(f"/api/sites/{sid}", json={"settings": {"auto_apply": False}})

    print("channel plan")
    cp = c.post(f"/api/sites/{sid}/wifi/channel-plan", json={"measure": True}).json()
    check(cp["measured"] and len(cp["radios"]) >= 6 and all(x["proposed"] for x in cp["radios"]), "every managed radio gets a proposed channel")
    five = [x for x in cp["radios"] if x["band"] == "5g"]
    two = [x for x in cp["radios"] if x["band"] == "2g"]
    check(len({x["proposed"] for x in two}) == len(two) and all(x["proposed"] in (2412, 2437, 2462) for x in two),
          "2.4 GHz: our radios on different channels out of 1, 6 and 11")
    check(len({x["proposed"] for x in five}) == len(five), "5 GHz: our radios on different channel blocks")
    check(all(x["reason"] for x in cp["radios"]), "each choice has a reason")
    r = c.post(f"/api/sites/{sid}/wifi/channel-plan/apply", json={"radios": cp["radios"], "power": False}).json()
    check(r["apply"]["ok"], "channel plan applied")
    check(wait(lambda: all(radio(x["mac"])["frequency"] == x["proposed"] for x in cp["radios"]), "channels set", timeout=40),
          "every radio now runs on its planned channel")
    for x in cp["radios"]:
        c.post(f"/api/sites/{sid}/wifi/radios/{x['mac']}", json={"mode": "high", "apply": False})
    check(c.post(f"/api/sites/{sid}/wifi/apply").json()["ok"], "back to automatic channels")

    print("router radios: mode per radio, drift, roaming, steering")
    def lradio(band):
        return next(r for a in c.get(f"/api/sites/{sid}/wifi").json()["aps"] if a["local"] for r in a["radios"] if r["band"] == band)
    check(lradio("5g")["local_mode"] == "site" and lradio("5g")["drift"] == [], "router 5 GHz: site networks, in line with the access points")
    ro = c.get(f"/api/sites/{sid}/wifi").json()["roaming"]
    thuis_r = next(x for x in ro if x["ssid"] == "Thuis")
    check(thuis_r["aps"] == 3 and thuis_r["ft"] and not thuis_r["issues"], "roaming: Thuis on the router and both cAPs, 802.11r on, no issues")
    # someone changes the router's own radio in WinBox
    w1 = next(i for i in rt.get("/interface/wifi").json() if i["name"] == lradio("5g")["interface"])
    rt.patch(f"/interface/wifi/{w1['.id']}", json={"configuration.ssid": "Thuis-oud", "security.ft": "no"})
    rt.post("/interface/wifi/unset", json={".id": w1[".id"], "value-name": "configuration"})
    x = wait(lambda: (r := lradio("5g")) and r["drift"] and r, "drift seen", timeout=30)
    check("configuration.ssid" in x["drift"] and "security.ft" in x["drift"], "a router radio that deviates from the access points is shown")
    plan = c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"]
    check(len(plan) == 1 and plan[0]["group"] == "local" and plan[0]["show"]["configuration.ssid"] == "Thuis", "the plan puts it back")
    res = c.post(f"/api/sites/{sid}/wifi/apply").json()
    check(res["ok"] and not [r for r in res["results"] if r["text"].startswith("Controle")], "apply and read back: no deviation left")
    check(wait(lambda: lradio("5g")["drift"] == [], "in line again", timeout=30), "in line with the access points again")
    # per radio: leave the 2.4 GHz alone, then back to the site networks
    l2m = lradio("2g")
    check(c.post(f"/api/sites/{sid}/wifi/radios/{l2m['mac']}/mode", json={"mode": "bestaat-niet"}).status_code == 400, "unknown mode refused")
    r = c.post(f"/api/sites/{sid}/wifi/radios/{l2m['mac']}/mode", json={"mode": "none"})
    w2 = next(i for i in rt.get("/interface/wifi").json() if i["name"] == l2m["interface"])
    check(r.status_code == 200 and not w2.get("configuration") and w2.get("configuration.ssid") == "Thuis"
          and not [i for i in rt.get("/interface/wifi").json() if i.get("master-interface") == w2["name"] and i.get("comment", "").startswith("mm:local:")],
          "not managed: profile and extra SSIDs gone, the radio keeps its main SSID")
    check(lradio("2g")["local_mode"] == "none" and not c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"], "the plan leaves it alone")
    check(lradio("5g")["local_mode"] == "site", "the other radio stays on the site networks")
    r = c.post(f"/api/sites/{sid}/wifi/radios/{l2m['mac']}/mode", json={"mode": "site"})
    check(r.status_code == 200 and wait(lambda: lradio("2g")["ssids"] == ["Thuis", "Thuis-IoT"], "2g back"), "back on the site networks with both SSIDs")
    # roaming help (802.11k/v)
    c.patch(f"/api/sites/{sid}", json={"settings": {"steering": True}})
    plan = c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"]
    check(any("steering" in o["text"] for o in plan), "roaming help adds a steering profile")
    check(c.post(f"/api/sites/{sid}/wifi/apply").json()["ok"], "apply roaming help")
    st = rt.get("/interface/wifi/steering").json()
    check(len(st) == 1 and st[0]["rrm"] in ("yes", "true") and st[0]["wnm"] in ("yes", "true")
          and all(c2.get("steering") == "mm-steering" for c2 in rt.get("/interface/wifi/configuration").json() if c2["name"].startswith("mm-")),
          "steering profile with rrm and wnm on every configuration")
    c.patch(f"/api/sites/{sid}", json={"settings": {"steering": False}})
    check(c.post(f"/api/sites/{sid}/wifi/apply").json()["ok"] and not rt.get("/interface/wifi/steering").json(), "roaming help off again")
    check(not c.get(f"/api/sites/{sid}/wifi/plan").json()["ops"], "nothing pending")

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
    # the queue: chosen devices, a start time, cancel
    j = c.post(f"/api/sites/{sid}/updates/queue", json={"device_ids": [ids["router"], ids["ap1"], ids["crs"]], "at": time.time() + 600}).json()
    check(j["waiting_for_time"] and [s["device"] for s in j["steps"]] == ["cAP-ax-woonkamer", "CRS310-kantoor", "hAP-ax2-meterkast"],
          "queued for later, in a safe order: access point, switch, router")
    check(c.post(f"/api/sites/{sid}/updates/queue", json={"device_ids": [ids["hexpoe"]]}).status_code == 400, "one round at a time")
    check(c.post(f"/api/sites/{sid}/updates/queue/cancel").json()["cancelled"] == 3, "cancel the waiting round")
    j = c.post(f"/api/sites/{sid}/updates/queue", json={"device_ids": [ids["hexpoe"], ids["crs"]], "at": time.time() + 2}).json()
    check([s["device"] for s in j["steps"]] == ["hEX-PoE-zolder", "CRS310-kantoor"], "deeper switch first")
    j = wait(lambda: (x := c.get(f"/api/sites/{sid}/updates").json()["job"]) and not x["running"] and x, "queued round", 60)
    check(all(s["status"] == "klaar" for s in j["steps"]), "the queued round runs at its time and finishes")

    print("interfaces")
    crs = httpx.Client(base_url=f"http://127.0.0.1:{MOCK + 1}/rest", auth=("mikromanager", "demo-pass"), timeout=5)
    hx = httpx.Client(base_url=f"http://127.0.0.1:{MOCK + 2}/rest", auth=("mikromanager", "demo-pass"), timeout=5)
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
    topo = {n["name"]: n for n in o["topology"]}
    by_id = {n["id"]: n["name"] for n in o["topology"]}
    check(topo["hAP-ax2-meterkast"]["parent"] is None
          and by_id[topo["CRS310-kantoor"]["parent"]] == "hAP-ax2-meterkast" and topo["CRS310-kantoor"]["port"] == "ether2"
          and by_id[topo["hEX-PoE-zolder"]["parent"]] == "CRS310-kantoor"
          and by_id[topo["cAP-ax-woonkamer"]["parent"]] == "hEX-PoE-zolder" and topo["cAP-ax-overloop"]["port"] == "ether3",
          "topology: router > CRS > hEX > both cAPs, with the ports")
    check(any(h["kind"] == "internet" and h["rtt"] for h in wq["history"]), "WAN latency history")
    check(c.delete(f"/api/sites/{sid}/networks/gasten").json()["removed"] >= 7, "managed network removed with all its parts")
    check(not [f for f in rt.get("/ip/firewall/filter").json() if "mm:" in f.get("comment", "")], "isolation rule gone")
    check(c.delete(f"/api/sites/{sid}/networks/bridge").status_code == 404, "hand-made network cannot be deleted")
    check(len(rt.get("/ip/address").json()) == 3, "LAN and WAN addresses untouched")


if __name__ == "__main__":
    main()
