"""MikroManager API + static frontend."""
import asyncio
import json
import re
import time
from contextlib import asynccontextmanager

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import clients as clients_mod
from . import db, interfaces, live, maint, networks, poller, safe, security, wifi
from .config import DEFAULT_SITE_SETTINGS, DEMO, SECURE_COOKIE, STATIC_DIR, VERSION
from .poller import STATE, snap
from .ros import Ros, RosError, close_all, truthy

COOKIE = "tc_session"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if DEMO:
        from . import demo
        demo.reset_data()
    db.init()
    security.init()
    tasks = []
    if DEMO:
        tasks += await demo.start()
    tasks.append(asyncio.create_task(poller.run()))
    tasks.append(asyncio.create_task(live.run()))
    yield
    for t in tasks:
        t.cancel()
    await close_all()


app = FastAPI(title="MikroManager", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None)


@app.exception_handler(RosError)
async def ros_error(_: Request, e: RosError):
    return JSONResponse({"detail": str(e)}, status_code=502 if e.unreachable else 400)


@app.exception_handler(ValueError)
async def value_error(_: Request, e: ValueError):
    return JSONResponse({"detail": str(e)}, status_code=400)


def user(request: Request) -> dict:
    u = security.session_user(request.cookies.get(COOKIE))
    if not u:
        raise HTTPException(401, "Niet ingelogd")
    return u


def _site(site_id: int) -> dict:
    site = db.get_site(site_id)
    if not site:
        raise HTTPException(404, "Site niet gevonden")
    return site


def _device(dev_id: int) -> dict:
    dev = db.q1("SELECT * FROM devices WHERE id=?", dev_id)
    if not dev:
        raise HTTPException(404, "Apparaat niet gevonden")
    return dev


def _controller(site_id: int) -> dict:
    ctrl = db.controller(site_id)
    if not ctrl:
        raise ValueError("Deze site heeft nog geen router/controller. Voeg eerst je router toe.")
    return ctrl


# ---- auth ------------------------------------------------------------------

def _set_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(COOKIE, token, max_age=security.SESSION_TTL, httponly=True, samesite="lax", secure=SECURE_COOKIE)


@app.get("/api/state")
def state(request: Request):
    u = security.session_user(request.cookies.get(COOKIE))
    return {"version": VERSION, "demo": DEMO, "setup_needed": db.q1("SELECT 1 FROM users") is None,
            "user": u["username"] if u else None}


@app.post("/api/setup")
def setup(resp: Response, body: dict = Body(...)):
    if db.q1("SELECT 1 FROM users"):
        raise HTTPException(400, "Er bestaat al een beheerder")
    if len(body.get("password", "")) < 8 or not body.get("username"):
        raise ValueError("Kies een gebruikersnaam en een wachtwoord van minstens 8 tekens")
    uid = security.create_user(body["username"].strip(), body["password"])
    _set_cookie(resp, security.new_session(uid))
    return {"ok": True}


_fails: dict[str, list[float]] = {}


@app.post("/api/login")
def login(request: Request, resp: Response, body: dict = Body(...)):
    ip = request.client.host if request.client else "?"
    recent = [t for t in _fails.get(ip, []) if t > time.time() - 300]
    if len(recent) >= 8:
        raise HTTPException(429, "Te veel pogingen, probeer het over een paar minuten opnieuw")
    u = security.check_login(body.get("username", ""), body.get("password", ""))
    if not u:
        _fails[ip] = recent + [time.time()]
        raise HTTPException(401, "Onjuiste gebruikersnaam of wachtwoord")
    _fails.pop(ip, None)
    _set_cookie(resp, security.new_session(u["id"]))
    return {"ok": True}


@app.post("/api/logout")
def logout(request: Request, resp: Response):
    security.end_session(request.cookies.get(COOKIE))
    resp.delete_cookie(COOKIE)
    return {"ok": True}


@app.post("/api/password")
def password(body: dict = Body(...), u: dict = Depends(user)):
    if not security.check_login(u["username"], body.get("current", "")):
        raise ValueError("Huidig wachtwoord klopt niet")
    if len(body.get("new", "")) < 8:
        raise ValueError("Nieuw wachtwoord moet minstens 8 tekens zijn")
    security.set_password(u["id"], body["new"])
    return {"ok": True}


# ---- sites -----------------------------------------------------------------

def _site_summary(site: dict) -> dict:
    devs = db.site_devices(site["id"])
    online = sum(1 for d in devs if (STATE.get(d["id"]) or {}).get("online"))
    return {"id": site["id"], "name": site["name"], "settings": db.site_settings(site),
            "devices": len(devs), "online": online}


@app.get("/api/sites")
def sites(_: dict = Depends(user)):
    return [_site_summary(s) for s in db.q("SELECT * FROM sites ORDER BY name")]


@app.post("/api/sites")
def site_create(body: dict = Body(...), _: dict = Depends(user)):
    name = (body.get("name") or "").strip()
    if not name:
        raise ValueError("Geef de site een naam")
    sid = db.x("INSERT INTO sites (name, settings) VALUES (?,?)", name, json.dumps(body.get("settings") or {}))
    db.log(sid, f"Site '{name}' aangemaakt")
    return _site_summary(db.q1("SELECT * FROM sites WHERE id=?", sid))


@app.patch("/api/sites/{site_id}")
def site_update(site_id: int, body: dict = Body(...), _: dict = Depends(user)):
    site = _site(site_id)
    if "name" in body and body["name"].strip():
        db.x("UPDATE sites SET name=? WHERE id=?", body["name"].strip(), site_id)
    if "settings" in body:
        st = site["settings"]
        st.update({k: v for k, v in body["settings"].items() if k in DEFAULT_SITE_SETTINGS})
        st["backup_hour"] = max(0, min(23, int(st["backup_hour"])))
        st["backup_keep"] = max(1, min(365, int(st["backup_keep"])))
        db.x("UPDATE sites SET settings=? WHERE id=?", json.dumps(st), site_id)
    if "controller_id" in body:
        db.x("UPDATE devices SET is_controller = (id = ?) WHERE site_id=?", int(body["controller_id"]), site_id)
    return _site_summary(db.q1("SELECT * FROM sites WHERE id=?", site_id))


@app.delete("/api/sites/{site_id}")
def site_delete(site_id: int, _: dict = Depends(user)):
    _site(site_id)
    db.x("DELETE FROM sites WHERE id=?", site_id)
    return {"ok": True}


# ---- devices ---------------------------------------------------------------

def _ports(s: dict) -> list[dict]:
    eth = {e["name"]: e for e in s.get("ethernet") or []}
    mon, poe, rates = s.get("eth_mon") or {}, s.get("poe_mon") or {}, s.get("rates") or {}
    bridge_of = {p.get("interface"): p for p in s.get("bridge_ports") or []}
    out = []
    for i in s.get("interfaces") or []:
        if i.get("type") != "ether":
            continue
        name = i["name"]
        m, p, bp = mon.get(name, {}), poe.get(name), bridge_of.get(name, {})
        rate = rates.get(name, (0, 0))
        out.append({"name": name, "comment": i.get("comment"), "running": truthy(i.get("running", "false")),
                    "disabled": truthy(i.get("disabled", "false")), "speed": m.get("rate") if m.get("status") == "link-ok" else None,
                    "sfp": name.startswith("sfp"), "bridge": bp.get("bridge"), "pvid": bp.get("pvid"),
                    "wan": name == s.get("wan"), "rx_bps": rate[0], "tx_bps": rate[1],
                    "poe": {"status": p.get("poe-out-status"), "power": p.get("poe-out-power")} if p else None,
                    "mac": i.get("mac-address"), "default_name": eth.get(name, {}).get("default-name")})
    return out


def _device_view(dev: dict, detail: bool = False, counts: dict[int, int] | None = None) -> dict:
    if counts is None:
        counts = clients_mod.clients_per_ap(clients_mod.site_clients(dev["site_id"]))
    s = STATE.get(dev["id"]) or {}
    res = s.get("resource") or {}
    total, free = float(res.get("total-memory", 0) or 0), float(res.get("free-memory", 0) or 0)
    health = {h.get("name"): h.get("value") for h in s.get("health") or [] if isinstance(h, dict)}
    info = maint.update_info(dev)
    out = {
        "id": dev["id"], "site_id": dev["site_id"], "name": dev["name"], "host": dev["host"], "port": dev["port"],
        "scheme": dev["scheme"], "verify_tls": bool(dev["verify_tls"]), "username": dev["username"], "role": dev["role"],
        "is_controller": bool(dev["is_controller"]), "online": s.get("online"), "error": s.get("error"),
        "last_seen": s.get("last_seen"), "identity": s.get("identity"), "board": res.get("board-name"),
        "arch": res.get("architecture-name"), "version": res.get("version", "").split(" ")[0] or None,
        "uptime": poller.uptime_seconds(res.get("uptime")), "cpu": float(res.get("cpu-load", 0) or 0) if res else None,
        "mem": round(100 * (1 - free / total), 1) if total else None,
        "temperature": health.get("temperature") or health.get("cpu-temperature") or health.get("board-temperature1"),
        "voltage": health.get("voltage"), "clients": counts.get(dev["id"], 0),
        "update_available": info["available"], "firmware_pending": info["firmware_pending"], "busy": s.get("busy"),
        "serial": (s.get("routerboard") or {}).get("serial-number"), "model": (s.get("routerboard") or {}).get("model"),
    }
    if detail:
        poe = [p for p in (s.get("poe_mon") or {}).values() if p.get("poe-out-power")]
        out.update(ports=_ports(s), history=poller.history(dev["id"]), wan=s.get("wan"),
                   poe_total=round(sum(float(p["poe-out-power"]) for p in poe), 1) if poe else None,
                   update=info, cap_enabled=truthy((s.get("wifi_cap") or {}).get("enabled", "false")),
                   has_wifi=bool(s.get("wifi_ifaces")), bridges=[b["name"] for b in s.get("bridges") or []],
                   packages=[p.get("name") for p in s.get("packages") or []])
    return out


async def _probe(body: dict) -> tuple[Ros, dict, str]:
    host = (body.get("host") or "").strip()
    if not host or not body.get("username"):
        raise ValueError("Adres en gebruikersnaam zijn verplicht")
    scheme = body.get("scheme") or "https"
    port = int(body.get("port") or (443 if scheme == "https" else 80))
    ros = Ros(host, port, scheme, body["username"], body.get("password") or "", bool(body.get("verify_tls")))
    res = await ros.get("/system/resource")
    ident = (await ros.get("/system/identity")).get("name", host)
    if not str(res.get("version", "")).startswith("7"):
        raise ValueError(f"RouterOS {res.get('version')} wordt niet ondersteund (v7 met REST API nodig)")
    return ros, res, ident


@app.post("/api/devices/test")
async def device_test(body: dict = Body(...), _: dict = Depends(user)):
    _, res, ident = await _probe(body)
    return {"identity": ident, "board": res.get("board-name"), "version": res.get("version")}


@app.get("/api/sites/{site_id}/devices")
def devices(site_id: int, _: dict = Depends(user)):
    counts = clients_mod.clients_per_ap(clients_mod.site_clients(site_id))
    return [_device_view(d, counts=counts) for d in db.site_devices(site_id)]


@app.post("/api/sites/{site_id}/devices")
async def device_add(site_id: int, body: dict = Body(...), _: dict = Depends(user)):
    _site(site_id)
    ros, res, ident = await _probe(body)
    role = body.get("role") if body.get("role") in ("router", "switch", "ap") else "router"
    first_router = role == "router" and not db.q1("SELECT 1 FROM devices WHERE site_id=? AND is_controller=1", site_id)
    did = db.x(
        "INSERT INTO devices (site_id, name, host, port, scheme, verify_tls, username, password_enc, role, is_controller, created) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)", site_id, (body.get("name") or ident).strip(), body["host"].strip(),
        int(body.get("port") or (443 if (body.get("scheme") or "https") == "https" else 80)), body.get("scheme") or "https",
        int(bool(body.get("verify_tls"))), body["username"], security.encrypt(body.get("password") or ""), role,
        int(first_router), time.time())
    dev = _device(did)
    db.log(site_id, f"{dev['name']} toegevoegd ({res.get('board-name')}, RouterOS {str(res.get('version', '')).split(' ')[0]})", "ok")
    await poller.refresh_device(dev)
    return _device_view(dev)


@app.get("/api/devices/{dev_id}")
def device_get(dev_id: int, _: dict = Depends(user)):
    return _device_view(_device(dev_id), detail=True)


@app.patch("/api/devices/{dev_id}")
async def device_update(dev_id: int, body: dict = Body(...), _: dict = Depends(user)):
    dev = _device(dev_id)
    conn = {k: body.get(k, dev[k]) for k in ("host", "port", "scheme", "username", "verify_tls")}
    conn_changed = any(str(conn[k]) != str(dev[k]) for k in conn) or body.get("password")
    if conn_changed:
        await _probe({**conn, "password": body.get("password") or security.decrypt(dev["password_enc"])})
    db.x("UPDATE devices SET name=?, host=?, port=?, scheme=?, username=?, verify_tls=?, role=?, password_enc=? WHERE id=?",
         (body.get("name") or dev["name"]).strip(), str(conn["host"]).strip(), int(conn["port"]), conn["scheme"],
         conn["username"], int(bool(conn["verify_tls"])),
         body.get("role") if body.get("role") in ("router", "switch", "ap") else dev["role"],
         security.encrypt(body["password"]) if body.get("password") else dev["password_enc"], dev_id)
    if body.get("identity"):
        await Ros.for_device(_device(dev_id)).cmd("/system/identity/set", {"name": body["identity"]})
    await poller.refresh_device(_device(dev_id))
    return _device_view(_device(dev_id), detail=True)


@app.delete("/api/devices/{dev_id}")
def device_delete(dev_id: int, _: dict = Depends(user)):
    dev = _device(dev_id)
    for b in db.q("SELECT * FROM backups WHERE device_id=?", dev_id):
        maint.delete_backup(b)
    db.x("DELETE FROM devices WHERE id=?", dev_id)
    db.x("DELETE FROM metrics WHERE device_id=?", dev_id)
    STATE.pop(dev_id, None)
    db.log(dev["site_id"], f"{dev['name']} verwijderd uit MikroManager (configuratie op het apparaat is niet aangepast)")
    return {"ok": True}


@app.post("/api/devices/{dev_id}/reboot")
async def device_reboot(dev_id: int, _: dict = Depends(user)):
    await maint.reboot(_device(dev_id))
    return {"ok": True}


@app.post("/api/devices/{dev_id}/ports/{name}")
async def port_set(dev_id: int, name: str, body: dict = Body(...), _: dict = Depends(user)):
    dev = _device(dev_id)
    data = {}
    if "disabled" in body:
        data["disabled"] = "yes" if body["disabled"] else "no"
    if "comment" in body:
        data["comment"] = body["comment"]
    if data:
        await Ros.for_device(dev).set("/interface", name, data)
        db.log(dev["site_id"], f"{dev['name']}: poort {name} aangepast")
        await poller.refresh_device(dev)
    return _device_view(dev, detail=True)


# ---- interfaces -------------------------------------------------------------

@app.get("/api/devices/{dev_id}/interfaces")
async def interfaces_list(dev_id: int, _: dict = Depends(user)):
    dev = _device(dev_id)
    return interfaces.view(dev, await interfaces.fetch(dev))


async def _guarded(dev: dict, ops: list, what: str) -> JSONResponse:
    result = await safe.apply(dev, ops, what)
    await poller.refresh_device(dev)
    view = interfaces.view(dev, await interfaces.fetch(dev)) if result["applied"] else None
    return JSONResponse({**result, "view": view}, status_code=200 if result["applied"] else 202)


@app.post("/api/devices/{dev_id}/interfaces/{name}")
async def interface_set(dev_id: int, name: str, body: dict = Body(...), _: dict = Depends(user)):
    dev = _device(dev_id)
    ops = interfaces.plan_port(await interfaces.fetch(dev), name, body)
    return await _guarded(dev, ops, f"interface {name} aangepast")


@app.post("/api/devices/{dev_id}/vlans")
async def vlan_add(dev_id: int, body: dict = Body(...), _: dict = Depends(user)):
    dev = _device(dev_id)
    ops = interfaces.plan_vlan(await interfaces.fetch(dev), body)
    return await _guarded(dev, ops, f"VLAN-interface {body.get('name')} toegevoegd")


@app.patch("/api/devices/{dev_id}/vlans/{name}")
async def vlan_set(dev_id: int, name: str, body: dict = Body(...), _: dict = Depends(user)):
    dev = _device(dev_id)
    ops = interfaces.plan_vlan(await interfaces.fetch(dev), body, current=name)
    return await _guarded(dev, ops, f"VLAN-interface {name} aangepast")


@app.delete("/api/devices/{dev_id}/vlans/{name}")
async def vlan_delete(dev_id: int, name: str, _: dict = Depends(user)):
    dev = _device(dev_id)
    ops = interfaces.plan_vlan(await interfaces.fetch(dev), {"delete": True}, current=name)
    return await _guarded(dev, ops, f"VLAN-interface {name} verwijderd")


# ---- live -------------------------------------------------------------------

@app.get("/api/sites/{site_id}/live")
def site_live(site_id: int, since: float = 0, _: dict = Depends(user)):
    """Fast-moving numbers for the overview: WAN traffic, internet latency, CPU per device."""
    _site(site_id)
    devs = db.site_devices(site_id)
    live.watch([d["id"] for d in devs])
    ctrl = db.controller(site_id)
    cs = (STATE.get(ctrl["id"]) or {}) if ctrl else {}
    wan = cs.get("wan")
    traffic = [{"ts": p["ts"], "rx": p["rates"].get(wan, (None, None))[0], "tx": p["rates"].get(wan, (None, None))[1]}
               for p in live.samples(ctrl["id"], since)] if ctrl and wan else []
    latency = live.pings(ctrl["id"], since) if ctrl else []
    if ctrl and not since:
        # first request: fill the window with the stored 15-second measurements so the chart is not empty
        first = traffic[0]["ts"] if traffic else time.time()
        hist = poller.history(ctrl["id"], live.LIVE_WINDOW / 3600, points=live.LIVE_WINDOW // 15)
        traffic = [{"ts": h["ts"], "rx": h["rx"], "tx": h["tx"]} for h in hist if h["ts"] < first - 1] + traffic
        first = latency[0]["ts"] if latency else time.time()
        wh = poller.wan_history(ctrl["id"], live.LIVE_WINDOW / 3600, points=live.LIVE_WINDOW // 15)
        latency = [{"ts": h["ts"], "rtt": h["rtt"], "loss": h["loss"]} for h in wh
                   if h["kind"] == "internet" and h["wan"] == wan and h["ts"] < first - 1] + latency
    return {"now": time.time(), "interval": live.LIVE_INTERVAL, "window": live.LIVE_WINDOW, "wan": wan,
            "traffic": traffic, "latency": latency,
            "cpu": {d["id"]: (live.samples(d["id"])[-1]["cpu"] if live.samples(d["id"]) else None) for d in devs}}


@app.get("/api/devices/{dev_id}/live")
def device_live(dev_id: int, since: float = 0, _: dict = Depends(user)):
    """CPU/memory series and current rate of every interface, for the device page."""
    dev = _device(dev_id)
    live.watch([dev_id])
    pts = live.samples(dev_id, since)
    last = live.samples(dev_id)[-1] if live.samples(dev_id) else None
    load = [{"ts": p["ts"], "cpu": p["cpu"], "mem": p["mem"]} for p in pts]
    if not since:
        first = load[0]["ts"] if load else time.time()
        load = [{"ts": h["ts"], "cpu": h["cpu"], "mem": h["mem"]}
                for h in poller.history(dev_id, live.LIVE_WINDOW / 3600, points=live.LIVE_WINDOW // 15)
                if h["ts"] < first - 1] + load
    return {"now": time.time(), "interval": live.LIVE_INTERVAL, "window": live.LIVE_WINDOW,
            "load": load,
            "rates": {k: {"rx": v[0], "tx": v[1]} for k, v in (last or {}).get("rates", {}).items()}}


# ---- overview --------------------------------------------------------------

@app.get("/api/sites/{site_id}/overview")
def overview(site_id: int, hours: float = 6, _: dict = Depends(user)):
    site = _site(site_id)
    devs = db.site_devices(site_id)
    cl = clients_mod.site_clients(site_id)
    counts = clients_mod.clients_per_ap(cl)
    views = [{**_device_view(d, counts=counts), "ports": _ports(STATE.get(d["id"]) or {})} for d in devs]
    ctrl = db.controller(site_id)
    cs = (STATE.get(ctrl["id"]) or {}) if ctrl else {}
    wan_rate = (cs.get("rates") or {}).get(cs.get("wan") or "", (None, None))
    ssids: dict[str, int] = {}
    for c in cl:
        if c["wifi"] and c["wifi"]["ssid"]:
            ssids[c["wifi"]["ssid"]] = ssids.get(c["wifi"]["ssid"], 0) + 1
    return {
        "site": {"id": site["id"], "name": site["name"]},
        "devices": {"total": len(views), "online": sum(1 for v in views if v["online"]),
                    "offline": [v["name"] for v in views if v["online"] is False]},
        "clients": {"online": sum(1 for c in cl if c["online"]), "wifi": sum(1 for c in cl if c["online"] and c["type"] == "wifi"),
                    "wired": sum(1 for c in cl if c["online"] and c["type"] == "wired"), "known": len(cl)},
        "updates": sum(1 for v in views if v["update_available"]),
        "wan": {"interface": cs.get("wan"), "rx_bps": wan_rate[0], "tx_bps": wan_rate[1],
                "history": poller.history(ctrl["id"], hours) if ctrl else []},
        "wan_quality": {"target": poller.WAN_PING_TARGET,
                        "wans": [{**w, "ping": (cs.get("wan_quality") or {}).get(w["interface"]) or {}} for w in poller.wan_routes(cs)],
                        "history": poller.wan_history(ctrl["id"], hours) if ctrl else []},
        "ssids": sorted(ssids.items(), key=lambda kv: -kv[1]),
        "top_clients": [{"mac": c["mac"], "display": c["display"], "rx": c["rx"], "tx": c["tx"], "ssid": c["wifi"]["ssid"]}
                        for c in sorted((c for c in cl if c["wifi"]), key=lambda c: -(c["rx"] + c["tx"]))[:5]],
        "device_list": views,
        "activity": db.q("SELECT ts, level, message FROM activity WHERE site_id=? OR site_id IS NULL ORDER BY id DESC LIMIT 12", site_id),
    }


@app.get("/api/sites/{site_id}/activity")
def activity(site_id: int, limit: int = 200, _: dict = Depends(user)):
    return db.q("SELECT ts, level, message FROM activity WHERE site_id=? OR site_id IS NULL ORDER BY id DESC LIMIT ?",
                site_id, min(limit, 1000))


# ---- clients ---------------------------------------------------------------

@app.get("/api/sites/{site_id}/clients")
def clients(site_id: int, _: dict = Depends(user)):
    return clients_mod.site_clients(site_id)


def _client(site_id: int, mac: str) -> dict:
    c = next((c for c in clients_mod.site_clients(site_id) if c["mac"] == mac.upper()), None)
    if not c:
        raise HTTPException(404, "Client niet gevonden")
    return c


@app.post("/api/sites/{site_id}/clients/{mac}/name")
def client_name(site_id: int, mac: str, body: dict = Body(...), _: dict = Depends(user)):
    name = (body.get("name") or "").strip()
    if name:
        db.x("INSERT INTO client_names (site_id, mac, name) VALUES (?,?,?) ON CONFLICT(site_id, mac) DO UPDATE SET name=excluded.name",
             site_id, mac.upper(), name)
    else:
        db.x("DELETE FROM client_names WHERE site_id=? AND mac=?", site_id, mac.upper())
    return {"ok": True}


@app.post("/api/sites/{site_id}/clients/{mac}/static")
async def client_static(site_id: int, mac: str, body: dict = Body(default={}), _: dict = Depends(user)):
    c = _client(site_id, mac)
    if not c["lease_id"]:
        raise ValueError("Deze client heeft geen DHCP-lease op een beheerde router")
    dev = _device(c["lease_device"])
    ros = Ros.for_device(dev)
    if not c["static"]:
        await ros.cmd("/ip/dhcp-server/lease/make-static", {".id": c["lease_id"]})
    patch = {}
    if body.get("address"):
        patch["address"] = body["address"]
    if c["name"] or c["hostname"]:
        patch["comment"] = c["name"] or c["hostname"]
    if patch:
        await ros.set("/ip/dhcp-server/lease", c["lease_id"], patch)
    db.log(site_id, f"Vast IP-adres voor {c['display']}: {body.get('address') or c['ip']}")
    await poller.refresh_device(dev)
    return {"ok": True}


@app.post("/api/sites/{site_id}/clients/{mac}/kick")
async def client_kick(site_id: int, mac: str, _: dict = Depends(user)):
    c = _client(site_id, mac)
    if not c["wifi"]:
        raise ValueError("Client is niet via wifi verbonden")
    dev = _device(c["wifi"]["device_id"])
    await Ros.for_device(dev).remove("/interface/wifi/registration-table", c["wifi"]["reg_id"])
    db.log(site_id, f"{c['display']} gedisconnect van de wifi")
    return {"ok": True}


@app.post("/api/sites/{site_id}/clients/{mac}/block")
async def client_block(site_id: int, mac: str, body: dict = Body(default={}), _: dict = Depends(user)):
    c = _client(site_id, mac)
    ctrl = _controller(site_id)
    ros = Ros.for_device(ctrl)
    if body.get("blocked", True):
        if not c["blocked"]:
            await ros.add("/interface/wifi/access-list", {"mac-address": c["mac"], "action": "reject",
                                                          "comment": f"{clients_mod.BLOCK_COMMENT} {c['display']}"})
        if c["wifi"]:
            try:
                await Ros.for_device(_device(c["wifi"]["device_id"])).remove("/interface/wifi/registration-table", c["wifi"]["reg_id"])
            except RosError:
                pass
        db.log(site_id, f"{c['display']} geblokkeerd op wifi", "warn")
    elif c["blocked"]:
        await ros.remove("/interface/wifi/access-list", c["block_id"])
        db.log(site_id, f"Blokkade van {c['display']} opgeheven")
    await poller.refresh_device(ctrl)
    return {"ok": True}


_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _router(site_id: int) -> dict:
    """The router that runs DHCP/kid-control for this site (the controller, else the first router)."""
    dev = db.controller(site_id)
    if not dev:
        raise ValueError("Deze site heeft nog geen router. Voeg eerst je router toe.")
    return dev


async def _kid_assign(site_id: int, c: dict, kid: str | None) -> None:
    """Put the client under one MikroManager kid-control profile (or none)."""
    dev = _router(site_id)
    ros = Ros.for_device(dev)
    if kid and not await ros.get("/ip/kid-control", name=kid):
        sched = clients_mod.parse_schedule_kid(kid)
        days = {d: f"{sched['from']}-{sched['to']}" for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")} if sched else {}
        await ros.add("/ip/kid-control", {"name": kid, **days,
                                          "comment": "MikroManager: pauze" if not sched else "MikroManager: tijdschema"})
        if kid == clients_mod.PAUSE_KID:
            await ros.cmd("/ip/kid-control/pause", {"numbers": kid})
    if c.get("kid_device_id"):
        await ros.remove("/ip/kid-control/device", c["kid_device_id"])
    if kid:
        await ros.add("/ip/kid-control/device", {"name": f"mm-{c['mac'].replace(':', '').lower()}",
                                                 "mac-address": c["mac"], "user": kid})
    await poller.refresh_device(dev)


@app.post("/api/sites/{site_id}/clients/{mac}/pause")
async def client_pause(site_id: int, mac: str, body: dict = Body(default={}), _: dict = Depends(user)):
    c = _client(site_id, mac)
    if body.get("paused", True):
        await _kid_assign(site_id, c, clients_mod.PAUSE_KID)
        db.log(site_id, f"Internet gepauzeerd voor {c['display']}", "warn")
    else:
        sched = db.q1("SELECT start, stop FROM client_schedules WHERE site_id=? AND mac=?", site_id, c["mac"])
        await _kid_assign(site_id, c, clients_mod.schedule_kid(sched["start"], sched["stop"]) if sched else None)
        db.log(site_id, f"Internet hervat voor {c['display']}")
    return {"ok": True}


@app.post("/api/sites/{site_id}/clients/{mac}/schedule")
async def client_schedule(site_id: int, mac: str, body: dict = Body(default={}), _: dict = Depends(user)):
    c = _client(site_id, mac)
    start, stop = body.get("from"), body.get("to")
    if start or stop:
        if not (_HHMM.match(start or "") and _HHMM.match(stop or "")) or start >= stop:
            raise ValueError("Kies een begin- en eindtijd (uu:mm) op dezelfde dag, begin vóór eind")
        db.x("INSERT INTO client_schedules (site_id, mac, start, stop) VALUES (?,?,?,?) "
             "ON CONFLICT(site_id, mac) DO UPDATE SET start=excluded.start, stop=excluded.stop", site_id, c["mac"], start, stop)
        if not c["paused"]:
            await _kid_assign(site_id, c, clients_mod.schedule_kid(start, stop))
        db.log(site_id, f"Tijdschema voor {c['display']}: internet van {start} tot {stop}")
    else:
        db.x("DELETE FROM client_schedules WHERE site_id=? AND mac=?", site_id, c["mac"])
        if not c["paused"]:
            await _kid_assign(site_id, c, None)
        db.log(site_id, f"Tijdschema voor {c['display']} verwijderd")
    return {"ok": True}


@app.post("/api/sites/{site_id}/clients/{mac}/wol")
async def client_wol(site_id: int, mac: str, _: dict = Depends(user)):
    c = _client(site_id, mac)
    dev = _device(c["lease_device"]) if c["lease_device"] else _router(site_id)
    s = STATE.get(dev["id"]) or {}
    iface = next((a.get("interface") for a in s.get("arp") or [] if (a.get("mac-address") or "").upper() == c["mac"]), None)
    iface = iface or _site(site_id)["settings"].get("bridge") or "bridge"
    await Ros.for_device(dev).cmd("/tool/wol", {"mac": c["mac"], "interface": iface})
    db.log(site_id, f"Wake-on-LAN verstuurd naar {c['display']} via {iface}")
    return {"ok": True, "interface": iface}


# ---- wifi ------------------------------------------------------------------

def _wlan_view(w: dict) -> dict:
    return {"id": w["id"], "ssid": w["ssid"], "slug": w["slug"], "security": w["security"], "vlan_id": w["vlan_id"],
            "bands": w["bands"].split(","), "hidden": bool(w["hidden"]), "isolation": bool(w["isolation"]),
            "ft": bool(w["ft"]), "enabled": bool(w["enabled"]), "passphrase": security.decrypt(w["passphrase_enc"])}


def _wlan_fields(body: dict, site_id: int, current: dict | None = None) -> dict:
    cur = _wlan_view(current) if current else {}
    ssid = (body.get("ssid", cur.get("ssid")) or "").strip()
    sec = body.get("security", cur.get("security", "wpa2wpa3"))
    pw = body.get("passphrase", cur.get("passphrase", ""))
    bands = [b for b in body.get("bands", cur.get("bands", ["2g", "5g"])) if b in ("2g", "5g")]
    vlan = body.get("vlan_id", cur.get("vlan_id"))
    if not 1 <= len(ssid.encode()) <= 32:
        raise ValueError("SSID moet 1 tot 32 tekens zijn")
    if sec not in wifi.AUTH:
        raise ValueError("Onbekend beveiligingstype")
    if sec != "open" and not 8 <= len(pw) <= 63:
        raise ValueError("Wachtwoord moet 8 tot 63 tekens zijn")
    if not bands:
        raise ValueError("Kies minstens één band")
    if vlan in ("", None):
        vlan = None
    elif not 1 <= int(vlan) <= 4094:
        raise ValueError("VLAN-ID moet tussen 1 en 4094 liggen")
    return {"ssid": ssid, "security": sec, "passphrase_enc": security.encrypt(pw if sec != "open" else ""),
            "vlan_id": int(vlan) if vlan else None, "bands": ",".join(bands),
            "hidden": int(bool(body.get("hidden", cur.get("hidden", False)))),
            "isolation": int(bool(body.get("isolation", cur.get("isolation", False)))),
            "ft": int(bool(body.get("ft", cur.get("ft", True)))),
            "enabled": int(bool(body.get("enabled", cur.get("enabled", True))))}


async def _pending(site: dict) -> dict:
    ctrl = db.controller(site["id"])
    if not ctrl:
        return {"count": None, "error": "Geen controller"}
    try:
        plan = await wifi.build_plan(Ros.for_device(ctrl), site["settings"], wifi.site_wlans(site["id"]),
                                     wifi.tx_radios(site["id"]))
        return {"count": len(plan), "error": None}
    except RosError as e:
        return {"count": None, "error": str(e)}


@app.get("/api/sites/{site_id}/wifi")
async def wifi_get(site_id: int, _: dict = Depends(user)):
    site = _site(site_id)
    ctrl = db.controller(site_id)
    cs = (STATE.get(ctrl["id"]) or {}) if ctrl else {}
    return {"wlans": [_wlan_view(w) for w in wifi.site_wlans(site_id)], "settings": site["settings"],
            "aps": wifi.access_points(site_id), "pending": await _pending(site),
            "controller": {"id": ctrl["id"], "name": ctrl["name"], "online": cs.get("online"),
                           "has_wifi_menu": cs.get("wifi_ifaces") is not None,
                           "bridges": [b["name"] for b in cs.get("bridges") or []]} if ctrl else None}


@app.post("/api/sites/{site_id}/wifi/radios/{mac}")
def wifi_radio_tx(site_id: int, mac: str, body: dict = Body(...), _: dict = Depends(user)):
    """Transmit power of one radio: manual (dBm), low, medium or high. Applied with the wifi plan."""
    _site(site_id)
    mode = body.get("mode")
    if mode not in wifi.TX_MODES:
        raise ValueError("Kies handmatig, laag, midden of hoog")
    power = None
    if mode == "manual":
        try:
            power = int(body.get("power"))
        except (TypeError, ValueError):
            raise ValueError("Vul het zendvermogen in dBm in")
        if not 1 <= power <= 30:
            raise ValueError("Zendvermogen moet tussen 1 en 30 dBm liggen")
    db.x("INSERT INTO radio_settings (site_id, radio_mac, tx_mode, tx_power) VALUES (?,?,?,?) "
         "ON CONFLICT(site_id, radio_mac) DO UPDATE SET tx_mode=excluded.tx_mode, tx_power=excluded.tx_power",
         site_id, mac.upper(), mode, power)
    return {"ok": True}


@app.post("/api/sites/{site_id}/wifi/wlans")
def wlan_create(site_id: int, body: dict = Body(...), _: dict = Depends(user)):
    _site(site_id)
    f = _wlan_fields(body, site_id)
    taken = {w["slug"] for w in wifi.site_wlans(site_id)}
    slug = base = wifi.slugify(f["ssid"])
    n = 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    pos = (db.q1("SELECT COALESCE(MAX(position), 0) + 1 AS p FROM wlans WHERE site_id=?", site_id) or {"p": 1})["p"]
    wid = db.x("INSERT INTO wlans (site_id, slug, ssid, passphrase_enc, security, vlan_id, bands, hidden, isolation, ft, enabled, position) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", site_id, slug, f["ssid"], f["passphrase_enc"], f["security"], f["vlan_id"],
               f["bands"], f["hidden"], f["isolation"], f["ft"], f["enabled"], pos)
    return _wlan_view(db.q1("SELECT * FROM wlans WHERE id=?", wid))


@app.patch("/api/wlans/{wlan_id}")
def wlan_update(wlan_id: int, body: dict = Body(...), _: dict = Depends(user)):
    w = db.q1("SELECT * FROM wlans WHERE id=?", wlan_id)
    if not w:
        raise HTTPException(404, "Netwerk niet gevonden")
    f = _wlan_fields(body, w["site_id"], w)
    db.x("UPDATE wlans SET ssid=?, passphrase_enc=?, security=?, vlan_id=?, bands=?, hidden=?, isolation=?, ft=?, enabled=? WHERE id=?",
         f["ssid"], f["passphrase_enc"], f["security"], f["vlan_id"], f["bands"], f["hidden"], f["isolation"], f["ft"], f["enabled"], wlan_id)
    return _wlan_view(db.q1("SELECT * FROM wlans WHERE id=?", wlan_id))


@app.delete("/api/wlans/{wlan_id}")
def wlan_delete(wlan_id: int, _: dict = Depends(user)):
    db.x("DELETE FROM wlans WHERE id=?", wlan_id)
    return {"ok": True}


@app.get("/api/sites/{site_id}/wifi/plan")
async def wifi_plan(site_id: int, _: dict = Depends(user)):
    site = _site(site_id)
    ctrl = _controller(site_id)
    plan = await wifi.build_plan(Ros.for_device(ctrl), site["settings"], wifi.site_wlans(site_id), wifi.tx_radios(site_id))
    return {"controller": ctrl["name"], "ops": wifi.public_plan(plan)}


@app.post("/api/sites/{site_id}/wifi/apply")
async def wifi_apply(site_id: int, _: dict = Depends(user)):
    site = _site(site_id)
    ctrl = _controller(site_id)
    ros = Ros.for_device(ctrl)
    plan = await wifi.build_plan(ros, site["settings"], wifi.site_wlans(site_id), wifi.tx_radios(site_id))
    results = await wifi.apply_plan(ros, plan)
    ok = all(r["ok"] for r in results) and len(results) == len(plan)
    db.log(site_id, f"Wifi-instellingen toegepast op {ctrl['name']}: {sum(r['ok'] for r in results)}/{len(plan)} stappen",
           "ok" if ok else "error")
    await asyncio.sleep(0.5)
    await poller.refresh_device(ctrl)
    return {"ok": ok, "results": results, "remaining": len(plan) - len(results)}


@app.post("/api/devices/{dev_id}/adopt")
async def device_adopt(dev_id: int, body: dict = Body(default={}), _: dict = Depends(user)):
    dev = _device(dev_id)
    ctrl = _controller(dev["site_id"])
    if ctrl["id"] == dev["id"]:
        raise ValueError("De controller zelf kan geen CAP zijn. Gebruik 'Lokale radio's overnemen'.")
    steps = await wifi.adopt_ap(Ros.for_device(dev), ctrl["host"] if body.get("pin_controller") else None, body.get("bridge") or None)
    db.log(dev["site_id"], f"{dev['name']} geadopteerd door controller {ctrl['name']}", "ok")
    await asyncio.sleep(1)
    await asyncio.gather(poller.refresh_device(dev), poller.refresh_device(ctrl))
    return {"ok": True, "steps": steps}


@app.post("/api/devices/{dev_id}/release")
async def device_release(dev_id: int, _: dict = Depends(user)):
    dev = _device(dev_id)
    await wifi.release_ap(Ros.for_device(dev))
    db.log(dev["site_id"], f"{dev['name']} losgekoppeld van de controller (radio's weer lokaal beheerd)", "warn")
    ctrl = db.controller(dev["site_id"])
    await asyncio.gather(poller.refresh_device(dev), *([poller.refresh_device(ctrl)] if ctrl else []))
    return {"ok": True}


@app.post("/api/sites/{site_id}/wifi/local-radios")
async def wifi_local(site_id: int, body: dict = Body(default={}), _: dict = Depends(user)):
    """The controller's own radios: take them over (they carry the site's SSIDs) or give them back.

    Taking over sets the configuration profiles directly on the static interfaces, as the MikroTik CAPsMAN manual
    prescribes; it never provisions them. Both directions first repair radios that an older MikroManager did
    provision (disable rules, provision again, enable rules)."""
    site = _site(site_id)
    ctrl = _controller(site_id)
    ros = Ros.for_device(ctrl)
    take = body.get("action", "take") == "take"
    if not [r for r in await ros.get(wifi.RADIO) if not r.get("cap")]:
        raise ValueError("De controller heeft geen eigen radio's")
    done = await wifi.release_local(ros)
    if done:
        await asyncio.sleep(1)
    st = {**site["settings"], "local_radios": take}
    db.x("UPDATE sites SET settings=? WHERE id=?", json.dumps(st), site_id)
    if take:
        if not wifi.site_wlans(site_id):
            raise ValueError("Maak eerst een wifi-netwerk aan")
        ops = [o for o in await wifi.build_plan(ros, st, wifi.site_wlans(site_id), wifi.tx_radios(site_id)) if o.get("local")]
        results = await wifi.apply_plan(ros, ops)
        failed = next((r for r in results if not r["ok"]), None)
        if failed:
            raise RosError(f"{failed['text']}: {failed['error']}")
        done += [r["text"] for r in results]
        db.log(site_id, f"Eigen radio's van {ctrl['name']} zenden nu de netwerken van de site uit", "ok")
    else:
        done += await wifi.unmanage_local(ros)
        db.log(site_id, f"Eigen radio's van {ctrl['name']} teruggegeven (onbeheerd)", "warn")
    await asyncio.sleep(0.5)
    await poller.refresh_device(ctrl)
    return {"ok": True, "steps": done}


# ---- networks --------------------------------------------------------------

@app.get("/api/sites/{site_id}/networks")
async def networks_get(site_id: int, _: dict = Depends(user)):
    site = _site(site_id)
    ctrl = _controller(site_id)
    ros = Ros.for_device(ctrl)
    s = STATE.get(ctrl["id"]) or {}
    bridges = await ros.get("/interface/bridge")
    bridge = next((b for b in bridges if b["name"] == site["settings"]["bridge"]), None)
    ports = [p.get("interface") for p in await ros.get("/interface/bridge/port") if p.get("bridge") == site["settings"]["bridge"]]
    lists = sorted({l["name"] for l in await ros.get("/interface/list") if not truthy(l.get("builtin", "false"))})
    return {"networks": await networks.list_networks(ros, s.get("wan"), s.get("leases")),
            "bridge": {"name": site["settings"]["bridge"], "exists": bridge is not None,
                       "vlan_filtering": truthy((bridge or {}).get("vlan-filtering", "false")), "ports": ports},
            "bridges": [b["name"] for b in bridges], "interface_lists": lists,
            "dns": [d for d in await ros.get("/ip/dns/static") if not truthy(d.get("dynamic", "false"))]}


@app.post("/api/sites/{site_id}/networks")
async def network_create(site_id: int, body: dict = Body(...), _: dict = Depends(user)):
    site = _site(site_id)
    ctrl = _controller(site_id)
    ros = Ros.for_device(ctrl)
    existing = await networks.list_networks(ros)
    steps = await networks.create_network(ros, site["settings"]["bridge"], body, existing)
    db.log(site_id, f"Netwerk '{body.get('name')}' (VLAN {body.get('vlan_id')}) aangemaakt op {ctrl['name']}", "ok")
    await poller.refresh_device(ctrl)
    return {"ok": True, "steps": steps}


@app.delete("/api/sites/{site_id}/networks/{slug}")
async def network_delete(site_id: int, slug: str, _: dict = Depends(user)):
    ctrl = _controller(site_id)
    removed = await networks.delete_network(Ros.for_device(ctrl), slug)
    if not removed:
        raise HTTPException(404, "Geen door MikroManager beheerd netwerk met deze naam")
    db.log(site_id, f"Netwerk '{slug}' verwijderd van {ctrl['name']}", "warn")
    await poller.refresh_device(ctrl)
    return {"ok": True, "removed": removed}


@app.post("/api/sites/{site_id}/dns")
async def dns_add(site_id: int, body: dict = Body(...), _: dict = Depends(user)):
    if not body.get("name") or not body.get("address"):
        raise ValueError("Naam en adres zijn verplicht")
    await Ros.for_device(_controller(site_id)).add("/ip/dns/static", {
        "name": body["name"].strip(), "address": body["address"].strip(), "comment": body.get("comment") or "MikroManager"})
    return {"ok": True}


@app.delete("/api/sites/{site_id}/dns/{rec_id}")
async def dns_delete(site_id: int, rec_id: str, _: dict = Depends(user)):
    await Ros.for_device(_controller(site_id)).remove("/ip/dns/static", rec_id)
    return {"ok": True}


# ---- updates & backups -----------------------------------------------------

@app.get("/api/sites/{site_id}/updates")
def updates(site_id: int, _: dict = Depends(user)):
    return {"devices": [maint.update_info(d) for d in db.site_devices(site_id)], "job": maint.JOBS.get(site_id)}


@app.post("/api/sites/{site_id}/updates/check")
async def updates_check(site_id: int, _: dict = Depends(user)):
    async def one(d):
        try:
            return await maint.check_update(d)
        except RosError as e:
            return {**maint.update_info(d), "error": str(e)}
    return {"devices": await asyncio.gather(*(one(d) for d in db.site_devices(site_id)))}


@app.post("/api/sites/{site_id}/updates/all")
async def updates_all(site_id: int, _: dict = Depends(user)):
    return maint.start_site_upgrade(site_id)


@app.post("/api/devices/{dev_id}/upgrade")
async def device_upgrade(dev_id: int, _: dict = Depends(user)):
    dev = _device(dev_id)
    info = maint.update_info(dev)
    if not info["available"]:
        raise ValueError("Geen update beschikbaar. Controleer eerst op updates.")
    await maint.start_upgrade(dev)
    maint.watch_upgrade(dev, info["latest"])
    return {"ok": True, "target": info["latest"]}


@app.post("/api/devices/{dev_id}/firmware")
async def device_firmware(dev_id: int, _: dict = Depends(user)):
    dev = _device(dev_id)
    await maint.upgrade_firmware(dev)
    maint.watch_upgrade(dev, None)
    return {"ok": True}


def _backup(backup_id: int) -> dict:
    b = db.q1("SELECT * FROM backups WHERE id=?", backup_id)
    if not b:
        raise HTTPException(404, "Back-up niet gevonden")
    return b


@app.get("/api/sites/{site_id}/backups")
def backups(site_id: int, _: dict = Depends(user)):
    out = []
    for d in db.site_devices(site_id):
        rows = db.q("SELECT id, ts, size, ros_version, trigger FROM backups WHERE device_id=? ORDER BY ts DESC", d["id"])
        out.append({"device_id": d["id"], "name": d["name"], "role": d["role"], "backups": rows})
    return out


@app.post("/api/devices/{dev_id}/backups")
async def backup_now(dev_id: int, _: dict = Depends(user)):
    dev = _device(dev_id)
    res = await maint.backup_device(dev)
    if res["changed"]:
        db.log(dev["site_id"], f"Back-up van {dev['name']} opgeslagen")
    return res


@app.post("/api/sites/{site_id}/backups")
async def backup_site(site_id: int, _: dict = Depends(user)):
    out = []
    for dev in db.site_devices(site_id):
        try:
            out.append({"name": dev["name"], **(await maint.backup_device(dev))})
        except RosError as e:
            out.append({"name": dev["name"], "error": str(e)})
    db.log(site_id, f"Back-up van alle apparaten: {sum(1 for o in out if o.get('changed'))} nieuw, "
           f"{sum(1 for o in out if 'error' in o)} mislukt")
    return out


@app.get("/api/backups/{backup_id}")
def backup_get(backup_id: int, download: bool = False, _: dict = Depends(user)):
    b = _backup(backup_id)
    text = maint.read_backup(b)
    if download:
        dev = db.q1("SELECT name FROM devices WHERE id=?", b["device_id"]) or {"name": "device"}
        return PlainTextResponse(text, headers={
            "Content-Disposition": f'attachment; filename="{wifi.slugify(dev["name"])}-{b["filename"]}"'})
    return {"id": b["id"], "ts": b["ts"], "text": text}


@app.get("/api/backups/{backup_id}/diff/{other_id}")
def backup_diff(backup_id: int, other_id: int, _: dict = Depends(user)):
    a, b = _backup(other_id), _backup(backup_id)
    if a["device_id"] != b["device_id"]:
        raise ValueError("Back-ups horen bij verschillende apparaten")
    return maint.diff_backups(a, b)


@app.delete("/api/backups/{backup_id}")
def backup_delete(backup_id: int, _: dict = Depends(user)):
    maint.delete_backup(_backup(backup_id))
    return {"ok": True}


# ---- frontend --------------------------------------------------------------

@app.get("/api/{rest:path}", include_in_schema=False)
def api_404(rest: str):
    raise HTTPException(404, "Onbekend API-pad")


if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = (STATIC_DIR / path).resolve()
        if path and f.is_file() and STATIC_DIR.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
