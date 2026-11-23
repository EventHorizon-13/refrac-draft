from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from math import isfinite

from refracdraft.domain.models import (
    AnchorParameters, AnchorType, BoardFaceProfile, BoardParameters, GeometryType, ModuleParameters,
    StructureType, DIAMOND_ANCHOR_TYPES, WELDED_ANCHOR_TYPES, format_bolt_remark,
)
from refracdraft.standard import (
    StandardAnchorValues, StandardModuleValues, build_standard_anchor, build_standard_board,
    build_standard_module, standard_anchor_values, standard_module_values,
)


MODULE_MATERIALS = (
    "1050", "1100", "1150", "1260", "1350", "1400", "1430", "1500", "1600",
    "铬锆复合",
)
BOARD_TYPES = ("9厘", "8厘", "6厘")
ANCHOR_MATERIALS = ("201", "304", "309", "310")
THREAD_SPECS = ("M8", "M10")
PROFILE_SHEET = "异形参数"
AUTOMATIC_SHEET = "联动设置"
AUTOMATIC_FALLBACK_KEYS = ("board_material", "anchor_material", "hose_spec")
PROFILE_COLUMNS = ("编号", "类型", "a", "b", "c", "d", "旋转角度", "镜像", "剪切深度", "起切面", "加工面")
PIN_DIAMETERS = ("8", "6", "5")
HOSE_SPECS = ("25", "32")
AUTOMATIC = "自动"
STANDARD_LINK_VERSION = 2
TAPER_LABEL_VERSION = 2
AUTOMATIC_FIELDS = ("structure_type", "board_material", "anchor_material", "hose_spec", "anchor_length_mm", "source_note")
EMPTY_SELECTS_AUTOMATIC = ("structure_type", "board_material", "hose_spec")
OPTIONAL_ANCHOR_FIELDS = ("anchor_length_mm", "anchor_material", "thread_spec", "pin_diameter_mm")
M_ANCHOR_LENGTHS = (240, 220, 200, 180, 150, 120)
DIAMOND_ANCHOR_LENGTHS = (230, 200, 180, 150, 120)
INSERT_ANCHOR_LENGTHS = (450, 400, 350, 250)
INSERT_ANCHOR_LABELS = frozenset({AnchorType.SIDE_INSERT.value, AnchorType.QUICK_INSERT.value})
INSERT_ANCHOR_NOTE = "木板开口60*110 插针隔1层毯子插"

ANCHOR_TYPES = (
    ("M型", AnchorType.M_SHAPE),
    ("菱形", AnchorType.DIAMOND),
    ("旁插", AnchorType.SIDE_INSERT),
    ("快插", AnchorType.QUICK_INSERT),
    ("焊接M型", AnchorType.WELDED_M),
    ("焊接菱形", AnchorType.WELDED_DIAMOND),
    ("自定义", AnchorType.CUSTOM),
)
ANCHOR_TYPE_BY_LABEL = dict(ANCHOR_TYPES)
ANCHOR_LABEL_BY_TYPE = {value: label for label, value in ANCHOR_TYPES}

STRUCTURE_TYPES = (
    ("折叠", StructureType.FOLDED),
    ("半折叠", StructureType.HALF_FOLDED),
    ("层叠", StructureType.STACKED),
    ("自定义", StructureType.CUSTOM),
)
STRUCTURE_TYPE_BY_LABEL = dict(STRUCTURE_TYPES)
STRUCTURE_LABEL_BY_TYPE = {value: label for label, value in STRUCTURE_TYPES}


@dataclass(frozen=True)
class ColumnSpec:
    key: str
    label: str
    kind: str = "text"
    options: tuple[str, ...] = ()
    width: int = 84
    group: str = "module"


COLUMN_SPECS = (
    ColumnSpec("module_id", "编号", width=62, group="base"),
    ColumnSpec("length_mm", "长度", "number", (), 56, "base"),
    ColumnSpec("expansion_length_mm", "膨胀长度", "number", (), 64, "base"),
    ColumnSpec("thickness_mm", "厚度", "number", (), 56, "base"),
    ColumnSpec(
        "structure_type",
        "折叠方式",
        "combo",
        tuple(label for label, _ in STRUCTURE_TYPES),
        74,
        "base",
    ),
    ColumnSpec("material", "模块材质", "combo", MODULE_MATERIALS, 72, "base"),
    ColumnSpec("density_kg_m3", "容重", "number", (), 52, "base"),
    ColumnSpec("production_quantity", "数量", "integer", (), 50, "base"),
    ColumnSpec("taper_enabled", "大小头", "check", width=50, group="taper"),
    ColumnSpec("big_head_mm", "大头", "number", (), 54, "taper"),
    ColumnSpec("small_head_mm", "小头", "number", (), 54, "taper"),
    ColumnSpec("taper_type", "类型", "enum", ("正敲", "侧敲"), 58, "taper"),
    ColumnSpec("board_exists", "夹板", "check", width=50, group="board"),
    ColumnSpec("board_material", "夹板型号", "combo", BOARD_TYPES, 64, "board"),
    ColumnSpec("show_upper_board", "上板图", "check", width=62, group="board"),
    ColumnSpec("show_lower_board", "下板图", "check", width=62, group="board"),
    ColumnSpec("anchor_enabled", "锚固件", "check", width=56, group="anchor"),
    ColumnSpec("anchor_position_mm", "位置", "number", (), 54, "anchor"),
    ColumnSpec("anchor_spacing_mm", "间距", "number", (), 54, "anchor"),
    ColumnSpec("anchor_count", "锚固数量", "integer", (), 62, "anchor"),
    ColumnSpec(
        "anchor_type",
        "锚固件类型",
        "enum",
        tuple(label for label, _ in ANCHOR_TYPES),
        82,
        "anchor",
    ),
    ColumnSpec("anchor_length_mm", "锚固件长度", "number", tuple(map(str, M_ANCHOR_LENGTHS)), 82, "anchor"),
    ColumnSpec("anchor_material", "材质", "combo", ANCHOR_MATERIALS, 60, "anchor"),
    ColumnSpec("thread_spec", "螺栓", "combo", THREAD_SPECS, 60, "anchor"),
    ColumnSpec("pin_diameter_mm", "插针", "number", PIN_DIAMETERS, 54, "anchor"),
    ColumnSpec("hose_spec", "胶管", "combo", HOSE_SPECS, 54, "anchor"),
    ColumnSpec("embedment_depth_mm", "嵌入深度", "number", (), 62, "anchor"),
    ColumnSpec("bolt_exposure_mm", "螺栓外露长度", "number", (), 96, "anchor"),
    ColumnSpec("source_note", "备注", options=(AUTOMATIC,), width=116, group="footer"),
)
DEFAULT_ROW = {
    "module_id": "M1",
    "length_mm": "300",
    "expansion_length_mm": "300",
    "thickness_mm": "230",
    "structure_type": "折叠",
    "material": "1430",
    "density_kg_m3": "220",
    "production_quantity": "1",
    "taper_enabled": False,
    "big_head_mm": "289",
    "small_head_mm": "220",
    "taper_type": GeometryType.FRONT_TAPER.value,
    "board_exists": True,
    "board_material": "9厘",
    "show_upper_board": False,
    "show_lower_board": False,
    "anchor_enabled": False,
    "anchor_position_mm": "150",
    "anchor_spacing_mm": "300",
    "anchor_count": "1",
    "anchor_type": "M型",
    "anchor_length_mm": "230",
    "anchor_material": "310",
    "thread_spec": "M10",
    "pin_diameter_mm": "8",
    "hose_spec": "32",
    "embedment_depth_mm": "50",
    "bolt_exposure_mm": "",
    "source_note": AUTOMATIC,
}


def _number(value: str, label: str, module_id: str) -> float:
    try:
        parsed = float(value.strip().replace(",", ""))
    except (TypeError, ValueError):
        raise ValueError(f"{module_id or '未编号模块'}: {label}必须是数字") from None
    if not isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{module_id or '未编号模块'}: {label}必须大于 0")
    return parsed


def _optional_number(value: str, label: str, module_id: str) -> float | None:
    if not value.strip():
        return None
    return _number(value, label, module_id)


def _integer(value: str, label: str, module_id: str, minimum: int = 1) -> int:
    try:
        parsed = int(float(value.strip()))
    except (TypeError, ValueError):
        raise ValueError(f"{module_id or '未编号模块'}: {label}必须是整数") from None
    if parsed < minimum:
        raise ValueError(f"{module_id or '未编号模块'}: {label}必须至少为 {minimum}")
    return parsed


def _without_suffix(value: str, *suffixes: str) -> str:
    text = value.strip()
    for suffix in sorted(suffixes, key=len, reverse=True):
        if suffix and text.endswith(suffix):
            return text[: -len(suffix)].strip()
    return text


def _board_material_value(value: str) -> str:
    text = value.strip()
    if not text or text == "无" or text.endswith(("夹板", "mm")):
        return text
    return f"{text}夹板"


def _hose_value(value: str) -> str:
    text = value.strip()
    if not text or text == "无" or text.endswith("胶管"):
        return "无胶管" if text == "无" else text
    return f"{text}胶管"


def automatic_fields(values: dict[str, str | bool]) -> list[str]:
    return [
        key for key in AUTOMATIC_FIELDS
        if values.get(key) == AUTOMATIC or (key in EMPTY_SELECTS_AUTOMATIC and values.get(key) == "")
    ]


def _insert_anchor_note(values: dict[str, str | bool]) -> str:
    return INSERT_ANCHOR_NOTE if values["anchor_enabled"] and values["anchor_type"] in INSERT_ANCHOR_LABELS else ""


def legacy_source_note(values: dict[str, str | bool]) -> str:
    note = str(values["source_note"]).strip()
    if note in ("", AUTOMATIC):
        return AUTOMATIC
    instruction = _insert_anchor_note(values)
    if instruction and instruction not in note:
        return f"{note}；{instruction}"
    return note


def legacy_automatic_fields(values: dict[str, str | bool]) -> list[str]:
    """Recognize older preset values while keeping custom values explicit."""
    presets = {
        "structure_type": ("折叠", "半折叠", "折叠模块", "半折叠模块"),
        "board_material": ("8厘", "9厘", "8厘夹板", "9厘夹板"),
        "anchor_material": ANCHOR_MATERIALS,
        "hose_spec": ("25", "32", "25胶管", "32胶管"),
        "anchor_length_mm": ((*anchor_length_options(str(values["anchor_type"])), "230")
                             if values["anchor_type"] != AnchorType.WELDED_DIAMOND else ()),
    }
    automatic = automatic_fields(values)
    return [key for key in AUTOMATIC_FIELDS if key in automatic or str(values[key]) in presets.get(key, ())]


def anchor_length_options(anchor_type: str) -> tuple[str, ...]:
    if anchor_type in INSERT_ANCHOR_LABELS:
        return tuple(map(str, INSERT_ANCHOR_LENGTHS + M_ANCHOR_LENGTHS))
    if anchor_type in (AnchorType.M_SHAPE, AnchorType.WELDED_M):
        return tuple(map(str, M_ANCHOR_LENGTHS))
    if anchor_type == AnchorType.DIAMOND.value:
        return tuple(map(str, DIAMOND_ANCHOR_LENGTHS))
    return ()


def _input_number(value: str | bool) -> float | None:
    try:
        parsed = float(str(value).strip().replace(",", ""))
    except ValueError:
        return None
    return parsed if isfinite(parsed) and parsed > 0 else None


def _anchor_remark(values: dict[str, str | bool]) -> str:
    anchor_type = values["anchor_type"]
    if not values["anchor_enabled"] or anchor_type not in WELDED_ANCHOR_TYPES:
        return _insert_anchor_note(values)
    exposure = _input_number(values["bolt_exposure_mm"])
    depth = _input_number(values["embedment_depth_mm"]) if anchor_type == AnchorType.WELDED_DIAMOND else 0.0
    return format_bolt_remark(exposure + depth, exposure) if exposure is not None and depth is not None else ""


def _automatic_anchor_length(values: dict[str, str | bool], length: float | None) -> str:
    tapered = bool(values["taper_enabled"])
    height = _input_number(values["big_head_mm"] if tapered else values["expansion_length_mm"])
    if height is None:
        return ""
    front_taper = tapered and values["taper_type"] == GeometryType.FRONT_TAPER.value
    if front_taper:
        small = _input_number(values["small_head_mm"])
        start = _input_number(values["anchor_position_mm"])
        spacing = _input_number(values["anchor_spacing_mm"])
        count = _input_number(values["anchor_count"])
        if (length is None or small is None or small >= height or start is None
                or spacing is None or count is None or not count.is_integer()):
            return ""
        end = start + spacing * (count - 1)
        if end > length:
            return ""
        # The standard editor places the big head at x=0. A common length must fit the shortest section.
        height -= (height - small) * end / length

    anchor_type = str(values["anchor_type"]).strip()
    if anchor_type == AnchorType.WELDED_DIAMOND:
        return ""
    if anchor_type in INSERT_ANCHOR_LABELS:
        target = round(height - 50, 2)
        if target < 250:
            target = next((size for size in M_ANCHOR_LENGTHS if size <= target), target)
    elif front_taper:
        target = round(height - 60, 2)
    else:
        sizes = map(int, anchor_length_options(anchor_type))
        target = next((size for size in sizes if height - 60 <= size <= height - 50),
                      round(height - 55, 2))
    return f"{target:g}" if target > 0 else ""


def resolve_automatic_values(
    values: dict[str, str | bool],
    fallback: dict[str, str | bool] | None = None,
) -> dict[str, str]:
    fields = automatic_fields(values)
    if not fields:
        return {}
    length = _input_number(values["length_mm"])
    density = _input_number(values["density_kg_m3"])
    grade = _input_number(_without_suffix(str(values["material"]), "材质", "板材"))
    thread = str(values["thread_spec"]).strip().upper()
    defaults = {}
    for key in AUTOMATIC_FALLBACK_KEYS:
        value = (fallback or {}).get(key)
        defaults[key] = str(value if value not in ("", AUTOMATIC, None) else DEFAULT_ROW[key])
    suggestions = {
        "structure_type": "半折叠" if length is not None and length > 600 else "折叠",
        "board_material": defaults["board_material"] if density is None else ("8厘" if density <= 192 else "9厘"),
        "anchor_material": (
            ("310" if grade >= 1430 else "304")
            if grade is not None else defaults["anchor_material"]
        ),
        "hose_spec": {"M10": "32", "M8": "25"}.get(thread, defaults["hose_spec"]),
        "source_note": _anchor_remark(values),
    }
    if "anchor_length_mm" in fields:
        suggestions["anchor_length_mm"] = _automatic_anchor_length(values, length)
    return {key: suggestions[key] for key in fields}


def row_values_from_models(
    module: ModuleParameters,
    board: BoardParameters | None,
    anchor: AnchorParameters | None,
    *,
    automatic: Collection[str] = (),
) -> dict[str, str | bool]:
    board_model = board or BoardParameters(module_id=module.module_id, exists=False)
    anchor_model = anchor or AnchorParameters(
        module_id=module.module_id,
        exists=False,
        anchor_type=AnchorType.NONE,
        count=0,
    )
    module_values = standard_module_values(module, board_model)
    anchor_values = standard_anchor_values(anchor_model)
    values = {
        "module_id": module_values.module_id,
        "length_mm": str(module_values.length_mm).removesuffix(".0"),
        "expansion_length_mm": f"{module_values.expansion_length_mm:g}",
        "thickness_mm": str(module_values.thickness_mm).removesuffix(".0"),
        "structure_type": module_values.custom_structure_label
        or STRUCTURE_LABEL_BY_TYPE.get(module_values.structure_type, "自定义"),
        "material": _without_suffix(module_values.material, "材质", "板材"),
        "production_quantity": str(module_values.production_quantity),
        "taper_enabled": module_values.taper_enabled,
        "big_head_mm": f"{module_values.big_head_mm:g}" if module_values.big_head_mm is not None else "289",
        "small_head_mm": f"{module_values.small_head_mm:g}" if module_values.small_head_mm is not None else "220",
        "taper_type": module_values.taper_type.value,
        "board_exists": module_values.board_exists,
        "board_material": _without_suffix(module_values.board_material, "夹板"),
        "show_upper_board": board_model.show_upper_board,
        "show_lower_board": board_model.show_lower_board,
        "anchor_enabled": anchor_values.enabled,
        "anchor_position_mm": f"{anchor_values.position_mm:g}",
        "anchor_spacing_mm": f"{anchor_values.spacing_mm:g}",
        "anchor_count": str(anchor_values.count),
        "anchor_type": anchor_values.custom_type_label
        or ANCHOR_LABEL_BY_TYPE.get(anchor_values.anchor_type, "M型"),
        "anchor_length_mm": f"{anchor_model.length_mm:g}" if anchor_model.length_mm is not None else "",
        "anchor_material": anchor_model.material,
        "thread_spec": anchor_model.thread_spec,
        "pin_diameter_mm": (
            f"{anchor_model.diameter_mm:g}" if anchor_model.diameter_mm is not None else ""
        ),
        "hose_spec": _without_suffix(
            anchor_model.hose_spec or anchor_values.hose_spec,
            "胶管",
        ),
        "embedment_depth_mm": (
            f"{anchor_values.embedment_depth_mm:g}"
            if anchor_values.embedment_depth_mm is not None
            else "" if anchor_values.anchor_type == AnchorType.WELDED_DIAMOND else "50"
        ),
        "bolt_exposure_mm": (f"{anchor_values.bolt_exposure_mm:g}"
                             if anchor_values.bolt_exposure_mm is not None else ""),
        "density_kg_m3": (
            f"{module_values.density_kg_m3:g}" if module_values.density_kg_m3 is not None else ""
        ),
        "source_note": module_values.source_note,
    }
    values.update({key: AUTOMATIC for key in AUTOMATIC_FIELDS if key in automatic})
    return values

def standard_board_face_bounds(values: dict[str, str | bool]) -> tuple[float, float]:
    module_id = str(values["module_id"]).strip()
    return (
        _number(str(values["length_mm"]), "长度", module_id),
        _number(str(values["thickness_mm"]), "厚度", module_id),
    )


def build_standard_row(
    values: dict[str, str | bool],
    bases: tuple[ModuleParameters | None, BoardParameters | None, AnchorParameters | None] = (
        None, None, None,
    ),
    *,
    board_face_profile: BoardFaceProfile | None = None,
    fallback: dict[str, str | bool] | None = None,
) -> tuple[ModuleParameters, BoardParameters, AnchorParameters]:
    module_id = str(values["module_id"]).strip()
    if not module_id:
        raise ValueError("模块编号不能为空")
    base_module, base_board, base_anchor = bases
    values = {**values, **resolve_automatic_values(values, fallback)}
    length, thickness = standard_board_face_bounds(values)
    structure_label = str(values["structure_type"]).strip()
    tapered = bool(values["taper_enabled"])
    big_head = _number(str(values["big_head_mm"]), "大头", module_id) if tapered else None
    module_values = StandardModuleValues(
        module_id=module_id,
        length_mm=length,
        expansion_length_mm=(
            big_head if big_head is not None
            else _number(str(values["expansion_length_mm"]), "膨胀长度", module_id)
        ),
        thickness_mm=thickness,
        structure_type=_structure_type(structure_label, module_id),
        custom_structure_label="" if structure_label == "自定义" else structure_label,
        taper_enabled=tapered,
        big_head_mm=big_head,
        small_head_mm=(
            _number(str(values["small_head_mm"]), "小头", module_id)
            if tapered
            else None
        ),
        taper_type=_geometry_type(str(values["taper_type"]), module_id) if tapered else GeometryType.FRONT_TAPER,
        board_exists=bool(values["board_exists"]),
        material=str(values["material"]),
        production_quantity=_integer(str(values["production_quantity"]), "模块数量", module_id),
        board_material=_board_material_value(str(values["board_material"]).strip() or "9厘"),
        density_kg_m3=_optional_number(str(values["density_kg_m3"]), "容重", module_id),
        source_note=str(values["source_note"]).strip(),
        board_face_profile=board_face_profile,
    )
    module = build_standard_module(base_module, module_values)
    board = build_standard_board(
        base_board,
        module.module_id,
        module_values.board_exists,
        module_values.board_material,
        show_upper_board=bool(values["show_upper_board"]) if "show_upper_board" in values else None,
        show_lower_board=bool(values["show_lower_board"]) if "show_lower_board" in values else None,
    )
    anchor = build_standard_anchor(
        base_anchor,
        module.module_id,
        module_values.length_mm,
        _anchor_values(values, module.module_id),
    )
    return module, board, anchor

def _geometry_type(value: str, module_id: str) -> GeometryType:
    try:
        return GeometryType(value)
    except ValueError:
        raise ValueError(f"{module_id}: 大小头类型必须是正敲或侧敲") from None

def _structure_type(value: str, module_id: str) -> StructureType:
    label = value.strip()
    structure = STRUCTURE_TYPE_BY_LABEL.get(label)
    if structure is not None:
        return structure
    try:
        return StructureType(label)
    except ValueError:
        if label in {"折叠模块", "折叠"}:
            return StructureType.FOLDED
        if label in {"半折叠模块", "半折叠"}:
            return StructureType.HALF_FOLDED
        if label in {"层叠模块", "层叠"}:
            return StructureType.STACKED
        if label:
            return StructureType.CUSTOM
        raise ValueError(f"{module_id}: 折叠方式不能为空") from None

def _anchor_values(values: dict[str, str | bool], module_id: str) -> StandardAnchorValues:
    enabled = bool(values["anchor_enabled"])
    type_label = str(values["anchor_type"]).strip()
    anchor_type = ANCHOR_TYPE_BY_LABEL.get(type_label)
    if anchor_type is None:
        try:
            anchor_type = AnchorType(type_label)
        except ValueError:
            anchor_type = AnchorType.CUSTOM
    if not enabled:
        pin_text = str(values["pin_diameter_mm"]).strip()
        return StandardAnchorValues(
            enabled=False,
            anchor_type=anchor_type,
            material=str(values["anchor_material"]).strip(),
            thread_spec=str(values["thread_spec"]).strip(),
            pin_diameter_mm=_optional_number(pin_text, "插针直径", module_id),
            hose_spec=_hose_value(str(values["hose_spec"]).strip()) or "32胶管",
        )
    if anchor_type == AnchorType.NONE:
        raise ValueError(f"{module_id}: 已勾选锚固件，必须选择锚固件类型")
    if not type_label:
        raise ValueError(f"{module_id}: 锚固件类型不能为空")
    embedment = None
    if anchor_type == AnchorType.DIAMOND:
        embedment = _number(str(values["embedment_depth_mm"]), "嵌入深度", module_id)
    elif anchor_type == AnchorType.WELDED_DIAMOND:
        embedment = _optional_number(str(values["embedment_depth_mm"]), "嵌入深度", module_id)
    exposure = None
    if anchor_type in WELDED_ANCHOR_TYPES:
        exposure = _optional_number(str(values.get("bolt_exposure_mm", "")), "螺栓外露长度", module_id)
    pin_text = str(values["pin_diameter_mm"]).strip()
    pin_diameter = (
        _number(pin_text, "插针直径", module_id)
        if pin_text and anchor_type not in DIAMOND_ANCHOR_TYPES
        else None
    )
    return StandardAnchorValues(
        enabled=True,
        position_mm=_number(str(values["anchor_position_mm"]), "锚固件位置", module_id),
        spacing_mm=_number(str(values["anchor_spacing_mm"]), "锚固件间距", module_id),
        count=_integer(str(values["anchor_count"]), "锚固件数量", module_id),
        anchor_type=anchor_type,
        custom_type_label="" if type_label == "自定义" else type_label,
        embedment_depth_mm=embedment,
        bolt_exposure_mm=exposure,
        material=str(values["anchor_material"]).strip(),
        thread_spec=str(values["thread_spec"]).strip(),
        pin_diameter_mm=pin_diameter,
        hose_spec=_hose_value(str(values["hose_spec"]).strip()) or "32胶管",
        length_mm=_optional_number(str(values["anchor_length_mm"]), "锚固件长度", module_id),
    )

