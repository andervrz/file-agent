# app/theme.py
"""
theme.py — Colores, fuentes, tags CTkTextbox y dataclasses UI para File Agent.

Soporta modo claro/oscuro dinámico via tuple colors de CustomTkinter.
Los tags de tkinter.Text usan colores estáticos; se recrean al cambiar tema.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

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
FONT_STATS = (FONT_FAMILY, 11, "italic")

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

TAG_USER = "user"
TAG_AGENT = "agent"
TAG_TOOL = "tool"
TAG_ERROR = "error"
TAG_SYSTEM = "system"
TAG_TIMESTAMP = "timestamp"
TAG_SENDER = "sender"
TAG_STATS = "stats"        # ← NUEVO: línea de tokens/duración

# Colores estáticos para modo CLARO (default)
_TAG_COLORS_LIGHT = {
    TAG_USER: "#2563EB",
    TAG_AGENT: "#059669",
    TAG_TOOL: "#D97706",
    TAG_ERROR: "#DC2626",
    TAG_SYSTEM: "#6B7280",
    TAG_TIMESTAMP: "#9CA3AF",
    TAG_SENDER: "#374151",
    TAG_STATS: "#6B7280",   # ← NUEVO
}

# Colores estáticos para modo OSCURO
_TAG_COLORS_DARK = {
    TAG_USER: "#60A5FA",
    TAG_AGENT: "#34D399",
    TAG_TOOL: "#FBBF24",
    TAG_ERROR: "#F87171",
    TAG_SYSTEM: "#9CA3AF",
    TAG_TIMESTAMP: "#6B7280",
    TAG_SENDER: "#E5E7EB",
    TAG_STATS: "#9CA3AF",   # ← NUEVO
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

# ─── Dataclasses UI ─────────────────────────────────────────────────────────

@dataclass
class ToolCallItem:
    """Representación visual de un tool call en el chat."""
    name: str
    duration_ms: int
    is_error: bool
    summary: str


@dataclass
class ChatMessage:
    """Mensaje en el chat UI — puede ser user, agent, tool o system."""
    sender: str  # "user" | "agent" | "tool" | "system"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%H:%M"))
    tool_calls: list[ToolCallItem] | None = None
    # ← NUEVO: métricas del turno (solo para mensajes del agente)
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0
    llm_calls: int = 0


@dataclass
class SessionItem:
    """Item de sesión para el sidebar — datos + callback de selección."""
    session_id: str
    title: str
    status: str  # "active" | "archived"
    total_turns: int
    total_tools: int
    total_errors: int
    updated_at: str
    # ← NUEVO: métricas acumuladas
    tokens_in: int = 0
    tokens_out: int = 0
    on_select: Callable[[], None] | None = None
    on_archive: Callable[[], None] | None = None
    on_rename: Callable[[], None] | None = None
    on_delete: Callable[[], None] | None = None  # ← NUEVO

    @property
    def short_id(self) -> str:
        return self.session_id[:8]

    @property
    def relative_time(self) -> str:
        """Retorna 'Today', 'Yesterday', o fecha formateada."""
        try:
            dt = datetime.fromisoformat(self.updated_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            delta = now - dt
            if delta.days == 0:
                return "Today"
            elif delta.days == 1:
                return "Yesterday"
            elif delta.days < 7:
                return f"{delta.days} days ago"
            else:
                return dt.strftime("%d %b")
        except Exception:
            return ""

    @property
    def display_title(self) -> str:
        """Título truncado para el sidebar."""
        return self.title[:35] + "…" if len(self.title) > 35 else self.title
