"""Networks: VLAN + gateway address + DHCP server in one go, like a UniFi "network"."""
import ipaddress
import re

from .config import PREFIX, TAG
from .ros import Ros, RosError, truthy

RFC1918 = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
PRIVATE_LIST = f"{PREFIX}private"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:16]


async def list_networks(ros: Ros, wan: str | None = None, leases: list[dict] | None = None) -> list[dict]:
    addrs = await ros.get("/ip/address")
    vlans = {v["name"]: v for v in await ros.get("/interface/vlan")}
    servers = {d.get("interface"): d for d in await ros.get("/ip/dhcp-server")}
    pools = {p["name"]: p for p in await ros.get("/ip/pool")}
    dnets = {n.get("address"): n for n in await ros.get("/ip/dhcp-server/network")}
    out = []
    for a in addrs:
        try:
            ipif = ipaddress.ip_interface(a["address"])
        except ValueError:
            continue
        iface = a.get("interface", "")
        vlan = vlans.get(iface)
        srv = servers.get(iface)
        net = dnets.get(str(ipif.network), {})
        managed = a.get("comment", "").startswith(f"{TAG}net:")
        out.append({
            "name": iface, "label": (vlan or {}).get("comment") if managed else None,
            "slug": a["comment"].split(":", 2)[2] if managed else None,
            "vlan_id": int(vlan["vlan-id"]) if vlan else None, "parent": (vlan or {}).get("interface"),
            "subnet": str(ipif.network), "gateway": str(ipif.ip), "wan": iface == wan or truthy(a.get("dynamic", "false")),
            "disabled": truthy(a.get("disabled", "false")), "managed": managed,
            "dhcp": {"name": srv.get("name"), "pool": (pools.get(srv.get("address-pool", "")) or {}).get("ranges"),
                     "dns": net.get("dns-server"), "disabled": truthy(srv.get("disabled", "false")),
                     "leases": sum(1 for l in leases or [] if l.get("server") == srv.get("name") and l.get("status") == "bound")}
            if srv else None,
        })
    out.sort(key=lambda n: (n["wan"], n["vlan_id"] or 0))
    return out


def validate(data: dict, existing: list[dict]) -> dict:
    name = (data.get("name") or "").strip()
    slug = slugify(name)
    if not slug:
        raise ValueError("Geef het netwerk een naam")
    try:
        vlan_id = int(data.get("vlan_id"))
    except (TypeError, ValueError):
        raise ValueError("VLAN-ID moet een getal zijn")
    if not 2 <= vlan_id <= 4094:
        raise ValueError("VLAN-ID moet tussen 2 en 4094 liggen")
    try:
        net = ipaddress.ip_network(data.get("subnet", ""), strict=False)
    except ValueError:
        raise ValueError("Ongeldig subnet, bijvoorbeeld 192.168.30.0/24")
    if net.version != 4 or net.prefixlen > 29:
        raise ValueError("Gebruik een IPv4-subnet van /29 of groter")
    hosts = list(net.hosts())
    gateway = ipaddress.ip_address(data["gateway"]) if data.get("gateway") else hosts[0]
    if gateway not in net:
        raise ValueError("Gateway valt buiten het subnet")
    start = ipaddress.ip_address(data["dhcp_start"]) if data.get("dhcp_start") else hosts[min(9, len(hosts) - 2)]
    end = ipaddress.ip_address(data["dhcp_end"]) if data.get("dhcp_end") else hosts[-1]
    if start not in net or end not in net or start > end:
        raise ValueError("DHCP-bereik valt buiten het subnet")
    if start <= gateway <= end:
        raise ValueError("De gateway ligt in het DHCP-bereik")
    for n in existing:
        if n["vlan_id"] == vlan_id:
            raise ValueError(f"VLAN {vlan_id} wordt al gebruikt door {n['name']}")
        if n["name"] == PREFIX + slug:
            raise ValueError("Er bestaat al een netwerk met deze naam")
        if ipaddress.ip_network(n["subnet"]).overlaps(net):
            raise ValueError(f"Subnet overlapt met {n['name']} ({n['subnet']})")
    return {"name": name, "slug": slug, "vlan_id": vlan_id, "net": net, "gateway": gateway, "start": start, "end": end,
            "dns": (data.get("dns") or "").strip() or str(gateway),
            "tagged": [p for p in data.get("tagged_ports") or [] if p],
            "interface_list": (data.get("interface_list") or "").strip(), "isolate": bool(data.get("isolate"))}


async def create_network(ros: Ros, bridge: str, data: dict, existing: list[dict]) -> list[str]:
    v = validate(data, existing)
    tag = f"{TAG}net:{v['slug']}"
    iface = PREFIX + v["slug"]
    created: list[tuple[str, str]] = []
    steps: list[str] = []

    async def add(path: str, body: dict, text: str) -> dict:
        rec = await ros.add(path, body)
        created.append((path, rec[".id"]))
        steps.append(text)
        return rec

    try:
        await add("/interface/vlan", {"name": iface, "vlan-id": str(v["vlan_id"]), "interface": bridge, "comment": v["name"]},
                  f"VLAN-interface {iface} (VLAN {v['vlan_id']}) op {bridge}")
        await add("/ip/address", {"address": f"{v['gateway']}/{v['net'].prefixlen}", "interface": iface, "comment": tag},
                  f"Adres {v['gateway']}/{v['net'].prefixlen}")
        await add("/ip/pool", {"name": f"{PREFIX}pool-{v['slug']}", "ranges": f"{v['start']}-{v['end']}", "comment": tag},
                  f"DHCP-pool {v['start']}-{v['end']}")
        await add("/ip/dhcp-server", {"name": f"{PREFIX}dhcp-{v['slug']}", "interface": iface,
                                      "address-pool": f"{PREFIX}pool-{v['slug']}", "disabled": "no", "comment": tag},
                  "DHCP-server")
        await add("/ip/dhcp-server/network", {"address": str(v["net"]), "gateway": str(v["gateway"]),
                                              "dns-server": v["dns"], "comment": tag}, "DHCP-netwerk")

        # Bridge VLAN table: the bridge itself (CPU port) plus the chosen trunk ports.
        bvlans = await ros.get("/interface/bridge/vlan")
        if any(str(v["vlan_id"]) in str(b.get("vlan-ids", "")).split(",") and b.get("bridge") == bridge
               and not truthy(b.get("dynamic", "false")) for b in bvlans):
            steps.append(f"Bridge-VLAN {v['vlan_id']} bestond al: niet aangepast")
        else:
            await add("/interface/bridge/vlan", {"bridge": bridge, "vlan-ids": str(v["vlan_id"]),
                                                 "tagged": ",".join([bridge] + v["tagged"]), "comment": tag},
                      f"Bridge-VLAN {v['vlan_id']} tagged op {', '.join([bridge] + v['tagged'])}")

        if v["interface_list"]:
            await add("/interface/list/member", {"list": v["interface_list"], "interface": iface, "comment": tag},
                      f"Toegevoegd aan interface-lijst {v['interface_list']}")

        if v["isolate"]:
            have = {a.get("address") for a in await ros.get("/ip/firewall/address-list") if a.get("list") == PRIVATE_LIST}
            for cidr in RFC1918:
                if cidr not in have:
                    await ros.add("/ip/firewall/address-list", {"list": PRIVATE_LIST, "address": cidr, "comment": f"{TAG}rfc1918"})
            rule = await add("/ip/firewall/filter", {
                "chain": "forward", "action": "drop", "in-interface": iface, "dst-address-list": PRIVATE_LIST,
                "comment": f"{tag} isolatie: geen toegang tot lokale netwerken"}, "Firewall: verkeer naar lokale netwerken geblokkeerd")
            # Put the drop right after the established/related accept so replies keep working.
            fw = [r for r in await ros.get("/ip/firewall/filter") if r.get("chain") == "forward"]
            anchor = next((i for i, r in enumerate(fw) if r.get("action") == "accept"
                           and "established" in r.get("connection-state", "")), None)
            if anchor is not None and anchor + 1 < len(fw) and fw[anchor + 1][".id"] != rule[".id"]:
                await ros.cmd("/ip/firewall/filter/move", {"numbers": rule[".id"], "destination": fw[anchor + 1][".id"]})
    except RosError as e:
        # Roll back in reverse so a failed step leaves nothing behind.
        for path, ident in reversed(created):
            try:
                await ros.remove(path, ident)
            except RosError:
                pass
        raise RosError(f"{e} (alle stappen zijn teruggedraaid)", e.status)
    return steps


async def delete_network(ros: Ros, slug: str) -> int:
    tag = f"{TAG}net:{slug}"
    removed = 0
    for path in ("/ip/firewall/filter", "/interface/list/member", "/interface/bridge/vlan", "/ip/dhcp-server/network",
                 "/ip/dhcp-server", "/ip/pool", "/ip/address"):
        for rec in await ros.get(path):
            if rec.get("comment", "").split(" ")[0] == tag:
                await ros.remove(path, rec[".id"])
                removed += 1
    for rec in await ros.get("/interface/vlan"):
        if rec.get("name") == PREFIX + slug:
            await ros.remove("/interface/vlan", rec[".id"])
            removed += 1
    return removed
