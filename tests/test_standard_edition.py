from pathlib import Path

import pytest
import ezdxf
import pymupdf
from openpyxl import Workbook, load_workbook

from refracdraft.drawing.generator import DrawingGenerator, _anchor_positions, _balanced_page_groups, _details
from refracdraft.drawing.layout import (
    DETAIL_LINE_SPACING,
    DETAIL_TEXT_SIZE_MM,
    DIMENSION_TEXT_SIZE_MM,
    PANEL_INNER_MARGIN_MM,
    detail_box,
    details_width,
)
from refracdraft.domain.models import (
    AnchorParameters,
    AnchorType,
    BoardFaceProfile,
    BoardParameters,
    GeometryType,
    LayoutMode,
    ModuleParameters,
    Project,
    StructureType,
)
from refracdraft.importers.excel import _normalize_row, import_project_xlsx
from refracdraft.reference.library import ReferenceLibrary
from refracdraft.exporters.dxf import export_dxf
from refracdraft.exporters.pdf import PDF_FONT_CANDIDATES, _find_pdf_font, _render_page, _single_page_dxf
from refracdraft.release import latest_portable_release
from refracdraft.standard_sheet import COLUMN_SPECS, DEFAULT_ROW, build_standard_row
from refracdraft.standard import (
    StandardAnchorValues,
    StandardModuleValues,
    build_standard_anchor,
    build_standard_board,
    build_standard_module,
    ensure_standard_project,
    standard_anchor_values,
    standard_module_values,
)


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


def test_standard_board_face_profile_round_trips_and_uses_table_bounds():
    profile = BoardFaceProfile.model_validate({
        "features": [{"type": 1, "a": 62, "b": 24, "rotation_deg": 90, "mirror_x": True}],
    })
    values = dict(DEFAULT_ROW, length_mm="345", thickness_mm="210", anchor_enabled=False)
    part, board, anchor = build_standard_row(values, board_face_profile=profile)
    project = Project(modules=[part], boards=[board], anchors=[anchor])
    restored = Project.model_validate_json(project.model_dump_json())
    ensure_standard_project(restored)
    part = restored.modules[0]
    assert part.board_face_outline == profile
    assert (part.board_face_width_mm, part.board_face_height_mm) == (345, 210)
    assert build_standard_module(part, standard_module_values(part, board)).board_face_outline == profile
    drawing = DrawingGenerator().build_module(restored, part)
    x, y = zip(*drawing.board_view.outline.points)
    assert (max(x) - min(x), max(y) - min(y)) == (345, 210)
    with pytest.raises(ValueError, match=r"M1.*类型 1"):
        build_standard_row(dict(values, thickness_mm="60"), board_face_profile=profile)


def test_welded_diamond_type_survives_unified_input_normalization():
    assert _normalize_row({"anchor_type": "焊接菱形"}, "anchors")["anchor_type"] == "焊接菱形"


def test_standard_normal_row_maps_length_expansion_and_thickness():
    values = StandardModuleValues("N1", 400, 260, 180, board_exists=True)
    built = build_standard_module(None, values)

    assert built.geometry_type == GeometryType.NORMAL
    assert built.front_width_mm == 400
    assert built.front_height_mm == 260
    assert built.expansion_length_mm == 260
    assert built.board_face_width_mm == 400
    assert built.board_face_height_mm == 180
    assert built.front_left_height_mm is None
    assert built.front_right_height_mm is None


@pytest.mark.parametrize(
    ("taper_type", "expected_side"),
    [
        (GeometryType.FRONT_TAPER, None),
        (GeometryType.SIDE_TAPER, 230),
    ],
)
def test_standard_taper_rows_map_big_small_and_type(taper_type, expected_side):
    values = StandardModuleValues(
        "T1", 300, 280, 230, True, big_head_mm=289, small_head_mm=220, taper_type=taper_type
    )
    built = build_standard_module(None, values)

    assert built.geometry_type == taper_type
    assert built.expansion_length_mm == 289
    assert built.board_face_width_mm == 300
    assert built.board_face_height_mm == 230
    assert built.side_length_mm == expected_side
    if taper_type == GeometryType.FRONT_TAPER:
        assert built.front_left_height_mm == 289
        assert built.front_right_height_mm == 220
    else:
        assert built.side_left_height_mm == 289
        assert built.side_right_height_mm == 220


def test_standard_taper_rejects_inverted_heads():
    values = StandardModuleValues(
        "T2", 300, 300, 230, True, big_head_mm=200, small_head_mm=220
    )
    with pytest.raises(ValueError, match="大头必须大于小头"):
        build_standard_module(None, values)


def test_standard_anchor_uses_fixed_spacing_and_only_diamond_keeps_depth():
    diamond = build_standard_anchor(
        None,
        "D1",
        500,
        StandardAnchorValues(True, 80, 150, 3, AnchorType.DIAMOND, 60),
    )
    assert diamond.layout_mode == LayoutMode.FIXED_SPACING
    assert diamond.edge_offset_mm == 80
    assert diamond.spacing_mm == 150
    assert diamond.count == 3
    assert diamond.embedment_depth_mm == 60
    assert diamond.length_mm == 230
    assert diamond.diameter_mm is None

    m_shape = build_standard_anchor(
        diamond,
        "D1",
        500,
        StandardAnchorValues(True, 80, 150, 3, AnchorType.M_SHAPE, 60),
    )
    assert m_shape.embedment_depth_mm is None
    assert m_shape.diameter_mm == 8


def test_standard_anchor_rejects_position_beyond_length():
    with pytest.raises(ValueError, match="超出模块长度"):
        build_standard_anchor(
            None,
            "A1",
            300,
            StandardAnchorValues(True, 250, 100, 2, AnchorType.M_SHAPE),
        )


def test_standard_values_read_back_from_models():
    module_model = build_standard_module(
        None,
        StandardModuleValues(
            "B2", 300, 300, 230, True, 289, 220, GeometryType.FRONT_TAPER
        ),
    )
    board_model = build_standard_board(None, "B2", True)
    anchor_model = build_standard_anchor(
        None,
        "B2",
        300,
        StandardAnchorValues(True, 150, 200, 1, AnchorType.DIAMOND, 50),
    )

    module_values = standard_module_values(module_model, board_model)
    anchor_values = standard_anchor_values(anchor_model)
    assert module_values.length_mm == 300
    assert module_values.expansion_length_mm == 289
    assert module_values.thickness_mm == 230
    assert module_values.big_head_mm == 289
    assert module_values.small_head_mm == 220
    assert anchor_values.position_mm == 150
    assert anchor_values.count == 1
    assert anchor_values.embedment_depth_mm == 50
    assert anchor_values.length_mm == 230


def test_standard_excel_aliases_accept_dynamic_block_terms():
    normalized = _normalize_row(
        {
            "编号": "X1",
            "长度": 300,
            "膨胀长度": 260,
            "厚度": 180,
            "大头": 280,
            "小头": 210,
        },
        "modules",
    )
    assert normalized["expansion_length_mm"] == 260
    assert normalized["front_left_height_mm"] == 280
    assert normalized["front_right_height_mm"] == 210
    anchor = _normalize_row(
        {"锚固件位置": 80, "嵌入深度": 55, "间距": 200, "数量": 2, "类型": "菱形"},
        "anchors",
    )
    assert anchor["edge_offset_mm"] == 80
    assert anchor["embedment_depth_mm"] == 55
    assert anchor["spacing_mm"] == 200
    assert anchor["anchor_type"] == "菱形"


def test_standard_excel_generic_heads_move_to_side_for_side_taper():
    normalized = _normalize_row(
        {"编号": "S1", "几何类型": "正敲", "大头": 300, "小头": 200},
        "modules",
    )
    assert normalized["side_left_height_mm"] == 300
    assert normalized["side_right_height_mm"] == 200
    assert "front_left_height_mm" not in normalized
    assert "front_right_height_mm" not in normalized


@pytest.mark.parametrize(("label", "expected_type", "has_side_view"), [
    ("正敲", GeometryType.SIDE_TAPER, True),
    ("侧敲", GeometryType.FRONT_TAPER, False),
])
def test_standard_taper_labels_generate_the_correct_views(label, expected_type, has_side_view):
    module, board, anchor = build_standard_row({
        **DEFAULT_ROW, "taper_enabled": True, "taper_type": label,
    })
    assert module.geometry_type == expected_type
    project = Project(modules=[module], boards=[board], anchors=[anchor])
    view = DrawingGenerator().generate(project).pages[0].modules[0].drawing
    assert (view.side_view is not None) == has_side_view
    legacy = module.model_dump(mode="json")
    legacy["geometry_type"] = "侧敲" if label == "正敲" else "正敲"
    assert ModuleParameters.model_validate(legacy).geometry_type == expected_type


@pytest.mark.parametrize(
    ("anchor_type", "expected_y"),
    [
        (AnchorType.M_SHAPE, 230 - 35.4391501542),
        (AnchorType.DIAMOND, 180.0),
    ],
)
def test_board_face_anchor_uses_source_top_offset(anchor_type, expected_y):
    anchor = AnchorParameters(
        module_id="A1",
        exists=True,
        anchor_type=anchor_type,
        count=1,
        layout_mode=LayoutMode.FIXED_SPACING,
        edge_offset_mm=150,
        spacing_mm=300,
    )
    positions = _anchor_positions(anchor, 300, 230, board_face=True)
    assert positions[0][0] == 150.0
    assert positions[0][1] == pytest.approx(expected_y)


def test_standard_details_include_new_manufacturing_fields():
    module = build_standard_module(
        None,
        StandardModuleValues(
            "A1", 300, 300, 330, True, 300, 200, GeometryType.SIDE_TAPER,
            material="1350板材", production_quantity=84, board_material="12厘夹板",
            density_kg_m3=220, source_note="现场复核",
        ),
    )
    board = build_standard_board(None, "A1", True, "12厘夹板")
    anchor = build_standard_anchor(
        None,
        "A1",
        300,
        StandardAnchorValues(
            True, 150, 300, 1, AnchorType.M_SHAPE,
            material="304", thread_spec="M8", pin_diameter_mm=8, hose_spec="25胶管",
        ),
    )
    text = "\n".join(_details(module, board, anchor))
    assert "2、材质：1350" in text
    assert "1350材质" not in text
    assert "3、锚固件：304M型M8φ8" in text
    assert "插针" not in text
    assert "数量：84 Pcs" in text
    assert "容重：220 kg/m³" in text
    assert "7、25胶管，12厘夹板" in text
    assert "8、现场复核" in text


def test_side_insert_adds_machining_note_without_replacing_existing_note():
    module = build_standard_module(None, StandardModuleValues("M1", 300, 300, 230))
    module = module.model_copy(update={"source_note": "现场复核"})
    board = build_standard_board(None, "M1", True)
    anchor = build_standard_anchor(
        None, "M1", 300, StandardAnchorValues(enabled=True, anchor_type=AnchorType.SIDE_INSERT),
    )
    assert _details(module, board, anchor)[-1] == "8、现场复核；木板开口60*110 插针隔1层毯子插"


def test_custom_type_labels_survive_project_json_and_appear_in_details():
    module = build_standard_module(
        None,
        StandardModuleValues(
            "M1", 300, 300, 230, structure_type=StructureType.CUSTOM,
            custom_structure_label="定制折叠",
        ),
    )
    board = build_standard_board(None, "M1", True)
    anchor = build_standard_anchor(
        None,
        "M1",
        300,
        StandardAnchorValues(
            enabled=True, anchor_type=AnchorType.CUSTOM, custom_type_label="定制型",
        ),
    )
    project = Project(modules=[module], boards=[board], anchors=[anchor])
    restored = Project.model_validate_json(project.model_dump_json())
    module, board, anchor = restored.modules[0], restored.boards[0], restored.anchors[0]
    assert standard_module_values(module, board).custom_structure_label == "定制折叠"
    assert standard_anchor_values(anchor).custom_type_label == "定制型"
    details = "\n".join(_details(module, board, anchor))
    assert "定制折叠M1" in details
    assert "3、锚固件：310定制型M10φ8" in details


def test_standard_anchor_length_round_trip_and_validation():
    anchor = build_standard_anchor(
        None,
        "L1",
        300,
        StandardAnchorValues(True, 150, 300, 1, AnchorType.M_SHAPE, length_mm=275),
    )
    assert anchor.length_mm == 275
    assert standard_anchor_values(anchor).length_mm == 275

    with pytest.raises(ValueError, match="锚固件长度"):
        build_standard_anchor(
            None,
            "L2",
            300,
            StandardAnchorValues(True, 150, 300, 1, AnchorType.M_SHAPE, length_mm=0),
        )


def test_no_anchor_views_include_expansion_face_marks():
    module = build_standard_module(
        None,
        StandardModuleValues("A2", 300, 300, 330, True, 300, 220, GeometryType.SIDE_TAPER),
    )
    board = build_standard_board(None, "A2", True)
    anchor = build_standard_anchor(None, "A2", 300, StandardAnchorValues(False))
    project = Project(modules=[module], boards=[board], anchors=[anchor])
    document = DrawingGenerator(ReferenceLibrary("references/示例.dxf")).generate(project)
    drawing = document.pages[0].modules[0].drawing
    assert len(drawing.front_view.internal_lines) == 6
    assert len(drawing.side_view.internal_lines) == 4


def test_diamond_side_anchor_uses_expansion_face_profile():
    module = build_standard_module(
        None,
        StandardModuleValues("A1", 300, 300, 330, True, 300, 200, GeometryType.SIDE_TAPER),
    )
    board = build_standard_board(None, "A1", True)
    anchor = build_standard_anchor(
        None,
        "A1",
        300,
        StandardAnchorValues(True, 150, 300, 1, AnchorType.DIAMOND, 50),
    )
    project = Project(modules=[module], boards=[board], anchors=[anchor])
    document = DrawingGenerator(ReferenceLibrary("references/示例.dxf")).generate(project)
    side_view = document.pages[0].modules[0].drawing.side_view
    assert side_view is not None
    symbol_points = [point for line in side_view.anchor_symbols for point in line.points]
    symbol_min_x = min(point[0] for point in symbol_points)
    symbol_min_y = min(point[1] for point in symbol_points)
    symbol_max_y = max(point[1] for point in symbol_points)
    assert symbol_min_x == pytest.approx(50.0)
    assert symbol_max_y - symbol_min_y == pytest.approx(220.0)
    assert side_view.anchor_points == ()
    assert set(side_view.anchor_symbol_colors) == {7}
    assert "CONTINUOUS" in side_view.anchor_symbol_linetypes
    assert "CENTER2" in side_view.anchor_symbol_linetypes


def test_side_taper_front_has_small_head_contour_lines():
    module = build_standard_module(
        None,
        StandardModuleValues("A1", 300, 300, 330, True, 300, 200, GeometryType.SIDE_TAPER),
    )
    board = build_standard_board(None, "A1", True)
    anchor = build_standard_anchor(
        None,
        "A1",
        300,
        StandardAnchorValues(True, 150, 300, 1, AnchorType.DIAMOND, 50),
    )
    project = Project(modules=[module], boards=[board], anchors=[anchor])
    document = DrawingGenerator(ReferenceLibrary("references/示例.dxf")).generate(project)
    lines = document.pages[0].modules[0].drawing.front_view.internal_lines
    assert len(lines) == 2
    ys = sorted({point[1] for line in lines for point in line.points})
    assert ys == pytest.approx([50.0, 250.0])
    assert {point[0] for line in lines for point in line.points} == {0.0, 300.0}


def test_m_shape_side_anchor_uses_expansion_face_profile():
    module = build_standard_module(
        None,
        StandardModuleValues("M2", 300, 300, 230, True, 289, 220, GeometryType.SIDE_TAPER),
    )
    board = build_standard_board(None, "M2", True)
    anchor = build_standard_anchor(
        None,
        "M2",
        300,
        StandardAnchorValues(True, 150, 300, 1, AnchorType.M_SHAPE),
    )
    project = Project(modules=[module], boards=[board], anchors=[anchor])
    library = ReferenceLibrary("references/示例.dxf")
    document = DrawingGenerator(library).generate(project)
    side_view = document.pages[0].modules[0].drawing.side_view
    assert side_view is not None
    symbol_points = [point for line in side_view.anchor_symbols for point in line.points]
    symbol_min_x = min(point[0] for point in symbol_points)
    symbol_max_x = max(point[0] for point in symbol_points)
    assert symbol_min_x == pytest.approx(0.0)
    assert symbol_max_x - symbol_min_x == pytest.approx(138.4935864220024)
    assert side_view.anchor_points == ()
    assert set(side_view.anchor_symbol_colors) == {5}
    assert "CENTER2" in side_view.anchor_symbol_linetypes

    source = library.symbol_from_block("*U324")
    expected = tuple(line.transformed(sx=-1.0) for line in source.polylines)
    actual = library.side_anchor_symbol("M型").polylines
    assert len(actual) == len(expected)
    for actual_line, expected_line in zip(actual, expected):
        actual_coords = tuple(value for point in actual_line.points for value in point)
        expected_coords = tuple(value for point in expected_line.points for value in point)
        assert actual_coords == pytest.approx(expected_coords)


def test_standard_anchor_positions_are_dimensioned_on_board_face():
    module = build_standard_module(None, StandardModuleValues("D2", 500, 300, 230))
    board = build_standard_board(None, "D2", True)
    anchor = build_standard_anchor(
        None,
        "D2",
        500,
        StandardAnchorValues(True, 80, 150, 3, AnchorType.DIAMOND, 50),
    )
    project = Project(modules=[module], boards=[board], anchors=[anchor])
    document = DrawingGenerator(ReferenceLibrary("references/示例.dxf")).generate(project)
    labels = [dimension.label for dimension in document.pages[0].modules[0].drawing.board_view.dimensions]
    assert "80" in labels
    assert "150" in labels
    assert "120" in labels
    depth_dimensions = [dimension for dimension in document.pages[0].modules[0].drawing.board_view.dimensions
                        if dimension.label == "50"]
    assert depth_dimensions
    depth_dimension = depth_dimensions[0]
    assert depth_dimension.start == (80, 230)
    assert depth_dimension.end == (80, 180)
    symbol_points = [
        point
        for line in document.pages[0].modules[0].drawing.board_view.anchor_symbols
        for point in line.points
    ]
    symbol_y = [point[1] for point in symbol_points]
    assert max(symbol_y) == pytest.approx(180.0)


@pytest.mark.parametrize("depth", [50.0, 60.0])
def test_diamond_anchor_geometry_follows_real_embedment_depth(depth):
    module = build_standard_module(None, StandardModuleValues("D3", 500, 300, 230))
    board = build_standard_board(None, "D3", True)
    anchor = build_standard_anchor(
        None,
        "D3",
        500,
        StandardAnchorValues(True, 80, 150, 3, AnchorType.DIAMOND, depth),
    )
    project = Project(modules=[module], boards=[board], anchors=[anchor])
    drawing = DrawingGenerator(ReferenceLibrary("references/示例.dxf")).generate(project).pages[0].modules[0].drawing
    points = [point for line in drawing.board_view.anchor_symbols for point in line.points]
    ys = [point[1] for point in points]
    assert max(ys) == pytest.approx(230.0 - depth)
    depth_dimensions = [dim for dim in drawing.board_view.dimensions if dim.label == f"{depth:g}"]
    assert depth_dimensions[0].end[1] == pytest.approx(230.0 - depth)


def test_separator_lines_use_150_model_unit_top_and_title_block_insets(tmp_path):
    modules = [
        build_standard_module(None, StandardModuleValues(f"S{i}", 450, 300, 230))
        for i in range(1, 3)
    ]
    boards = [build_standard_board(None, item.module_id, True) for item in modules]
    anchors = [
        build_standard_anchor(None, item.module_id, 450, StandardAnchorValues(False))
        for item in modules
    ]
    document = DrawingGenerator().generate(Project(modules=modules, boards=boards, anchors=anchors))
    output = export_dxf(document, tmp_path / "separator.dxf", "references/示例.dxf")
    exported = ezdxf.readfile(output)
    separators = [
        line
        for line in exported.modelspace().query("LINE")
        if line.dxf.layer == "FRAME" and abs(line.dxf.start.x - line.dxf.end.x) < 0.01
    ]
    assert len(separators) == 1
    ys = sorted((separators[0].dxf.start.y, separators[0].dxf.end.y))
    assert ys[0] == pytest.approx(520.0)
    assert ys[1] == pytest.approx(1880.0)


def test_automatic_layout_keeps_panel_gaps_and_paginates():
    modules = [
        build_standard_module(None, StandardModuleValues(f"W{i}", 600, 300, 230))
        for i in range(1, 7)
    ]
    boards = [build_standard_board(None, item.module_id, True) for item in modules]
    anchors = [build_standard_anchor(None, item.module_id, 600, StandardAnchorValues(False)) for item in modules]
    document = DrawingGenerator().generate(Project(modules=modules, boards=boards, anchors=anchors))

    assert len(document.pages) > 1
    for page in document.pages:
        for placed in page.modules:
            assert placed.content_x_mm >= placed.x_mm + PANEL_INNER_MARGIN_MM
            assert placed.content_x_mm <= placed.x_mm + placed.panel_width_mm - PANEL_INNER_MARGIN_MM
        for left, right in zip(page.modules, page.modules[1:]):
            assert left.x_mm + left.panel_width_mm <= right.x_mm


def test_balanced_pages_do_not_leave_a_tiny_last_page():
    groups = _balanced_page_groups([150, 120, 70])
    assert groups == [(0, 1), (1, 3)]


def test_short_module_details_are_centered_independently_of_geometry(tmp_path):
    item = build_standard_module(None, StandardModuleValues("M1", 350, 300, 230))
    document = DrawingGenerator().generate(Project(modules=[item]))
    placed, = document.pages[0].modules
    left, width = detail_box(placed)
    center = placed.x_mm + placed.panel_width_mm / 2
    assert left + details_width(placed.drawing) / 2 == pytest.approx(center)
    assert left < placed.content_x_mm
    output = export_dxf(document, tmp_path / "short-module.dxf")
    detail, = ezdxf.readfile(output).modelspace().query("MTEXT")
    assert detail.dxf.insert.x == pytest.approx(left * 10)
    assert detail.dxf.width == pytest.approx(width * 10)


def test_long_module_details_line_up_with_geometry_on_the_left():
    item = build_standard_module(None, StandardModuleValues("M1", 351, 300, 230))
    document = DrawingGenerator().generate(Project(modules=[item]))
    placed, = document.pages[0].modules
    assert detail_box(placed)[0] == pytest.approx(placed.content_x_mm)


@pytest.mark.parametrize(("board_exists", "label"), [(True, "夹板"), (False, "无夹板")])
def test_board_face_has_status_label_when_no_anchors(tmp_path, board_exists, label):
    item = build_standard_module(None, StandardModuleValues("M1", 300, 300, 230))
    board = build_standard_board(None, item.module_id, board_exists)
    document = DrawingGenerator().generate(Project(modules=[item], boards=[board]))
    assert document.pages[0].modules[0].drawing.board_view.note == label
    output = export_dxf(document, tmp_path / "board-label.dxf")
    labels = list(ezdxf.readfile(output).modelspace().query("TEXT"))
    assert [entity.dxf.text for entity in labels] == ["M1", label]
    assert labels[-1].get_align_enum().name == "MIDDLE_CENTER"


def test_update_selects_the_latest_formal_release_with_a_standard_portable_zip(monkeypatch):
    monkeypatch.setattr("refracdraft.release.app_version", lambda: "0.1.1")

    def release(tag, *, prerelease=False, standard_zip=True):
        assets = [{"name": f"RefracDraft-Standard-Windows-x64-portable-{tag.removeprefix('standard-')}.zip"}]
        return {"tag_name": tag, "prerelease": prerelease, "assets": assets if standard_zip else []}

    current = release("standard-v0.1.1")
    assert latest_portable_release([current, release("standard-20261118-editor-shx-final")]) is None
    version, url = latest_portable_release([
        current,
        release("standard-v0.2.1", prerelease=True),
        release("standard-v0.2.0", standard_zip=False),
        release("standard-v0.1.2"),
    ])
    assert version == "0.1.2"
    assert url.endswith("/standard-v0.1.2/RefracDraft-Standard-Windows-x64-portable-v0.1.2.zip")


def test_dxf_uses_reference_dimension_style_and_big_font(tmp_path):
    module = build_standard_module(None, StandardModuleValues("S1", 300, 300, 230))
    board = build_standard_board(None, "S1", True)
    anchor = build_standard_anchor(
        None,
        "S1",
        300,
        StandardAnchorValues(True, 150, 300, 1, AnchorType.DIAMOND, 50),
    )
    document = DrawingGenerator().generate(Project(modules=[module], boards=[board], anchors=[anchor]))
    output = export_dxf(document, tmp_path / "standard.dxf", "references/示例.dxf")
    exported = ezdxf.readfile(output)

    dimensions = [entity for entity in exported.modelspace() if entity.dxftype() == "DIMENSION"]
    assert dimensions
    assert {dimension.dxf.dimstyle for dimension in dimensions} == {"_10"}
    assert {entity.dxf.style for entity in exported.modelspace().query("TEXT MTEXT")} == {"大字体"}
    assert exported.dimstyles.get("_10").dxf.dimtxsty == "大字体"
    assert exported.dimstyles.get("_10").dxf.dimscale == 20
    assert exported.dimstyles.get("_10").dxf.dimtxt == pytest.approx(DIMENSION_TEXT_SIZE_MM / 2)
    frame_inserts = [entity for entity in exported.modelspace().query("INSERT") if entity.dxf.name == "图框-A4"]
    assert frame_inserts
    assert frame_inserts[0].dxf.xscale == pytest.approx(10.0)
    title_inserts = [entity for entity in exported.modelspace().query("INSERT") if entity.dxf.name == "标题栏"]
    assert title_inserts
    assert title_inserts[0].dxf.xscale == pytest.approx(1.02)
    detail_texts = list(exported.modelspace().query("MTEXT"))
    assert len(detail_texts) == 1
    assert detail_texts[0].dxf.char_height == pytest.approx(DETAIL_TEXT_SIZE_MM * 10.0)
    assert detail_texts[0].dxf.width > 0
    assert detail_texts[0].dxf.line_spacing_style == 2
    assert detail_texts[0].dxf.line_spacing_factor == pytest.approx(DETAIL_LINE_SPACING)
    assert "\\P" in detail_texts[0].text
    assert detail_texts[0].dxf.insert.y > 44 * 10
    for style_name in ("工程字", "大字体"):
        style = exported.styles.get(style_name)
        assert style.dxf.font.lower() == "gbenor.shx"
        assert style.dxf.bigfont.lower() == "gbcbig.shx"


def test_standard_example_excel_headers_follow_parameter_table():
    path = Path("examples/standard_example_6_modules.xlsx")
    workbook = load_workbook(path, read_only=True)
    try:
        assert workbook.sheetnames == ["标准版"]
        assert next(workbook.active.values) == tuple(spec.label for spec in COLUMN_SPECS)
    finally:
        workbook.close()
    project = import_project_xlsx(path)
    assert [module.module_id for module in project.modules] == [f"M{i}" for i in range(1, 7)]
    assert len(project.boards) == len(project.anchors) == 6
    assert project.modules[3].custom_structure_label == "自定义折叠"
    assert project.modules[-1].geometry_type == GeometryType.SIDE_TAPER
    assert project.anchors[-1].embedment_depth_mm == 50


def test_import_accepts_legacy_excel_groups(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "模块参数"
    sheet.append(["模块编号", "正面宽度", "正面高度", "夹板面宽度", "夹板面高度"])
    sheet.append(["M1", 300, 300, 300, 230])
    board = workbook.create_sheet("夹板参数")
    board.append(["模块编号", "是否有夹板"])
    board.append(["M1", "是"])
    anchor = workbook.create_sheet("锚固件参数")
    anchor.append(["模块编号", "是否有锚固件", "锚固件类型", "锚固件数量"])
    anchor.append(["M1", "否", "无", 0])
    path = tmp_path / "legacy.xlsx"
    workbook.save(path)
    project = import_project_xlsx(path)
    assert project.modules[0].module_id == "M1"
    assert project.boards[0].exists
    assert not project.anchors[0].exists


def test_pdf_plot_uses_one_font_in_title_and_nested_logo_without_changing_source(tmp_path):
    source = ezdxf.new("R2018")
    title = source.blocks.new("标题栏")
    logo = source.blocks.new("设计标志")
    title.add_blockref(logo.name, (50, 50))
    english = title.add_mtext(r"{\T0.9;ZHUMADIAN\fSimSun|b0;\~\fFangSong|b0;HENGRUI}")
    chinese = logo.add_mtext(r"{\fSimHei|b0;\C170;恒 瑞}")
    source.modelspace().add_blockref(title.name, (0, 0))
    input_path = tmp_path / "source.dxf"
    source.saveas(input_path)

    plotted_path = _single_page_dxf(input_path, 0, tmp_path / "plot.dxf", True)
    plotted = ezdxf.readfile(plotted_path)
    plotted_english, = plotted.blocks[title.name].query("MTEXT")
    plotted_chinese, = plotted.blocks[logo.name].query("MTEXT")
    assert plotted_english.text == r"{\T0.9;ZHUMADIAN HENGRUI}"
    assert plotted_chinese.text == r"{\C170;恒 瑞}"
    original = ezdxf.readfile(input_path)
    assert original.entitydb[english.dxf.handle].text == english.text
    assert original.entitydb[chinese.dxf.handle].text == chinese.text


def test_pdf_prefers_bundled_song_font_to_system_font(monkeypatch):
    bundled_song = next(path for path in PDF_FONT_CANDIDATES if path.name == "SourceHanSerifSC-Regular.otf")
    system_font = Path(r"C:\Windows\Fonts\simsun.ttc")
    monkeypatch.setattr(Path, "is_file", lambda path: path in (bundled_song, system_font))
    assert _find_pdf_font() == bundled_song


def test_pdf_render_skips_layers_with_plot_disabled():
    source = ezdxf.new("R2018")
    source.layers.add("PRINT", color=7)
    no_plot = source.layers.add("NO_PLOT", color=1)
    no_plot.dxf.plot = 0
    msp = source.modelspace()
    msp.add_line((0, 0), (1000, 0), dxfattribs={"layer": "PRINT"})
    msp.add_line((0, 500), (1000, 500), dxfattribs={"layer": "NO_PLOT", "color": 1})

    pdf_bytes = _render_page(source, 0, None)
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
        drawings = pdf[0].get_drawings()

    assert drawings
    red_paths = [
        drawing
        for drawing in drawings
        if drawing.get("color") and tuple(round(v, 3) for v in drawing["color"]) == (1.0, 0.0, 0.0)
    ]
    assert red_paths == []

