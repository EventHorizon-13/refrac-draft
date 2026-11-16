import pytest

from refracdraft.domain.models import GeometryType, ModuleParameters, Project
from refracdraft.importers.excel import _normalize_row
from refracdraft.standard import ensure_standard_project


def module(module_id="M1", geometry_type=GeometryType.NORMAL, **extra):
    fields = dict(
        module_id=module_id, geometry_type=geometry_type,
        front_width_mm=300, front_height_mm=300,
        board_face_width_mm=300, board_face_height_mm=230,
    )
    if geometry_type == GeometryType.FRONT_TAPER:
        fields.update(front_left_height_mm=300, front_right_height_mm=220)
    if geometry_type == GeometryType.SIDE_TAPER:
        fields.update(side_length_mm=300, side_left_height_mm=300, side_right_height_mm=220)
    fields.update(extra)
    return ModuleParameters(**fields)


@pytest.mark.parametrize("geometry_type", list(GeometryType))
def test_standard_edition_accepts_three_existing_geometry_types(geometry_type):
    ensure_standard_project(Project(modules=[module(geometry_type=geometry_type)]))


@pytest.mark.parametrize("extra", [
    {"front_outline": {"kind": "corner-cut", "feature_width_mm": 40, "feature_height_mm": 30}},
    {"board_face_outline": {"kind": "step", "feature_width_mm": 40, "feature_height_mm": 30}},
    {"board_face_template_id": "irregular-5"},
])
def test_standard_edition_rejects_irregular_geometry_with_module_id(extra):
    with pytest.raises(ValueError, match="M1.*异形"):
        ensure_standard_project(Project(modules=[module(**extra)]))


def test_welded_diamond_type_survives_unified_input_normalization():
    assert _normalize_row({"anchor_type": "焊接菱形"}, "anchors")["anchor_type"] == "焊接菱形"

