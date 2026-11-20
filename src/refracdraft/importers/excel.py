from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from refracdraft.domain.models import (
    AnchorParameters, BoardFaceFeature, BoardFaceProfile, BoardParameters, GeometryType, ModuleParameters, Project,
)
from refracdraft.standard_sheet import (
    COLUMN_SPECS, DEFAULT_ROW, PROFILE_COLUMNS, PROFILE_SHEET, automatic_fields, build_standard_row,
)


SHEET_ALIASES = {
    "modules": {"modules", "模块", "模块参数", "模块清单"},
    "boards": {"boards", "夹板", "夹板参数"},
    "anchors": {"anchors", "锚固件", "锚固件参数"},
}

FIELD_ALIASES = {
    "modules": {
        "module_id": {"模块编号", "编号", "型号", "模块型号"},
        "name": {"模块名称", "名称"},
        "structure_type": {"结构类型", "模块结构", "折叠方式"},
        "geometry_type": {"几何类型", "模块几何", "敲型"},
        "front_width_mm": {"正面宽度", "正面长度", "正面宽度mm", "宽度", "长度"},
        "front_height_mm": {"正面高度", "高度"},
        "expansion_length_mm": {"膨胀长度", "展开长度", "膨胀长度mm"},
        "front_left_height_mm": {"正面左高", "左端高度", "左侧高度", "大头高度", "大头", "长边"},
        "front_right_height_mm": {"正面右高", "右端高度", "右侧高度", "小头高度", "小头", "短边"},
        "side_length_mm": {"侧面长度", "侧面宽度"},
        "side_left_height_mm": {"侧面左高", "侧面左端高度", "侧面大头"},
        "side_right_height_mm": {"侧面右高", "侧面右端高度", "侧面小头"},
        "board_face_width_mm": {"夹板面宽度", "夹板面长度", "夹板宽度"},
        "board_face_height_mm": {"夹板面高度", "夹板高度"},
        "board_face_template_id": {"夹板面类型", "夹板面模板", "异形夹板面"},
        "material": {"材质", "模块材质"},
        "density_kg_m3": {"容重", "密度", "容重kgm3"},
        "production_quantity": {"模块数量", "生产数量", "数量"},
        "source_note": {"备注", "来源说明", "待确认事项"},
    },
    "boards": {
        "module_id": {"模块编号", "编号", "型号", "模块型号"},
        "exists": {"是否有夹板", "有无夹板", "夹板是否存在"},
        "material": {"夹板材质", "材质", "夹板"},
        "thickness_mm": {"夹板厚度", "厚度"},
        "opening_mode": {"开口模式", "快插开口", "开口类型"},
        "custom_opening": {"自定义开口坐标", "开口坐标"},
        "source_note": {"备注", "来源说明", "待确认事项"},
    },
    "anchors": {
        "module_id": {"模块编号", "编号", "型号", "模块型号"},
        "exists": {"是否有锚固件", "有无锚固件"},
        "anchor_type": {"锚固件类型", "锚固件形式", "锚固件", "类型"},
        "material": {"锚固件材质", "材质"},
        "thread_spec": {"螺纹规格", "规格", "螺纹"},
        "diameter_mm": {"直径", "锚固件直径"},
        "length_mm": {"锚固件长度", "长度"},
        "embedment_depth_mm": {"嵌入深度", "埋入深度", "锚固件嵌入深度"},
        "count": {"锚固件数量", "锚固件个数", "数量"},
        "layout_mode": {"布置方式", "排列方式"},
        "positions": {"锚固件坐标", "坐标", "位置坐标"},
        "edge_offset_mm": {"端部留边", "边距", "锚固件位置", "位置"},
        "spacing_mm": {"锚固件间距", "间距"},
        "hose_spec": {"胶管规格", "胶管"},
        "dimension_horizontal": {"标注水平定位尺寸", "水平定位尺寸", "是否标注水平定位"},
        "dimension_vertical": {"标注垂直定位尺寸", "垂直定位尺寸", "是否标注垂直定位"},
        "source_note": {"备注", "来源说明", "待确认事项"},
    },
}


def _rows(ws) -> list[dict[str, Any]]:
    values = list(ws.iter_rows(values_only=True))
    if not values:
        return []
    headers = [str(v).strip() if v is not None else "" for v in values[0]]
    result = []
    for row in values[1:]:
        if not any(v is not None for v in row):
            continue
        result.append({headers[i]: row[i] for i in range(min(len(headers), len(row))) if headers[i]})
    return result


def _number(value: Any) -> Any:
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        match = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*(?:mm|毫米|kg/m3|kg/m³)?", cleaned, re.I)
        if match:
            return float(match.group(1))
    return value


def _bool(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"有", "是", "√", "yes", "true", "1", "存在"}:
            return True
        if v in {"无", "否", "×", "no", "false", "0", "不存在"}:
            return False
    return value


def _enum_value(field: str, value: Any) -> Any:
    if not isinstance(value, str):
        return value
    v = value.strip()
    if field == "anchor_type":
        for token, normalized in (("无", "无"), ("M型", "M型"), ("M形", "M型"),
                                  ("焊接菱形", "焊接菱形"), ("菱形", "菱形"),
                                  ("旁插", "旁插"), ("快插", "快插")):
            if token in v:
                return normalized
    if field == "geometry_type":
        if "侧敲" in v:
            return "侧敲"
        if "正敲" in v:
            return "正敲"
        if "普通" in v:
            return "普通"
    if field == "structure_type":
        if "半折叠" in v:
            return "半折叠模块"
        if "折叠" in v:
            return "折叠模块"
        if "层叠" in v:
            return "层叠模块"
        if "自定义" in v:
            return "自定义"
    if field == "layout_mode":
        if "均布" in v:
            return "均布"
        if "间距" in v:
            return "指定间距"
        if "坐标" in v:
            return "指定坐标"
    if field == "opening_mode":
        if "标准" in v:
            return "标准开口"
        if "自定义" in v:
            return "自定义开口"
        if "无" in v:
            return "无开口"
    return v


def _normalize_row(row: dict[str, Any], group: str) -> dict[str, Any]:
    aliases = FIELD_ALIASES[group]
    reverse = {alias: field for field, values in aliases.items() for alias in values}
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        if value is None or value == "":
            continue
        key_clean = str(key).strip()
        field = key_clean if key_clean in aliases else reverse.get(key_clean)
        if not field:
            continue
        if field in {"exists", "dimension_horizontal", "dimension_vertical"}:
            value = _bool(value)
        elif field in {"front_width_mm", "front_height_mm", "expansion_length_mm", "front_left_height_mm", "front_right_height_mm",
                       "side_length_mm", "side_left_height_mm", "side_right_height_mm", "board_face_width_mm",
                       "board_face_height_mm", "density_kg_m3", "production_quantity", "thickness_mm",
                       "diameter_mm", "length_mm", "embedment_depth_mm", "count", "edge_offset_mm", "spacing_mm"}:
            value = _number(value)
        elif field in {"geometry_type", "structure_type", "anchor_type", "layout_mode", "opening_mode"}:
            value = _enum_value(field, value)
        elif field in {"positions", "custom_opening"} and isinstance(value, str):
            value = json.loads(value) if value.strip().startswith("[") else value
        normalized[field] = value
    if group == "modules" and normalized.get("geometry_type") in (
        GeometryType.FRONT_TAPER, GeometryType.SIDE_TAPER,
    ) and (
        normalized.get("geometry_type") == GeometryType.SIDE_TAPER
        or "side_length_mm" in normalized
    ):
        header_names = {str(name).strip() for name in row}
        for front_field, side_field, generic_headers in (
            ("front_left_height_mm", "side_left_height_mm", {"大头", "大头高度", "长边"}),
            ("front_right_height_mm", "side_right_height_mm", {"小头", "小头高度", "短边"}),
        ):
            if side_field not in normalized and front_field in normalized and header_names & generic_headers:
                normalized[side_field] = normalized.pop(front_field)
    return normalized


def _profiles(ws) -> dict[str, BoardFaceProfile]:
    features: dict[str, list[BoardFaceFeature]] = {}
    for number, row in enumerate(_rows(ws), start=2):
        try:
            module_id, kind, a, b, c, d, angle, mirror = (row.get(key) for key in PROFILE_COLUMNS)
            if module_id is None or not str(module_id).strip():
                raise ValueError("缺少编号")
            cuts = features.setdefault(str(module_id).strip(), [])
            cuts.append(BoardFaceFeature(type=kind, a=a, b=b, c=c, d=d,
                                         rotation_deg=angle or 0, mirror_x=_bool(mirror) if mirror is not None else False))
        except ValueError as exc:
            raise ValueError(f"「{PROFILE_SHEET}」第 {number} 行：{exc}") from exc
    return {key: BoardFaceProfile(features=value) for key, value in features.items()}


def _import_standard_sheet(ws, headers: list[str], profiles: dict[str, BoardFaceProfile]) -> Project:
    columns = {label: index for index, label in enumerate(headers)}
    if len(columns) != len(COLUMN_SPECS) or set(columns) != {spec.label for spec in COLUMN_SPECS}:
        raise ValueError("「标准版」表头不完整或有重复列，请使用程序附带的示例")
    modules = []
    boards = []
    anchors = []
    auto_fields = {}
    for number, cells in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not any(value is not None and value != "" for value in cells):
            continue
        values = DEFAULT_ROW.copy()
        for spec in COLUMN_SPECS:
            value = cells[columns[spec.label]]
            if spec.kind == "check":
                parsed = False if value is None else _bool(value)
                if not isinstance(parsed, bool):
                    raise ValueError(f"Excel 第 {number} 行「{spec.label}」应填 TRUE/FALSE 或是/否")
                values[spec.key] = parsed
            else:
                values[spec.key] = "" if value is None else str(value).strip()
        try:
            module, board, anchor = build_standard_row(values, board_face_profile=profiles.get(values["module_id"]))
        except ValueError as exc:
            raise ValueError(f"Excel 第 {number} 行：{exc}") from exc
        modules.append(module)
        boards.append(board)
        anchors.append(anchor)
        fields = automatic_fields(values)
        if fields:
            auto_fields[module.module_id] = fields
    if not modules:
        raise ValueError("「标准版」工作表没有模块数据")
    missing = profiles.keys() - {module.module_id for module in modules}
    if missing:
        raise ValueError(f"「{PROFILE_SHEET}」包含未知模块：{'，'.join(sorted(missing))}")
    return Project(modules=modules, boards=boards, anchors=anchors, standard_auto_fields=auto_fields)


def _import_legacy_sheets(wb) -> Project:
    found: dict[str, list[dict[str, Any]]] = {"modules": [], "boards": [], "anchors": []}
    for ws in wb.worksheets:
        name = ws.title.strip().lower()
        for group, aliases in SHEET_ALIASES.items():
            if name in aliases:
                found[group] = [_normalize_row(row, group) for row in _rows(ws)]
                break
    if not found["modules"]:
        raise ValueError("Excel 中未找到「模块参数」工作表")
    modules = [ModuleParameters.model_validate(row) for row in found["modules"]]
    boards = [BoardParameters.model_validate(row) for row in found["boards"]]
    anchors = [AnchorParameters.model_validate(row) for row in found["anchors"]]
    return Project(modules=modules, boards=boards, anchors=anchors)


def import_project_xlsx(path: str | Path) -> Project:
    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        labels = {spec.label for spec in COLUMN_SPECS}
        for ws in wb.worksheets:
            row = next(ws.iter_rows(max_row=1, values_only=True), ())
            headers = [str(value).strip() if value is not None else "" for value in row]
            while headers and not headers[-1]:
                headers.pop()
            if ws.title.strip() == "标准版" or set(headers) == labels:
                profiles = _profiles(wb[PROFILE_SHEET]) if PROFILE_SHEET in wb.sheetnames else {}
                return _import_standard_sheet(ws, headers, profiles)
        return _import_legacy_sheets(wb)
    finally:
        wb.close()

