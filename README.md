# RefracDraft

**Refractory Module 2D Drawing Generator** — 参数化生成耐火材料/陶瓷纤维模块二维加工图。

> The supplied DXF/PDF examples are the accepted golden-master drawing standard. RefracDraft must reproduce their drafting language and page composition; it is not a free redesign of the drawings.

## Current scope

- Pure 2D drawing; no 3D modeler.
- Three independent peer parameter groups: modules, boards, anchors, associated by module ID.
- Excel import and manual table entry.
- Generate-on-click preview; no live redraw while editing.
- A4 landscape, automatic pagination.
- Editable DXF and vector PDF export from one drawing model.
- Source-DXF board-face template extraction and reuse of anchor linework.
- Original A4 frame/title-block block import for DXF; original sample PDF title block/footer reused as vector content for PDF.

## Run from source

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -e ".[ui,dev]"

# Desktop UI
refrac-draft-gui

# CLI: generate DXF + PDF from JSON or Excel
refrac-draft generate examples/b2_positive_tap.json --outdir output
refrac-draft generate examples/jiangyin_b1_b4.json --outdir output

# Inspect the supplied reference DXF and create a block inventory
refrac-draft analyze-reference --dxf references/示例.dxf
```

If PySide6 is not installed, the CLI engine still works. The desktop UI is an optional dependency.

## Input model

The Excel workbook uses three worksheets:

1. `模块参数`
2. `夹板参数`
3. `锚固件参数`

The three groups are independent tables. Use `模块编号` to associate rows. Generate a starter workbook with `python scripts/create_excel_template.py --output examples/参数导入模板.xlsx`.

For explicit anchor positions, use JSON in the `锚固件坐标` cell, e.g.:

```json
[{"x_mm": 500, "y_mm": 180}, {"x_mm": 700, "y_mm": 180}]
```

## Non-negotiable geometry rules

- 普通: front + board-face views.
- 正敲: trapezoid on the front face; front trapezoid + board-face views.
- 侧敲: normal front + side trapezoid + board-face views.
- Every module gets a board-face view. If there is no physical board, put `无夹板` at the center of that view.
- Board outline follows the module's board-face geometry. Board material/thickness/presence/opening remain independent board parameters.
- Quick-insert uses a front-profile block from the source DXF and a B10-PDF-derived board-face opening candidate (outer contour + four slots, about 22.578×16.933 mm). The opening is automatically drawn but explicitly flagged as unconfirmed because the PDF does not label its machining meaning.
- Anchor positions can be explicit, evenly distributed, or fixed-spacing. Explicit segmented dimensions in the examples must be preserved.

## Golden-master rule

The examples are the output standard. Do not modernize, simplify, or redesign their view ordering, dimensions, labels, color usage, linework, BOM/detail block, title block, footer, or pagination. See `PROMPT.md`, `AGENTS.md`, and `docs/REFERENCE_ANALYSIS.md`.

## Known implementation limits (initial engine)

- Dynamic-block visibility/action metadata is proprietary; the current extractor uses visible block geometry and does not claim to recover every AutoCAD dynamic state.
- Quick-insert standard board-opening geometry remains unresolved.
- Page grouping currently follows the observed sample pattern (4 standard-width modules, 3 when an oversized/three-view group requires it); the general packing rules need more sample jobs.
- The initial UI provides editable parameter tables, Excel/JSON import, generate-on-click preview, and export actions. Spreadsheet-grade fill-handle/undo/redo refinements are planned after geometry and output validation.

## Standard edition branch

The `feat/standard-edition` branch builds a separate Windows x64 portable app, `RefracDraft-Standard.exe`. It keeps only the ordinary rectangular module, front taper (正敲), and side taper (侧敲) in its GUI. A module list, grouped property editor, and drawing preview share one window; the saved project still contains three independent parameter tables. Existing irregular inputs are rejected with a module-specific error instead of being silently replaced. The full edition remains on `feat/phase-1-core-engine`. See [Windows Standard guide](docs/WINDOWS_STANDARD.md).

