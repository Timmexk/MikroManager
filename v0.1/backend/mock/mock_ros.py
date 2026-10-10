"""A small simulated RouterOS v7 REST API for tests and demo mode.

Five devices on consecutive ports that share one "world":
  router  hAP ax2   (CAPsMAN controller, 2 local radios, DHCP, firewall)
  crs     CRS310    (switch, no wifi menu, no `:execute as-string`)
  hexpoe  hEX PoE   (switch with PoE-out feeding the APs)
  ap1/2   cAP ax    (become CAPs once /interface/wifi/cap is enabled)

It mimics the parts of RouterOS that TikControl uses: string-typed values,
PUT/PATCH/DELETE/POST semantics, reference checks between wifi profiles,
provisioning rules that create dynamic interfaces, reboots during upgrades.
It is NOT a faithful RouterOS; real hardware remains the reference.
"""
import asyncio
import base64
import ipaddress
import math
import os
import random
import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

USER, PASSWORD = "tikcontrol", "demo-pass"
REBOOT_SECS = float(os.environ.get("MOCK_REBOOT_SECS", "25"))
BASE_PORT = int(os.environ.get("MOCK_BASE_PORT", "18081"))
LATEST = "7.20.2"

WIFI_REFS = {"security": "/interface/wifi/security", "datapath": "/interface/wifi/datapath",
             "channel": "/interface/wifi/channel"}
ALLOWED = {
    "/interface/wifi/security": {"name", "authentication-types", "passphrase", "ft", "ft-over-ds", "wps", "comment", "disabled"},
    "/interface/wifi/datapath": {"name", "bridge", "vlan-id", "client-isolation", "comment", "disabled", "interface-list"},
    "/interface/wifi/channel": {"name", "width", "frequency", "band", "skip-dfs-channels", "comment", "disabled"},
    "/interface/wifi/configuration": {"name", "ssid", "country", "security", "datapath", "channel", "hide-ssid", "comment",
                                      "disabled", "mode"},
    "/interface/wifi/provisioning": {"action", "supported-bands", "master-configuration", "slave-configurations", "comment",
                                     "disabled", "radio-mac", "identity-regexp", "name-format"},
    "/interface/wifi/access-list": {"mac-address", "action", "comment", "disabled", "interface", "ssid-regexp"},
    "/interface/vlan": {"name", "vlan-id", "interface", "comment", "disabled"},
    "/ip/dhcp-server": {"name", "interface", "address-pool", "disabled", "comment", "lease-time"},
}
EXPORT_ORDER = ["/interface/bridge", "/interface/vlan", "/interface/list", "/interface/wifi/channel",
                "/interface/wifi/datapath", "/interface/wifi/security", "/interface/wifi/configuration",
                "/interface/wifi", "/ip/pool", "/ip/dhcp-server", "/interface/bridge/port", "/interface/bridge/vlan",
                "/interface/list/member", "/interface/wifi/access-list", "/interface/wifi/provisioning", "/ip/address",
                "/ip/dhcp-server/lease", "/ip/dhcp-server/network", "/ip/dns/static", "/ip/firewall/address-list",
                "/ip/firewall/filter"]


def norm(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    v = str(v)
    return {"yes": "true", "no": "false"}.get(v, v)


def mac(prefix: str, n: int) -> str:
    return f"{prefix}:{n >> 8 & 0xFF:02X}:{n & 0xFF:02X}"


def fmt_uptime(sec: float) -> str:
    sec = int(sec)
    w, sec = divmod(sec, 604800)
    d, sec = divmod(sec, 86400)
    h, sec = divmod(sec, 3600)
    m, s = divmod(sec, 60)
    return "".join(f"{n}{u}" for n, u in ((w, "w"), (d, "d"), (h, "h"), (m, "m"), (s, "s")) if n or u == "s")


class Dev:
    def __init__(self, world, key, port, identity, board, arch, ip, mac_prefix, ports, radios=(), poe=(),
                 version="7.20.1", fw=("7.20.1", "7.20.1"), has_wifi=True, exec_as_string=True, uptime=0.0):
        self.world, self.key, self.port, self.ip, self.board, self.arch = world, key, port, ip, board, arch
        self.version, self.fw_cur, self.fw_new, self.fw_pending = version, fw[0], fw[1], False
        self.ports, self.radios, self.poe = list(ports), list(radios), list(poe)
        self.has_wifi, self.exec_as_string = has_wifi, exec_as_string
        self.mac_prefix = mac_prefix
        self.boot = time.time() - uptime
        self.reboot_until = 0.0
        self.after_reboot = None
        self.seq = 0x10
        self.local_provisioned = False
        self.kicked: dict[str, float] = {}
        self.static_leases: dict[str, dict] = {}
        self.files: list[dict] = []
        self.last_tick = time.time()
        self.t: dict[str, list[dict]] = {}
        self.single = {"/system/identity": {"name": identity},
                       "/system/package/update": {"channel": "stable", "installed-version": version}}
        self.base_mac = mac(mac_prefix, 0)
        self._build_interfaces()

    # -- construction ------------------------------------------------------
    def nid(self) -> str:
        self.seq += 1
        return f"*{self.seq:X}"

    def _build_interfaces(self):
        ifs, eth = [], []
        for n, p in enumerate(self.ports):
            m = mac(self.mac_prefix, n + 1)
            ifs.append({".id": self.nid(), "name": p, "default-name": p, "type": "ether", "mtu": "1500", "mac-address": m,
                        "running": "false", "disabled": "false", "rx-byte": str(random.randint(10 ** 8, 10 ** 10)),
                        "tx-byte": str(random.randint(10 ** 8, 10 ** 10))})
            eth.append({".id": ifs[-1][".id"], "name": p, "default-name": p, "mac-address": m, "disabled": "false"})
        ifs.append({".id": self.nid(), "name": "bridge", "type": "bridge", "mtu": "1500", "mac-address": self.base_mac,
                    "running": "true", "disabled": "false", "rx-byte": "0", "tx-byte": "0"})
        self.t["/interface"], self.t["/interface/ethernet"] = ifs, eth
        self.t["/interface/bridge"] = [{".id": self.nid(), "name": "bridge", "vlan-filtering": "true",
                                        "mac-address": self.base_mac, "disabled": "false", "protocol-mode": "rstp"}]
        self.t["/interface/bridge/port"] = [{".id": self.nid(), "interface": p, "bridge": "bridge", "pvid": "1",
                                             "disabled": "false"} for p in self.ports if not (self.key == "router" and p == "ether1")]
        self.t["/interface/bridge/vlan"] = []
        self.t["/interface/vlan"] = []
        self.t["/interface/list"] = [{".id": self.nid(), "name": n, "builtin": "true"} for n in ("all", "none", "dynamic", "static")]
        self.t["/interface/list/member"] = []
        self.t["/ip/address"] = []
        self.t["/ip/dns/static"] = []
        self.t["/system/package"] = [{".id": "*1", "name": "routeros", "version": self.version}]
        if self.has_wifi:
            self.t["/system/package"].append({".id": "*2", "name": "wifi-qcom", "version": self.version})
            for p in ("security", "datapath", "channel", "configuration", "provisioning", "access-list"):
                self.t[f"/interface/wifi/{p}"] = []
            self.t["/interface/wifi"] = []
            for n, (name, band) in enumerate(self.radios):
                self.t["/interface/wifi"].append({
                    ".id": self.nid(), "name": name, "default-name": name, "radio-mac": mac(self.mac_prefix, 0x80 + n),
                    "mac-address": mac(self.mac_prefix, 0x80 + n), "disabled": "false", "running": "true", "dynamic": "false",
                    "configuration.manager": "local", "configuration.mode": "ap", "configuration.ssid": "MikroTik-oud",
                    "security.authentication-types": "wpa2-psk", "master": "true"})
            self.single["/interface/wifi/capsman"] = {"enabled": "false", "interfaces": "", "ca-certificate": "none"}
            self.single["/interface/wifi/cap"] = {"enabled": "false", "discovery-interfaces": ""}

    # -- state -------------------------------------------------------------
    @property
    def rebooting(self) -> bool:
        if self.reboot_until and time.time() >= self.reboot_until:
            self.reboot_until = 0.0
            self.boot = time.time()
            if self.after_reboot:
                self.after_reboot()
                self.after_reboot = None
        return bool(self.reboot_until)

    def reboot(self, then=None):
        self.reboot_until = time.time() + REBOOT_SECS
        self.after_reboot = then

    def tick(self):
        now = time.time()
        dt, self.last_tick = now - self.last_tick, now
        linked = self.world.linked_ports(self)
        for i in self.t["/interface"]:
            if i["type"] != "ether":
                continue
            up = i["name"] in linked and i["disabled"] == "false"
            i["running"] = norm(up)
            if not up:
                continue
            base = linked[i["name"]]
            wave = 0.55 + 0.45 * math.sin(now / 240 + hash(i["name"]) % 7) + random.uniform(-0.15, 0.15)
            rate = max(0.02, wave) * base
            i["rx-byte"] = str(int(i["rx-byte"]) + int(rate * dt / 8))
            i["tx-byte"] = str(int(i["tx-byte"]) + int(rate * 0.18 * dt / 8))

    def resource(self) -> dict:
        total = 1024 ** 3 if "ax" in self.board else 512 * 1024 ** 2
        return {"uptime": fmt_uptime(time.time() - self.boot), "version": f"{self.version} (stable)",
                "build-time": "2026-09-18 09:12:44", "free-memory": str(int(total * random.uniform(0.52, 0.6))),
                "total-memory": str(total), "cpu": "ARM64", "cpu-count": "4", "cpu-frequency": "864",
                "cpu-load": str(random.randint(1, 9) + (12 if self.key == "router" else 0)),
                "free-hdd-space": "92000000", "total-hdd-space": "128000000", "architecture-name": self.arch,
                "board-name": self.board, "platform": "MikroTik"}

    # -- derived tables ----------------------------------------------------
    def all_radios(self):
        """(owner device, local iface, band, radio mac, is_local) for every radio this CAPsMAN sees."""
        out = [(self, n, b, mac(self.mac_prefix, 0x80 + i), True) for i, (n, b) in enumerate(self.radios)]
        if self.single.get("/interface/wifi/capsman", {}).get("enabled") == "true":
            for ap in self.world.devs.values():
                if ap is not self and ap.has_wifi and ap.single["/interface/wifi/cap"]["enabled"] == "true" and not ap.reboot_until:
                    out += [(ap, n, b, mac(ap.mac_prefix, 0x80 + i), False) for i, (n, b) in enumerate(ap.radios)]
        return out

    def _rule_for(self, band: str):
        for r in self.t["/interface/wifi/provisioning"]:
            sb = r.get("supported-bands", "")
            if r.get("disabled") != "true" and (not sb or sb.startswith("2ghz" if band == "2g" else "5ghz")):
                return r
        return None

    def dyn_wifi(self) -> list[dict]:
        out, n = [], 0
        for owner, _, band, rmac, local in self.all_radios():
            if local and not self.local_provisioned:
                continue
            rule = self._rule_for(band)
            if not rule or rule.get("action") == "none":
                continue
            n += 1
            master = f"cap-wifi{n}"
            common = {"dynamic": "true", "disabled": "false", "running": "true", "bound": "true", "inactive": "false"}
            out.append({".id": f"*D{n:02d}0", "name": master, "radio-mac": rmac, "configuration": rule["master-configuration"],
                        "master": "true", **common})
            for j, sc in enumerate(x for x in rule.get("slave-configurations", "").split(",") if x):
                out.append({".id": f"*D{n:02d}{j + 1}", "name": f"{master}-virtual{j + 1}", "master-interface": master,
                            "configuration": sc, "master": "false", **common})
        return out

    def wifi_ifaces(self) -> list[dict]:
        static = [] if self.local_provisioned else self.t["/interface/wifi"]
        return static + self.dyn_wifi()

    def radio_table(self) -> list[dict]:
        ifs = {i.get("radio-mac"): i["name"] for i in self.wifi_ifaces() if i.get("radio-mac")}
        out = []
        for n, (owner, _, band, rmac, local) in enumerate(self.all_radios()):
            g = "2ghz" if band == "2g" else "5ghz"
            rec = {".id": f"*R{n}", "radio-mac": rmac, "local": norm(local), "tx-chains": "0,1", "rx-chains": "0,1",
                   "bands": f"{g}-n:20mhz,20/40mhz,{g}-ax:20mhz,20/40mhz" + (",20/40/80mhz" if band == "5g" else ""),
                   "hw-type": "QCA6018", "countries": "all"}
            if not local:
                rec["cap"] = f"{owner.single['/system/identity']['name']}@{owner.ip}"
            if rmac in ifs:
                rec["interface"] = ifs[rmac]
            out.append(rec)
        return out

    def remote_caps(self) -> list[dict]:
        seen, out = set(), []
        for owner, *_rest, local in self.all_radios():
            if not local and owner.key not in seen:
                seen.add(owner.key)
                out.append({".id": f"*C{len(out)}", "address": owner.ip, "identity": owner.single["/system/identity"]["name"],
                            "board-name": owner.board, "version": owner.version, "state": "Ok",
                            "base-mac": owner.base_mac, "serial": f"HG{owner.mac_prefix[-2:]}0A1B2C"})
        return out

    def ssid_of(self, iface: dict) -> str | None:
        if iface.get("configuration.ssid"):
            return iface["configuration.ssid"]
        cfg = next((c for c in self.t["/interface/wifi/configuration"] if c["name"] == iface.get("configuration")), None)
        return cfg.get("ssid") if cfg else None

    def reg_table(self) -> list[dict]:
        if not self.has_wifi:
            return []
        blocked = {a.get("mac-address") for a in self.t["/interface/wifi/access-list"] if a.get("action") == "reject"}
        radio_owner = {rmac: (owner.key, band) for owner, _, band, rmac, _l in self.all_radios()}
        ifs = self.wifi_ifaces()
        by_name = {i["name"]: i for i in ifs}
        out, now = [], time.time()
        for c in self.world.clients:
            if c["type"] != "wifi" or c["mac"] in blocked or self.kicked.get(c["mac"], 0) > now:
                continue
            for i in ifs:
                root = by_name.get(i.get("master-interface", ""), i)
                if radio_owner.get(root.get("radio-mac")) == (c["ap"], c["band"]) and self.ssid_of(i) == c["ssid"]:
                    sig = c["signal"] + int(3 * math.sin(now / 30 + c["n"]))
                    g = "2ghz-ax" if c["band"] == "2g" else "5ghz-ax"
                    used = int((now - self.world.t0 + 3600 * (c["n"] + 1)) * c["bps"] / 8)
                    out.append({".id": f"*W{c['n']:02d}", "interface": i["name"], "ssid": c["ssid"], "mac-address": c["mac"],
                                "uptime": fmt_uptime(now - self.world.t0 + 900 * (c["n"] + 3)), "signal": str(sig),
                                "band": g, "auth-type": "wpa3-psk" if c["n"] % 2 else "wpa2-psk", "authorized": "true",
                                "tx-rate": "286Mbps-20MHz/2S/GI0.8us" if c["band"] == "2g" else "1.2Gbps-80MHz/2S/GI0.8us",
                                "rx-rate": "229Mbps-20MHz/2S" if c["band"] == "2g" else "864Mbps-80MHz/2S",
                                "bytes": f"{used},{used // 6}", "packets": f"{used // 900},{used // 5000}"})
                    break
        return out

    def leases(self) -> list[dict]:
        if "/ip/dhcp-server" not in self.t:
            return []
        nets = []
        for a in self.t["/ip/address"]:
            srv = next((s for s in self.t["/ip/dhcp-server"] if s["interface"] == a["interface"]), None)
            if srv:
                nets.append((ipaddress.ip_interface(a["address"]).network, srv["name"]))
        online = {r["mac-address"] for r in self.reg_table()}
        out = list(self.static_leases.values())
        for c in self.world.clients:
            if c["mac"] in self.static_leases:
                continue
            srv = next((name for net, name in nets if ipaddress.ip_address(c["ip"]) in net), None)
            if not srv:
                continue
            up = c["type"] == "wired" or c["mac"] in online
            out.append({".id": f"*L{c['n']:02d}", "address": c["ip"], "mac-address": c["mac"], "server": srv,
                        "dynamic": "true", "status": "bound" if up else "waiting", "host-name": c["host"],
                        "last-seen": "12s" if up else "3h14m", **({"active-address": c["ip"]} if up else {})})
        return out

    def hosts(self) -> list[dict]:
        out = [{".id": "*H0", "mac-address": self.base_mac, "on-interface": "bridge", "bridge": "bridge", "local": "true",
                "dynamic": "true"}]
        seen = self.world.learned(self)
        for n, (m, port) in enumerate(sorted(seen.items())):
            out.append({".id": f"*H{n + 1}", "mac-address": m, "on-interface": port, "bridge": "bridge", "local": "false",
                        "dynamic": "true"})
        return out

    def table(self, path: str) -> list[dict] | None:
        if path.startswith("/interface/wifi") and not self.has_wifi:
            return None
        dyn = {"/interface/wifi": self.wifi_ifaces, "/interface/wifi/radio": self.radio_table,
               "/interface/wifi/capsman/remote-cap": self.remote_caps, "/interface/wifi/registration-table": self.reg_table,
               "/ip/dhcp-server/lease": self.leases, "/interface/bridge/host": self.hosts,
               "/system/health": lambda: [{".id": "*1", "name": "temperature", "value": str(44 + self.port % 9), "type": "C"}]
               + ([{".id": "*2", "name": "voltage", "value": "24.1", "type": "V"}] if self.poe else []),
               "/file": lambda: self.files,
               "/interface/ethernet/poe": lambda: [{".id": f"*P{n}", "name": p, "poe-out": "auto-on"} for n, p in enumerate(self.poe)],
               "/ip/arp": lambda: [{".id": f"*A{n}", "address": l.get("active-address", l["address"]), "mac-address": l["mac-address"],
                                    "interface": "bridge", "complete": "true", "dynamic": "true"}
                                   for n, l in enumerate(self.leases()) if l.get("status") == "bound"]}
        if path in dyn:
            if path == "/ip/dhcp-server/lease" and "/ip/dhcp-server" not in self.t:
                return None
            return dyn[path]()
        if path == "/interface":
            extra = [{".id": v[".id"], "name": v["name"], "type": "vlan", "mtu": "1500", "running": "true",
                      "disabled": v.get("disabled", "false"), "mac-address": self.base_mac, "rx-byte": "0", "tx-byte": "0"}
                     for v in self.t["/interface/vlan"]]
            extra += [{".id": w[".id"], "name": w["name"], "type": "wifi", "mtu": "1500", "running": w.get("running", "true"),
                       "disabled": w.get("disabled", "false"), "mac-address": w.get("mac-address", w.get("radio-mac", "")),
                       "rx-byte": "0", "tx-byte": "0"} for w in (self.wifi_ifaces() if self.has_wifi else [])]
            return self.t["/interface"] + extra
        return self.t.get(path)

    # -- export ------------------------------------------------------------
    def export(self) -> str:
        ident = self.single["/system/identity"]["name"]
        lines = [f"# {time.strftime('%Y-%m-%d %H:%M:%S')} by RouterOS {self.version}", "# software id = TK7C-DEMO", "#",
                 f"# model = {self.board}", f"# serial number = HG{self.mac_prefix[-2:]}0A1B2C"]
        skip = {".id", "dynamic", "running", "builtin", "master", "default-name", "radio-mac", "mac-address", "bound", "inactive"}
        for path in EXPORT_ORDER:
            rows = [r for r in self.t.get(path, []) if r.get("dynamic") != "true" and r.get("builtin") != "true"]
            if path == "/ip/dhcp-server/lease":
                rows = list(self.static_leases.values())
            if not rows:
                continue
            lines.append(path.replace("/", " ").replace(" ", "/", 1))
            for r in rows:
                kv = " ".join(f'{k}={v if v and " " not in v else chr(34) + v + chr(34)}' for k, v in sorted(r.items())
                              if k not in skip and not (k == "passphrase"))
                lines.append(f"add {kv}")
        for path, s in sorted(self.single.items()):
            if path.startswith("/interface/wifi/"):
                lines += [path.replace("/", " ").replace(" ", "/", 1), "set " + " ".join(f"{k}={v}" for k, v in sorted(s.items()) if v)]
        lines += ["/system identity", f'set name="{ident}"']
        return "\n".join(lines) + "\n"


class World:
    def __init__(self):
        self.t0 = time.time()
        self.devs: dict[str, Dev] = {}
        self.clients: list[dict] = []
        # child device -> (parent device, port on the parent); every child uplinks on ether1
        self.links = {"crs": ("router", "ether2"), "hexpoe": ("crs", "ether2"), "ap1": ("hexpoe", "ether2"),
                      "ap2": ("hexpoe", "ether3")}
        self._build()

    def _build(self):
        p = BASE_PORT
        d = self.devs
        d["router"] = Dev(self, "router", p, "hAP-ax2-meterkast", "hAP ax^2", "arm64", "192.168.88.1", "48:A9:8A:10",
                          [f"ether{i}" for i in range(1, 6)], radios=[("wifi1", "5g"), ("wifi2", "2g")], uptime=19 * 86400 + 7000)
        d["crs"] = Dev(self, "crs", p + 1, "CRS310-kantoor", "CRS310-8G+2S+", "arm", "192.168.88.2", "48:A9:8A:20",
                       [f"ether{i}" for i in range(1, 9)] + ["sfp-sfpplus1", "sfp-sfpplus2"], has_wifi=False,
                       exec_as_string=False, uptime=41 * 86400, fw=("7.19.4", "7.20.1"))
        d["hexpoe"] = Dev(self, "hexpoe", p + 2, "hEX-PoE-zolder", "hEX PoE", "mipsbe", "192.168.88.3", "48:A9:8A:30",
                          [f"ether{i}" for i in range(1, 6)] + ["sfp1"], poe=["ether2", "ether3", "ether4", "ether5"],
                          has_wifi=False, uptime=41 * 86400)
        d["ap1"] = Dev(self, "ap1", p + 3, "cAP-ax-woonkamer", "cAP ax", "arm64", "192.168.88.11", "48:A9:8A:41",
                       ["ether1", "ether2"], radios=[("wifi1", "5g"), ("wifi2", "2g")], uptime=12 * 86400)
        d["ap2"] = Dev(self, "ap2", p + 4, "cAP-ax-overloop", "cAP ax", "arm64", "192.168.88.12", "48:A9:8A:42",
                       ["ether1", "ether2"], radios=[("wifi1", "5g"), ("wifi2", "2g")], uptime=12 * 86400)

        r = d["router"]
        r.t["/interface/list"] += [{".id": r.nid(), "name": "WAN", "builtin": "false"}, {".id": r.nid(), "name": "LAN", "builtin": "false"}]
        r.t["/interface/list/member"] = [{".id": r.nid(), "list": "WAN", "interface": "ether1"},
                                         {".id": r.nid(), "list": "LAN", "interface": "bridge"}]
        r.t["/ip/address"] = [{".id": r.nid(), "address": "192.168.88.1/24", "network": "192.168.88.0", "interface": "bridge",
                               "comment": "defconf", "dynamic": "false", "disabled": "false"},
                              {".id": r.nid(), "address": "203.0.113.42/24", "network": "203.0.113.0", "interface": "ether1",
                               "dynamic": "true", "disabled": "false"}]
        r.t["/ip/pool"] = [{".id": r.nid(), "name": "default-dhcp", "ranges": "192.168.88.10-192.168.88.254"}]
        r.t["/ip/dhcp-server"] = [{".id": r.nid(), "name": "defconf", "interface": "bridge", "address-pool": "default-dhcp",
                                   "disabled": "false"}]
        r.t["/ip/dhcp-server/network"] = [{".id": r.nid(), "address": "192.168.88.0/24", "gateway": "192.168.88.1",
                                           "dns-server": "192.168.88.1", "comment": "defconf"}]
        r.t["/ip/route"] = [{".id": "*8000", "dst-address": "0.0.0.0/0", "gateway": "203.0.113.1",
                             "immediate-gw": "203.0.113.1%ether1", "active": "true", "dynamic": "true", "distance": "1"}]
        r.t["/ip/firewall/address-list"] = []
        r.t["/ip/firewall/filter"] = [
            {".id": r.nid(), "chain": "input", "action": "accept", "connection-state": "established,related,untracked", "comment": "defconf: accept established,related,untracked"},
            {".id": r.nid(), "chain": "input", "action": "drop", "in-interface-list": "!LAN", "comment": "defconf: drop all not coming from LAN"},
            {".id": r.nid(), "chain": "forward", "action": "fasttrack-connection", "connection-state": "established,related", "comment": "defconf: fasttrack"},
            {".id": r.nid(), "chain": "forward", "action": "accept", "connection-state": "established,related,untracked", "comment": "defconf: accept established,related, untracked"},
            {".id": r.nid(), "chain": "forward", "action": "drop", "connection-state": "invalid", "comment": "defconf: drop invalid"},
            {".id": r.nid(), "chain": "forward", "action": "drop", "connection-nat-state": "!dstnat", "in-interface-list": "WAN", "comment": "defconf: drop all from WAN not DSTNATed"}]
        r.t["/ip/dns/static"] = [{".id": r.nid(), "name": "router.lan", "address": "192.168.88.1", "type": "A", "comment": "defconf"}]
        for dev in d.values():
            if dev is not r:
                dev.t["/ip/address"] = [{".id": dev.nid(), "address": f"{dev.ip}/24", "network": "192.168.88.0",
                                         "interface": "bridge", "dynamic": "true", "disabled": "false"}]

        def wifi(host, ap, band, ssid, ip, signal, bps=2e5):
            self.clients.append({"n": len(self.clients), "type": "wifi", "host": host, "ap": ap, "band": band, "ssid": ssid,
                                 "ip": ip, "signal": signal, "bps": bps, "mac": mac("D6:3A:91:5C", 0x100 + len(self.clients) * 7)})

        def wired(host, dev, port, ip):
            self.clients.append({"n": len(self.clients), "type": "wired", "host": host, "dev": dev, "port": port, "ip": ip,
                                 "mac": mac("00:E0:4C:68", 0x200 + len(self.clients) * 5)})

        wifi("iPhone", "ap1", "5g", "Thuis", "192.168.88.101", -52, 9e5)
        wifi("Pixel-8", "ap2", "5g", "Thuis", "192.168.88.102", -61, 4e5)
        wifi("MacBook-Air", "router", "5g", "Thuis", "192.168.88.103", -47, 3e6)
        wifi("iPad", "ap1", "5g", "Thuis", "192.168.88.104", -58, 6e5)
        wifi("Galaxy-Tab-S9", "ap2", "5g", "Thuis", "192.168.88.105", -66, 2e5)
        wifi("Steam-Deck", "ap1", "5g", "Thuis", "192.168.88.106", -55, 1.5e6)
        wifi("shelly-plug-keuken", "ap1", "2g", "Thuis-IoT", "192.168.30.21", -63, 2e3)
        wifi("esp32-display", "router", "2g", "Thuis-IoT", "192.168.30.22", -44, 3e3)
        wifi("tasmota-wasmachine", "ap2", "2g", "Thuis-IoT", "192.168.30.23", -71, 2e3)
        wifi("roborock-s8", "ap1", "2g", "Thuis-IoT", "192.168.30.24", -68, 8e3)
        wifi("sonos-woonkamer", "ap1", "5g", "Thuis-IoT", "192.168.30.25", -50, 3e5)
        wifi("p1-meter", "router", "2g", "Thuis-IoT", "192.168.30.26", -57, 1e3)
        wifi("OnePlus-Nord", "ap2", "5g", "Thuis-Gast", "192.168.40.31", -64, 5e5)
        wired("nas", "crs", "ether3", "192.168.88.20")
        wired("homeassistant", "crs", "ether4", "192.168.88.21")
        wired("werk-pc", "crs", "ether5", "192.168.88.22")
        wired("adguard", "crs", "ether6", "192.168.88.23")
        wired("tv-woonkamer", "hexpoe", "ether4", "192.168.88.24")
        wired("printer", "hexpoe", "ether5", "192.168.88.25")

    # -- topology helpers --------------------------------------------------
    def subtree(self, key: str) -> set[str]:
        out = {key}
        for child, (parent, _) in self.links.items():
            if parent == key:
                out |= self.subtree(child)
        return out

    def _port_towards(self, dev: Dev, target: str) -> str | None:
        if target == dev.key:
            return None
        for child, (parent, port) in self.links.items():
            if parent == dev.key and target in self.subtree(child):
                return port
        return "ether1" if dev.key in self.links else None

    def linked_ports(self, dev: Dev) -> dict[str, float]:
        """port -> typical bit rate, for every port that has link."""
        out = {}
        if dev.key == "router":
            out["ether1"] = 38e6
        if dev.key in self.links:
            out["ether1"] = 6e6
        for child, (parent, port) in self.links.items():
            if parent == dev.key:
                out[port] = 6e6 if child in ("crs", "hexpoe") else 2.5e6
        for c in self.clients:
            if c["type"] == "wired" and c["dev"] == dev.key:
                out[c["port"]] = 1.2e6
        return out

    def learned(self, dev: Dev) -> dict[str, str]:
        """MAC -> port for the bridge host table of `dev`."""
        out = {}
        ctrl = self.devs["router"]
        online = {r["mac-address"]: r["interface"] for r in ctrl.reg_table()}
        for other in self.devs.values():
            port = self._port_towards(dev, other.key)
            if port:
                out[other.base_mac] = port
        for c in self.clients:
            if c["type"] == "wired":
                port = c["port"] if c["dev"] == dev.key else self._port_towards(dev, c["dev"])
            elif c["mac"] in online:
                port = ("wifi1" if c["band"] == "5g" else "wifi2") if c["ap"] == dev.key else self._port_towards(dev, c["ap"])
            else:
                continue
            if port:
                out[c["mac"]] = port
        return out


def err(status: int, detail: str):
    msg = {400: "Bad Request", 401: "Unauthorized", 404: "Not Found", 406: "Not Acceptable"}.get(status, "Error")
    return JSONResponse({"error": status, "message": msg, "detail": detail}, status_code=status)


def make_app(dev: Dev) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    expected = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()

    def find(rows, ident):
        return next((r for r in rows if r.get(".id") == ident or r.get("name") == ident), None)

    def validate(path: str, data: dict, current: dict | None = None):
        allowed = ALLOWED.get(path)
        if allowed:
            bad = [k for k in data if k not in allowed]
            if bad:
                return f"unknown parameter {bad[0]}"
        merged = {**(current or {}), **data}
        if "name" in data and any(r.get("name") == data["name"] and r is not current for r in dev.t.get(path, [])):
            return "failure: already have such name"
        if path == "/interface/wifi/configuration":
            for key, ref in WIFI_REFS.items():
                if merged.get(key) and not find(dev.t[ref], merged[key]):
                    return f"input does not match any value of {key}"
        if path == "/interface/wifi/provisioning":
            names = [merged.get("master-configuration", "")] + merged.get("slave-configurations", "").split(",")
            for n in filter(None, names):
                if not find(dev.t["/interface/wifi/configuration"], n):
                    return "input does not match any value of configuration"
            if not merged.get("master-configuration") and merged.get("action") != "none":
                return "master-configuration required"
        if path == "/interface/vlan" and merged.get("interface") and not find(dev.table("/interface"), merged["interface"]):
            return "input does not match any value of interface"
        if path == "/interface/wifi/datapath" and str(merged.get("vlan-id", "")) not in ("", "none") \
                and not str(merged["vlan-id"]).isdigit():
            return "invalid value for argument vlan-id"
        return None

    def in_use(path: str, rec: dict) -> bool:
        name = rec.get("name")
        if path in WIFI_REFS.values():
            key = next(k for k, v in WIFI_REFS.items() if v == path)
            return any(c.get(key) == name for c in dev.t["/interface/wifi/configuration"])
        if path == "/interface/wifi/configuration":
            return any(name == r.get("master-configuration") or name in r.get("slave-configurations", "").split(",")
                       for r in dev.t["/interface/wifi/provisioning"])
        if path == "/ip/pool":
            return any(s.get("address-pool") == name for s in dev.t.get("/ip/dhcp-server", []))
        return False

    def store(rec: dict, data: dict):
        for k, v in data.items():
            v = norm(v)
            if v == "" and k not in ("passphrase", "authentication-types", "comment"):
                rec.pop(k, None)
            elif k == "vlan-id" and v == "none":
                rec.pop(k, None)
            else:
                rec[k] = v

    async def command(path: str, body: dict):
        menu, _, cmd = path.rpartition("/")
        if path == "/system/package/update/check-for-updates":
            await asyncio.sleep(0.3)
            up = dev.single["/system/package/update"]
            up.update({"latest-version": LATEST, "status": "New version is available" if dev.version != LATEST
                       else "System is already up to date"})
            return [{".section": "0", "status": "finding out latest version..."}, {".section": "1", **up}]
        if path == "/system/package/update/install":
            if dev.single["/system/package/update"].get("latest-version", dev.version) == dev.version:
                return err(400, "System is already up to date")

            def done():
                dev.version = LATEST
                dev.single["/system/package/update"]["installed-version"] = LATEST
                dev.fw_new = LATEST
                for p in dev.t["/system/package"]:
                    p["version"] = LATEST
            dev.reboot(done)
            return []
        if path == "/system/reboot":
            def done():
                if dev.fw_pending:
                    dev.fw_cur, dev.fw_pending = dev.fw_new, False
            dev.reboot(done)
            return []
        if path == "/system/routerboard/upgrade":
            dev.fw_pending = True
            return []
        if path == "/system/identity/set":
            dev.single["/system/identity"]["name"] = body.get("name", "MikroTik")
            return []
        if path == "/execute":
            if not dev.exec_as_string or "as-string" not in body:
                return err(400, "unknown parameter as-string") if "as-string" in body else {"ret": "*1F"}
            return {"ret": dev.export() if "/export" in body.get("script", "") else ""}
        if path == "/export":
            name = body.get("file", "export") + ".rsc"
            dev.files[:] = [f for f in dev.files if f["name"] != name]
            text = dev.export()
            dev.files.append({".id": dev.nid(), "name": name, "type": "script", "size": str(len(text)), "contents": text})
            return []
        if path == "/interface/ethernet/monitor":
            ifs = {i["name"]: i for i in dev.t["/interface"]}
            out = []
            for n in body.get("numbers", "").split(","):
                up = ifs.get(n, {}).get("running") == "true"
                speed = "10Gbps" if n.startswith("sfp") else "1Gbps" if "tv" not in n else "100Mbps"
                out.append({"name": n, "status": "link-ok" if up else "no-link", **({"rate": speed, "full-duplex": "true"} if up else {})})
            return out
        if path == "/interface/ethernet/poe/monitor":
            feeds = {port for child, (parent, port) in dev.world.links.items() if parent == dev.key}
            return [{"name": n, "poe-out": "auto-on",
                     **({"poe-out-status": "powered-on", "poe-out-voltage": "24.0", "poe-out-current": str(280 + 13 * i),
                         "poe-out-power": f"{6.7 + 0.4 * i:.1f}"} if n in feeds else {"poe-out-status": "waiting-for-load"})}
                    for i, n in enumerate(body.get("numbers", "").split(","))]
        if not dev.has_wifi and path.startswith("/interface/wifi"):
            return err(400, "no such command or directory (wifi)")
        if path == "/interface/wifi/monitor":
            ifs = {i["name"]: i for i in dev.wifi_ifaces()}
            reg = dev.reg_table()
            owner_band = {rmac: band for _o, _n, band, rmac, _l in dev.all_radios()}
            out = []
            for i, n in enumerate(body.get("numbers", "").split(",")):
                if n not in ifs:
                    return err(400, f"input does not match any value of numbers")
                band = owner_band.get(ifs[n].get("radio-mac"), "5g")
                ch = ["5180/ax/Ceee", "5500/ax/Ceee", "5260/ax/eCee"][i % 3] if band == "5g" else ["2412/ax", "2437/ax", "2462/ax"][i % 3]
                out.append({"state": "running", "channel": ch, "tx-power": "17" if band == "5g" else "15",
                            "registered-peers": str(sum(1 for r in reg if r["interface"].startswith(n))),
                            "authorized-peers": "0"})
            return out
        if path in ("/interface/wifi/capsman/remote-cap/provision",):
            return []
        if path == "/interface/wifi/radio/provision":
            radio = find(dev.radio_table(), body.get("numbers"))
            if radio and radio.get("local") == "true":
                dev.local_provisioned = bool(dev.t["/interface/wifi/provisioning"])
            return []
        if path == "/ip/dhcp-server/lease/make-static":
            lease = find(dev.leases(), body.get(".id") or body.get("numbers"))
            if not lease:
                return err(400, "no such item")
            dev.static_leases[lease["mac-address"]] = {**lease, ".id": dev.nid(), "dynamic": "false"}
            return []
        if path == "/ip/firewall/filter/move":
            rows = dev.t["/ip/firewall/filter"]
            rec, dest = find(rows, body.get("numbers")), find(rows, body.get("destination"))
            if not rec or not dest:
                return err(400, "no such item")
            rows.remove(rec)
            rows.insert(rows.index(dest), rec)
            return []

        # generic verbs
        if cmd == "print":
            if menu in dev.single:
                return dev.single[menu]
            rows = dev.table(menu)
            return rows if rows is not None else err(400, "no such command or directory")
        if cmd == "set" and menu in dev.single:
            store(dev.single[menu], body)
            return []
        if cmd == "unset":
            rows = dev.t.get(menu)
            rec = find(rows or [], body.get(".id") or body.get("numbers"))
            if not rec:
                return err(400, "no such item")
            rec.pop(body.get("value-name", ""), None)
            return []
        return err(400, f"no such command or directory ({cmd})")

    @app.api_route("/rest/{path:path}", methods=["GET", "PUT", "PATCH", "DELETE", "POST"])
    async def rest(path: str, request: Request):
        if dev.rebooting:
            return Response(status_code=503)
        if request.headers.get("authorization") != expected:
            return err(401, "")
        dev.tick()
        path = "/" + path.strip("/")
        method = request.method
        body = {}
        if method in ("PUT", "PATCH", "POST"):
            try:
                body = await request.json()
            except ValueError:
                body = {}
        if method == "POST":
            result = await command(path, body)
            return result if isinstance(result, Response) else JSONResponse(result)

        if method == "GET":
            if path == "/system/resource":
                return dev.resource()
            if path == "/system/routerboard":
                return {"routerboard": "true", "model": dev.board, "serial-number": f"HG{dev.mac_prefix[-2:]}0A1B2C",
                        "current-firmware": dev.fw_cur, "upgrade-firmware": dev.fw_new, "firmware-type": "ipq6000"}
            if path in dev.single:
                return dev.single[path]
            rows = dev.table(path)
            if rows is not None:
                flt = {k: v for k, v in request.query_params.items() if not k.startswith(".")}
                return [r for r in rows if all(r.get(k) == v for k, v in flt.items())]
            menu, _, ident = path.rpartition("/")
            rows = dev.table(menu)
            if rows is None:
                return err(400, "no such command or directory")
            rec = find(rows, ident)
            return rec if rec else err(404, "")

        if method == "PUT":
            rows = dev.t.get(path)
            if rows is None or (path.startswith("/interface/wifi") and not dev.has_wifi):
                return err(400, "no such command or directory (add)")
            data = {k: norm(v) for k, v in body.items()}
            problem = validate(path, data)
            if problem:
                return err(400, problem)
            rec = {".id": dev.nid(), "dynamic": "false"}
            if path not in ("/interface/wifi/security", "/interface/wifi/datapath", "/interface/wifi/channel",
                            "/interface/wifi/configuration", "/ip/pool"):
                rec["disabled"] = "false"
            store(rec, data)
            rows.append(rec)
            return rec

        menu, _, ident = path.rpartition("/")
        if menu == "/interface/wifi/registration-table" and method == "DELETE":
            reg = find(dev.reg_table(), ident)
            if not reg:
                return err(404, "")
            dev.kicked[reg["mac-address"]] = time.time() + 12
            return Response(status_code=204)
        if menu == "/ip/dhcp-server/lease":
            rec = next((l for l in dev.static_leases.values() if l[".id"] == ident), None)
            if not rec:
                return err(400, "can not change dynamic lease" if method == "PATCH" else "no such item")
            if method == "DELETE":
                dev.static_leases.pop(rec["mac-address"])
                return Response(status_code=204)
            store(rec, body)
            return rec
        rows = dev.files if menu == "/file" else dev.t.get(menu)
        rec = find(rows or [], ident)
        if rec is None:
            return err(404, "")
        if method == "PATCH":
            data = {k: norm(v) for k, v in body.items()}
            problem = validate(menu, data, rec)
            if problem:
                return err(400, problem)
            store(rec, data)
            return rec
        if in_use(menu, rec):
            return err(400, "can not remove - object is in use")
        if menu == "/file":
            dev.files.remove(rec)
        else:
            rows.remove(rec)
        return Response(status_code=204)

    return app


class MockServer:
    """Runs all mock devices in a background thread with its own event loop."""

    def __init__(self):
        self.world = World()
        self.servers: list[uvicorn.Server] = []
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        async def main():
            self.servers = [uvicorn.Server(uvicorn.Config(make_app(d), host="127.0.0.1", port=d.port, log_level="warning",
                                                          access_log=False)) for d in self.world.devs.values()]
            await asyncio.gather(*(s.serve() for s in self.servers))
        self.thread = threading.Thread(target=lambda: asyncio.run(main()), daemon=True, name="mock-routeros")
        self.thread.start()

    def stop(self) -> None:
        for s in self.servers:
            s.should_exit = True


if __name__ == "__main__":
    srv = MockServer()
    srv.start()
    for d in srv.world.devs.values():
        print(f"{d.key:8s} http://127.0.0.1:{d.port}/rest  ({d.board})  user={USER} password={PASSWORD}")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.stop()
