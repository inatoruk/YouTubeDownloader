"""形式・品質選択パネル。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QRadioButton, QButtonGroup, QComboBox, QFrame,
)
from PySide6.QtWidgets import QSizePolicy

from theme import Theme


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
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("形式と品質")
        title.setObjectName("Title")
        layout.addWidget(title)

        # Video / Audio
        type_layout = QHBoxLayout()
        self.video_radio = QRadioButton("動画 (MP4)")
        self.audio_radio = QRadioButton("音声 (MP3/WAV)")
        self.video_radio.setChecked(True)

        self._type_group = QButtonGroup()
        self._type_group.addButton(self.video_radio)
        self._type_group.addButton(self.audio_radio)

        type_layout.addWidget(self.video_radio)
        type_layout.addWidget(self.audio_radio)
        type_layout.addStretch()
        layout.addLayout(type_layout)

        # Video options
        self._video_container = QWidget()
        video_layout = QHBoxLayout(self._video_container)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.setSpacing(12)

        res_label = QLabel("解像度:")
        res_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        video_layout.addWidget(res_label)
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(
            ["最高画質（自動）", "720p", "1080p", "1440p", "2160p"]
        )
        self.resolution_combo.setCurrentText("最高画質（自動）")
        self.resolution_combo.setFixedWidth(170)
        video_layout.addWidget(self.resolution_combo)
        video_layout.addStretch()
        layout.addWidget(self._video_container)

        # Audio options
        self._audio_container = QWidget()
        audio_layout = QHBoxLayout(self._audio_container)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        audio_layout.setSpacing(12)

        fmt_label = QLabel("形式:")
        fmt_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        audio_layout.addWidget(fmt_label)
        self.format_combo = QComboBox()
        self.format_combo.addItems(["MP3", "WAV"])
        self.format_combo.setCurrentText("MP3")
        self.format_combo.setFixedWidth(100)

        self._bitrate_label = QLabel("ビットレート:")
        self._bitrate_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.bitrate_combo = QComboBox()
        self.bitrate_combo.addItems(["320kbps", "256kbps", "192kbps", "128kbps"])
        self.bitrate_combo.setFixedWidth(120)

        audio_layout.addWidget(self.format_combo)
        audio_layout.addWidget(self._bitrate_label)
        audio_layout.addWidget(self.bitrate_combo)
        audio_layout.addStretch()
        layout.addWidget(self._audio_container)

        # Signals
        self._type_group.buttonClicked.connect(self._update_visibility)
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
