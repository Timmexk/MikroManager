import os
from pathlib import Path

VERSION = "0.2.0"

DATA_DIR = Path(os.environ.get("TIKCONTROL_DATA", "/data"))
STATIC_DIR = Path(os.environ.get("TIKCONTROL_STATIC", Path(__file__).resolve().parent.parent / "static"))
POLL_INTERVAL = int(os.environ.get("TIKCONTROL_POLL", "15"))
DEMO = os.environ.get("TIKCONTROL_DEMO", "").lower() in ("1", "true", "yes")
if DEMO:
    DATA_DIR = DATA_DIR / "demo"   # wiped on every start, never touches real data
SECURE_COOKIE = os.environ.get("TIKCONTROL_SECURE_COOKIE", "").lower() in ("1", "true", "yes")

# Everything MikroManager creates on a router carries this prefix (names) or
# "tc:" (comments). The sync code never touches objects without it.
PREFIX = "tc-"
TAG = "tc:"

DEFAULT_SITE_SETTINGS = {
    "country": "Netherlands",
    "bridge": "bridge",
    "capsman_interfaces": "",      # empty = same as bridge
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
SAFE_SECS = int(os.environ.get("TIKCONTROL_SAFE_SECS", "90"))
SAFE_CHECK_SECS = int(os.environ.get("TIKCONTROL_SAFE_CHECK_SECS", "20"))

# Live view: while someone has the overview or a device page open, counters and CPU are read
# every LIVE_INTERVAL seconds and kept in memory for LIVE_WINDOW seconds (not in the database).
LIVE_INTERVAL = float(os.environ.get("TIKCONTROL_LIVE_INTERVAL", "2"))
LIVE_WINDOW = int(os.environ.get("TIKCONTROL_LIVE_WINDOW", "600"))
LIVE_PING_EVERY = int(os.environ.get("TIKCONTROL_LIVE_PING_EVERY", "3"))   # ping every N live ticks
LIVE_IDLE_AFTER = 60   # stop fast polling this many seconds after the last viewer
