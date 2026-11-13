"""Tests for the bundled snippet library and custom-library merging."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from latex_picker.library import load_library


class BundledLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library, cls.warnings = load_library()

    def test_library_has_expected_size(self) -> None:
        self.assertEqual(len(self.library.snippets), 266)
        self.assertEqual(len(self.library.categories), 12)
        self.assertEqual(self.warnings, [])

    def test_ids_and_categories_are_unique_and_known(self) -> None:
        ids = [snippet.id for snippet in self.library.snippets]
        self.assertEqual(len(ids), len(set(ids)))
        category_ids = {category.id for category in self.library.categories}
        for snippet in self.library.snippets:
            self.assertIn(snippet.category, category_ids, snippet.id)
            self.assertTrue(snippet.title.strip(), snippet.id)
            self.assertTrue(snippet.latex.strip(), snippet.id)

    def test_every_snippet_has_a_usable_preview(self) -> None:
        for snippet in self.library.snippets:
            self.assertTrue(snippet.preview.strip(), snippet.id)

    def test_categories_all_have_snippets(self) -> None:
        counts = self.library.counts_by_category()
        for category in self.library.categories:
            self.assertGreater(counts[category.id], 0, category.id)

    def test_snippet_lookup_and_counts(self) -> None:
        snippet = self.library.snippet("frac-basic")
        self.assertIsNotNone(snippet)
        self.assertEqual(snippet.latex, "\\frac{<numerator>}{<denominator>}")
        self.assertIsNone(self.library.snippet("does-not-exist"))
        self.assertEqual(
            sum(self.library.counts_by_category().values()),
            len(self.library.snippets),
        )

    def test_placeholders_are_preserved_in_source(self) -> None:
        latex = self.library.snippet("frac-basic").latex
        self.assertIn("<numerator>", latex)
        self.assertIn("<denominator>", latex)


class CustomLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "snippets.json"

    def write(self, payload) -> None:
        self.path.write_text(json.dumps(payload), encoding="utf-8")

    def test_new_category_and_snippet_are_merged(self) -> None:
        self.write(
            {
                "categories": [
                    {"id": "mine", "name": "Mine", "symbol": "★"}
                ],
                "snippets": [
                    {
                        "id": "mine-ft",
                        "category": "mine",
                        "title": "Fourier transform",
                        "latex": "\\hat{f}(\\xi)",
                        "keywords": "fourier transform",
                    }
                ],
            }
        )
        library, warnings = load_library(self.path)
        self.assertEqual(library.snippet("mine-ft").title, "Fourier transform")
        self.assertIsNotNone(library.category("mine"))
        self.assertEqual(len(library.snippets), 267)
        self.assertTrue(any("custom snippet" in warning.lower() for warning in warnings))

    def test_existing_snippet_can_be_overridden_in_place(self) -> None:
        self.write(
            [
                {
                    "id": "frac-basic",
                    "category": "fractions",
                    "title": "My fraction",
                    "latex": "\\frac{<a>}{<b>}",
                }
            ]
        )
        library, _ = load_library(self.path)
        self.assertEqual(library.snippet("frac-basic").title, "My fraction")
        self.assertEqual(len(library.snippets), 266)
        self.assertEqual(library.snippets[0].id, "frac-basic")

    def test_invalid_user_file_is_ignored_with_warning(self) -> None:
        self.write(
            {
                "snippets": [
                    {
                        "id": "bad",
                        "category": "nope",
                        "title": "Bad",
                        "latex": "x",
                    }
                ]
            }
        )
        library, warnings = load_library(self.path)
        self.assertEqual(len(library.snippets), 266)
        self.assertTrue(any("ignored" in warning.lower() for warning in warnings))

    def test_missing_user_file_warns_but_loads_builtin(self) -> None:
        library, warnings = load_library(self.path)
        self.assertEqual(len(library.snippets), 266)
        self.assertTrue(any("not found" in warning.lower() for warning in warnings))

    def test_invalid_json_is_ignored_with_warning(self) -> None:
        self.path.write_text("{not json", encoding="utf-8")
        library, warnings = load_library(self.path)
        # load_library treats an optional custom file as best-effort.
        self.assertEqual(len(library.snippets), 266)
        self.assertTrue(warnings)


if __name__ == "__main__":
    unittest.main()
