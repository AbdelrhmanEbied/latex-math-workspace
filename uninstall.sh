#!/usr/bin/env bash
set -euo pipefail

PURGE=0
for arg in "$@"; do
    case "$arg" in
        --purge) PURGE=1 ;;
        -h|--help)
            echo "Usage: ./uninstall.sh [--purge]"
            echo "  --purge  Also remove ~/.config/latex-picker and state"
            exit 0
            ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
APP_DIR="$DATA_HOME/latex-picker"
BIN="$HOME/.local/bin/latex-picker"

rm -f "$BIN"
rm -f "$DATA_HOME/applications/latex-picker.desktop"
rm -f "$DATA_HOME/icons/hicolor/scalable/apps/latex-picker.svg"
rm -rf "$APP_DIR"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DATA_HOME/applications" >/dev/null 2>&1 || true
fi

if [ "$PURGE" = "1" ]; then
    rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/latex-picker"
    rm -rf "$STATE_HOME/latex-picker"
    echo "Removed installed files and user configuration."
else
    echo "Removed installed files. Config and recent items were kept;"
    echo "use --purge to remove them."
fi
