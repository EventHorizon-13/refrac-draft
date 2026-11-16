from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from pathlib import Path

import ezdxf
from ezdxf.disassemble import recursive_decompose
from ezdxf.path import make_path

from refracdraft.geometry.primitives import Polyline


BOARD_FACE_BLOCKS: dict[str, str] = {
    "m-anchor": "动态模块-M形锚固件-夹板面",
    "diamond-anchor": "动态模块-菱形锚固件-夹板面",
    "no-anchor": "动态模块-无锚固件-夹板面",
    "side-insert": "动态模块-旁插锚固件-夹板面",
    "side-insert-irregular-1": "动态模块-旁插锚固件-异形1-夹板面",
    "side-insert-irregular-2": "动态模块-旁插锚固件-异形2-夹板面",
    "side-insert-irregular-3": "动态模块-旁插锚固件-异形3-夹板面",
    "side-insert-irregular-4": "动态模块-旁插锚固件-异形4-夹板面",
    "irregular-2": "动态模块-异形2-夹板面",
    "irregular-3": "动态模块-异形3-夹板面",
    "irregular-4": "动态模块-异形4-夹板面",
    "irregular-5": "动态模块-异形5-夹板面",
    "irregular-7": "动态模块-异形7-夹板面",
    "no-anchor-irregular-5": "动态模块-无锚固件-异形5-夹板面",
    "welded-diamond": "动态模块-焊接菱形锚固件2-夹板面",
}

ANCHOR_SYMBOL_BLOCKS: dict[str, str] = {
    # These two nested block representations are currently mapped to visible plan-view
    # symbols. Other candidate blocks contain patterns/profile geometry that still need
    # confirmation before they can be treated as a single anchor symbol.
    "m-shaped": "动态模块-M形锚固件-夹板面",
    "diamond": "动态模块-菱形锚固件-夹板面",
}


@dataclass(frozen=True)
class SymbolGeometry:
    polylines: tuple[Polyline, ...]


class ReferenceLibrary:
    """Read-only extractor for the supplied reference DXF.

    The source file is never saved. ACAD dynamic-block metadata is not rewritten;
    visible source geometry is extracted for parameterized output.
    """

    def __init__(self, dxf_path: str | Path):
        self.path = Path(dxf_path)
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        self.doc = ezdxf.readfile(self.path)

    def board_outline(self, template_id: str) -> Polyline:
        block_name = BOARD_FACE_BLOCKS.get(template_id, template_id)
        if block_name not in self.doc.blocks:
            raise KeyError(f"参考 DXF 中不存在夹板面模板: {template_id}")
        block = self.doc.blocks[block_name]
        candidates: list[tuple[float, list[tuple[float, float]]]] = []
        for entity in block:
            if entity.dxftype() != "LWPOLYLINE":
                continue
            path = make_path(entity)
            pts = [(float(v.x), float(v.y)) for v in path.flattening(distance=0.25)]
            if len(pts) < 3:
                continue
            area = abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] -
                           pts[(i + 1) % len(pts)][0] * pts[i][1]
                           for i in range(len(pts))) / 2.0)
            candidates.append((area, pts))
        if not candidates:
            raise ValueError(f"夹板面模板 {block_name} 中没有可用的 LWPOLYLINE 轮廓")
        _, points = max(candidates, key=lambda item: item[0])
        # The source includes one visually closed polyline whose DXF closed flag is false.
        if len(points) > 2 and hypot(points[0][0] - points[-1][0], points[0][1] - points[-1][1]) < 1e-5:
            points = points[:-1]
        return Polyline(tuple(points), closed=True)

    def anchor_symbol(self, symbol_id: str) -> SymbolGeometry:
        block_name = ANCHOR_SYMBOL_BLOCKS.get(symbol_id)
        if not block_name:
            raise KeyError(f"尚未建立锚固件符号映射: {symbol_id}")
        block = self.doc.blocks[block_name]
        inserts = [entity for entity in block if entity.dxftype() == "INSERT"]
        if not inserts:
            return SymbolGeometry(())
        symbol_entities = list(recursive_decompose(inserts))
        polylines: list[Polyline] = []
        for entity in symbol_entities:
            try:
                path = make_path(entity)
                pts = [(float(v.x), float(v.y)) for v in path.flattening(distance=0.35)]
                if len(pts) >= 2:
                    closed = len(pts) > 2 and hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-4
                    if closed:
                        pts = pts[:-1]
                    polylines.append(Polyline(tuple(pts), closed=closed))
            except (TypeError, AttributeError, ValueError):
                continue
        if not polylines:
            return SymbolGeometry(())
        xs = [p[0] for line in polylines for p in line.points]
        ys = [p[1] for line in polylines for p in line.points]
        cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
        normalized = tuple(line.transformed(tx=-cx, ty=-cy) for line in polylines)
        return SymbolGeometry(normalized)


    def symbol_from_block(self, block_name: str) -> SymbolGeometry:
        """Flatten a source block into reusable local polylines, centered at its bounds."""
        if block_name not in self.doc.blocks:
            raise KeyError(f"参考 DXF 中不存在图块: {block_name}")
        entities = list(recursive_decompose(self.doc.blocks[block_name]))
        polylines: list[Polyline] = []
        for entity in entities:
            try:
                path = make_path(entity)
                pts = [(float(v.x), float(v.y)) for v in path.flattening(distance=0.35)]
                if len(pts) >= 2:
                    closed = len(pts) > 2 and hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-4
                    if closed:
                        pts = pts[:-1]
                    polylines.append(Polyline(tuple(pts), closed=closed))
            except (TypeError, AttributeError, ValueError):
                continue
        if not polylines:
            return SymbolGeometry(())
        xs = [p[0] for line in polylines for p in line.points]
        ys = [p[1] for line in polylines for p in line.points]
        cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
        return SymbolGeometry(tuple(line.transformed(tx=-cx, ty=-cy) for line in polylines))

    def board_face_catalog(self) -> list[dict[str, object]]:
        catalog = []
        for template_id, block_name in BOARD_FACE_BLOCKS.items():
            block = self.doc.blocks[block_name]
            outline = self.board_outline(template_id)
            min_x, min_y, max_x, max_y = outline.bounds
            catalog.append({
                "id": template_id,
                "block_name": block_name,
                "vertex_count": len(outline.points),
                "bounds_mm": [round(min_x, 3), round(min_y, 3), round(max_x, 3), round(max_y, 3)],
                "nested_inserts": [e.dxf.name for e in block if e.dxftype() == "INSERT"],
                "attdefs": [e.dxf.tag for e in block if e.dxftype() == "ATTDEF"],
            })
        return catalog
