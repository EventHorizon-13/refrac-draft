
## 8. Source-derived view profiles and opening candidates

- M-shaped front profile: `*U168` from `动态模块-M形锚固件-上`.
- Diamond front profile: `*U163` from `动态模块-菱形锚固件-上`.
- M-shaped side profile: `*U330` from `动态模块-侧敲-1`.
- Diamond side profile: `*U445` from `动态模块-侧敲-菱形-1`.
- Stacked no-anchor front marks: `*U824` nested in `动态模块-无锚固件-上`.
- Quick-insert profile: `快插锚固件-右视图` (provisional match for B3/B10/B11/B12).
- Quick-insert board-face opening: candidate traced from the B10 PDF mark, stored in `references/derived/quick_insert_opening_candidate.json`. The generator draws it automatically for quick-insert anchors when a physical board exists, but flags it as unconfirmed because the PDF does not explicitly identify the mark as a machined opening.


## 9. Anchor-symbol insertion coordinates and source colors

- Anchor `positions` are the geometric center coordinates used to place the corresponding symbol, not automatically the top-edge attachment point.
- In the source M-shaped board-face block, the symbol center is 35.4391501542 mm below the board's top edge. For B1/B2/B4 on a 230 mm-high board face, the center Y coordinate is therefore 194.5608498458 mm.
- The source M-shaped board-face symbol contains its own blue structural lines and red center/end marks. Preserve the source DXF ACI colors; do not draw an additional red/yellow marker at the symbol insertion center.
- The front-view marker style is anchor-type-specific: the M-shaped anchor uses the target marker; the quick-insert front profile uses a red cross marker.
