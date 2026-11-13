"""Session/compositor detection, diagnostics and shortcut instructions."""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass
from importlib import metadata, util
from pathlib import Path

from .config import APP_NAME, VERSION, config_path


@dataclass(frozen=True)
class SessionInfo:
    session_type: str
    desktop: str
    compositor: str
    is_wayland: bool
    is_x11: bool
    is_hyprland: bool

    @property
    def label(self) -> str:
        pieces = [self.session_type]
        if self.compositor:
            pieces.append(self.compositor)
        elif self.desktop:
            pieces.append(self.desktop)
        return " / ".join(pieces)


def detect_session() -> SessionInfo:
    wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
    x11 = bool(os.environ.get("DISPLAY"))
    session_type = "wayland" if wayland else ("x11" if x11 else "unknown")
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "") or os.environ.get("XDG_SESSION_DESKTOP", "")
    compositor = ""
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") or "Hyprland" in desktop:
        compositor = "Hyprland"
    elif "sway" in desktop.lower():
        compositor = "Sway"
    elif "KDE" in desktop.upper() or "PLASMA" in desktop.upper():
        compositor = "KWin"
    elif "GNOME" in desktop.upper():
        compositor = "Mutter"
    return SessionInfo(
        session_type=session_type,
        desktop=desktop,
        compositor=compositor,
        is_wayland=wayland,
        is_x11=x11 and not wayland,
        is_hyprland=compositor == "Hyprland",
    )


def hyprland_user_config() -> Path | None:
    """Best guess at the file a Hyprland user should edit.

    Caelestia's Lua config keeps user overrides in ~/.config/caelestia and the
    stock Lua layout uses ~/.config/hypr/hypr-user.lua.  Classic Hyprland uses
    hyprland.conf.
    """
    home = Path.home()
    candidates = [
        home / ".config/caelestia/hypr-user.lua",
        home / ".config/hypr/hypr-user.lua",
        home / ".config/hypr/hyprland.conf",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if (home / ".config/hypr/hyprland.lua").exists():
        return home / ".config/hypr/hypr-user.lua"
    return None


def hyprland_config_style() -> str:
    home = Path.home()
    if (home / ".config/hypr/hyprland.lua").exists():
        return "lua"
    return "classic"


def hyprland_rule_installed() -> bool:
    """Return True when a window rule mentioning latex-picker is present."""
    home = Path.home()
    roots = [home / ".config/hypr", home / ".config/caelestia"]
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix not in {".conf", ".lua"} or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "latex-picker" not in text:
                continue
            if "window_rule" in text or "windowrulev2" in text:
                return True
    return False


def preview_backend() -> tuple[str, str]:
    """Return (kind, description) without importing matplotlib."""
    if util.find_spec("matplotlib") is None:
        return "unicode", "Matplotlib not installed; using Unicode previews"
    try:
        version = metadata.version("matplotlib")
    except metadata.PackageNotFoundError:
        version = "unknown"
    return "matplotlib", f"Matplotlib {version} mathtext"


def doctor_report() -> str:
    session = detect_session()
    from .clipboard import available_backends, preferred_backend

    backends = available_backends()
    backend = preferred_backend()
    _, preview_desc = preview_backend()
    try:
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
        qt_line = f"Qt                 {QT_VERSION_STR} (PyQt {PYQT_VERSION_STR})"
    except Exception:  # noqa: BLE001 - diagnostics must not crash
        qt_line = "Qt                 unavailable"
    lines = [
        f"{APP_NAME} {VERSION}",
        f"Python             {sys.version.split()[0]} ({platform.platform()})",
        qt_line,
        f"Session            {session.label}",
        f"XDG_CURRENT_DESKTOP {session.desktop or '-'}",
        f"WAYLAND_DISPLAY    {os.environ.get('WAYLAND_DISPLAY', '-')}",
        f"DISPLAY            {os.environ.get('DISPLAY', '-')}",
        f"Clipboard backend  {backend}",
        f"  wl-copy          {backends['wl-copy'] or 'not found'}",
        f"  xclip            {backends['xclip'] or 'not found'}",
        f"  xsel             {backends['xsel'] or 'not found'}",
        f"Preview backend    {preview_desc}",
        f"Config             {config_path()}",
    ]
    try:
        from .library import load_library
        library, warnings = load_library()
        counts = library.counts_by_category()
        lines.append(
            f"Library            {len(library.snippets)} snippets, "
            f"{len(library.categories)} categories"
        )
        lines.append(
            "  " + ", ".join(f"{c.name}: {counts.get(c.id, 0)}" for c in library.categories)
        )
        lines.extend(f"Warning: {warning}" for warning in warnings)
    except Exception as exc:  # noqa: BLE001 - diagnostics should never crash
        lines.append(f"Library            ERROR: {exc}")

    if session.is_wayland:
        lines.append("Hotkey model       compositor keybinding (Wayland cannot be grabbed by apps)")
    else:
        lines.append("Hotkey model       desktop-environment keybinding")
    if session.is_hyprland:
        lines.append(f"Hyprland config    {hyprland_user_config() or '-'} ({hyprland_config_style()})")
        lines.append(
            "Window rule        " + ("installed" if hyprland_rule_installed() else "NOT FOUND")
        )

    lines.extend(["", "Recommended shortcut setup", "-" * 26])
    lines.append(shortcut_instructions(include_rule=session.is_hyprland))
    return "\n".join(lines)


def shortcut_instructions(command: str = "latex-picker", binding: str = "SUPER + SHIFT + L",
                          *, include_rule: bool = True) -> str:
    """Human-readable, copy-pasteable setup instructions for the current DE."""
    session = detect_session()
    if session.is_hyprland:
        style = hyprland_config_style()
        target = hyprland_user_config() or Path("~/.config/hypr/hypr-user.lua")
        target_display = str(target).replace(str(Path.home()), "~", 1)
        if style == "lua":
            rule = (
                '\n-- Keep the picker floating and centered\n'
                'hl.window_rule({ match = { class = "latex-picker" }, '
                'float = true, center = true })\n'
            )
            text = (
                f"Add these lines to {target_display}:\n\n"
                f'hl.bind("{binding}", hl.dsp.exec_cmd("{command}"))\n'
            )
            if include_rule:
                text += rule
            text += "\nThen run: hyprctl reload"
        else:
            # Hyprland's classic syntax separates modifiers and key with a comma.
            parts = binding.split(" + ")
            key = parts[-1]
            modifiers = " ".join(parts[:-1])
            text = (
                f"Add these lines to {target_display}:\n\n"
                f"bind = {modifiers}, {key}, exec, {command}\n"
            )
            if include_rule:
                text += (
                    "windowrulev2 = float,class:^(latex-picker)$\n"
                    "windowrulev2 = center,class:^(latex-picker)$\n"
                )
            text += "\nThen run: hyprctl reload"
        return text

    if "GNOME" in session.desktop.upper():
        return (
            "GNOME on Wayland does not let applications grab global keys. Register a\n"
            "custom shortcut (Settings → Keyboard → View and Customise Shortcuts →\n"
            "Custom Shortcuts → +), or run:\n\n"
            "  gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"
            "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/latex-picker/ "
            f"name 'LaTeX Picker'\n"
            "  gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"
            "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/latex-picker/ "
            f"command '{command}'\n"
            "  gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"
            "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/latex-picker/ "
            "binding '<Super><Shift>l'\n\n"
            "You must also add the path to the existing custom-keybindings list; see\n"
            "README.md for the complete command."
        )

    if "KDE" in session.desktop.upper() or "PLASMA" in session.desktop.upper():
        return (
            "Open System Settings → Keyboard → Shortcuts → Custom Shortcuts, create\n"
            "a New → Global Shortcut → Command/URL, set the trigger to Super+Shift+L\n"
            f"and the command to {command}.  KDE stores this in kglobalshortcutsrc."
        )

    return (
        "Bind a desktop-environment shortcut to run:\n\n"
        f"  {command}\n\n"
        "GNOME/KDE: Settings → Keyboard → Custom Shortcuts.\n"
        "Hyprland: add a bind line and run hyprctl reload.\n"
        "Sway: bindsym Super+Shift+l exec latex-picker\n\n"
        "The application intentionally does not grab keys itself: on Wayland that\n"
        "is not permitted, and delegating to the compositor is reliable everywhere."
    )
