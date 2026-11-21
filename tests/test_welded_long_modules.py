from pathlib import Path

import ezdxf
import pytest
from openpyxl import load_workbook

from refracdraft.domain.models import BoardFaceFeature, BoardFaceProfile, CutStart, Project
from refracdraft.drawing.generator import DrawingGenerator
from refracdraft.drawing.layout import (
    _leader_text_bounds, detail_box, page_model_origins, place_cut_notes, view_bounds, view_placement,
)
from refracdraft.exporters.dxf import export_dxf
from refracdraft.exporters.project import export_standard_excel
from refracdraft.importers.excel import import_project_xlsx
from refracdraft.standard_sheet import DEFAULT_ROW, build_standard_row


def test_mixed_scale_frames_and_dimensions_keep_the_real_model_width(tmp_path: Path):
    modules = [
        build_standard_row({**DEFAULT_ROW, "module_id": name, "length_mm": length})[0]
        for name, length in (("A", "300"), ("K", "4700"), ("B", "300"))
    ]
    drawing = DrawingGenerator().generate(Project(modules=modules))
    assert [page.scale_denominator for page in drawing.pages] == [10, 20, 10]
    assert page_model_origins(drawing) == (0, -4400, -6900)
    board_view = drawing.pages[1].modules[0].drawing.board_view
    lower_dimension = next(dim for dim in board_view.dimensions if dim.label == "4700")
    assert lower_dimension.line_position < -100
    path = export_dxf(drawing, tmp_path / "mixed.dxf")
    dxf = ezdxf.readfile(path)
    long_dimensions = [
        entity for entity in dxf.modelspace().query("DIMENSION")
        if entity.dxf.dimstyle == "_20"
    ]
    assert long_dimensions
    assert sum(entity.get_measurement() == pytest.approx(4700) for entity in long_dimensions) == 2
    assert dxf.dimstyles.get("_20").dxf.dimtxt > 2 * dxf.dimstyles.get("_10").dxf.dimtxt


def test_exposure_and_blind_cut_round_trip_and_depth_controls_projection(tmp_path: Path):
    cut = BoardFaceFeature(type=1, a=120, b=65, cut_depth_mm=80, cut_start=CutStart.UPPER)
    profile = BoardFaceProfile(features=(cut,))
    values = {
        **DEFAULT_ROW, "anchor_enabled": True, "anchor_type": "焊接M型",
        "bolt_exposure_mm": "50",
    }
    module, board, anchor = build_standard_row(values, board_face_profile=profile)
    project = Project(modules=[module], boards=[board], anchors=[anchor])
    excel = tmp_path / "project.xlsx"
    export_standard_excel(project, excel)
    reloaded = import_project_xlsx(excel)
    assert reloaded.anchors[0].bolt_exposure_mm == 50
    assert reloaded.modules[0].board_face_outline == profile
    assert Project.model_validate_json(project.model_dump_json()).modules[0].board_face_outline == profile
    old_workbook = load_workbook(excel)
    old_workbook["异形参数"].delete_cols(10)
    old_workbook.save(excel)
    assert import_project_xlsx(excel).modules[0].board_face_outline.features[0].cut_start == CutStart.LOWER
    old_json = project.model_dump(mode="json")
    del old_json["modules"][0]["board_face_outline"]["features"][0]["cut_start"]
    assert Project.model_validate(old_json).modules[0].board_face_outline.features[0].cut_start == CutStart.LOWER

    for side, depth in ((CutStart.LOWER, 80), (CutStart.UPPER, 120)):
        cut_profile = BoardFaceProfile(features=(cut.model_copy(update={"cut_depth_mm": depth, "cut_start": side}),))
        body, board, _ = build_standard_row(DEFAULT_ROW, board_face_profile=cut_profile)
        drawn = DrawingGenerator().build_module(Project(modules=[body], boards=[board]), body)
        view = drawn.front_view
        projected = {line.points for line in view.internal_lines + view.hidden_lines}
        bottom, top = (0, depth) if side == CutStart.LOWER else (300 - depth, 300)
        assert ((120, bottom), (120, top)) in projected
        stop = top if side == CutStart.LOWER else bottom
        assert ((0, stop), (120, stop)) in projected
        assert ((120, 0), (120, 300)) not in projected
        board_view = drawn.board_view
        assert (0, 0) in board_view.outline.points
        walls = board_view.internal_lines if side == CutStart.UPPER else board_view.hidden_lines
        assert ((0, 65), (120, 65)) in [wall.points for wall in walls]
        note, = board_view.leaders
        assert note.machining and note.text == f"{side.value}切缺口"
        arranged, = place_cut_notes(board_view, 10, body.module_id).leaders
        left, low, right, high = _leader_text_bounds(arranged, 10)
        if 0 < high and low < body.board_face_height_mm / 10:
            assert not left < 0 < right
            assert not left < body.board_face_width_mm / 10 < right
        assert not any("剪切深度" in detail or "切缺口" in detail for detail in drawn.details)
        depth_dim, = (dim for dim in view.dimensions if dim.label == str(depth))
        assert (depth_dim.start[1], depth_dim.end[1]) == (bottom, top)

    invalid = BoardFaceProfile(features=(cut.model_copy(update={"cut_depth_mm": 301}),))
    with pytest.raises(ValueError, match="剪切深度"):
        build_standard_row(DEFAULT_ROW, board_face_profile=invalid)


def test_welded_diamond_depth_and_remark_are_independent_of_anchor_length(tmp_path: Path):
    from dataclasses import replace
    from refracdraft.reference.library import ReferenceLibrary

    values = {
        **DEFAULT_ROW,
        "length_mm": "4700",
        "thickness_mm": "600",
        "anchor_enabled": True,
        "anchor_type": "焊接菱形",
        "anchor_length_mm": "245",
        "bolt_exposure_mm": "190",
        "embedment_depth_mm": "140",
        "anchor_count": "16",
        "anchor_position_mm": "250",
        "anchor_spacing_mm": "280",
        "source_note": "自动",
    }
    module, board, anchor = build_standard_row(values)
    assert (anchor.length_mm, anchor.bolt_length_mm) == (245, 330)
    assert module.source_note == "螺栓长度330mm，外露190mm"
    generator = DrawingGenerator(ReferenceLibrary("references/示例.dxf"))
    project = Project(modules=[module], boards=[board], anchors=[anchor], standard_link_version=2)
    drawing = generator.generate(project)
    page, = drawing.pages
    data = page.modules[0].drawing
    view = data.board_view
    assert page.scale_denominator == 20
    leader, = view.leaders
    assert "外露190" in leader.text
    shoe_count = len(generator.reference_library.welded_diamond_shoe.polylines)
    assert max(line.bounds[3] for line in view.anchor_symbols[:shoe_count]) == pytest.approx(460)
    assert min(line.bounds[1] for line in view.anchor_symbols[:shoe_count]) < 460
    assert any(line.points == ((250, 460), (250, 790)) for line in view.anchor_symbols)
    assert max(line.bounds[3] for line in view.anchor_symbols) == 790
    assert "4、锚固件长度：245mm" in data.details
    assert data.details[-1] == "8、螺栓长度330mm，外露190mm"
    denominator = page.scale_denominator
    _, _, _, top = view_bounds(replace(view, leaders=()), denominator)
    assert len(leader.vertices_mm) == 2
    dx, dy = leader.offset_mm
    assert all(x * dy == pytest.approx(y * dx) for path in leader.paths_mm for x, y in path)
    assert leader.tip[1] / denominator + leader.offset_mm[1] > top
    assert {"140", "190", "330"} <= {dim.label for dim in view.dimensions if dim.orientation == "vertical"}

    edited = anchor.model_copy(update={"length_mm": None})
    new_project = project.model_copy(update={"anchors": [edited]})
    assert edited.bolt_length_mm == 330
    assert generator.build_module(new_project, module).board_view.anchor_symbols == view.anchor_symbols
    manual_module = module.model_copy(update={"source_note": "客户自备"})
    assert generator.build_module(project, manual_module).details[-1] == (
        "8、螺栓长度330mm，外露190mm，客户自备"
    )

    excel = tmp_path / "welded.xlsx"
    export_standard_excel(project, excel)
    recovered = import_project_xlsx(excel).anchors[0]
    assert (recovered.length_mm, recovered.embedment_depth_mm, recovered.bolt_length_mm) == (245, 140, 330)
    modelspace = ezdxf.readfile(export_dxf(drawing, tmp_path / "welded.dxf")).modelspace()
    leaders = modelspace.query("LEADER")
    assert leaders and all(len(leader.vertices) == 2 for leader in leaders)
    for value in (190, 140, 330):
        assert any(dim.dxf.text == str(value) and dim.get_measurement() == pytest.approx(value)
                   for dim in modelspace.query("DIMENSION"))

    for kind, depth in (("焊接M型", 0), ("焊接菱形", 50)):
        taper, plate, hardware = build_standard_row({
            **DEFAULT_ROW, "length_mm": "600", "thickness_mm": "300",
            "taper_enabled": True, "taper_type": "侧敲", "big_head_mm": "300", "small_head_mm": "220",
            "anchor_enabled": True, "anchor_length_mm": "220", "anchor_type": kind,
            "bolt_exposure_mm": "50", "embedment_depth_mm": "50",
        })
        taper_project = Project(modules=[taper], boards=[plate], anchors=[hardware])
        placed, = generator.generate(taper_project).pages[0].modules
        module_drawing = placed.drawing
        side = module_drawing.side_view
        *body, shaft, axis = side.anchor_symbols
        assert body and min(line.bounds[0] for line in body) == pytest.approx(depth)
        assert max(line.bounds[3] for line in body) - min(line.bounds[1] for line in body) == pytest.approx(220)
        assert shaft.bounds[0] == -50 and shaft.bounds[2] == depth
        assert axis.points == ((-50, 150), (depth, 150))
        placement = view_placement(module_drawing)
        detail_left, _ = detail_box(placed)
        assert placement.detail_on_side
        assert detail_left > placed.content_x_mm + view_bounds(module_drawing.board_view)[2]
        assert detail_left < placed.content_x_mm + placement.side_x + view_bounds(side)[2]

    step = BoardFaceProfile(features=(BoardFaceFeature(type=1, a=120, b=65, rotation_deg=180),))
    for kind, expected_contact in (("M型", 235), ("菱形", 185), ("焊接M型", 285), ("焊接菱形", 285)):
        body, plate, hardware = build_standard_row({
            **DEFAULT_ROW, "length_mm": "300", "thickness_mm": "300",
            "anchor_enabled": True, "anchor_type": kind, "anchor_position_mm": "180",
            "bolt_exposure_mm": "50", "embedment_depth_mm": "50",
        }, board_face_profile=step)
        stepped = generator.build_module(Project(modules=[body], boards=[plate], anchors=[hardware]), body)
        assert max(line.bounds[3] for line in stepped.board_view.anchor_symbols) == pytest.approx(expected_contact)
        if "焊接" in kind:
            assert stepped.board_view.leaders[0].tip == (180, 285)
        if kind == "菱形":
            assert any(dim.start == (180, 235) and dim.end == (180, 185) and dim.label == "50"
                       for dim in stepped.board_view.dimensions)

    legacy = anchor.model_copy(update={"embedment_depth_mm": None})
    incomplete = project.model_copy(update={"anchors": [legacy]})
    with pytest.raises(ValueError, match="填写焊接菱形的嵌入深度"):
        generator.generate(incomplete)
