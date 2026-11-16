# Initial Reference Analysis

This is an initial index of findings from the reference materials. It is not a substitute for Codex re-opening and inspecting every original file after it is added to `references/`.

## 1. DXF: `示例.dxf`

Initial structural inspection of the supplied original found:

- DXF version: AC1032 (AutoCAD 2018).
- Modelspace entities: 236.
- Block definitions: 733.
- Modelspace INSERT entities: 136.

Observed layer names include:

- `0`
- `Defpoints`
- `9`
- `1轮廓实线层`
- `a标注`
- `中心线层`
- `center`
- `STEELCASE`
- `剖面线`
- `00-陶瓷钉`
- `不打印`
- `尺寸线层`

The file contains named blocks related to M-shaped anchors, diamond anchors, side-insert anchors, quick-insert side view, no-anchor mark, normal module views, 正敲 views, 侧敲 views, multiple irregular board-face views, A4/A3/A2/A1 frames, and title blocks.

Important candidate board-face block names found in the source include:

- `动态模块-M形锚固件-夹板面`
- `动态模块-菱形锚固件-夹板面`
- `动态模块-无锚固件-夹板面`
- `动态模块-旁插锚固件-夹板面`
- `动态模块-旁插锚固件-异形1-夹板面`
- `动态模块-旁插锚固件-异形2-夹板面`
- `动态模块-旁插锚固件-异形3-夹板面`
- `动态模块-旁插锚固件-异形4-夹板面`
- `动态模块-异形2-夹板面`
- `动态模块-异形3-夹板面`
- `动态模块-异形4-夹板面`
- `动态模块-异形5-夹板面`
- `动态模块-异形7-夹板面`
- `动态模块-无锚固件-异形5-夹板面`
- `动态模块-焊接菱形锚固件2-夹板面`

These names are only discovery hints. Codex must inspect each block's actual geometry, extents, base point, nested inserts, attributes, orientation, and dimensions before building the catalog.

Potential anchor-related block names include `M型锚固件-左`, `快插锚固件-右视图`, `旁插锚固件1`, `旁插锚固件2`, `旁插锚固件3`, `旁插锚固件插针`, `无锚固件标志`, `M形锚固件本体`, `焊钉-菱形`, and bolt blocks.

## 2. PDF: `江阴铁包-11098-qf.pdf`

- Four pages.
- Modules B1–B13.
- Useful examples include trapezoidal/small-head modules, rectangular modules, single-anchor and two-anchor layouts, different anchor lengths, explicit anchor positioning dimensions, and repeated A4 landscape module panels.
- B6 and B7 show two anchors and explicit segmented positioning dimensions. Their anchor positions must not be replaced with a generic equal-spacing rule.
- B10–B13 provide additional examples of anchor positioning and different module sizes.
- The module production quantity in the BOM is not the number of anchors in an individual module.

## 3. PDF: `上下盖_3100_2100_400_640_0930_q-02.pdf`

- One page.
- Modules S1–S4.
- S1 and S2 have no anchor; S3 and S4 use 304 diamond anchors M8.
- The board-face dimensions are not always the same as the module front dimensions.
- The drawing contains a likely S2 view-label/BOM-label discrepancy: visually, one view appears to say S1 while the BOM says S2. Keep this as an unresolved source discrepancy; do not silently correct the original.

## 4. Supplemental images

- `B2_正敲示例.png`: front face is trapezoidal; board-face view is the second view; two views total.
- `A1_侧敲示例.png`: front face is rectangular; side face is trapezoidal; board-face view is the third view; three views total.

## 5. Mandatory next analysis

After the binary files are committed to this repository, Codex must:
1. Re-open all five source files.
2. Generate preview sheets for the DXF's relevant named blocks.
3. Build a board-face template catalog with actual thumbnails.
4. Build an anchor template catalog with actual thumbnails.
5. Record drawing rules with source page/block references.
6. Separate confirmed source facts, geometric interpretations, and items needing user confirmation.


## 6. Golden-master status of the examples

The supplied examples are the accepted final drawing output standard. They are not loose style inspiration. Implementation must closely reproduce their actual drafting language and page composition.

- The DXF is the primary CAD source for reusable vector geometry, blocks, layers, linetypes, text/dimension styles, frames, and title blocks.
- The PDFs are the primary final-output source for page composition, view ordering, dimensions and annotation placement, module panels, BOM/detail presentation, title blocks, and pagination.
- The B2 正敲 and A1 侧敲 images clarify the intended geometry and must be followed for those two types.
- Use original sample dimensions and properties to build golden-master input datasets. Generate output and compare page-by-page and view-by-view against the supplied references.
- A successful export alone is not acceptance. Fidelity of geometry, annotations, text, details, frames, title blocks, and layout is part of functional correctness.
