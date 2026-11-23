"""Interactive editor for the four parameterized cuts in each orthographic view."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QTabBar, QVBoxLayout, QWidget,
)

from refracdraft.domain.models import BoardFaceFeature, BoardFaceProfile, CutFace, ModuleParameters
from refracdraft.drawing.board_profiles import board_cut_edges, build_board_profile, chamfer_legs, profiles_by_face
from refracdraft.drawing.multiface import machined_module
from refracdraft.drawing.model import Dimension
from refracdraft.geometry.primitives import Polyline, rectangle


CUT_NAMES = ("类型 1 · 台阶", "类型 2 · 凹槽", "类型 3 · 斜切角", "类型 4 · 斜切台阶")
CUT_DIMENSIONS = ("ab", "abcd", "ab", "abc")
DIMENSION_COLORS = {
    "a": ("#17669f", "#83c5ff"),
    "b": ("#925713", "#ffc37e"),
    "c": ("#1a7650", "#7fdfaf"),
    "d": ("#8346a1", "#e4a9ff"),
}


def _dimension_color(letter: str, palette) -> QColor:
    return QColor(DIMENSION_COLORS[letter][int(palette.base().color().lightness() < 128)])


class OutlinePreview(QWidget):
    def __init__(self, width: float, height: float, parent: QWidget):
        super().__init__(parent)
        self.frame_width = width
        self.frame_height = height
        self.outline: Polyline | None = None
        self.dimensions: tuple[tuple[str, Dimension], ...] = ()
        self.setMinimumSize(450, 235)
        self.setAccessibleName("夹板面轮廓示意图")

    @staticmethod
    def dimension_endpoints(dim: Dimension, start: QPointF, end: QPointF, scale: float):
        offset = max(-34, min(34, -dim.offset * scale))
        if dim.orientation == "horizontal":
            lane = min(start.y(), end.y()) + offset
            return QPointF(start.x(), lane), QPointF(end.x(), lane)
        lane = min(start.x(), end.x()) + offset
        return QPointF(lane, start.y()), QPointF(lane, end.y())

    def _transform(self):
        scale = min((self.width() - 120) / self.frame_width, (self.height() - 90) / self.frame_height)
        left = (self.width() - self.frame_width * scale) / 2
        bottom = (self.height() + self.frame_height * scale) / 2

        def point(x: float, y: float) -> QPointF:
            return QPointF(left + x * scale, bottom - y * scale)

        return point, scale

    def dimension_layout(self, point, scale):
        size = max(16.0, self.fontMetrics().height() + 2.0)
        gap = size + 6.0
        viewport = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        occupied = []
        lanes = {"horizontal": [], "vertical": []}
        for letter, dim in self.dimensions:
            start, end = point(*dim.start), point(*dim.end)
            first, last = self.dimension_endpoints(dim, start, end, scale)
            horizontal = dim.orientation == "horizontal"
            normal = QPointF(0, 1) if horizontal else QPointF(1, 0)
            lane = first.y() if horizontal else first.x()
            direction = -1 if dim.offset >= 0 else 1
            label_width = max(size, self.fontMetrics().horizontalAdvance(f"{letter}=0") + 4) if start == end else size
            normal_size = size if horizontal else label_width
            center = (first + last) / 2 + normal * direction * (normal_size / 2 + 3)
            offsets = [0.0]
            for step in range(1, 1 + int((self.height() if horizontal else self.width()) / gap)):
                offsets.extend((step * gap * direction, -step * gap * direction))
            for offset in offsets:
                shift = normal * offset
                label = QRectF(center.x() - label_width / 2, center.y() - size / 2, label_width, size).translated(shift)
                if (not viewport.contains(label) or any(label.intersects(other) for other in occupied)
                    or any(abs(lane + offset - other) < gap for other in lanes[dim.orientation])):
                    continue
                occupied.append(label.adjusted(-2, -2, 2, 2))
                lanes[dim.orientation].append(lane + offset)
                yield letter, start, end, first + shift, last + shift, label
                break

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.base())
        point, scale = self._transform()
        painter.setPen(QPen(palette.mid().color(), 1, Qt.PenStyle.DashLine))
        painter.drawRect(QRectF(point(0, self.frame_height), point(self.frame_width, 0)))
        if self.outline is None:
            return
        fill = palette.highlight().color()
        fill.setAlpha(31)
        painter.setBrush(fill)
        painter.setPen(QPen(palette.text().color(), 2))
        painter.drawPolygon(QPolygonF([point(x, y) for x, y in self.outline.points]))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        dimensions = tuple(self.dimension_layout(point, scale))
        for letter, start, end, first, last, _ in dimensions:
            painter.setPen(QPen(_dimension_color(letter, palette), 1))
            painter.drawLine(start, first)
            painter.drawLine(end, last)
            painter.drawLine(first, last)
            tick = QPointF(0, 3) if first.y() == last.y() else QPointF(3, 0)
            painter.drawLine(first - tick, first + tick)
            painter.drawLine(last - tick, last + tick)
        for letter, start, end, _, _, label_rect in dimensions:
            painter.setPen(_dimension_color(letter, palette))
            painter.fillRect(label_rect, palette.base())
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, f"{letter}=0" if start == end else letter)


@dataclass
class CutControls:
    face: CutFace
    kind: QComboBox
    dimensions: dict[str, QLineEdit]
    depth: QLineEdit
    start: QComboBox
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
        depth_text = self.depth.text().strip()
        try:
            depth = None if depth_text in ("", "贯通") else float(depth_text)
            if depth is not None and not (0 < depth < float("inf")):
                raise ValueError
        except ValueError:
            raise ValueError("剪切深度须为正数，留空表示贯通") from None
        try:
            return BoardFaceFeature(
                type=kind + 1, **values, face=self.face, cut_depth_mm=depth, cut_start=self.start.currentData(),
                rotation_deg=self.angle, mirror_x=self.mirror.isChecked(),
            )
        except ValueError:
            raise ValueError("a、b、c 须为有限正数，斜切台阶 a 可为 0，凹槽 d 可为负或 0") from None

    def set_angle(self, angle: int) -> None:
        self.angle = angle
        self.rotate.setText(f"旋转 · {angle}°")

    def widgets(self) -> tuple[QWidget, ...]:
        return (self.kind, *self.dimensions.values(), self.depth, self.start, self.rotate, self.mirror, self.remove)


class BoardFaceDialog(QDialog):
    def __init__(self, module: ModuleParameters, profile: BoardFaceProfile | None, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle(f"异形模块 · {module.module_id}")
        self.resize(900, 490)
        self.module = module
        self.active_face = CutFace.BOARD
        self.profile: BoardFaceProfile | None = profile
        self._all_cuts: list[CutControls] = []

        layout = QVBoxLayout(self)
        self.faces = QTabBar()
        self.faces.setExpanding(False)
        for face in CutFace:
            self.faces.addTab(face.value)
        self.faces.setAccessibleName("加工面")
        layout.addWidget(self.faces)
        self.face_caption = QLabel()
        layout.addWidget(self.face_caption)
        width, height, _ = self.module.cut_face_dimensions(self.active_face)
        self.preview = OutlinePreview(width, height, self)
        layout.addWidget(self.preview, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(108)
        scroll.setMaximumHeight(190)
        grid_widget = QWidget()
        self.grid = QGridLayout(grid_widget)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        for column, label in enumerate(("轮廓类型", "a", "b", "c", "d", "剪切深度", "起切面", "旋转", "镜像", "")):
            header = QLabel(label)
            if label in DIMENSION_COLORS:
                header.setStyleSheet(f"color: {_dimension_color(label, self.palette()).name()}; font-weight: 600;")
            self.grid.addWidget(header, 0, column)
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
        self.faces.currentChanged.connect(self._select_face)
        self._select_face(0)

    @property
    def cuts(self) -> list[CutControls]:
        return [cut for cut in self._all_cuts if cut.face == self.active_face]

    def _select_face(self, index: int) -> None:
        self.active_face = tuple(CutFace)[index]
        width, height, depth = self.module.cut_face_dimensions(self.active_face)
        self.preview.frame_width, self.preview.frame_height = width, height
        self.preview.setAccessibleName(f"{self.active_face}切口示意图")
        self.face_caption.setText(
            f"外框 {width:g} × {height:g} mm  ·  最大盲切深度 {depth:g} mm  ·  更换起切面只反转深度方向"
        )
        self._place_rows()
        self._refresh(next(iter(self.cuts), None))

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.FocusIn:
            for cut in self.cuts:
                if watched in cut.widgets():
                    self._refresh(cut)
                    break
        return super().eventFilter(watched, event)

    def accept(self) -> None:
        if not self.confirm.isEnabled():
            return
        if self.profile is not None and any(cut.face != CutFace.BOARD for cut in self.profile.features):
            try:
                machined_module(self.module, self.profile)
            except ValueError as exc:
                self.status.setText(str(exc))
                return
        super().accept()

    def _add_cut(self, feature: BoardFaceFeature | None = None) -> None:
        face = feature.face if feature is not None else self.active_face
        kind = QComboBox()
        kind.addItems(CUT_NAMES)
        kind.setCurrentIndex(feature.type - 1 if feature else 0)
        inputs = {letter: QLineEdit() for letter in "abcd"}
        for letter, field in inputs.items():
            field.setAccessibleName(f"尺寸 {letter}（mm）")
            field.setMinimumWidth(45)
        inputs["d"].setToolTip("凹槽肩部的有向尺寸，允许负值和 0")
        depth = QLineEdit()
        depth.setPlaceholderText("贯通")
        depth.setAccessibleName("剪切深度（mm）")
        depth.setToolTip("从选定的起切面向模块内部量取，留空表示贯通")
        depth.setMinimumWidth(70)
        if feature and feature.cut_depth_mm is not None:
            depth.setText(f"{feature.cut_depth_mm:g}")
        start = QComboBox()
        start.setAccessibleName("起切面")
        for origin in face.starts:
            start.addItem(origin.value, origin.value)
        start.setCurrentIndex(start.findData((feature.cut_start if feature else face.starts[0]).value))
        start.setEnabled(bool(depth.text()))
        rotate = QPushButton()
        rotate.setToolTip("逆时针旋转 90°")
        mirror = QPushButton("镜像")
        mirror.setCheckable(True)
        mirror.setToolTip("沿模板水平方向镜像，再应用旋转")
        mirror.setChecked(feature.mirror_x if feature else False)
        remove = QPushButton("删除")
        for button in (rotate, mirror, remove):
            button.setAutoDefault(False)
        cut = CutControls(face, kind, inputs, depth, start, rotate, mirror, remove, 0)
        cut.set_angle(feature.rotation_deg if feature else 0)
        self._all_cuts.append(cut)
        self._place_rows()
        self._set_inputs(cut, feature)
        for widget in cut.widgets():
            widget.installEventFilter(self)
        kind.currentIndexChanged.connect(lambda: self._set_inputs(cut))
        for field in (*inputs.values(), depth):
            field.textChanged.connect(lambda: self._refresh(cut))
        depth.textChanged.connect(lambda value: start.setEnabled(value.strip() not in ("", "贯通")))
        start.currentIndexChanged.connect(lambda: self._refresh(cut))
        rotate.clicked.connect(lambda: self._rotate(cut))
        mirror.toggled.connect(lambda: self._refresh(cut))
        remove.clicked.connect(lambda: self._remove_cut(cut))

    def _place_rows(self) -> None:
        for cut in self._all_cuts:
            for widget in cut.widgets():
                self.grid.removeWidget(widget)
                widget.hide()
        for row, cut in enumerate(self.cuts, 1):
            for column, widget in enumerate(cut.widgets()):
                self.grid.addWidget(widget, row, column)
                widget.show()

    def _set_inputs(self, cut: CutControls, feature: BoardFaceFeature | None = None) -> None:
        width, height, _ = self.module.cut_face_dimensions(cut.face)
        if cut.angle in (90, 270):
            width, height = height, width
        kind = cut.kind.currentIndex()
        defaults = (
            (width * .4, height * .2),
            (height * .3, width * .3, height * .3, width * .15),
            (width * .25, height * .25),
            (width * .33, width * .28, height * .63),
        )[kind]
        if feature is not None and feature.type == 3 and feature.b is None:
            try:
                run, rise = chamfer_legs(width, height, feature)
            except ValueError:
                # A resized legacy profile may need its dimensions edited.
                pass
            else:
                feature = feature.model_copy(update={"a": run, "b": rise})
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
        self._all_cuts.remove(cut)
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
            for index, cut in enumerate(self._all_cuts, 1):
                try:
                    feature = cut.read()
                    _, _, max_depth = self.module.cut_face_dimensions(cut.face)
                    if feature.cut_depth_mm is not None and feature.cut_depth_mm > max_depth:
                        raise ValueError(f"剪切深度不能超过 {max_depth:g} mm")
                    features.append(feature)
                except ValueError as exc:
                    raise ValueError(f"{cut.face}切口 {index}：{exc}") from exc
            self.profile = BoardFaceProfile(features=features) if features else None
            self.preview.outline = rectangle(width, height)
            for face, profile in (profiles_by_face(self.profile).items() if self.profile is not None else ()):
                face_width, face_height, _ = self.module.cut_face_dimensions(face)
                outline, dimensions = build_board_profile(face_width, face_height, profile)
                if face != self.active_face:
                    continue
                self.preview.outline = outline
                if active in self.cuts:
                    active_index = self.cuts.index(active)
                    key_groups = [
                        "".join(letter for letter in CUT_DIMENSIONS[feature.type - 1] if getattr(feature, letter) != 0)
                        for feature in profile.features
                    ]
                    start = sum(map(len, key_groups[:active_index]))
                    letters = key_groups[active_index]
                    self.preview.dimensions = tuple(zip(letters, dimensions[start:start + len(letters)]))
                    feature = profile.features[active_index]
                    if feature.type == 4 and feature.a == 0:
                        corner = next(point for edge in board_cut_edges(face_width, face_height, feature)
                                      for point in edge if point[0] in (0, face_width) and point[1] in (0, face_height))
                        horizontal = feature.rotation_deg % 180 == 0
                        side = (corner[1] == face_height) if horizontal else (corner[0] == 0)
                        marker = Dimension(corner, corner, "0", "horizontal" if horizontal else "vertical", 26 if side else -26)
                        self.preview.dimensions = (("a", marker), *self.preview.dimensions)
        except ValueError as exc:
            self.status.setText(str(exc))
            self.confirm.setEnabled(False)
        else:
            self.status.setText("此面没有切口" if not self.cuts else "")
            self.confirm.setEnabled(True)
        self.preview.update()
