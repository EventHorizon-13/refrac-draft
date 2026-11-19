import pytest

from refracdraft.domain.models import (
    AnchorParameters, BoardParameters, GeometryType, ModuleParameters,
    OutlineKind, OutlineSpec, Project,
)
from refracdraft.drawing.generator import DrawingGenerator
from refracdraft.geometry.primitives import module_front_outline, parametric_outline


def module_with_outline(kind, width=300, height=230, **kwargs):
    return ModuleParameters(
        module_id="I1", front_width_mm=width, front_height_mm=height,
        board_face_width_mm=width, board_face_height_mm=height,
        board_face_outline=OutlineSpec(
            kind=kind, feature_width_mm=40, feature_height_mm=30, **kwargs,
        ),
    )


@pytest.mark.parametrize("kind", list(OutlineKind))
def test_board_contour_is_recomputed_for_two_sizes(kind):
    first = module_with_outline(kind, offset_mm=60 if kind == OutlineKind.EDGE_NOTCH else 0)
    second = module_with_outline(kind, width=420, height=280,
                                 offset_mm=60 if kind == OutlineKind.EDGE_NOTCH else 0)
    drawings = [DrawingGenerator().generate(Project(modules=[module])).pages[0].modules[0].drawing
                for module in (first, second)]
    a, b = (drawing.board_view.outline for drawing in drawings)
    assert a.bounds == (0, 0, 300, 230)
    assert b.bounds == (0, 0, 420, 280)
    assert (300 - 40, 0) in a.points if kind != OutlineKind.EDGE_NOTCH else (60, 30) in a.points
    assert (420 - 40, 0) in b.points if kind != OutlineKind.EDGE_NOTCH else (60, 30) in b.points
    for drawing in drawings:
        labels = [dimension.label for dimension in drawing.board_view.dimensions]
        assert "40" in labels and "30" in labels


def test_front_outline_is_computed_and_taper_is_not_silently_discarded():
    spec = OutlineSpec(kind=OutlineKind.CORNER_CUT, feature_width_mm=40, feature_height_mm=30)
    module = ModuleParameters(
        module_id="I1", front_width_mm=300, front_height_mm=230,
        board_face_width_mm=300, board_face_height_mm=230, front_outline=spec,
    )
    assert (260, 0) in module_front_outline(module).points
    drawing = DrawingGenerator().generate(Project(modules=[module])).pages[0].modules[0].drawing
    assert len(drawing.front_view.dimensions) == 4
    with pytest.raises(ValueError, match="侧敲正面异形组合尚未定义"):
        ModuleParameters(
            module_id="I1", geometry_type=GeometryType.FRONT_TAPER,
            front_width_mm=300, front_height_mm=230,
            front_left_height_mm=230, front_right_height_mm=200,
            board_face_width_mm=300, board_face_height_mm=230, front_outline=spec,
        )


def test_anchor_cannot_be_placed_in_removed_corner():
    module = module_with_outline(OutlineKind.CORNER_CUT)
    anchor = AnchorParameters(module_id="I1", positions=[{"x_mm": 290, "y_mm": 5}])
    with pytest.raises(ValueError, match="I1.*轮廓之外"):
        DrawingGenerator().generate(Project(modules=[module], anchors=[anchor]))


def test_invalid_feature_dimensions_and_template_conflict_are_rejected():
    with pytest.raises(ValueError, match="特征尺寸"):
        parametric_outline(300, 230, OutlineSpec(
            kind=OutlineKind.STEP, feature_width_mm=300, feature_height_mm=30,
        ))
    with pytest.raises(ValueError, match="开槽起点"):
        parametric_outline(300, 230, OutlineSpec(
            kind=OutlineKind.EDGE_NOTCH, feature_width_mm=40, feature_height_mm=30,
        ))
    with pytest.raises(ValueError, match="不能与参考 DXF 模板同时指定"):
        ModuleParameters(
            module_id="I1", front_width_mm=300, front_height_mm=230,
            board_face_width_mm=300, board_face_height_mm=230,
            board_face_template_id="irregular-5",
            board_face_outline=OutlineSpec(
                kind=OutlineKind.STEP, feature_width_mm=40, feature_height_mm=30,
            ),
        )


def test_no_board_retains_parametric_board_face():
    module = module_with_outline(OutlineKind.STEP)
    drawing = DrawingGenerator().generate(Project(
        modules=[module], boards=[BoardParameters(module_id="I1", exists=False)],
    )).pages[0].modules[0].drawing
    assert drawing.board_view.note == "无夹板"
    assert (260, 30) in drawing.board_view.outline.points

