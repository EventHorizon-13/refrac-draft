# Reference File Analysis — observed facts

The three supplied source files are the accepted output standard. This document records observations made by reopening the exact files in the repository. The originals are read-only inputs and must never be saved back by the application.

## 1. `references/示例.dxf`

### File and drawing structure

- Format: AutoCAD 2018 DXF (`AC1032`), code page/encoding reported by ezdxf as `gbk`.
- File size: 10,978,820 bytes.
- Model space: 236 top-level entities: 136 `INSERT`, 56 `DIMENSION`, 19 `TEXT`, 11 `MTEXT`, 12 `LWPOLYLINE`, and 2 `HATCH`.
- Block definitions: 733, including anonymous `*U...` blocks and `G$...` blocks.
- Layouts: `Model` (236 entities), `梯形块` (2 viewports), and `模块-01` (2 viewports).
- The model-space extents are approximately X=0..20209.19, Y=0..2948.92, Z=0..641.85. The model space is a multi-area reference drawing, not one simple module drawing.
- The file includes A4/A3/A2/A1 frame blocks and a reusable `标题栏` block. `图框-A4` has a 297×210 drawing-unit boundary. `标题栏` has a raw block extent of approximately 1200.38×303.58 and is inserted in the model space with a scale near 0.102.

### Layer and style observations

Observed layers include `0`, `Defpoints`, `9`, `1轮廓实线层`, `a标注`, `中心线层`, `center`, `STEELCASE`, `剖面线`, `00-陶瓷钉`, `不打印`, `尺寸线层`, and AutoCAD constraint/backup layers.

Text styles include `工程字` and `大字体`, both referencing `gbenor.shx` with `gbcbig.shx` as big font. Dimension styles include `_5`, `_10`, `_20`, `_25`, `_40`, `_100`, `_1`, `ISO-25`, `GB_尺寸`, and `Standard`.

The DXF contains AutoCAD dynamic-block data (`ACDB_BLOCKREPRESENTATION_DATA`) and associative-dimension data (`DIMASSOC`). ezdxf emits warnings that these proprietary objects are not fully preserved by its generic copy process. Therefore:

- Never open and save the original reference DXF as part of analysis or export.
- Extract visible geometry and source style information read-only.
- Treat dynamic block action/lookup behavior as a separate compatibility investigation. A named block's default visible geometry is not proof that all dynamic states have been captured.

### Useful block families

- Module/front-view families: `动态模块-M形锚固件-上`, `动态模块-无锚固件-上`, `动态模块-菱形锚固件-上`, `动态模块-侧敲-1`, `动态模块-侧敲-菱形-1`, `动态模块-M形锚固件-正敲-上`, `动态模块-菱形锚固件-正敲-上`, `动态模块-无锚固件-正敲-上`, `动态模块-旁插锚固件-上`, `动态模块-旁插锚固件-正敲-上`, and `动态模块-旁插-侧敲-1`.
- Board-face family: 15 named blocks are catalogued in `BOARD_FACE_CATALOG.md`.
- Anchor family: `M型锚固件-左`, `M形锚固件本体`, `快插锚固件-右视图`, `旁插锚固件1/2/3`, `旁插锚固件插针`, `旁插锚固件-侧面`, `焊钉-菱形`, and several bolt blocks.
- Sheet blocks: `图框-A4`, `图框-A3`, `图框-A2`, `图框-A1`, `标题栏`.

## 2. `references/江阴铁包-11098-qf.pdf`

- 4 pages, each 842×595 pt (A4 landscape).
- The page content is vector-heavy: approximately 3,714–6,591 vector drawing operations per page, plus four embedded raster image resources per page.
- The visible drawing sets contain modules B1–B13.
- Pages 1 and 3 contain four module panels; page 2 contains three panels because B6/B7 are wider; page 4 contains the remaining two modules.
- Each module panel uses a front view above, a board-face view below, and a multi-line manufacturing detail list beneath the views.
- The title block sits at the lower-right of the page. A company/legal footer runs along the bottom edge.
- The output uses distinct plotted colors: black for outlines/text, pure green for dimensions, blue/cyan for anchor linework, red for center/anchor marks, and occasional yellow fills. These are visible in the PDF vector strokes, not just screen colors.
- Common details visible in the set include material 1430, density 220 kg/m³, 9厘夹板, 32胶管 for most modules, and anchor material/type/specification, anchor length, and production quantity.
- B6 and B7 use two anchors with explicit segmented positioning dimensions. B6 shows 500 / 200 / 185 across an 885-wide board face; B7 shows 150 / 300 / 250 across a 700-wide board face. Do not replace these with generic equal spacing.
- B10–B13 also show explicit anchor-position dimensions. Preserve the individual dimension chain rather than infer uniform spacing.

## 3. `references/上下盖_3100_2100_400_640_0930_q-02.pdf`

- 1 page, 842×595 pt (A4 landscape), vector-heavy.
- Visible module set S1–S4.
- S1 and S2 have no anchor, with 300×150 and 370×150 board-face views respectively; both list 9厘夹板 and no glue hose.
- S3 and S4 use 304 菱形锚固件 M8, length 230 mm, 220 kg/m³ density, 25胶管, and 9厘夹板. Their board-face outline is 410×200.
- The front-view label in the second panel visually reads S1 while its detail list identifies S2. Record this as a source discrepancy; do not silently change the source or use it as an unquestioned golden value.

## 4. Supplementary geometry images

- `B2_正敲示例.png`: 正敲 has the trapezoid on the **front face**. It has two views: front trapezoid and board face. Example front width is 300 mm with end heights 289 and 220 mm; board face is 300×230 mm.
- `A1_侧敲示例.png`: 侧敲 has the trapezoid on the **side face**. It has three views: normal front, side trapezoid, and board face. Example front is 300×300 mm; side view is 300 mm long with end heights 300 and 200 mm; board face is 300×330 mm.

## 5. Source facts vs unresolved items

### Confirmed by actual files

- A4 landscape is the page standard in both PDFs.
- The PDFs use multiple module panels per page, with variable module count depending on view width.
- The PDFs have front/board-face views and detailed BOM-like text.
- The reference DXF contains 15 named board-face blocks and reusable frame/title blocks.
- Anchor placement is explicitly dimensioned in multiple modules; it is not universally uniform.
- The DXF uses SHX big-font styles and contains AutoCAD dynamic block data.

### Still requiring exact mapping or user confirmation

- The standard opening geometry for quick-insert anchors is not unambiguously identified in the currently catalogued visible board-face blocks. The DXF contains `快插锚固件-右视图`, but a right-side anchor view is not proof of the board opening shape. Do not invent a standard opening.
- The full set of dynamic block visibility states and parameters must be inspected; ezdxf's generic reader does not preserve all proprietary dynamic-block metadata.
- Some source PDF text is plotted as vector outlines and is not available as normal selectable text. OCR or visual review must be used for any ambiguous label.
- The exact automatic panel-packing algorithm must be inferred from more sample jobs or confirmed by the user; do not hardcode the observed four-page grouping as a universal law.

## 7. Module-view source geometry discovered during implementation

- `动态模块-无锚固件-上` contains the 300×300 front-view outline and nested `*U824`. The `*U824` insert produces four internal horizontal marks. These are reused for the S1/S2 no-anchor stacked-module front view, scaled to the module front dimensions.
- `动态模块-M形锚固件-上` contains nested `*U168`, used as the M-shaped front profile.
- `动态模块-菱形锚固件-上` contains nested `*U163`, used as the diamond front profile.
- `动态模块-侧敲-1` contains nested `*U330`, used as the M-shaped side-view profile.
- `动态模块-侧敲-菱形-1` contains nested `*U445`, used as the diamond side-view profile.
- `快插锚固件-右视图` is used as a provisional quick-insert front profile because it visually matches the thin profile in B3/B10/B11/B12. The PDF BOM only states `310锚固件M10`, so this classification remains an inference.
- The B10 board-face mark on PDF page 3 was traced into `references/derived/quick_insert_opening_candidate.json` (outer contour + four slot contours, about 22.578×16.933 mm at 1:10). It is used as a provisional quick-insert opening candidate, not a confirmed manufacturing rule.
