from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction, QColor, QBrush, QPen, QPainter, QPalette
from PySide6.QtWidgets import (
    QFileDialog, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QSpinBox, QSplitter, QTabWidget, QTableWidget,
    QTableWidgetItem, QToolBar, QVBoxLayout, QWidget,
)

from refracdraft.domain.models import Project
from refracdraft.drawing.generator import DrawingGenerator
from refracdraft.drawing.layout import (
    BOARD_VIEW_BOTTOM_MM,
    SIDE_VIEW_GAP_MM,
    TOP_VIEW_BOTTOM_MM,
    VIEW_SCALE,
    detail_baseline,
    outline_width,
)
from refracdraft.exporters.dxf import export_dxf
from refracdraft.exporters.pdf import export_pdf
from refracdraft.importers.excel import import_project_xlsx
from refracdraft.reference.library import ReferenceLibrary
from refracdraft.resources import resource_path


MODULE_COLUMNS = [
    "module_id", "name", "structure_type", "geometry_type", "front_width_mm", "front_height_mm", "expansion_length_mm",
    "front_left_height_mm", "front_right_height_mm", "side_length_mm", "side_left_height_mm",
    "side_right_height_mm", "board_face_width_mm", "board_face_height_mm", "board_face_template_id",
    "material", "density_kg_m3", "production_quantity", "source_note",
]
BOARD_COLUMNS = ["module_id", "exists", "material", "thickness_mm", "opening_mode", "custom_opening", "source_note"]
ANCHOR_COLUMNS = [
    "module_id", "exists", "anchor_type", "material", "thread_spec", "diameter_mm", "length_mm",
    "embedment_depth_mm", "count", "layout_mode", "positions", "edge_offset_mm", "spacing_mm", "hose_spec",
    "dimension_horizontal", "dimension_vertical", "source_note",
]
MODULE_LABELS = ["模块编号", "模块名称", "结构类型", "几何类型", "正面宽度(mm)", "正面高度(mm)", "膨胀长度(mm)",
                 "正面左高(mm)", "正面右高(mm)", "侧面长度(mm)", "侧面左高(mm)", "侧面右高(mm)",
                 "夹板面宽(mm)", "夹板面高(mm)", "夹板面类型", "模块材质", "容重(kg/m³)", "生产数量", "备注"]
BOARD_LABELS = ["模块编号", "有无夹板", "夹板材质", "夹板厚度(mm)", "开口模式", "自定义开口坐标(JSON)", "备注"]
ANCHOR_LABELS = ["模块编号", "有无锚固件", "锚固件类型", "锚固件材质", "螺纹规格", "直径(mm)",
                 "长度(mm)", "嵌入深度(mm)", "数量", "布置方式", "坐标(JSON)", "端部留边(mm)", "间距(mm)", "胶管规格",
                 "标注水平定位尺寸", "标注垂直定位尺寸", "备注"]


class DrawingPreview(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._apply_theme_background()

    def _apply_theme_background(self) -> None:
        self.setBackgroundBrush(self.palette().brush(QPalette.ColorRole.Window))

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.PaletteChange:
            self._apply_theme_background()
        super().changeEvent(event)

    def show_page(self, document, page_index: int = 0):
        scene = self.scene()
        scene.clear()
        if not document.pages:
            return
        page = document.pages[max(0, min(page_index, len(document.pages) - 1))]
        scene.setSceneRect(0, 0, 297, 210)
        scene.addRect(0, 0, 297, 210, QPen(Qt.PenStyle.NoPen), QBrush(QColor("#ffffff")))
        scene.addRect(7, 7, 283, 196, QPen(QColor("#111111"), 0.25), QBrush(Qt.BrushStyle.NoBrush))
        for placed in page.modules[1:]:
            scene.addLine(placed.x_mm, 7, placed.x_mm, 173, QPen(QColor("#222222"), 0.2))
        scene.addRect(168.5, 172, 121.5, 31, QPen(QColor("#111111"), 0.2), QBrush(Qt.BrushStyle.NoBrush))
        for placed in page.modules:
            drawing, px = placed.drawing, placed.content_x_mm
            if drawing.side_view:
                fw = outline_width(drawing.front_view)
                self._draw_view(scene, drawing.front_view, (px, TOP_VIEW_BOTTOM_MM), drawing.module_id, VIEW_SCALE)
                self._draw_view(
                    scene,
                    drawing.side_view,
                    (px + fw + SIDE_VIEW_GAP_MM, TOP_VIEW_BOTTOM_MM),
                    drawing.module_id,
                    VIEW_SCALE,
                )
            else:
                self._draw_view(scene, drawing.front_view, (px, TOP_VIEW_BOTTOM_MM), drawing.module_id, VIEW_SCALE)
            self._draw_view(
                scene,
                drawing.board_view,
                (px, BOARD_VIEW_BOTTOM_MM),
                drawing.module_id,
                VIEW_SCALE,
            )
            for i, line in enumerate(drawing.details):
                self._add_text(scene, line, px, detail_baseline(i), 3.0, "#111111")
        self.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _add_text(self, scene, text, x, y, size, color):
        item = scene.addText(text)
        item.setDefaultTextColor(QColor(color))
        item.setScale(size / 10.0)
        item.setPos(x, 210 - y - size)

    def _draw_view(self, scene, view, origin, module_id, scale):
        ox, oy = origin
        pts = [(ox + x * scale, 210 - (oy + y * scale)) for x, y in view.outline.points]
        if len(pts) >= 2:
            for a, b in zip(pts, pts[1:] + ([pts[0]] if view.outline.closed else [])):
                scene.addLine(a[0], a[1], b[0], b[1], QPen(QColor("#111111"), 0.25))
        for dim in view.dimensions:
            x1, y1 = ox + dim.start[0] * scale, oy + dim.start[1] * scale
            x2, y2 = ox + dim.end[0] * scale, oy + dim.end[1] * scale
            if dim.orientation == "horizontal":
                y = max(y1, y2) + dim.offset * scale
                self._dim_line(scene, x1, y, x2, y, dim.label, True)
            else:
                x = x1 - dim.offset * scale
                self._dim_line(scene, x, y1, x, y2, dim.label, False)
        for cutout in view.cutouts:
            p = [(ox + x * scale, 210 - (oy + y * scale)) for x, y in cutout.points]
            for a, b in zip(p, p[1:] + ([p[0]] if cutout.closed else [])):
                scene.addLine(a[0], a[1], b[0], b[1], QPen(QColor("#111111"), 0.25))
        for line in view.internal_lines:
            p = [(ox + x * scale, 210 - (oy + y * scale)) for x, y in line.points]
            for a, b in zip(p, p[1:]):
                scene.addLine(a[0], a[1], b[0], b[1], QPen(QColor("#111111"), 0.22))
        aci_colors = {1: "#ff0000", 2: "#ffff00", 3: "#00ff00", 4: "#00ffff", 5: "#0000ff",
                      6: "#ff00ff", 7: "#111111", 8: "#808080", 9: "#c0c0c0"}
        for symbol_index, symbol in enumerate(view.anchor_symbols):
            p = [(ox + x * scale, 210 - (oy + y * scale)) for x, y in symbol.points]
            aci = view.anchor_symbol_colors[symbol_index] if symbol_index < len(view.anchor_symbol_colors) else 5
            lineweight = view.anchor_symbol_lineweights[symbol_index] if symbol_index < len(view.anchor_symbol_lineweights) else 22
            linetype = view.anchor_symbol_linetypes[symbol_index] if symbol_index < len(view.anchor_symbol_linetypes) else "CONTINUOUS"
            pen = QPen(QColor(aci_colors.get(aci, "#111111")), lineweight / 100.0)
            if any(token in linetype.upper() for token in ("CENTER", "DASH", "HIDDEN")):
                pen.setDashPattern([16.0, 3.0, 3.0, 3.0])
            for a, b in zip(p, p[1:] + ([p[0]] if symbol.closed else [])):
                scene.addLine(a[0], a[1], b[0], b[1], pen)
        for x, y in view.anchor_points:
            cx, cy = ox + x * scale, 210 - (oy + y * scale)
            if view.anchor_marker_style == "target":
                scene.addEllipse(cx - 0.6, cy - 0.6, 1.2, 1.2, QPen(QColor("#ff0000")), QBrush(QColor("#ffff00")))
                scene.addLine(cx - 1.5, cy, cx + 1.5, cy, QPen(QColor("#ff0000"), 0.18))
            else:
                scene.addLine(cx - 1.5, cy, cx + 1.5, cy, QPen(QColor("#ff0000"), 0.25))
                scene.addLine(cx, cy - 1.5, cx, cy + 1.5, QPen(QColor("#ff0000"), 0.25))
        min_x, min_y, max_x, max_y = view.outline.bounds
        label = view.note or module_id
        label_y = (max_y - min_y) / 2
        if view.view_type != "board-face" and (view.anchor_symbols or view.anchor_points):
            label_y = (view.outline.points[0][1] + view.outline.points[1][1]) / 2 + 5.0
        self._add_text(scene, label, ox + (max_x - min_x) * scale / 2 - 3, oy + label_y, 4, "#111111")

    def _dim_line(self, scene, x1, y1, x2, y2, label, horizontal):
        pen = QPen(QColor("#00ffff"), 0.25)
        scene.addLine(x1, 210 - y1, x2, 210 - y2, pen)

        def arrow(x, y, ux, uy):
            length, half_width = 1.6, 0.25
            bx, by = x - ux * length, y - uy * length
            px, py = -uy * half_width, ux * half_width
            tip = (x, 210 - y)
            left = (bx + px, 210 - (by + py))
            right = (bx - px, 210 - (by - py))
            scene.addLine(tip[0], tip[1], left[0], left[1], pen)
            scene.addLine(tip[0], tip[1], right[0], right[1], pen)

        if horizontal:
            direction = 1.0 if x2 >= x1 else -1.0
            arrow(x1, y1, -direction, 0)
            arrow(x2, y2, direction, 0)
            self._add_text(scene, label, (x1 + x2) / 2 - 2, y1 + 1.5, 2.5, "#00ff00")
        else:
            direction = 1.0 if y2 >= y1 else -1.0
            arrow(x1, y1, 0, -direction)
            arrow(x2, y2, 0, direction)
            self._add_text(scene, label, x1 - 2, (y1 + y2) / 2, 2.5, "#00ff00")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RefracDraft — 模块加工图生成器")
        self.resize(1500, 900)
        self.project = Project()
        self.drawing_document = None
        self.reference_dxf = resource_path("references/示例.dxf")
        self.reference_pdf = resource_path("references/江阴铁包-11098-qf.pdf")
        self.tables: dict[str, QTableWidget] = {}
        self._build_ui()
        self._add_empty_rows()

    def _build_ui(self):
        toolbar = QToolBar("主工具栏")
        self.addToolBar(toolbar)
        actions = [
            ("新建", self.new_project), ("打开 JSON", self.open_json), ("导入 Excel", self.import_excel),
            ("保存 JSON", self.save_json), ("生成预览", self.generate),
            ("导出 DXF", self.export_dxf_file), ("导出 PDF", self.export_pdf_file),
        ]
        for label, callback in actions:
            action = QAction(label, self)
            action.triggered.connect(callback)
            toolbar.addAction(action)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.tabs = QTabWidget()
        for key, title, columns, labels in (
            ("modules", "模块参数", MODULE_COLUMNS, MODULE_LABELS),
            ("boards", "夹板参数", BOARD_COLUMNS, BOARD_LABELS),
            ("anchors", "锚固件参数", ANCHOR_COLUMNS, ANCHOR_LABELS),
        ):
            table = QTableWidget(0, len(columns))
            table.setHorizontalHeaderLabels(labels)
            table.horizontalHeader().setStretchLastSection(True)
            table.setAlternatingRowColors(True)
            self.tables[key] = table
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.addWidget(table)
            row_actions = QHBoxLayout()
            add = QPushButton("添加行")
            remove = QPushButton("删除选中行")
            add.clicked.connect(lambda _=False, t=table, k=key: self._add_row(t, k))
            remove.clicked.connect(lambda _=False, t=table: self._remove_row(t))
            row_actions.addWidget(add)
            row_actions.addWidget(remove)
            tab_layout.addLayout(row_actions)
            self.tabs.addTab(tab, title)
        left_layout.addWidget(self.tabs)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        page_row = QHBoxLayout()
        page_row.addWidget(QLabel("预览页"))
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.valueChanged.connect(self._show_selected_page)
        page_row.addWidget(self.page_spin)
        page_row.addStretch(1)
        right_layout.addLayout(page_row)
        self.preview = DrawingPreview()
        right_layout.addWidget(self.preview)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([760, 740])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("参数修改后点击「生成预览」更新图纸；不会自动实时重绘。")

    def _add_empty_rows(self):
        self._add_row(self.tables["modules"], "modules", {
            "module_id": "M1", "geometry_type": "普通", "front_width_mm": "300", "front_height_mm": "300",
            "board_face_width_mm": "300", "board_face_height_mm": "230", "board_face_template_id": "rectangular",
            "production_quantity": "1",
        })
        self._add_row(self.tables["boards"], "boards", {"module_id": "M1", "exists": "是", "material": "9厘夹板"})
        self._add_row(self.tables["anchors"], "anchors", {
            "module_id": "M1", "exists": "否", "anchor_type": "无", "count": "0", "layout_mode": "均布",
        })

    def _add_row(self, table, key, values=None):
        values = values or {}
        columns = MODULE_COLUMNS if key == "modules" else BOARD_COLUMNS if key == "boards" else ANCHOR_COLUMNS
        row = table.rowCount()
        table.insertRow(row)
        for col, name in enumerate(columns):
            item = QTableWidgetItem(str(values.get(name, "")))
            table.setItem(row, col, item)

    def _remove_row(self, table):
        rows = sorted({item.row() for item in table.selectedItems()}, reverse=True)
        for row in rows:
            table.removeRow(row)

    def _table_rows(self, key):
        table = self.tables[key]
        columns = MODULE_COLUMNS if key == "modules" else BOARD_COLUMNS if key == "boards" else ANCHOR_COLUMNS
        result = []
        for row in range(table.rowCount()):
            values = {}
            for col, name in enumerate(columns):
                item = table.item(row, col)
                if item and item.text().strip():
                    values[name] = item.text().strip()
            if values:
                result.append(values)
        return result

    def _collect_project(self):
        from refracdraft.importers.excel import _normalize_row
        modules = [_normalize_row(row, "modules") for row in self._table_rows("modules")]
        boards = [_normalize_row(row, "boards") for row in self._table_rows("boards")]
        anchors = [_normalize_row(row, "anchors") for row in self._table_rows("anchors")]
        for row in anchors:
            if row.get("positions") and isinstance(row["positions"], str):
                row["positions"] = json.loads(row["positions"])
            if row.get("exists") is False:
                row["anchor_type"] = "无"
                row["count"] = 0
        return Project(metadata=self.project.metadata, modules=modules, boards=boards, anchors=anchors)

    def new_project(self):
        self.project = Project()
        for table in self.tables.values():
            table.setRowCount(0)
        self._add_empty_rows()
        self.drawing_document = None
        self.preview.scene().clear()

    def open_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开项目", "", "RefracDraft 项目 (*.json)")
        if not path:
            return
        try:
            self.project = Project.model_validate_json(Path(path).read_text(encoding="utf-8"))
            self._populate_tables()
        except Exception as exc:
            QMessageBox.critical(self, "打开失败", str(exc))

    def import_excel(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入 Excel", "", "Excel 工作簿 (*.xlsx *.xlsm)")
        if not path:
            return
        try:
            self.project = import_project_xlsx(path)
            self._populate_tables()
            self.statusBar().showMessage(f"已导入：{path}")
        except Exception as exc:
            QMessageBox.critical(self, "导入失败", str(exc))

    def _populate_tables(self):
        for key, group in (("modules", self.project.modules), ("boards", self.project.boards), ("anchors", self.project.anchors)):
            table = self.tables[key]
            table.setRowCount(0)
            columns = MODULE_COLUMNS if key == "modules" else BOARD_COLUMNS if key == "boards" else ANCHOR_COLUMNS
            for model in group:
                values = model.model_dump(mode="json")
                self._add_row(table, key, {k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v for k, v in values.items()})

    def save_json(self):
        try:
            self.project = self._collect_project()
            path, _ = QFileDialog.getSaveFileName(self, "保存项目", "project.json", "RefracDraft 项目 (*.json)")
            if path:
                Path(path).write_text(self.project.model_dump_json(indent=2), encoding="utf-8")
                self.statusBar().showMessage(f"项目已保存：{path}")
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))

    def generate(self):
        try:
            self.project = self._collect_project()
            library = ReferenceLibrary(self.reference_dxf) if self.reference_dxf.exists() else None
            self.drawing_document = DrawingGenerator(library).generate(self.project)
            self.page_spin.setMaximum(max(1, len(self.drawing_document.pages)))
            self.page_spin.setValue(1)
            self.preview.show_page(self.drawing_document, 0)
            warnings = "\n".join(self.drawing_document.warnings)
            self.statusBar().showMessage("图纸已生成" + (f"；警告：{warnings}" if warnings else ""))
        except Exception as exc:
            QMessageBox.critical(self, "生成失败", str(exc))

    def _show_selected_page(self, value):
        if self.drawing_document:
            self.preview.show_page(self.drawing_document, value - 1)

    def export_dxf_file(self):
        if not self.drawing_document:
            self.generate()
        if not self.drawing_document:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出 DXF", "module-drawing.dxf", "DXF 文件 (*.dxf)")
        if not path:
            return
        try:
            export_dxf(self.drawing_document, path, self.reference_dxf)
            self.statusBar().showMessage(f"DXF 已导出：{path}")
        except Exception as exc:
            QMessageBox.critical(self, "DXF 导出失败", str(exc))

    def export_pdf_file(self):
        if not self.drawing_document:
            self.generate()
        if not self.drawing_document:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出 PDF", "module-drawing.pdf", "PDF 文件 (*.pdf)")
        if not path:
            return
        try:
            export_pdf(
                self.drawing_document,
                path,
                reference_pdf=self.reference_pdf,
                reference_dxf=self.reference_dxf,
            )
            self.statusBar().showMessage(f"PDF 已导出：{path}")
        except Exception as exc:
            QMessageBox.critical(self, "PDF 导出失败", str(exc))

