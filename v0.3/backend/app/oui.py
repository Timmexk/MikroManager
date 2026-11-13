"""Manufacturer of a device from the first half of its MAC address (the OUI).

The list is the public registry of the IEEE (about 38,000 prefixes). MikroManager does not ship it: it is
downloaded once and refreshed every two months, into the data folder. Nothing about your network is sent;
it is a plain download of a public file. Set MIKROMANAGER_OUI_AUTO=0 to never download it by itself.

Phones and laptops often use a random ("private") MAC address per network. Those have no manufacturer;
they are recognised by the locally-administered bit and shown as such.
"""
import csv
import io
import logging
import re
import time
from pathlib import Path

import httpx

from .config import DATA_DIR, DEMO, env

log = logging.getLogger("mikromanager")
URL = env("OUI_URL", "https://standards-oui.ieee.org/oui/oui.csv")
AUTO = env("OUI_AUTO", "1") != "0"
MAX_AGE = 60 * 86400
_table: dict[str, str] | None = None
_last_try = 0.0
_SUFFIX = re.compile(r"[,.]?\s+(inc|incorporated|corp|corporation|co|ltd|limited|llc|gmbh|ag|bv|b\.v|sa|s\.a|srl|oy|ab|as|plc|"
                     r"company|technologies|technology|electronics|international|holdings?)\.?$", re.I)
# Enough to make the simulated network look right; real installs use the IEEE list.
DEMO_TABLE = {"00E04C": "Realtek Semiconductor", "48A98A": "Routerboard.com"}


def _file() -> Path:
    return DATA_DIR / "oui.tsv"


def short(name: str) -> str:
    name = " ".join(name.split())
    for _ in range(3):
        name = _SUFFIX.sub("", name).rstrip(" ,.")
    return name[:40]


def _load() -> dict[str, str]:
    global _table
    if _table is None:
        _table = dict(DEMO_TABLE) if DEMO else {}
        try:
            for line in _file().read_text(encoding="utf-8").splitlines():
                p, _, n = line.partition("\t")
                if len(p) == 6 and n:
                    _table[p] = n
        except OSError:
            pass
    return _table


def parse_ieee_csv(text: str) -> dict[str, str]:
    """IEEE oui.csv: Registry,Assignment,Organization Name,Organization Address"""
    out = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 3 and re.fullmatch(r"[0-9A-Fa-f]{6}", row[1].strip()):
            out[row[1].strip().upper()] = short(row[2])
    return out


async def update() -> int:
    """Download the registry now. Returns the number of prefixes."""
    global _table, _last_try
    _last_try = time.time()
    if URL.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=60, follow_redirects=True, headers={"User-Agent": "MikroManager"}) as c:
            r = await c.get(URL)
            r.raise_for_status()
            text = r.text
    else:
        text = Path(URL).read_text(encoding="utf-8", errors="replace")
    table = parse_ieee_csv(text)
    if len(table) < 5 and URL.startswith("http"):
        raise ValueError("De lijst van de IEEE had een onverwachte inhoud")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _file().write_text("".join(f"{p}\t{n}\n" for p, n in sorted(table.items())), encoding="utf-8")
    _table = None
    return len(_load())


async def refresh_if_stale() -> None:
    """Called from the poll loop: at most one attempt per day, only when the list is missing or old."""
    if not AUTO or DEMO or time.time() - _last_try < 86400:
        return
    try:
        if time.time() - _file().stat().st_mtime < MAX_AGE:
            return
    except OSError:
        pass
    try:
        n = await update()
        log.info("Fabrikantenlijst bijgewerkt: %d prefixen", n)
    except Exception as e:      # no internet is fine; try again tomorrow
        log.info("Fabrikantenlijst niet kunnen ophalen (%s); morgen opnieuw", e)


def status() -> dict:
    try:
        updated = _file().stat().st_mtime
    except OSError:
        updated = None
    return {"count": len(_load()), "updated": updated, "auto": AUTO, "source": URL}


def is_random(mac: str) -> bool:
    """Locally administered address: second hex digit is 2, 6, A or E."""
    return len(mac) >= 2 and mac[1].upper() in "26AE"


def lookup(mac: str) -> str | None:
    return None if is_random(mac) else _load().get(mac.replace(":", "").replace("-", "").upper()[:6])
