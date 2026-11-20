import pytest

from refracdraft.domain.models import (
    AnchorParameters, BoardFaceProfile, BoardParameters, GeometryType, ModuleParameters,
    OutlineKind, OutlineSpec, Project,
)
from refracdraft.drawing.board_profiles import build_board_profile
from refracdraft.drawing.generator import DrawingGenerator
from refracdraft.drawing.layout import (
    FRAME_INSET_MM, PAGE_HEIGHT_MM, VIEW_CLEARANCE_MM, view_bounds, view_placement,
)
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


@pytest.mark.parametrize(("feature", "point", "labels"), [
    ({"type": 1, "a": 250, "b": 42}, (250, 42), {"250", "42"}),
    ({"type": 2, "a": 72, "b": 95, "c": 75, "d": 48}, (47, 147), {"72", "95", "75", "48"}),
    ({"type": 3, "a": 250}, (50, 230), {"250"}),
    ({"type": 4, "a": 100, "b": 85, "c": 145}, (215, 85), {"100", "85", "145"}),
])
def test_illustrated_board_profiles_use_the_annotated_dimensions(feature, point, labels):
    profile = BoardFaceProfile.model_validate({"features": [feature]})
    outline, dimensions = build_board_profile(300, 230, profile)
    assert outline.closed and outline.bounds == (0, 0, 300, 230)
    assert point in outline.points
    assert {dimension.label for dimension in dimensions} == labels


def test_board_profile_rotation_mirror_and_multiple_cuts():
    profile = BoardFaceProfile.model_validate({"features": [
        {"type": 1, "a": 85, "b": 35, "rotation_deg": 270},
        {"type": 3, "a": 255, "mirror_x": True},
    ]})
    outline, dimensions = build_board_profile(300, 230, profile)
    assert outline.bounds == (0, 0, 300, 230)
    assert (35, 145) in outline.points
    assert (255, 230) in outline.points
    assert [(dim.label, dim.orientation) for dim in dimensions] == [
        ("85", "vertical"), ("35", "horizontal"), ("255", "horizontal"),
    ]


def test_board_profile_rejects_overlapping_cuts():
    profile = BoardFaceProfile.model_validate({"features": [
        {"type": 1, "a": 85, "b": 35},
        {"type": 3, "a": 250},
    ]})
    with pytest.raises(ValueError, match="同一段边缘"):
        build_board_profile(300, 230, profile)


def test_board_profile_hidden_projection_and_dimension_lanes():
    profile = BoardFaceProfile.model_validate({"features": [
        {"type": 2, "a": 69, "b": 90, "c": 69, "d": 45},
    ]})
    module = ModuleParameters(
        module_id="M1", front_width_mm=300, front_height_mm=300,
        board_face_width_mm=300, board_face_height_mm=230, board_face_outline=profile,
    )
    drawing = DrawingGenerator().build_module(Project(modules=[module]), module)
    assert not drawing.front_view.internal_lines
    assert [line.points for line in drawing.front_view.hidden_lines] == [
        ((45, 0), (45, 300)), ((90, 0), (90, 300)),
    ]
    overall_width, overall_height, lower_step, notch_width, notch_height, shoulder = (
        drawing.board_view.dimensions[:6]
    )
    assert overall_width.line_position < notch_width.line_position < 0
    assert overall_height.line_position < lower_step.line_position < 0
    assert 0 < notch_height.line_position < 45
    assert shoulder.line_position > 230


@pytest.mark.parametrize(("rotation", "labels", "datum", "side_x", "front_solid", "side_solid"), [
    (270, ("104", "150"), (46, 230), 120, False, True),
    (0, ("150", "150"), (0, 46), 184, True, True),
    (180, ("150", "30"), (180, 230), 46, False, False),
    (90, ("150", "150"), (300, 120), 110, True, False),
])
def test_board_profile_datums_and_line_visibility(rotation, labels, datum, side_x, front_solid, side_solid):
    profile = BoardFaceProfile.model_validate({"features": [
        {"type": 1, "a": 120, "b": 46, "rotation_deg": rotation},
    ]})
    module = ModuleParameters(
        module_id="M1", geometry_type=GeometryType.SIDE_TAPER, front_width_mm=300, front_height_mm=289,
        side_length_mm=230, side_left_height_mm=289, side_right_height_mm=220,
        board_face_width_mm=300, board_face_height_mm=230, board_face_outline=profile,
    )
    anchor = AnchorParameters(
        module_id="M1", positions=[{"x_mm": 150, "y_mm": 190}], dimension_horizontal=True,
    )
    drawing = DrawingGenerator().build_module(Project(modules=[module], anchors=[anchor]), module)
    dimensions = drawing.board_view.dimensions[-2:]
    assert tuple(dimension.label for dimension in dimensions) == labels
    assert datum in (dimensions[0].start, dimensions[-1].end)
    assert all((150, 230) in (dimension.start, dimension.end) for dimension in dimensions)
    for view, solid in ((drawing.front_view, front_solid), (drawing.side_view, side_solid)):
        solid_verticals = [line for line in view.internal_lines if line.points[0][0] == line.points[1][0]]
        assert len(solid_verticals) == int(solid)
        assert len(view.hidden_lines) == int(not solid)
    side_edges = drawing.side_view.internal_lines if side_solid else drawing.side_view.hidden_lines
    assert any(line.points[0][0] == side_x == line.points[1][0] for line in side_edges)


def test_mixed_rotated_board_profile_marks_exposed_steps_and_missing_lengths():
    profile = BoardFaceProfile.model_validate({"features": [
        {"type": 2, "a": 69, "b": 90, "c": 69, "d": 45, "rotation_deg": 90},
        {"type": 1, "a": 120, "b": 46, "rotation_deg": 270},
    ]})
    module = ModuleParameters(
        module_id="M1", front_width_mm=300, front_height_mm=300,
        board_face_width_mm=300, board_face_height_mm=230, board_face_outline=profile,
    )
    drawing = DrawingGenerator().build_module(Project(modules=[module]), module)
    assert [line.points[0][0] for line in drawing.front_view.internal_lines] == [162, 231]
    assert [line.points[0][0] for line in drawing.front_view.hidden_lines] == [46]
    labels = {(dim.orientation, dim.label) for dim in drawing.board_view.dimensions}
    assert {("horizontal", "162"), ("horizontal", "254"), ("vertical", "65")} <= labels


def test_tall_board_dimensions_keep_clear_of_the_front_view():
    profile = BoardFaceProfile.model_validate({"features": [
        {"type": 2, "a": 69, "b": 90, "c": 69, "d": 45},
    ]})
    module = ModuleParameters(
        module_id="M1", front_width_mm=300, front_height_mm=300,
        board_face_width_mm=300, board_face_height_mm=450, board_face_outline=profile,
    )
    anchor = AnchorParameters(
        module_id="M1", anchor_type="快插", positions=[{"x_mm": 150, "y_mm": 420}],
        dimension_horizontal=True,
    )
    drawing = DrawingGenerator().build_module(Project(modules=[module], anchors=[anchor]), module)
    placement = view_placement(drawing)
    _, front_bottom, _, front_top = view_bounds(drawing.front_view)
    _, _, _, board_top = view_bounds(drawing.board_view)
    assert placement.top_y + front_bottom - (placement.board_y + board_top) >= VIEW_CLEARANCE_MM - 1e-8
    assert placement.top_y + front_top <= PAGE_HEIGHT_MM - FRAME_INSET_MM

