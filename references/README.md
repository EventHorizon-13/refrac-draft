# Reference Materials

This directory is the source-of-truth input for drawing-rule analysis and regression testing.

## Required original files

| File | Role | Status |
|---|---|---|
| `示例.dxf` | Main CAD reference: module views, board-face templates, anchor blocks, layers, title blocks | **Not yet uploaded** |
| `江阴铁包-11098-qf.pdf` | Four-page folded-module drawing set, B1–B13 | **Not yet uploaded** |
| `上下盖_3100_2100_400_640_0930_q-02.pdf` | One-page stacked-module drawing set, S1–S4 | **Not yet uploaded** |

## Supplemental geometry examples

| File | Role | Status |
|---|---|---|
| `B2_正敲示例.png` | 正敲：梯形在正面；正面 + 夹板面，共两个视图 | Uploaded |
| `A1_侧敲示例.png` | 侧敲：梯形在侧面；正面 + 侧面 + 夹板面，共三个视图 | Uploaded |

## Handling rules

- Preserve original filenames and bytes for the three source files.
- Never overwrite, modify, or re-save original source files.
- Do not treat a filename or block name as proof of geometry; inspect the actual drawing.
- PDFs must be inspected visually page by page if text extraction is incomplete.
- Record source-derived facts, visual interpretations, and unresolved questions separately.
- Use the DXF/PDF files as reference and regression inputs, not as generated output templates to copy wholesale.
