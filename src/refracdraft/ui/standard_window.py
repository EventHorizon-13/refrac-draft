from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime
from multiprocessing import get_context
from pathlib import Path
from queue import Empty, SimpleQueue
from tempfile import TemporaryDirectory
import re

from PySide6.QtCore import (
    QByteArray, QEvent, QEventLoop, QItemSelectionModel, QPersistentModelIndex, QPointF, QRect,
    QRegularExpression, QSettings, QSignalBlocker, QStandardPaths, QTimer, Qt, QUrl, Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QDoubleValidator,
    QFont,
    QIcon,
    QInputMethodEvent,
    QIntValidator,
    QKeySequence,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QRegularExpressionValidator,
    QShortcut,
    QTextCharFormat,
    QTextLayout,
    QTextOption,
    QValidator,
)
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QStyle,
    QStyleOption,
    QStyleOptionButton,
    QStyleOptionViewItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from refracdraft.domain.models import (
    AnchorParameters,
    AnchorType,
    DIAMOND_ANCHOR_TYPES,
    WELDED_ANCHOR_TYPES,
    BoardFaceProfile,
    BoardParameters,
    GeometryType,
    ModuleParameters,
    Project,
)
from refracdraft.drawing.generator import DrawingGenerator
from refracdraft.drawing.model import TAPER_LABEL_PATTERN, TAPER_LABEL_SCALE
from refracdraft.exporters.dxf import export_dxf
from refracdraft.exporters.pdf import PdfPageCache, export_pdf, shx_detail_measure
from refracdraft.exporters.pdf_preview import render_pdf_preview
from refracdraft.exporters.project import export_complete_project, project_output_paths
from refracdraft.release import app_version
from refracdraft.resources import application_directory
from refracdraft.reference.library import ReferenceLibrary
from refracdraft.standard import ensure_standard_project
from refracdraft.standard_sheet import (
    AUTOMATIC, AUTOMATIC_FIELDS, COLUMN_SPECS, DEFAULT_ROW, EMPTY_SELECTS_AUTOMATIC, EQUAL_SEGMENTS,
    OPTIONAL_ANCHOR_FIELDS, STANDARD_LINK_VERSION, anchor_length_options, automatic_fields, build_standard_row,
    equal_segment_values, legacy_automatic_fields, legacy_source_note, resolve_automatic_values,
    row_values_from_models, standard_board_face_bounds, standard_taper_geometry, standard_taper_label,
)
from refracdraft.ui.about import AboutDialog
from refracdraft.ui.board_face_dialog import BoardFaceDialog
from refracdraft.ui.main_window import DrawingPreview, MainWindow, PageSpinBox


@dataclass(frozen=True)
class RowBase:
    models: tuple[ModuleParameters | None, BoardParameters | None, AnchorParameters | None] = (
        None, None, None,
    )
    profile: BoardFaceProfile | None = None
    automatic_fallback: dict[str, str | bool] | None = None


@dataclass(frozen=True)
class TableState:
    rows: tuple[dict[str, str | bool], ...]
    bases: tuple[RowBase, ...]


COLUMN_INDEX = {spec.key: index for index, spec in enumerate(COLUMN_SPECS)}
COMPACT_COLUMN_WIDTHS = {
    "density_kg_m3": 44, "production_quantity": 42, "taper_enabled": 46,
    "board_exists": 40, "show_upper_board": 48, "show_lower_board": 48,
    "anchor_enabled": 48, "anchor_material": 54, "anchor_position_mm": 70,
    "anchor_count": 58, "anchor_length_mm": 64, "thread_spec": 52,
    "pin_diameter_mm": 47, "hose_spec": 47, "bolt_exposure_mm": 88,
}
PROFILE_COLUMN = len(COLUMN_SPECS)
COLUMN_BY_KEY = {spec.key: spec for spec in COLUMN_SPECS}
AUTOMATIC_PREVIEW_ROLE = int(Qt.ItemDataRole.UserRole) + 1
NOTE_ALIGNMENT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
ARROW_STEPS = {
    Qt.Key.Key_Left: (0, -1),
    Qt.Key.Key_Right: (0, 1),
    Qt.Key.Key_Up: (-1, 0),
    Qt.Key.Key_Down: (1, 0),
}
TAPER_SETTING_KEYS = ("big_head_mm", "small_head_mm", "taper_type")
BOARD_SETTING_KEYS = ("board_material", "show_upper_board", "show_lower_board")
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
    "bolt_exposure_mm",
)

def _default_filename_stem() -> str:
    return f"模块加工图_{datetime.now():%m%d}_"


def _short_rule() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    line.setFixedWidth(32)
    line.setFixedHeight(1)
    return line


class OperationProgress(QDialog):
    PDF_START = 450
    PDF_END = 950

    def __init__(self, parent: QWidget, text: str, steps: int, *, tracks_pdf: bool = False):
        super().__init__(parent)
        self.setWindowTitle("正在处理")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setMinimumWidth(320)
        layout = QVBoxLayout(self)
        self.label = QLabel(text)
        self.bar = QProgressBar()
        self._steps = steps
        self._stage = 0
        self._stage_limit = self.PDF_START if tracks_pdf else 990
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        layout.addWidget(self.label)
        layout.addWidget(self.bar)
        self.show()
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def update_stage(self, text: str, completed: int, *, pump: bool = True) -> None:
        self.label.setText(text)
        self.bar.setValue(completed)
        if pump:
            QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def advance(self, text: str, *, pump: bool = True) -> None:
        self._stage += 1
        completed = min(self._stage, self._steps) * self._stage_limit // self._steps
        self.update_stage(text, max(self.bar.value(), completed), pump=pump)

    def update_pdf_pages(self, done: int, total: int) -> None:
        completed = self.PDF_START + (self.PDF_END - self.PDF_START) * done // max(1, total)
        self.update_stage(f"正在渲染 PDF {done}/{total} 页…", completed, pump=False)

    def finish(self, text: str) -> None:
        self.update_stage(text, self.bar.maximum())


def _preset_button_rect(cell_rect: QRect) -> QRect:
    return QRect(cell_rect.right() - 15, cell_rect.top(), 16, cell_rect.height() - 7)


_BACKGROUND_WORKER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="refracdraft")


def _run_background(progress: OperationProgress, work):
    updates = SimpleQueue()
    loop = QEventLoop(progress)
    timer = QTimer(loop)
    timer.setInterval(30)
    def report(text):
        updates.put(text)

    def report_pages(done, total):
        updates.put((done, total))

    future = _BACKGROUND_WORKER.submit(work, report, report_pages)

    def refresh():
        while True:
            try:
                message = updates.get_nowait()
            except Empty:
                break
            if isinstance(message, tuple):
                progress.update_pdf_pages(*message)
            else:
                progress.advance(message, pump=False)
        if future.done() and updates.empty():
            timer.stop()
            loop.quit()

    timer.timeout.connect(refresh)
    timer.start()
    loop.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    return future.result()


def _full_window_icon(button: QPushButton, active: bool) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(button.palette().color(QPalette.ColorRole.ButtonText), 1.4))
    for left, top in ((True, True), (False, True), (True, False), (False, False)):
        outer_x, outer_y = (2.5 if left else 13.5), (2.5 if top else 13.5)
        inner_x, inner_y = (6 if left else 10), (6 if top else 10)
        if active:
            painter.drawLine(QPointF(outer_x, inner_y), QPointF(inner_x, inner_y))
            painter.drawLine(QPointF(inner_x, inner_y), QPointF(inner_x, outer_y))
        else:
            painter.drawLine(QPointF(inner_x, outer_y), QPointF(outer_x, outer_y))
            painter.drawLine(QPointF(outer_x, outer_y), QPointF(outer_x, inner_y))
    painter.end()
    return QIcon(pixmap)


class OptionalNumberValidator(QDoubleValidator):
    def validate(self, text, position):
        if not text:
            return QValidator.State.Acceptable, text, position
        return super().validate(text, position)


class ParameterDelegate(QStyledItemDelegate):
    """Editable preset editor used by the spreadsheet-style module table."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

    def createEditor(self, parent: QWidget, option, index):
        if index.column() == PROFILE_COLUMN:
            return None
        spec = COLUMN_SPECS[index.column()]
        if spec.kind == "check":
            return None
        editor = QLineEdit(parent)
        editor.setAlignment(NOTE_ALIGNMENT if spec.key == "source_note" else Qt.AlignmentFlag.AlignCenter)
        editor.setMaxLength(180)
        editor.setAutoFillBackground(True)
        editor.setStyleSheet(
            "QLineEdit { background: palette(base); color: palette(text);"
            " border: 1px solid #3b82f6; padding: 0 4px;"
            " selection-background-color: #3b82f6; selection-color: white; }"
        )
        if spec.kind == "number":
            validator_type = OptionalNumberValidator if spec.key in OPTIONAL_ANCHOR_FIELDS else QDoubleValidator
            validator = validator_type(0.0, 1_000_000.0, 2, editor)
            validator.setNotation(QDoubleValidator.Notation.StandardNotation)
            editor.setValidator(validator)
        elif spec.kind == "integer":
            validator = QIntValidator(0, 1_000_000, editor)
            editor.setValidator(validator)
        elif spec.kind == "enum" and "自定义" not in spec.options:
            choices = QRegularExpression("|".join(QRegularExpression.escape(value) for value in spec.options))
            editor.setValidator(QRegularExpressionValidator(choices, editor))
        return editor

    def eventFilter(self, editor, event) -> bool:
        if not isinstance(editor, QLineEdit) or event.type() != QEvent.Type.KeyPress:
            return super().eventFilter(editor, event)
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if editor.hasAcceptableInput():
                self.parent()._commit_and_move(editor, 1, 0, commit_at_edge=True)
            return True
        if key in ARROW_STEPS and event.modifiers() in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier):
            row_step, column_step = ARROW_STEPS[key]
            if column_step and not self._at_text_edge(editor, column_step):
                return super().eventFilter(editor, event)
            if editor.hasAcceptableInput():
                self.parent()._commit_and_move(editor, row_step, column_step)
            return True
        return super().eventFilter(editor, event)

    @staticmethod
    def _at_text_edge(editor: QLineEdit, step: int) -> bool:
        if editor.hasSelectedText():
            return False
        # Qt's cursor position counts UTF-16 code units.
        edge = 0 if step < 0 else len(editor.text().encode("utf-16-le")) // 2
        return editor.cursorPosition() == edge

    def setEditorData(self, editor, index) -> None:
        if not isinstance(editor, QLineEdit) or editor.isModified():
            return
        value = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if value in (AUTOMATIC, EQUAL_SEGMENTS):
            value = index.data(AUTOMATIC_PREVIEW_ROLE) or ""
        if editor.text() != str(value):
            editor.setText(str(value))
            editor.selectAll()

    def setModelData(self, editor, model, index) -> None:
        if isinstance(editor, QLineEdit):
            if index.data(Qt.ItemDataRole.EditRole) in (AUTOMATIC, EQUAL_SEGMENTS) and not editor.isModified():
                return
            model.setData(index, editor.text(), Qt.ItemDataRole.EditRole)

    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        suggestion = index.data(AUTOMATIC_PREVIEW_ROLE)
        if suggestion is not None:
            option.text = str(suggestion)
            option.font.setItalic(True)
        elif index.column() == COLUMN_INDEX["anchor_position_mm"] and option.text == EQUAL_SEGMENTS:
            option.text = ""
        if index.column() == COLUMN_INDEX["taper_type"] and TAPER_LABEL_PATTERN.fullmatch(option.text):
            option.font = self._larger_taper_font(option.font)
            color = self._taper_color(option)
            for role in (QPalette.ColorRole.Text, QPalette.ColorRole.HighlightedText):
                option.palette.setColor(role, color)

    @staticmethod
    def _larger_taper_font(base: QFont) -> QFont:
        font = QFont(base)
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() * TAPER_LABEL_SCALE)
        else:
            font.setPixelSize(round(font.pixelSize() * TAPER_LABEL_SCALE))
        return font

    @staticmethod
    def _taper_color(option: QStyleOptionViewItem) -> QColor:
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        dark = option.palette.base().color().lightness() < 128
        return QColor("#ffb0b0" if selected or dark else "#be1e2d")

    def _paint_note(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        text = " ".join(styled.text.splitlines())
        labels = tuple(TAPER_LABEL_PATTERN.finditer(text))
        if not labels:
            super().paint(painter, option, index)
            return
        widget = self.parent()
        style = widget.style()
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, styled, widget)
        rect.setRight(min(rect.right(), _preset_button_rect(styled.rect).left() - 2))
        rect.adjust(3, 0, 0, 0)
        styled.text = ""
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, widget)
        layout = QTextLayout(text, styled.font)
        text_option = QTextOption()
        text_option.setWrapMode(QTextOption.WrapMode.NoWrap)
        layout.setTextOption(text_option)
        emphasis = QTextCharFormat()
        emphasis.setFont(self._larger_taper_font(styled.font))
        emphasis.setForeground(self._taper_color(styled))
        formats = []
        for label in labels:
            run = QTextLayout.FormatRange()
            run.start = len(text[:label.start()].encode("utf-16-le")) // 2
            run.length = len(label.group())
            run.format = emphasis
            formats.append(run)
        layout.setFormats(formats)
        layout.beginLayout()
        line = layout.createLine()
        line.setLineWidth(rect.width())
        layout.endLayout()
        selected = bool(styled.state & QStyle.StateFlag.State_Selected)
        role = QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        painter.save()
        painter.setClipRect(rect, Qt.ClipOperation.IntersectClip)
        painter.setPen(styled.palette.color(role))
        layout.draw(painter, QPointF(rect.left(), rect.top() + (rect.height() - line.height()) / 2))
        painter.restore()

    def updateEditorGeometry(self, editor, option, index) -> None:
        editor.setGeometry(option.rect)

    def paint(self, painter, option, index):
        if index.column() == PROFILE_COLUMN:
            super().paint(painter, option, index)
            return
        spec = COLUMN_SPECS[index.column()]
        item = self.parent().item(index.row(), index.column())
        background = (
            option.palette.alternateBase()
            if index.row() % 2
            else option.palette.base()
        )
        if option.state & QStyle.StateFlag.State_Selected:
            background = option.palette.highlight()
        if item is not None and not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            painter.fillRect(option.rect, background)
            return
        if spec.kind == "check":
            painter.save()
            painter.fillRect(option.rect, background)
            control = QStyleOptionButton()
            control.initFrom(self.parent())
            control.rect = QRect(
                option.rect.center().x() - 8,
                option.rect.center().y() - 8,
                16,
                16,
            )
            control.state = QStyle.StateFlag.State_Enabled | (
                QStyle.StateFlag.State_On
                if item is not None and item.checkState() == Qt.CheckState.Checked
                else QStyle.StateFlag.State_Off
            )
            self.parent().style().drawControl(
                QStyle.ControlElement.CE_CheckBox,
                control,
                painter,
                self.parent(),
            )
            painter.restore()
            return
        if spec.key == "source_note":
            self._paint_note(painter, option, index)
        else:
            super().paint(painter, option, index)
        if spec.options:
            button = QStyleOption()
            button.initFrom(self.parent())
            button.rect = _preset_button_rect(option.rect).adjusted(4, 0, -4, 0)
            self.parent().style().drawPrimitive(
                QStyle.PrimitiveElement.PE_IndicatorArrowDown, button, painter, self.parent()
            )


class ParameterTable(QTableWidget):
    """QTableWidget with an Excel-style fill handle and multi-cell paste."""

    changed = Signal()
    rowsRequired = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(0, PROFILE_COLUMN + 1, parent)
        self._fill_source: tuple[int, int, int, int] | None = None
        self._fill_target: tuple[int, int] | None = None
        self._fill_dragging = False
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._preset_list = QListWidget(self.viewport())
        self._preset_list.setObjectName("parameterPresetList")
        self._preset_list.viewport().setAutoFillBackground(True)
        self._preset_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._preset_list.setMouseTracking(True)
        self._preset_list.hide()
        self._preset_list.itemClicked.connect(self._select_preset)
        self.currentCellChanged.connect(self._preset_list.hide)
        self.horizontalScrollBar().valueChanged.connect(self._preset_list.hide)
        self.verticalScrollBar().valueChanged.connect(self._preset_list.hide)

    def _visible_selected_range(self) -> tuple[int, int, int, int] | None:
        indexes = [index for index in self.selectionModel().selectedIndexes()
                   if index.column() != PROFILE_COLUMN and not self.isColumnHidden(index.column())]
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
        return QRect(corner.right() - 5, corner.bottom() - 5, 6, 6)

    def _edit_cell(self, row: int, column: int) -> None:
        self._preset_list.hide()
        index = self.model().index(row, column)
        if index.isValid():
            self.setCurrentIndex(index)
            self.edit(index)

    def _adjacent_cell(self, row_step: int, column_step: int) -> tuple[int, int] | None:
        row = self.currentRow()
        column = self.currentColumn()
        if row < 0 or column < 0:
            return None
        row += row_step
        column += column_step
        while 0 <= row < self.rowCount() and 0 <= column < self.columnCount():
            item = self.item(row, column)
            if (
                not self.isRowHidden(row)
                and not self.isColumnHidden(column)
                and item is not None
                and item.flags() & Qt.ItemFlag.ItemIsEnabled
            ):
                return row, column
            row += row_step
            column += column_step
        return None

    def _move_current_cell(self, row_step: int, column_step: int) -> None:
        self._preset_list.hide()
        cell = self._adjacent_cell(row_step, column_step)
        if cell is not None:
            self.clearSelection()
            self.setCurrentCell(*cell)
            self.setFocus()
            self._show_cell_menu(*cell)

    def _commit_and_move(self, editor: QLineEdit, row_step: int, column_step: int, *,
                         commit_at_edge: bool = False) -> None:
        if not commit_at_edge and self._adjacent_cell(row_step, column_step) is None:
            return
        self.commitData(editor)
        self.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)
        self._move_current_cell(row_step, column_step)

    def _show_cell_menu(self, row: int, column: int) -> None:
        self._preset_list.hide()
        item = self.item(row, column)
        if column == PROFILE_COLUMN or item is None or not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            return
        spec = COLUMN_SPECS[column]
        if not spec.options:
            return
        choices = self._preset_list
        choices.clear()
        current = item.text().strip()
        options = spec.options
        if spec.key == "anchor_length_mm":
            options = anchor_length_options(self.item(row, COLUMN_INDEX["anchor_type"]).text())
        if spec.key in AUTOMATIC_FIELDS and AUTOMATIC not in options:
            options = (AUTOMATIC,) + options
        for option in options:
            if option == "自定义":
                continue
            entry = QListWidgetItem(option, choices)
            entry.setData(Qt.ItemDataRole.UserRole, option)
            if current == option:
                choices.setCurrentItem(entry)
        if spec.key in OPTIONAL_ANCHOR_FIELDS or spec.key == "source_note":
            entry = QListWidgetItem("留空", choices)
            entry.setData(Qt.ItemDataRole.UserRole, "")
            if not current:
                choices.setCurrentItem(entry)
        if spec.kind != "enum" or "自定义" in spec.options:
            QListWidgetItem("自定义…", choices)
        rect = self.visualRect(self.model().index(row, column))
        viewport = self.viewport()
        width = min(viewport.width(), max(rect.width(), choices.sizeHintForColumn(0) + 32))
        desired_height = choices.sizeHintForRow(0) * choices.count() + 2 * choices.frameWidth()
        below = viewport.height() - rect.bottom() - 1
        above = rect.top()
        height = min(desired_height, max(above, below))
        if height <= 0:
            return
        left = max(0, min(rect.left(), viewport.width() - width))
        top = rect.bottom() + 1 if below >= height else above - height
        choices.setGeometry(left, top, width, height)
        choices.show()
        choices.raise_()

    def _select_preset(self, entry: QListWidgetItem) -> None:
        value = entry.data(Qt.ItemDataRole.UserRole)
        self._preset_list.hide()
        row, column = self.currentRow(), self.currentColumn()
        item = self.item(row, column)
        if item is None or not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            return
        if value is None:
            self._edit_cell(row, column)
        else:
            item.setText(value)

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
        self._preset_list.hide()
        if event.button() == Qt.MouseButton.LeftButton:
            position = event.position().toPoint()
            target = self.indexAt(position)
            handle = self._handle_rect()
            if not handle.isEmpty() and handle.contains(position):
                self._fill_source = self._visible_selected_range()
                self._fill_target = (target.row(), target.column()) if target.isValid() else None
                self._fill_dragging = self._fill_source is not None
                self.viewport().setCursor(Qt.CursorShape.SizeFDiagCursor)
                event.accept()
                return
            if target.isValid() and target.column() != PROFILE_COLUMN:
                item = self.item(target.row(), target.column())
                spec = COLUMN_SPECS[target.column()]
                if item is not None and item.flags() & Qt.ItemFlag.ItemIsEnabled and spec.kind == "check":
                    self.setCurrentCell(target.row(), target.column())
                    next_state = (
                        Qt.CheckState.Unchecked
                        if item.checkState() == Qt.CheckState.Checked
                        else Qt.CheckState.Checked
                    )
                    item.setCheckState(next_state)
                    event.accept()
                    return
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if target.isValid() and target == self.currentIndex():
                self._show_cell_menu(target.row(), target.column())

    def mouseDoubleClickEvent(self, event) -> None:
        target = self.indexAt(event.position().toPoint())
        if (
            event.button() == Qt.MouseButton.LeftButton and target.isValid()
            and target.column() != PROFILE_COLUMN
        ):
            spec = COLUMN_SPECS[target.column()]
            item = self.item(target.row(), target.column())
            if spec.options and item is not None and item.flags() & Qt.ItemFlag.ItemIsEditable:
                self._edit_cell(target.row(), target.column())
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def focusOutEvent(self, event) -> None:
        self._preset_list.hide()
        super().focusOutEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._fill_dragging:
            target = self.indexAt(event.position().toPoint())
            if target.isValid() and target.column() != PROFILE_COLUMN and not self.isColumnHidden(target.column()):
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
                if target.isValid() and target.column() != PROFILE_COLUMN:
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
        key = event.key()
        modifiers = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        choices = self._preset_list
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            item = self.currentItem()
            if (modifiers == Qt.KeyboardModifier.ControlModifier and item is not None
                and item.column() < PROFILE_COLUMN and COLUMN_SPECS[item.column()].kind == "check"):
                if item.flags() & Qt.ItemFlag.ItemIsEnabled and not event.isAutoRepeat():
                    item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked
                                       else Qt.CheckState.Checked)
            elif modifiers == Qt.KeyboardModifier.NoModifier and choices.isVisible():
                entry = choices.currentItem()
                if entry is not None:
                    self._select_preset(entry)
            else:
                self._move_current_cell(1, 0)
            event.accept()
            return
        if (
            key == Qt.Key.Key_Down
            and event.modifiers() == Qt.KeyboardModifier.AltModifier
            and self.currentIndex().isValid()
        ):
            self._show_cell_menu(self.currentRow(), self.currentColumn())
            event.accept()
            return
        if (
            key in ARROW_STEPS
            and modifiers == Qt.KeyboardModifier.NoModifier
            and self.state() != QAbstractItemView.State.EditingState
        ):
            row_step, column_step = ARROW_STEPS[key]
            if row_step and choices.isVisible():
                last = choices.count() - 1
                current = choices.currentRow()
                if current < 0:
                    current = -1 if row_step > 0 else last + 1
                choices.setCurrentRow(max(0, min(last, current + row_step)))
            else:
                self._move_current_cell(row_step, column_step)
            event.accept()
            return
        choices.hide()
        if event.matches(QKeySequence.StandardKey.Paste):
            self._paste_clipboard()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Delete):
            self._clear_selection()
            event.accept()
            return
        text = event.text()
        modifiers = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier
        index = self.currentIndex()
        required_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable
        if (
            text and text.isprintable() and not event.modifiers() & modifiers
            and self.state() != QAbstractItemView.State.EditingState
            and (index.flags() & required_flags) == required_flags
        ):
            # Qt delivers the original key to the editor after it is initialized.
            if self.edit(index, QAbstractItemView.EditTrigger.AnyKeyPressed, event):
                event.accept()
                return
        super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            pixel_delta = event.pixelDelta().y() or event.pixelDelta().x()
            angle_delta = event.angleDelta().y() or event.angleDelta().x()
            if pixel_delta:
                steps = max(1, round(abs(pixel_delta) / 20))
                direction = 1 if pixel_delta > 0 else -1
            elif angle_delta:
                lines = max(1, QApplication.wheelScrollLines())
                steps = max(1, round(abs(angle_delta) / 120 * lines))
                direction = 1 if angle_delta > 0 else -1
            else:
                event.ignore()
                return
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - direction * steps * bar.singleStep())
            event.accept()
            return
        super().wheelEvent(event)

    def inputMethodEvent(self, event: QInputMethodEvent) -> None:
        index = self.currentIndex()
        editable = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable
        if (event.commitString() and not event.preeditString()
            and self.state() != QAbstractItemView.State.EditingState
            and (index.flags() & editable) == editable):
            # A commit without preedit can arrive before an editor has focus.
            self._preset_list.hide()
            if self.edit(index, QAbstractItemView.EditTrigger.AllEditTriggers, None):
                editor = self.indexWidget(index)
                if isinstance(editor, QLineEdit):
                    QApplication.sendEvent(editor, event)
                    event.accept()
                    return
        super().inputMethodEvent(event)

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
        while start_column < PROFILE_COLUMN and self.isColumnHidden(start_column):
            start_column += 1
        if start_column >= PROFILE_COLUMN:
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
                    for column in range(start_column, PROFILE_COLUMN)
                    if not self.isColumnHidden(column)
                ]
                all_columns = list(range(start_column, PROFILE_COLUMN))
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
                            item.setText("")
                        elif item.flags() & Qt.ItemFlag.ItemIsEditable or (
                            spec.key == "anchor_spacing_mm" and item.flags() & Qt.ItemFlag.ItemIsEnabled
                            and self.item(row, COLUMN_INDEX["anchor_position_mm"]).text() != EQUAL_SEGMENTS
                        ):
                            item.setText(value.strip())
                    column_index += 1
        finally:
            self.blockSignals(False)
        self.changed.emit()


class StandardWindow(MainWindow):
    def __init__(self):
        self._preview_pdf: tuple[str | None, bytes] | None = None
        self._pdf_page_cache = PdfPageCache()
        self._preview_cache_pages = None
        self._drawing_generator: DrawingGenerator | None = None
        self._reference_key = None
        self._focused_module_id: str | None = None
        self._preview_images = OrderedDict()
        self._preview_jobs = {}
        self._preview_pool = None
        self._shown_preview_page = None
        self._preview_workers_failed = False
        self._drawing_dirty = False
        self._full_window_active = False
        self._full_window_layout_state: dict[str, object] | None = None
        self._settings = QSettings("EventHorizon", "RefracDraft Standard")
        self._history_ready = False
        self._history_restoring = False
        self._undo_stack: list[TableState] = []
        self._redo_stack: list[TableState] = []
        self._history_state: TableState | None = None
        super().__init__()
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(35)
        self._preview_timer.timeout.connect(self._collect_preview_pages)
        self._exit_full_window_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._exit_full_window_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._exit_full_window_shortcut.activated.connect(self._exit_preview_full_window)
        self._exit_full_window_shortcut.setEnabled(False)
        self._generate_shortcut = QShortcut(QKeySequence("F5"), self)
        self._generate_shortcut.activated.connect(self.generate)
        self._history_ready = True
        self._reset_history()
        geometry = self._settings.value("window/geometry", QByteArray())
        if isinstance(geometry, QByteArray) and not geometry.isEmpty():
            self.restoreGeometry(geometry)
        split = self._settings.value("window/output_splitter", QByteArray())
        if isinstance(split, QByteArray) and not split.isEmpty():
            self.output_splitter.restoreState(split)
        self.stay_on_top_action.setChecked(self._settings.value("window/stay_on_top", False, type=bool))
        self.setWindowTitle(f"RefracDraft Standard v{app_version()} — 模块加工图生成器")
        self.statusBar().showMessage("修改参数后点击「预览」；可拖动选区右下角批量填充。")

    def _build_ui(self) -> None:
        self._row_bases: list[RowBase] = []
        self._updating_table = False

        toolbar = self.main_toolbar = QToolBar("主工具栏")
        self.addToolBar(toolbar)
        for label, callback, shortcut in (
            ("新建", self.new_project, "Ctrl+N"),
            ("打开", self.open_json, "Ctrl+O"),
            ("导入 Excel", self.import_excel, "Ctrl+I"),
            ("保存", self.save_json, "Ctrl+S"),
        ):
            action = QAction(label, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            toolbar.addAction(action)
        toolbar.addSeparator()
        self.undo_action = QAction("撤销", self)
        self.undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        self.undo_action.triggered.connect(self.undo)
        toolbar.addAction(self.undo_action)
        self.redo_action = QAction("重做", self)
        self.redo_action.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self.redo_action.triggered.connect(self.redo)
        toolbar.addAction(self.redo_action)
        toolbar.addSeparator()
        self.stay_on_top_action = QAction("置顶", self)
        self.stay_on_top_action.setCheckable(True)
        self.stay_on_top_action.setToolTip("保持主窗口在其他窗口上方")
        self.stay_on_top_action.toggled.connect(self._set_stay_on_top)
        toolbar.addAction(self.stay_on_top_action)
        about = QAction("关于", self)
        about.triggered.connect(self._show_about)
        toolbar.addAction(about)

        splitter = self.main_splitter = QSplitter(Qt.Orientation.Vertical)

        parameter_panel = self.parameter_panel = QWidget()
        parameter_layout = QVBoxLayout(parameter_panel)
        parameter_layout.setContentsMargins(8, 8, 8, 8)
        header = QHBoxLayout()
        title = QLabel("模块参数")
        title.setStyleSheet("font-weight: 600;")
        header.addWidget(title)
        add_button = QPushButton("添加模块")
        remove_button = QPushButton("删除模块")
        add_button.clicked.connect(lambda _checked=False: self._add_module())
        remove_button.clicked.connect(lambda _checked=False: self._remove_selected_module())
        header.addWidget(add_button)
        header.addWidget(remove_button)
        self.row_count_label = QLabel("0 个模块")
        header.addWidget(self.row_count_label)
        header.addStretch(1)
        parameter_layout.addLayout(header)

        self.parameter_table = ParameterTable()
        self.module_table = self.parameter_table
        self.tables = {"modules": self.parameter_table}
        table = self.parameter_table
        table.setObjectName("moduleParameterTable")
        table.setHorizontalHeaderLabels([
            "插针长度" if spec.key == "anchor_length_mm" else spec.label for spec in COLUMN_SPECS
        ] + ["异形"])
        table.setColumnWidth(PROFILE_COLUMN, 78)
        table.horizontalHeader().moveSection(PROFILE_COLUMN, COLUMN_INDEX["thickness_mm"] + 1)
        table.setItemDelegate(ParameterDelegate(table))
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.setShowGrid(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.AnyKeyPressed)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setMinimumSectionSize(38)
        table.verticalHeader().setDefaultSectionSize(31)
        table.verticalHeader().setMinimumWidth(34)
        table.setMinimumHeight(185)
        for column, spec in enumerate(COLUMN_SPECS):
            width = COMPACT_COLUMN_WIDTHS.get(spec.key, spec.width)
            table.setColumnWidth(column, max(width, table.horizontalHeader().sectionSizeHint(column)))
            header_item = table.horizontalHeaderItem(column)
            if header_item is not None:
                header_item.setToolTip(header_item.text())
                header_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        table.horizontalHeader().sectionDoubleClicked.connect(self._edit_whole_column)
        table.itemChanged.connect(self._table_item_changed)
        table.currentCellChanged.connect(self._current_cell_changed)
        table.cellClicked.connect(self._locate_module_from_table)
        table.horizontalHeaderItem(COLUMN_INDEX["module_id"]).setToolTip("点击编号可定位到图纸中的对应模块")
        table.changed.connect(self._table_bulk_changed)
        table.rowsRequired.connect(self._ensure_row_count)
        parameter_layout.addWidget(table)

        preview_panel = self.preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        preview_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.output_splitter = preview_splitter
        preview_splitter.setChildrenCollapsible(False)
        preview_splitter.setHandleWidth(7)

        output_panel = self.output_panel = QFrame()
        output_panel.setObjectName("outputPanel")
        output_panel.setMinimumWidth(245)
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
        self.open_directory_button = QPushButton("打开")
        self.open_directory_button.setFixedWidth(58)
        self.open_directory_button.setToolTip("在文件管理器中打开工作目录")
        self.open_directory_button.clicked.connect(self._open_output_directory)
        directory_row.addWidget(self.output_directory_edit, 1)
        directory_row.addWidget(self.browse_directory_button)
        directory_row.addWidget(self.open_directory_button)
        output_layout.addLayout(directory_row)

        output_layout.addWidget(QLabel("自定义文件名"))
        self.output_filename_edit = QLineEdit(_default_filename_stem())
        self.output_filename_edit.setPlaceholderText("不含扩展名")
        output_layout.addWidget(self.output_filename_edit)
        self.print_filename_check = QCheckBox("图框左下角显示文件名")
        self.print_filename_check.setChecked(self._settings.value("output/print_filename", False, type=bool))
        self.print_filename_check.toggled.connect(self._filename_label_changed)
        self.print_filename_check.toggled.connect(self._save_output_settings)
        output_layout.addWidget(self.print_filename_check)

        self.output_path_label = QLabel()
        self.output_path_label.setProperty("role", "fieldLabel")
        self.output_path_label.setWordWrap(True)
        output_layout.addWidget(self.output_path_label)
        output_layout.addStretch(1)

        self.preview_button = QPushButton("预览")
        self.preview_button.setProperty("primary", True)
        self.preview_button.setToolTip("生成或更新图纸预览 (F5)")
        self.preview_button.clicked.connect(self.generate)
        output_layout.addWidget(self.preview_button)

        self.output_dxf_button = QPushButton("导出 DXF")
        self.output_pdf_button = QPushButton("导出 PDF")
        self.output_dxf_button.setProperty("primary", True)
        self.output_pdf_button.setProperty("primary", True)
        self.output_dxf_button.clicked.connect(self.export_dxf_file)
        self.output_pdf_button.clicked.connect(self.export_pdf_file)
        output_layout.addWidget(self.output_dxf_button)
        output_layout.addWidget(self.output_pdf_button)
        self.output_project_button = QPushButton("导出完整项目")
        self.output_project_button.setProperty("primary", True)
        self.output_project_button.clicked.connect(self.export_project_file)
        output_layout.addWidget(self.output_project_button)

        preview_canvas = self.preview_canvas = QWidget()
        preview_canvas.setMinimumWidth(240)
        canvas_layout = QGridLayout(preview_canvas)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        self.preview = DrawingPreview()
        self.preview.page_step_requested.connect(self._preview_page_step)
        self.preview.zoom_requested.connect(self._preview_zoom)
        self.preview.module_clicked.connect(self._locate_module_from_preview)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        canvas_layout.addWidget(self.preview, 0, 0)

        preview_title = QLabel("图纸预览")
        preview_title.setObjectName("previewTitle")
        preview_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        canvas_layout.addWidget(
            preview_title, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )

        page_controls = self.page_controls = QFrame()
        page_controls.setObjectName("previewPageControls")
        page_row = QHBoxLayout(page_controls)
        page_row.setContentsMargins(9, 5, 9, 5)
        page_row.addWidget(QLabel("预览页"))
        self.page_spin = PageSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.valueChanged.connect(self._show_selected_page)
        page_row.addWidget(self.page_spin)
        preview_tools = QWidget()
        preview_tools.setObjectName("previewTools")
        tools_layout = QHBoxLayout(preview_tools)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.setSpacing(6)
        tools_layout.addWidget(page_controls)
        self.full_window_button = QPushButton()
        self.full_window_button.setObjectName("previewFullWindowButton")
        self.full_window_button.setFixedSize(32, 30)
        self.full_window_button.setShortcut(QKeySequence("F11"))
        self.full_window_button.clicked.connect(self._toggle_preview_full_window)
        self._update_full_window_button()
        tools_layout.addWidget(self.full_window_button)
        canvas_layout.addWidget(
            preview_tools, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
        )
        page_controls.hide()

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

        remembered_directory = str(self._settings.value("output/last_directory", ""))
        preferred_directory = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        )
        output_directory = (
            remembered_directory
            if remembered_directory and Path(remembered_directory).expanduser().is_dir()
            else preferred_directory or str(Path.cwd())
        )
        self.output_directory_edit.setText(output_directory)
        self.output_directory_edit.textChanged.connect(self._update_output_preview)
        self.output_filename_edit.textChanged.connect(self._update_output_preview)
        self.output_filename_edit.textChanged.connect(self._filename_label_changed)
        self.output_directory_edit.editingFinished.connect(self._save_output_settings)
        self._update_output_preview()

        self.setStyleSheet(
            "QTableWidget#moduleParameterTable {"
            " gridline-color: palette(mid); alternate-background-color: palette(alternate-base); }"
            "QTableWidget#moduleParameterTable QHeaderView::section {"
            " padding: 4px 6px; background-color: palette(button); color: palette(button-text);"
            " border: 0; border-right: 1px solid palette(mid); border-bottom: 1px solid palette(mid); }"
            "QFrame#outputPanel { border: 1px solid palette(mid); border-radius: 4px; }"
            "QLabel#previewTitle, QFrame#previewPageControls {"
            " background: palette(window); color: palette(window-text);"
            " border: 1px solid palette(mid); border-radius: 4px; margin: 5px; }"
            "QLabel#previewTitle { padding: 4px 7px; }"
            "QListWidget#parameterPresetList {"
            " background-color: palette(base); color: palette(text);"
            " border: 2px solid #5688c7; }"
            "QListWidget#parameterPresetList::item {"
            " background-color: palette(base); color: palette(text); padding: 4px 7px; }"
            "QListWidget#parameterPresetList::item:hover { background: palette(alternate-base); }"
            "QListWidget#parameterPresetList::item:selected {"
            " background: palette(highlight); color: palette(highlighted-text); }"
            "QPushButton[primary='true'] { background: #2f6fde; color: white;"
            " border: 1px solid #245bb8; border-radius: 4px; padding: 6px 10px; }"
            "QPushButton[primary='true']:hover { background: #3b7bea; }"
            "QPushButton#previewFullWindowButton {"
            " background: palette(window); color: palette(window-text);"
            " border: 1px solid palette(mid); border-radius: 4px; padding: 5px 10px; }"
            "QPushButton#previewFullWindowButton:hover { background: palette(alternate-base); }"
            "QPushButton#previewFullWindowButton:pressed { background: palette(mid); }"
            "QLabel[role='fieldLabel'] { font-size: 11px; color: palette(mid); }"
        )

    def _add_empty_rows(self) -> None:
        self._add_module()

    def _set_stay_on_top(self, enabled: bool) -> None:
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if visible:
            self.show()
        self._settings.setValue("window/stay_on_top", enabled)

    def _update_full_window_button(self) -> None:
        if not hasattr(self, "full_window_button"):
            return
        self.full_window_button.setIcon(_full_window_icon(self.full_window_button, self._full_window_active))
        self.full_window_button.setAccessibleName("还原窗口" if self._full_window_active else "全窗口")
        self.full_window_button.setToolTip(
            "还原参数区和输出设置 (F11 / Esc)"
            if self._full_window_active
            else "在当前窗口内铺满图纸预览 (F11)"
        )

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self._update_full_window_button()

    def _mark_preview_stale(self) -> None:
        self._drawing_dirty = True

    def _toggle_preview_full_window(self) -> None:
        if self._full_window_active:
            self._exit_preview_full_window()
        else:
            self._enter_preview_full_window()

    def _enter_preview_full_window(self) -> None:
        if self._full_window_active:
            return
        self._full_window_layout_state = {
            "toolbar": not self.main_toolbar.isHidden(),
            "status": not self.statusBar().isHidden(),
            "parameter": not self.parameter_panel.isHidden(),
            "output": not self.output_panel.isHidden(),
            "main_splitter": self.main_splitter.saveState(),
            "output_splitter": self.output_splitter.saveState(),
        }
        self._full_window_active = True
        self.main_toolbar.hide()
        self.statusBar().hide()
        self.parameter_panel.hide()
        self.output_panel.hide()
        self.main_splitter.setSizes([0, 1])
        self.output_splitter.setSizes([0, 1])
        self._exit_full_window_shortcut.setEnabled(True)
        self._update_full_window_button()
        self.preview.setFocus()
        QTimer.singleShot(0, self.preview.fit_current)

    def _exit_preview_full_window(self) -> None:
        if not self._full_window_active:
            return
        state = self._full_window_layout_state or {}
        self._full_window_active = False
        self._exit_full_window_shortcut.setEnabled(False)
        self.parameter_panel.setVisible(bool(state.get("parameter", True)))
        self.output_panel.setVisible(bool(state.get("output", True)))
        self.main_toolbar.setVisible(bool(state.get("toolbar", True)))
        self.statusBar().setVisible(bool(state.get("status", True)))
        main_splitter_state = state.get("main_splitter")
        if isinstance(main_splitter_state, QByteArray):
            self.main_splitter.restoreState(main_splitter_state)
        output_splitter_state = state.get("output_splitter")
        if isinstance(output_splitter_state, QByteArray):
            self.output_splitter.restoreState(output_splitter_state)
        self._full_window_layout_state = None
        self._update_full_window_button()
        QTimer.singleShot(0, self.preview.fit_current)

    def _show_about(self) -> None:
        dialog = AboutDialog(self)
        dialog.exec()
        dialog.deleteLater()

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
            self._save_output_settings()

    def _open_output_directory(self) -> None:
        directory = self._default_output_directory()
        if not directory.is_dir():
            QMessageBox.warning(self, "无法打开工作目录", f"目录不存在：\n{directory}")
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory.absolute()))):
            QMessageBox.warning(self, "无法打开工作目录", str(directory))

    def _save_output_settings(self, *_args) -> None:
        if not hasattr(self, "output_directory_edit"):
            return
        self._settings.setValue(
            "output/last_directory", self.output_directory_edit.text().strip()
        )
        self._settings.setValue("output/print_filename", self.print_filename_check.isChecked())

    def _filename_label(self) -> str:
        return self._filename_stem() if self.print_filename_check.isChecked() else ""

    def _filename_label_changed(self, *_args) -> None:
        if self.drawing_document and self.drawing_document.filename_label != self._filename_label():
            self._mark_preview_stale()

    def closeEvent(self, event) -> None:
        if self._full_window_active:
            self._exit_preview_full_window()
        self._reset_preview_pdf()
        if self._preview_pool is not None:
            self._preview_pool.shutdown(wait=False, cancel_futures=True)
            self._preview_pool = None
        self._save_output_settings()
        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.setValue("window/output_splitter", self.output_splitter.saveState())
        super().closeEvent(event)

    def _filename_stem(self) -> str:
        value = self.output_filename_edit.text().strip() if hasattr(self, "output_filename_edit") else ""
        if value.lower().endswith((".dxf", ".pdf", ".json", ".xlsx", ".zip")):
            value = Path(value).stem
        value = re.sub(r'[<>:"/\\|?*]+', "-", value).strip(" .")
        return value or _default_filename_stem()

    def _project_save_path(self) -> Path:
        self._save_output_settings()
        return self._default_output_directory() / f"{self._filename_stem()}.json"

    def _update_output_preview(self, *_args) -> None:
        if not hasattr(self, "output_path_label"):
            return
        directory = self.output_directory_edit.text().strip() or "当前工作目录"
        stem = self._filename_stem()
        self.output_path_label.setText(f"{directory}\n{stem}.json  /  {stem}.xlsx  /  {stem}.dxf  /  {stem}.pdf")

    def _output_target(self, suffix: str) -> Path | None:
        self._save_output_settings()
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

    def _write_row(self, row: int, values: dict[str, str | bool], profile: BoardFaceProfile | None) -> None:
        table = self.parameter_table
        for column, spec in enumerate(COLUMN_SPECS):
            value = values.get(spec.key, DEFAULT_ROW.get(spec.key, ""))
            item = QTableWidgetItem()
            if spec.kind == "check":
                if isinstance(value, str):
                    checked = value.strip().lower() in {"1", "是", "yes", "true", "y"}
                else:
                    checked = bool(value)
                item.setText("")
                item.setFlags(
                    Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if spec.key in {"show_upper_board", "show_lower_board"}:
                    item.setToolTip(f"勾选后绘制{spec.label}，同时保留夹板面总图。")
            else:
                item.setText("" if value is None else str(value))
                item.setFlags(
                    Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsEditable
                )
                item.setTextAlignment(NOTE_ALIGNMENT if spec.key == "source_note" else Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, column, item)
        button = QPushButton()
        button.setObjectName("boardFaceProfileButton")
        self._set_profile_button(button, profile)
        index = QPersistentModelIndex(table.model().index(row, PROFILE_COLUMN))
        button.clicked.connect(lambda: self._edit_board_face(index.row(), button))
        table.setCellWidget(row, PROFILE_COLUMN, button)

    @staticmethod
    def _set_profile_button(button: QPushButton, profile: BoardFaceProfile | None) -> None:
        button.setText("异形 ✓" if profile is not None else "非异形")
        button.setToolTip("编辑夹板面、正面和侧面的切口")

    def _edit_board_face(self, row: int, button: QPushButton) -> None:
        if not 0 <= row < len(self._row_bases):
            return
        self.parameter_table.setCurrentCell(row, COLUMN_INDEX["module_id"])
        values = self._sheet_values(row)
        try:
            length, thickness = standard_board_face_bounds(values)
            geometry = (
                standard_taper_geometry(str(values["taper_type"]), str(values["module_id"]))
                if values["taper_enabled"] else GeometryType.NORMAL
            )
            height_key = "big_head_mm" if values["taper_enabled"] else "expansion_length_mm"
            height = float(str(values[height_key]).replace(",", ""))
            if not 0 < height < float("inf"):
                raise ValueError("请填写有效的膨胀长度或大头尺寸")
            options = {}
            if geometry != GeometryType.NORMAL:
                small = float(str(values["small_head_mm"]).replace(",", ""))
                if not 0 < small < height:
                    raise ValueError("小头尺寸须为正数且小于大头")
                if geometry == GeometryType.FRONT_TAPER:
                    options = {"front_left_height_mm": height, "front_right_height_mm": small}
                else:
                    options = {"side_length_mm": thickness, "side_left_height_mm": height, "side_right_height_mm": small}
            module = ModuleParameters(
                module_id=str(values["module_id"]) or f"第 {row + 1} 行",
                geometry_type=geometry, front_width_mm=length, front_height_mm=height,
                board_face_width_mm=length, board_face_height_mm=thickness, **options,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "请先填写有效的外尺寸", str(exc))
            return
        base = self._row_bases[row]
        dialog = BoardFaceDialog(module, base.profile, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.profile != base.profile:
            self._row_bases[row] = replace(base, profile=dialog.profile)
            self._set_profile_button(button, dialog.profile)
            self._record_history()
            self.statusBar().showMessage("异形切口已修改，点击「预览」更新图纸。")
        dialog.deleteLater()
        self.activateWindow()
        self.parameter_table.setFocus(Qt.FocusReason.OtherFocusReason)

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
        if source is not None:
            module, board, anchor = source
            fallback = row_values_from_models(module, board, anchor)
            automatic = self.project.standard_auto_fields.get(module.module_id)
            if automatic is None:
                automatic = legacy_automatic_fields(fallback)
            values = {**fallback, **dict.fromkeys((key for key in AUTOMATIC_FIELDS if key in automatic), AUTOMATIC)}
            if self.project.standard_link_version < STANDARD_LINK_VERSION and "source_note" not in automatic:
                values["source_note"] = legacy_source_note(values)
            profile = module.board_face_outline
            base = RowBase(source, profile if isinstance(profile, BoardFaceProfile) else None, fallback)
        elif table.rowCount():
            values = self._sheet_values(table.rowCount() - 1)
            used = {
                str(self._sheet_values(row).get("module_id", "")).strip()
                for row in range(table.rowCount())
            }
            base_id = str(values.get("module_id", "M1")).strip() or "M1"
            values["module_id"] = self._next_unique_module_id(base_id, used)
            previous = self._row_bases[-1]
            base = RowBase(profile=previous.profile, automatic_fallback=previous.automatic_fallback)
        else:
            values = dict(DEFAULT_ROW)
            values.update(dict.fromkeys(AUTOMATIC_FIELDS, AUTOMATIC))
            base = RowBase()

        row = table.rowCount()
        self._updating_table = True
        table.blockSignals(True)
        try:
            table.insertRow(row)
            self._write_row(row, values, base.profile)
            self._row_bases.append(base)
        finally:
            table.blockSignals(False)
            self._updating_table = False
        self._update_row_count()
        self._update_conditional_states()
        table.clearSelection()
        table.setCurrentCell(row, 0)
        self._record_history()
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
        self._record_history()

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
        if item is None:
            return ""
        suggestion = item.data(AUTOMATIC_PREVIEW_ROLE)
        return str(item.text() if suggestion is None else suggestion).strip()

    def _cell_bool(self, row: int, key: str) -> bool:
        item = self.parameter_table.item(row, COLUMN_INDEX[key])
        return item is not None and item.checkState() == Qt.CheckState.Checked

    def _sync_expansion_length(self, row: int) -> None:
        if self._cell_bool(row, "taper_enabled"):
            big = self._cell_text(row, "big_head_mm")
            if big:
                self._set_cell_text(row, "expansion_length_mm", big)

    def _set_cell_enabled(self, row: int, key: str, enabled: bool, *, editable: bool = True) -> None:
        item = self.parameter_table.item(row, COLUMN_INDEX[key])
        if item is None:
            return
        previous = flags = item.flags()
        if enabled:
            flags |= Qt.ItemFlag.ItemIsEnabled
            if editable and COLUMN_BY_KEY[key].kind != "check":
                flags |= Qt.ItemFlag.ItemIsEditable
            else:
                flags &= ~Qt.ItemFlag.ItemIsEditable
        else:
            flags &= ~Qt.ItemFlag.ItemIsEnabled
            flags &= ~Qt.ItemFlag.ItemIsEditable
        if flags != previous:
            item.setFlags(flags)

    def _update_conditional_states(self) -> None:
        table = self.parameter_table
        if table.rowCount() == 0:
            for key in (*TAPER_SETTING_KEYS, *BOARD_SETTING_KEYS, *ANCHOR_SETTING_KEYS):
                table.setColumnHidden(COLUMN_INDEX[key], True)
            return
        any_taper = any(self._cell_bool(row, "taper_enabled") for row in range(table.rowCount()))
        any_board = any(self._cell_bool(row, "board_exists") for row in range(table.rowCount()))
        any_anchor = any(self._cell_bool(row, "anchor_enabled") for row in range(table.rowCount()))
        any_diamond = any(
            self._cell_bool(row, "anchor_enabled") and self._cell_text(row, "anchor_type") in DIAMOND_ANCHOR_TYPES
            for row in range(table.rowCount())
        )
        any_welded = any(
            self._cell_bool(row, "anchor_enabled") and self._cell_text(row, "anchor_type") in WELDED_ANCHOR_TYPES
            for row in range(table.rowCount())
        )
        any_pin_anchor = any(
            self._cell_bool(row, "anchor_enabled") and self._cell_text(row, "anchor_type") not in DIAMOND_ANCHOR_TYPES
            for row in range(table.rowCount())
        )
        for key in TAPER_SETTING_KEYS:
            table.setColumnHidden(COLUMN_INDEX[key], not any_taper)
        for key in BOARD_SETTING_KEYS:
            table.setColumnHidden(COLUMN_INDEX[key], not any_board)
        for key in ANCHOR_SETTING_KEYS:
            table.setColumnHidden(COLUMN_INDEX[key], not any_anchor)
        table.setColumnHidden(COLUMN_INDEX["embedment_depth_mm"], not any_diamond)
        table.setColumnHidden(COLUMN_INDEX["pin_diameter_mm"], not any_pin_anchor)
        table.setColumnHidden(COLUMN_INDEX["bolt_exposure_mm"], not any_welded)

        was_updating = self._updating_table
        self._updating_table = True
        try:
            for row in range(table.rowCount()):
                taper = self._cell_bool(row, "taper_enabled")
                board = self._cell_bool(row, "board_exists")
                anchor = self._cell_bool(row, "anchor_enabled")
                anchor_type = self._cell_text(row, "anchor_type")
                is_diamond = anchor_type in DIAMOND_ANCHOR_TYPES
                taper_item = table.item(row, COLUMN_INDEX["taper_type"])
                taper_item.setText(standard_taper_label(taper_item.text()))
                position_item = table.item(row, COLUMN_INDEX["anchor_position_mm"])
                equal = anchor and position_item.text() == EQUAL_SEGMENTS
                self._set_cell_enabled(row, "expansion_length_mm", not taper)
                for key in TAPER_SETTING_KEYS:
                    self._set_cell_enabled(row, key, taper)
                self._set_cell_enabled(row, "board_material", board)
                self._set_cell_enabled(row, "show_upper_board", board)
                self._set_cell_enabled(row, "show_lower_board", board)
                for key in ANCHOR_SETTING_KEYS:
                    enabled = anchor and not (key == "pin_diameter_mm" and is_diamond)
                    enabled = enabled and not (key == "embedment_depth_mm" and not is_diamond)
                    enabled = enabled and not (key == "bolt_exposure_mm" and anchor_type not in WELDED_ANCHOR_TYPES)
                    self._set_cell_enabled(row, key, enabled, editable=not (equal and key == "anchor_spacing_mm"))
                if taper:
                    self._sync_expansion_length(row)
                values = self._sheet_values(row)
                spacing_item = table.item(row, COLUMN_INDEX["anchor_spacing_mm"])
                layout = equal_segment_values(values) if equal else None
                for item, value in zip((position_item, spacing_item), layout or (None, None)):
                    item.setData(AUTOMATIC_PREVIEW_ROLE, f"{value:g}" if value is not None else None)
                position_item.setToolTip("首个锚固件在第一等份的中心" if equal else "")
                spacing_item.setToolTip("均分间距 = 模块长度 ÷ 锚固件数量" if equal else "")
                suggestions = resolve_automatic_values(values, self._row_bases[row].automatic_fallback)
                for key in AUTOMATIC_FIELDS:
                    item = table.item(row, COLUMN_INDEX[key])
                    if key in EMPTY_SELECTS_AUTOMATIC and not item.text().strip():
                        item.setText(AUTOMATIC)
                    suggestion = suggestions.get(key)
                    item.setData(AUTOMATIC_PREVIEW_ROLE, suggestion)
                    if key == "source_note":
                        item.setToolTip(
                            (suggestion or "随大小头类型和锚固件参数自动填写") if key in suggestions else item.text()
                        )
                    else:
                        item.setToolTip(f"自动计算 · {suggestion or '待填写参数'}" if key in suggestions else "")
        finally:
            self._updating_table = was_updating

    def _capture_table_state(self) -> TableState:
        rows = tuple(self._sheet_values(row) for row in range(self.parameter_table.rowCount()))
        bases = list(self._row_bases[: self.parameter_table.rowCount()])
        while len(bases) < len(rows):
            bases.append(RowBase())
        return TableState(rows=rows, bases=tuple(bases))

    def _reset_history(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._history_state = self._capture_table_state()
        self._refresh_history_actions()

    def _record_history(self) -> None:
        if not self._history_ready or self._history_restoring:
            return
        current = self._capture_table_state()
        if self._history_state is None:
            self._history_state = current
            return
        if current == self._history_state:
            return
        self._mark_preview_stale()
        self._undo_stack.append(self._history_state)
        if len(self._undo_stack) > 100:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._history_state = current
        self._refresh_history_actions()

    def _refresh_history_actions(self) -> None:
        if hasattr(self, "undo_action"):
            self.undo_action.setEnabled(bool(self._undo_stack))
        if hasattr(self, "redo_action"):
            self.redo_action.setEnabled(bool(self._redo_stack))

    def _restore_table_state(self, state: TableState) -> None:
        table = self.parameter_table
        self._history_restoring = True
        self._updating_table = True
        table.blockSignals(True)
        try:
            table.setRowCount(0)
            self._row_bases.clear()
            for row, values in enumerate(state.rows):
                table.insertRow(row)
                base = state.bases[row]
                self._write_row(row, values, base.profile)
                self._row_bases.append(base)
        finally:
            table.blockSignals(False)
            self._updating_table = False
            self._history_restoring = False
        self._update_row_count()
        self._update_conditional_states()
        self._history_state = state
        self._mark_preview_stale()
        self._refresh_history_actions()

    def undo(self) -> None:
        if not self._undo_stack:
            return
        current = self._capture_table_state()
        previous = self._undo_stack.pop()
        self._redo_stack.append(current)
        self._restore_table_state(previous)
        self.statusBar().showMessage("已撤销参数修改。")

    def redo(self) -> None:
        if not self._redo_stack:
            return
        current = self._capture_table_state()
        following = self._redo_stack.pop()
        self._undo_stack.append(current)
        self._restore_table_state(following)
        self.statusBar().showMessage("已重做参数修改。")

    def _edit_whole_column(self, column: int) -> None:
        if column < 0 or column >= len(COLUMN_SPECS):
            return
        table = self.parameter_table
        if table.isColumnHidden(column) or table.rowCount() == 0:
            return
        spec = COLUMN_SPECS[column]
        if spec.kind == "check":
            items = [table.item(row, column) for row in range(table.rowCount())]
            target = not all(
                item is not None and item.checkState() == Qt.CheckState.Checked
                for item in items
            )
            table.blockSignals(True)
            try:
                for item in items:
                    if item is None:
                        continue
                    item.setCheckState(
                        Qt.CheckState.Checked if target else Qt.CheckState.Unchecked
                    )
                    item.setText("")
            finally:
                table.blockSignals(False)
            self._table_bulk_changed()
            return

        dialog = QInputDialog(self)
        dialog.setWindowTitle(f"修改整列 - {spec.label}")
        options = spec.options
        if spec.key in AUTOMATIC_FIELDS and AUTOMATIC not in options:
            options = (AUTOMATIC,) + options
        hint = "，".join(options) if options else "输入任意自定义内容"
        dialog.setLabelText(f"将第 {column + 1} 列设置为：\n{hint}")
        if options:
            dialog.setComboBoxItems(list(options))
            dialog.setComboBoxEditable(True)
        table.blockSignals(True)
        try:
            values = {
                table.item(row, column).text().strip()
                for row in range(table.rowCount())
                if table.item(row, column) is not None
            }
        finally:
            table.blockSignals(False)
        if len(values) == 1:
            dialog.setTextValue(next(iter(values)))
        if dialog.exec() != QInputDialog.DialogCode.Accepted:
            return
        value = dialog.textValue().strip()
        if not value:
            return
        table.blockSignals(True)
        try:
            for row in range(table.rowCount()):
                item = table.item(row, column)
                if item is not None:
                    item.setText(value)
        finally:
            table.blockSignals(False)
        self._table_bulk_changed()

    def _table_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_table or item.row() >= len(self._row_bases):
            return
        spec = COLUMN_SPECS[item.column()]
        self._updating_table = True
        try:
            if spec.kind == "check":
                checked = item.checkState() == Qt.CheckState.Checked
                item.setText("")
            if spec.key in {"taper_enabled", "big_head_mm"}:
                self._sync_expansion_length(item.row())
        finally:
            self._updating_table = False
        self._update_conditional_states()
        self._record_history()
        self.statusBar().showMessage("参数已修改，点击「预览」更新图纸。")

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
        self._record_history()
        self.statusBar().showMessage("参数已修改，点击「预览」更新图纸。")

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

    def _module_page(self, module_id: str | None) -> int | None:
        if self.drawing_document and module_id:
            for index, page in enumerate(self.drawing_document.pages, 1):
                if any(placed.drawing.module_id == module_id for placed in page.modules):
                    return index
        return None

    def _locate_module_from_table(self, row: int, column: int) -> None:
        if column != COLUMN_INDEX["module_id"]:
            return
        if QApplication.keyboardModifiers() != Qt.KeyboardModifier.NoModifier:
            return
        module_id = self._cell_text(row, "module_id").strip()
        page = self._module_page(module_id)
        if page is None:
            self.statusBar().showMessage("当前预览没有此模块，请先生成或更新预览。")
            return
        self._focused_module_id = module_id
        self.preview.highlight_module(module_id)
        self.page_spin.setValue(page)
        self.statusBar().showMessage(f"模块 {module_id} · 第 {page} 页")

    def _locate_module_from_preview(self, module_id: str) -> None:
        table = self.parameter_table
        column = COLUMN_INDEX["module_id"]
        for row in range(table.rowCount()):
            if self._cell_text(row, "module_id").strip() == module_id:
                if self._full_window_active:
                    self._exit_preview_full_window()
                self._focused_module_id = module_id
                self.preview.highlight_module(module_id)
                table.setCurrentCell(row, column, QItemSelectionModel.SelectionFlag.ClearAndSelect)
                table.scrollToItem(table.item(row, column))
                table.setFocus(Qt.FocusReason.MouseFocusReason)
                self.statusBar().showMessage(f"模块 {module_id} · 第 {self.page_spin.value()} 页")
                return
        self.statusBar().showMessage(f"参数表已没有模块 {module_id}，请更新预览。")

    def _populate_tables(self) -> None:
        ensure_standard_project(self.project)
        self.drawing_document = None
        self._focused_module_id = None
        self._reset_preview_pdf()
        self._mark_preview_stale()
        self.preview.scene().clear()
        self.page_controls.hide()
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
        self._reset_history()

    def new_project(self) -> None:
        self.project = Project()
        self.drawing_document = None
        self._focused_module_id = None
        self._reset_preview_pdf()
        self._mark_preview_stale()
        self.preview.scene().clear()
        self.page_spin.setMaximum(1)
        self.page_controls.hide()
        self._clear_rows()
        self._add_module()
        self._reset_history()

    def _build_project_row(self, row: int) -> tuple[ModuleParameters, BoardParameters, AnchorParameters]:
        base = self._row_bases[row]
        return build_standard_row(
            self._sheet_values(row), base.models, board_face_profile=base.profile, fallback=base.automatic_fallback,
        )

    def _collect_project(self) -> Project:
        modules: list[ModuleParameters] = []
        boards: list[BoardParameters] = []
        anchors: list[AnchorParameters] = []
        auto_fields = {}
        for row in range(self.parameter_table.rowCount()):
            module, board, anchor = self._build_project_row(row)
            modules.append(module)
            boards.append(board)
            anchors.append(anchor)
            auto_fields[module.module_id] = automatic_fields(self._sheet_values(row))
        project = Project(
            metadata=self.project.metadata,
            modules=modules,
            boards=boards,
            anchors=anchors,
            standard_auto_fields=auto_fields,
            standard_link_version=STANDARD_LINK_VERSION,
        )
        ensure_standard_project(project)
        return project

    def _get_drawing_generator(self, reference: Path | None) -> DrawingGenerator:
        def stamp(path: Path):
            try:
                info = path.stat()
            except FileNotFoundError:
                return None
            return info.st_size, info.st_mtime_ns, info.st_ctime_ns

        key = None
        if reference is not None:
            candidate = reference.parent / "derived" / "quick_insert_opening_candidate.json"
            key = reference, stamp(reference), stamp(candidate)
        if self._drawing_generator is None or key != self._reference_key:
            self._drawing_generator = DrawingGenerator(
                ReferenceLibrary(reference) if reference else None, reuse_modules=True
            )
            self._reference_key = key
        return self._drawing_generator

    def generate(self) -> None:
        module_count = self.parameter_table.rowCount()
        progress = OperationProgress(self, "正在整理参数…", module_count + 4, tracks_pdf=True)
        try:
            project = self._collect_project()
            font_directory = self._pdf_font_directory()
            label = self._filename_label()
            reference = self.reference_dxf if self.reference_dxf.exists() else None
            previous_cache_pages = self._pdf_page_cache.pages

            def work(report, report_pages):
                report("正在读取参考图块…")
                generator = self._get_drawing_generator(reference)
                report(f"正在生成模块视图 0/{module_count}…")
                drawing = generator.generate(
                    project,
                    measure_detail=shx_detail_measure(font_directory),
                    on_module_drawn=lambda count: report(
                        f"正在生成模块视图 {count}/{module_count}…"
                        if count < module_count else "正在排版…"
                    ),
                )
                reused = generator.reused_module_count
                drawing = replace(drawing, filename_label=label)
                report("正在准备 PDF 预览…")
                try:
                    with TemporaryDirectory(prefix="refracdraft-preview-") as directory:
                        path = export_pdf(
                            drawing, Path(directory) / "preview.pdf", reference_dxf=reference,
                            font_directory=font_directory, progress=report, workers=2, page_progress=report_pages,
                            page_cache=self._pdf_page_cache,
                        )
                        return drawing, path.read_bytes(), None, reused, self._pdf_page_cache.reused_page_count
                except Exception as exc:
                    return drawing, None, f"暂用绘图预览，PDF 预览生成失败：{exc}", reused, 0

            self.drawing_document, pdf_bytes, warning, reused, reused_pages = _run_background(progress, work)
            self.project = project
            self._drawing_dirty = False
            images = ()
            if pdf_bytes is not None and self._preview_cache_pages is previous_cache_pages:
                reused_numbers = {index + 1 for index in self._pdf_page_cache.reused_page_indices}
                images = [(number, image) for number, image in self._preview_images.items() if number in reused_numbers]
            self._reset_preview_pdf(
                (font_directory, pdf_bytes) if pdf_bytes is not None else None
            )
            if pdf_bytes is not None and self._pdf_page_cache.pages is not previous_cache_pages:
                self._preview_cache_pages = self._pdf_page_cache.pages
                self._preview_images.update(images)
            page = self._module_page(self._focused_module_id) or 1
            with QSignalBlocker(self.page_spin):
                self.page_spin.setMaximum(max(1, len(self.drawing_document.pages)))
                self.page_spin.setValue(page)
            self.page_controls.setVisible(len(self.drawing_document.pages) > 1)
            warnings = list(self.drawing_document.warnings)
            self._show_selected_page(page)
            if warning:
                warnings.append(warning)
            progress.finish("图纸已生成")
            summary = f"图纸已生成 · 复用 {reused}/{module_count} 个模块" if reused else "图纸已生成"
            if reused_pages:
                summary += f" · 复用 {reused_pages}/{len(self.drawing_document.pages)} 页 PDF"
            self.statusBar().showMessage(summary + ("；" + "；".join(warnings) if warnings else ""))
        except Exception as exc:
            progress.hide()
            QMessageBox.critical(self, "生成失败", str(exc))
        finally:
            progress.hide()
            progress.deleteLater()

    def _reset_preview_pdf(self, pdf=None) -> None:
        self._preview_pdf = pdf
        self._preview_cache_pages = None
        for future in self._preview_jobs.values():
            future.cancel()
        self._preview_jobs.clear()
        self._preview_images.clear()
        self._shown_preview_page = None
        self.preview.set_module_panels()
        if hasattr(self, "_preview_timer"):
            self._preview_timer.stop()

    def _show_selected_page(self, value: int) -> None:
        if self._preview_pdf is None or not self.drawing_document or self._preview_workers_failed:
            super()._show_selected_page(value)
            self._set_preview_panels(value)
            return
        if value != self._shown_preview_page:
            if value in self._preview_images:
                self._preview_images.move_to_end(value)
                self.preview.show_page_image(self._preview_images[value])
                self._set_preview_panels(value)
            else:
                self.preview.scene().clear()
                self.preview.set_module_panels()
            self._shown_preview_page = value
        page_count = len(self.drawing_document.pages)
        try:
            if self._preview_pool is None:
                self._preview_pool = ProcessPoolExecutor(max_workers=2, mp_context=get_context("spawn"))
            for page in (value, value + 1, value - 1):
                if len(self._preview_jobs) >= 2:
                    break
                if 1 <= page <= page_count and page not in self._preview_images and page not in self._preview_jobs:
                    self._preview_jobs[page] = self._preview_pool.submit(render_pdf_preview, self._preview_pdf[1], page - 1)
        except (OSError, RuntimeError) as exc:
            self._disable_preview_workers(exc)
        if self._preview_jobs and not self._preview_timer.isActive():
            self._preview_timer.start()

    def _disable_preview_workers(self, error: Exception) -> None:
        pdf = self._preview_pdf
        self._reset_preview_pdf()
        self._preview_pdf = pdf
        self._shown_preview_page = self.page_spin.value()
        self._preview_workers_failed = True
        super()._show_selected_page(self.page_spin.value())
        self._set_preview_panels(self.page_spin.value())
        self.statusBar().showMessage(f"暂用绘图预览：{error}")

    def _collect_preview_pages(self) -> None:
        current = self.page_spin.value()
        for page, future in tuple(self._preview_jobs.items()):
            if not future.done():
                continue
            del self._preview_jobs[page]
            try:
                pixmap = QPixmap()
                if not pixmap.loadFromData(future.result()):
                    raise ValueError("无法读取预览页面")
            except Exception as exc:
                self._disable_preview_workers(exc)
                return
            self._preview_images[page] = pixmap
            self._preview_images.move_to_end(page)
            if len(self._preview_images) > 6:
                self._preview_images.popitem(last=False)
            if page == current:
                self.preview.show_page_image(pixmap)
                self._set_preview_panels(page)
        self._show_selected_page(current)
        if not self._preview_jobs:
            self._preview_timer.stop()

    def _set_preview_panels(self, value: int) -> None:
        pages = self.drawing_document.pages if self.drawing_document else ()
        self.preview.set_module_panels(pages[value - 1].modules if 1 <= value <= len(pages) else ())
        self.preview.highlight_module(self._focused_module_id)

    def _pdf_font_directory(self) -> str | None:
        directory = application_directory() / "fonts"
        return str(directory) if directory.is_dir() else None

    def _render_pdf(
        self, path: Path, font_directory: str | None, progress: OperationProgress,
        *, filename_label: str | None = None,
    ) -> Path:
        drawing = self.drawing_document
        if filename_label is not None:
            drawing = replace(drawing, filename_label=filename_label)
        reference = self.reference_dxf
        return _run_background(progress, lambda report, report_pages: export_pdf(
            drawing, path, reference_dxf=reference, font_directory=font_directory,
            progress=report, workers=2, page_progress=report_pages,
        ))

    def export_dxf_file(self) -> None:
        if self._drawing_dirty or not self.drawing_document:
            self.generate()
        if self._drawing_dirty or not self.drawing_document:
            return
        path = self._output_target(".dxf")
        if path is None:
            return
        progress = OperationProgress(self, "正在准备 DXF…", 2)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            progress.advance("正在写入 DXF…")
            label = path.stem if self.print_filename_check.isChecked() else ""
            drawing = replace(self.drawing_document, filename_label=label)
            reference = self.reference_dxf
            _run_background(progress, lambda _report, _report_pages: export_dxf(drawing, path, reference))
            progress.finish("DXF 已导出")
            self.statusBar().showMessage(f"DXF 已导出：{path}")
        except Exception as exc:
            progress.hide()
            QMessageBox.critical(self, "DXF 导出失败", str(exc))
        finally:
            progress.hide()
            progress.deleteLater()

    def export_pdf_file(self) -> None:
        if self._drawing_dirty or not self.drawing_document:
            self.generate()
        if self._drawing_dirty or not self.drawing_document:
            return
        path = self._output_target(".pdf")
        if path is None:
            return
        progress = OperationProgress(self, "正在准备 PDF…", 2, tracks_pdf=True)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            font_directory = self._pdf_font_directory()
            label = path.stem if self.print_filename_check.isChecked() else ""
            same_label = label == self.drawing_document.filename_label
            if same_label and self._preview_pdf is not None and self._preview_pdf[0] == font_directory:
                progress.update_stage("正在保存预览 PDF…", progress.bar.maximum() - 1)
                with TemporaryDirectory(prefix="refracdraft-save-", dir=path.parent) as directory:
                    staged = Path(directory) / "drawing.pdf"
                    staged.write_bytes(self._preview_pdf[1])
                    staged.replace(path)
            else:
                self._render_pdf(path, font_directory, progress, filename_label=label)
                if same_label:
                    self._reset_preview_pdf((font_directory, path.read_bytes()))
                    self._show_selected_page(self.page_spin.value())
            progress.finish("PDF 已导出")
            self.statusBar().showMessage(f"PDF 已导出：{path}")
        except Exception as exc:
            progress.hide()
            QMessageBox.critical(self, "PDF 导出失败", str(exc))
        finally:
            progress.hide()
            progress.deleteLater()

    def export_project_file(self) -> None:
        self._save_output_settings()
        path = self._default_output_directory() / self._filename_stem()
        existing = [file.name for file in project_output_paths(path).values() if file.exists()]
        if existing:
            names = "\n".join(existing)
            answer = QMessageBox.question(
                self, "覆盖文件", f"以下文件已存在，是否覆盖？\n{names}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        progress = OperationProgress(self, "正在整理项目参数…", 6, tracks_pdf=True)
        try:
            project = self._collect_project()
            progress.advance("正在读取参考图块…")
            reference = self.reference_dxf if self.reference_dxf.exists() else None
            progress.advance("正在生成模块图纸…")
            font_directory = self._pdf_font_directory()
            label = self._filename_label()

            def work(report, report_pages):
                generator = self._get_drawing_generator(reference)
                drawing = generator.generate(project, measure_detail=shx_detail_measure(font_directory))
                export_complete_project(
                    project, replace(drawing, filename_label=label), path, reference_dxf=reference,
                    font_directory=font_directory, progress=report, pdf_workers=2, pdf_page_progress=report_pages,
                )

            _run_background(progress, work)
            progress.finish("完整项目已导出")
            self.statusBar().showMessage(f"完整项目已导出到：{path.parent}")
        except Exception as exc:
            progress.hide()
            QMessageBox.critical(self, "完整项目导出失败", str(exc))
        finally:
            progress.hide()
            progress.deleteLater()

    def _preview_page_step(self, step: int) -> None:
        if not self.drawing_document:
            return
        page_count = len(self.drawing_document.pages)
        if page_count <= 1:
            return
        next_page = max(1, min(page_count, self.page_spin.value() + step))
        self.page_spin.setValue(next_page)

    def _preview_zoom(self, factor: float) -> None:
        if not self.drawing_document:
            return
        self.preview.scale(factor, factor)
