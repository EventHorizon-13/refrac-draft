from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt

from refracdraft.reference.library import ReferenceLibrary, BOARD_FACE_BLOCKS


def render_board_faces(library: ReferenceLibrary, output: Path) -> None:
    ids = list(BOARD_FACE_BLOCKS)
    rows, cols = 5, 3
    fig, axes = plt.subplots(rows, cols, figsize=(15, 15), dpi=160)
    for ax, template_id in zip(axes.flat, ids):
        outline = library.board_outline(template_id)
        xs = [p[0] for p in outline.points] + [outline.points[0][0]]
        ys = [p[1] for p in outline.points] + [outline.points[0][1]]
        ax.plot(xs, ys, linewidth=1.8)
        ax.set_title(template_id, fontsize=9)
        ax.set_aspect("equal", adjustable="datalim")
        ax.axis("off")
    for ax in axes.flat[len(ids):]:
        ax.axis("off")
    fig.suptitle("Board-face templates extracted from the reference DXF", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight", facecolor="white")
    fig.savefig(output.with_suffix(".svg"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def render_anchor_symbols(library: ReferenceLibrary, output: Path) -> None:
    candidates = [("m-shaped", "*U179"), ("diamond", "*U155"),
                  ("side-insert candidate", "*U217"), ("welded-diamond candidate", "*U298")]
    fig, axes = plt.subplots(2, 2, figsize=(10, 8), dpi=160)
    for ax, (symbol_id, block_name) in zip(axes.flat, candidates):
        symbol = library.symbol_from_block(block_name)
        for poly in symbol.polylines:
            if len(poly.points) < 2:
                continue
            pts = list(poly.points)
            if poly.closed:
                pts.append(pts[0])
            ax.plot([p[0] for p in pts], [p[1] for p in pts], linewidth=1.2)
        ax.set_title(f"{symbol_id} ({block_name})", fontsize=10)
        ax.set_aspect("equal", adjustable="datalim")
        ax.axis("off")
    fig.suptitle("Visible anchor symbols recursively extracted from source blocks", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight", facecolor="white")
    fig.savefig(output.with_suffix(".svg"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dxf", type=Path, default=Path("references/示例.dxf"))
    parser.add_argument("--output-dir", type=Path, default=Path("docs/assets"))
    args = parser.parse_args()
    library = ReferenceLibrary(args.dxf)
    render_board_faces(library, args.output_dir / "board_face_templates.png")
    render_anchor_symbols(library, args.output_dir / "anchor_symbols.png")
    print(f"Catalog previews written to {args.output_dir}")


if __name__ == "__main__":
    main()
