# Anchor block catalog from `示例.dxf`


## Candidate source blocks

| Function | Source block | Observed content / notes |
|---|---|---|
| M-anchor side/shape | `M型锚固件-左` | 41 entities: lines, arcs and circles; local bounds about -2.28,-62.5 to 71.55,62.5 |
| M-anchor body | `M形锚固件本体` | 25 entities: 23 lines and 2 circles; bounds about -68.2,-40 to 68.2,40 |
| Quick-insert side view | `快插锚固件-右视图` | 14 entities: lines and arcs; source coordinates are offset far from origin, so normalize only after inspecting its block transform |
| Side-insert part 1 | `旁插锚固件1` | Two closed polylines and one nested anonymous insert |
| Side-insert part 2 | `旁插锚固件2` | Two closed polylines and one nested anonymous insert; raw local coordinates are far from origin |
| Side-insert assembly | `旁插锚固件3` | Three nested inserts including side-insert pin geometry |
| Side-insert side view | `旁插锚固件-侧面` | Nested quick-insert right-side geometry plus a thin rectangular strip |
| Side-insert pin | `旁插锚固件插针` | Four open polylines, including a bulged segment |
| Welded diamond | `焊钉-菱形` | Spline/arc/circle/line geometry and nested center mark |
| Bolt families | `六角头螺栓`, `六角头尖头不带丝`, `螺栓六角头长` | Separate bolt representations; do not merge into an anchor type without confirming intended use |

## Board-face anchor-symbol sources

The board-face blocks contain nested anonymous inserts that can be recursively decomposed to visible vector geometry:

- M-shaped board-face symbol: nested insert under `动态模块-M形锚固件-夹板面` (`*U179` chain), flattened bounds about 120×70.88 units.
- Diamond board-face symbol: nested insert under `动态模块-菱形锚固件-夹板面` (`*U155` chain), flattened bounds about 21×20 units.
- Side-insert board-face nested geometry: nested insert under `动态模块-旁插锚固件-夹板面` (`*U217` chain), flattened bounds about 146×97.5 units. The preview resembles a multi-hole/pattern representation, not one isolated anchor symbol; do not use it as a single anchor marker without confirmation.
- Welded-diamond board-face nested geometry: nested insert under `动态模块-焊接菱形锚固件2-夹板面` (`*U298` chain), flattened bounds about 32×173 units. It is strongly elongated and may be a side/profile representation; do not use it as a plan-view symbol without confirming orientation.

## Important limits

- The quick-insert right-side view is not a confirmed quick-insert board opening template.
- The current implementation directly maps only the M-shaped and diamond nested representations to board-face symbols. Side-insert and welded-diamond nested geometry is catalogued but deliberately not auto-used until its role and orientation are confirmed.
- The source DXF includes anonymous dynamic-block state blocks. Recursively flattening the default nested insert is useful for a visible symbol, but does not prove that every dynamic visibility state or action parameter has been recovered.
- Preserve anchor symbols as editable vector geometry. Avoid replacing them with generic dots/icons in final production drawings.

## Additional view-profile mappings extracted from module blocks

| Anchor type | Front-view source geometry | Side-view source geometry | Status |
|---|---|---|---|
| M-shaped | `*U168` nested in `动态模块-M形锚固件-上` (about 136×220 source units) | `*U324` nested in `动态模块-M形锚固件-膨胀面` (about 138.494×240) | Used for the expansion-face side view |
| Diamond | `*U163` nested in `动态模块-菱形锚固件-上` (about 19.26×220) | `*U476` nested in `动态模块-菱形锚固件-膨胀面1`, scale `0.2291667` (about 18.333×220) | Used for the expansion-face side view |
| Quick insert | `快插锚固件-右视图` | Candidate right-side profile block | Front profile used provisionally; PDF BOM classification still needs confirmation |

## Quick-insert board-face opening candidate

`references/derived/quick_insert_opening_candidate.json` stores a vector contour traced from the B10 board-face mark in page 3 of `江阴铁包-11098-qf.pdf`. It contains one outer contour and four internal slot contours, approximately **22.578 × 16.933 mm** at the drawing's 1:10 scale.

The generator currently places this candidate automatically when the anchor type is quick insert and a physical board exists. This reproduces the visible B10/B11/B12 board-face mark, but the PDF does not explicitly label the mark as a machining opening. It is therefore flagged as **unconfirmed** and must be checked with the user before production use.
