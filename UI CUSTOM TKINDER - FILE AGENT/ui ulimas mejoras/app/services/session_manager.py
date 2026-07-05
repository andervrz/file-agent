# app/services/session_manager.py
"""
services/session_manager.py — Gestión de sesiones y reconstrucción de contexto.

Responsabilidades:
  - CRUD de sesiones en SQLite (session_metadata + conversation_turns)
  - Carga de historial completo para reconstruir chat UI
  - Rebuild de contexto del harness al cambiar de sesión
  - Compaction automática de episodic memory cada N turnos
  - Conteo REAL de turns (no cacheado en metadata)
  - get_recent_turns() para /traces command

CAMBIO (v2.1): Usa list_sessions_with_stats() y get_session_with_stats()
del store para eliminar N+1 queries y JSON parsing en Python.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from agent.loop.harness import AgentHarness
from agent.memory.store import TinyDBMemoryStore
from agent.memory.models_sqlmodel import ConversationTurn

from ..theme import SessionItem, ChatMessage, ToolCallItem

logger = logging.getLogger(__name__)

# Compaction: cada cuántos turnos resumir historial antiguo
_COMPACTION_INTERVAL = 20


class SessionManager:
    """
    Gestiona el ciclo de vida de sesiones y la reconstrucción de contexto.
    """

    def __init__(self, memory_store: TinyDBMemoryStore, harness: AgentHarness) -> None:
        self._store = memory_store
        self._harness = harness
        self._current_session_id: str | None = None

    # ── Creación ─────────────────────────────────────────────────────────────

    async def create_session(self, title: str | None = None) -> SessionItem:
        """Crea una nueva sesión activa en SQLite y retorna el item UI."""
        session_id = str(uuid.uuid4())
        default_title = title or f"Session {datetime.now(timezone.utc).strftime('%H:%M')}"

        if self._store._enabled:
            await self._store.create_session(
                session_id=session_id,
                title=default_title,
                description="",
            )

        self._current_session_id = session_id
        logger.info("Session created: %s", session_id)

        return SessionItem(
            session_id=session_id,
            title=default_title,
            status="active",
            total_turns=0,
            total_tools=0,
            total_errors=0,
            tokens_in=0,
            tokens_out=0,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    async def get_or_create_empty_session(self) -> SessionItem:
        """Reusa una sesión activa con 0 turnos, o crea una nueva."""
        if self._store._enabled:
            empty = await self._store.get_empty_active_session()
            if empty:
                logger.info("Reusing empty session: %s", empty.session_id)
                self._current_session_id = empty.session_id
                return SessionItem(
                    session_id=empty.session_id,
                    title=empty.title or "Session",
                    status="active",
                    total_turns=0,
                    total_tools=0,
                    total_errors=0,
                    tokens_in=0,
                    tokens_out=0,
                    updated_at=empty.updated_at or empty.created_at,
                )
        return await self.create_session()

    # ── Listado (batch — N+1 eliminado) ────────────────────────────────────

    async def list_sessions(self, status: str = "active") -> list[SessionItem]:
        """Lista sesiones con stats REALES en una sola query."""
        if not self._store._enabled:
            return []

        # NUEVO: usar batch query del store (1 query vs N+1)
        rows = await self._store.list_sessions_with_stats(status=status, limit=100)
        return [_row_to_session_item(r) for r in rows]

    async def list_archived_sessions(self) -> list[SessionItem]:
        """Lista sesiones archivadas (papelera)."""
        return await self.list_sessions(status="archived")

    async def get_session(self, session_id: str) -> Optional[SessionItem]:
        """Retorna un item de sesión por ID con conteo REAL (1 query)."""
        if not self._store._enabled:
            return None

        # NUEVO: usar batch query del store
        row = await self._store.get_session_with_stats(session_id)
        if row is None:
            return None

        return _row_to_session_item(row)

    # ── NUEVO: retornar últimos N turns crudos ───────────────────────────────
    async def get_recent_turns(self, session_id: str, limit: int = 5) -> list[ConversationTurn]:
        """Retorna los últimos N turns de una sesión, ordenados cronológicamente."""
        if not self._store._enabled:
            return []
        turns = await self._store.get_conversation_turns(session_id)
        return turns[-limit:] if turns else []

    # ── Carga de historial ─────────────────────────────────────────────────────

    async def load_session_history(self, session_id: str) -> list[ChatMessage]:
        """
        Reconstruye el historial completo de chat de una sesión.
        Útil para renderizar el chat al cambiar de sesión.
        """
        if not self._store._enabled:
            return []

        turns = await self._store.get_conversation_turns(session_id)
        messages: list[ChatMessage] = []

        for turn in turns:
            # Mensaje del usuario
            messages.append(ChatMessage(
                sender="user",
                content=turn.user_message,
                timestamp=turn.timestamp[:16] if turn.timestamp else "",
            ))

            # Tool calls si hubo
            tool_calls = self._parse_tool_calls(turn.tool_calls)
            if tool_calls:
                messages.append(ChatMessage(
                    sender="tool",
                    content="",
                    timestamp=turn.timestamp[:16] if turn.timestamp else "",
                    tool_calls=tool_calls,
                ))

            # Respuesta del agente
            messages.append(ChatMessage(
                sender="agent",
                content=turn.response,
                timestamp=turn.timestamp[:16] if turn.timestamp else "",
            ))

        return messages

    def _parse_tool_calls(self, tool_calls_json: str) -> list[ToolCallItem]:
        """Parsea el JSON de tool_calls de conversation_turns."""
        try:
            raw = json.loads(tool_calls_json or "[]")
            items: list[ToolCallItem] = []
            for tc in raw:
                items.append(ToolCallItem(
                    name=tc.get("name", "unknown"),
                    duration_ms=tc.get("duration_ms", 0),
                    is_error=tc.get("is_error", False),
                    summary=self._format_tool_summary(tc),
                ))
            return items
        except Exception:
            return []

    @staticmethod
    def _format_tool_summary(tc: dict) -> str:
        """Genera un resumen legible del input del tool."""
        name = tc.get("name", "")
        inp = tc.get("input", {})
        if name in ("list_directory", "read_file", "create_directory"):
            return str(inp.get("path", ""))
        if name in ("move_file", "copy_file"):
            src = inp.get("source", "")
            dst = inp.get("destination", "")
            return f"{src} → {dst}"
        if name == "run_command":
            return str(inp.get("command", ""))[:50]
        if inp:
            return str(list(inp.values())[0])[:50]
        return name

    # ── Rebuild de contexto ────────────────────────────────────────────────

    async def rebuild_context(self, session_id: str, max_turns: int = 10) -> None:
        """
        Carga los últimos N turnos de una sesión al harness para continuar
        la conversación con contexto.
        """
        if not self._store._enabled:
            self._current_session_id = session_id
            return

        # Resetear contexto actual
        self._harness.reset()

        turns = await self._store.get_conversation_turns(session_id)
        if not turns:
            self._current_session_id = session_id
            return

        # Tomar los últimos max_turns turnos
        recent = turns[-max_turns:]

        for turn in recent:
            # Reconstruir mensajes en el contexto del harness
            self._harness._context.add_user_message(turn.user_message)

            # Si hay tool calls, reconstruir tool results (simplificado)
            tool_calls = self._parse_tool_calls(turn.tool_calls)
            for tc in tool_calls:
                from agent.tools.base import ToolResult
                self._harness._context.add_tool_results([
                    ToolResult(
                        tool_use_id="rebuilt",
                        content=tc.summary,
                        is_error=tc.is_error,
                        tool_name=tc.name,
                    )
                ])

            # Respuesta del agente
            self._harness._context.add_assistant_response(turn.response)

        self._current_session_id = session_id
        logger.info("Context rebuilt for session %s with %d turns", session_id, len(recent))

    # ── Archivar / Renombrar / Eliminar ────────────────────────────────────

    async def archive_session(self, session_id: str) -> bool:
        """Archiva una sesión."""
        if not self._store._enabled:
            return False
        ok = await self._store.archive_session(session_id)
        if ok and self._current_session_id == session_id:
            self._current_session_id = None
        return ok

    async def rename_session(self, session_id: str, new_title: str) -> bool:
        """Renombra una sesión."""
        if not self._store._enabled:
            return False
        return await self._store.update_session_stats(
            session_id=session_id,
            title=new_title,
        )

    async def delete_session(self, session_id: str) -> bool:
        """Elimina físicamente una sesión y todos sus datos."""
        if not self._store._enabled:
            return False
        ok = await self._store.delete_session(session_id)
        if ok and self._current_session_id == session_id:
            self._current_session_id = None
        return ok

    # ── Compaction automática ────────────────────────────────────────────────

    async def maybe_compact(self, session_id: str) -> bool:
        """
        Si una sesión tiene múltiplos de _COMPACTION_INTERVAL turnos,
        genera un summary de los turnos antiguos y los marca como compactados.
        Retorna True si se ejecutó compaction.
        """
        if not self._store._enabled:
            return False

        last_turn = await self._store.get_last_turn_number(session_id)
        if last_turn < _COMPACTION_INTERVAL:
            return False

        # Solo compactar si es múltiplo exacto del intervalo
        if last_turn % _COMPACTION_INTERVAL != 0:
            return False

        logger.info("Compaction triggered for session %s at turn %d", session_id, last_turn)
        # TODO: Implementar compaction con LLM summary
        return False

    # ── Propiedades ──────────────────────────────────────────────────────────

    @property
    def current_session_id(self) -> str | None:
        return self._current_session_id

    def set_current_session(self, session_id: str) -> None:
        self._current_session_id = session_id


# ─── Helper: row dict → SessionItem ─────────────────────────────────────────

def _row_to_session_item(row: dict) -> SessionItem:
    """Convierte un row dict del store batch query en SessionItem."""
    return SessionItem(
        session_id=row["session_id"],
        title=row["title"] or "Untitled",
        status=row["status"],
        total_turns=row["total_turns"],
        total_tools=row["total_tools"],
        total_errors=row["total_errors"],
        tokens_in=row["tokens_in"],
        tokens_out=row["tokens_out"],
        updated_at=row["updated_at"] or row["created_at"],
    )
