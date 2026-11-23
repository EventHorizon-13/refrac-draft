# RefracDraft — Repository Instructions for Codex

Before coding, read `PROMPT.md`, `README.md`, and `docs/REFERENCE_ANALYSIS.md`.

## Non-negotiable product rules

- This is an independent project. It is not part of SolidCraft; only the user experience may take inspiration from SolidCraft Roller-Seal.
- The application generates **2D module manufacturing drawings only**. Do not create a 3D modeler.
- Input is Excel import and manual entry. Drawing starts only when the user clicks Generate. Sheet format is A4 landscape with automatic pagination. Export editable DXF and PDF.
- Module, board, and anchor are three **parallel, independent parameter groups**, linked by module ID. They are not parent/child objects and must not inherit or overwrite one another's parameters.
- Board outer contour matches the module's board-face geometry. Board properties such as presence, material, thickness, and machining remain independent.
- Every module must have a board-face view. If there is no physical board, still draw that view and put `无夹板` in its center.
- **侧敲** means the trapezoid is on the side face: front view + side trapezoid view + board-face view (3 views).
- **正敲** means the trapezoid is on the front face: front trapezoid + board-face view (2 views).
- Normal modules use front + board-face views (2 views).
- Modules with parametric front or side cuts use all three views. Compute the remaining solid after combining the cuts, then project that same geometry into each view.
- Quick-insert anchor types determine a standard board opening; custom opening geometry is also supported.
- Board-face shapes include multiple irregular templates. Inspect and reuse the actual shapes in the reference DXF; do not reduce them to generic rectangles/trapezoids.
- Side-insert and quick-insert are different anchor types.
- Anchor positions can be uniform, fixed-spacing, or explicitly specified. Do not force all anchors to be uniformly distributed.
- Production quantity and anchor count are different fields.
- DXF and PDF must be generated from the same 2D drawing model. DXF geometry, dimensions, and text must remain editable.

## Reference files

Expected paths:
- `references/示例.dxf`
- `references/江阴铁包-11098-qf.pdf`
- `references/上下盖_3100_2100_400_640_0930_q-02.pdf`
- `references/B2_正敲示例.png`
- `references/A1_侧敲示例.png`

If any source file is missing, report it explicitly and ask for it. Do not claim to have analyzed a missing source.

Do not modify original reference files. Record uncertain or conflicting information as unresolved rather than inventing a rule.


## Golden-master drawing fidelity

The supplied sample files are the **final drawing standard**, not loose inspiration. Generated drawings must closely reproduce their drafting conventions and page appearance. Do not redesign or modernize the drawing style.

- Use the DXF as the primary source for CAD geometry, blocks, layers, linetypes, text/dimension styles, frames, and title blocks.
- Use the PDFs as the primary source for final page composition, view arrangement, annotation placement, BOM/detail layout, frames, title blocks, and pagination.
- Use the B2 front-trapezoid and A1 side-trapezoid images to check geometry and view count.
- Recreate sample inputs as golden-master regression cases. Generate vector/editable DXF and PDF and compare them page by page and view by view with the samples.
- Do not omit dimensions, anchor details, board-face irregularities, technical text, BOMs, or title-block fields for the sake of a simplified demo.
- Do not rasterize a sample PDF into the output or copy a whole sample drawing unchanged as a fake parameterized result. Extract reusable geometry and drafting rules, then generate editable drawings that match the sample style.
- When details are uncertain, record them as unresolved. Explicit user corrections take precedence over conflicting source details.
