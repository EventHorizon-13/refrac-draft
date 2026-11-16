# Reference Materials

This directory is the source-of-truth input for drawing-rule analysis and golden-master regression tests.

| File | Role | Repository status |
|---|---|---|
| `示例.dxf` | Main CAD reference: module views, board-face templates, anchor blocks, layers, title blocks | Not yet committed; upload the supplied reference bundle |
| `江阴铁包-11098-qf.pdf` | Four-page folded-module drawing set, B1–B13 | Not yet committed; upload the supplied reference bundle |
| `上下盖_3100_2100_400_640_0930_q-02.pdf` | One-page stacked-module drawing set, S1–S4 | Not yet committed; upload the supplied reference bundle |
| `B2_正敲示例.png` | 正敲: trapezoid on front face; two views | Present in repository |
| `A1_侧敲示例.png` | 侧敲: trapezoid on side face; three views | Present in repository |

## Upload procedure

Upload `RefracDraft-reference-materials.zip` to the repository root and extract it from the repository root. The archive contains the original three source files under `references/` and a SHA-256 checksum list. Preserve original bytes and filenames.

## Handling rules

- Never modify or re-save original source files.
- Do not treat a filename or block name as proof of geometry; inspect actual entities.
- Inspect PDF pages visually if text extraction is incomplete.
- Record source-derived facts, visual interpretations, and unresolved questions separately.
- Use the DXF/PDF as reference and regression inputs, not as entire drawing pages to paste into output.
