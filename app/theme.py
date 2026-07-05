"""
app/theme.py — Colores, fuentes, tags CTkTextbox y constantes UI para File Agent.

Soporta modo claro/oscuro dinámico via tuple colors de CustomTkinter.
Los tags de tkinter.Text usan colores estáticos; se recrean al cambiar tema.

NOTA: SessionItem, ChatMessage, ToolCallItem movidos a app/entities.py
"""
from __future__ import annotations

import sys

# ─── Fonts ──────────────────────────────────────────────────────────────────

FONT_FAMILY = "SF Pro Display" if sys.platform == "darwin" else "Segoe UI"

FONT_TITLE = (FONT_FAMILY, 20, "bold")
FONT_SUBTITLE = (FONT_FAMILY, 12)
FONT_BODY = (FONT_FAMILY, 14)
FONT_BODY_BOLD = (FONT_FAMILY, 14, "bold")
FONT_SMALL = (FONT_FAMILY, 12)
FONT_SMALL_BOLD = (FONT_FAMILY, 12, "bold")
FONT_TINY = (FONT_FAMILY, 11)
FONT_BUTTON = (FONT_FAMILY, 13, "bold")

# ─── Tuple Colors (light, dark) — CustomTkinter auto-switch ─────────────────

COLOR_BG_PRIMARY = ("gray95", "gray13")       # fondo principal
COLOR_BG_SECONDARY = ("gray90", "gray17")     # sidebar, panels
COLOR_BG_TERTIARY = ("gray85", "gray20")      # hover, selected
COLOR_TEXT_PRIMARY = ("gray10", "gray90")     # texto principal
COLOR_TEXT_SECONDARY = ("gray40", "gray60")   # subtítulos, timestamps
COLOR_TEXT_MUTED = ("gray50", "gray50")       # deshabilitado

COLOR_ACCENT = ("#3B82F6", "#60A5FA")       # azul — user messages
COLOR_SUCCESS = ("#10B981", "#34D399")      # verde — agent messages
COLOR_WARNING = ("#F59E0B", "#FBBF24")      # naranja — tools
COLOR_ERROR = ("#EF4444", "#F87171")        # rojo — errores
COLOR_INFO = ("#6B7280", "#9CA3AF")         # gris — system

COLOR_BORDER = ("gray75", "gray25")
COLOR_PANEL_BG = ("gray92", "gray15")

# ─── Tags para CTkTextbox (tkinter.Text subyacente) ─────────────────────────
# NOTA: tkinter.Text NO soporta tuple colors. Los colores estáticos deben
# recrearse al cambiar de tema. Ver ChatArea._recreate_tags()

TAG_USER = "user"
TAG_AGENT = "agent"
TAG_TOOL = "tool"
TAG_ERROR = "error"
TAG_SYSTEM = "system"
TAG_TIMESTAMP = "timestamp"
TAG_SENDER = "sender"

# Colores estáticos para modo CLARO (default)
_TAG_COLORS_LIGHT = {
    TAG_USER: "#2563EB",      # azul más oscuro
    TAG_AGENT: "#059669",     # verde más oscuro
    TAG_TOOL: "#D97706",      # naranja más oscuro
    TAG_ERROR: "#DC2626",     # rojo más oscuro
    TAG_SYSTEM: "#6B7280",    # gris
    TAG_TIMESTAMP: "#9CA3AF", # gris claro
    TAG_SENDER: "#374151",    # gris oscuro
}

# Colores estáticos para modo OSCURO
_TAG_COLORS_DARK = {
    TAG_USER: "#60A5FA",      # azul claro
    TAG_AGENT: "#34D399",     # verde claro
    TAG_TOOL: "#FBBF24",      # naranja claro
    TAG_ERROR: "#F87171",     # rojo claro
    TAG_SYSTEM: "#9CA3AF",    # gris claro
    TAG_TIMESTAMP: "#6B7280", # gris medio
    TAG_SENDER: "#E5E7EB",    # gris muy claro
}


def get_tag_colors(appearance_mode: str) -> dict[str, str]:
    """Retorna el mapa de colores de tags según el modo actual."""
    if appearance_mode.lower() == "dark":
        return _TAG_COLORS_DARK
    return _TAG_COLORS_LIGHT


# ─── Dimensiones UI ─────────────────────────────────────────────────────────

WIDTH = 1200
HEIGHT = 800
SIDEBAR_W = 280
INPUT_H = 70
TOOL_PANEL_H = 120
