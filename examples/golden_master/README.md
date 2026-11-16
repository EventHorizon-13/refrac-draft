# Golden-master datasets (draft)

These JSON files transcribe the module dimensions and BOM information visible in the supplied PDFs. They are regression fixtures, but not all anchor classifications are confirmed.

- `jiangyin_b1_b13.json`: B1–B13. B3/B10/B11/B12 are temporarily mapped to the DXF quick-insert candidate because their front-view profile resembles `快插锚固件-右视图`; the PDF BOM itself only says `310锚固件M10`. The B10 board-face mark is traced into a provisional opening candidate; confirm both before treating these four as final golden-master cases.
- `upper_cover_s1_s4.json`: S1–S4. S1/S2 use the no-anchor stacked front-view lines extracted from `*U824`. S3/S4 use the diamond anchor blocks.

Dimensions are millimetres. The production quantity is not the anchor count. Position dimensions are explicit per source drawing (`dimension_horizontal` / `dimension_vertical`).
