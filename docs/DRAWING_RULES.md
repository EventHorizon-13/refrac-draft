
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
- In the source diamond board-face block, the symbol center is 70 mm below the board's top edge. This offset is independent of the board-face length and is used by the Standard editor when the anchor layout is not an explicit-coordinate full-edition layout.
- The source M-shaped board-face symbol contains its own blue structural lines and red center/end marks. Preserve the source DXF ACI colors; do not draw an additional red/yellow marker at the symbol insertion center.
- The front-view marker style is anchor-type-specific: the M-shaped anchor uses the target marker; the quick-insert front profile uses a red cross marker.


## 10. Quick-insert front-profile scale

- The source DXF block `快插锚固件-右视图` has a visible profile envelope of approximately 25 × 100 units. The accepted B3/B10/B11/B12 PDF front profile measures approximately 18.35 × 220 mm. Apply independent X/Y scale factors (18.35/25 and 220/102) before placement; uniform scaling produces a visibly undersized symbol.


## 11. 正敲 / 侧敲梯形轮廓

- 正敲是正面梯形，侧敲是侧面梯形；不要把其中一类误画成另一类。
- 两类梯形的左右端面高度分别由左高、右高参数定义，两个长边都倾斜，不是“底边水平、只斜顶边”的直角梯形。
- 左右端面的中点处于同一水平中心线上。若左右高度为 H_L、H_R，整体高度 H=max(H_L,H_R)，左右底边抬高量分别为 (H-H_L)/2、(H-H_R)/2。
- 正敲只改变正面轮廓；侧敲只改变侧面轮廓。侧敲仍然需要正面、夹板面、侧面三个视图。

## 12. 锚固件与无锚固件膨胀面标记

- 侧视图的锚固件是一个代表性符号，不按锚固数量重复绘制。M型参考插入横向比例为 175/300；菱形按源块应用 0.916667 比例和 180° 旋转，并以「嵌入深度」为侧面外缘到符号左边缘的距离定位。
- 侧敲主视图必须绘制两条横贯模块宽度的小头轮廓线，位置按小头高度在总高度中居中确定。无锚固件时，再叠加四根渐短的膨胀面标记。
- 无锚固件模块的正面和侧面都需要四根渐短的膨胀面标记。正面沿用 `*U824` 的比例；侧面按同一纵向比例生成，并沿梯形顶边斜率倾斜。
