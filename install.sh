#!/bin/sh
# Ruttla installieren (Linux, macOS): eigene Python-Umgebung, dann Paket und
# passende Rust-Engine aus dem letzten GitHub-Release (`ruttla update`).
#
#   curl -fsSL https://raw.githubusercontent.com/hehljo/Ruttla/main/install.sh | sh
#
# Erneut ausführen oder `ruttla update` holt den neuesten Stand.
# Einstellbar: RUTTLA_HOME (Vorgabe ~/.local/share/ruttla),
# RUTTLA_BIN_DIR (Vorgabe ~/.local/bin), RUTTLA_CHANNEL (auto|stable|nightly).
set -eu

RUTTLA_HOME="${RUTTLA_HOME:-$HOME/.local/share/ruttla}"
BIN_DIR="${RUTTLA_BIN_DIR:-$HOME/.local/bin}"
CHANNEL="${RUTTLA_CHANNEL:-auto}"
BOOTSTRAP="ruttla @ https://github.com/hehljo/Ruttla/archive/refs/heads/main.tar.gz"

fail() { echo "ruttla-install: $*" >&2; exit 1; }

PY=""
for cand in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "$cand" >/dev/null 2>&1 &&
       "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
        PY="$cand"
        break
    fi
done
[ -n "$PY" ] || fail "Python >= 3.11 nicht gefunden (z. B. 'sudo apt install python3' oder 'brew install python')."

VENV="$RUTTLA_HOME/venv"
"$PY" -m venv "$VENV" ||
    fail "Python-venv fehlt (Debian/Ubuntu: 'sudo apt install python3-venv')."
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet "$BOOTSTRAP"
"$VENV/bin/ruttla" update --channel "$CHANNEL"

mkdir -p "$BIN_DIR"
ln -sf "$VENV/bin/ruttla" "$BIN_DIR/ruttla"
echo "Ruttla installiert: $BIN_DIR/ruttla ($("$BIN_DIR/ruttla" --version))"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo "Hinweis: $BIN_DIR steht nicht im PATH — z. B. in ~/.profile ergänzen: export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac
