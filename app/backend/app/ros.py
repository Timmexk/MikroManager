"""Async client for the RouterOS v7 REST API.

Mapping (help.mikrotik.com, REST API):
  GET    /rest/<menu>            print
  GET    /rest/<menu>/<id|name>  print one record
  PUT    /rest/<menu>            add
  PATCH  /rest/<menu>/<id>       set
  DELETE /rest/<menu>/<id>       remove
  POST   /rest/<menu>/<command>  any console command
All values come back as strings, booleans as "true"/"false".
"""
from urllib.parse import quote

import httpx

from . import security

_clients: dict[bool, httpx.AsyncClient] = {}


class RosError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status

    @property
    def unreachable(self) -> bool:
        return self.status in (0, 502, 503, 504)


def _client(verify: bool) -> httpx.AsyncClient:
    if verify not in _clients:
        _clients[verify] = httpx.AsyncClient(
            verify=verify, limits=httpx.Limits(max_connections=40, max_keepalive_connections=20))
    return _clients[verify]


async def close_all() -> None:
    for c in _clients.values():
        await c.aclose()
    _clients.clear()


def truthy(v) -> bool:
    return str(v).lower() in ("true", "yes", "1")


def yn(v: bool) -> str:
    return "yes" if v else "no"


class Ros:
    def __init__(self, host: str, port: int, scheme: str, username: str, password: str, verify: bool = False):
        self.base = f"{scheme}://{host}:{port}/rest"
        self.auth = (username, password)
        self.verify = verify

    @classmethod
    def for_device(cls, dev: dict) -> "Ros":
        return cls(dev["host"], dev["port"], dev["scheme"], dev["username"],
                   security.decrypt(dev["password_enc"]), bool(dev["verify_tls"]))

    async def _req(self, method: str, path: str, body=None, params=None, timeout: float = 12):
        try:
            r = await _client(self.verify).request(
                method, self.base + path, json=body, params=params, auth=self.auth, timeout=timeout)
        except httpx.TimeoutException:
            raise RosError("Geen antwoord (timeout)")
        except httpx.ConnectError:
            raise RosError("Niet bereikbaar")
        except httpx.HTTPError as e:
            raise RosError(f"Verbindingsfout: {type(e).__name__}")
        if r.status_code == 401:
            raise RosError("Inloggen geweigerd (gebruikersnaam/wachtwoord of rechten)", 401)
        if r.status_code >= 400:
            try:
                j = r.json()
                msg = j.get("detail") or j.get("message") or r.text
            except ValueError:
                msg = r.text[:200] or f"HTTP {r.status_code}"
            raise RosError(str(msg), r.status_code)
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            raise RosError("Onverwacht antwoord (geen JSON) - is dit de REST API?")

    @staticmethod
    def _item(path: str, ident: str) -> str:
        return f"{path}/{quote(str(ident), safe='*')}"

    async def get(self, path: str, timeout: float = 12, **filters):
        """print. Keyword filters become ?key=value (underscores -> dashes)."""
        params = {k.replace("_", "-"): v for k, v in filters.items()} or None
        return await self._req("GET", path, params=params, timeout=timeout)

    async def add(self, path: str, data: dict) -> dict:
        return await self._req("PUT", path, body=data)

    async def set(self, path: str, ident: str, data: dict) -> dict:
        return await self._req("PATCH", self._item(path, ident), body=data)

    async def remove(self, path: str, ident: str) -> None:
        await self._req("DELETE", self._item(path, ident))

    async def cmd(self, path: str, data: dict | None = None, timeout: float = 30):
        return await self._req("POST", path, body=data or {}, timeout=timeout)
