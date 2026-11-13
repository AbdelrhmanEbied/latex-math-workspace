"""Command line interface."""

from __future__ import annotations

import argparse
import os
import sys

from .config import (
    APP_NAME,
    VERSION,
    _atomic_write_json,
    config_path,
    default_custom_snippets_path,
    example_config,
    load_config,
    load_state,
)
from .environment import (
    detect_session,
    doctor_report,
    hyprland_rule_installed,
    shortcut_instructions,
)
from .library import LibraryError, load_library


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="latex-picker",
        description="Search and copy LaTeX mathematical notation from a popup.",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    parser.add_argument("--config", metavar="PATH", help="Use a specific config.json")
    parser.add_argument("--snippets", metavar="PATH", help="Merge a custom snippets JSON file")
    parser.add_argument("--theme", choices=["auto", "dark", "light"], help="Override theme")
    parser.add_argument("--font-scale", type=float, metavar="FACTOR", help="UI scale (0.8–1.6)")
    parser.add_argument("--width", type=int, help="Window width in logical pixels")
    parser.add_argument("--height", type=int, help="Window height in logical pixels")
    parser.add_argument("--no-preview", action="store_true", help="Disable the detail preview pane")
    parser.add_argument("--unicode-preview", action="store_true",
                        help="Use Unicode previews instead of matplotlib rendering")
    parser.add_argument("--no-blur-close", action="store_true",
                        help="Keep the popup open when it loses keyboard focus")
    parser.add_argument("--doctor", action="store_true",
                        help="Print environment and installation diagnostics")
    parser.add_argument("--shortcut-help", action="store_true",
                        help="Print global shortcut setup instructions")
    parser.add_argument("--print-config-path", action="store_true",
                        help="Print the config file path and exit")
    parser.add_argument("--write-config", action="store_true",
                        help="Write an example config file and exit")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite an existing config with --write-config")
    parser.add_argument("--mode", choices=["picker", "editor", "calculator", "graph", "matrix"],
                        help="Open a specific tab instead of the configured start mode")
    parser.add_argument("--debug", action="store_true", help="Print warnings to stderr")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.print_config_path:
        print(config_path())
        return 0

    if args.write_config:
        target = config_path()
        if target.exists() and not args.force:
            print(f"Config already exists: {target}", file=sys.stderr)
            print("Use --force to overwrite it.", file=sys.stderr)
            return 1
        _atomic_write_json(target, example_config())
        print(f"Wrote {target}")
        print(f"Optional custom snippets file: {default_custom_snippets_path()}")
        return 0

    if args.doctor:
        print(doctor_report())
        return 0

    if args.shortcut_help:
        print(shortcut_instructions(include_rule=True))
        return 0

    if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
        print(
            "No Wayland or X11 display found. This is a GUI application; run it "
            "inside a desktop session, or use --doctor.",
            file=sys.stderr,
        )
        return 2

    config, warnings = load_config(args.config)
    if args.theme:
        config.theme = args.theme
    if args.font_scale is not None:
        config.font_scale = args.font_scale
    if args.width:
        config.width = args.width
    if args.height:
        config.height = args.height
    if args.no_preview:
        config.show_preview = False
    if args.unicode_preview:
        config.preview_renderer = "unicode"
    if args.no_blur_close:
        config.close_on_blur = False
    config = config.normalised()

    snippets_path = args.snippets or config.custom_snippets
    try:
        library, library_warnings = load_library(snippets_path)
    except LibraryError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    warnings.extend(library_warnings)

    session = detect_session()
    if session.is_hyprland and not hyprland_rule_installed():
        warnings.append(
            "Hyprland window rule for class 'latex-picker' was not found. "
            "The picker may open tiled; run ./scripts/configure-shortcut.sh --apply "
            "or add the window rule from README.md."
        )

    if args.debug or warnings:
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)

    from .app import run

    state = load_state()
    return run(library, config, session, state, warnings, mode=args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
