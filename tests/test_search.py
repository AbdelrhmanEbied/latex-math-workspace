"""Tests for weighted fuzzy search and filtering."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from latex_picker.library import load_library
from latex_picker.search import SearchEngine


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library, _ = load_library()
        cls.engine = SearchEngine(cls.library)

    def ids(self, query: str, category: str | None = None, *, allowed=None):
        return [snippet.id for snippet in self.engine.search(query, category, allowed_ids=allowed)]

    def test_empty_query_returns_entire_library(self) -> None:
        self.assertEqual(len(self.ids("")), len(self.library.snippets))

    def test_exact_title_ranks_first(self) -> None:
        self.assertEqual(self.ids("Fraction")[0], "frac-basic")

    def test_search_is_case_insensitive(self) -> None:
        self.assertEqual(self.ids("FRACTION")[0], "frac-basic")

    def test_latex_command_search(self) -> None:
        results = self.ids("\\partial")
        self.assertIn("frac-partial", results)

    def test_placeholder_text_is_searchable(self) -> None:
        self.assertIn("frac-basic", self.ids("numerator"))

    def test_every_token_must_match(self) -> None:
        results = self.ids("partial derivative")
        self.assertTrue(results)
        self.assertIn("frac-partial", results)
        self.assertEqual(self.ids("partial zzzznotfound"), [])

    def test_category_filter(self) -> None:
        results = self.ids("alpha", "greek")
        self.assertTrue(results)
        self.assertTrue(
            all(self.library.snippet(item).category == "greek" for item in results)
        )

    def test_recent_order_is_preserved(self) -> None:
        allowed = ["op-nabla", "frac-basic", "greek-alpha"]
        self.assertEqual(self.ids("", allowed=allowed), allowed)

    def test_recent_filter_still_searches(self) -> None:
        allowed = ["op-nabla", "frac-basic", "greek-alpha"]
        self.assertEqual(self.ids("nabla", allowed=allowed), ["op-nabla"])
        self.assertEqual(self.ids("not-there", allowed=allowed), [])

    def test_no_match_returns_empty(self) -> None:
        self.assertEqual(self.ids("qqqqzzzz"), [])

    def test_results_have_no_duplicates(self) -> None:
        results = self.ids("a")
        self.assertEqual(len(results), len(set(results)))

    def test_fuzzy_subsequence_match(self) -> None:
        self.assertTrue(self.ids("frctn"))


if __name__ == "__main__":
    unittest.main()
