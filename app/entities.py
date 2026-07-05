"""
app/entities.py — Dataclasses de dominio para la UI.

Movidas desde theme.py para separar modelo de datos de constantes de presentación.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable


@dataclass
class ToolCallItem:
    """Representación visual de un tool call en el chat."""
    name: str
    duration_ms: int
    is_error: bool
    summary: str  # ej: "backup → /home/docs"


@dataclass
class ChatMessage:
    """Mensaje en el chat UI — puede ser user, agent, tool o system."""
    sender: str  # "user" | "agent" | "tool" | "system"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%H:%M"))
    tool_calls: list[ToolCallItem] | None = None
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class SessionItem:
    """Item de sesión para el sidebar — datos + callback de selección."""
    session_id: str
    title: str
    status: str  # "active" | "archived"
    total_turns: int
    total_tools: int
    total_errors: int
    tokens_in: int = 0
    tokens_out: int = 0
    updated_at: str = ""
    on_select: Callable[[], None] | None = None
    on_archive: Callable[[], None] | None = None
    on_rename: Callable[[], None] | None = None
    on_delete: Callable[[], None] | None = None

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
