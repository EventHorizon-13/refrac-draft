from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GeometryType(StrEnum):
    NORMAL = "普通"
    FRONT_TAPER = "正敲"
    SIDE_TAPER = "侧敲"


class StructureType(StrEnum):
    FOLDED = "折叠模块"
    HALF_FOLDED = "半折叠模块"
    STACKED = "层叠模块"
    CUSTOM = "自定义"
    OTHER = "其他"


class AnchorType(StrEnum):
    NONE = "无"
    M_SHAPE = "M型"
    DIAMOND = "菱形"
    SIDE_INSERT = "旁插"
    QUICK_INSERT = "快插"
    WELDED_M = "焊接M型"
    WELDED_DIAMOND = "焊接菱形"
    CUSTOM = "自定义"


DIAMOND_ANCHOR_TYPES = frozenset({AnchorType.DIAMOND, AnchorType.WELDED_DIAMOND})
WELDED_ANCHOR_TYPES = frozenset({AnchorType.WELDED_M, AnchorType.WELDED_DIAMOND})


def format_bolt_remark(length_mm: float, exposure_mm: float) -> str:
    return f"螺栓长度{length_mm:g}mm，外露{exposure_mm:g}mm"


class LayoutMode(StrEnum):
    EXPLICIT = "指定坐标"
    EQUAL = "均布"
    FIXED_SPACING = "指定间距"


class OpeningMode(StrEnum):
    NONE = "无开口"
    STANDARD = "标准开口"
    CUSTOM = "自定义开口"


class OutlineKind(StrEnum):
    CORNER_CUT = "corner-cut"
    EDGE_NOTCH = "edge-notch"
    STEP = "step"


class OutlineSpec(BaseModel):
    """Dimensions for an independently computed front or board-face contour.

    Features originate at the upper right, except the top-edge notch, whose
    offset is measured from the left. mirror_x reflects the result horizontally.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: OutlineKind
    feature_width_mm: float = Field(gt=0)
    feature_height_mm: float = Field(gt=0)
    offset_mm: float = Field(default=0, ge=0)
    mirror_x: bool = False


class BoardFaceFeature(BaseModel):
    """One perimeter cut from the illustrated board-face templates, in mm."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal[1, 2, 3, 4]
    a: float = Field(gt=0, allow_inf_nan=False)
    b: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    c: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    d: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    cut_depth_mm: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    rotation_deg: Literal[0, 90, 180, 270] = 0
    mirror_x: bool = False

    @model_validator(mode="after")
    def validate_dimensions(self) -> "BoardFaceFeature":
        required = {1: "ab", 2: "abcd", 3: "a", 4: "abc"}[self.type]
        supplied = "".join(key for key in "abcd" if getattr(self, key) is not None)
        if supplied != required:
            raise ValueError(f"夹板面类型 {self.type} 需要尺寸 {', '.join(required)}")
        return self


class BoardFaceProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    features: tuple[BoardFaceFeature, ...] = Field(min_length=1)


class Point2D(BaseModel):
    model_config = ConfigDict(frozen=True)
    x: float
    y: float


class ModuleParameters(BaseModel):
    """Module geometry and production data; independent of board and anchor data."""

    model_config = ConfigDict(extra="forbid")

    module_id: str = Field(min_length=1)
    name: str = ""
    structure_type: StructureType = StructureType.FOLDED
    custom_structure_label: str = ""
    geometry_type: GeometryType = GeometryType.NORMAL

    # Front view. For 正敲, use the two end heights; for 普通 use front_height_mm.
    front_width_mm: float = Field(gt=0)
    front_height_mm: float = Field(gt=0)
    # Uncompressed module length from the source dynamic blocks. The standard
    # editor always writes it and older files derive it from front_height_mm.
    expansion_length_mm: float | None = Field(default=None, gt=0)
    front_left_height_mm: float | None = Field(default=None, gt=0)
    front_right_height_mm: float | None = Field(default=None, gt=0)

    # Side view. Used only by 侧敲.
    side_length_mm: float | None = Field(default=None, gt=0)
    side_left_height_mm: float | None = Field(default=None, gt=0)
    side_right_height_mm: float | None = Field(default=None, gt=0)

    # Board-face outline dimensions and source-DXF template ID.
    board_face_width_mm: float = Field(gt=0)
    board_face_height_mm: float = Field(gt=0)
    board_face_template_id: str = "rectangular"
    front_outline: OutlineSpec | None = None
    board_face_outline: OutlineSpec | BoardFaceProfile | None = None

    material: str = ""
    density_kg_m3: float | None = Field(default=None, gt=0)
    production_quantity: int = Field(default=1, ge=1)
    source_note: str = ""

    @model_validator(mode="before")
    @classmethod
    def preserve_saved_taper_geometry(cls, data):
        # Older project files used the opposite labels. Their dimensions select the face.
        if not isinstance(data, dict) or type(data.get("geometry_type")) is not str:
            return data
        if data["geometry_type"] not in (GeometryType.FRONT_TAPER, GeometryType.SIDE_TAPER):
            return data
        front = all(data.get(key) is not None for key in ("front_left_height_mm", "front_right_height_mm"))
        side = all(data.get(key) is not None for key in ("side_length_mm", "side_left_height_mm", "side_right_height_mm"))
        if front != side:
            return {**data, "geometry_type": GeometryType.FRONT_TAPER if front else GeometryType.SIDE_TAPER}
        return data

    @property
    def minimum_expansion_mm(self) -> float:
        return min(value for value in (
            self.expansion_length_mm, self.front_height_mm,
            self.front_left_height_mm, self.front_right_height_mm,
            self.side_left_height_mm, self.side_right_height_mm,
        ) if value is not None)

    @model_validator(mode="after")
    def validate_geometry(self) -> "ModuleParameters":
        if self.expansion_length_mm is None:
            self.expansion_length_mm = self.front_height_mm
        if self.front_outline and self.geometry_type == GeometryType.FRONT_TAPER:
            raise ValueError("正敲正面异形组合尚未定义，不能忽略异形参数")
        if self.board_face_outline and self.board_face_template_id != "rectangular":
            raise ValueError("参数化夹板面轮廓不能与参考 DXF 模板同时指定")
        if self.geometry_type == GeometryType.FRONT_TAPER:
            if self.front_left_height_mm is None or self.front_right_height_mm is None:
                raise ValueError("正敲模块必须输入正面两端高度 front_left_height_mm / front_right_height_mm")
        if self.geometry_type == GeometryType.SIDE_TAPER:
            required = (self.side_length_mm, self.side_left_height_mm, self.side_right_height_mm)
            if any(v is None for v in required):
                raise ValueError("侧敲模块必须输入侧面长度和侧面两端高度")
        if isinstance(self.board_face_outline, BoardFaceProfile):
            for index, feature in enumerate(self.board_face_outline.features, 1):
                if feature.cut_depth_mm is not None and feature.cut_depth_mm > self.minimum_expansion_mm:
                    raise ValueError(f"{self.module_id}: 切口 {index} 的剪切深度不能超过 {self.minimum_expansion_mm:g} mm")
        return self


class BoardParameters(BaseModel):
    """Physical board properties; the outline comes from ModuleParameters."""

    model_config = ConfigDict(extra="forbid")

    module_id: str = Field(min_length=1)
    exists: bool = True
    material: str = "9厘夹板"
    thickness_mm: float | None = Field(default=None, gt=0)
    opening_mode: OpeningMode = OpeningMode.NONE
    # Custom opening polygon is expressed in board-face local millimetres.
    custom_opening: list[Point2D] = Field(default_factory=list)
    source_note: str = ""

    @model_validator(mode="after")
    def validate_opening(self) -> "BoardParameters":
        if self.opening_mode == OpeningMode.CUSTOM and len(self.custom_opening) < 3:
            raise ValueError("自定义开口至少需要 3 个顶点")
        return self


class AnchorPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    x_mm: float
    y_mm: float


class AnchorParameters(BaseModel):
    """Anchor properties and layout; independent of module and board properties."""

    model_config = ConfigDict(extra="forbid")

    module_id: str = Field(min_length=1)
    exists: bool = True
    anchor_type: AnchorType = AnchorType.M_SHAPE
    custom_type_label: str = ""
    material: str = "310"
    thread_spec: str = "M10"
    diameter_mm: float | None = Field(default=None, gt=0)
    length_mm: float | None = Field(default=None, gt=0)
    # Source dynamic-block parameter used by diamond anchors.
    embedment_depth_mm: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    bolt_exposure_mm: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    count: int = Field(default=1, ge=0)
    layout_mode: LayoutMode = LayoutMode.EXPLICIT
    positions: list[AnchorPosition] = Field(default_factory=list)
    edge_offset_mm: float = Field(default=150, ge=0)
    spacing_mm: float | None = Field(default=None, gt=0)
    hose_spec: str = ""
    dimension_horizontal: bool = False
    dimension_vertical: bool = False
    source_note: str = ""

    @property
    def bolt_length_mm(self) -> float | None:
        if self.anchor_type not in WELDED_ANCHOR_TYPES or self.bolt_exposure_mm is None:
            return None
        if self.anchor_type == AnchorType.WELDED_M:
            return self.bolt_exposure_mm
        if self.embedment_depth_mm is None:
            return None
        return self.bolt_exposure_mm + self.embedment_depth_mm

    @field_validator("material", "thread_spec", mode="before")
    @classmethod
    def normalize_empty_text(cls, value):
        return "" if value is None else value

    @model_validator(mode="after")
    def validate_layout(self) -> "AnchorParameters":
        if not self.exists or self.anchor_type == AnchorType.NONE:
            return self
        if self.anchor_type == AnchorType.DIAMOND and self.embedment_depth_mm is None:
            self.embedment_depth_mm = 50.0
        if self.layout_mode == LayoutMode.EXPLICIT and self.count and len(self.positions) != self.count:
            raise ValueError("指定坐标模式下，锚固件数量必须与坐标数量一致")
        if self.layout_mode == LayoutMode.FIXED_SPACING and self.spacing_mm is None:
            raise ValueError("指定间距模式必须输入 spacing_mm")
        return self


class ProjectMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_name: str = "模块详情图"
    project_unit: str = ""
    order_number: str = ""
    drawing_number: str = ""
    designer: str = ""
    checker: str = ""


class Project(BaseModel):
    """Three peer parameter tables, associated only by module_id."""

    model_config = ConfigDict(extra="forbid")
    metadata: ProjectMetadata = Field(default_factory=ProjectMetadata)
    modules: list[ModuleParameters] = Field(default_factory=list)
    boards: list[BoardParameters] = Field(default_factory=list)
    anchors: list[AnchorParameters] = Field(default_factory=list)
    standard_auto_fields: dict[str, list[str]] = Field(default_factory=dict)
    standard_link_version: int = 1

    @model_validator(mode="after")
    def validate_relations(self) -> "Project":
        ids = [m.module_id for m in self.modules]
        if len(ids) != len(set(ids)):
            raise ValueError("模块编号重复")
        known = set(ids)
        for group_name, group in (("夹板", self.boards), ("锚固件", self.anchors)):
            refs = [item.module_id for item in group]
            if len(refs) != len(set(refs)):
                raise ValueError(f"{group_name}参数中模块编号重复")
            unknown = set(refs) - known
            if unknown:
                raise ValueError(f"{group_name}参数引用了不存在的模块编号: {', '.join(sorted(unknown))}")
        return self

    def board_for(self, module_id: str) -> BoardParameters:
        return next((x for x in self.boards if x.module_id == module_id), BoardParameters(module_id=module_id))

    def anchor_for(self, module_id: str) -> AnchorParameters:
        return next(
            (x for x in self.anchors if x.module_id == module_id),
            AnchorParameters(module_id=module_id, exists=False, anchor_type=AnchorType.NONE, count=0),
        )

