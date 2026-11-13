import contextvars
import os
from pathlib import Path

VERSION = "0.3.0"


def env(name: str, default: str = "") -> str:
    """MIKROMANAGER_<NAME>, falling back to the old TIKCONTROL_<NAME> so existing installs keep working."""
    return os.environ.get(f"MIKROMANAGER_{name}", os.environ.get(f"TIKCONTROL_{name}", default))


def flag(name: str) -> bool:
    return env(name).lower() in ("1", "true", "yes")


DATA_DIR = Path(env("DATA", "/data"))
STATIC_DIR = Path(env("STATIC", str(Path(__file__).resolve().parent.parent / "static")))
POLL_INTERVAL = int(env("POLL", "15"))
DEMO = flag("DEMO")
if DEMO:
    DATA_DIR = DATA_DIR / "demo"   # wiped on every start, never touches real data
SECURE_COOKIE = flag("SECURE_COOKIE")
DB_NAME, OLD_DB_NAME = "mikromanager.db", "tikcontrol.db"

# Everything MikroManager creates on a router carries a prefix (names: "mm-") or tag (comments: "mm:").
# The sync code never touches objects without it. Sites made with 0.1/0.2 used "tc-"/"tc:"; they keep
# that, so nothing on those routers has to be renamed. The prefix is a per-site setting.
NEW_PREFIX, OLD_PREFIX = "mm", "tc"
_prefix: contextvars.ContextVar[str] = contextvars.ContextVar("site_prefix", default=NEW_PREFIX)


def use_prefix(settings_or_prefix) -> str:
    """Select the naming of the site being worked on (call at the start of a request or job)."""
    p = settings_or_prefix.get("prefix", OLD_PREFIX) if isinstance(settings_or_prefix, dict) else settings_or_prefix
    _prefix.set(p if p in (NEW_PREFIX, OLD_PREFIX) else NEW_PREFIX)
    return _prefix.get()


def pfx() -> str:
    return _prefix.get() + "-"


def tag() -> str:
    return _prefix.get() + ":"


DEFAULT_SITE_SETTINGS = {
    "country": "Netherlands",
    "bridge": "bridge",
    "capsman_interfaces": "",      # empty = same as bridge
    "local_radios": False,         # controller's own radios carry the site's SSIDs (static interfaces, no provisioning)
    "ch2_width": "20mhz",
    "ch2_freq": "",                # empty = automatic
    "ch5_width": "20/40/80mhz",
    "ch5_freq": "",
    "skip_dfs": "disabled",        # disabled | 10min-cac | all
    "ac_caps": False,              # also provision wifi-qcom-ac CAPs (no VLAN in datapath)
    "backup_enabled": True,
    "backup_hour": 3,
    "backup_keep": 30,
    "backup_sensitive": False,
}

# Safe mode: risky changes arm a scheduler on the device that undoes them after
# this many seconds, unless MikroManager can still reach the device and disarms it.
SAFE_SECS = int(env("SAFE_SECS", "90"))
SAFE_CHECK_SECS = int(env("SAFE_CHECK_SECS", "20"))

# Live view: while someone has the overview or a device page open, counters and CPU are read
# every LIVE_INTERVAL seconds and kept in memory for LIVE_WINDOW seconds (not in the database).
LIVE_INTERVAL = float(env("LIVE_INTERVAL", "2"))
LIVE_WINDOW = int(env("LIVE_WINDOW", "600"))
LIVE_PING_EVERY = int(env("LIVE_PING_EVERY", "3"))   # ping every N live ticks
LIVE_IDLE_AFTER = 60   # stop fast polling this many seconds after the last viewer
