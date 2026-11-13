#!/usr/bin/env bash
# Configure the global shortcut (and, on Hyprland, the floating window rule).
# Prints instructions by default; pass --apply to modify configuration.
set -euo pipefail

BINDING="${BINDING:-SUPER + SHIFT + L}"
APPLY=0
COMMAND=""

usage() {
    cat <<'EOF'
Usage: ./scripts/configure-shortcut.sh [--apply] [--binding "SUPER + SHIFT + L"]
                                        [--command PATH]

Without --apply, prints exactly what would change.  With --apply, writes a
small marked block to the detected Hyprland config, or registers a GNOME
custom keybinding.  KDE is configured through System Settings (instructions
are printed because its shortcut store is not stable public API).
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --apply) APPLY=1; shift ;;
        --binding) BINDING="${2:?--binding needs a value}"; shift 2 ;;
        --command) COMMAND="${2:?--command needs a value}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [ -z "$COMMAND" ]; then
    COMMAND="$(command -v latex-picker 2>/dev/null || true)"
fi
if [ -z "$COMMAND" ]; then
    COMMAND="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/bin/latex-picker"
fi

# "SUPER + SHIFT + L" -> array
IFS='+' read -r -a RAW_PARTS <<< "$BINDING"
MODIFIERS=()
KEY=""
for part in "${RAW_PARTS[@]}"; do
    trimmed="$(echo "$part" | sed 's/^ *//; s/ *$//')"
    [ -z "$trimmed" ] && continue
    MODIFIERS+=("$trimmed")
done
KEY="${MODIFIERS[${#MODIFIERS[@]}-1]}"
MODIFIERS=("${MODIFIERS[@]:0:${#MODIFIERS[@]}-1}")
MOD_STRING="$(IFS=' '; echo "${MODIFIERS[*]}")"

GNOME_BINDING=""
for modifier in "${MODIFIERS[@]}"; do
    case "${modifier^^}" in
        SUPER|LOGO|META) GNOME_BINDING+="<Super>" ;;
        SHIFT) GNOME_BINDING+="<Shift>" ;;
        CTRL|CONTROL) GNOME_BINDING+="<Control>" ;;
        ALT) GNOME_BINDING+="<Alt>" ;;
    esac
done
GNOME_BINDING+="$(echo "$KEY" | tr '[:upper:]' '[:lower:]')"

HYPRLAND=0
if [ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ] || [[ "${XDG_CURRENT_DESKTOP:-}" == *Hyprland* ]]; then
    HYPRLAND=1
fi
GNOME=0
if [[ "${XDG_CURRENT_DESKTOP:-}" == *GNOME* ]]; then GNOME=1; fi
KDE=0
if [[ "${XDG_CURRENT_DESKTOP:-}" == *KDE* || "${XDG_CURRENT_DESKTOP:-}" == *Plasma* ]]; then KDE=1; fi

if [ "$HYPRLAND" = "1" ]; then
    LUA_CFG="$HOME/.config/hypr/hyprland.lua"
    CAELESTIA_USER="$HOME/.config/caelestia/hypr-user.lua"
    HYPR_USER="$HOME/.config/hypr/hypr-user.lua"
    HYPR_CONF="$HOME/.config/hypr/hyprland.conf"

    if [ -f "$LUA_CFG" ] || [ -f "$CAELESTIA_USER" ] || [ -f "$HYPR_USER" ]; then
        if [ -f "$CAELESTIA_USER" ]; then
            TARGET="$CAELESTIA_USER"
        elif [ -f "$HYPR_USER" ]; then
            TARGET="$HYPR_USER"
        else
            echo "Detected a Lua Hyprland config but no known user override file."
            echo "Add this to the file required by your config:"
            echo
            echo "hl.bind(\"$BINDING\", hl.dsp.exec_cmd(\"$COMMAND\"))"
            echo "hl.window_rule({ match = { class = \"latex-picker\" }, float = true, center = true })"
            exit 0
        fi
        if grep -q 'latex-picker >>>' "$TARGET" 2>/dev/null; then
            echo "A latex-picker block is already present in $TARGET"
            exit 0
        fi
        BLOCK="$(cat <<EOF
-- >>> latex-picker >>>
hl.bind("$BINDING", hl.dsp.exec_cmd("$COMMAND"))
hl.window_rule({ match = { class = "latex-picker" }, float = true, center = true })
-- <<< latex-picker <<<
EOF
)"
        if [ "$APPLY" = "0" ]; then
            echo "Would append to $TARGET:"
            echo
            echo "$BLOCK"
            echo
            echo "Run with --apply to write it, then: hyprctl reload"
            exit 0
        fi
        BACKUP="$TARGET.bak.$(date +%Y%m%d-%H%M%S)"
        cp "$TARGET" "$BACKUP"
        printf '\n%s\n' "$BLOCK" >> "$TARGET"
        if command -v hyprctl >/dev/null 2>&1; then
            hyprctl reload >/dev/null 2>&1 && echo "Reloaded Hyprland." || echo "Could not reload; run: hyprctl reload"
        fi
        echo "Configured $BINDING → $COMMAND"
        echo "  config: $TARGET"
        echo "  backup: $BACKUP"
        exit 0
    fi

    # Classic Hyprland configuration
    if [ -f "$HYPR_CONF" ]; then
        if grep -q '# >>> latex-picker >>>' "$HYPR_CONF" 2>/dev/null; then
            echo "A latex-picker block is already present in $HYPR_CONF"
            exit 0
        fi
        BLOCK="$(cat <<EOF
# >>> latex-picker >>>
bind = $MOD_STRING, $KEY, exec, $COMMAND
windowrulev2 = float,class:^(latex-picker)\$
windowrulev2 = center,class:^(latex-picker)\$
# <<< latex-picker <<<
EOF
)"
        if [ "$APPLY" = "0" ]; then
            echo "Would append to $HYPR_CONF:"
            echo
            echo "$BLOCK"
            echo
            echo "Run with --apply to write it, then: hyprctl reload"
            exit 0
        fi
        BACKUP="$HYPR_CONF.bak.$(date +%Y%m%d-%H%M%S)"
        cp "$HYPR_CONF" "$BACKUP"
        printf '\n%s\n' "$BLOCK" >> "$HYPR_CONF"
        hyprctl reload >/dev/null 2>&1 || true
        echo "Configured $BINDING → $COMMAND"
        echo "  config: $HYPR_CONF"
        echo "  backup: $BACKUP"
        exit 0
    fi
fi

if [ "$GNOME" = "1" ]; then
    SCHEMA="org.gnome.settings-daemon.plugins.media-keys"
    KEY_SCHEMA="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
    PATH_ID="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/latex-picker/"
    if [ "$APPLY" = "0" ]; then
        cat <<EOF
Would register a GNOME custom shortcut:
  name:    LaTeX Picker
  command: $COMMAND
  binding: $GNOME_BINDING
Path: $PATH_ID

Run with --apply to register it with gsettings.
EOF
        exit 0
    fi
    CURRENT="$(gsettings get "$SCHEMA" custom-keybindings 2>/dev/null || echo "[]")"
    NEW_LIST="$(python3 - "$CURRENT" "$PATH_ID" <<'PY'
import ast, sys
raw, path = sys.argv[1], sys.argv[2]
raw = raw.replace("@as ", "").strip() or "[]"
try:
    items = ast.literal_eval(raw)
except Exception:
    items = []
items = [str(item) for item in items]
if path not in items:
    items.append(path)
print("[" + ", ".join(repr(item) for item in items) + "]")
PY
)"
    gsettings set "$SCHEMA" custom-keybindings "$NEW_LIST"
    gsettings set "$KEY_SCHEMA:$PATH_ID" name "LaTeX Picker"
    gsettings set "$KEY_SCHEMA:$PATH_ID" command "$COMMAND"
    gsettings set "$KEY_SCHEMA:$PATH_ID" binding "$GNOME_BINDING"
    echo "Registered GNOME shortcut $GNOME_BINDING → $COMMAND"
    exit 0
fi

if [ "$KDE" = "1" ]; then
    cat <<EOF
KDE Plasma: configure the shortcut in System Settings.

  1. System Settings → Keyboard → Shortcuts → Custom Shortcuts
  2. New → Global Shortcut → Command/URL
  3. Name: LaTeX Picker
     Trigger: Super+Shift+L
     Action: $COMMAND

The desktop entry installed by install.sh also appears in the application
launcher, where a shortcut can be assigned from its context menu.
EOF
    exit 0
fi

cat <<EOF
Could not identify a supported desktop environment.

Bind this command to $BINDING in your window manager or desktop settings:

  $COMMAND

Hyprland (classic):  bind = $MOD_STRING, $KEY, exec, $COMMAND
Sway:                bindsym Super+Shift+l exec $COMMAND
GNOME/KDE:           Settings → Keyboard → Custom Shortcuts

The application does not grab keys itself: Wayland forbids that, so the
compositor/desktop must own the shortcut.
EOF
