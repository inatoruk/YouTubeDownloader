"""Air × Native palette. Gradients are reserved for background surfaces."""
from queue_manager import ItemStatus


class Theme:
    @classmethod
    def configure(cls, dark=False):
        cls.dark = dark
        colors = {
            'BG_DARK': ('#F8FBFF', '#1F2B39'),
            'BG_CARD': ('#FFFFFF', '#263547'),
            'TEXT_PRIMARY': ('#263449', '#E5EDF9'),
            'TEXT_SECONDARY': ('#61758D', '#B2C1D5'),
            'TEXT_TERTIARY': ('#6C8098', '#A0B2CA'),
            'ACCENT': ('#3378E6', '#94BAFF'),
            'ACCENT_HOVER': ('#2565C9', '#AFCCFF'),
            'ON_ACCENT': ('#FFFFFF', '#182F52'),
            'INPUT_BG': ('#FFFFFF', '#263547'),
            'INPUT_BORDER': ('#D6E2F0', '#43566D'),
            'CARD_BORDER': ('#DFE8F3', '#3E5067'),
            'SIDEBAR_TOP': ('#C8DFFF', '#264C78'),
            'SIDEBAR_BOTTOM': ('#EDF7FF', '#243947'),
            'BG_BOTTOM': ('#FFFFFF', '#233847'),
            'TRACK': ('#DCE6F2', '#3A4D62'),
            'SUCCESS': ('#24724F', '#77D6AA'),
            'ERROR': ('#BF3838', '#FF9696'),
            'WARNING': ('#98601C', '#EDBD75'),
        }
        for name, pair in colors.items():
            setattr(cls, name, pair[bool(dark)])
        cls.ACCENT_LIGHT = cls.ACCENT
        cls.INPUT_BORDER_FOCUS = cls.ACCENT
        cls.ACCENT_GLOW = cls.TRACK


Theme.configure()
STATUS_ICONS = {
    ItemStatus.PENDING: '待機', ItemStatus.RESOLVING: '取得中',
    ItemStatus.DOWNLOADING: '保存中', ItemStatus.COMPLETED: '✓ 完了',
    ItemStatus.FAILED: '失敗', ItemStatus.CANCELLED: '停止',
}


def build_global_stylesheet():
    return f'''
    QWidget {{ color: {Theme.TEXT_PRIMARY};
        font-size: 16px; background: transparent; }}
    QMainWindow, QDialog, QMessageBox {{ background: {Theme.BG_DARK}; }}
    QWidget#Workspace {{ background: {Theme.BG_DARK}; }}
    QFrame#Sidebar {{ background: transparent; }}
    QFrame#InputGroup {{ background: {Theme.INPUT_BG}; border: 1px solid {Theme.INPUT_BORDER}; border-radius: 12px; }}
    QLineEdit#UrlInput {{ background: transparent; border: none; padding: 14px 20px; font-size: 16px; }}
    QLabel#MediaTitle {{ font-size: 16px; font-weight: 500; }}
    QPushButton::menu-indicator {{ image: none; width: 0; height: 0; }}
    QComboBox::down-arrow {{ image: none; }}
    QPushButton#segmentOption {{ background: transparent; color: {Theme.TEXT_SECONDARY}; border: 1px solid transparent; border-radius: 6px; padding: 6px 10px; }}
    QPushButton#segmentOption:checked {{ background: transparent; color: {Theme.TEXT_PRIMARY}; }}
    QFrame#Card {{ border: none; background: transparent; }}
    QFrame#OutputGroup {{ border: none; border-top: 1px solid {Theme.CARD_BORDER}; }}
    QFrame#Footer {{ border-top: 1px solid {Theme.CARD_BORDER}; }}
    QFrame#QueueItem {{ border: none; border-bottom: 1px solid {Theme.CARD_BORDER}; }}
    QLabel#Title {{ font-size: 15px; font-weight: 600; color: {Theme.TEXT_SECONDARY}; }}
    QLabel#Secondary {{ color: {Theme.TEXT_SECONDARY}; font-size: 14px; }}
    QLabel#Error {{ color: {Theme.ERROR}; font-size: 14px; }}
    QLabel#Thumbnail {{ background: {Theme.TRACK}; border-radius: 7px; color: {Theme.TEXT_TERTIARY}; }}
    QLabel#Duration {{ background: #263B50; color: white; border-radius: 3px; font-size: 12px; padding: 1px 3px; }}
    QLineEdit, QTextEdit {{ background: {Theme.INPUT_BG}; border: 1px solid {Theme.INPUT_BORDER};
        border-radius: 10px; padding: 14px 18px; color: {Theme.TEXT_PRIMARY};
        selection-background-color: {Theme.ACCENT}; selection-color: {Theme.ON_ACCENT}; }}
    QPushButton {{ background: {Theme.ACCENT}; color: {Theme.ON_ACCENT}; border: 1px solid transparent;
        border-radius: 10px; padding: 14px 22px; font-size: 15px; font-weight: 500; }}
    QPushButton:hover {{ background: {Theme.ACCENT_HOVER}; }}
    QPushButton:disabled {{ background: {Theme.TRACK}; color: {Theme.TEXT_TERTIARY}; }}
    QPushButton#secondary {{ background: {Theme.INPUT_BG}; color: {Theme.TEXT_PRIMARY}; border: 1px solid {Theme.INPUT_BORDER}; }}
    QPushButton#secondary:hover {{ background: {Theme.TRACK}; }}
    QPushButton#link {{ background: transparent; color: {Theme.ACCENT}; padding: 4px 0; border: none; }}
    QPushButton#icon {{ background: transparent; color: {Theme.TEXT_SECONDARY}; padding: 0; border: none; font-size: 16px; }}
    QPushButton#icon:hover {{ background: {Theme.TRACK}; }}
    QFrame#Segment {{ background: transparent; border-radius: 9px; }}
    QRadioButton {{ padding: 7px; border-radius: 6px; color: {Theme.TEXT_SECONDARY}; }}
    QRadioButton::indicator {{ width: 0; height: 0; }}
    QRadioButton:checked {{ background: {Theme.BG_CARD}; color: {Theme.TEXT_PRIMARY}; }}
    QComboBox {{ background: {Theme.INPUT_BG}; border: 1px solid {Theme.INPUT_BORDER};
        border-radius: 9px; padding: 13px 16px; font-size: 15px; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox QAbstractItemView {{ background: {Theme.BG_CARD}; color: {Theme.TEXT_PRIMARY};
        border: 1px solid {Theme.INPUT_BORDER}; selection-background-color: {Theme.ACCENT};
        selection-color: {Theme.ON_ACCENT}; font-size: 17px; padding: 4px; }}
    QMenu {{ background: {Theme.BG_CARD}; color: {Theme.TEXT_PRIMARY};
        border: 1px solid {Theme.INPUT_BORDER}; selection-background-color: {Theme.ACCENT};
        selection-color: {Theme.ON_ACCENT}; }}
    QMenu::item {{ padding: 7px 18px; }}
    QMenu::item:selected {{ background: {Theme.ACCENT}; color: {Theme.ON_ACCENT}; }}
    QMenu::item:disabled {{ color: {Theme.TEXT_TERTIARY}; }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ width: 8px; background: transparent; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {Theme.INPUT_BORDER}; min-height: 24px; border-radius: 4px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QToolTip {{ background: {Theme.BG_CARD}; color: {Theme.TEXT_PRIMARY}; border: 1px solid {Theme.INPUT_BORDER}; }}
    '''
