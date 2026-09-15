"""形式・品質選択パネル。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QButtonGroup, QComboBox, QFrame,
)
from PySide6.QtWidgets import QSizePolicy

from theme import Theme
from widgets.surfaces import AirComboBox, SegmentButton, AnimatedSegment


class FormatPanel(QFrame):
    """動画/音声の形式と品質を選択するカード。

    外部から get_format_type() / get_resolution() / get_audio_format() /
    get_bitrate() で現在の選択値を取得できる。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        title = QLabel("保存設定")
        title.setObjectName("Title")
        layout.addWidget(title)
        segment = AnimatedSegment()
        self.segment = segment
        segment.setObjectName("Segment")
        types = QHBoxLayout(segment)
        types.setContentsMargins(3, 3, 3, 3)
        types.setSpacing(3)
        self.video_radio = SegmentButton("動画")
        self.audio_radio = SegmentButton("音声")
        for button in (self.video_radio, self.audio_radio):
            button.setCheckable(True)
            button.setObjectName("segmentOption")
        self.video_radio.setChecked(True)
        self._type_group = QButtonGroup(self)
        for button in (self.video_radio, self.audio_radio):
            self._type_group.addButton(button)
            types.addWidget(button, 1)
        segment.bind((self.video_radio, self.audio_radio))
        layout.addWidget(segment)
        self._video_container = QWidget()
        video = QVBoxLayout(self._video_container)
        video.setContentsMargins(0, 10, 0, 0)
        video.setSpacing(7)
        label = QLabel("画質")
        label.setObjectName("Secondary")
        video.addWidget(label)
        self.resolution_combo = AirComboBox()
        self.resolution_combo.addItems(["最高画質（自動）", "2160p", "1440p", "1080p", "720p"])
        video.addWidget(self.resolution_combo)
        layout.addWidget(self._video_container)
        self._audio_container = QWidget()
        audio = QVBoxLayout(self._audio_container)
        audio.setContentsMargins(0, 10, 0, 0)
        audio.setSpacing(7)
        label = QLabel("音声形式")
        label.setObjectName("Secondary")
        audio.addWidget(label)
        self.format_combo = AirComboBox()
        self.format_combo.addItems(["MP3", "WAV"])
        audio.addWidget(self.format_combo)
        self._bitrate_label = QLabel("ビットレート")
        self._bitrate_label.setObjectName("Secondary")
        audio.addWidget(self._bitrate_label)
        self.bitrate_combo = AirComboBox()
        self.bitrate_combo.addItems(["320kbps", "256kbps", "192kbps", "128kbps"])
        audio.addWidget(self.bitrate_combo)
        layout.addWidget(self._audio_container)
        self.video_radio.toggled.connect(self._update_visibility)
        self.format_combo.currentTextChanged.connect(self._on_format_changed)
        self._update_visibility()

    def _update_visibility(self):
        is_audio = self.audio_radio.isChecked()
        self._video_container.setVisible(not is_audio)
        self._audio_container.setVisible(is_audio)
        if is_audio:
            self._on_format_changed(self.format_combo.currentText())

    def _on_format_changed(self, text):
        is_mp3 = text == "MP3"
        self._bitrate_label.setVisible(is_mp3)
        self.bitrate_combo.setVisible(is_mp3)

    # --- 公開API ---

    def get_format_type(self) -> str:
        """'audio' or 'video'"""
        return "audio" if self.audio_radio.isChecked() else "video"

    def get_resolution(self) -> str:
        text = self.resolution_combo.currentText()
        return "best" if text == "最高画質（自動）" else text

    def get_audio_format(self) -> str:
        return self.format_combo.currentText()

    def get_bitrate(self) -> str:
        return self.bitrate_combo.currentText()
