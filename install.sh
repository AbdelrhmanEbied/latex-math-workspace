#!/usr/bin/env bash
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$DATA_HOME/latex-picker"
VENV="$APP_DIR/venv"
DESKTOP_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/scalable/apps"

WITH_PREVIEW=0
CONFIGURE=0
for arg in "$@"; do
    case "$arg" in
        --with-preview) WITH_PREVIEW=1 ;;
        --configure) CONFIGURE=1 ;;
        -h|--help)
            cat <<'EOF'
Usage: ./install.sh [--with-preview] [--configure]

Creates a private virtualenv in ~/.local/share/latex-picker, installs the app,
adds a launcher in ~/.local/bin and a desktop entry.

  --with-preview  Install matplotlib into the venv (otherwise the system copy
                  is used when available; Unicode previews otherwise).
  --configure     Also install the Super+Shift+L shortcut and (on Hyprland)
                  the floating-window rule by calling configure-shortcut.sh.
EOF
            exit 0
            ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "error: $PYTHON not found" >&2
    exit 1
fi

if ! "$PYTHON" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
then
    echo "error: Python 3.10 or newer is required" >&2
    exit 1
fi

mkdir -p "$APP_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR"

echo "→ Creating virtual environment in $VENV"
"$PYTHON" -m venv --system-site-packages "$VENV"

if ! "$VENV/bin/python" -c "import PyQt6" 2>/dev/null; then
    echo "→ PyQt6 is not available; installing it (may download a wheel)"
    "$VENV/bin/pip" install --upgrade "PyQt6>=6.5"
fi

if [ "$WITH_PREVIEW" = "1" ]; then
    if ! "$VENV/bin/python" -c "import matplotlib" 2>/dev/null; then
        echo "→ Installing optional matplotlib preview renderer"
        "$VENV/bin/pip" install "matplotlib>=3.6"
    fi
fi

if ! "$VENV/bin/python" -c "import sympy, numpy, scipy, matplotlib" 2>/dev/null; then
    echo "→ Installing math libraries for the workspace (sympy, numpy, scipy, matplotlib)"
    "$VENV/bin/pip" install "sympy>=1.12" "numpy>=1.24" "scipy>=1.10" "matplotlib>=3.6"
fi

echo "→ Installing LaTeX Picker into $VENV"
"$VENV/bin/pip" install --no-deps --no-build-isolation --force-reinstall "$SRC"

ln -sfn "$VENV/bin/latex-picker" "$BIN_DIR/latex-picker"
chmod +x "$SRC/bin/latex-picker"

install -m 0644 "$SRC/latex-picker.desktop" "$DESKTOP_DIR/latex-picker.desktop"
sed -i "s|^Exec=.*|Exec=$BIN_DIR/latex-picker|" "$DESKTOP_DIR/latex-picker.desktop"
install -m 0644 "$SRC/assets/icon.svg" "$ICON_DIR/latex-picker.svg"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
fi

if [ -n "${WAYLAND_DISPLAY:-}" ] && ! command -v wl-copy >/dev/null 2>&1; then
    echo
    echo "⚠ wl-clipboard is not installed. On Wayland the clipboard will be kept"
    echo "  alive only while the picker process is running. Install it with:"
    echo "     sudo pacman -S wl-clipboard        # Arch"
    echo "     sudo apt install wl-clipboard      # Debian/Ubuntu"
    echo "     sudo dnf install wl-clipboard      # Fedora"
fi

echo
echo "Installed:"
echo "  launcher  $BIN_DIR/latex-picker"
echo "  desktop   $DESKTOP_DIR/latex-picker.desktop"
echo "  data      $APP_DIR"
echo
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo "Note: $BIN_DIR is not in PATH. Add it to your shell profile."
fi
echo "Verify the installation with:"
echo "  latex-picker --doctor"
echo
if [ "$CONFIGURE" = "1" ]; then
    "$SRC/scripts/configure-shortcut.sh" --apply
else
    echo "Configure the global shortcut with:"
    echo "  $SRC/scripts/configure-shortcut.sh --apply"
    echo "or follow: latex-picker --shortcut-help"
fi
