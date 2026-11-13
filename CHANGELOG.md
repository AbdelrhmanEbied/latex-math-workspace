# Changelog

## 2.0.0 — 2026-11-13

The popup becomes a five-tab math workspace.

- **Editor**: ~490 clickable symbol/structure buttons in 13 palettes, ⬚
  placeholders with Tab navigation, live preview with error hints, matrix
  builder, 8 copy formats, copy as PNG/Unicode, history, favorites and saving
  equations as Picker snippets.
- **Calculator**: exact SymPy CAS with a clickable keypad, equations, systems,
  inequalities, calculus, series, variables and user functions, RAD/DEG, LaTeX
  input, copyable history cards.
- **Graph**: explicit, parametric, polar, implicit and inequality plots,
  auto-sliders, roots/extrema/intersections/integrals/tangents, PNG/SVG/PDF and
  pgfplots export.
- **Matrix**: grid editor, manual row operations with undo/redo, step-by-step
  REF/RREF/inverse/determinant, Ax=b classification, eigen-analysis and
  LU/QR/Cholesky/SVD/Jordan decompositions, matrix expressions.
- **Renderer**: real LaTeX when available, otherwise mathtext plus natively
  drawn matrices, `cases`, `array` and `aligned` blocks.
- **Picker**: `Shift+Enter` / right-click inserts a snippet into the Editor.
- Ctrl+1…5 tab switching, per-tab state persisted across launches,
  `--mode` command-line option, `start_mode` and `tools_close_on_blur` config.
- Default window size is now 1180×780.

## 1.0.0

- Searchable popup of 266 LaTeX snippets with previews, categories and Recent.
