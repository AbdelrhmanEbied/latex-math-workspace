"""Configuration, paths and persisted recent snippets.

Everything is deliberately optional: the application must start with no config
file at all.  Unknown keys are ignored so newer configs do not break old builds.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

APP_ID = "latex-picker"
APP_NAME = "LaTeX Picker"
VERSION = "2.0.0"
MODES = ("picker", "editor", "calculator", "graph", "matrix")


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser() / APP_ID


def state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", "~/.local/state")).expanduser() / APP_ID


def config_path() -> Path:
    return config_dir() / "config.json"


def state_path() -> Path:
    return state_dir() / "state.json"


def workspace_path() -> Path:
    return state_dir() / "workspace.json"


def default_custom_snippets_path() -> Path:
    return config_dir() / "snippets.json"


@dataclass
class AppConfig:
    theme: str = "auto"                 # auto | dark | light
    width: int = 1180
    height: int = 780
    close_on_blur: bool = True
    show_preview: bool = True
    preview_renderer: str = "auto"      # auto | unicode
    font_scale: float = 1.0
    custom_snippets: str | None = None  # expanded lazily
    show_recent: bool = True
    recent_limit: int = 12
    start_mode: str = "last"            # last | picker | editor | calculator | graph | matrix
    tools_close_on_blur: bool = False   # close on focus loss while a tool tab is open

    def normalised(self) -> AppConfig:
        theme = self.theme if self.theme in {"auto", "dark", "light"} else "auto"
        renderer = self.preview_renderer if self.preview_renderer in {"auto", "unicode"} else "auto"
        width = min(1600, max(520, int(self.width)))
        height = min(1000, max(360, int(self.height)))
        scale = min(1.6, max(0.8, float(self.font_scale)))
        limit = min(30, max(1, int(self.recent_limit)))
        start = self.start_mode if self.start_mode in ("last",) + MODES else "last"
        return AppConfig(
            theme=theme,
            width=width,
            height=height,
            close_on_blur=bool(self.close_on_blur),
            show_preview=bool(self.show_preview),
            preview_renderer=renderer,
            font_scale=scale,
            custom_snippets=self.custom_snippets,
            show_recent=bool(self.show_recent),
            recent_limit=limit,
            start_mode=start,
            tools_close_on_blur=bool(self.tools_close_on_blur),
        )


@dataclass
class State:
    recent: list[str] = field(default_factory=list)


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def load_config(path: str | Path | None = None) -> tuple[AppConfig, list[str]]:
    """Load config, returning defaults on missing/invalid values."""
    warnings: list[str] = []
    config = AppConfig()
    target = Path(path).expanduser() if path else config_path()
    if not target.exists():
        return config.normalised(), warnings
    try:
        with target.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("top-level value must be an object")  # noqa: TRY004
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        warnings.append(f"Config ignored ({target}): {exc}")
        return config.normalised(), warnings

    known = {item.name for item in fields(AppConfig)}
    for key, value in data.items():
        if key not in known:
            warnings.append(f"Unknown config key ignored: {key}")
            continue
        setattr(config, key, value)
    if config.custom_snippets is None and default_custom_snippets_path().exists():
        config.custom_snippets = str(default_custom_snippets_path())
    return config.normalised(), warnings


def load_state() -> State:
    target = state_path()
    try:
        with target.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        recent = data.get("recent", [])
        if not isinstance(recent, list):
            return State()
        clean = [item for item in recent if isinstance(item, str)]
        return State(recent=clean[:30])
    except (OSError, json.JSONDecodeError, AttributeError):
        return State()


def save_state(state: State) -> None:
    try:
        _atomic_write_json(state_path(), {"recent": state.recent[:30]})
    except OSError:
        # Recent items are a convenience; never let a read-only home break copy.
        pass


def record_recent(state: State, snippet_id: str, limit: int) -> None:
    state.recent = [snippet_id] + [item for item in state.recent if item != snippet_id]
    del state.recent[limit:]
    save_state(state)


def load_workspace() -> dict[str, Any]:
    try:
        with workspace_path().open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_workspace(data: dict[str, Any]) -> None:
    try:
        _atomic_write_json(workspace_path(), data)
    except (OSError, TypeError, ValueError):
        pass


def example_config() -> dict[str, Any]:
    return {
        "theme": "auto",
        "width": 1180,
        "height": 780,
        "close_on_blur": True,
        "show_preview": True,
        "preview_renderer": "auto",
        "font_scale": 1.0,
        "custom_snippets": "~/.config/latex-picker/snippets.json",
        "show_recent": True,
        "recent_limit": 12,
        "start_mode": "last",
        "tools_close_on_blur": False,
    }
