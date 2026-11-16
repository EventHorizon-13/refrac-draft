# Confirmed 2D Drawing Rules

This document records the requirements explicitly confirmed by the user. The three source files and the two supplementary images remain the primary drawing references.

## 1. Product workflow

Excel import or manual parameter entry → validate → user clicks Generate → 2D preview → DXF export + PDF export.

- 2D only.
- A4 landscape.
- Automatic pagination.
- Generate on click, not live redraw.

## 2. Three parallel parameter groups

Module, board, and anchor are three peer parameter groups. They share a module identifier but do not inherit or overwrite each other's parameters.

### Module
Contains module structure type, geometric type, front/side/board-face geometry, material, density, production quantity, and other module-specific properties.

### Board
Contains whether a physical board exists, material, thickness, quick-insert opening mode, and machining attributes.

Board outer contour matches the module's board-face geometry. Do not ask for a second independent board outline unless a future confirmed manufacturing rule requires it.

### Anchor
Contains presence, anchor type, material, thread/specification, length, count, layout mode, coordinates, hose size, and machining attributes.

## 3. Board-face view

Every module must have a board-face view, regardless of whether a physical board exists.

- With a board: draw the board using the module's board-face outline.
- Without a board: still draw the board-face view and put `无夹板` in its center.
- Board-face geometry has multiple irregular types. Build a reusable template catalog from the reference DXF.
- Quick-insert anchors may require a board opening. The anchor type selects the standard opening geometry and dimensions; users may switch to custom and edit it.

## 4. Normal / 正敲 / 侧敲 views

| Geometry type | Front view | Side view | Board-face view | Total |
|---|---|---|---|---:|
| Normal | Normal front | Not generated | Always generated | 2 |
| 正敲 | Front trapezoid | Not generated | Always generated | 2 |
| 侧敲 | Normal front | Side trapezoid | Always generated | 3 |

正敲 and 侧敲 are both trapezoidal modules. The distinction is the face on which the trapezoid appears.

## 5. Anchor layout

Support:
- Uniform distribution.
- Fixed spacing.
- Explicit coordinates.

Do not force all anchors to be uniformly distributed. Respect explicit dimensions in the source drawings. Anchor count and module production quantity are separate values.

## 6. Export

- DXF geometry, dimensions, text, blocks, and layers remain editable.
- PDF is A4 landscape and paginated.
- Both outputs derive from the same 2D drawing model.


## 7. 示例文件是最终成图黄金样板

示例文件不是仅供参考的灵感素材，而是用户认可的最终加工图样式和表达标准。生成的图纸必须尽可能忠实地复刻示例。

- DXF：作为 CAD 几何、图块、图层、线型、文字/尺寸样式、图框和标题栏的主要依据。
- PDF：作为最终视图组织、标注布局、文字层级、明细、页面构图、图框、标题栏和分页的主要依据。
- B2 正敲、A1 侧敲补充图片：用于明确两类梯形模块的梯形所在面和视图数量。
- 不得自行重新设计版式，不得随意删减标注、锚固件表达、夹板面异形、技术文字或明细。
- 必须以原始样本参数建立黄金样板回归测试，生成后逐页、逐视图与源文件核对。
- 输出必须是可编辑、可参数化生成的真实二维 DXF/PDF；不得把整页 PDF 图片贴进输出，也不得把整张 DXF 原样复制冒充生成。
- 用户明确纠正的规则优先于源文件中的偶然错误或冲突；冲突必须记录。
