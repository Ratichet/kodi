
COLORS = {
    "bg_dark": "#121212",
    "bg_sidebar": "#1a1a2e",
    "bg_content": "#16213e",
    "bg_card": "#1e2a4a",
    "bg_card_hover": "#2a3a5c",
    "bg_input": "#0f1629",
    "accent": "#e94560",
    "accent_hover": "#ff6b81",
    "text_primary": "#eaeaea",
    "text_secondary": "#8892a0",
    "text_muted": "#556070",
    "border": "#2a3450",
    "success": "#2ed573",
    "warning": "#ffa502",
    "scrollbar_bg": "#1a1a2e",
    "scrollbar_handle": "#3a4a6c",
}

DARK_THEME = """
/* === Global === */
QMainWindow {{
    background-color: {bg_dark};
    color: {text_primary};
}}

QWidget {{
    color: {text_primary};
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}}

/* === Sidebar === */
QWidget#sidebar {{
    background-color: {bg_sidebar};
    border-right: 1px solid {border};
}}

QPushButton#nav_button {{
    background-color: transparent;
    color: {text_secondary};
    border: none;
    border-radius: 8px;
    padding: 12px 16px;
    text-align: left;
    font-size: 14px;
    font-weight: 500;
}}

QPushButton#nav_button:hover {{
    background-color: {bg_card};
    color: {text_primary};
}}

QPushButton#nav_button[active="true"] {{
    background-color: {accent};
    color: white;
    font-weight: 600;
}}

/* === Content Area === */
QWidget#content_area {{
    background-color: {bg_content};
}}

/* === Labels === */
QLabel#section_title {{
    color: {text_primary};
    font-size: 20px;
    font-weight: 700;
    padding: 8px 0px;
}}

QLabel#page_title {{
    color: {text_primary};
    font-size: 26px;
    font-weight: 700;
    padding: 4px 0px;
}}

QLabel#subtitle {{
    color: {text_secondary};
    font-size: 12px;
}}

QLabel#logo_label {{
    color: {accent};
    font-size: 22px;
    font-weight: 800;
}}

/* === Poster Card === */
QFrame#poster_card {{
    background-color: {bg_card};
    border-radius: 8px;
    border: 2px solid transparent;
}}

QFrame#poster_card:hover {{
    background-color: {bg_card_hover};
    border: 2px solid {accent};
}}

QLabel#card_title {{
    color: {text_primary};
    font-size: 12px;
    font-weight: 600;
    padding: 4px 6px 0px 6px;
}}

QLabel#card_subtitle {{
    color: {text_secondary};
    font-size: 11px;
    padding: 0px 6px 6px 6px;
}}

/* === Search Bar === */
QLineEdit#search_bar {{
    background-color: {bg_input};
    color: {text_primary};
    border: 1px solid {border};
    border-radius: 20px;
    padding: 10px 20px;
    font-size: 14px;
    selection-background-color: {accent};
}}

QLineEdit#search_bar:focus {{
    border: 1px solid {accent};
}}

QLineEdit#search_bar::placeholder {{
    color: {text_muted};
}}

/* === Buttons === */
QPushButton#primary_button {{
    background-color: {accent};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 10px 24px;
    font-size: 14px;
    font-weight: 600;
}}

QPushButton#primary_button:hover {{
    background-color: {accent_hover};
}}

QPushButton#primary_button:pressed {{
    background-color: {accent};
}}

QPushButton#secondary_button {{
    background-color: {bg_card};
    color: {text_primary};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 13px;
}}

QPushButton#secondary_button:hover {{
    background-color: {bg_card_hover};
    border-color: {text_secondary};
}}

QPushButton#icon_button {{
    background-color: transparent;
    color: {text_secondary};
    border: none;
    border-radius: 4px;
    padding: 6px;
    font-size: 16px;
}}

QPushButton#icon_button:hover {{
    background-color: {bg_card};
    color: {text_primary};
}}

/* === Combo Box / Filters === */
QComboBox {{
    background-color: {bg_input};
    color: {text_primary};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
    min-width: 120px;
}}

QComboBox:hover {{
    border-color: {text_secondary};
}}

QComboBox::drop-down {{
    border: none;
    width: 30px;
}}

QComboBox QAbstractItemView {{
    background-color: {bg_card};
    color: {text_primary};
    border: 1px solid {border};
    selection-background-color: {accent};
    selection-color: white;
}}

/* === Scroll Areas === */
QScrollArea {{
    border: none;
    background-color: transparent;
}}

QScrollArea > QWidget > QWidget {{
    background-color: transparent;
}}

QScrollBar:vertical {{
    background-color: {scrollbar_bg};
    width: 8px;
    margin: 0px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical {{
    background-color: {scrollbar_handle};
    min-height: 30px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {text_secondary};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background-color: {scrollbar_bg};
    height: 6px;
    margin: 0px;
    border-radius: 3px;
}}

QScrollBar::handle:horizontal {{
    background-color: {scrollbar_handle};
    min-width: 30px;
    border-radius: 3px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {text_secondary};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* === Slider (Player) === */
QSlider::groove:horizontal {{
    background-color: {bg_input};
    height: 4px;
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    background-color: {accent};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}

QSlider::handle:horizontal:hover {{
    background-color: {accent_hover};
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}}

QSlider::sub-page:horizontal {{
    background-color: {accent};
    border-radius: 2px;
}}

/* === Progress Bar === */
QProgressBar {{
    background-color: {bg_input};
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}}

QProgressBar::chunk {{
    background-color: {accent};
    border-radius: 4px;
}}

/* === Player Controls === */
QWidget#player_controls {{
    background-color: rgba(18, 18, 18, 220);
}}

/* === Settings === */
QListWidget {{
    background-color: {bg_input};
    color: {text_primary};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px;
    font-size: 13px;
}}

QListWidget::item {{
    padding: 8px 12px;
    border-radius: 4px;
}}

QListWidget::item:selected {{
    background-color: {accent};
    color: white;
}}

QListWidget::item:hover {{
    background-color: {bg_card};
}}

/* === Empty State === */
QLabel#empty_state {{
    color: {text_muted};
    font-size: 16px;
    font-weight: 500;
    padding: 40px;
}}
""".format(**COLORS)


def get_dark_theme() -> str:
    """Returns the dark theme QSS."""
    return DARK_THEME