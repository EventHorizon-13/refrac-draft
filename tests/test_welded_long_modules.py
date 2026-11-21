from pathlib import Path

import ezdxf
import pytest

from refracdraft.domain.models import BoardFaceFeature, BoardFaceProfile, Project
from refracdraft.drawing.generator import DrawingGenerator
from refracdraft.drawing.layout import page_model_origins
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
    cut = BoardFaceFeature(type=1, a=120, b=65, cut_depth_mm=80)
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

    for depth in (80, 120):
        cut_profile = BoardFaceProfile(features=(cut.model_copy(update={"cut_depth_mm": depth}),))
        body, _, _ = build_standard_row(DEFAULT_ROW, board_face_profile=cut_profile)
        view = DrawingGenerator().build_module(Project(), body).front_view
        projected = {line.points for line in view.internal_lines + view.hidden_lines}
        assert ((120, 0), (120, depth)) in projected
        assert ((0, depth), (120, depth)) in projected
        assert ((120, 0), (120, 300)) not in projected

    invalid = BoardFaceProfile(features=(cut.model_copy(update={"cut_depth_mm": 301}),))
    with pytest.raises(ValueError, match="剪切深度"):
        build_standard_row(DEFAULT_ROW, board_face_profile=invalid)
