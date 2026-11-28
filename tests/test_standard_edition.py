from dataclasses import replace
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
import ezdxf
import pymupdf
from openpyxl import Workbook, load_workbook

from refracdraft.drawing.generator import DrawingGenerator, _anchor_positions, _balanced_page_groups, _details
from refracdraft.drawing.model import DrawingDocument, SheetPage
from refracdraft.drawing.layout import (
    DETAIL_LINE_SPACING,
    DETAIL_TEXT_SIZE_MM,
    DIMENSION_TEXT_SIZE_MM,
    DETAIL_LINE_HEIGHT_MM,
    DETAIL_TITLE_CLEARANCE_MM,
    DETAIL_VIEW_CLEARANCE_MM,
    FRAME_INSET_MM,
    PAGE_CONTENT_WIDTH_MM,
    PAGE_HEIGHT_MM,
    PAGE_LEFT_MM,
    PANEL_INNER_MARGIN_MM,
    SIDE_DETAIL_GAP_MM,
    SIDE_DETAIL_RIGHT_MARGIN_MM,
    SIDE_PANEL_GAP_MM,
    TITLE_BLOCK_TOP_MM,
    VIEW_CLEARANCE_MM,
    detail_box,
    detail_line_width_factor,
    detail_lines,
    detail_vertical_anchor,
    details_width,
    page_model_origins,
    view_bounds,
    view_placement,
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
from refracdraft.exporters.pdf import (
    PDF_FONT_CANDIDATES,
    PdfPageCache,
    ShxFontInfo,
    _export_pdf_with_shx,
    _find_pdf_font,
    _fix_shx_page_scale,
    _render_fallback_pages,
    _render_page,
    _single_page_dxf,
    export_pdf,
)
from refracdraft.exporters.project import export_standard_excel
from refracdraft.release import RELEASES_URL, latest_portable_release, portable_release_from_latest_url
from refracdraft.standard_sheet import (
    AUTOMATIC, AUTOMATIC_FIELDS, COLUMN_SPECS, DEFAULT_ROW, EQUAL_SEGMENTS, anchor_length_options, build_standard_row,
    resolve_automatic_values,
)
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
        {"编号": "S1", "几何类型": "侧敲", "大头": 300, "小头": 200},
        "modules",
    )
    assert normalized["side_left_height_mm"] == 300
    assert normalized["side_right_height_mm"] == 200
    assert "front_left_height_mm" not in normalized
    assert "front_right_height_mm" not in normalized


@pytest.mark.parametrize(("label", "expected_type", "has_side_view"), [
    ("侧敲", GeometryType.SIDE_TAPER, True),
    ("正敲", GeometryType.FRONT_TAPER, False),
    ("正常敲", GeometryType.FRONT_TAPER, False),
])
def test_standard_taper_labels_generate_the_correct_views(label, expected_type, has_side_view):
    module, board, anchor = build_standard_row({
        **DEFAULT_ROW, "taper_enabled": True, "taper_type": label,
    })
    assert module.geometry_type == expected_type
    project = Project(modules=[module], boards=[board], anchors=[anchor])
    view = DrawingGenerator().generate(project).pages[0].modules[0].drawing
    assert (view.side_view is not None) == has_side_view
    assert view.details[-1] == ("8、侧敲" if has_side_view else "8、正常敲")
    legacy = module.model_dump(mode="json")
    legacy["geometry_type"] = "正敲" if has_side_view else "侧敲"
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


@pytest.mark.parametrize("anchor_type", ["旁插", "快插"])
def test_insert_anchor_remark_can_be_edited_or_cleared(anchor_type):
    values = dict(DEFAULT_ROW, anchor_enabled=True, anchor_type=anchor_type)
    module, board, anchor = build_standard_row(values)
    assert module.source_note == "木板开口60*110 插针隔1层毯子插"
    assert _details(module, board, anchor)[-1] == f"8、{module.source_note}"
    for remark in ("现场复核开口", ""):
        module, board, anchor = build_standard_row(dict(values, source_note=remark))
        details = _details(module, board, anchor)
        assert [line for line in details if line.startswith("8、")] == ([f"8、{remark}"] if remark else [])


def test_blank_anchor_fields_and_remark_roundtrip_in_json_and_excel(tmp_path):
    module, board, anchor = build_standard_row(dict(
        DEFAULT_ROW, anchor_enabled=True, anchor_type="快插", anchor_length_mm="", anchor_material="",
        thread_spec="", pin_diameter_mm="", source_note="",
    ))
    project = Project(modules=[module], boards=[board], anchors=[anchor], standard_link_version=2)
    path = tmp_path / "empty-fields.xlsx"
    export_standard_excel(project, path)
    for restored in (Project.model_validate_json(project.model_dump_json()), import_project_xlsx(path)):
        module, board, anchor = restored.modules[0], restored.boards[0], restored.anchors[0]
        assert (anchor.length_mm, anchor.material, anchor.thread_spec, anchor.diameter_mm) == (None, "", "", None)
        assert not restored.standard_auto_fields.get("M1")
        assert module.source_note == ""
        assert _details(module, board, anchor)[2:4] == ("3、锚固件：快插", "4、锚固件长度：")


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
    assert len(drawing.front_view.internal_lines) == 2
    assert len(drawing.front_view.layer_marks) == 4
    assert len(drawing.side_view.layer_marks) == 4


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


def test_repeated_generation_rebuilds_only_changed_modules_and_keeps_fresh_pagination(monkeypatch):
    first = build_standard_module(None, StandardModuleValues("A", 300, 300, 230))
    second = build_standard_module(None, StandardModuleValues("B", 310, 300, 230))
    project = Project(modules=[first, second])
    generator = DrawingGenerator(reuse_modules=True)
    original_build = generator.build_module
    built = []

    def record_build(project, module):
        built.append(module.module_id)
        return original_build(project, module)

    monkeypatch.setattr(generator, "build_module", record_build)
    initial_pages = generator.generate(project).pages
    assert built == ["A", "B"]

    built.clear()
    assert generator.generate(project).pages == initial_pages
    assert generator.reused_module_count == 2
    assert built == []

    long_module = build_standard_module(None, StandardModuleValues("B", 4700, 300, 230))
    changed = Project(modules=[first, long_module])
    result = generator.generate(changed)
    assert built == ["B"]
    assert generator.reused_module_count == 1
    assert result == DrawingGenerator().generate(changed)
    assert [page.scale_denominator for page in result.pages] == [10, 20]

    built.clear()
    board_changed = changed.model_copy(update={"boards": [BoardParameters(module_id="A", source_note="新夹板备注")]})
    generator.generate(board_changed)
    assert built == ["A"]

    built.clear()
    anchor = AnchorParameters(module_id="B", exists=False, count=0, source_note="新增锚固件备注")
    anchor_changed = board_changed.model_copy(update={"anchors": [anchor]})
    generator.generate(anchor_changed)
    assert built == ["B"]

    built.clear()
    reordered = anchor_changed.model_copy(update={"modules": [long_module, first]})
    assert generator.generate(reordered) == DrawingGenerator().generate(reordered)
    assert generator.reused_module_count == 2
    assert built == []


def test_balanced_pages_do_not_leave_a_tiny_last_page():
    groups = _balanced_page_groups([150, 120, 70])
    assert groups == [(0, 1), (1, 3)]


def test_short_module_details_are_centered_on_views(tmp_path):
    item = build_standard_module(None, StandardModuleValues("M1", 350, 300, 230))
    document = DrawingGenerator().generate(Project(modules=[item]))
    placed, = document.pages[0].modules
    left, width = detail_box(placed)
    center = placed.x_mm + placed.panel_width_mm / 2
    assert left + details_width(placed.drawing) / 2 == pytest.approx(center)
    output = export_dxf(document, tmp_path / "short-module.dxf")
    detail, = ezdxf.readfile(output).modelspace().query("MTEXT")
    assert detail.dxf.insert.x == pytest.approx(left * 10)
    assert detail.dxf.width == 0
    assert width > 0


@pytest.mark.parametrize("length", [351, 600, 900])
def test_long_two_view_module_details_follow_outline_left_edge(length):
    item = build_standard_module(None, StandardModuleValues("M1", length, 300, 230))
    document = DrawingGenerator().generate(Project(modules=[item]))
    placed, = document.pages[0].modules
    left, _ = detail_box(placed)
    assert left == pytest.approx(placed.content_x_mm)


def test_1120_pair_uses_balanced_below_view_details_when_full_stack_fits(tmp_path):
    rows = [
        build_standard_row(
            dict(DEFAULT_ROW, module_id=f"M{index}", length_mm=str(length), thickness_mm="300",
                 expansion_length_mm=str(height), anchor_enabled=True, anchor_count=str(index),
                 anchor_position_mm="150", anchor_spacing_mm="300",
                 anchor_type="旁插" if index == 1 else "M型", thread_spec="M8" if index == 1 else "M10",
                 source_note=AUTOMATIC if index == 1 else "普通模块示例"),
            board_face_profile=BoardFaceProfile.model_validate({"features": [feature]}),
        )
        for index, length, height, feature in (
            (1, 300, 300, {"type": 2, "a": 90, "b": 90, "c": 90, "d": 45}),
            (2, 600, 350, {"type": 1, "a": 50, "b": 50, "rotation_deg": 180}),
        )
    ]
    modules, boards, anchors = map(list, zip(*rows))
    remaining = import_project_xlsx("examples/standard_example_6_modules.xlsx")
    document = DrawingGenerator().generate(Project(
        modules=modules + remaining.modules[2:], boards=boards + remaining.boards[2:],
        anchors=anchors + remaining.anchors[2:],
    ))
    assert [[placed.drawing.module_id for placed in page.modules] for page in document.pages] == [
        ["M1", "M2"], ["M3", "M4"], ["M5", "M6"],
    ]
    page = document.pages[0]
    assert [placed.drawing.module_id for placed in page.modules] == ["M1", "M2"]
    assert "木板开口" in page.modules[0].drawing.details[-1]
    output = export_dxf(DrawingDocument(document.project_name, (page,)), tmp_path / "below-view-details.dxf")
    details = list(ezdxf.readfile(output).modelspace().query("MTEXT"))
    ceiling = PAGE_HEIGHT_MM - FRAME_INSET_MM - 2
    floor = TITLE_BLOCK_TOP_MM + DETAIL_TITLE_CLEARANCE_MM
    for placed, entity in zip(page.modules, details, strict=True):
        drawing = placed.drawing
        layout = view_placement(drawing)
        anchor_y, align_bottom = detail_vertical_anchor(placed)
        assert not align_bottom
        assert entity.dxf.attachment_point == 1
        assert entity.dxf.insert.y == pytest.approx(anchor_y * 10)
        assert entity.plain_text(split=True) == list(drawing.details)
        assert entity.dxf.width == 0 and r"\W" not in entity.text
        _, front_bottom, _, front_top = view_bounds(drawing.front_view)
        _, board_bottom, _, board_top = view_bounds(drawing.board_view)
        assert layout.top_y + front_bottom - (layout.board_y + board_top) >= VIEW_CLEARANCE_MM - 1e-6
        assert layout.board_y + board_bottom - anchor_y >= DETAIL_VIEW_CLEARANCE_MM - 1e-6
        text_bottom = anchor_y - DETAIL_TEXT_SIZE_MM - (len(drawing.details) - 1) * DETAIL_LINE_HEIGHT_MM - 1
        assert text_bottom >= floor
        assert ceiling - (layout.top_y + front_top) == pytest.approx(text_bottom - floor)
    assert detail_box(page.modules[1])[0] == pytest.approx(page.modules[1].content_x_mm)


@pytest.mark.parametrize(
    ("length", "density", "thread", "fold", "board_mm", "hose"),
    [(600, 192, "M8", StructureType.FOLDED, 8, "25胶管"),
     (601, 193, "M10", StructureType.HALF_FOLDED, 9, "32胶管")],
)
def test_standard_associations_keep_manual_choices_and_roundtrip(
    tmp_path, length, density, thread, fold, board_mm, hose,
):
    values = dict(DEFAULT_ROW, **dict.fromkeys(AUTOMATIC_FIELDS, AUTOMATIC))
    values.update(length_mm=str(length), density_kg_m3=str(density), material="1430",
                  thread_spec=thread, anchor_enabled=True, expansion_length_mm="300")
    module, board, anchor = build_standard_row(values)
    assert (module.structure_type, board.thickness_mm, anchor.material, anchor.hose_spec, anchor.length_mm) == (
        fold, board_mm, "310", hose, 240,
    )
    values.update(structure_type="层叠", board_material="12厘", anchor_material="309", hose_spec="40",
                  anchor_length_mm="233.5")
    manual_module, manual_board, manual_anchor = build_standard_row(values)
    assert (manual_module.structure_type, manual_board.thickness_mm, manual_anchor.material,
            manual_anchor.hose_spec, manual_anchor.length_mm) == (StructureType.STACKED, 12, "309", "40胶管", 233.5)
    project = Project(modules=[module], boards=[board], anchors=[anchor],
                      standard_auto_fields={"M1": list(AUTOMATIC_FIELDS)})
    path = tmp_path / "standard-auto.xlsx"
    export_standard_excel(project, path)
    restored = import_project_xlsx(path)
    assert restored.standard_auto_fields == project.standard_auto_fields
    assert restored.modules[0].structure_type == fold
    assert restored.anchors[0].length_mm == 240
    assert Project.model_validate_json(project.model_dump_json()).standard_auto_fields == project.standard_auto_fields


@pytest.mark.parametrize(
    ("grade", "expected_material"),
    [("1260", "304"), ("1400", "304"), ("1430", "310"), ("1500", "310")],
)
def test_automatic_anchor_material_tracks_module_grade(grade, expected_material):
    values = dict(DEFAULT_ROW, anchor_enabled=True, anchor_material=AUTOMATIC, material=grade)
    assert resolve_automatic_values(values)["anchor_material"] == expected_material
    assert build_standard_row(values)[2].material == expected_material
    values["anchor_material"] = "309"
    assert build_standard_row(values)[2].material == "309"


def test_automatic_anchor_material_updates_after_grade_changes():
    values = dict(DEFAULT_ROW, anchor_enabled=True, anchor_material=AUTOMATIC, material="1430")
    for grade, expected in (("1430", "310"), ("1260", "304"), ("1600", "310"), ("1050", "304")):
        values["material"] = grade
        assert resolve_automatic_values(values)["anchor_material"] == expected
        assert build_standard_row(values)[2].material == expected
    values["material"] = "铬锆复合"
    assert resolve_automatic_values(values, {"anchor_material": "201"})["anchor_material"] == "201"


def test_legacy_excel_resolves_associations_and_keeps_custom_values(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "标准版"
    sheet.append([spec.label for spec in COLUMN_SPECS])
    row = dict(DEFAULT_ROW, length_mm="700", density_kg_m3="192", anchor_enabled=True,
               anchor_material="304", thread_spec="M8", anchor_position_mm=None,
               board_material="9厘", hose_spec="32", anchor_length_mm="233.5")
    sheet.append([row[spec.key] for spec in COLUMN_SPECS])
    path = tmp_path / "legacy-standard.xlsx"
    workbook.save(path)
    result = import_project_xlsx(path)
    assert result.modules[0].structure_type == StructureType.HALF_FOLDED
    assert result.boards[0].thickness_mm == 8
    anchor = result.anchors[0]
    assert (anchor.material, anchor.hose_spec, anchor.length_mm) == ("310", "25胶管", 233.5)
    assert anchor.layout_mode == LayoutMode.EQUAL_SEGMENTS
    assert anchor_length_options("菱形") == ("230", "200", "180", "150", "120")


def test_standard_excel_blanks_use_new_module_defaults(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "标准版"
    sheet.append([spec.label for spec in COLUMN_SPECS])
    sheet.append([None, "   "])
    sheet.append([" M20 "])
    provided = {"module_id": "M21", "length_mm": 480, "board_exists": False, "anchor_enabled": True}
    sheet.append([provided.get(spec.key) for spec in COLUMN_SPECS])
    path = tmp_path / "defaults.xlsx"
    workbook.save(path)

    project = import_project_xlsx(path)
    expected = [
        build_standard_row(dict(DEFAULT_ROW, module_id="M20")),
        build_standard_row(dict(DEFAULT_ROW, **provided)),
    ]
    assert list(zip(project.modules, project.boards, project.anchors)) == expected
    assert [module.module_id for module in project.modules] == ["M20", "M21"]
    assert not project.boards[1].exists
    assert project.anchors[1].layout_mode == LayoutMode.EQUAL_SEGMENTS


@pytest.mark.parametrize("sheet_name", ["标准版", "模块参数"])
def test_excel_skips_wholly_blank_rows_but_requires_module_id(tmp_path, sheet_name):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    sheet.append(["编号", "长度"])
    sheet.append(["M1"])
    sheet.append([None, "   "])
    path = tmp_path / "sparse.xlsx"
    workbook.save(path)
    module, = import_project_xlsx(path).modules
    assert module.module_id == "M1"
    assert (module.front_width_mm, module.front_height_mm, module.board_face_height_mm) == (300, 300, 230)

    sheet.append([" ", 300])
    workbook.save(path)
    with pytest.raises(ValueError, match=r"第 4 行：模块编号不能为空"):
        import_project_xlsx(path)


def test_standard_excel_still_validates_explicit_nonblank_values(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "标准版"
    sheet.append(["编号", "数量"])
    sheet.append(["M1", 0])
    path = tmp_path / "invalid.xlsx"
    workbook.save(path)
    with pytest.raises(ValueError, match=r"第 2 行.*数量"):
        import_project_xlsx(path)


def test_measured_details_pack_the_450mm_pair_without_compressing_text(tmp_path):
    rows = [build_standard_row(
        dict(DEFAULT_ROW, module_id=f"M{index}", length_mm=str(length), thickness_mm="450",
             expansion_length_mm=str(height), anchor_enabled=True, anchor_count=str(index),
             anchor_position_mm="150", anchor_spacing_mm="300", source_note="普通模块示例"),
        board_face_profile=BoardFaceProfile.model_validate({"features": [cut]}),
    ) for index, length, height, cut in (
        (1, 300, 300, {"type": 2, "a": 90, "b": 90, "c": 90, "d": 45}),
        (2, 600, 350, {"type": 1, "a": 50, "b": 50, "rotation_deg": 180}),
    )]
    modules, boards, anchors = map(list, zip(*rows))
    project = Project(modules=modules, boards=boards, anchors=anchors)
    # The fixture models the advance of the compact SHX lettering used in the PDF.
    drawing = DrawingGenerator().generate(
        project, measure_detail=lambda text: sum(2.8 if char.isascii() else 4.8 for char in text),
    )
    page, = drawing.pages
    assert [placed.drawing.module_id for placed in page.modules] == ["M1", "M2"]
    assert any(not detail_vertical_anchor(placed)[1] for placed in page.modules)
    for placed in page.modules:
        module = placed.drawing
        layout = view_placement(module)
        if not layout.detail_on_side:
            assert layout.board_y + view_bounds(module.board_view)[1] - layout.detail_y >= DETAIL_VIEW_CLEARANCE_MM - 1e-6
    drawing = replace(drawing, pages=(page, replace(page, page_number=2)), filename_label="加工图_1120")
    path = export_dxf(drawing, tmp_path / "packed.dxf")
    msp = ezdxf.readfile(path).modelspace()
    assert all(r"\W" not in text.text for text in msp.query("MTEXT"))
    # The page count must be immediately beside the filename in all renderers,
    # rather than positioned using a coarse estimate of Chinese glyph widths.
    footer_labels = [
        text for text in msp.query("TEXT")
        if text.dxf.text.startswith(f"{drawing.filename_label}  第")
    ]
    assert [text.dxf.text for text in footer_labels] == [
        "加工图_1120  第1页 共2页", "加工图_1120  第2页 共2页",
    ]
    assert [text.dxf.insert.x for text in footer_labels] == pytest.approx([90, 90])
    assert [text.dxf.insert.y for text in footer_labels] == pytest.approx([190, -2110])
    assert [text.dxf.height for text in footer_labels] == pytest.approx([24, 24])
    assert not any(text.dxf.text == drawing.filename_label for text in msp.query("TEXT"))

    no_filename = export_dxf(
        replace(drawing, filename_label=""), tmp_path / "packed-no-filename.dxf",
    )
    footer_texts = list(ezdxf.readfile(no_filename).modelspace().query("TEXT"))
    assert not any(text.dxf.text == drawing.filename_label for text in footer_texts)
    bare_page_labels = [
        text for text in footer_texts
        if text.dxf.text in ("第1页 共2页", "第2页 共2页")
    ]
    assert [text.dxf.insert.x for text in bare_page_labels] == pytest.approx([90, 90])

    # Match the reported customer case and verify no independent far-right
    # page-number TEXT object can be created by the DXF export.
    sample_filename = "模块加工图__1121__测试"
    sample_drawing = replace(drawing, filename_label=sample_filename)
    sample_path = export_dxf(sample_drawing, tmp_path / "customer-footer.dxf")
    sample_labels = [
        entity for entity in ezdxf.readfile(sample_path).modelspace().query("TEXT")
        if "页 共" in entity.dxf.text
    ]
    assert [entity.dxf.text for entity in sample_labels] == [
        f"{sample_filename}  第1页 共2页",
        f"{sample_filename}  第2页 共2页",
    ]
    assert all(entity.dxf.insert.x == pytest.approx(90) for entity in sample_labels)


@pytest.mark.parametrize(
    ("anchor_type", "taper", "height", "expected"),
    [("M型", "正常敲", 320, 180), ("M型", "侧敲", 310, 240), ("M型", "", 350, 240),
     ("M型", "", 270, 220), ("M型", "", 269.99, 200), ("菱形", "", 280, 230), ("菱形", "", 279.99, 200),
     ("菱形", "", 170, 120), ("菱形", "", 169.99, None),
     ("菱形", "正常敲", 320, 180), ("菱形", "侧敲", 310, 230),
     ("旁插", "正敲", 320, 180), ("快插", "", 460, 410), ("快插", "", 400, 350)],
)
def test_standard_automatic_anchor_lengths_use_installation_height(anchor_type, taper, height, expected):
    values = dict(DEFAULT_ROW, length_mm="600", expansion_length_mm=str(height), taper_enabled=bool(taper),
                  taper_type=taper, big_head_mm=str(height), small_head_mm="190", anchor_enabled=True,
                  anchor_type=anchor_type, anchor_position_mm="60", anchor_spacing_mm="300",
                  anchor_count="2", anchor_length_mm=AUTOMATIC)
    _, _, anchor = build_standard_row(values)
    assert anchor.length_mm == expected


def test_standard_equal_segments_survive_json_and_excel_and_dimension_each_anchor(tmp_path):
    def build(length, count):
        return build_standard_row(dict(DEFAULT_ROW, length_mm=str(length), anchor_count=str(count),
                                       anchor_enabled=True, anchor_spacing_mm=""))

    _, _, single = build(450, 1)
    assert single.layout_mode == LayoutMode.EQUAL_SEGMENTS and single.edge_offset_mm == 225

    module, board, anchor = build(610, 3)
    assert anchor.edge_offset_mm == pytest.approx(610 / 6)
    assert anchor.spacing_mm == pytest.approx(610 / 3)
    project = Project(modules=[module], boards=[board], anchors=[anchor])
    workbook = tmp_path / "equal.xlsx"
    export_standard_excel(project, workbook)
    for restored in (import_project_xlsx(workbook), Project.model_validate_json(project.model_dump_json())):
        restored_anchor = restored.anchors[0]
        assert restored_anchor.layout_mode == LayoutMode.EQUAL_SEGMENTS
        xs = [x for x, _ in _anchor_positions(restored_anchor, 610, 230, board_face=True)]
        assert xs == pytest.approx([610 / 6, 305, 610 * 5 / 6])
        drawing = DrawingGenerator().build_module(restored, restored.modules[0])
        assert {"101.667", "203.333", "610"} <= {mark.label for mark in drawing.board_view.dimensions}


def test_standard_taper_pin_length_tracks_equal_positions_and_embedment():
    values = dict(DEFAULT_ROW, length_mm="600", taper_enabled=True, taper_type="正常敲",
                  big_head_mm="320", small_head_mm="190", anchor_enabled=True, anchor_length_mm=AUTOMATIC,
                  anchor_position_mm=EQUAL_SEGMENTS, anchor_count="3")
    assert build_standard_row(values)[2].length_mm == 150
    values["anchor_count"] = "1"
    assert build_standard_row(values)[2].length_mm == 200
    values.update(taper_type="侧敲", anchor_type="菱形", big_head_mm="310", embedment_depth_mm="100")
    assert build_standard_row(values)[2].length_mm == 200
    values.update(anchor_type="焊接菱形", bolt_exposure_mm="50")
    assert build_standard_row(values)[0].source_note == "侧敲；螺栓长度150mm，外露50mm"


def test_tall_1120_style_pair_keeps_details_clear(tmp_path):
    profile = BoardFaceProfile.model_validate({"features": [
        {"type": 2, "a": 69, "b": 90, "c": 69, "d": 50, "rotation_deg": 270, "mirror_x": True},
    ]})
    rows = [build_standard_row(
        dict(DEFAULT_ROW, module_id=f"M{index}", length_mm="300", thickness_mm="550",
             taper_enabled=True, taper_type="正敲", big_head_mm="289", small_head_mm="220",
             anchor_enabled=True, anchor_type="旁插", anchor_position_mm="150"),
        board_face_profile=profile,
    ) for index in (1, 2)]
    modules, boards, anchors = map(list, zip(*rows))
    doc = DrawingGenerator().generate(Project(modules=modules, boards=boards, anchors=anchors))
    output = export_dxf(doc, tmp_path / "side-details.dxf")
    details = list(ezdxf.readfile(output).modelspace().query("MTEXT"))
    placed_modules = [(page, placed) for page in doc.pages for placed in page.modules]
    assert len(doc.pages) == 1
    assert [placed.drawing.module_id for _, placed in placed_modules] == ["M1", "M2"]
    for (page, placed), detail in zip(placed_modules, details, strict=True):
        left, width = detail_box(placed)
        assert left + width < placed.x_mm + placed.panel_width_mm
        anchor_y, align_bottom = detail_vertical_anchor(placed)
        layout = view_placement(placed.drawing)
        if align_bottom:
            geometry_right = max(view_bounds(view)[2] for view in (placed.drawing.front_view, placed.drawing.board_view))
            assert left == pytest.approx(placed.content_x_mm + geometry_right + SIDE_DETAIL_GAP_MM)
            assert anchor_y == pytest.approx(layout.board_y + placed.drawing.board_view.outline.bounds[1] / 10)
        else:
            measured_bottom = layout.board_y + view_bounds(placed.drawing.board_view)[1]
            assert measured_bottom - anchor_y >= DETAIL_VIEW_CLEARANCE_MM - 1e-6
        assert detail.dxf.attachment_point == (7 if align_bottom else 1)
        assert detail.dxf.insert.y == pytest.approx((anchor_y - (page.page_number - 1) * 230) * 10)
        assert detail.dxf.width == 0
        assert detail.plain_text(split=True) == list(placed.drawing.details)


@pytest.mark.parametrize("note", ["普通模块示例", "工艺备注" * 32])
def test_side_details_use_the_panel_width_without_wrapping(note):
    profile = BoardFaceProfile.model_validate({"features": [
        {"type": 2, "a": 69, "b": 90, "c": 69, "d": 45},
    ]})
    rows = [build_standard_row(
        dict(DEFAULT_ROW, module_id=f"M{index}", length_mm=str(length), thickness_mm=str(thickness),
             expansion_length_mm=str(height), anchor_enabled=True, anchor_count=str(index),
             anchor_position_mm="150", anchor_spacing_mm="300", production_quantity=str(index), source_note=note),
        board_face_profile=profile if index == 1 else None,
    ) for index, length, thickness, height in ((1, 300, 600, 300), (2, 600, 600, 350))]
    modules, boards, anchors = map(list, zip(*rows))
    document = DrawingGenerator().generate(Project(modules=modules, boards=boards, anchors=anchors))
    long_note = note != "普通模块示例"
    assert len(document.pages) == (2 if long_note else 1)
    if not long_note:
        first, second = document.pages[0].modules
        assert (first.drawing.module_id, second.drawing.module_id) == ("M1", "M2")
        assert second.x_mm - (first.x_mm + first.panel_width_mm) == pytest.approx(SIDE_PANEL_GAP_MM)
        right_text_x, right_text_width = detail_box(second)
        assert right_text_x + right_text_width < PAGE_LEFT_MM + PAGE_CONTENT_WIDTH_MM
    for page in document.pages:
        for placed in page.modules:
            left, width = detail_box(placed)
            assert width > 60
            assert left + width == pytest.approx(placed.x_mm + placed.panel_width_mm - SIDE_DETAIL_RIGHT_MARGIN_MM)
            lines = detail_lines(placed)
            assert lines == placed.drawing.details
            assert all(detail_line_width_factor(line, width) == 1.0 for line in lines[:-1])
            assert (detail_line_width_factor(lines[-1], width) < 1.0) == long_note


def test_exported_standard_excel_round_trips_ordered_cuts_and_literal_text(tmp_path):
    profile = BoardFaceProfile.model_validate({"features": [
        {"type": 2, "a": 69, "b": 90, "c": 69, "d": 45, "rotation_deg": 90},
        {"type": 1, "a": 120, "b": 46, "rotation_deg": 270},
    ]})
    part, board, anchor = build_standard_row(
        dict(DEFAULT_ROW, module_id="=M1", source_note="=复核"), board_face_profile=profile,
    )
    path = tmp_path / "project.xlsx"
    export_standard_excel(Project(modules=[part], boards=[board], anchors=[anchor]), path)
    restored, = import_project_xlsx(path).modules
    assert (restored.module_id, restored.source_note) == ("=M1", "=复核")
    assert restored.board_face_outline == profile


def test_complete_project_outputs_four_files_and_rolls_back_on_publish_failure(tmp_path, monkeypatch):
    from refracdraft.exporters import project as exporter

    part = build_standard_module(None, StandardModuleValues("M1", 300, 300, 230))
    project = Project(modules=[part])
    drawing = DrawingGenerator().generate(project)
    base = tmp_path / "项目.v2"
    paths = exporter.project_output_paths(base)

    def dxf(_drawing, path, _reference):
        path.write_bytes(b"DXF")

    def pdf(_drawing, path, *, dxf_path, **kwargs):
        assert dxf_path.read_bytes() == b"DXF"
        path.write_bytes(b"PDF")

    monkeypatch.setattr(exporter, "export_dxf", dxf)
    monkeypatch.setattr(exporter, "export_pdf", pdf)
    exporter.export_complete_project(project, drawing, base, progress=lambda _: None)
    assert set(tmp_path.iterdir()) == set(paths.values())
    for target in paths.values():
        target.write_bytes(b"previous")
    replace = Path.replace

    def locked_pdf(source, target):
        if target == paths["pdf"]:
            raise PermissionError("PDF in use")
        return replace(source, target)

    monkeypatch.setattr(Path, "replace", locked_pdf)
    with pytest.raises(PermissionError, match="PDF in use"):
        exporter.export_complete_project(project, drawing, base, progress=lambda _: None)
    assert all(path.read_bytes() == b"previous" for path in paths.values())


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
    with_filename = export_dxf(replace(document, filename_label="模块加工图"), tmp_path / "board-filename.dxf")
    labels = ezdxf.readfile(with_filename).modelspace().query("TEXT")
    assert [entity.dxf.text for entity in labels] == ["模块加工图", "M1", label]


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


def test_update_fallback_uses_only_the_official_stable_release_redirect(monkeypatch):
    monkeypatch.setattr("refracdraft.release.app_version", lambda: "0.3.0")
    assert portable_release_from_latest_url(f"{RELEASES_URL}/tag/standard-v0.3.0") is None
    version, url = portable_release_from_latest_url(f"{RELEASES_URL}/tag/standard-v0.3.1")
    assert version == "0.3.1"
    assert url == f"{RELEASES_URL}/download/standard-v0.3.1/RefracDraft-Standard-Windows-x64-portable-v0.3.1.zip"
    for invalid in (f"{RELEASES_URL}/latest", f"{RELEASES_URL}/tag/standard-v0.3.1b1",
                    f"{RELEASES_URL.replace('github.com', 'example.com')}/tag/standard-v0.3.1"):
        with pytest.raises(ValueError):
            portable_release_from_latest_url(invalid)


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
    assert detail_texts[0].dxf.width == 0
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


def test_shx_dxf_retains_label_direction_on_first_and_translated_pages(tmp_path):
    module = build_standard_module(None, StandardModuleValues("M1", 350, 300, 230))
    drawing = DrawingGenerator().generate(Project(modules=[module]))
    page, = drawing.pages
    drawing = replace(drawing, pages=(page, replace(page, page_number=2)))
    source = export_dxf(drawing, tmp_path / "dimensions.dxf")
    for page_index in range(2):
        plot = _single_page_dxf(source, page_index, tmp_path / f"plot-{page_index}.dxf", True)
        dims = ezdxf.readfile(plot).modelspace().query("DIMENSION")
        assert {dim.dxf.angle for dim in dims} == {0, 90}
        for dim in dims:
            label, = dim.get_geometry_block().query("MTEXT")
            assert label.get_rotation() == pytest.approx(dim.dxf.angle)
            if dim.dxf.angle == 90:
                assert label.dxf.hasattr("text_direction")


def test_shx_reuses_bounds_and_starts_rendering_before_preparing_all_pages(monkeypatch, tmp_path):
    drawing = DrawingDocument("进度测试", (SheetPage(1, (), 0), SheetPage(2, (), 0, 20)))
    dxf = ezdxf.new()
    for origin in page_model_origins(drawing):
        dxf.modelspace().add_line((0, origin + 10), (100, origin + 10))
    source = tmp_path / "source.dxf"
    dxf.saveas(source)
    font = tmp_path / "sample.shx"
    font.write_bytes(b"test")
    first_started = Event()
    rendered = []
    renderer_jobs = []
    plotted_pages = {}
    for number in (1, 2):
        with pymupdf.open() as pdf:
            pdf.new_page(width=100 + number, height=100)
            plotted_pages[number] = pdf.tobytes()

    from refracdraft.exporters import pdf as exporter

    original_extents = exporter.ezdxf_bbox.extents
    measured = []

    def count_extents(entities):
        measured.extend(entity.dxf.handle for entity in entities)
        return original_extents(entities)

    def run_renderer(command, **_kwargs):
        manifest = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
        output = Path(manifest["output"])
        number = int(output.stem.removeprefix("page-"))
        renderer_jobs.append(number)
        if number == 1:
            first_started.set()
        plot = ezdxf.readfile(manifest["inputs"][0])
        line, = plot.modelspace().query("LINE")
        assert line.dxf.start.y == pytest.approx(10)
        output.write_bytes(plotted_pages[number])
        return SimpleNamespace(returncode=0)

    def progress(message):
        if "第 2/2 页" in message:
            assert first_started.wait(timeout=3)

    monkeypatch.setattr(exporter.ezdxf_bbox, "extents", count_extents)
    monkeypatch.setattr(exporter.subprocess, "run", run_renderer)
    monkeypatch.setattr(exporter, "_fix_shx_page_scale", lambda *_args: None)
    output = _export_pdf_with_shx(
        drawing, tmp_path / "output.pdf", source, tmp_path, (source, source, tmp_path),
        ShxFontInfo(font.name, font, False), None, None, progress, 2,
        lambda done, total: rendered.append((done, total)),
    )
    assert len(measured) == len(set(measured)) == 2
    assert rendered == [(0, 2), (1, 2), (2, 2)]
    with pymupdf.open(output) as pdf:
        assert [page.rect.width for page in pdf] == [101, 102]
    assert sorted(renderer_jobs) == [1, 2]

    rendered.clear()
    renderer_jobs.clear()
    _export_pdf_with_shx(
        drawing, output, source, tmp_path, (source, source, tmp_path),
        ShxFontInfo(font.name, font, False), None, None, lambda _message: None, 2,
        lambda done, total: rendered.append((done, total)), {0: plotted_pages[1]},
    )
    assert renderer_jobs == [2]
    assert rendered == [(1, 2), (2, 2)]
    with pymupdf.open(output) as pdf:
        assert [page.rect.width for page in pdf] == [101, 102]


def test_pdf_prefers_bundled_song_font_to_system_font(monkeypatch):
    bundled_song = next(path for path in PDF_FONT_CANDIDATES if path.name == "SourceHanSerifSC-Regular.otf")
    system_font = Path(r"C:\Windows\Fonts\simsun.ttc")
    monkeypatch.setattr(Path, "is_file", lambda path: path in (bundled_song, system_font))
    assert _find_pdf_font() == bundled_song


def test_pdf_reports_completed_pages_only_after_rendering(monkeypatch, tmp_path):
    events = []
    monkeypatch.setattr("refracdraft.exporters.pdf._load_render_dxf", lambda *_args: None)

    def render(_doc, index, *_args):
        events.append(("render", index))
        return f"page {index + 1}".encode()

    monkeypatch.setattr("refracdraft.exporters.pdf._render_page", render)
    pages = list(_render_fallback_pages(
        tmp_path / "test.dxf", None, None, [(0, 10, 0), (1, 20, -5000)], 1,
        lambda done, total: events.append((done, total)), tmp_path,
    ))
    assert pages == [b"page 1", b"page 2"]
    assert events == [(0, 2), ("render", 0), (1, 2), ("render", 1), (2, 2)]


def test_preview_pdf_cache_renders_only_changed_pages_when_pagination_matches(monkeypatch, tmp_path):
    from refracdraft.exporters import pdf as exporter

    first = build_standard_module(None, StandardModuleValues("A", 300, 300, 230))
    second = build_standard_module(None, StandardModuleValues("B", 4700, 300, 230))
    initial = DrawingGenerator().generate(Project(modules=[first, second]))
    assert [page.scale_denominator for page in initial.pages] == [10, 20]
    cache = PdfPageCache()
    rendered = []
    dxf_writes = []
    font = tmp_path / "preview-font.otf"
    font.write_bytes(b"first version")

    def render(_source_dxf, _font, _font_directory, pages, _workers, report, _scratch):
        report(0, len(pages))
        for count, (index, _scale, _origin) in enumerate(pages, 1):
            rendered.append(index)
            with pymupdf.open() as pdf:
                pdf.new_page(width=100 + index, height=100)
                yield pdf.tobytes()
            report(count, len(pages))

    monkeypatch.setattr(exporter, "_find_pdf_font", lambda *_args: font)
    monkeypatch.setattr(exporter, "_reference_dxf_path", lambda *_args: None)
    monkeypatch.setattr(exporter, "_add_searchable_text_layer", lambda *_args: None)
    monkeypatch.setattr(exporter, "_render_fallback_pages", render)
    monkeypatch.setattr(exporter, "export_dxf", lambda *_args, **kwargs: dxf_writes.append(kwargs["page_indices"]))

    path = tmp_path / "preview.pdf"
    export_pdf(initial, path, page_cache=cache)
    assert rendered == [0, 1]
    assert dxf_writes == [None]

    rendered.clear()
    changed = first.model_copy(update={"source_note": "新备注"})
    revised = DrawingGenerator().generate(Project(modules=[changed, second]))
    export_pdf(revised, path, page_cache=cache)
    assert rendered == [0]
    assert cache.reused_page_count == 1
    with pymupdf.open(path) as pdf:
        assert [page.rect.width for page in pdf] == [100, 101]

    rendered.clear()
    export_pdf(revised, path, page_cache=cache)
    assert rendered == []
    assert dxf_writes == [None, (0,)]
    assert cache.reused_page_count == 2

    font.write_bytes(b"changed")
    export_pdf(revised, path, page_cache=cache)
    assert rendered == [0, 1]
    rendered.clear()

    shuffled = DrawingGenerator().generate(Project(modules=[second, changed]))
    export_pdf(shuffled, path, page_cache=cache)
    assert rendered == [0, 1]
    assert cache.reused_page_count == 0


def test_partial_dxf_writes_only_selected_page_at_original_origin_and_scale(tmp_path):
    first = build_standard_module(None, StandardModuleValues("PAGE1", 300, 300, 230))
    second = build_standard_module(None, StandardModuleValues("PAGE2", 4700, 300, 230))
    drawing = DrawingGenerator().generate(Project(modules=[first, second]))
    reference = ezdxf.new("R2018")
    frame = reference.blocks.new("图框-A4")
    frame.add_line((0, 0), (297, 210))
    path = export_dxf(
        drawing, tmp_path / "partial.dxf", page_indices=(1,), reference_document=reference,
    )
    modelspace = ezdxf.readfile(path).modelspace()
    labels = {entity.dxf.text for entity in modelspace.query("TEXT")}
    assert "第2页 共2页" in labels and "第1页 共2页" not in labels
    assert "PAGE2" in labels and "PAGE1" not in labels
    frame_ref, = modelspace.query('INSERT[name=="图框-A4"]')
    assert frame_ref.dxf.insert.y == page_model_origins(drawing)[1]
    assert frame_ref.dxf.xscale == 20
    assert any(dim.dxf.dimstyle == "_20" and dim.get_measurement() == 4700
               for dim in modelspace.query("DIMENSION"))
    assert len(frame) == 1


def test_shx_pdf_keeps_full_a4_frame_when_renderer_zooms_to_module():
    with pymupdf.open() as doc:
        page = doc.new_page(width=297 * 72 / 25.4, height=210 * 72 / 25.4)
        page.draw_rect(pymupdf.Rect(0, 0, 1, 1))
        stream, = page.get_contents()
        doc.update_stream(stream, (
            b"q\n0.4766134803702599 0 0 0.4766134803702599 215.5269738327779 -367.9554320440735 cm\n"
            b"60 2040 m 2910 2040 l 2910 60 l 60 60 l h S\n"
            b"1687 60 m 1687 370 l 2910 370 l S\nQ\n"
        ))
        assert page.get_drawings()[0]["rect"].x1 > page.rect.x1

        _fix_shx_page_scale(page)

        frame, title = (path["rect"] for path in page.get_drawings())
        points_per_mm = 72 / 25.4
        assert tuple(frame) == pytest.approx(tuple(n * points_per_mm for n in (6, 6, 291, 204)), abs=0.001)
        assert frame.contains(title)


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



def test_versioned_excel_preserves_taper_geometry_across_label_correction(tmp_path):
    module, board, anchor = build_standard_row({
        **DEFAULT_ROW, "taper_enabled": True, "taper_type": "侧敲",
    })
    project = Project(modules=[module], boards=[board], anchors=[anchor])
    path = tmp_path / "tap.xlsx"
    export_standard_excel(project, path)
    assert import_project_xlsx(path).modules[0].geometry_type == GeometryType.SIDE_TAPER

    workbook = load_workbook(path)
    sheet = workbook["标准版"]
    taper_col = [cell.value for cell in sheet[1]].index("类型") + 1
    sheet.cell(2, taper_col).value = "正敲"
    settings = workbook["联动设置"]
    settings.delete_cols(settings.max_column)
    workbook.save(path)
    assert import_project_xlsx(path).modules[0].geometry_type == GeometryType.SIDE_TAPER
