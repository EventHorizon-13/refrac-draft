from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
import re

from refracdraft.domain.models import (
    AnchorParameters,
    DIAMOND_ANCHOR_TYPES,
    WELDED_ANCHOR_TYPES,
    AnchorType,
    BoardFaceProfile,
    BoardParameters,
    GeometryType,
    LayoutMode,
    ModuleParameters,
    Project,
    StructureType,
)
from refracdraft.drawing.board_profiles import build_board_profile, profiles_by_face
from refracdraft.geometry.primitives import equal_segment_layout


@dataclass(frozen=True)
class StandardModuleValues:
    module_id: str
    length_mm: float
    expansion_length_mm: float
    thickness_mm: float
    taper_enabled: bool = False
    big_head_mm: float | None = None
    small_head_mm: float | None = None
    taper_type: GeometryType = GeometryType.FRONT_TAPER
    board_exists: bool = True
    material: str = ""
    production_quantity: int = 1
    board_material: str = "9厘夹板"
    density_kg_m3: float | None = None
    source_note: str = ""
    structure_type: StructureType = StructureType.FOLDED
    custom_structure_label: str = ""
    board_face_profile: BoardFaceProfile | None = None


@dataclass(frozen=True)
class StandardAnchorValues:
    enabled: bool = False
    position_mm: float | None = 150.0
    spacing_mm: float | None = 300.0
    count: int = 1
    anchor_type: AnchorType = AnchorType.M_SHAPE
    embedment_depth_mm: float | None = None
    material: str = "310"
    thread_spec: str = "M10"
    pin_diameter_mm: float | None = 8.0
    hose_spec: str = "32胶管"
    length_mm: float | None = 230.0
    custom_type_label: str = ""
    bolt_exposure_mm: float | None = None
    layout_mode: LayoutMode = LayoutMode.FIXED_SPACING


def _positive(value: float | None, label: str, module_id: str) -> float:
    if value is None or not isfinite(value) or value <= 0:
        raise ValueError(f"{module_id}: {label}必须大于 0")
    return float(value)


def _default_hose_spec(thread_spec: str) -> str:
    thread = thread_spec.strip().upper()
    if thread == "M8":
        return "25胶管"
    if thread == "M10":
        return "32胶管"
    return "32胶管"


def _board_thickness(material: str, fallback: float | None) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:厘|mm)", material, re.I)
    if match:
        return float(match.group(1))
    return fallback


def _module_material(value: str) -> str:
    text = value.strip()
    for suffix in ("板材", "材质"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break
    return f"{text}材质" if text else ""


def build_standard_module(
    base: ModuleParameters | None,
    values: StandardModuleValues,
) -> ModuleParameters:
    module_id = values.module_id.strip()
    if not module_id:
        raise ValueError("模块编号不能为空")
    length = _positive(values.length_mm, "长度", module_id)
    expansion = _positive(values.expansion_length_mm, "膨胀长度", module_id)
    thickness = _positive(values.thickness_mm, "厚度", module_id)
    data = base.model_dump(mode="python") if base else {}
    data.update(
        module_id=module_id,
        material=_module_material(values.material),
        density_kg_m3=values.density_kg_m3,
        source_note=values.source_note.strip(),
        production_quantity=max(1, int(values.production_quantity)),
        structure_type=values.structure_type,
        custom_structure_label=(
            values.custom_structure_label.strip()
            if values.structure_type == StructureType.CUSTOM else ""
        ),
        front_width_mm=length,
        expansion_length_mm=expansion,
        board_face_width_mm=length,
        board_face_height_mm=thickness,
        board_face_template_id="rectangular",
        front_outline=None,
        board_face_outline=values.board_face_profile,
    )
    if not values.taper_enabled:
        data.update(
            geometry_type=GeometryType.NORMAL,
            front_height_mm=expansion,
            front_left_height_mm=None,
            front_right_height_mm=None,
            side_length_mm=None,
            side_left_height_mm=None,
            side_right_height_mm=None,
        )
    else:
        big = _positive(values.big_head_mm, "大头", module_id)
        small = _positive(values.small_head_mm, "小头", module_id)
        if big <= small:
            raise ValueError(f"{module_id}: 大头必须大于小头")
        # A tapered standard module has one expansion length: it always follows the big head.
        expansion = big
        if values.taper_type == GeometryType.FRONT_TAPER:
            data.update(
                geometry_type=GeometryType.FRONT_TAPER,
                expansion_length_mm=expansion,
                front_height_mm=big,
                front_left_height_mm=big,
                front_right_height_mm=small,
                side_length_mm=None,
                side_left_height_mm=None,
                side_right_height_mm=None,
            )
        elif values.taper_type == GeometryType.SIDE_TAPER:
            data.update(
                geometry_type=GeometryType.SIDE_TAPER,
                expansion_length_mm=expansion,
                front_height_mm=expansion,
                front_left_height_mm=None,
                front_right_height_mm=None,
                side_length_mm=thickness,
                side_left_height_mm=big,
                side_right_height_mm=small,
            )
        else:
            raise ValueError(f"{module_id}: 大小头类型必须是正敲或侧敲")
    module = ModuleParameters.model_validate(data)
    if values.board_face_profile is not None:
        for face, profile in profiles_by_face(values.board_face_profile).items():
            width, height, _ = module.cut_face_dimensions(face)
            try:
                build_board_profile(width, height, profile)
            except ValueError as exc:
                raise ValueError(f"{module_id} {face}: {exc}") from exc
    return module


def build_standard_board(
    base: BoardParameters | None,
    module_id: str,
    exists: bool,
    material: str = "9厘夹板",
    *,
    show_upper_board: bool | None = None,
    show_lower_board: bool | None = None,
) -> BoardParameters:
    data = base.model_dump(mode="python") if base else {}
    data.update(module_id=module_id, exists=exists)
    if show_upper_board is not None:
        data["show_upper_board"] = show_upper_board
    if show_lower_board is not None:
        data["show_lower_board"] = show_lower_board
    if exists:
        board_material = material.strip() or "9厘夹板"
        data["material"] = board_material
        parsed_thickness = _board_thickness(board_material, data.get("thickness_mm"))
        if parsed_thickness is None:
            parsed_thickness = 9.0
        data["thickness_mm"] = parsed_thickness
    return BoardParameters.model_validate(data)


def build_standard_anchor(
    base: AnchorParameters | None,
    module_id: str,
    module_length_mm: float,
    values: StandardAnchorValues,
) -> AnchorParameters:
    data = base.model_dump(mode="python") if base else {}
    pin_diameter = (None if values.anchor_type in DIAMOND_ANCHOR_TYPES
                    else values.pin_diameter_mm)
    data.update(
        module_id=module_id,
        material=values.material.strip(),
        thread_spec=values.thread_spec.strip(),
        diameter_mm=pin_diameter,
        length_mm=None,
        hose_spec=values.hose_spec.strip(),
        dimension_horizontal=True,
        bolt_exposure_mm=values.bolt_exposure_mm if values.enabled and values.anchor_type in WELDED_ANCHOR_TYPES else None,
        dimension_vertical=False,
        custom_type_label=(
            values.custom_type_label.strip()
            if values.enabled and values.anchor_type == AnchorType.CUSTOM else ""
        ),
    )
    if not values.enabled:
        data.update(
            exists=False,
            anchor_type=AnchorType.NONE,
            count=0,
            layout_mode=LayoutMode.FIXED_SPACING,
            positions=[],
            embedment_depth_mm=None,
            length_mm=None,
        )
        return AnchorParameters.model_validate(data)

    if values.anchor_type == AnchorType.NONE:
        raise ValueError(f"{module_id}: 已勾选锚固件，必须选择锚固件类型")
    length = _positive(values.length_mm, "锚固件长度", module_id) if values.length_mm is not None else None
    count = int(values.count)
    if count < 1:
        raise ValueError(f"{module_id}: 锚固件数量至少为 1")
    if values.layout_mode == LayoutMode.EQUAL_SEGMENTS:
        position, spacing = equal_segment_layout(module_length_mm, count)
    else:
        position = _positive(values.position_mm, "锚固件位置", module_id)
        spacing = _positive(values.spacing_mm, "锚固件间距", module_id)
        if position + spacing * (count - 1) > module_length_mm:
            raise ValueError(f"{module_id}: 锚固件位置与间距超出模块长度")
    embedment = None
    if values.anchor_type == AnchorType.DIAMOND:
        embedment = _positive(
            50.0 if values.embedment_depth_mm is None else values.embedment_depth_mm,
            "嵌入深度", module_id,
        )
    elif values.anchor_type == AnchorType.WELDED_DIAMOND and values.embedment_depth_mm is not None:
        embedment = _positive(values.embedment_depth_mm, "嵌入深度", module_id)
    data.update(
        exists=True,
        anchor_type=values.anchor_type,
        count=count,
        layout_mode=values.layout_mode,
        positions=[],
        edge_offset_mm=position,
        spacing_mm=spacing,
        embedment_depth_mm=embedment,
        length_mm=length,
    )
    return AnchorParameters.model_validate(data)


def standard_module_values(
    module: ModuleParameters,
    board: BoardParameters,
) -> StandardModuleValues:
    taper = module.geometry_type in (GeometryType.FRONT_TAPER, GeometryType.SIDE_TAPER)
    if module.geometry_type == GeometryType.FRONT_TAPER:
        left = module.front_left_height_mm or module.front_height_mm
        right = module.front_right_height_mm or module.front_height_mm
        big, small = max(left, right), min(left, right)
    elif module.geometry_type == GeometryType.SIDE_TAPER:
        left = module.side_left_height_mm or module.front_height_mm
        right = module.side_right_height_mm or module.front_height_mm
        big, small = max(left, right), min(left, right)
    else:
        big = small = None
    return StandardModuleValues(
        module_id=module.module_id,
        length_mm=(
            module.board_face_width_mm
            if isinstance(module.board_face_outline, BoardFaceProfile) else module.front_width_mm
        ),
        expansion_length_mm=(big if taper else module.expansion_length_mm or module.front_height_mm),
        thickness_mm=module.board_face_height_mm,
        taper_enabled=taper,
        big_head_mm=big,
        small_head_mm=small,
        taper_type=module.geometry_type if taper else GeometryType.FRONT_TAPER,
        board_exists=board.exists,
        material=module.material,
        production_quantity=module.production_quantity,
        board_material=board.material,
        density_kg_m3=module.density_kg_m3,
        source_note=module.source_note,
        structure_type=module.structure_type,
        custom_structure_label=module.custom_structure_label,
        board_face_profile=(
            module.board_face_outline if isinstance(module.board_face_outline, BoardFaceProfile) else None
        ),
    )


def standard_anchor_values(anchor: AnchorParameters) -> StandardAnchorValues:
    enabled = anchor.exists and anchor.anchor_type != AnchorType.NONE and anchor.count > 0
    if not enabled:
        return StandardAnchorValues(enabled=False)
    if anchor.layout_mode == LayoutMode.EXPLICIT and anchor.positions:
        xs = sorted(p.x_mm for p in anchor.positions)
        position = xs[0]
        differences = [b - a for a, b in zip(xs, xs[1:]) if b > a]
        spacing = differences[0] if differences else (anchor.spacing_mm or 300.0)
    else:
        position = anchor.edge_offset_mm
        spacing = anchor.spacing_mm or 300.0
    return StandardAnchorValues(
        enabled=True,
        position_mm=position,
        spacing_mm=spacing,
        count=anchor.count,
        anchor_type=anchor.anchor_type,
        embedment_depth_mm=anchor.embedment_depth_mm,
        bolt_exposure_mm=anchor.bolt_exposure_mm,
        material=anchor.material,
        thread_spec=anchor.thread_spec,
        pin_diameter_mm=anchor.diameter_mm,
        hose_spec=anchor.hose_spec or _default_hose_spec(anchor.thread_spec),
        length_mm=anchor.length_mm,
        custom_type_label=anchor.custom_type_label,
        layout_mode=(LayoutMode.EQUAL_SEGMENTS if anchor.layout_mode == LayoutMode.EQUAL_SEGMENTS
                     else LayoutMode.FIXED_SPACING),
    )


def ensure_standard_project(project: Project) -> None:
    """Accept parameterized board cuts and the supported front and side views."""
    for module in project.modules:
        if (
            module.front_outline is not None
            or (
                module.board_face_outline is not None
                and not isinstance(module.board_face_outline, BoardFaceProfile)
            )
            or module.board_face_template_id != "rectangular"
        ):
            raise ValueError(
                f"{module.module_id}: 标准版仅支持「异形模块」中的切口预设"
            )

