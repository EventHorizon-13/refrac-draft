from pathlib import Path

import pytest

from refracdraft.domain.models import (
    AnchorParameters, AnchorType, BoardParameters, GeometryType, LayoutMode,
    ModuleParameters, Project,
)
from refracdraft.drawing.generator import DrawingGenerator
from refracdraft.geometry.primitives import module_front_outline, module_side_outline
from refracdraft.reference.library import ReferenceLibrary
from refracdraft.importers.excel import import_project_xlsx
from openpyxl import Workbook
from refracdraft.exporters.dxf import export_dxf
from refracdraft.exporters.pdf import export_pdf
import ezdxf
import fitz


ROOT = Path(__file__).resolve().parents[1]
REF_DXF = ROOT / "references" / "示例.dxf"


def test_positive_tap_is_front_trapezoid():
    module = ModuleParameters(
        module_id="B2", geometry_type=GeometryType.FRONT_TAPER,
        front_width_mm=300, front_height_mm=289,
        front_left_height_mm=289, front_right_height_mm=220,
        board_face_width_mm=300, board_face_height_mm=230,
    )
    outline = module_front_outline(module)
    assert outline.points == ((0.0, 0.0), (300.0, 34.5), (300.0, 254.5), (0.0, 289.0))
    assert module_side_outline(module) is None


def test_side_tap_has_separate_side_trapezoid():
    module = ModuleParameters(
        module_id="A1", geometry_type=GeometryType.SIDE_TAPER,
        front_width_mm=300, front_height_mm=300,
        side_length_mm=300, side_left_height_mm=300, side_right_height_mm=200,
        board_face_width_mm=300, board_face_height_mm=330,
    )
    assert module_front_outline(module).bounds == (0, 0, 300, 300)
    side = module_side_outline(module)
    assert side is not None
    assert side.bounds == (0, 0, 300, 300)
    assert side.points == ((0.0, 0.0), (300.0, 50.0), (300.0, 250.0), (0.0, 300.0))


def test_reference_library_has_irregular_board_templates():
    if not REF_DXF.exists():
        pytest.skip("reference DXF not mounted")
    library = ReferenceLibrary(REF_DXF)
    catalog = library.board_face_catalog()
    assert len(catalog) == 15
    ids = {item["id"] for item in catalog}
    assert {"side-insert-irregular-1", "irregular-5", "irregular-7"} <= ids


def test_no_board_still_produces_board_face_view():
    module = ModuleParameters(
        module_id="X1", front_width_mm=300, front_height_mm=300,
        board_face_width_mm=300, board_face_height_mm=230,
    )
    project = Project(modules=[module], boards=[BoardParameters(module_id="X1", exists=False)])
    drawing = DrawingGenerator().generate(project)
    assert len(drawing.pages) == 1
    assert drawing.pages[0].modules[0].drawing.board_view.note == "无夹板"


def test_side_taper_generator_creates_three_views():
    module = ModuleParameters(
        module_id="A1", geometry_type=GeometryType.SIDE_TAPER,
        front_width_mm=300, front_height_mm=300,
        side_length_mm=300, side_left_height_mm=300, side_right_height_mm=200,
        board_face_width_mm=300, board_face_height_mm=330,
    )
    project = Project(modules=[module])
    drawing = DrawingGenerator().generate(project).pages[0].modules[0].drawing
    assert drawing.front_view.view_type == "front"
    assert drawing.side_view is not None
    assert drawing.side_view.outline.points[2] == (300, 200)
    assert drawing.board_view.view_type == "board-face"


def test_parameter_groups_are_peer_tables():
    module = ModuleParameters(
        module_id="X1", front_width_mm=300, front_height_mm=300,
        board_face_width_mm=300, board_face_height_mm=230,
    )
    project = Project(
        modules=[module],
        boards=[BoardParameters(module_id="X1", exists=True, material="9厘夹板")],
        anchors=[AnchorParameters(module_id="X1", exists=False, anchor_type=AnchorType.NONE, count=0)],
    )
    assert project.board_for("X1").material == "9厘夹板"
    assert not project.anchor_for("X1").exists


def test_explicit_anchor_count_must_match_positions():
    with pytest.raises(ValueError):
        AnchorParameters(module_id="X1", count=2, layout_mode=LayoutMode.EXPLICIT, positions=[])


def test_excel_import_supports_chinese_headers(tmp_path):
    path = tmp_path / "params.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "模块参数"
    ws.append(["模块编号", "结构类型", "几何类型", "正面宽度", "正面高度", "正面左高", "正面右高", "夹板面宽度", "夹板面高度", "材质", "容重", "数量"])
    ws.append(["B2", "折叠模块", "正敲", 300, 289, 289, 220, 300, 230, "1430材质", 220, 26])
    board = wb.create_sheet("夹板参数")
    board.append(["模块编号", "是否有夹板", "夹板材质", "夹板厚度"])
    board.append(["B2", "有", "9厘夹板", 9])
    anchor = wb.create_sheet("锚固件参数")
    anchor.append(["模块编号", "是否有锚固件", "锚固件类型", "锚固件材质", "螺纹规格", "直径", "锚固件长度", "锚固件数量", "布置方式", "锚固件坐标", "胶管规格"])
    anchor.append(["B2", "有", "M型", "310", "M10", 8, 180, 1, "指定坐标", '[{"x_mm":150,"y_mm":180}]', "32胶管"])
    wb.save(path)
    project = import_project_xlsx(path)
    assert project.modules[0].geometry_type == GeometryType.FRONT_TAPER
    assert project.modules[0].front_right_height_mm == 220
    assert project.boards[0].exists is True
    assert project.anchors[0].positions[0].x_mm == 150


def test_exporters_create_readable_vector_files(tmp_path):
    module = ModuleParameters(
        module_id="B2", geometry_type=GeometryType.FRONT_TAPER,
        front_width_mm=300, front_height_mm=289,
        front_left_height_mm=289, front_right_height_mm=220,
        board_face_width_mm=300, board_face_height_mm=230,
    )
    project = Project(modules=[module])
    drawing = DrawingGenerator().generate(project)
    dxf_path = export_dxf(drawing, tmp_path / "test.dxf", REF_DXF if REF_DXF.exists() else None)
    pdf_path = export_pdf(drawing, tmp_path / "test.pdf", reference_pdf=ROOT / "references" / "江阴铁包-11098-qf.pdf" if (ROOT / "references" / "江阴铁包-11098-qf.pdf").exists() else None)
    parsed_dxf = ezdxf.readfile(dxf_path)
    assert parsed_dxf.header["$INSUNITS"] == 4
    assert len(parsed_dxf.modelspace()) > 10
    parsed_pdf = fitz.open(pdf_path)
    assert len(parsed_pdf) == 1
    assert len(parsed_pdf[0].get_drawings()) > 20


def test_stacked_no_anchor_uses_source_layer_marks():
    module = ModuleParameters(
        module_id="S1", structure_type="层叠模块", geometry_type=GeometryType.NORMAL,
        front_width_mm=300, front_height_mm=300,
        board_face_width_mm=300, board_face_height_mm=150,
    )
    project = Project(modules=[module], anchors=[AnchorParameters(module_id="S1", exists=False, anchor_type=AnchorType.NONE, count=0)])
    drawing = DrawingGenerator(ReferenceLibrary(REF_DXF) if REF_DXF.exists() else None).generate(project).pages[0].modules[0].drawing
    if REF_DXF.exists():
        assert len(drawing.front_view.internal_lines) == 4
    assert drawing.board_view.note == "夹板"


def test_anchor_position_dimension_flags_are_explicit():
    module = ModuleParameters(
        module_id="B3", geometry_type=GeometryType.FRONT_TAPER,
        front_width_mm=300, front_height_mm=289, front_left_height_mm=289, front_right_height_mm=220,
        board_face_width_mm=300, board_face_height_mm=230,
    )
    anchor = AnchorParameters(module_id="B3", anchor_type=AnchorType.QUICK_INSERT, count=1,
                              positions=[{"x_mm":150,"y_mm":180}], dimension_vertical=True)
    drawing = DrawingGenerator(ReferenceLibrary(REF_DXF) if REF_DXF.exists() else None).generate(Project(modules=[module],anchors=[anchor])).pages[0].modules[0].drawing
    labels = [d.label for d in drawing.board_view.dimensions]
    assert "50" in labels
    assert labels.count("150") == 0
    if REF_DXF.exists():
        assert len(drawing.board_view.cutouts) == 5
    assert drawing.board_view.anchor_points == ()
    assert drawing.front_view.anchor_marker_style == "cross"
    front_points = [point for line in drawing.front_view.anchor_symbols for point in line.points]
    width = max(x for x, _ in front_points) - min(x for x, _ in front_points)
    height = max(y for _, y in front_points) - min(y for _, y in front_points)
    assert width == pytest.approx(18.35, abs=0.1)
    assert height == pytest.approx(220.0, abs=0.2)


def test_m_anchor_board_symbol_preserves_reference_colors_without_extra_center_marker():
    if not REF_DXF.exists():
        pytest.skip("reference DXF not mounted")
    module = ModuleParameters(
        module_id="B1", geometry_type=GeometryType.FRONT_TAPER,
        front_width_mm=300, front_height_mm=318,
        front_left_height_mm=318, front_right_height_mm=259,
        board_face_width_mm=300, board_face_height_mm=230,
    )
    anchor = AnchorParameters(
        module_id="B1", anchor_type=AnchorType.M_SHAPE, count=1,
        positions=[{"x_mm": 150, "y_mm": 194.5608498458106}],
    )
    drawing = DrawingGenerator(ReferenceLibrary(REF_DXF)).generate(
        Project(modules=[module], anchors=[anchor])
    ).pages[0].modules[0].drawing
    assert drawing.board_view.anchor_points == ()
    assert drawing.board_view.anchor_symbols
    assert 5 in drawing.board_view.anchor_symbol_colors
    assert 1 in drawing.board_view.anchor_symbol_colors
    assert 13 in drawing.board_view.anchor_symbol_lineweights



def test_pdf_keeps_diameter_and_density_symbols(tmp_path):
    module = ModuleParameters(
        module_id="B1", front_width_mm=300, front_height_mm=300,
        board_face_width_mm=300, board_face_height_mm=230,
        material="1430材质", density_kg_m3=220,
    )
    anchor = AnchorParameters(
        module_id="B1", anchor_type=AnchorType.M_SHAPE, material="310",
        thread_spec="M10", diameter_mm=8, length_mm=200, count=1,
        positions=[{"x_mm": 150, "y_mm": 194.5608498458106}],
    )
    drawing = DrawingGenerator().generate(Project(modules=[module], anchors=[anchor]))
    path = export_pdf(drawing, tmp_path / "symbols.pdf")
    text = fitz.open(path)[0].get_text()
    assert "Ø8" in text
    assert "kg/m³" in text



def test_b1_front_taper_matches_reference_two_sloped_edges():
    module = ModuleParameters(
        module_id="B1", geometry_type=GeometryType.FRONT_TAPER,
        front_width_mm=300, front_height_mm=318,
        front_left_height_mm=318, front_right_height_mm=259,
        board_face_width_mm=300, board_face_height_mm=230,
    )
    assert module_front_outline(module).points == (
        (0.0, 0.0), (300.0, 29.5), (300.0, 288.5), (0.0, 318.0)
    )

