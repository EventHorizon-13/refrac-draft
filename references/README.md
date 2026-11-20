# Reference Materials

This directory is the source-of-truth input for drawing-rule analysis and golden-master regression tests.

| File | Role | Repository status |
|---|---|---|
| `示例.dxf` | Main CAD reference: module views, board-face templates, anchor blocks, layers, title blocks | Committed in repository; ready for local analysis |
| `江阴铁包-11098-qf.pdf` | Four-page folded-module drawing set, B1–B13 | Committed in repository; available to Codex and CI |
| `上下盖_3100_2100_400_640_0930_q-02.pdf` | One-page stacked-module drawing set, S1–S4 | Committed in repository; available to Codex and CI |
| `B2_正敲示例.png` | 正敲: trapezoid on front face; two views | Present in repository |
| `A1_侧敲示例.png` | 侧敲: trapezoid on side face; three views | Present in repository |

## Derived source geometry

- `derived/quick_insert_opening_candidate.json` is a vector contour candidate traced from the B10 board-face mark in the sample PDF. It is used provisionally for quick-insert board openings and is not yet a confirmed manufacturing standard.

## Handling rules

- The three original source files are tracked in this repository. Do not ask the user to upload them again.

- Never modify or re-save original source files.
- Do not treat a filename or block name as proof of geometry; inspect actual entities.
- Inspect PDF pages visually if text extraction is incomplete.
- Record source-derived facts, visual interpretations, and unresolved questions separately.
- Use the DXF/PDF as reference and regression inputs, not as entire drawing pages to paste into output.
