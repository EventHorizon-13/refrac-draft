from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from PySide6.QtCore import QRect, QStandardPaths, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QDoubleValidator,
    QIntValidator,
    QKeySequence,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
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
from refracdraft.exporters.dxf import export_dxf
from refracdraft.exporters.pdf import export_pdf
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
ANCHOR_LENGTH_PRESETS = ("180", "200", "220", "230", "250", "280", "300", "330", "350", "400")
DENSITY_PRESETS = ("180", "200", "210", "220", "240", "260", "280", "300")
MODULE_MATERIALS = ("1260材质", "1350板材", "1430材质", "1260", "1350", "1430")
BOARD_TYPES = ("5厘夹板", "9厘夹板", "12厘夹板", "15厘夹板", "18厘夹板")
ANCHOR_MATERIALS = ("201", "304", "309", "310")
THREAD_SPECS = ("M6", "M8", "M10", "M12", "M16")
PIN_DIAMETERS = ("5", "6", "8", "10", "12")
HOSE_SPECS = ("无胶管", "25胶管", "32胶管", "38胶管")
QUANTITY_PRESETS = ("1", "2", "5", "10", "20", "50", "100")
ANCHOR_COUNT_PRESETS = ("1", "2", "3", "4", "5", "6", "8", "10")

ANCHOR_TYPES = (
    ("M型", AnchorType.M_SHAPE),
    ("菱形", AnchorType.DIAMOND),
    ("旁插", AnchorType.SIDE_INSERT),
    ("快插", AnchorType.QUICK_INSERT),
    ("焊接菱形", AnchorType.WELDED_DIAMOND),
    ("自定义", AnchorType.CUSTOM),
)
ANCHOR_TYPE_BY_LABEL = dict(ANCHOR_TYPES)
ANCHOR_LABEL_BY_TYPE = {value: label for label, value in ANCHOR_TYPES}


@dataclass(frozen=True)
class ColumnSpec:
    key: str
    label: str
    kind: str = "text"
    options: tuple[str, ...] = ()
    width: int = 84
    group: str = "module"


COLUMN_SPECS = (
    ColumnSpec("module_id", "编号", width=78, group="base"),
    ColumnSpec("length_mm", "长度 (mm)", "number", LENGTH_PRESETS, 78, "base"),
    ColumnSpec("expansion_length_mm", "膨胀长度 (mm)", "number", EXPANSION_PRESETS, 92, "base"),
    ColumnSpec("thickness_mm", "厚度 (mm)", "number", THICKNESS_PRESETS, 78, "base"),
    ColumnSpec("material", "模块材质", "combo", MODULE_MATERIALS, 108, "base"),
    ColumnSpec("production_quantity", "模块数量", "integer", QUANTITY_PRESETS, 76, "base"),
    ColumnSpec("taper_enabled", "大小头", "check", width=66, group="taper"),
    ColumnSpec("big_head_mm", "大头 (mm)", "number", HEAD_PRESETS, 78, "taper"),
    ColumnSpec("small_head_mm", "小头 (mm)", "number", HEAD_PRESETS, 78, "taper"),
    ColumnSpec("taper_type", "大小头类型", "enum", ("正敲", "侧敲"), 92, "taper"),
    ColumnSpec("board_exists", "夹板", "check", width=60, group="board"),
    ColumnSpec("board_material", "夹板类型", "combo", BOARD_TYPES, 100, "board"),
    ColumnSpec("anchor_enabled", "锚固件", "check", width=66, group="anchor"),
    ColumnSpec("anchor_position_mm", "位置 (mm)", "number", POSITION_PRESETS, 78, "anchor"),
    ColumnSpec("anchor_spacing_mm", "间距 (mm)", "number", SPACING_PRESETS, 78, "anchor"),
    ColumnSpec("anchor_count", "锚固数量", "integer", ANCHOR_COUNT_PRESETS, 94, "anchor"),
    ColumnSpec(
        "anchor_type",
        "锚固件类型",
        "enum",
        tuple(label for label, _ in ANCHOR_TYPES),
        102,
        "anchor",
    ),
    ColumnSpec("anchor_length_mm", "锚固件长度 (mm)", "number", ANCHOR_LENGTH_PRESETS, 112, "anchor"),
    ColumnSpec("anchor_material", "锚固件材质", "combo", ANCHOR_MATERIALS, 96, "anchor"),
    ColumnSpec("thread_spec", "螺栓 M", "combo", THREAD_SPECS, 90, "anchor"),
    ColumnSpec("pin_diameter_mm", "插针 φ (mm)", "number", PIN_DIAMETERS, 98, "anchor"),
    ColumnSpec("hose_spec", "胶管", "combo", HOSE_SPECS, 96, "anchor"),
    ColumnSpec("embedment_depth_mm", "嵌入深度 (mm)", "number", EMBEDMENT_PRESETS, 108, "anchor"),
    ColumnSpec("density_kg_m3", "容重 (kg/m³)", "number", DENSITY_PRESETS, 108, "footer"),
    ColumnSpec("source_note", "备注", width=170, group="footer"),
)
COLUMN_INDEX = {spec.key: index for index, spec in enumerate(COLUMN_SPECS)}
COLUMN_BY_KEY = {spec.key: spec for spec in COLUMN_SPECS}
TAPER_SETTING_KEYS = ("big_head_mm", "small_head_mm", "taper_type")
ANCHOR_SETTING_KEYS = (
    "anchor_position_mm",
    "anchor_spacing_mm",
    "anchor_count",
    "anchor_type",
    "anchor_length_mm",
    "anchor_material",
    "thread_spec",
    "pin_diameter_mm",
    "hose_spec",
    "embedment_depth_mm",
)

DEFAULT_ROW = {
    "module_id": "M1",
    "length_mm": "300",
    "expansion_length_mm": "300",
    "thickness_mm": "230",
    "material": "1430材质",
    "production_quantity": "1",
    "taper_enabled": False,
    "big_head_mm": "289",
    "small_head_mm": "220",
    "taper_type": "正敲",
    "board_exists": True,
    "board_material": "9厘夹板",
    "anchor_enabled": False,
    "anchor_position_mm": "50",
    "anchor_spacing_mm": "300",
    "anchor_count": "1",
    "anchor_type": "M型",
    "anchor_length_mm": "230",
    "anchor_material": "310",
    "thread_spec": "M10",
    "pin_diameter_mm": "8",
    "hose_spec": "32胶管",
    "embedment_depth_mm": "50",
    "density_kg_m3": "220",
    "source_note": "",
}


def _number(value: str, label: str, module_id: str) -> float:
    try:
        parsed = float(value.strip().replace(",", ""))
    except (TypeError, ValueError):
        raise ValueError(f"{module_id or '未编号模块'}: {label}必须是数字") from None
    if parsed <= 0:
        raise ValueError(f"{module_id or '未编号模块'}: {label}必须大于 0")
    return parsed


def _optional_number(value: str, label: str, module_id: str) -> float | None:
    if not value.strip():
        return None
    return _number(value, label, module_id)


def _integer(value: str, label: str, module_id: str, minimum: int = 1) -> int:
    try:
        parsed = int(float(value.strip()))
    except (TypeError, ValueError):
        raise ValueError(f"{module_id or '未编号模块'}: {label}必须是整数") from None
    if parsed < minimum:
        raise ValueError(f"{module_id or '未编号模块'}: {label}必须至少为 {minimum}")
    return parsed


def _short_rule() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    line.setFixedWidth(54)
    line.setFixedHeight(1)
    return line


class ParameterDelegate(QStyledItemDelegate):
    """Editable preset editor used by the spreadsheet-style module table."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

    def createEditor(self, parent: QWidget, option, index):
        spec = COLUMN_SPECS[index.column()]
        if spec.kind == "check":
            return None
        if spec.kind in {"combo", "number", "integer", "enum"}:
            editor = QComboBox(parent)
            editor.setMaxVisibleItems(18)
            editor.setEditable(spec.kind != "enum")
            editor.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            editor.addItems(spec.options)
            if editor.isEditable():
                if spec.kind == "number":
                    validator = QDoubleValidator(0.0, 1_000_000.0, 2, editor)
                    validator.setNotation(QDoubleValidator.Notation.StandardNotation)
                elif spec.kind == "integer":
                    validator = QIntValidator(0, 1_000_000, editor)
                else:
                    validator = None
                if validator is not None:
                    editor.lineEdit().setValidator(validator)
                editor.lineEdit().setPlaceholderText("自定义")
            return editor
        editor = QLineEdit(parent)
        editor.setMaxLength(180)
        return editor

    def setEditorData(self, editor, index) -> None:
        value = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if isinstance(editor, QComboBox):
            position = editor.findText(str(value))
            if position >= 0:
                editor.setCurrentIndex(position)
            elif editor.isEditable():
                editor.setCurrentText(str(value))
        elif isinstance(editor, QLineEdit):
            editor.setText(str(value))

    def setModelData(self, editor, model, index) -> None:
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)
        elif isinstance(editor, QLineEdit):
            model.setData(index, editor.text(), Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(self, editor, option, index) -> None:
        editor.setGeometry(option.rect)


class ParameterTable(QTableWidget):
    """QTableWidget with an Excel-style fill handle and multi-cell paste."""

    changed = Signal()
    rowsRequired = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(0, len(COLUMN_SPECS), parent)
        self._fill_source: tuple[int, int, int, int] | None = None
        self._fill_target: tuple[int, int] | None = None
        self._fill_dragging = False
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def _visible_selected_range(self) -> tuple[int, int, int, int] | None:
        indexes = [index for index in self.selectionModel().selectedIndexes()
                   if not self.isColumnHidden(index.column())]
        if not indexes:
            return None
        rows = [index.row() for index in indexes]
        columns = [index.column() for index in indexes]
        return min(rows), min(columns), max(rows), max(columns)

    def _handle_rect(self) -> QRect:
        selected = self._visible_selected_range()
        if selected is None:
            return QRect()
        top, left, bottom, right = selected
        corner = self.visualRect(self.model().index(bottom, right))
        return QRect(corner.right() - 3, corner.bottom() - 3, 7, 7)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._fill_dragging and self._fill_source and self._fill_target:
            row, column = self._fill_target
            top, left, bottom, right = self._fill_source
            bounds = (min(top, row), min(left, column), max(bottom, row), max(right, column))
            start = self.visualRect(self.model().index(bounds[0], bounds[1]))
            end = self.visualRect(self.model().index(bounds[2], bounds[3]))
            if start.isValid() and end.isValid():
                painter = QPainter(self.viewport())
                painter.setPen(QPen(QColor("#3b82f6"), 1.0, Qt.PenStyle.DashLine))
                painter.setBrush(QColor(59, 130, 246, 32))
                painter.drawRect(QRect(start.topLeft(), end.bottomRight()))
                painter.end()
        selected = self._visible_selected_range()
        if selected is None:
            return
        handle = self._handle_rect()
        if not handle.isEmpty():
            painter = QPainter(self.viewport())
            painter.fillRect(handle, QColor("#3b82f6"))
            painter.setPen(QPen(QColor("#ffffff"), 1.0))
            painter.drawRect(handle.adjusted(0, 0, -1, -1))
            painter.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            position = event.position().toPoint()
            if self._handle_rect().adjusted(-2, -2, 2, 2).contains(position):
                self._fill_source = self._visible_selected_range()
                target = self.indexAt(position)
                self._fill_target = (target.row(), target.column()) if target.isValid() else None
                self._fill_dragging = self._fill_source is not None
                self.viewport().setCursor(Qt.CursorShape.SizeFDiagCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._fill_dragging:
            target = self.indexAt(event.position().toPoint())
            if target.isValid() and not self.isColumnHidden(target.column()):
                self._fill_target = (target.row(), target.column())
                self.viewport().update()
            event.accept()
            return
        if self._handle_rect().adjusted(-2, -2, 2, 2).contains(event.position().toPoint()):
            self.viewport().setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self.viewport().unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._fill_dragging and event.button() == Qt.MouseButton.LeftButton:
            if self._fill_source and self._fill_target:
                target = self.indexAt(event.position().toPoint())
                if target.isValid():
                    self._fill_target = (target.row(), target.column())
                    self._apply_fill(self._fill_source, self._fill_target)
            self._fill_dragging = False
            self._fill_source = None
            self._fill_target = None
            self.viewport().unsetCursor()
            self.viewport().update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _copy_item(self, target: QTableWidgetItem, source: QTableWidgetItem) -> None:
        target.setText(source.text())
        if source.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            target.setCheckState(source.checkState())

    def _apply_fill(self, source: tuple[int, int, int, int],
                    target: tuple[int, int]) -> None:
        top, left, bottom, right = source
        target_row, target_column = target
        target_bounds = (
            min(top, target_row),
            min(left, target_column),
            max(bottom, target_row),
            max(right, target_column),
        )
        if target_bounds == source:
            return
        source_height = bottom - top + 1
        source_width = right - left + 1
        self.blockSignals(True)
        try:
            for row in range(target_bounds[0], target_bounds[2] + 1):
                for column in range(target_bounds[1], target_bounds[3] + 1):
                    if top <= row <= bottom and left <= column <= right:
                        continue
                    if self.isColumnHidden(column):
                        continue
                    source_row = top + (row - top) % source_height
                    source_column = left + (column - left) % source_width
                    source_item = self.item(source_row, source_column)
                    target_item = self.item(row, column)
                    if source_item is not None and target_item is not None:
                        self._copy_item(target_item, source_item)
        finally:
            self.blockSignals(False)
        self.setCurrentCell(target_bounds[2], target_bounds[3])
        self.changed.emit()

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Paste):
            self._paste_clipboard()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Delete):
            self._clear_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def _clear_selection(self) -> None:
        self.blockSignals(True)
        try:
            for index in self.selectionModel().selectedIndexes():
                item = self.item(index.row(), index.column())
                if item is None or not (item.flags() & Qt.ItemFlag.ItemIsEditable):
                    continue
                item.setText("")
        finally:
            self.blockSignals(False)
        self.changed.emit()

    def _paste_clipboard(self) -> None:
        text = QApplication.clipboard().text()
        if not text:
            return
        rows = text.replace("\r", "").split("\n")
        if rows and rows[-1] == "":
            rows.pop()
        matrix = [row.split("\t") for row in rows]
        if not matrix:
            return
        start_row = max(0, self.currentRow())
        start_column = max(0, self.currentColumn())
        while start_column < self.columnCount() and self.isColumnHidden(start_column):
            start_column += 1
        if start_column >= self.columnCount():
            return
        missing_rows = start_row + len(matrix) - self.rowCount()
        if missing_rows > 0:
            self.rowsRequired.emit(missing_rows)
        self.blockSignals(True)
        try:
            for row_offset, values in enumerate(matrix):
                row = start_row + row_offset
                if row >= self.rowCount():
                    break
                visible_columns = [
                    column
                    for column in range(start_column, self.columnCount())
                    if not self.isColumnHidden(column)
                ]
                all_columns = list(range(start_column, self.columnCount()))
                columns = all_columns if len(values) > len(visible_columns) else visible_columns
                column_index = 0
                for value in values:
                    if column_index >= len(columns):
                        break
                    column = columns[column_index]
                    item = self.item(row, column)
                    if item is not None:
                        spec = COLUMN_SPECS[column]
                        if spec.kind == "check":
                            checked = value.strip().lower() in {"1", "是", "yes", "true", "y"}
                            item.setCheckState(
                                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                            )
                            item.setText("是" if checked else "否")
                        elif item.flags() & Qt.ItemFlag.ItemIsEditable:
                            item.setText(value.strip())
                    column_index += 1
        finally:
            self.blockSignals(False)
        self.changed.emit()


class StandardWindow(MainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RefracDraft Standard — 模块加工图生成器")
        self.statusBar().showMessage("修改参数后点击「生成预览」；可拖动选区右下角批量填充。")

    def _build_ui(self) -> None:
        self._row_bases: list[
            tuple[ModuleParameters | None, BoardParameters | None, AnchorParameters | None]
        ] = []
        self._updating_table = False

        toolbar = QToolBar("主工具栏")
        self.addToolBar(toolbar)
        for label, callback in (
            ("新建", self.new_project),
            ("打开 JSON", self.open_json),
            ("导入 Excel", self.import_excel),
            ("保存 JSON", self.save_json),
            ("生成预览", self.generate),
        ):
            action = QAction(label, self)
            action.triggered.connect(callback)
            toolbar.addAction(action)
        toolbar.addSeparator()
        for label, callback in (
            ("添加模块", lambda: self._add_module()),
            ("删除模块", self._remove_selected_module),
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

        self.parameter_table = ParameterTable()
        self.module_table = self.parameter_table
        self.tables = {"modules": self.parameter_table}
        table = self.parameter_table
        table.setObjectName("moduleParameterTable")
        table.setHorizontalHeaderLabels([spec.label for spec in COLUMN_SPECS])
        table.setItemDelegate(ParameterDelegate(table))
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.setShowGrid(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setMinimumSectionSize(52)
        table.verticalHeader().setDefaultSectionSize(31)
        table.verticalHeader().setMinimumWidth(40)
        table.setMinimumHeight(185)
        for column, spec in enumerate(COLUMN_SPECS):
            table.setColumnWidth(column, spec.width)
            header_item = table.horizontalHeaderItem(column)
            if header_item is not None:
                header_item.setToolTip(spec.label)
        table.itemChanged.connect(self._table_item_changed)
        table.currentCellChanged.connect(self._current_cell_changed)
        table.changed.connect(self._table_bulk_changed)
        table.rowsRequired.connect(self._ensure_row_count)
        parameter_layout.addWidget(table)

        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        preview_splitter = QSplitter(Qt.Orientation.Horizontal)

        output_panel = QFrame()
        output_panel.setObjectName("outputPanel")
        output_panel.setMinimumWidth(245)
        output_panel.setMaximumWidth(365)
        output_layout = QVBoxLayout(output_panel)
        output_layout.setContentsMargins(12, 10, 12, 10)
        output_layout.setSpacing(7)
        output_title = QLabel("输出设置")
        output_title.setStyleSheet("font-weight: 600;")
        output_layout.addWidget(output_title)
        output_layout.addWidget(_short_rule())

        output_layout.addWidget(QLabel("工作目录"))
        directory_row = QHBoxLayout()
        self.output_directory_edit = QLineEdit()
        self.output_directory_edit.setPlaceholderText("选择保存目录")
        self.working_directory_edit = self.output_directory_edit
        self.browse_directory_button = QPushButton("选择")
        self.browse_directory_button.setFixedWidth(58)
        self.browse_directory_button.clicked.connect(self._choose_output_directory)
        directory_row.addWidget(self.output_directory_edit, 1)
        directory_row.addWidget(self.browse_directory_button)
        output_layout.addLayout(directory_row)

        output_layout.addWidget(QLabel("自定义文件名"))
        self.output_filename_edit = QLineEdit("module-drawing")
        self.output_filename_edit.setPlaceholderText("不含扩展名")
        output_layout.addWidget(self.output_filename_edit)

        page_row = QHBoxLayout()
        page_row.addWidget(QLabel("预览页"))
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.valueChanged.connect(self._show_selected_page)
        page_row.addWidget(self.page_spin)
        page_row.addStretch(1)
        output_layout.addLayout(page_row)

        self.output_path_label = QLabel()
        self.output_path_label.setProperty("role", "fieldLabel")
        self.output_path_label.setWordWrap(True)
        output_layout.addWidget(self.output_path_label)
        output_layout.addStretch(1)

        self.output_dxf_button = QPushButton("导出 DXF")
        self.output_pdf_button = QPushButton("导出 PDF")
        self.output_pdf_button.setProperty("primary", True)
        self.output_dxf_button.clicked.connect(self.export_dxf_file)
        self.output_pdf_button.clicked.connect(self.export_pdf_file)
        output_layout.addWidget(self.output_dxf_button)
        output_layout.addWidget(self.output_pdf_button)

        preview_canvas = QWidget()
        canvas_layout = QVBoxLayout(preview_canvas)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_header = QHBoxLayout()
        canvas_header.addWidget(QLabel("图纸预览"))
        canvas_header.addStretch(1)
        canvas_layout.addLayout(canvas_header)
        self.preview = DrawingPreview()
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        canvas_layout.addWidget(self.preview)

        preview_splitter.addWidget(output_panel)
        preview_splitter.addWidget(preview_canvas)
        preview_splitter.setStretchFactor(0, 0)
        preview_splitter.setStretchFactor(1, 1)
        preview_splitter.setSizes([280, 1040])
        preview_layout.addWidget(preview_splitter)

        splitter.addWidget(parameter_panel)
        splitter.addWidget(preview_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([330, 570])
        self.setCentralWidget(splitter)

        preferred_directory = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        )
        self.output_directory_edit.setText(preferred_directory or str(Path.cwd()))
        self.output_directory_edit.textChanged.connect(self._update_output_preview)
        self.output_filename_edit.textChanged.connect(self._update_output_preview)
        self._update_output_preview()

        self.setStyleSheet(
            "QTableWidget#moduleParameterTable {"
            " gridline-color: palette(mid); alternate-background-color: palette(alternate-base); }"
            "QTableWidget#moduleParameterTable QHeaderView::section {"
            " padding: 4px 6px; background-color: palette(button); color: palette(button-text);"
            " border: 0; border-right: 1px solid palette(mid); border-bottom: 1px solid palette(mid); }"
            "QFrame#outputPanel { border: 1px solid palette(mid); border-radius: 4px; }"
            "QPushButton[primary='true'] { background: #2f6fde; color: white;"
            " border: 1px solid #245bb8; border-radius: 4px; padding: 6px 10px; }"
            "QPushButton[primary='true']:hover { background: #3b7bea; }"
            "QLabel[role='fieldLabel'] { font-size: 11px; color: palette(mid); }"
        )

    def _add_empty_rows(self) -> None:
        self._add_module()

    def _default_output_directory(self) -> Path:
        text = self.output_directory_edit.text().strip() if hasattr(self, "output_directory_edit") else ""
        if text:
            return Path(text).expanduser()
        return Path.cwd()

    def _choose_output_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择输出工作目录",
            str(self._default_output_directory()),
        )
        if directory:
            self.output_directory_edit.setText(directory)

    def _filename_stem(self) -> str:
        value = self.output_filename_edit.text().strip() if hasattr(self, "output_filename_edit") else ""
        if value.lower().endswith((".dxf", ".pdf")):
            value = Path(value).stem
        value = re.sub(r'[<>:"/\\|?*]+', "-", value).strip(" .")
        return value or "module-drawing"

    def _update_output_preview(self, *_args) -> None:
        if not hasattr(self, "output_path_label"):
            return
        directory = self.output_directory_edit.text().strip() or "当前工作目录"
        stem = self._filename_stem()
        self.output_path_label.setText(f"{directory}\n{stem}.dxf  /  {stem}.pdf")

    def _output_target(self, suffix: str) -> Path | None:
        directory_text = self.output_directory_edit.text().strip()
        if not directory_text:
            path, _ = QFileDialog.getSaveFileName(
                self,
                f"导出 {suffix.removeprefix('.').upper()}",
                f"{self._filename_stem()}{suffix}",
                f"{suffix.removeprefix('.').upper()} 文件 (*{suffix})",
            )
            return Path(path) if path else None
        directory = Path(directory_text).expanduser()
        target = directory / f"{self._filename_stem()}{suffix}"
        if target.exists():
            answer = QMessageBox.question(
                self,
                "覆盖文件",
                f"文件已存在，是否覆盖？\n{target}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return None
        return target

    @property
    def rows(self) -> list[int]:
        return list(range(self.parameter_table.rowCount()))

    def _next_unique_module_id(self, base: str, used: set[str]) -> str:
        match = re.match(r"^(.*?)(\d+)$", base.strip())
        if match:
            prefix, number_text = match.groups()
            number = int(number_text)
            width = len(number_text)
            while True:
                number += 1
                candidate = f"{prefix}{number:0{width}d}"
                if candidate not in used:
                    return candidate
        candidate = f"{base}-2"
        index = 2
        while candidate in used:
            index += 1
            candidate = f"{base}-{index}"
        return candidate

    def _row_values_from_models(
        self,
        module: ModuleParameters,
        board: BoardParameters | None,
        anchor: AnchorParameters | None,
    ) -> dict[str, str | bool]:
        board_model = board or BoardParameters(module_id=module.module_id, exists=False)
        anchor_model = anchor or AnchorParameters(
            module_id=module.module_id,
            exists=False,
            anchor_type=AnchorType.NONE,
            count=0,
        )
        module_values = standard_module_values(module, board_model)
        anchor_values = standard_anchor_values(anchor_model)
        return {
            "module_id": module_values.module_id,
            "length_mm": f"{module_values.length_mm:g}",
            "expansion_length_mm": f"{module_values.expansion_length_mm:g}",
            "thickness_mm": f"{module_values.thickness_mm:g}",
            "material": module_values.material,
            "production_quantity": str(module_values.production_quantity),
            "taper_enabled": module_values.taper_enabled,
            "big_head_mm": f"{module_values.big_head_mm:g}" if module_values.big_head_mm is not None else "289",
            "small_head_mm": f"{module_values.small_head_mm:g}" if module_values.small_head_mm is not None else "220",
            "taper_type": module_values.taper_type.value,
            "board_exists": module_values.board_exists,
            "board_material": module_values.board_material,
            "anchor_enabled": anchor_values.enabled,
            "anchor_position_mm": f"{anchor_values.position_mm:g}",
            "anchor_spacing_mm": f"{anchor_values.spacing_mm:g}",
            "anchor_count": str(anchor_values.count),
            "anchor_type": ANCHOR_LABEL_BY_TYPE.get(anchor_values.anchor_type, "M型"),
            "anchor_length_mm": f"{anchor_values.length_mm or 230.0:g}",
            "anchor_material": anchor_model.material or anchor_values.material,
            "thread_spec": anchor_model.thread_spec or anchor_values.thread_spec,
            "pin_diameter_mm": (
                f"{anchor_values.pin_diameter_mm:g}" if anchor_values.pin_diameter_mm is not None else "8"
            ),
            "hose_spec": anchor_model.hose_spec or anchor_values.hose_spec,
            "embedment_depth_mm": (
                f"{anchor_values.embedment_depth_mm:g}"
                if anchor_values.embedment_depth_mm is not None
                else "50"
            ),
            "density_kg_m3": (
                f"{module_values.density_kg_m3:g}" if module_values.density_kg_m3 is not None else ""
            ),
            "source_note": module_values.source_note,
        }

    def _write_row(self, row: int, values: dict[str, str | bool]) -> None:
        table = self.parameter_table
        for column, spec in enumerate(COLUMN_SPECS):
            value = values.get(spec.key, DEFAULT_ROW.get(spec.key, ""))
            item = QTableWidgetItem()
            if spec.kind == "check":
                if isinstance(value, str):
                    checked = value.strip().lower() in {"1", "是", "yes", "true", "y"}
                else:
                    checked = bool(value)
                item.setText("是" if checked else "否")
                item.setFlags(
                    Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            else:
                item.setText("" if value is None else str(value))
                item.setFlags(
                    Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsEditable
                )
                alignment = (
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    if spec.kind in {"number", "integer"}
                    else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                item.setTextAlignment(alignment)
            table.setItem(row, column, item)

    def _sheet_values(self, row: int) -> dict[str, str | bool]:
        values: dict[str, str | bool] = {}
        for column, spec in enumerate(COLUMN_SPECS):
            item = self.parameter_table.item(row, column)
            if item is None:
                values[spec.key] = False if spec.kind == "check" else ""
            elif spec.kind == "check":
                values[spec.key] = item.checkState() == Qt.CheckState.Checked
            else:
                values[spec.key] = item.text().strip()
        return values

    def _add_module(
        self,
        source: tuple[ModuleParameters, BoardParameters, AnchorParameters] | None = None,
    ) -> int:
        table = self.parameter_table
        base: tuple[ModuleParameters | None, BoardParameters | None, AnchorParameters | None]
        if source is not None:
            module, board, anchor = source
            values = self._row_values_from_models(module, board, anchor)
            base = source
        elif table.rowCount():
            values = self._sheet_values(table.rowCount() - 1)
            used = {
                str(self._sheet_values(row).get("module_id", "")).strip()
                for row in range(table.rowCount())
            }
            base_id = str(values.get("module_id", "M1")).strip() or "M1"
            values["module_id"] = self._next_unique_module_id(base_id, used)
            base = (None, None, None)
        else:
            values = dict(DEFAULT_ROW)
            base = (None, None, None)

        row = table.rowCount()
        self._updating_table = True
        table.blockSignals(True)
        try:
            table.insertRow(row)
            self._write_row(row, values)
            self._row_bases.append(base)
        finally:
            table.blockSignals(False)
            self._updating_table = False
        self._update_row_count()
        self._update_conditional_states()
        table.clearSelection()
        table.setCurrentCell(row, 0)
        return row

    def _ensure_row_count(self, extra: int) -> None:
        for _ in range(max(0, int(extra))):
            self._add_module()

    def _remove_selected_module(self) -> None:
        table = self.parameter_table
        rows = sorted({index.row() for index in table.selectionModel().selectedIndexes()}, reverse=True)
        if not rows:
            current = table.currentRow()
            if current >= 0:
                rows = [current]
        if not rows:
            return
        table.blockSignals(True)
        try:
            for row in rows:
                table.removeRow(row)
                if 0 <= row < len(self._row_bases):
                    self._row_bases.pop(row)
        finally:
            table.blockSignals(False)
        if table.rowCount() == 0:
            self._add_module()
        else:
            table.clearSelection()
            table.setCurrentCell(min(rows[-1], table.rowCount() - 1), 0)
        self._update_row_count()
        self._update_conditional_states()

    def _update_row_count(self) -> None:
        count = self.parameter_table.rowCount()
        self.row_count_label.setText(f"{count} 个模块")

    def _clear_rows(self) -> None:
        self.parameter_table.blockSignals(True)
        try:
            self.parameter_table.setRowCount(0)
            self._row_bases.clear()
        finally:
            self.parameter_table.blockSignals(False)
        self._update_row_count()
        self._update_conditional_states()

    def _set_cell_text(self, row: int, key: str, text: str) -> None:
        item = self.parameter_table.item(row, COLUMN_INDEX[key])
        if item is not None:
            item.setText(text)

    def _cell_text(self, row: int, key: str) -> str:
        item = self.parameter_table.item(row, COLUMN_INDEX[key])
        return item.text().strip() if item is not None else ""

    def _cell_bool(self, row: int, key: str) -> bool:
        item = self.parameter_table.item(row, COLUMN_INDEX[key])
        return item is not None and item.checkState() == Qt.CheckState.Checked

    def _sync_expansion_length(self, row: int) -> None:
        if self._cell_bool(row, "taper_enabled"):
            big = self._cell_text(row, "big_head_mm")
            if big:
                self._set_cell_text(row, "expansion_length_mm", big)

    def _set_cell_enabled(self, row: int, key: str, enabled: bool) -> None:
        item = self.parameter_table.item(row, COLUMN_INDEX[key])
        if item is None:
            return
        flags = item.flags()
        if enabled:
            flags |= Qt.ItemFlag.ItemIsEnabled
            if COLUMN_BY_KEY[key].kind != "check":
                flags |= Qt.ItemFlag.ItemIsEditable
        else:
            flags &= ~Qt.ItemFlag.ItemIsEnabled
            flags &= ~Qt.ItemFlag.ItemIsEditable
        item.setFlags(flags)

    def _update_conditional_states(self) -> None:
        table = self.parameter_table
        if table.rowCount() == 0:
            for key in ANCHOR_SETTING_KEYS:
                table.setColumnHidden(COLUMN_INDEX[key], True)
            return
        any_anchor = any(self._cell_bool(row, "anchor_enabled") for row in range(table.rowCount()))
        any_diamond = any(
            self._cell_bool(row, "anchor_enabled") and self._cell_text(row, "anchor_type") == "菱形"
            for row in range(table.rowCount())
        )
        any_pin_anchor = any(
            self._cell_bool(row, "anchor_enabled") and self._cell_text(row, "anchor_type") != "菱形"
            for row in range(table.rowCount())
        )
        for key in ANCHOR_SETTING_KEYS:
            table.setColumnHidden(COLUMN_INDEX[key], not any_anchor)
        table.setColumnHidden(COLUMN_INDEX["embedment_depth_mm"], not any_diamond)
        table.setColumnHidden(COLUMN_INDEX["pin_diameter_mm"], not any_pin_anchor)

        was_updating = self._updating_table
        self._updating_table = True
        try:
            for row in range(table.rowCount()):
                taper = self._cell_bool(row, "taper_enabled")
                board = self._cell_bool(row, "board_exists")
                anchor = self._cell_bool(row, "anchor_enabled")
                is_diamond = self._cell_text(row, "anchor_type") == "菱形"
                self._set_cell_enabled(row, "expansion_length_mm", not taper)
                for key in TAPER_SETTING_KEYS:
                    self._set_cell_enabled(row, key, taper)
                self._set_cell_enabled(row, "board_material", board)
                for key in ANCHOR_SETTING_KEYS:
                    enabled = anchor and not (key == "pin_diameter_mm" and is_diamond)
                    enabled = enabled and not (key == "embedment_depth_mm" and not is_diamond)
                    self._set_cell_enabled(row, key, enabled)
                if taper:
                    self._sync_expansion_length(row)
        finally:
            self._updating_table = was_updating

    def _table_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_table or item.row() >= len(self._row_bases):
            return
        spec = COLUMN_SPECS[item.column()]
        self._updating_table = True
        try:
            if spec.kind == "check":
                checked = item.checkState() == Qt.CheckState.Checked
                item.setText("是" if checked else "否")
            if spec.key in {"taper_enabled", "big_head_mm"}:
                self._sync_expansion_length(item.row())
        finally:
            self._updating_table = False
        self._update_conditional_states()
        self.statusBar().showMessage("参数已修改，点击「生成预览」更新图纸。")

    def _table_bulk_changed(self) -> None:
        if self._updating_table:
            return
        self._updating_table = True
        try:
            self._ensure_unique_module_ids()
        finally:
            self._updating_table = False
        self._update_row_count()
        self._update_conditional_states()
        self.statusBar().showMessage("参数已修改，点击「生成预览」更新图纸。")

    def _ensure_unique_module_ids(self) -> None:
        used: set[str] = set()
        for row in range(self.parameter_table.rowCount()):
            module_id = self._cell_text(row, "module_id") or "M1"
            if module_id in used:
                module_id = self._next_unique_module_id(module_id, used)
                item = self.parameter_table.item(row, COLUMN_INDEX["module_id"])
                if item is not None:
                    item.setText(module_id)
            used.add(module_id)

    def _current_cell_changed(self, current_row: int, _current_column: int,
                              _previous_row: int, _previous_column: int) -> None:
        if current_row < 0 or current_row >= self.parameter_table.rowCount():
            return
        module_id = self._cell_text(current_row, "module_id") or f"第 {current_row + 1} 行"
        self.statusBar().showMessage(f"当前模块：{module_id}")

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
        self._update_row_count()
        self._update_conditional_states()

    def new_project(self) -> None:
        self.project = Project()
        self.drawing_document = None
        self.preview.scene().clear()
        self.page_spin.setMaximum(1)
        self._clear_rows()
        self._add_module()

    def _build_project_row(self, row: int) -> tuple[
        ModuleParameters, BoardParameters, AnchorParameters
    ]:
        values = self._sheet_values(row)
        module_id = str(values["module_id"]).strip()
        if not module_id:
            raise ValueError("模块编号不能为空")
        module_values = StandardModuleValues(
            module_id=module_id,
            length_mm=_number(str(values["length_mm"]), "长度", module_id),
            expansion_length_mm=_number(str(values["expansion_length_mm"]), "膨胀长度", module_id),
            thickness_mm=_number(str(values["thickness_mm"]), "厚度", module_id),
            taper_enabled=bool(values["taper_enabled"]),
            big_head_mm=(
                _number(str(values["big_head_mm"]), "大头", module_id)
                if values["taper_enabled"]
                else None
            ),
            small_head_mm=(
                _number(str(values["small_head_mm"]), "小头", module_id)
                if values["taper_enabled"]
                else None
            ),
            taper_type=self._geometry_type(str(values["taper_type"]), module_id),
            board_exists=bool(values["board_exists"]),
            material=str(values["material"]).strip(),
            production_quantity=_integer(str(values["production_quantity"]), "模块数量", module_id),
            board_material=str(values["board_material"]).strip() or "9厘夹板",
            density_kg_m3=_optional_number(str(values["density_kg_m3"]), "容重", module_id),
            source_note=str(values["source_note"]).strip(),
        )
        base_module, base_board, base_anchor = self._row_bases[row]
        module = build_standard_module(base_module, module_values)
        board = build_standard_board(
            base_board,
            module.module_id,
            module_values.board_exists,
            module_values.board_material,
        )
        anchor = build_standard_anchor(
            base_anchor,
            module.module_id,
            module_values.length_mm,
            self._anchor_values(values, module.module_id),
        )
        return module, board, anchor

    @staticmethod
    def _geometry_type(value: str, module_id: str) -> GeometryType:
        try:
            return GeometryType(value)
        except ValueError:
            raise ValueError(f"{module_id}: 大小头类型必须是正敲或侧敲") from None

    def _anchor_values(self, values: dict[str, str | bool], module_id: str) -> StandardAnchorValues:
        enabled = bool(values["anchor_enabled"])
        type_label = str(values["anchor_type"]).strip()
        anchor_type = ANCHOR_TYPE_BY_LABEL.get(type_label)
        if anchor_type is None:
            try:
                anchor_type = AnchorType(type_label)
            except ValueError:
                anchor_type = AnchorType.CUSTOM
        if not enabled:
            pin_text = str(values["pin_diameter_mm"]).strip()
            return StandardAnchorValues(
                enabled=False,
                anchor_type=anchor_type,
                material=str(values["anchor_material"]).strip() or "310",
                thread_spec=str(values["thread_spec"]).strip() or "M10",
                pin_diameter_mm=_optional_number(pin_text, "插针直径", module_id),
                hose_spec=str(values["hose_spec"]).strip() or "32胶管",
            )
        if anchor_type == AnchorType.NONE:
            raise ValueError(f"{module_id}: 已勾选锚固件，必须选择锚固件类型")
        embedment = None
        if anchor_type == AnchorType.DIAMOND:
            embedment = _number(str(values["embedment_depth_mm"]), "嵌入深度", module_id)
        pin_text = str(values["pin_diameter_mm"]).strip()
        pin_diameter = (
            _number(pin_text, "插针直径", module_id)
            if pin_text and anchor_type != AnchorType.DIAMOND
            else None
        )
        return StandardAnchorValues(
            enabled=True,
            position_mm=_number(str(values["anchor_position_mm"]), "锚固件位置", module_id),
            spacing_mm=_number(str(values["anchor_spacing_mm"]), "锚固件间距", module_id),
            count=_integer(str(values["anchor_count"]), "锚固件数量", module_id),
            anchor_type=anchor_type,
            embedment_depth_mm=embedment,
            material=str(values["anchor_material"]).strip() or "310",
            thread_spec=str(values["thread_spec"]).strip() or "M10",
            pin_diameter_mm=pin_diameter,
            hose_spec=str(values["hose_spec"]).strip() or "32胶管",
            length_mm=_number(str(values["anchor_length_mm"]), "锚固件长度", module_id),
        )

    def _collect_project(self) -> Project:
        modules: list[ModuleParameters] = []
        boards: list[BoardParameters] = []
        anchors: list[AnchorParameters] = []
        for row in range(self.parameter_table.rowCount()):
            module, board, anchor = self._build_project_row(row)
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

    def export_dxf_file(self) -> None:
        if not self.drawing_document:
            self.generate()
        if not self.drawing_document:
            return
        path = self._output_target(".dxf")
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            export_dxf(self.drawing_document, path, self.reference_dxf)
            self.statusBar().showMessage(f"DXF 已导出：{path}")
        except Exception as exc:
            QMessageBox.critical(self, "DXF 导出失败", str(exc))

    def export_pdf_file(self) -> None:
        if not self.drawing_document:
            self.generate()
        if not self.drawing_document:
            return
        path = self._output_target(".pdf")
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            export_pdf(self.drawing_document, path, reference_dxf=self.reference_dxf)
            self.statusBar().showMessage(f"PDF 已导出：{path}")
        except Exception as exc:
            QMessageBox.critical(self, "PDF 导出失败", str(exc))
