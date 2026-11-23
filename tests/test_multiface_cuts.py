import pytest

from refracdraft.domain.models import BoardFaceFeature, BoardFaceProfile, CutFace, CutStart, Project
from refracdraft.drawing.generator import DrawingGenerator
from refracdraft.drawing.multiface import machined_module, project_module
from refracdraft.exporters.project import export_standard_excel
from refracdraft.importers.excel import import_project_xlsx
from refracdraft.standard_sheet import DEFAULT_ROW, build_standard_row


def _project(*cuts, **settings):
    profile = BoardFaceProfile(features=cuts)
    module, plate, hardware = build_standard_row({
        **DEFAULT_ROW, "length_mm": "300", "thickness_mm": "200",
        "expansion_length_mm": "180", **settings,
    }, board_face_profile=profile)
    return Project(modules=[module], boards=[plate], anchors=[hardware]), profile


def _segment_contains(lines, x, y):
    for line in lines:
        points = line.points + line.points[:1] if line.closed else line.points
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            if (min(x1, x2) - 1e-6 <= x <= max(x1, x2) + 1e-6
                and min(y1, y2) - 1e-6 <= y <= max(y1, y2) + 1e-6
                and abs((x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)) < 1e-5):
                return True
    return False


def test_intersecting_cuts_remove_the_union_and_project_actual_stop_edges(tmp_path):
    front = BoardFaceFeature(face=CutFace.FRONT, type=1, a=50, b=40, cut_depth_mm=80)
    side = BoardFaceFeature(face=CutFace.SIDE, type=1, a=60, b=55, cut_depth_mm=80, mirror_x=True)
    project, profile = _project(front, side)
    module = project.modules[0]
    assert (front.cut_start, side.cut_start) == (CutStart.FRONT, CutStart.LEFT)
    solid = machined_module(module, profile)
    # 50×40×80 and 60×55×80 overlap by 50×60×40.
    assert solid.volume() == pytest.approx(300 * 200 * 180 - 160000 - 264000 + 120000)
    reversed_profile = BoardFaceProfile(features=(side, front))
    assert machined_module(module, reversed_profile).volume() == pytest.approx(solid.volume())
    front_view = project_module(solid, module, CutFace.FRONT)
    assert _segment_contains(front_view.visible, 70, 55)
    assert _segment_contains(front_view.visible, 25, 40)
    for x, z, floor in ((25, 25, 80), (25, 45, 60), (70, 25, 60), (85, 25, 0)):
        assert solid.ray_cast((x, -1, z), (x, 201, z))[0].position[1] == pytest.approx(floor)
    drawing = DrawingGenerator().generate(project).pages[0].modules[0].drawing
    assert drawing.side_view is not None
    assert [note.text for note in drawing.front_view.leaders] == ["正面起切 深80"]
    assert [note.text for note in drawing.side_view.leaders] == ["左端起切 深80"]
    assert Project.model_validate_json(project.model_dump_json()).modules[0].board_face_outline == profile
    excel = tmp_path / "多面.xlsx"
    export_standard_excel(project, excel)
    assert import_project_xlsx(excel).modules[0].board_face_outline == profile


@pytest.mark.parametrize("start,wall_visible", [(CutStart.FRONT, True), (CutStart.BACK, False)])
def test_front_blind_cut_direction_controls_visibility(start, wall_visible):
    cut = BoardFaceFeature(face=CutFace.FRONT, cut_start=start, type=1, a=50, b=40, cut_depth_mm=80)
    project, profile = _project(cut)
    module = project.modules[0]
    solid = machined_module(module, profile)
    projection = project_module(solid, module, CutFace.FRONT)
    assert _segment_contains(projection.visible, 25, 40) == wall_visible
    assert _segment_contains(projection.hidden, 25, 40) != wall_visible


@pytest.mark.parametrize("depth", [None, 300])
def test_through_cut_is_a_contour_without_depth_note(depth):
    cut = BoardFaceFeature(face=CutFace.SIDE, type=1, a=60, b=55, cut_depth_mm=depth)
    project, _ = _project(cut)
    drawing = DrawingGenerator().generate(project).pages[0].modules[0].drawing
    side = drawing.side_view
    assert (60, 55) in side.outline.points
    assert (0, 0) not in side.outline.points
    assert not side.leaders


def test_plate_depth_follows_sloping_surface_in_multiface_module():
    plate = BoardFaceFeature(type=1, a=50, b=40, cut_start=CutStart.UPPER, cut_depth_mm=35)
    front = BoardFaceFeature(face=CutFace.FRONT, type=1, a=40, b=40, mirror_x=True, cut_depth_mm=35)
    project, profile = _project(plate, front, taper_enabled=True, taper_type="正敲", big_head_mm="200", small_head_mm="120")
    solid = machined_module(project.modules[0], profile)
    for x in (10, 40):
        hits = solid.ray_cast((x, 20, 215), (x, 20, -1))
        assert hits[0].position[2] == pytest.approx(200 - 40 * x / 300 - 35)


def test_reject_depth_beyond_selected_face_and_mismatched_origin():
    with pytest.raises(ValueError, match="起切面"):
        BoardFaceFeature(face=CutFace.SIDE, cut_start=CutStart.BACK, type=1, a=40, b=40)
    cut = BoardFaceFeature(face=CutFace.FRONT, type=1, a=40, b=40, cut_depth_mm=201)
    with pytest.raises(ValueError, match="正面.*200 mm"):
        _project(cut)


def test_back_cut_relocates_anchor_to_remaining_installation_surface():
    cut = BoardFaceFeature(face=CutFace.FRONT, cut_start=CutStart.BACK, type=1, a=120, b=110, cut_depth_mm=55)
    project, _ = _project(cut, anchor_enabled=True, anchor_type="M型", anchor_position_mm="100")
    board = DrawingGenerator().build_module(project, project.modules[0]).board_view
    chain = [dim for dim in board.dimensions if dim.orientation == "horizontal"]
    assert any((100, 145) in (dim.start, dim.end) for dim in chain)
    through = cut.model_copy(update={"cut_depth_mm": None})
    project, _ = _project(through, anchor_enabled=True, anchor_type="M型", anchor_position_mm="100")
    with pytest.raises(ValueError, match="移除锚固件"):
        DrawingGenerator().build_module(project, project.modules[0])
