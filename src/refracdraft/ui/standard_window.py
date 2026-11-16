from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QDoubleValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from refracdraft.domain.models import (
    AnchorParameters,
    AnchorType,
    BoardParameters,
    GeometryType,
    ModuleParameters,
    Project,
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
from refracdraft.ui.main_window import DrawingPreview, MainWindow


LENGTH_PRESETS = ("200", "250", "300", "350", "400", "450", "500", "600")
EXPANSION_PRESETS = (
    "150", "180", "200", "230", "250", "280", "300", "350", "400", "450", "500"
)
THICKNESS_PRESETS = (
    "50", "75", "100", "125", "150", "180", "200", "230", "250", "300", "330",
    "350", "400", "500",
)
HEAD_PRESETS = (
    "150", "180", "200", "220", "230", "250", "280", "289", "300", "330", "350",
    "400", "450", "500",
)
POSITION_PRESETS = (
    "25", "30", "40", "50", "60", "75", "100", "125", "150", "200", "250", "300"
)
SPACING_PRESETS = (
    "50", "75", "100", "120", "150", "180", "200", "230", "250", "300", "350",
    "400", "500",
)
EMBEDMENT_PRESETS = ("25", "30", "40", "50", "60", "70", "80", "100", "120")

ANCHOR_TYPES = (
    ("M型", AnchorType.M_SHAPE),
    ("菱形", AnchorType.DIAMOND),
    ("旁插", AnchorType.SIDE_INSERT),
    ("快插", AnchorType.QUICK_INSERT),
    ("焊接菱形", AnchorType.WELDED_DIAMOND),
    ("自定义", AnchorType.CUSTOM),
)


def _number_combo(values: tuple[str, ...], default: str, width: int = 82) -> QComboBox:
    combo = QComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    combo.addItems(values)
    combo.setCurrentText(default)
    combo.setFixedWidth(width)
    validator = QDoubleValidator(0.0, 1_000_000.0, 2, combo)
    validator.setNotation(QDoubleValidator.Notation.StandardNotation)
    combo.lineEdit().setValidator(validator)
    return combo


def _field(label: str, widget: QWidget, width: int | None = None) -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    caption = QLabel(label)
    caption.setProperty("role", "fieldLabel")
    layout.addWidget(caption)
    layout.addWidget(widget)
    if width is not None:
        container.setFixedWidth(width)
    return container


def _toggle_field(widget: QWidget) -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    spacer = QLabel(" ")
    spacer.setProperty("role", "fieldLabel")
    layout.addWidget(spacer)
    layout.addWidget(widget, alignment=Qt.AlignmentFlag.AlignLeft)
    return container


def _separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    return line


def _number(value: str, label: str, module_id: str) -> float:
    try:
        parsed = float(value.strip().replace(",", ""))
    except (TypeError, ValueError):
        raise ValueError(f"{module_id or '未编号模块'}: {label}必须是数字") from None
    if parsed <= 0:
        raise ValueError(f"{module_id or '未编号模块'}: {label}必须大于 0")
    return parsed


class ModuleRowWidget(QFrame):
    changed = Signal()
    activated = Signal(object)

    def __init__(
        self,
        module: ModuleParameters | None = None,
        board: BoardParameters | None = None,
        anchor: AnchorParameters | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("moduleRow")
        self.setProperty("active", False)
        self.base_module = module
        self.base_board = board
        self.base_anchor = anchor
        self._build_ui()
        self._load_values(module, board, anchor)
        self._connect_signals()
        self._update_visibility()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(7)

        self.module_id_edit = QLineEdit()
        self.module_id_edit.setFixedWidth(78)
        self.module_id_edit.setMaxLength(24)
        self.length_combo = _number_combo(LENGTH_PRESETS, "300")
        self.expansion_combo = _number_combo(EXPANSION_PRESETS, "300")
        self.thickness_combo = _number_combo(THICKNESS_PRESETS, "230")
        self.taper_check = QCheckBox("大小头")
        self.big_combo = _number_combo(HEAD_PRESETS, "289")
        self.small_combo = _number_combo(HEAD_PRESETS, "220")
        self.taper_type_combo = QComboBox()
        self.taper_type_combo.addItem("正敲", GeometryType.FRONT_TAPER)
        self.taper_type_combo.addItem("侧敲", GeometryType.SIDE_TAPER)
        self.taper_type_combo.setFixedWidth(88)
        self.board_check = QCheckBox("夹板")
        self.board_check.setChecked(True)
        self.anchor_check = QCheckBox("锚固件")
        self.position_combo = _number_combo(POSITION_PRESETS, "50")
        self.spacing_combo = _number_combo(SPACING_PRESETS, "300")
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 99)
        self.count_spin.setValue(1)
        self.count_spin.setFixedWidth(60)
        self.anchor_type_combo = QComboBox()
        for label, anchor_type in ANCHOR_TYPES:
            self.anchor_type_combo.addItem(label, anchor_type)
        self.anchor_type_combo.setFixedWidth(92)
        self.embedment_combo = _number_combo(EMBEDMENT_PRESETS, "50")

        layout.addWidget(_field("编号", self.module_id_edit))
        layout.addWidget(_field("长度 (mm)", self.length_combo))
        layout.addWidget(_field("膨胀长度 (mm)", self.expansion_combo, 92))
        layout.addWidget(_field("厚度 (mm)", self.thickness_combo))
        layout.addWidget(_separator())
        layout.addWidget(_toggle_field(self.taper_check))

        self.taper_fields = QWidget()
        taper_layout = QHBoxLayout(self.taper_fields)
        taper_layout.setContentsMargins(0, 0, 0, 0)
        taper_layout.setSpacing(7)
        taper_layout.addWidget(_field("大头 (mm)", self.big_combo))
        taper_layout.addWidget(_field("小头 (mm)", self.small_combo))
        taper_layout.addWidget(_field("大小头类型", self.taper_type_combo, 100))
        layout.addWidget(self.taper_fields)

        layout.addWidget(_toggle_field(self.board_check))
        layout.addWidget(_separator())
        layout.addWidget(_toggle_field(self.anchor_check))

        self.anchor_fields = QWidget()
        anchor_layout = QHBoxLayout(self.anchor_fields)
        anchor_layout.setContentsMargins(0, 0, 0, 0)
        anchor_layout.setSpacing(7)
        anchor_layout.addWidget(_field("位置 (mm)", self.position_combo))
        anchor_layout.addWidget(_field("间距 (mm)", self.spacing_combo))
        anchor_layout.addWidget(_field("数量", self.count_spin))
        anchor_layout.addWidget(_field("锚固件类型", self.anchor_type_combo, 100))
        self.embedment_field = _field("嵌入深度 (mm)", self.embedment_combo, 100)
        anchor_layout.addWidget(self.embedment_field)
        layout.addWidget(self.anchor_fields)
        layout.addStretch(1)

    def _load_values(
        self,
        module: ModuleParameters | None,
        board: BoardParameters | None,
        anchor: AnchorParameters | None,
    ) -> None:
        if module is None:
            module_values = StandardModuleValues("M1", 300.0, 300.0, 230.0)
        else:
            module_values = standard_module_values(
                module,
                board or BoardParameters(module_id=module.module_id, exists=True),
            )
        anchor_values = (
            standard_anchor_values(anchor) if anchor is not None else StandardAnchorValues()
        )

        self.module_id_edit.setText(module_values.module_id)
        self.length_combo.setCurrentText(f"{module_values.length_mm:g}")
        self.expansion_combo.setCurrentText(f"{module_values.expansion_length_mm:g}")
        self.thickness_combo.setCurrentText(f"{module_values.thickness_mm:g}")
        self.taper_check.setChecked(module_values.taper_enabled)
        if module_values.big_head_mm is not None:
            self.big_combo.setCurrentText(f"{module_values.big_head_mm:g}")
        if module_values.small_head_mm is not None:
            self.small_combo.setCurrentText(f"{module_values.small_head_mm:g}")
        taper_index = self.taper_type_combo.findData(module_values.taper_type)
        self.taper_type_combo.setCurrentIndex(max(0, taper_index))
        self.board_check.setChecked(module_values.board_exists)
        self.anchor_check.setChecked(anchor_values.enabled)
        self.position_combo.setCurrentText(f"{anchor_values.position_mm:g}")
        self.spacing_combo.setCurrentText(f"{anchor_values.spacing_mm:g}")
        self.count_spin.setValue(max(1, anchor_values.count))
        anchor_index = self.anchor_type_combo.findData(anchor_values.anchor_type)
        self.anchor_type_combo.setCurrentIndex(max(0, anchor_index))
        if anchor_values.embedment_depth_mm is not None:
            self.embedment_combo.setCurrentText(f"{anchor_values.embedment_depth_mm:g}")

    def _connect_signals(self) -> None:
        self.module_id_edit.textEdited.connect(self._emit_changed)
        for combo in (
            self.length_combo,
            self.expansion_combo,
            self.thickness_combo,
            self.big_combo,
            self.small_combo,
            self.position_combo,
            self.spacing_combo,
            self.embedment_combo,
        ):
            combo.currentTextChanged.connect(self._emit_changed)
        self.taper_check.toggled.connect(self._taper_changed)
        self.anchor_check.toggled.connect(self._anchor_changed)
        self.taper_type_combo.currentIndexChanged.connect(self._emit_changed)
        self.anchor_type_combo.currentIndexChanged.connect(self._anchor_type_changed)
        self.board_check.toggled.connect(self._emit_changed)
        self.count_spin.valueChanged.connect(self._emit_changed)

    def _emit_changed(self, *_args) -> None:
        self.activated.emit(self)
        self.changed.emit()

    def _taper_changed(self, _checked: bool) -> None:
        self._update_visibility()
        self._emit_changed()

    def _anchor_changed(self, _checked: bool) -> None:
        self._update_visibility()
        self._emit_changed()

    def _anchor_type_changed(self, _index: int) -> None:
        self._update_visibility()
        self._emit_changed()

    def _update_visibility(self) -> None:
        self.taper_fields.setVisible(self.taper_check.isChecked())
        anchor_visible = self.anchor_check.isChecked()
        self.anchor_fields.setVisible(anchor_visible)
        is_diamond = self.anchor_type_combo.currentData() == AnchorType.DIAMOND
        self.embedment_field.setVisible(anchor_visible and is_diamond)

    def set_active(self, active: bool) -> None:
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mousePressEvent(self, event) -> None:
        self.activated.emit(self)
        super().mousePressEvent(event)

    def module_values(self) -> StandardModuleValues:
        module_id = self.module_id_edit.text().strip()
        if not module_id:
            raise ValueError("模块编号不能为空")
        return StandardModuleValues(
            module_id=module_id,
            length_mm=_number(self.length_combo.currentText(), "长度", module_id),
            expansion_length_mm=_number(self.expansion_combo.currentText(), "膨胀长度", module_id),
            thickness_mm=_number(self.thickness_combo.currentText(), "厚度", module_id),
            taper_enabled=self.taper_check.isChecked(),
            big_head_mm=(
                _number(self.big_combo.currentText(), "大头", module_id)
                if self.taper_check.isChecked()
                else None
            ),
            small_head_mm=(
                _number(self.small_combo.currentText(), "小头", module_id)
                if self.taper_check.isChecked()
                else None
            ),
            taper_type=self.taper_type_combo.currentData(),
            board_exists=self.board_check.isChecked(),
        )

    def anchor_values(self) -> StandardAnchorValues:
        if not self.anchor_check.isChecked():
            return StandardAnchorValues(enabled=False)
        module_id = self.module_id_edit.text().strip() or "未编号模块"
        anchor_type = self.anchor_type_combo.currentData()
        embedment = None
        if anchor_type == AnchorType.DIAMOND:
            embedment = _number(self.embedment_combo.currentText(), "嵌入深度", module_id)
        return StandardAnchorValues(
            enabled=True,
            position_mm=_number(self.position_combo.currentText(), "锚固件位置", module_id),
            spacing_mm=_number(self.spacing_combo.currentText(), "锚固件间距", module_id),
            count=self.count_spin.value(),
            anchor_type=anchor_type,
            embedment_depth_mm=embedment,
        )

    def collect(self) -> tuple[ModuleParameters, BoardParameters, AnchorParameters]:
        module_values = self.module_values()
        module = build_standard_module(self.base_module, module_values)
        board = build_standard_board(self.base_board, module.module_id, module_values.board_exists)
        anchor = build_standard_anchor(
            self.base_anchor,
            module.module_id,
            module_values.length_mm,
            self.anchor_values(),
        )
        return module, board, anchor


class StandardWindow(MainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RefracDraft Standard — 模块加工图生成器")
        self.statusBar().showMessage("标准版：一行一个模块，修改后点击「生成预览」。")

    def _build_ui(self) -> None:
        toolbar = QToolBar("主工具栏")
        self.addToolBar(toolbar)
        for label, callback in (
            ("新建", self.new_project),
            ("打开 JSON", self.open_json),
            ("导入 Excel", self.import_excel),
            ("保存 JSON", self.save_json),
            ("添加模块", lambda: self._add_module()),
            ("删除模块", self._remove_selected_module),
            ("生成预览", self.generate),
            ("导出 DXF", self.export_dxf_file),
            ("导出 PDF", self.export_pdf_file),
        ):
            action = QAction(label, self)
            action.triggered.connect(callback)
            toolbar.addAction(action)

        splitter = QSplitter(Qt.Orientation.Vertical)

        parameter_panel = QWidget()
        parameter_layout = QVBoxLayout(parameter_panel)
        parameter_layout.setContentsMargins(8, 8, 8, 8)
        header = QHBoxLayout()
        title = QLabel("模块参数")
        title.setStyleSheet("font-weight: 600;")
        header.addWidget(title)
        self.row_count_label = QLabel("0 个模块")
        header.addWidget(self.row_count_label)
        header.addStretch(1)
        add_button = QPushButton("添加模块")
        remove_button = QPushButton("删除模块")
        add_button.clicked.connect(lambda _checked=False: self._add_module())
        remove_button.clicked.connect(lambda _checked=False: self._remove_selected_module())
        header.addWidget(add_button)
        header.addWidget(remove_button)
        parameter_layout.addLayout(header)

        self.row_scroll = QScrollArea()
        self.row_scroll.setWidgetResizable(True)
        self.row_scroll.setFrameShape(QFrame.Shape.StyledPanel)
        self.row_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.row_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.row_container = QWidget()
        self.row_layout = QVBoxLayout(self.row_container)
        self.row_layout.setContentsMargins(4, 4, 4, 4)
        self.row_layout.setSpacing(4)
        self.row_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.row_layout.addStretch(1)
        self.row_scroll.setWidget(self.row_container)
        parameter_layout.addWidget(self.row_scroll)

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
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        preview_layout.addWidget(self.preview)

        splitter.addWidget(parameter_panel)
        splitter.addWidget(preview_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 650])
        self.setCentralWidget(splitter)

        self.rows: list[ModuleRowWidget] = []
        self.active_row: ModuleRowWidget | None = None
        self.setStyleSheet(
            "QLabel[role='fieldLabel'] { color: palette(mid); font-size: 11px; }"
            "QFrame#moduleRow { border: 1px solid palette(mid);"
            " border-left: 3px solid transparent; }"
            "QFrame#moduleRow[active='true'] { border-left: 3px solid #2f6fde; }"
        )

    def _add_empty_rows(self) -> None:
        self._add_module()

    def _add_module(
        self,
        source: tuple[ModuleParameters, BoardParameters, AnchorParameters] | None = None,
    ) -> ModuleRowWidget:
        module, board, anchor = source if source is not None else (None, None, None)
        row = ModuleRowWidget(module, board, anchor)
        row.activated.connect(self._activate_row)
        row.changed.connect(lambda r=row: self._row_changed(r))
        self.row_layout.insertWidget(self.row_layout.count() - 1, row)
        self.rows.append(row)
        self._activate_row(row)
        self._update_row_count()
        return row

    def _activate_row(self, row: ModuleRowWidget) -> None:
        if row not in self.rows:
            return
        if self.active_row is not None and self.active_row is not row:
            self.active_row.set_active(False)
        self.active_row = row
        row.set_active(True)

    def _row_changed(self, row: ModuleRowWidget) -> None:
        self._activate_row(row)
        self.statusBar().showMessage("参数已修改，点击「生成预览」更新图纸。")

    def _remove_selected_module(self) -> None:
        row = self.active_row or (self.rows[-1] if self.rows else None)
        if row is None:
            return
        index = self.rows.index(row)
        self.rows.pop(index)
        self.row_layout.removeWidget(row)
        row.deleteLater()
        if not self.rows:
            self.active_row = None
            self._add_module()
            return
        next_row = self.rows[min(index, len(self.rows) - 1)]
        self.active_row = None
        self._activate_row(next_row)
        self._update_row_count()

    def _update_row_count(self) -> None:
        self.row_count_label.setText(f"{len(self.rows)} 个模块")

    def _clear_rows(self) -> None:
        for row in self.rows:
            self.row_layout.removeWidget(row)
            row.deleteLater()
        self.rows.clear()
        self.active_row = None

    def _populate_tables(self) -> None:
        ensure_standard_project(self.project)
        self._clear_rows()
        for module in self.project.modules:
            self._add_module((
                module,
                self.project.board_for(module.module_id),
                self.project.anchor_for(module.module_id),
            ))
        if not self.project.modules:
            self._add_module()

    def new_project(self) -> None:
        self.project = Project()
        self.drawing_document = None
        self.preview.scene().clear()
        self.page_spin.setMaximum(1)
        self._clear_rows()
        self._add_module()

    def _collect_project(self) -> Project:
        modules: list[ModuleParameters] = []
        boards: list[BoardParameters] = []
        anchors: list[AnchorParameters] = []
        for row in self.rows:
            module, board, anchor = row.collect()
            modules.append(module)
            boards.append(board)
            anchors.append(anchor)
        project = Project(
            metadata=self.project.metadata,
            modules=modules,
            boards=boards,
            anchors=anchors,
        )
        ensure_standard_project(project)
        return project
