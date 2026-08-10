"""アプリケーション共通テーマ定義。

全ウィジェットが参照するカラーパレットとグローバルスタイルシートを提供する。
"""

from queue_manager import ItemStatus


class Theme:
    """ダークテーマのカラー定数。"""

    # 背景色
    BG_DARK = "#0A0A0A"
    BG_CARD = "#161616"

    # テキスト
    TEXT_PRIMARY = "#FFFFFF"
    TEXT_SECONDARY = "#8E8E93"
    TEXT_TERTIARY = "#636366"

    # アクセント（青のグラデーション用）
    ACCENT = "#0A84FF"
    ACCENT_LIGHT = "#5AC8FA"
    ACCENT_HOVER = "#0070E0"
    ACCENT_GLOW = "rgba(10, 132, 255, 0.3)"

    # 入力欄
    INPUT_BG = "#1C1C1E"
    INPUT_BORDER = "#38383A"
    INPUT_BORDER_FOCUS = "#0A84FF"

    # カード
    CARD_BORDER = "#2C2C2E"

    # 状態色
    SUCCESS = "#30D158"
    ERROR = "#FF453A"
    WARNING = "#FF9F0A"


# --- ステータスアイコン（モノクロ記号、UI色に染まる） ---
STATUS_ICONS = {
    ItemStatus.PENDING: "⋯",
    ItemStatus.RESOLVING: "↻",
    ItemStatus.DOWNLOADING: "↓",
    ItemStatus.COMPLETED: "✓",
    ItemStatus.FAILED: "✕",
    ItemStatus.CANCELLED: "⊘",
}


def build_global_stylesheet() -> str:
    """MainWindow に適用するグローバルスタイルシートを返す。"""
    return f"""
        QMainWindow {{
            background-color: {Theme.BG_DARK};
        }}
        QScrollArea {{
            border: none;
            background-color: transparent;
        }}
        QWidget {{
            background-color: transparent;
            color: {Theme.TEXT_PRIMARY};
            font-family: "SF Pro Display", "Helvetica Neue", "Segoe UI", sans-serif;
            font-size: 13px;
        }}

        /* 入力欄 */
        QLineEdit {{
            background-color: {Theme.INPUT_BG};
            border: 1px solid {Theme.INPUT_BORDER};
            border-radius: 10px;
            padding: 14px 16px;
            color: {Theme.TEXT_PRIMARY};
            font-size: 14px;
            selection-background-color: {Theme.ACCENT};
        }}
        QLineEdit:focus {{
            border: 2px solid {Theme.ACCENT};
            padding: 13px 15px;
        }}
        QLineEdit:hover {{
            border: 1px solid {Theme.TEXT_TERTIARY};
        }}

        /* メインボタン */
        QPushButton {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {Theme.ACCENT}, stop:1 {Theme.ACCENT_LIGHT});
            color: white;
            border: none;
            border-radius: 12px;
            padding: 12px 24px;
            font-size: 14px;
            font-weight: 600;
        }}
        QPushButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {Theme.ACCENT_HOVER}, stop:1 {Theme.ACCENT});
        }}
        QPushButton:pressed {{
            background: {Theme.ACCENT_HOVER};
        }}
        QPushButton:disabled {{
            background: {Theme.INPUT_BORDER};
            color: {Theme.TEXT_TERTIARY};
        }}

        /* セカンダリボタン */
        QPushButton#secondary {{
            background-color: {Theme.INPUT_BG};
            border: 1px solid {Theme.INPUT_BORDER};
            color: {Theme.TEXT_PRIMARY};
        }}
        QPushButton#secondary:hover {{
            background-color: {Theme.CARD_BORDER};
            border: 1px solid {Theme.TEXT_TERTIARY};
        }}

        /* プログレスバー */
        QProgressBar {{
            background-color: {Theme.INPUT_BG};
            border: none;
            border-radius: 6px;
            text-align: center;
        }}
        QProgressBar::chunk {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {Theme.ACCENT}, stop:1 {Theme.ACCENT_LIGHT});
            border-radius: 6px;
        }}

        /* カード */
        QFrame#Card {{
            background-color: {Theme.BG_CARD};
            border: 1px solid {Theme.CARD_BORDER};
            border-radius: 16px;
        }}

        /* カードタイトル */
        QLabel#Title {{
            font-size: 13px;
            font-weight: 600;
            color: {Theme.TEXT_SECONDARY};
            letter-spacing: 0.5px;
        }}

        /* コンボボックス */
        QComboBox {{
            background-color: {Theme.INPUT_BG};
            border: 1px solid {Theme.INPUT_BORDER};
            border-radius: 8px;
            padding: 8px 12px;
            color: {Theme.TEXT_PRIMARY};
            font-size: 13px;
        }}
        QComboBox:hover {{
            border: 1px solid {Theme.TEXT_TERTIARY};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 24px;
        }}
        QComboBox::down-arrow {{
            image: none;
        }}
        QComboBox QAbstractItemView {{
            background-color: {Theme.BG_CARD};
            border: 1px solid {Theme.CARD_BORDER};
            border-radius: 8px;
            selection-background-color: {Theme.ACCENT};
            color: {Theme.TEXT_PRIMARY};
            outline: none;
        }}
        QComboBox QAbstractItemView::item {{
            padding: 8px 10px;
            min-height: 28px;
            border-radius: 4px;
            margin: 2px;
        }}
        QComboBox QAbstractItemView::item:hover {{
            background-color: {Theme.INPUT_BG};
        }}

        /* ラジオボタン */
        QRadioButton {{
            spacing: 10px;
            font-size: 14px;
        }}
        QRadioButton::indicator {{
            width: 20px;
            height: 20px;
            border-radius: 10px;
            border: 2px solid {Theme.INPUT_BORDER};
            background: transparent;
        }}
        QRadioButton::indicator:hover {{
            border: 2px solid {Theme.TEXT_TERTIARY};
        }}
        QRadioButton::indicator:checked {{
            border: 2px solid {Theme.ACCENT};
            background: qradialgradient(cx:0.5, cy:0.5, radius:0.4,
                fx:0.5, fy:0.5, stop:0 {Theme.ACCENT}, stop:1 {Theme.ACCENT});
        }}

        /* メッセージボックス */
        QMessageBox {{
            background-color: {Theme.BG_CARD};
        }}
        QMessageBox QLabel {{
            color: {Theme.TEXT_PRIMARY};
            font-size: 13px;
            min-width: 400px;
        }}
    """
