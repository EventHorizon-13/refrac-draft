# Reference Materials

This directory is the source-of-truth input for drawing-rule analysis and regression testing.

## Required original files

| File | Role | Status |
|---|---|---|
| `示例.dxf` | Main CAD reference: module views, board-face templates, anchor blocks, layers, title blocks | Awaiting binary upload |
| `江阴铁包-11098-qf.pdf` | Four-page folded-module drawing set, B1–B13 | Awaiting binary upload |
| `上下盖_3100_2100_400_640_0930_q-02.pdf` | One-page stacked-module drawing set, S1–S4 | Awaiting binary upload |

## Supplemental geometry examples

| File | Role | Status |
|---|---|---|
| `B2_正敲示例.png` | Clarifies that 正敲 has the trapezoid on the front face; two views | Awaiting binary upload |
| `A1_侧敲示例.png` | Clarifies that 侧敲 has the trapezoid on the side face; three views | Awaiting binary upload |

## Handling rules

- Preserve original filenames and bytes.
- Never overwrite, modify, or re-save source files.
- Do not treat a filename or block name as proof of geometry; inspect the actual drawing.
- PDFs must be inspected visually page by page if text extraction is incomplete.
- Record source-derived facts, visual interpretations, and unresolved questions separately.
- Use the DXF/PDF files as reference and regression inputs, not as generated output templates to copy wholesale.
