"""Material Design icons rendered inline from SVG at startup.

Keeps them in-source (no extra files to install) and theme-independent
(the on-target icon theme may lack the names we'd otherwise look up).
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


# All glyphs use the Material Design 24x24 viewBox; we recolour at render
# time rather than committing per-palette variants.
_SVGS: dict[str, str] = {
    "network": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path fill="{color}" d="M15,20A1,1 0 0,0 14,19H13V17H17A2,2 0 0,0'
        ' 19,15V5A2,2 0 0,0 17,3H7A2,2 0 0,0 5,5V15A2,2 0 0,0 7,17H11V19H10A1,1'
        ' 0 0,0 9,20H2V22H9A1,1 0 0,0 10,23H14A1,1 0 0,0 15,22H22V20H15M7,15V5H17V15H7Z"/>'
        '</svg>'
    ),
    "usb": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path fill="{color}" d="M8 13C9.66 13 11 14.34 11 16C11 17.66 9.66 19 8 19C6.34'
        ' 19 5 17.66 5 16C5 14.34 6.34 13 8 13M8 15C7.45 15 7 15.45 7 16C7 16.55 7.45 17'
        ' 8 17C8.55 17 9 16.55 9 16C9 15.45 8.55 15 8 15M9.77 4.33L10.5 5.08L14.29'
        ' 1.29C14.47 1.11 14.72 1 15 1C15.28 1 15.53 1.11 15.71 1.29L22.78 8.36L22.78'
        ' 8.37C22.92 8.54 23 8.76 23 9C23 9.3 22.87 9.57 22.66 9.76L22.66 9.76L18.93'
        ' 13.5L19.67 14.23L12.95 20.95C11.68 22.22 9.93 23 8 23C4.13 23 1 19.87 1 16C1'
        ' 14.07 1.78 12.32 3.05 11.05L9.77 4.33M11.54 19.54L16.84 14.23L9.77 7.16L4.46'
        ' 12.46C3.56 13.37 3 14.62 3 16C3 18.76 5.24 21 8 21C9.38 21 10.63 20.44 11.54'
        ' 19.54M15.07 4.69L16.5 6.1L15.07 7.5L13.66 6.1L15.07 4.69M17.9 7.5L19.31'
        ' 8.93L17.9 10.34L16.5 8.93L17.9 7.5M20.59 9L15 3.41L11.93 6.5L17.5 12.08L20.59 9Z"/>'
        '</svg>'
    ),
    "recent": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path fill="{color}" d="M12,20A8,8 0 0,0 20,12A8,8 0 0,0 12,4A8,8 0 0,0'
        ' 4,12A8,8 0 0,0 12,20M12,2A10,10 0 0,1 22,12A10,10 0 0,1 12,22C6.47,22'
        ' 2,17.5 2,12A10,10 0 0,1 12,2M12.5,7V12.25L17,14.92L16.25,16.15L11,13V7H12.5Z"/>'
        '</svg>'
    ),
    "home": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path fill="{color}" d="M10,20V14H14V20H19V12H22L12,3L2,12H5V20H10Z"/>'
        '</svg>'
    ),
    "folder": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path fill="{color}" d="M10,4H4C2.89,4 2,4.89 2,6V18A2,2 0 0,0'
        ' 4,20H20A2,2 0 0,0 22,18V8C22,6.89 21.1,6 20,6H12L10,4Z"/>'
        '</svg>'
    ),
}


@lru_cache(maxsize=None)
def icon(name: str, size: int = 32, color: str = "#2c2c2c") -> QIcon:
    """Return a QIcon rendered from the named Material Design glyph."""
    svg = _SVGS[name].format(color=color).encode("utf-8")
    renderer = QSvgRenderer(QByteArray(svg))
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    return QIcon(pixmap)
