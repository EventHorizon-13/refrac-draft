from __future__ import annotations

import json

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from refracdraft.release import (
    PROJECT_URL, RELEASES_API, app_version, build_time_display, latest_portable_release,
)


class AboutDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("关于")
        self.setMinimumWidth(390)
        self.network = QNetworkAccessManager(self)
        self.download_url = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        title = QLabel("RefracDraft Standard")
        font = title.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 3)
        title.setFont(font)
        layout.addWidget(title)
        version_label = QLabel(f"版本 v{app_version()} · Windows x64 便携版")
        version_label.setObjectName("versionLabel")
        layout.addWidget(version_label)
        build_label = QLabel(f"编译时间 {build_time_display() or '未记录'}")
        build_label.setObjectName("buildTimeLabel")
        layout.addWidget(build_label)
        layout.addWidget(QLabel("陶瓷纤维模块加工图生成器"))
        project = QLabel(f'<a href="{PROJECT_URL}">GitHub 项目主页</a>')
        project.setOpenExternalLinks(True)
        layout.addWidget(project)

        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.check = QPushButton("检查更新")
        self.check.clicked.connect(self._check_updates)
        actions.addWidget(self.check)
        self.download = QPushButton("下载新版本")
        self.download.clicked.connect(self._open_download)
        self.download.hide()
        actions.addWidget(self.download)
        actions.addStretch()
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        layout.addLayout(actions)

    def _check_updates(self) -> None:
        self.check.setEnabled(False)
        self.download.hide()
        self.status.setText("正在检查更新…")
        request = QNetworkRequest(QUrl(RELEASES_API))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"User-Agent", b"RefracDraft-Standard")
        request.setTransferTimeout(12_000)
        reply = self.network.get(request)
        reply.finished.connect(lambda: self._show_result(reply))

    def _show_result(self, reply: QNetworkReply) -> None:
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.status.setText(f"检查更新失败：{reply.errorString()}")
                return
            releases = json.loads(bytes(reply.readAll()))
            if not isinstance(releases, list):
                raise ValueError
            update = latest_portable_release(releases)
            if update is None:
                self.status.setText("没有可下载的更新。")
                return
            version, self.download_url = update
            self.status.setText(f"发现新版本 v{version}。下载后解压到新目录即可使用。")
            self.download.show()
        except (AttributeError, TypeError, ValueError):
            self.status.setText("无法读取 GitHub 发布信息，请稍后重试。")
        finally:
            reply.deleteLater()
            self.check.setEnabled(True)

    def _open_download(self) -> None:
        if not QDesktopServices.openUrl(QUrl(self.download_url)):
            self.status.setText("无法打开下载链接，请从 GitHub 项目主页进入 Releases。")
