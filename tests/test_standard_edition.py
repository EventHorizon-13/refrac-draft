import pytest
import ezdxf

from refracdraft.drawing.generator import DrawingGenerator, _anchor_positions, _balanced_page_groups, _details
from refracdraft.drawing.layout import PANEL_INNER_MARGIN_MM
from refracdraft.domain.models import (
    AnchorParameters,
    AnchorType,
    BoardParameters,
    GeometryType,
    LayoutMode,
    ModuleParameters,
    Project,
)
from refracdraft.importers.excel import _normalize_row
from refracdraft.reference.library import ReferenceLibrary
from refracdraft.exporters.dxf import export_dxf
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


@pytest.mark.parametrize(
    ("anchor_type", "expected_y"),
    [
        (AnchorType.M_SHAPE, 230 - 35.4391501542),
        (AnchorType.DIAMOND, 160.0),
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
    assert "1350板材" in text
    assert "304M型锚固件M8" in text
    assert "插针φ8" in text
    assert "数量：84 Pcs" in text
    assert "容重：220 kg/m³" in text
    assert "25胶管，12厘夹板" in text
    assert "备注：现场复核" in text


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
    frame_inserts = [entity for entity in exported.modelspace().query("INSERT") if entity.dxf.name == "图框-A4"]
    assert frame_inserts
    assert frame_inserts[0].dxf.xscale == pytest.approx(10.0)
    title_inserts = [entity for entity in exported.modelspace().query("INSERT") if entity.dxf.name == "标题栏"]
    assert title_inserts
    assert title_inserts[0].dxf.xscale == pytest.approx(1.02)
    detail_heights = {
        entity.dxf.height for entity in exported.modelspace().query("TEXT") if entity.dxf.height > 50
    }
    assert len(detail_heights) == 1
    assert next(iter(detail_heights)) == pytest.approx(56.7)
    for style_name in ("工程字", "大字体"):
        style = exported.styles.get(style_name)
        assert style.dxf.font.lower() == "gbenor.shx"
        assert style.dxf.bigfont.lower() == "gbcbig.shx"

