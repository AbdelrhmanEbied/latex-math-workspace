"""Tests for configuration, state and recent-item persistence."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from latex_picker.config import (
    AppConfig,
    State,
    config_dir,
    config_path,
    example_config,
    load_config,
    load_state,
    record_recent,
    save_state,
    state_path,
)


class ConfigEnvironment(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.env = patch.dict(
            os.environ,
            {
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_STATE_HOME": str(root / "state"),
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def write_config(self, payload) -> Path:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path


class ConfigTests(ConfigEnvironment):
    def test_defaults_are_normalised(self) -> None:
        config, warnings = load_config()
        self.assertEqual(warnings, [])
        self.assertEqual(config.theme, "auto")
        self.assertTrue(config.close_on_blur)
        self.assertEqual((config.width, config.height), (1180, 780))

    def test_paths_respect_xdg_variables(self) -> None:
        self.assertEqual(config_path(), config_dir() / "config.json")
        self.assertTrue(str(config_path()).startswith(self.temp.name))

    def test_valid_config_is_loaded(self) -> None:
        self.write_config({"theme": "light", "width": 1000, "font_scale": 1.2})
        config, warnings = load_config()
        self.assertEqual(warnings, [])
        self.assertEqual(config.theme, "light")
        self.assertEqual(config.width, 1000)
        self.assertAlmostEqual(config.font_scale, 1.2)

    def test_unknown_keys_warn_and_are_ignored(self) -> None:
        self.write_config({"theme": "dark", "future_option": 42})
        config, warnings = load_config()
        self.assertEqual(config.theme, "dark")
        self.assertTrue(any("future_option" in warning for warning in warnings))

    def test_values_are_clamped(self) -> None:
        self.write_config(
            {
                "theme": "neon",
                "width": 10,
                "height": 99999,
                "font_scale": 9,
                "recent_limit": 0,
                "preview_renderer": "magic",
            }
        )
        config, _ = load_config()
        self.assertEqual(config.theme, "auto")
        self.assertEqual(config.width, 520)
        self.assertEqual(config.height, 1000)
        self.assertEqual(config.font_scale, 1.6)
        self.assertEqual(config.recent_limit, 1)
        self.assertEqual(config.preview_renderer, "auto")

    def test_malformed_json_falls_back_to_defaults(self) -> None:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken", encoding="utf-8")
        config, warnings = load_config()
        self.assertTrue(warnings)
        self.assertEqual(config, AppConfig().normalised())

    def test_example_config_is_loadable(self) -> None:
        self.write_config(example_config())
        config, warnings = load_config()
        self.assertEqual(warnings, [])
        self.assertIsInstance(config.custom_snippets, str)


class StateTests(ConfigEnvironment):
    def test_missing_state_returns_empty(self) -> None:
        self.assertEqual(load_state(), State())

    def test_state_round_trip(self) -> None:
        state = State(recent=["frac-basic", "op-nabla"])
        save_state(state)
        self.assertTrue(state_path().exists())
        self.assertEqual(load_state().recent, state.recent)

    def test_record_recent_moves_to_front_and_deduplicates(self) -> None:
        state = State(recent=["a", "b", "c"])
        record_recent(state, "b", 10)
        self.assertEqual(state.recent, ["b", "a", "c"])

    def test_record_recent_respects_limit(self) -> None:
        state = State(recent=["a", "b", "c"])
        record_recent(state, "d", 2)
        self.assertEqual(state.recent, ["d", "a"])

    def test_malformed_state_is_ignored(self) -> None:
        path = state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json", encoding="utf-8")
        self.assertEqual(load_state(), State())

    def test_state_file_is_valid_json(self) -> None:
        save_state(State(recent=["frac-basic"]))
        payload = json.loads(state_path().read_text(encoding="utf-8"))
        self.assertEqual(payload["recent"], ["frac-basic"])


if __name__ == "__main__":
    unittest.main()
