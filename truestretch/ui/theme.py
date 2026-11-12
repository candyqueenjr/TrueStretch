"""Colors, fonts and the app-wide stylesheet - a tactical, VALORANT-inspired look: deep navy, off-white text, red only
as an accent, sharp edges, thin lines and uppercase condensed headings. (Original design; no Riot assets.)"""

from PySide6.QtGui import QFont, QFontDatabase

from ..paths import resource_path
from ..system import system_prefers_dark

CHECK = resource_path("assets/check.svg").as_posix()
CHEVRON = resource_path("assets/chevron-down.svg").as_posix()

BODY = "Barlow"
DISPLAY = "Barlow Condensed"

DARK = {
    "bg": "#0f1923", "sidebar": "#0a1219", "surface": "#13202c", "surface2": "#192836", "surface3": "#223444",
    "border": "#223140", "border_strong": "#34495c", "text": "#ece8e1", "muted": "#8f9ba6", "faint": "#5b6b79",
    "accent": "#ff4655", "accent_hover": "#ff5b69", "accent_text": "#ffffff",
    "success": "#3ee0b9", "warning": "#f3c552", "danger": "#ff6a6a", "info": "#7cc4ff", "dark": True,
}
LIGHT = {
    "bg": "#ece8e1", "sidebar": "#e3ded5", "surface": "#f6f3ee", "surface2": "#ebe6de", "surface3": "#ddd7cc",
    "border": "#d3ccc0", "border_strong": "#b9b0a2", "text": "#0f1923", "muted": "#4f5b66", "faint": "#8a929a",
    "accent": "#e8303f", "accent_hover": "#ff4655", "accent_text": "#ffffff",
    "success": "#0f9f7f", "warning": "#a86b00", "danger": "#c62832", "info": "#1f6fb8", "dark": False,
}

_current = DARK
_fonts_loaded = False


def load_fonts():
    """Register the bundled Barlow fonts (SIL Open Font License) once per process."""
    global _fonts_loaded
    if _fonts_loaded:
        return
    folder = resource_path("assets/fonts")
    for f in sorted(folder.glob("*.ttf")) if folder.is_dir() else []:
        QFontDatabase.addApplicationFont(str(f))
    _fonts_loaded = True


def palette():
    return _current


def resolve(name):
    if name == "system":
        return DARK if system_prefers_dark() else LIGHT
    return LIGHT if name == "light" else DARK


def set_theme(name):
    global _current
    _current = resolve(name)
    return _current


def rgba(hex_color, alpha):
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# Text styles that use the condensed display face, uppercase and tracked out (QSS can't do either).
DISPLAY_STYLES = {
    "PageTitle": (24, QFont.Bold, 1.5), "H1": (19, QFont.Bold, 1.2), "H2": (13, QFont.DemiBold, 1.4),
    "Brand": (15, QFont.Bold, 2.0), "NavSection": (8.5, QFont.DemiBold, 2.2), "Caption": (8.5, QFont.DemiBold, 2.0),
    "Eyebrow": (9, QFont.DemiBold, 2.6), "Stat": (22, QFont.Bold, 0.5),
}


def display_font(kind):
    size, weight, spacing = DISPLAY_STYLES[kind]
    f = QFont(DISPLAY)
    f.setPointSizeF(size)
    f.setWeight(weight)
    f.setCapitalization(QFont.AllUppercase)
    f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


def button_font(size=10, weight=QFont.DemiBold, spacing=1.4):
    f = QFont(DISPLAY)
    f.setPointSizeF(size)
    f.setWeight(weight)
    f.setCapitalization(QFont.AllUppercase)
    f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


def stylesheet(p=None):
    p = p or _current
    badges = "".join(
        f"""
        QLabel[badge="{name}"] {{ background:{rgba(p[name], 0.10)}; color:{p[name]};
            border:1px solid {rgba(p[name], 0.45)}; border-radius:0; padding:1px 7px;
            font-family:"{DISPLAY}"; font-size:8.5pt; font-weight:600; }}"""
        for name in ("success", "warning", "danger", "info", "accent")
    )
    weights = {QFont.Bold: 700, QFont.DemiBold: 600, QFont.Medium: 500}
    displays = "".join(f"""
    #{name} {{ font-family:"{DISPLAY}"; font-size:{size}pt; font-weight:{weights.get(weight, 600)}; }}"""
                       for name, (size, weight, _) in DISPLAY_STYLES.items())
    return f"""
    * {{ font-family:"{BODY}","Segoe UI"; font-size:10.5pt; color:{p['text']}; outline:0; }}
    {displays}
    QMainWindow, #Content, QDialog {{ background:{p['bg']}; }}
    QWidget#Transparent, QScrollArea, QScrollArea > QWidget > QWidget {{ background:transparent; }}
    QScrollArea {{ border:none; }}

    #Sidebar {{ background:{p['sidebar']}; border-right:1px solid {p['border']}; }}
    #BrandSub {{ color:{p['faint']}; font-size:8.5pt; font-family:"{DISPLAY}"; }}
    #NavSection {{ color:{p['faint']}; padding:18px 12px 6px 14px; }}
    QPushButton#Nav {{ text-align:left; padding:9px 12px 9px 14px; border:none; border-left:2px solid transparent;
        border-radius:0; color:{p['muted']}; background:transparent; font-family:"{DISPLAY}"; font-size:11pt;
        font-weight:600; }}
    QPushButton#Nav:hover {{ background:{rgba(p['text'], 0.04)}; color:{p['text']}; }}
    QPushButton#Nav:checked {{ background:{rgba(p['accent'], 0.10)}; color:{p['text']};
        border-left:2px solid {p['accent']}; }}
    QPushButton#Nav:disabled {{ color:{p['faint']}; }}

    #TopBar {{ background:{rgba(p['sidebar'], 0.96)}; border-bottom:1px solid {p['border']}; }}
    QPushButton#TopNav {{ background:transparent; border:none; border-bottom:3px solid transparent; border-radius:0;
        padding:21px 14px 18px 14px; color:{p['muted']}; font-family:"{DISPLAY}"; font-size:12pt; font-weight:600; }}
    QPushButton#TopNav:hover {{ color:{p['text']}; background:{rgba(p['text'], 0.03)}; }}
    QPushButton#TopNav:checked {{ color:{p['text']}; border-bottom:3px solid {p['accent']};
        background:{rgba(p['text'], 0.05)}; }}
    #Card {{ background:{rgba(p['surface'], 0.92)}; border:1px solid {p['border']}; border-radius:0; }}
    #Panel {{ background:{rgba(p['text'], 0.94)}; border:none; }}
    #Panel QLabel {{ color:{p['bg']}; }}
    #Card[accent="true"] {{ border:1px solid {rgba(p['accent'], 0.6)}; background:{rgba(p['accent'], 0.05)}; }}
    #Divider {{ background:{p['border']}; max-height:1px; min-height:1px; }}
    #H3 {{ font-size:10.5pt; font-weight:600; }}
    #Muted {{ color:{p['muted']}; }}
    #Faint {{ color:{p['faint']}; font-size:9.5pt; }}
    #Caption, #Eyebrow {{ color:{p['faint']}; }}
    #Eyebrow {{ color:{p['accent']}; }}
    #Mono {{ font-family:"Cascadia Mono","Consolas"; font-size:9pt; color:{p['muted']}; }}
    #Footer {{ background:{p['sidebar']}; border-top:1px solid {p['border']}; }}
    #Footer QLabel {{ color:{p['muted']}; font-size:9pt; font-family:"{DISPLAY}"; }}
    {badges}

    QPushButton {{ background:transparent; border:1px solid {p['border_strong']}; border-radius:0;
        padding:8px 16px; font-family:"{DISPLAY}"; font-weight:600; font-size:10.5pt; color:{p['text']}; }}
    QPushButton:hover {{ background:{rgba(p['text'], 0.06)}; border-color:{p['text']}; }}
    QPushButton:pressed {{ background:{rgba(p['text'], 0.12)}; }}
    QPushButton:disabled {{ color:{p['faint']}; border-color:{p['border']}; }}
    QPushButton#Danger {{ color:{p['danger']}; border-color:{rgba(p['danger'], 0.5)}; }}
    QPushButton#Danger:hover {{ border-color:{p['danger']}; background:{rgba(p['danger'], 0.08)}; }}
    QPushButton#Ghost {{ background:transparent; border:none; color:{p['muted']}; padding:6px 10px; }}
    QPushButton#Ghost:hover {{ color:{p['text']}; }}
    QPushButton#Link {{ background:transparent; border:none; color:{p['accent']}; padding:0; }}
    QPushButton#Link:hover {{ color:{p['accent_hover']}; }}

    #Segmented {{ background:transparent; border:1px solid {p['border_strong']}; border-radius:0; }}
    QPushButton#Segment {{ background:transparent; border:none; border-radius:0; padding:6px 14px;
        color:{p['muted']}; }}
    QPushButton#Segment:hover {{ color:{p['text']}; background:{rgba(p['text'], 0.05)}; }}
    QPushButton#Segment:checked {{ background:{p['text']}; color:{p['bg']}; }}

    QComboBox, QSpinBox, QLineEdit {{ background:{p['surface2']}; border:1px solid {p['border']};
        border-radius:0; padding:6px 10px; min-height:22px; selection-background-color:{p['accent']}; }}
    QComboBox:hover, QSpinBox:hover, QLineEdit:hover {{ border-color:{p['border_strong']}; }}
    QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{ border-color:{p['accent']}; }}
    QComboBox::drop-down {{ border:none; width:26px; }}
    QComboBox::down-arrow {{ image:url("{CHEVRON}"); width:14px; height:14px; margin-right:8px; }}
    QComboBox QAbstractItemView {{ background:{p['surface']}; border:1px solid {p['border_strong']};
        border-radius:0; padding:4px; selection-background-color:{p['surface3']}; selection-color:{p['text']}; }}

    QTabWidget::pane {{ border:none; }}
    QTabBar {{ qproperty-drawBase:0; }}
    QTabBar::tab {{ background:transparent; color:{p['muted']}; padding:9px 2px; margin-right:26px;
        border:none; border-bottom:2px solid transparent; font-family:"{DISPLAY}"; font-weight:600;
        font-size:11pt; }}
    QTabBar::tab:hover {{ color:{p['text']}; }}
    QTabBar::tab:selected {{ color:{p['text']}; border-bottom:2px solid {p['accent']}; }}

    QTreeWidget, QTableWidget, QListWidget, QTextBrowser, QPlainTextEdit {{ background:{p['surface']};
        border:1px solid {p['border']}; border-radius:0; padding:4px; alternate-background-color:{p['surface2']};
        selection-background-color:{p['surface3']}; selection-color:{p['text']}; }}
    QTreeWidget::item, QTableWidget::item {{ padding:7px 4px; border:none; }}
    QHeaderView {{ background:transparent; }}
    QHeaderView::section {{ background:{p['surface']}; color:{p['faint']}; border:none;
        border-bottom:1px solid {p['border']}; padding:8px 6px; font-family:"{DISPLAY}"; font-weight:600;
        font-size:9pt; }}
    QTreeWidget::indicator, QCheckBox::indicator {{ width:15px; height:15px; border-radius:0;
        border:1px solid {p['border_strong']}; background:transparent; }}
    QTreeWidget::indicator:checked, QCheckBox::indicator:checked {{ background:{p['accent']};
        border-color:{p['accent']}; image:url("{CHECK}"); }}
    QCheckBox {{ spacing:8px; }}

    QProgressBar {{ background:{p['surface2']}; border:none; border-radius:0; max-height:4px; }}
    QProgressBar::chunk {{ background:{p['accent']}; }}

    QScrollBar:vertical {{ background:transparent; width:8px; margin:4px 1px; }}
    QScrollBar::handle:vertical {{ background:{p['surface3']}; border-radius:0; min-height:36px; }}
    QScrollBar::handle:vertical:hover {{ background:{p['border_strong']}; }}
    QScrollBar:horizontal {{ background:transparent; height:8px; margin:1px 4px; }}
    QScrollBar::handle:horizontal {{ background:{p['surface3']}; border-radius:0; min-width:36px; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        width:0; height:0; background:none; }}

    QToolTip {{ background:{p['surface2']}; color:{p['text']}; border:1px solid {p['border_strong']};
        padding:6px 8px; border-radius:0; }}
    QMenu {{ background:{p['surface']}; border:1px solid {p['border_strong']}; padding:4px; border-radius:0; }}
    QMenu::item {{ padding:7px 22px 7px 12px; }}
    QMenu::item:selected {{ background:{rgba(p['accent'], 0.14)}; }}
    QMenu::separator {{ height:1px; background:{p['border']}; margin:4px 6px; }}
    QMessageBox QLabel {{ min-width:320px; }}
    #Toast {{ background:{p['surface2']}; border:1px solid {p['border_strong']}; border-left:3px solid {p['accent']};
        border-radius:0; }}
    """
