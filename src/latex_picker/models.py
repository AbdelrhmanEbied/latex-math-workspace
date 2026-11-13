"""Data model for categories and snippets."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    symbol: str
    description: str = ""


@dataclass(frozen=True)
class Snippet:
    id: str
    category: str
    title: str
    latex: str
    description: str = ""
    keywords: tuple[str, ...] = ()
    preview: str = ""

    def searchable_parts(self) -> tuple[str, ...]:
        return (self.title, self.latex, self.description, " ".join(self.keywords))


@dataclass
class Library:
    categories: list[Category] = field(default_factory=list)
    snippets: list[Snippet] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._by_id = {s.id: s for s in self.snippets}
        self._categories = {c.id: c for c in self.categories}

    def category(self, category_id: str) -> Category | None:
        return self._categories.get(category_id)

    def snippet(self, snippet_id: str) -> Snippet | None:
        return self._by_id.get(snippet_id)

    def counts_by_category(self) -> dict[str, int]:
        counts = {c.id: 0 for c in self.categories}
        for snippet in self.snippets:
            counts[snippet.category] = counts.get(snippet.category, 0) + 1
        return counts
