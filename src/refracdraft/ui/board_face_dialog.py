"""Interactive editor for the four parameterized board-face cuts."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from refracdraft.domain.models import BoardFaceFeature, BoardFaceProfile
from refracdraft.drawing.board_profiles import build_board_profile
from refracdraft.drawing.model import Dimension
from refracdraft.geometry.primitives import Polyline, rectangle


CUT_NAMES = ("类型 1 · 台阶", "类型 2 · 凹槽", "类型 3 · 斜边", "类型 4 · 斜切台阶")
CUT_DIMENSIONS = ("ab", "abcd", "a", "abc")


class OutlinePreview(QWidget):
    def __init__(self, width: float, height: float, parent: QWidget):
        super().__init__(parent)
        self.frame_width = width
        self.frame_height = height
        self.outline: Polyline | None = None
        self.dimensions: tuple[tuple[str, Dimension], ...] = ()
        self.setMinimumSize(450, 235)
        self.setAccessibleName("夹板面轮廓示意图")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.base())
        scale = min((self.width() - 120) / self.frame_width, (self.height() - 90) / self.frame_height)
        left = (self.width() - self.frame_width * scale) / 2
        bottom = (self.height() + self.frame_height * scale) / 2

        def point(x: float, y: float) -> QPointF:
            return QPointF(left + x * scale, bottom - y * scale)

        painter.setPen(QPen(palette.mid().color(), 1, Qt.PenStyle.DashLine))
        painter.drawRect(QRectF(point(0, self.frame_height), point(self.frame_width, 0)))
        if self.outline is None:
            return
        fill = palette.highlight().color()
        fill.setAlpha(31)
        painter.setBrush(fill)
        painter.setPen(QPen(palette.text().color(), 2))
        painter.drawPolygon(QPolygonF([point(x, y) for x, y in self.outline.points]))
        painter.setPen(QPen(palette.text().color(), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for letter, dim in self.dimensions:
            start, end = point(*dim.start), point(*dim.end)
            if dim.orientation == "horizontal":
                shift = QPointF(0, max(-34, min(34, -dim.offset * scale)))
                text_shift = QPointF(0, -10)
            else:
                shift = QPointF(max(-34, min(34, -dim.offset * scale)), 0)
                text_shift = QPointF(-12 if dim.offset > 0 else 12, 0)
            painter.drawLine(start, start + shift)
            painter.drawLine(end, end + shift)
            painter.drawLine(start + shift, end + shift)
            center = (start + end) / 2 + shift + text_shift
            label_rect = QRectF(center.x() - 8, center.y() - 8, 16, 16)
            painter.fillRect(label_rect, palette.base())
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, letter)


@dataclass
class CutControls:
    kind: QComboBox
    dimensions: dict[str, QLineEdit]
    rotate: QPushButton
    mirror: QPushButton
    remove: QPushButton
    angle: int

    def read(self) -> BoardFaceFeature:
        kind = self.kind.currentIndex()
        values = {}
        for letter in CUT_DIMENSIONS[kind]:
            try:
                values[letter] = float(self.dimensions[letter].text())
            except ValueError:
                raise ValueError(f"请输入尺寸 {letter}（mm）") from None
        try:
            return BoardFaceFeature(
                type=kind + 1, **values, rotation_deg=self.angle, mirror_x=self.mirror.isChecked(),
            )
        except ValueError:
            raise ValueError("切口尺寸必须是有限的正数") from None

    def set_angle(self, angle: int) -> None:
        self.angle = angle
        self.rotate.setText(f"旋转 · {angle}°")

    def widgets(self) -> tuple[QWidget, ...]:
        return (self.kind, *self.dimensions.values(), self.rotate, self.mirror, self.remove)


class BoardFaceDialog(QDialog):
    def __init__(self, module_id: str, width: float, height: float,
                 profile: BoardFaceProfile | None, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle(f"异形模块 · {module_id}")
        self.resize(710, 490)
        self.profile: BoardFaceProfile | None = profile
        self.cuts: list[CutControls] = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"夹板面外框  {width:g} × {height:g} mm   ·   在参数表修改长度和厚度"))
        self.preview = OutlinePreview(width, height, self)
        layout.addWidget(self.preview, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(108)
        scroll.setMaximumHeight(190)
        grid_widget = QWidget()
        self.grid = QGridLayout(grid_widget)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        for column, label in enumerate(("轮廓类型", "a", "b", "c", "d", "方向", "镜像", "")):
            self.grid.addWidget(QLabel(label), 0, column)
        for column in range(1, 5):
            self.grid.setColumnStretch(column, 1)
        scroll.setWidget(grid_widget)
        layout.addWidget(scroll)

        actions = QHBoxLayout()
        add = QPushButton("添加切口")
        add.setAutoDefault(False)
        add.clicked.connect(lambda: self._add_cut())
        actions.addWidget(add)
        self.status = QLabel()
        self.status.setWordWrap(True)
        actions.addWidget(self.status, 1)
        layout.addLayout(actions)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.confirm = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.confirm.setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for feature in profile.features if profile else (None,):
            self._add_cut(feature)
        self._refresh(self.cuts[0])

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.FocusIn:
            for cut in self.cuts:
                if watched in cut.widgets():
                    self._refresh(cut)
                    break
        return super().eventFilter(watched, event)

    def accept(self) -> None:
        if self.confirm.isEnabled():
            super().accept()

    def _add_cut(self, feature: BoardFaceFeature | None = None) -> None:
        kind = QComboBox()
        kind.addItems(CUT_NAMES)
        kind.setCurrentIndex(feature.type - 1 if feature else 0)
        inputs = {letter: QLineEdit() for letter in "abcd"}
        for letter, field in inputs.items():
            field.setAccessibleName(f"尺寸 {letter}（mm）")
            field.setMinimumWidth(45)
        rotate = QPushButton()
        rotate.setToolTip("逆时针旋转 90°")
        mirror = QPushButton("镜像")
        mirror.setCheckable(True)
        mirror.setToolTip("沿模板水平方向镜像，再应用旋转")
        mirror.setChecked(feature.mirror_x if feature else False)
        remove = QPushButton("删除")
        for button in (rotate, mirror, remove):
            button.setAutoDefault(False)
        cut = CutControls(kind, inputs, rotate, mirror, remove, 0)
        cut.set_angle(feature.rotation_deg if feature else 0)
        self.cuts.append(cut)
        self._place_rows()
        self._set_inputs(cut, feature)
        for widget in cut.widgets():
            widget.installEventFilter(self)
        kind.currentIndexChanged.connect(lambda: self._set_inputs(cut))
        for field in inputs.values():
            field.textChanged.connect(lambda: self._refresh(cut))
        rotate.clicked.connect(lambda: self._rotate(cut))
        mirror.toggled.connect(lambda: self._refresh(cut))
        remove.clicked.connect(lambda: self._remove_cut(cut))

    def _place_rows(self) -> None:
        for row, cut in enumerate(self.cuts, 1):
            for column, widget in enumerate(cut.widgets()):
                self.grid.addWidget(widget, row, column)

    def _set_inputs(self, cut: CutControls, feature: BoardFaceFeature | None = None) -> None:
        width, height = self.preview.frame_width, self.preview.frame_height
        if cut.angle in (90, 270):
            width, height = height, width
        kind = cut.kind.currentIndex()
        defaults = (
            (width * .4, height * .2),
            (height * .3, width * .3, height * .3, width * .15),
            (width * .8,),
            (width * .33, width * .28, height * .63),
        )[kind]
        for index, (letter, field) in enumerate(cut.dimensions.items()):
            if feature is not None:
                value = getattr(feature, letter)
                text = "" if value is None else str(value).removesuffix(".0")
            else:
                text = f"{defaults[index]:.8g}" if index < len(defaults) else ""
            field.setEnabled(bool(text))
            field.setText(text)
        self._refresh(cut)

    def _rotate(self, cut: CutControls) -> None:
        cut.set_angle((cut.angle + 90) % 360)
        self._refresh(cut)

    def _remove_cut(self, cut: CutControls) -> None:
        self.cuts.remove(cut)
        for widget in cut.widgets():
            self.grid.removeWidget(widget)
            widget.hide()
            widget.deleteLater()
        self._place_rows()
        self._refresh(self.cuts[-1] if self.cuts else None)

    def _refresh(self, active: CutControls | None) -> None:
        width, height = self.preview.frame_width, self.preview.frame_height
        self.preview.outline = None
        self.preview.dimensions = ()
        try:
            features = []
            for index, cut in enumerate(self.cuts, 1):
                try:
                    features.append(cut.read())
                except ValueError as exc:
                    raise ValueError(f"切口 {index}：{exc}") from exc
            self.profile = BoardFaceProfile(features=features) if features else None
            if self.profile is None:
                self.preview.outline = rectangle(width, height)
            else:
                outline, dimensions = build_board_profile(width, height, self.profile)
                self.preview.outline = outline
                if active is not None:
                    active_index = self.cuts.index(active)
                    key_groups = [CUT_DIMENSIONS[feature.type - 1] for feature in features]
                    start = sum(map(len, key_groups[:active_index]))
                    letters = key_groups[active_index]
                    self.preview.dimensions = tuple(zip(letters, dimensions[start:start + len(letters)]))
        except ValueError as exc:
            self.status.setText(str(exc))
            self.confirm.setEnabled(False)
        else:
            self.status.setText("矩形夹板面" if self.profile is None else "")
            self.confirm.setEnabled(True)
        self.preview.update()
