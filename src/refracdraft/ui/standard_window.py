from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMessageBox, QPushButton, QSpinBox, QSplitter, QTreeWidget, QTreeWidgetItem,
    QToolBar, QVBoxLayout, QWidget,
)

from refracdraft.domain.models import Project
from refracdraft.importers.excel import _normalize_row, import_project_xlsx
from refracdraft.standard import ensure_standard_project
from refracdraft.ui.main_window import DrawingPreview, MainWindow


# A selected module exposes all three peer parameter groups in one property editor.
SECTIONS = (
    ("模块", (
        ("基本信息", (
            ("modules", "module_id", "编号"),
            ("modules", "name", "名称"),
            ("modules", "structure_type", "结构类型"),
            ("modules", "geometry_type", "几何类型"),
        )),
        ("正面尺寸", (
            ("modules", "front_width_mm", "宽度 (mm)"),
            ("modules", "front_height_mm", "高度 (mm)"),
            ("modules", "front_left_height_mm", "左端高度 (mm)"),
            ("modules", "front_right_height_mm", "右端高度 (mm)"),
        )),
        ("侧面尺寸", (
            ("modules", "side_length_mm", "长度 (mm)"),
            ("modules", "side_left_height_mm", "左端高度 (mm)"),
            ("modules", "side_right_height_mm", "右端高度 (mm)"),
        )),
        ("夹板面尺寸", (
            ("modules", "board_face_width_mm", "宽度 (mm)"),
            ("modules", "board_face_height_mm", "高度 (mm)"),
        )),
        ("生产信息", (
            ("modules", "material", "材质"),
            ("modules", "density_kg_m3", "容重 (kg/m³)"),
            ("modules", "production_quantity", "生产数量"),
            ("modules", "source_note", "备注"),
        )),
    )),
    ("夹板", (
        ("基本参数", (
            ("boards", "exists", "有无夹板"),
            ("boards", "material", "材质"),
            ("boards", "thickness_mm", "厚度 (mm)"),
        )),
        ("开口加工", (
            ("boards", "opening_mode", "开口模式"),
            ("boards", "custom_opening", "自定义开口坐标 (JSON)"),
            ("boards", "source_note", "备注"),
        )),
    )),
    ("锚固件", (
        ("基本参数", (
            ("anchors", "exists", "有无锚固件"),
            ("anchors", "anchor_type", "类型"),
            ("anchors", "material", "材质"),
            ("anchors", "thread_spec", "螺纹规格"),
            ("anchors", "diameter_mm", "直径 (mm)"),
            ("anchors", "length_mm", "长度 (mm)"),
            ("anchors", "count", "数量"),
        )),
        ("定位", (
            ("anchors", "layout_mode", "布置方式"),
            ("anchors", "positions", "坐标 (JSON)"),
            ("anchors", "edge_offset_mm", "端部留边 (mm)"),
            ("anchors", "spacing_mm", "间距 (mm)"),
        )),
        ("标注与备注", (
            ("anchors", "hose_spec", "胶管规格"),
            ("anchors", "dimension_horizontal", "标注水平定位尺寸"),
            ("anchors", "dimension_vertical", "标注垂直定位尺寸"),
            ("anchors", "source_note", "备注"),
        )),
    )),
)


def _default_record(module_id: str = "M1") -> dict[tuple[str, str], str]:
    return {
        ("modules", "module_id"): module_id,
        ("modules", "name"): "",
        ("modules", "structure_type"): "折叠模块",
        ("modules", "geometry_type"): "普通",
        ("modules", "front_width_mm"): "300",
        ("modules", "front_height_mm"): "300",
        ("modules", "board_face_width_mm"): "300",
        ("modules", "board_face_height_mm"): "230",
        ("modules", "production_quantity"): "1",
        ("boards", "exists"): "是",
        ("boards", "material"): "9厘夹板",
        ("boards", "opening_mode"): "无开口",
        ("anchors", "exists"): "否",
        ("anchors", "anchor_type"): "无",
        ("anchors", "count"): "0",
        ("anchors", "layout_mode"): "均布",
    }


def _module_label(record: dict[tuple[str, str], str]) -> str:
    module_id = record.get(("modules", "module_id"), "").strip() or "未编号"
    geometry = record.get(("modules", "geometry_type"), "").strip()
    return f"{module_id}  ·  {geometry}" if geometry else module_id


class StandardWindow(MainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RefracDraft Standard — 模块加工图生成器")
        self.statusBar().showMessage(
            "标准版：普通矩形 / 正敲 / 侧敲。选择模块后编辑分组参数，点击「生成预览」更新图纸。"
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

        module_panel = QWidget()
        module_layout = QVBoxLayout(module_panel)
        module_layout.addWidget(QLabel("模块"))
        self.module_list = QListWidget()
        self.module_list.currentRowChanged.connect(self._select_module)
        module_layout.addWidget(self.module_list)
        list_actions = QHBoxLayout()
        add = QPushButton("添加")
        remove = QPushButton("删除")
        add.clicked.connect(lambda _checked=False: self._add_module())
        remove.clicked.connect(lambda _checked=False: self._remove_selected_module())
        list_actions.addWidget(add)
        list_actions.addWidget(remove)
        module_layout.addLayout(list_actions)

        parameter_panel = QWidget()
        parameter_layout = QVBoxLayout(parameter_panel)
        parameter_layout.addWidget(QLabel("当前模块参数"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("查找参数")
        self.search.textChanged.connect(self._filter_fields)
        parameter_layout.addWidget(self.search)
        self.properties = QTreeWidget()
        self.properties.setColumnCount(2)
        self.properties.setHeaderLabels(["参数", "值"])
        self.properties.setColumnWidth(0, 190)
        self.properties.setAlternatingRowColors(True)
        self.properties.setToolTip("双击右侧的值进行编辑")
        self.properties.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.properties.itemChanged.connect(self._field_changed)
        self.fields: dict[tuple[str, str], QTreeWidgetItem] = {}
        self.groups: list[QTreeWidgetItem] = []
        self.sections: list[QTreeWidgetItem] = []
        self._make_property_tree()
        parameter_layout.addWidget(self.properties)

        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        page_row = QHBoxLayout()
        page_row.addWidget(QLabel("图纸预览 · 第"))
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.valueChanged.connect(self._show_selected_page)
        page_row.addWidget(self.page_spin)
        page_row.addWidget(QLabel("页"))
        page_row.addStretch(1)
        preview_layout.addLayout(page_row)
        self.preview = DrawingPreview()
        preview_layout.addWidget(self.preview)

        splitter.addWidget(module_panel)
        splitter.addWidget(parameter_panel)
        splitter.addWidget(preview_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([190, 490, 820])
        self.setCentralWidget(splitter)

        self.records: list[dict[tuple[str, str], str]] = []
        self.current_index = -1
        self.tables = {}

    def _make_property_tree(self):
        for group_name, sections in SECTIONS:
            group_item = QTreeWidgetItem(self.properties, [group_name, ""])
            group_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            group_item.setExpanded(True)
            self.groups.append(group_item)
            for section_name, fields in sections:
                section_item = QTreeWidgetItem(group_item, [section_name, ""])
                section_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                section_item.setExpanded(section_name in {
                    "基本信息", "正面尺寸", "夹板面尺寸", "基本参数"
                })
                self.sections.append(section_item)
                for group, field, label in fields:
                    item = QTreeWidgetItem(section_item, [label, ""])
                    item.setFlags(
                        Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                        | Qt.ItemFlag.ItemIsEditable
                    )
                    self.fields[(group, field)] = item

    def _add_empty_rows(self):
        self._add_module(_default_record())

    def _add_module(self, values=None):
        if values is None:
            used = {record.get(("modules", "module_id")) for record in self.records}
            number = 1
            while f"M{number}" in used:
                number += 1
            values = _default_record(f"M{number}")
        self._save_editor()
        row = len(self.records)
        self.records.append(dict(values))
        with QSignalBlocker(self.module_list):
            self.module_list.addItem(_module_label(values))
            self.module_list.setCurrentRow(row)
        self._select_module(row)

    def _remove_selected_module(self):
        row = self.module_list.currentRow()
        if row < 0:
            return
        self._save_editor()
        self.records.pop(row)
        with QSignalBlocker(self.module_list):
            self.module_list.takeItem(row)
            next_row = min(row, len(self.records) - 1)
            self.module_list.setCurrentRow(next_row)
        self.current_index = -1
        self._select_module(next_row)

    def _save_editor(self):
        if 0 <= self.current_index < len(self.records):
            record = self.records[self.current_index]
            for key, item in self.fields.items():
                record[key] = item.text(1).strip()

    def _select_module(self, row):
        self._save_editor()
        self.current_index = row
        record = self.records[row] if 0 <= row < len(self.records) else {}
        with QSignalBlocker(self.properties):
            for key, item in self.fields.items():
                item.setText(1, record.get(key, ""))
        self._update_geometry_sections()

    def _field_changed(self, item, column):
        if column != 1 or self.current_index < 0:
            return
        if item in (self.fields[("modules", "module_id")], self.fields[("modules", "geometry_type")]):
            record = self.records[self.current_index].copy()
            record[("modules", "module_id")] = self.fields[("modules", "module_id")].text(1)
            record[("modules", "geometry_type")] = self.fields[("modules", "geometry_type")].text(1)
            self.module_list.item(self.current_index).setText(_module_label(record))
        if item is self.fields[("modules", "geometry_type")]:
            self._update_geometry_sections()

    def _update_geometry_sections(self):
        geometry = self.fields[("modules", "geometry_type")].text(1).strip()
        for section in self.sections:
            if section.text(0) == "侧面尺寸" and geometry == "侧敲":
                section.setExpanded(True)
            elif section.text(0) == "侧面尺寸" and geometry != "侧敲":
                section.setExpanded(False)

    def _filter_fields(self, query):
        query = query.strip().casefold()
        for section in self.sections:
            any_visible = False
            group_name = section.parent().text(0).casefold()
            section_name = section.text(0).casefold()
            for index in range(section.childCount()):
                item = section.child(index)
                visible = (
                    not query
                    or query in item.text(0).casefold()
                    or query in section_name
                    or query in group_name
                )
                item.setHidden(not visible)
                any_visible |= visible
            section.setHidden(not any_visible)
            if query and any_visible:
                section.setExpanded(True)
        for group in self.groups:
            group.setHidden(all(group.child(index).isHidden() for index in range(group.childCount())))

    def _collect_project(self):
        self._save_editor()
        modules, boards, anchors = [], [], []
        for row_number, record in enumerate(self.records, start=1):
            raw = {"modules": {}, "boards": {}, "anchors": {}}
            for (group, field), value in record.items():
                if value:
                    raw[group][field] = value
            module_id = raw["modules"].get("module_id", "")
            if not module_id:
                raise ValueError(f"第 {row_number} 个模块缺少编号")
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
        self.current_index = -1
        self.records = []
        with QSignalBlocker(self.module_list):
            self.module_list.clear()
            for module in self.project.modules:
                data = {
                    "modules": module.model_dump(mode="json"),
                    "boards": self.project.board_for(module.module_id).model_dump(mode="json"),
                    "anchors": self.project.anchor_for(module.module_id).model_dump(mode="json"),
                }
                record = {}
                for group_name, sections in SECTIONS:
                    for _, fields in sections:
                        for group, field, _ in fields:
                            value = data[group].get(field)
                            if isinstance(value, bool):
                                value = "是" if value else "否"
                            elif isinstance(value, (list, dict)):
                                value = json.dumps(value, ensure_ascii=False)
                            record[(group, field)] = "" if value is None else str(value)
                self.records.append(record)
                self.module_list.addItem(_module_label(record))
            self.module_list.setCurrentRow(0 if self.records else -1)
        self._select_module(0 if self.records else -1)

    def new_project(self):
        self.project = Project()
        self.drawing_document = None
        self.preview.scene().clear()
        self.page_spin.setMaximum(1)
        self.current_index = -1
        self.records = []
        with QSignalBlocker(self.module_list):
            self.module_list.clear()
        self._add_empty_rows()

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

