"""Loading, validation and merging of the snippet library."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

from .latex_preview import compact_preview, detailed_preview
from .models import Category, Library, Snippet


class LibraryError(Exception):
    """Raised when the built-in or user library cannot be loaded."""


def _read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise LibraryError(f"Snippet file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise LibraryError(f"Invalid JSON in {path}: line {exc.lineno}: {exc.msg}") from exc
    except OSError as exc:
        raise LibraryError(f"Cannot read {path}: {exc}") from exc


def _as_string_list(value: Any, field_name: str, snippet_id: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(value.split())
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise LibraryError(
        f"Snippet {snippet_id!r}: {field_name!r} must be a string or a list of strings"
    )


def _parse_categories(raw: Any) -> list[Category]:
    if not isinstance(raw, list):
        raise LibraryError("'categories' must be a list")
    categories: list[Category] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise LibraryError("Every category must be an object")
        ident = item.get("id")
        name = item.get("name")
        symbol = item.get("symbol", "•")
        description = item.get("description", "")
        if not isinstance(ident, str) or not ident.strip():
            raise LibraryError("Every category needs a non-empty string 'id'")
        if not isinstance(name, str) or not name.strip():
            raise LibraryError(f"Category {ident!r} needs a non-empty 'name'")
        if ident in seen:
            raise LibraryError(f"Duplicate category id: {ident}")
        if not isinstance(symbol, str) or not symbol:
            symbol = "•"
        if not isinstance(description, str):
            description = ""
        seen.add(ident)
        categories.append(Category(ident, name.strip(), symbol, description))
    return categories


def _parse_snippets(raw: Any, valid_categories: set[str], *, origin: str) -> list[Snippet]:
    if not isinstance(raw, list):
        raise LibraryError(f"{origin}: 'snippets' must be a list")
    snippets: list[Snippet] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        where = f"{origin}, entry {index + 1}"
        if not isinstance(item, dict):
            raise LibraryError(f"{where}: every snippet must be an object")
        ident = item.get("id")
        category = item.get("category")
        title = item.get("title")
        latex = item.get("latex")
        if not isinstance(ident, str) or not ident.strip():
            raise LibraryError(f"{where}: missing non-empty string 'id'")
        ident = ident.strip()
        if ident in seen:
            raise LibraryError(f"{where}: duplicate snippet id {ident!r}")
        if not isinstance(category, str) or category not in valid_categories:
            raise LibraryError(f"{where} ({ident}): unknown category {category!r}")
        if not isinstance(title, str) or not title.strip():
            raise LibraryError(f"{where} ({ident}): missing non-empty 'title'")
        if not isinstance(latex, str) or not latex.strip():
            raise LibraryError(f"{where} ({ident}): missing non-empty 'latex'")
        description = item.get("description", "")
        if not isinstance(description, str):
            description = ""
        keywords = _as_string_list(item.get("keywords"), "keywords", ident)
        preview = item.get("preview")
        if not isinstance(preview, str) or not preview.strip():
            preview = compact_preview(latex)
        else:
            preview = preview.strip()
        # Validate the detail preview once so a broken converter shows up in
        # tests rather than at hover time.
        detailed_preview(latex)
        seen.add(ident)
        snippets.append(
            Snippet(
                id=ident,
                category=category,
                title=title.strip(),
                latex=latex.strip(),
                description=description.strip(),
                keywords=keywords,
                preview=preview,
            )
        )
    return snippets


def load_library(custom_path: str | Path | None = None) -> tuple[Library, list[str]]:
    """Load the bundled library and optionally merge a user library.

    Returns the library and a list of human-readable warnings (for example a
    malformed optional user file).
    """
    warnings: list[str] = []
    try:
        data_file = resources.files("latex_picker.data").joinpath("snippets.json")
        raw = json.loads(data_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LibraryError(f"Bundled snippet library is unavailable: {exc}") from exc

    if not isinstance(raw, dict):
        raise LibraryError("Bundled snippet library must be an object")
    categories = _parse_categories(raw.get("categories"))
    valid = {category.id for category in categories}
    snippets = _parse_snippets(raw.get("snippets"), valid, origin="built-in library")
    snippet_order = {snippet.id: index for index, snippet in enumerate(snippets)}

    if custom_path:
        path = Path(custom_path).expanduser()
        if path.is_file():
            try:
                custom = _read_json(path)
                custom_categories: list[Category] = []
                if isinstance(custom, list):
                    custom_snippets_raw = custom
                elif isinstance(custom, dict):
                    if "categories" in custom:
                        custom_categories = _parse_categories(custom["categories"])
                    custom_snippets_raw = custom.get("snippets", [])
                else:
                    raise LibraryError("Custom library must be an object or a list")
                known = {category.id for category in categories}
                for category in custom_categories:
                    if category.id not in known:
                        categories.append(category)
                        known.add(category.id)
                merged = _parse_snippets(
                    custom_snippets_raw, known, origin=str(path)
                )
                by_id = {snippet.id: snippet for snippet in snippets}
                for snippet in merged:
                    if snippet.id in by_id:
                        # Override in place, preserving library order.
                        index = snippet_order[snippet.id]
                        snippets[index] = snippet
                    else:
                        snippet_order[snippet.id] = len(snippets)
                        snippets.append(snippet)
                if merged:
                    warnings.append(
                        f"Loaded {len(merged)} custom snippet(s) from {path}"
                    )
            except LibraryError as exc:
                warnings.append(f"Custom snippets ignored: {exc}")
        else:
            warnings.append(f"Custom snippet file not found: {path}")

    return Library(categories, snippets), warnings
