from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QToolBar, QVBoxLayout, QWidget,
)

from refracdraft.domain.models import Project
from refracdraft.importers.excel import _normalize_row, import_project_xlsx
from refracdraft.standard import ensure_standard_project
from refracdraft.ui.main_window import DrawingPreview, MainWindow


# One row is one module ID. The three prefixes are display groups only; saving
# still constructs the three independent parameter tables in Project.
COLUMNS = (
    ("modules", "module_id", "编号"),
    ("modules", "name", "模块·名称"),
    ("modules", "geometry_type", "模块·几何类型"),
    ("modules", "structure_type", "模块·结构"),
    ("modules", "front_width_mm", "模块·正面宽"),
    ("modules", "front_height_mm", "模块·正面高"),
    ("modules", "front_left_height_mm", "模块·正面左高"),
    ("modules", "front_right_height_mm", "模块·正面右高"),
    ("modules", "side_length_mm", "模块·侧面长度"),
    ("modules", "side_left_height_mm", "模块·侧面左高"),
    ("modules", "side_right_height_mm", "模块·侧面右高"),
    ("modules", "board_face_width_mm", "模块·夹板面宽"),
    ("modules", "board_face_height_mm", "模块·夹板面高"),
    ("modules", "material", "模块·材质"),
    ("modules", "density_kg_m3", "模块·容重"),
    ("modules", "production_quantity", "模块·生产数量"),
    ("modules", "source_note", "模块·备注"),
    ("boards", "exists", "夹板·有无"),
    ("boards", "material", "夹板·材质"),
    ("boards", "thickness_mm", "夹板·厚度"),
    ("boards", "opening_mode", "夹板·开口模式"),
    ("boards", "custom_opening", "夹板·自定义开口JSON"),
    ("boards", "source_note", "夹板·备注"),
    ("anchors", "exists", "锚固件·有无"),
    ("anchors", "anchor_type", "锚固件·类型"),
    ("anchors", "material", "锚固件·材质"),
    ("anchors", "thread_spec", "锚固件·螺纹"),
    ("anchors", "diameter_mm", "锚固件·直径"),
    ("anchors", "length_mm", "锚固件·长度"),
    ("anchors", "count", "锚固件·数量"),
    ("anchors", "layout_mode", "锚固件·布置"),
    ("anchors", "positions", "锚固件·坐标JSON"),
    ("anchors", "edge_offset_mm", "锚固件·端部留边"),
    ("anchors", "spacing_mm", "锚固件·间距"),
    ("anchors", "hose_spec", "锚固件·胶管"),
    ("anchors", "dimension_horizontal", "锚固件·水平定位尺寸"),
    ("anchors", "dimension_vertical", "锚固件·垂直定位尺寸"),
    ("anchors", "source_note", "锚固件·备注"),
)


class StandardWindow(MainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RefracDraft Standard — 模块加工图生成器")
        self.statusBar().showMessage(
            "标准版：普通矩形 / 正敲 / 侧敲。每行关联同一模块的三组参数；修改后点击「生成预览」。"
        )

    def _build_ui(self):
        toolbar = QToolBar("主工具栏")
        self.addToolBar(toolbar)
        for label, callback in (
            ("新建", self.new_project), ("打开 JSON", self.open_json),
            ("导入 Excel", self.import_excel), ("保存 JSON", self.save_json),
            ("生成预览", self.generate), ("导出 DXF", self.export_dxf_file),
            ("导出 PDF", self.export_pdf_file),
        ):
            action = QAction(label, self)
            action.triggered.connect(callback)
            toolbar.addAction(action)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("统一参数表 · 一行一个模块，横向滚动查看夹板与锚固件参数"))
        table = QTableWidget(0, len(COLUMNS))
        table.setHorizontalHeaderLabels([label for _, _, label in COLUMNS])
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 95)
        for col in range(1, len(COLUMNS)):
            table.setColumnWidth(col, 125 if COLUMNS[col][1] not in {"positions", "custom_opening"} else 230)
        self.table = table
        self.tables = {"unified": table}
        left_layout.addWidget(table)
        row_actions = QHBoxLayout()
        add = QPushButton("添加模块")
        remove = QPushButton("删除选中模块")
        add.clicked.connect(lambda _checked=False: self._add_empty_row())
        remove.clicked.connect(lambda _checked=False: self._remove_selected_rows())
        row_actions.addWidget(add)
        row_actions.addWidget(remove)
        left_layout.addLayout(row_actions)

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
        splitter.setSizes([940, 560])
        self.setCentralWidget(splitter)

    def _add_empty_rows(self):
        self._add_empty_row({
            ("modules", "module_id"): "M1",
            ("modules", "geometry_type"): "普通",
            ("modules", "structure_type"): "折叠模块",
            ("modules", "front_width_mm"): "300",
            ("modules", "front_height_mm"): "300",
            ("modules", "board_face_width_mm"): "300",
            ("modules", "board_face_height_mm"): "230",
            ("modules", "production_quantity"): "1",
            ("boards", "exists"): "是",
            ("boards", "material"): "9厘夹板",
            ("anchors", "exists"): "否",
            ("anchors", "anchor_type"): "无",
            ("anchors", "count"): "0",
            ("anchors", "layout_mode"): "均布",
        })

    def _add_empty_row(self, values=None):
        values = values or {}
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, (group, field, _) in enumerate(COLUMNS):
            self.table.setItem(row, col, QTableWidgetItem(str(values.get((group, field), ""))))
        return row

    def _remove_selected_rows(self):
        for row in sorted({item.row() for item in self.table.selectedItems()}, reverse=True):
            self.table.removeRow(row)

    def _collect_project(self):
        modules, boards, anchors = [], [], []
        for row in range(self.table.rowCount()):
            raw = {"modules": {}, "boards": {}, "anchors": {}}
            for col, (group, field, _) in enumerate(COLUMNS):
                item = self.table.item(row, col)
                if item and item.text().strip():
                    raw[group][field] = item.text().strip()
            if not any(raw[group] for group in raw):
                continue
            module_id = raw["modules"].get("module_id", "")
            if not module_id:
                raise ValueError(f"第 {row + 1} 行缺少模块编号")
            raw["modules"]["board_face_template_id"] = "rectangular"
            for group in ("boards", "anchors"):
                raw[group]["module_id"] = module_id
            module = _normalize_row(raw["modules"], "modules")
            board = _normalize_row(raw["boards"], "boards")
            anchor = _normalize_row(raw["anchors"], "anchors")
            if anchor.get("exists") is False:
                anchor["anchor_type"] = "无"
                anchor["count"] = 0
            modules.append(module)
            boards.append(board)
            anchors.append(anchor)
        project = Project(metadata=self.project.metadata, modules=modules, boards=boards, anchors=anchors)
        ensure_standard_project(project)
        return project

    def _populate_tables(self):
        ensure_standard_project(self.project)
        self.table.setRowCount(0)
        for module in self.project.modules:
            data = {
                "modules": module.model_dump(mode="json"),
                "boards": self.project.board_for(module.module_id).model_dump(mode="json"),
                "anchors": self.project.anchor_for(module.module_id).model_dump(mode="json"),
            }
            values = {}
            for group, field, _ in COLUMNS:
                value = data[group].get(field)
                if isinstance(value, bool):
                    value = "是" if value else "否"
                elif isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=False)
                values[(group, field)] = "" if value is None else str(value)
            self._add_empty_row(values)

    def open_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开项目", "", "RefracDraft 项目 (*.json)")
        if not path:
            return
        try:
            candidate = Project.model_validate_json(Path(path).read_text(encoding="utf-8"))
            ensure_standard_project(candidate)
            self.project = candidate
            self._populate_tables()
        except Exception as exc:
            QMessageBox.critical(self, "打开失败", str(exc))

    def import_excel(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入 Excel", "", "Excel 工作簿 (*.xlsx *.xlsm)")
        if not path:
            return
        try:
            candidate = import_project_xlsx(path)
            ensure_standard_project(candidate)
            self.project = candidate
            self._populate_tables()
            self.statusBar().showMessage(f"已导入：{path}")
        except Exception as exc:
            QMessageBox.critical(self, "导入失败", str(exc))

