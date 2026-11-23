from math import dist
from pathlib import Path

import ezdxf
import pytest

from refracdraft.domain.models import BoardFaceFeature, BoardFaceProfile, CutFace, CutStart, Project
from refracdraft.drawing.generator import DrawingGenerator
from refracdraft.drawing.layout import DETAIL_VIEW_CLEARANCE_MM, view_bounds, view_placement
from refracdraft.drawing.model import INSERT_ANCHOR_ACI, LAYER_MARK_ACI, LEADER_ACI
from refracdraft.drawing.multiface import machined_module, project_module
from refracdraft.exporters.dxf import export_dxf
from refracdraft.exporters.project import export_standard_excel
from refracdraft.importers.excel import import_project_xlsx
from refracdraft.reference.library import ReferenceLibrary
from refracdraft.standard_sheet import DEFAULT_ROW, build_standard_row


@pytest.fixture(scope="module")
def reference_library():
    return ReferenceLibrary(Path(__file__).resolve().parents[1] / "references" / "示例.dxf")


def _project(*cuts, **settings):
    profile = BoardFaceProfile(features=cuts) if cuts else None
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


def test_no_anchor_layer_marks_survive_multiface_cuts_and_stop_at_the_chamfer(tmp_path, reference_library):
    generator = DrawingGenerator(reference_library)
    side = BoardFaceFeature(face=CutFace.SIDE, type=1, a=92, b=60, mirror_x=True)
    board = BoardFaceFeature(type=1, a=120, b=46)
    front = BoardFaceFeature(face=CutFace.FRONT, type=3, a=75, b=75)
    sizes = {"thickness_mm": "230", "expansion_length_mm": "300"}
    project, _ = _project(front, side, board, **sizes)
    drawing = generator.generate(project)
    module = drawing.pages[0].modules[0].drawing
    original = reference_library.stacked_front_lines(300, 300)
    assert len(module.front_view.layer_marks) == len(original) == 4
    assert module.front_view.layer_marks == original
    assert len(module.side_view.layer_marks) == 4
    assert any(line.points[0][0] == line.points[-1][0] for line in module.front_view.internal_lines)

    path = export_dxf(drawing, tmp_path / "layer-marks.dxf")
    doc = ezdxf.readfile(path)
    assert doc.layers.get("LAYER_MARKS").color == LAYER_MARK_ACI
    assert doc.layers.get("OUTLINE").color == 7
    marks = [entity for entity in doc.modelspace().query("LWPOLYLINE") if entity.dxf.layer == "LAYER_MARKS"]
    assert len(marks) == 8

    chamfer = front.model_copy(update={"a": 100, "b": 200, "mirror_x": True})
    clipped, _ = _project(chamfer, side, board, **sizes)
    view = generator.build_module(clipped, clipped.modules[0]).front_view
    assert len(view.layer_marks) == 4
    for mark, source in zip(view.layer_marks, original):
        x, y = max(mark.points)
        assert x == pytest.approx(min(max(source.points)[0], 300 - (y - 100) / 2))
    assert view.layer_marks != original


def test_layer_marks_follow_the_taper_and_keep_their_dxf_lengths(reference_library):
    generator = DrawingGenerator(reference_library)
    lengths = [dist(*mark.points) for mark in reference_library.stacked_front_lines(300, 300)]
    for width in (160, 300, 900):
        for taper in ("正敲", "侧敲"):
            project, _ = _project(length_mm=str(width), thickness_mm=str(width), taper_enabled=True,
                                  taper_type=taper, big_head_mm="300", small_head_mm="220")
            drawing = generator.build_module(project, project.modules[0])
            view = drawing.front_view if taper == "正敲" else drawing.side_view
            assert len(view.layer_marks) == 4
            assert [dist(*mark.points) for mark in view.layer_marks] == pytest.approx(lengths)
            for mark in view.layer_marks:
                (a, b), (c, d) = sorted(mark.points)
                assert d < b
                assert -40 / width < (d - b) / (c - a) < 0


def test_multiface_preserves_the_board_view_and_can_add_both_plate_details(tmp_path):
    front = BoardFaceFeature(face=CutFace.FRONT, type=3, a=75, b=75)
    side = BoardFaceFeature(face=CutFace.SIDE, type=1, a=92, b=60, mirror_x=True)
    board = BoardFaceFeature(type=1, a=120, b=46)
    sizes = {"thickness_mm": "230", "expansion_length_mm": "300"}
    baseline, _ = _project(front, side, board, **sizes)
    project, _ = _project(front, side, board, show_upper_board=True, show_lower_board=True, **sizes)
    generator = DrawingGenerator()
    original = generator.generate(baseline).pages[0].modules[0].drawing
    assert original.board_details == ()
    document = generator.generate(project)
    placed = document.pages[0].modules[0]
    upper = placed.drawing.upper_board_view
    lower = placed.drawing.lower_board_view
    assert placed.drawing.board_view == original.board_view
    assert (lower.note, upper.note) == ("下夹板", "上夹板")
    assert lower.outline.bounds == (0, 92, 300, 230)
    assert upper.outline.bounds == (75, 0, 300, 230)
    assert (120, 46) in upper.outline.points
    assert {dim.label for dim in lower.dimensions} == {"300", "138"}
    assert {"225", "230", "45", "46"} <= {dim.label for dim in upper.dimensions}
    placement = view_placement(placed.drawing)
    assert not placement.detail_on_side
    for view, (_, y) in zip(placed.drawing.board_details, placement.board_detail_origins, strict=True):
        assert placement.detail_y + DETAIL_VIEW_CLEARANCE_MM <= placement.board_y + y + view_bounds(view)[1] + 1e-6
    model = ezdxf.readfile(export_dxf(document, tmp_path / "plates.dxf")).modelspace()
    assert {"下夹板", "上夹板"} <= {item.dxf.text for item in model.query("TEXT")}


@pytest.mark.parametrize("upper", [True, False])
def test_board_blind_cut_only_changes_the_selected_plate(upper):
    cut = BoardFaceFeature(type=1, a=50, b=40, cut_depth_mm=60,
                           cut_start=CutStart.UPPER if upper else CutStart.LOWER)
    project, _ = _project(cut, show_upper_board=True, show_lower_board=True)
    drawing = DrawingGenerator().build_module(project, project.modules[0])
    machined = drawing.upper_board_view if upper else drawing.lower_board_view
    opposite = drawing.lower_board_view if upper else drawing.upper_board_view
    assert (50, 40) in machined.outline.points
    assert (0, 0) not in machined.outline.points
    assert (0, 0) in opposite.outline.points
    assert [note.text for note in drawing.board_view.leaders] == [f"{cut.cut_start.value}切缺口"]
    assert not machined.leaders and not opposite.leaders


@pytest.mark.parametrize(("upper", "lower"), [(False, False), (True, False), (False, True), (True, True)])
def test_board_checkboxes_round_trip_and_draw_only_selected_details(tmp_path, upper, lower):
    cut = BoardFaceFeature(type=1, a=50, b=40)
    project, _ = _project(cut)
    generator = DrawingGenerator()
    assert generator.build_module(project, project.modules[0]).upper_board_view is None
    forced, _ = _project(cut, show_upper_board=upper, show_lower_board=lower)
    path = tmp_path / "checkbox.xlsx"
    export_standard_excel(forced, path)
    workbook_project = import_project_xlsx(path)
    assert (workbook_project.boards[0].show_upper_board, workbook_project.boards[0].show_lower_board) == (upper, lower)
    restored = Project.model_validate_json(workbook_project.model_dump_json())
    assert (restored.boards[0].show_upper_board, restored.boards[0].show_lower_board) == (upper, lower)
    drawing = generator.build_module(restored, restored.modules[0])
    assert (drawing.upper_board_view is not None, drawing.lower_board_view is not None) == (upper, lower)
    assert all(view.outline == drawing.board_view.outline for view in drawing.board_details)
    absent, _ = _project(cut, board_exists=False, show_upper_board=upper, show_lower_board=lower)
    drawing = generator.build_module(absent, absent.modules[0])
    assert not drawing.board_details
    assert drawing.board_view.note == "无夹板"


def test_zero_leg_slanted_step_and_front_chamfer_keep_stock_and_plate_datums_distinct(tmp_path):
    chamfer = BoardFaceFeature(face=CutFace.FRONT, type=3, a=150, b=150, rotation_deg=180)
    slanted = BoardFaceFeature(type=4, a=0, b=400, c=120, cut_depth_mm=200)
    project, profile = _project(chamfer, slanted, length_mm="600", thickness_mm="230",
                                expansion_length_mm="300", show_upper_board=True, show_lower_board=True)
    assert machined_module(project.modules[0], profile).volume() == pytest.approx(29050000)
    document = DrawingGenerator().generate(project)
    drawing = document.pages[0].modules[0].drawing
    assert drawing.board_view.outline.bounds == (0, 0, 600, 230)
    assert {"400", "120"} <= {dim.label for dim in drawing.board_view.dimensions}
    assert drawing.upper_board_view.outline.bounds == (0, 0, 600, 230)
    lower = drawing.lower_board_view
    assert set(lower.outline.points) == {(0, 0), (200, 110), (450, 110), (450, 230), (0, 230)}
    length, = (dim for dim in lower.dimensions if dim.label == "450" and dim.orientation == "horizontal")
    assert (length.start, length.end) == ((0, 0), (450, 110))
    assert all(dim.label != "0" for view in drawing.board_details for dim in view.dimensions)
    model = ezdxf.readfile(export_dxf(document, tmp_path / "chamfer-step.dxf")).modelspace()
    assert {leader.dxf.layer for leader in model.query("LEADER")} == {"LEADERS"}
    assert model.doc.layers.get("LEADERS").color == LEADER_ACI


@pytest.mark.parametrize("anchor_type", ["快插", "旁插"])
def test_insert_anchor_symbols_share_the_distinct_color_across_views(anchor_type, reference_library, tmp_path):
    project, _ = _project(taper_enabled=True, taper_type="侧敲", big_head_mm="300", small_head_mm="220",
                          anchor_enabled=True, anchor_type=anchor_type)
    document = DrawingGenerator(reference_library).generate(project)
    drawing = document.pages[0].modules[0].drawing
    for view in (drawing.front_view, drawing.side_view, drawing.board_view):
        assert len(view.anchor_symbols) == len(view.anchor_symbol_colors) > 0
        assert set(view.anchor_symbol_colors) == {INSERT_ANCHOR_ACI}
        assert not view.layer_marks
    model = ezdxf.readfile(export_dxf(document, tmp_path / "insert.dxf")).modelspace()
    assert {item.dxf.color for item in model.query('LWPOLYLINE[layer=="ANCHORS"]')} == {INSERT_ANCHOR_ACI}


def test_side_taper_pair_uses_available_space_below_views():
    rows = [build_standard_row({
        **DEFAULT_ROW, "module_id": f"M{i + 5}", "length_mm": str(length), "thickness_mm": "230",
        "taper_enabled": True, "taper_type": "侧敲", "big_head_mm": "300", "small_head_mm": str(small),
        "anchor_enabled": True, "anchor_type": "菱形", "anchor_count": str(i + 2), "anchor_spacing_mm": "300",
    }) for i, (length, small) in enumerate(((600, 230), (900, 250)))]
    modules, boards, anchors = map(list, zip(*rows))
    document = DrawingGenerator().generate(Project(modules=modules, boards=boards, anchors=anchors))
    page, = document.pages
    assert len(page.modules) == 2
    for placed in page.modules:
        placement = view_placement(placed.drawing)
        assert placed.drawing.side_view is not None
        assert not placement.detail_on_side
        assert placement.detail_y + DETAIL_VIEW_CLEARANCE_MM <= (
            placement.board_y + view_bounds(placed.drawing.board_view)[1]
        ) + 1e-6
