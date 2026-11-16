# Implementation Status — Phase 1 foundation

## Implemented in the initial code foundation

- Python package structure and CLI entry point.
- Pydantic project model with three peer parameter tables: module, board, anchor.
- Separate geometry rules for 普通 / 正敲 / 侧敲.
- Explicit, equal, and fixed-spacing anchor layout modes.
- Read-only reference-DXF parser for the 15 named board-face templates.
- Recursive extraction and direct use of M-shaped and diamond front/side profiles, preserving source-DXF ACI/layer colors. Side-insert and welded-diamond nested geometry is catalogued but intentionally not auto-used until its role/orientation is confirmed.
- Sample-derived quick-insert board-face opening candidate is loaded from `references/derived/quick_insert_opening_candidate.json` and placed per anchor position.
- Generate-on-click drawing model and basic page packing.
- DXF export with millimetre units, editable vector geometry, SHX text style references, and imported A4 frame/title-block definitions from the reference DXF.
- PDF export as vector linework; title-block and footer strips are reused from the accepted sample PDF as vector PDF content.
- Chinese-header Excel importer with three worksheets.
- Optional PySide6 desktop shell with three editable parameter tables, JSON/Excel import, generated preview, and DXF/PDF export actions.
- Example parameter files for B2 正敲, A1 侧敲, and B1–B4 sample panels.

## Verified locally

- Unit tests pass for geometry separation, no-board view retention, peer parameter groups, irregular board-face catalog presence, and Chinese Excel headers.
- B2 正敲 generated PDF/DXF opens in the local PDF/DXF parsers.
- A1 侧敲 generates three views: front, side trapezoid, and board face.
- B1–B4 generates a four-panel A4 landscape page with the sample's title-block/footer vector strip.

## Not yet accepted as production-complete

- The current UI has not yet received full manual interaction testing on Windows.
- Dynamic-block action/lookup/visibility state recovery is not complete.
- Quick-insert board-face geometry is rendered from the B10 source mark as a candidate outline; confirm whether it is a machined opening or a plan symbol before production acceptance.
- Several anchor profile mappings and all B1–B13 / S1–S4 parameters still require page-by-page validation against the supplied samples.
- The current layout algorithm is an initial approximation, not a universal packing rule.
- PDF font/line-weight tuning and exact annotation spacing still need golden-master comparison.
- Undo/redo, fill-handle spreadsheet interactions, row duplication, and advanced batch editing are not yet implemented.

## Next phase

1. Build complete source block previews and verify every dynamic block state.
2. Map every anchor type to the correct front/side/board-face symbol and exact standard opening.
3. Transcribe B1–B13 and S1–S4 into golden-master input datasets with source-page references.
4. Compare generated output page-by-page and correct geometry, annotation placement, text hierarchy, title block and page packing.
5. Test the desktop UI on Windows with the actual sample workbook.


## B1-B4 source alignment corrections

- B1/B2/B4 M-shaped board-face anchor coordinates now use the source-block symbol center 35.4391501542 mm below the board top edge (Y=194.5608498458 for a 230 mm board face), instead of incorrectly placing the symbol center on the top edge.
- M-shaped and diamond board-face symbols preserve their source ACI colors; the duplicate insertion-point marker has been removed.
- Quick-insert front view uses a red cross marker, matching the B3 sample, instead of the yellow/red target marker used for M-shaped anchors.
- DXF export uses the view note as the board-face label rather than overlapping the module ID and note.
