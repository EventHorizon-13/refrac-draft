from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

import ezdxf
import fitz
from ezdxf import bbox

from refracdraft.reference.library import ReferenceLibrary


def analyze_dxf(path: Path) -> dict:
    doc = ezdxf.readfile(path)
    model = doc.modelspace()
    layers = []
    for layer in doc.layers:
        layers.append({
            "name": layer.dxf.name,
            "aci_color": layer.dxf.color,
            "linetype": layer.dxf.linetype,
            "lineweight": layer.dxf.lineweight,
        })
    block_records = []
    for block in doc.blocks:
        if block.name.startswith("*"):
            continue
        ext = bbox.extents(block, fast=False)
        block_records.append({
            "name": block.name,
            "entity_count": len(block),
            "entity_types": dict(collections.Counter(e.dxftype() for e in block)),
            "bounds": [round(v, 4) for v in (*ext.extmin, *ext.extmax)] if ext.has_data else None,
            "nested_inserts": [e.dxf.name for e in block if e.dxftype() == "INSERT"],
            "attribute_definitions": [e.dxf.tag for e in block if e.dxftype() == "ATTDEF"],
        })
    return {
        "file": path.name,
        "dxf_version": doc.dxfversion,
        "encoding": doc.encoding,
        "layouts": [{"name": layout.name, "entity_count": len(layout),
                     "entity_types": dict(collections.Counter(e.dxftype() for e in layout))}
                    for layout in doc.layouts],
        "modelspace_entity_count": len(model),
        "modelspace_entity_types": dict(collections.Counter(e.dxftype() for e in model)),
        "modelspace_insert_block_counts": dict(collections.Counter(e.dxf.name for e in model if e.dxftype() == "INSERT")),
        "block_definition_count": len(doc.blocks),
        "layers": layers,
        "blocks": block_records,
    }


def analyze_pdf(path: Path) -> dict:
    doc = fitz.open(path)
    pages = []
    for index, page in enumerate(doc):
        colors = collections.Counter()
        widths = collections.Counter()
        for item in page.get_drawings():
            color = item.get("color")
            colors[tuple(round(v, 3) for v in color) if color else None] += 1
            widths[round(item.get("width") or 0, 3)] += 1
        pages.append({
            "page": index + 1,
            "width_pt": round(page.rect.width, 3),
            "height_pt": round(page.rect.height, 3),
            "vector_drawing_count": len(page.get_drawings()),
            "embedded_image_count": len(page.get_images(full=True)),
            "stroke_color_counts": {str(k): v for k, v in colors.items()},
            "stroke_width_counts_pt": dict(widths),
        })
    return {"file": path.name, "page_count": len(doc), "pages": pages}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dxf", type=Path, default=Path("references/示例.dxf"))
    parser.add_argument("--pdf", type=Path, nargs="*", default=[
        Path("references/江阴铁包-11098-qf.pdf"),
        Path("references/上下盖_3100_2100_400_640_0930_q-02.pdf"),
    ])
    parser.add_argument("--output", type=Path, default=Path("output/reference_inventory.json"))
    args = parser.parse_args()

    result = {"dxf": analyze_dxf(args.dxf), "pdfs": [analyze_pdf(p) for p in args.pdf]}
    result["board_face_templates"] = ReferenceLibrary(args.dxf).board_face_catalog()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Reference inventory written to {args.output}")


if __name__ == "__main__":
    main()
