#!/usr/bin/env bash
# MikroManager - installeren, bijwerken of verwijderen op Linux met systemd.
#
#   sudo bash linux/install.sh              installeren of bijwerken (data en instellingen blijven staan)
#   sudo bash linux/install.sh --uninstall  service en programma verwijderen, data blijft staan
#   sudo bash linux/install.sh --purge      alles verwijderen, ook database, secret.key en back-ups
#
# Variabelen:
#   PYTHON=python3.12           een andere Python kiezen
#   MM_FRONTEND=build           frontend zelf bouwen met npm in plaats van downloaden
#   MM_FRONTEND_URL=...         frontend van een ander adres downloaden
set -euo pipefail

APP=mikromanager
PREFIX=/opt/$APP
CONF_DIR=/etc/$APP
DATA_DIR=/var/lib/$APP
UNIT=/etc/systemd/system/$APP.service
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # map v0.1
PYTHON="${PYTHON:-python3}"
REPO=Timmexk/MikroManager
MM_FRONTEND="${MM_FRONTEND:-download}"
MM_FRONTEND_URL="${MM_FRONTEND_URL:-https://github.com/$REPO/releases/download/frontend-latest/mikromanager-frontend-v0.2.tar.gz}"
MIN_PY="3.10"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

hint_python() {
    # Welke pakketten nodig zijn verschilt per distro
    if   command -v apt-get >/dev/null; then echo "sudo apt install python3 python3-venv"
    elif command -v dnf     >/dev/null; then echo "sudo dnf install python3"
    elif command -v pacman  >/dev/null; then echo "sudo pacman -S python"
    elif command -v zypper  >/dev/null; then echo "sudo zypper install python311"
    else echo "installeer Python $MIN_PY of nieuwer met venv-ondersteuning"; fi
}

download() {   # download URL BESTAND
    if   command -v curl >/dev/null; then curl -fsSL --retry 2 -o "$2" "$1"
    elif command -v wget >/dev/null; then wget -q -O "$2" "$1"
    else return 1; fi
}

[[ $EUID -eq 0 ]] || die "Draai dit script met sudo."
[[ -d /run/systemd/system ]] || die "Dit systeem draait niet op systemd. Gebruik de Docker-installatie (zie README)."

# ---- verwijderen ------------------------------------------------------------
if [[ "${1:-}" == "--uninstall" || "${1:-}" == "--purge" ]]; then
    say "Service stoppen en verwijderen"
    systemctl disable --now $APP 2>/dev/null || true
    rm -f "$UNIT"; systemctl daemon-reload
    rm -rf "$PREFIX"
    if [[ "$1" == "--purge" ]]; then
        rm -rf "$DATA_DIR" "$CONF_DIR"
        userdel $APP 2>/dev/null || true
        say "Alles verwijderd, ook de data."
    else
        say "Verwijderd. Data staat nog in $DATA_DIR, instellingen in $CONF_DIR."
    fi
    exit 0
fi

# ---- controles --------------------------------------------------------------
command -v "$PYTHON" >/dev/null || die "Python niet gevonden: $(hint_python)"
"$PYTHON" -c "import sys; sys.exit(0 if sys.version_info >= tuple(map(int, '$MIN_PY'.split('.'))) else 1)" \
    || die "Python $MIN_PY of nieuwer nodig, gevonden: $("$PYTHON" -V). Kies een andere met PYTHON=python3.12."
"$PYTHON" -c "import venv, ensurepip" 2>/dev/null || die "Python-venv ontbreekt: $(hint_python)"

# ---- frontend ---------------------------------------------------------------
# De gebouwde frontend komt standaard van GitHub (gebouwd door GitHub Actions), dan is npm niet nodig.
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
STATIC="$WORK/static"; mkdir -p "$STATIC"

build_frontend() {
    command -v npm >/dev/null || return 1
    say "Frontend bouwen met npm"
    (cd "$SRC/frontend" && npm ci --no-audit --no-fund && npm run build) || return 1
    cp -r "$SRC/backend/static/." "$STATIC/"
}

if [[ "$MM_FRONTEND" == "build" ]]; then
    build_frontend || die "Frontend bouwen mislukt. Is npm geïnstalleerd (pakket nodejs/npm)?"
elif say "Frontend downloaden" && download "$MM_FRONTEND_URL" "$WORK/frontend.tar.gz" \
        && tar -xzf "$WORK/frontend.tar.gz" -C "$STATIC" && [[ -f "$STATIC/index.html" ]]; then
    :
else
    warn "Downloaden van de frontend lukte niet ($MM_FRONTEND_URL)"
    rm -rf "${STATIC:?}"/*
    if ! build_frontend; then
        if [[ -f "$SRC/backend/static/index.html" ]]; then
            warn "Ik gebruik de eerder gebouwde frontend in backend/static (mogelijk verouderd)"
            cp -r "$SRC/backend/static/." "$STATIC/"
        else
            die "Geen frontend: downloaden mislukte en npm ontbreekt. Controleer de internetverbinding, of installeer nodejs en npm en draai opnieuw met MM_FRONTEND=build."
        fi
    fi
fi

# ---- gebruiker --------------------------------------------------------------
if ! id $APP >/dev/null 2>&1; then
    say "Systeemgebruiker $APP aanmaken"
    NOLOGIN="$(command -v nologin || echo /usr/sbin/nologin)"
    useradd --system --user-group --home-dir "$DATA_DIR" --no-create-home --shell "$NOLOGIN" $APP
fi

# ---- programma --------------------------------------------------------------
WAS_ACTIVE=0; systemctl is-active --quiet $APP && WAS_ACTIVE=1
say "Programma kopiëren naar $PREFIX"
install -d -m 0755 "$PREFIX"
rm -rf "$PREFIX/app.new" "$PREFIX/mock.new" "$PREFIX/static.new"
cp -r "$SRC/backend/app"    "$PREFIX/app.new"
cp -r "$SRC/backend/mock"   "$PREFIX/mock.new"
cp -r "$STATIC" "$PREFIX/static.new"
find "$PREFIX"/*.new -name __pycache__ -type d -prune -exec rm -rf {} +
for d in app mock static; do rm -rf "${PREFIX:?}/$d"; mv "$PREFIX/$d.new" "$PREFIX/$d"; done
install -m 0644 "$SRC/backend/requirements.txt" "$PREFIX/requirements.txt"

# venv opnieuw maken als Python van versie is veranderd (bijv. na een distro-upgrade)
WANT_PY="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
HAVE_PY="$("$PREFIX/venv/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
if [[ "$WANT_PY" != "$HAVE_PY" ]]; then
    say "Python-omgeving maken ($WANT_PY)"
    rm -rf "$PREFIX/venv"
    "$PYTHON" -m venv "$PREFIX/venv"
fi
say "Python-pakketten installeren"
"$PREFIX/venv/bin/pip" install --quiet --disable-pip-version-check --upgrade pip
"$PREFIX/venv/bin/pip" install --quiet --disable-pip-version-check -r "$PREFIX/requirements.txt"
chown -R root:root "$PREFIX"; chmod -R go-w,a+rX "$PREFIX"
command -v restorecon >/dev/null && restorecon -R "$PREFIX" 2>/dev/null || true   # SELinux (Fedora/RHEL)

# ---- instellingen en service ------------------------------------------------
install -d -m 0750 -o root -g $APP "$CONF_DIR"
if [[ ! -f "$CONF_DIR/$APP.env" ]]; then
    install -m 0640 -o root -g $APP "$SRC/linux/$APP.env" "$CONF_DIR/$APP.env"
    say "Instellingen geplaatst in $CONF_DIR/$APP.env"
else
    say "Bestaande instellingen in $CONF_DIR/$APP.env blijven staan"
fi
install -m 0644 "$SRC/linux/$APP.service" "$UNIT"
systemctl daemon-reload

if [[ $WAS_ACTIVE -eq 1 ]]; then
    say "Service herstarten"; systemctl restart $APP
else
    say "Service inschakelen en starten"; systemctl enable --now $APP
fi

sleep 3
PORT="$(sed -n 's/^MM_PORT=//p' "$CONF_DIR/$APP.env" | tail -1)"
if systemctl is-active --quiet $APP; then
    say "MikroManager draait: http://$(hostname -I 2>/dev/null | awk '{print $1}'):${PORT:-8080}"
    echo "    Logs:    journalctl -u $APP -f"
    echo "    Back-up: bewaar $DATA_DIR (vooral secret.key samen met de database)"
else
    warn "De service is niet gestart. Kijk in: journalctl -u $APP -n 50"; exit 1
fi
