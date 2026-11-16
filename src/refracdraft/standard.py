from __future__ import annotations

from refracdraft.domain.models import Project


def ensure_standard_project(project: Project) -> None:
    """Reject irregular module outlines in the Standard edition."""
    for module in project.modules:
        if (
            module.front_outline is not None
            or module.board_face_outline is not None
            or module.board_face_template_id != "rectangular"
        ):
            raise ValueError(
                f"{module.module_id}: 标准版只支持普通矩形、正敲和侧敲；"
                "不接受异形轮廓或异形夹板面模板"
            )

