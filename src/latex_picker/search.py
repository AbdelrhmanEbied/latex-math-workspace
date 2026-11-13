"""Fast, dependency-free fuzzy search over the snippet library."""

from __future__ import annotations

import re
from functools import lru_cache

from .models import Library, Snippet

_TOKEN_RE = re.compile(r"[^\s]+")


def normalise(value: str) -> str:
    return value.casefold().strip()


@lru_cache(maxsize=4096)
def _subsequence_score(needle: str, haystack: str) -> float:
    """Score a subsequence match, favouring consecutive and word-start hits."""
    if not needle:
        return 0.0
    start = haystack.find(needle)
    if start >= 0:
        score = 40.0 + 10.0 * (len(needle) / max(1, len(haystack)))
        if start == 0:
            score += 25.0
        elif haystack[start - 1] in " _-\\{}().,":
            score += 12.0
        return score
    position = 0
    score = 0.0
    streak = 0
    last_index = -2
    for char in needle:
        found = haystack.find(char, position)
        if found < 0:
            return 0.0
        if found == last_index + 1:
            streak += 1
            score += 4.0 + streak * 2.0
        else:
            streak = 0
            score += 1.0
        if found == 0 or haystack[found - 1] in " _-\\{}().,":
            score += 3.0
        last_index = found
        position = found + 1
    return score


class SearchEngine:
    def __init__(self, library: Library) -> None:
        self.library = library
        self._category_names = {
            category.id: normalise(f"{category.name} {category.description}")
            for category in library.categories
        }
        self._prepared: dict[str, tuple[str, tuple[str, ...]]] = {}
        for snippet in library.snippets:
            title = normalise(snippet.title)
            keywords = normalise(" ".join(snippet.keywords))
            latex = normalise(snippet.latex)
            description = normalise(snippet.description)
            category = self._category_names.get(snippet.category, "")
            self._prepared[snippet.id] = (title, (keywords, latex, description, category))

    def _score(self, snippet: Snippet, token: str) -> float:
        title, fields = self._prepared[snippet.id]
        keywords, latex, description, category = fields
        score = 0.0
        if title == token:
            score += 220.0
        elif title.startswith(token):
            score += 150.0
        elif token in title:
            score += 110.0
        if any(keyword == token for keyword in snippet.keywords):
            score += 100.0
        if token in keywords:
            score += 70.0
        if token in latex:
            score += 55.0
        if token in description:
            score += 30.0
        if token in category:
            score += 16.0
        if score == 0.0:
            score += _subsequence_score(token, title) * 1.6
            if score == 0.0:
                score += _subsequence_score(token, keywords) * 0.7
        return score

    def search(
        self,
        query: str,
        category: str | None = None,
        *,
        allowed_ids: list[str] | None = None,
    ) -> list[Snippet]:
        """Return snippets matching every token of *query*.

        ``category`` filters to one category.  ``allowed_ids`` (used by the
        Recent view) preserves the given order when the query is empty.
        """
        query = normalise(query)
        tokens = _TOKEN_RE.findall(query)
        if allowed_ids is not None:
            pool = [self.library.snippet(ident) for ident in allowed_ids]
            candidates = [snippet for snippet in pool if snippet is not None]
        else:
            candidates = list(self.library.snippets)
        if category:
            candidates = [s for s in candidates if s.category == category]
        if not tokens:
            if allowed_ids is not None:
                return candidates
            return candidates

        results: list[tuple[float, int, Snippet]] = []
        phrase_bonus = 60.0 if len(tokens) > 1 else 0.0
        for order, snippet in enumerate(candidates):
            scores = [self._score(snippet, token) for token in tokens]
            if any(score <= 0.0 for score in scores):
                continue
            total = sum(scores)
            title = self._prepared[snippet.id][0]
            if phrase_bonus and query in title:
                total += phrase_bonus
            if len(tokens) == 1 and title.startswith(tokens[0]):
                total += 10.0
            results.append((total, order, snippet))
        results.sort(key=lambda item: (-item[0], item[1]))
        return [snippet for _score_value, _order, snippet in results]
