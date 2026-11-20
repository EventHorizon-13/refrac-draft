# Board-face template catalog from `示例.dxf`


The following 15 named blocks were found in the supplied DXF. Bounds and vertex counts below come from the largest `LWPOLYLINE` in each block. The block name is only an identifier; use the actual polyline geometry. Several blocks contain a nested anchor symbol insert, which is separate from the outer board-face outline.

| Template ID | Source block | Vertices | Approx. bounds (source units) | Nested insert |
|---|---|---:|---|---|
| `m-anchor` | `动态模块-M形锚固件-夹板面` | 4 | 0,-350 to 300,0 | `*U179` |
| `diamond-anchor` | `动态模块-菱形锚固件-夹板面` | 4 | 0,-350 to 300,0 | `*U155` |
| `no-anchor` | `动态模块-无锚固件-夹板面` | 4 | 0,-350 to 300,0 | none |
| `side-insert` | `动态模块-旁插锚固件-夹板面` | 4 | 0,-350 to 300,0 | `*U217` |
| `side-insert-irregular-1` | `动态模块-旁插锚固件-异形1-夹板面` | 8 | -3.42,-475.99 to 300,0 | `*U234` |
| `side-insert-irregular-2` | `动态模块-旁插锚固件-异形2-夹板面` | 6 | 0,-400 to 300,0 | `*U229` |
| `side-insert-irregular-3` | `动态模块-旁插锚固件-异形3-夹板面` | 6 | 0,-334.50 to 300.13,47.43 | `*U239` |
| `side-insert-irregular-4` | `动态模块-旁插锚固件-异形4-夹板面` | 6 | 0,-300 to 300,0 | `*U247` |
| `irregular-2` | `动态模块-异形2-夹板面` | 6 | 0,-400 to 300,0 | `*U130` |
| `irregular-3` | `动态模块-异形3-夹板面` | 6 | 0,-334.50 to 300.13,47.43 | `*U254` |
| `irregular-4` | `动态模块-异形4-夹板面` | 6 | 0,-300 to 300,0 | `*U260` |
| `irregular-5` | `动态模块-异形5-夹板面` | 8 | 0,-400 to 508.15,0 | `*U198` |
| `irregular-7` | `动态模块-异形7-夹板面` | 9 | -90.70,-300 to 478.90,0 | `*U266` |
| `no-anchor-irregular-5` | `动态模块-无锚固件-异形5-夹板面` | 8 | 0,-400 to 508.15,0 | none |
| `welded-diamond` | `动态模块-焊接菱形锚固件2-夹板面` | 4 | 0,-350 to 300,0 | `*U298` |

## Geometric observations

- The catalog is not a rectangle/trapezoid-only set. It contains step/notch profiles, offset profiles, and a large 508.15-unit wide stepped profile.
- `side-insert-irregular-1` has an 8-vertex stepped contour extending to about 476 units in its local Y range.
- `side-insert-irregular-2` and `irregular-2` share the same 6-vertex outer contour in the source DXF.
- `side-insert-irregular-3` and `irregular-3` share the same 6-vertex outer contour and include a positive-Y offset above the nominal origin.
- `side-insert-irregular-4` and `irregular-4` share the same 6-vertex contour.
- `irregular-5` and `no-anchor-irregular-5` share the same 8-vertex outer contour; one contains a nested insert and one does not.
- `irregular-7` is stored as an open `LWPOLYLINE` even though its first and last vertices coincide. Treat it as a closed outline after verifying the repeated endpoint; do not assume the DXF closed flag alone is authoritative.
- Some blocks contain `ATTDEF` and `DIMENSION` entities. The outer contour should be extracted independently; static dimensions and attribute placeholders should not be blindly scaled as if they were geometry.

## Implementation requirements

1. Preserve each source outline as an individual template.
2. Keep board-face template selection independent of the anchor parameter group.
3. Keep anchor symbol geometry independent of the board outline.
4. Support scaling/positioning only after validating how each template's notch offsets and anchor locations are intended to behave.
5. A physical board may be absent while the board-face view still has to be generated and labelled `无夹板`.
6. Quick-insert opening geometry is not established by this catalog; do not infer it from the right-side anchor block.
