# app/services/session_manager.py
"""
services/session_manager.py — Session management and context rebuilding.

FIXES:
  - Real turn counter from conversation_turns (not session_metadata cache)
  - Physical delete of archived sessions
  - Archived panel
  - asyncio.to_thread() instead of _loop.run_in_executor()
  - rename_session updates title (not description)
"""
from __future__ import annotations

import json
import logging
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import func, select

from agent.loop.harness import AgentHarness
from agent.memory.store import SQLiteMemoryStore
from agent.memory.models_sqlmodel import ConversationTurn, SessionMetadata

from ..theme import SessionItem, ChatMessage, ToolCallItem

logger = logging.getLogger(__name__)

_COMPACTION_INTERVAL = 20


class SessionManager:
    """
    Manages session lifecycle and context rebuilding.
    """

    def __init__(self, memory_store: SQLiteMemoryStore, harness: AgentHarness) -> None:
        self._store = memory_store
        self._harness = harness
        self._current_session_id: str | None = None

    # ── Creation ─────────────────────────────────────────────────────────────

    async def create_session(self, title: str | None = None) -> SessionItem:
        """Creates a new active session in SQLite and returns the UI item."""
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
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    # ── Listing ──────────────────────────────────────────────────────────────

    async def list_sessions(self, status: str = "active") -> list[SessionItem]:
        """Lists sessions with REAL turn count from conversation_turns."""
        if not self._store._enabled:
            return []

        sessions = await self._store.list_sessions(status=status, limit=100)
        items: list[SessionItem] = []

        for meta in sessions:
            real_turns = await self._count_turns(meta.session_id)
            real_tools = await self._count_tools(meta.session_id)
            tokens = await self._sum_tokens(meta.session_id)

            items.append(SessionItem(
                session_id=meta.session_id,
                title=meta.title or "Untitled",
                status=meta.status,
                total_turns=real_turns,
                total_tools=real_tools,
                total_errors=meta.total_errors,
                updated_at=meta.updated_at or meta.created_at,
                tokens_in=tokens["in"],
                tokens_out=tokens["out"],
            ))

        return items

    async def _count_turns(self, session_id: str) -> int:
        """Counts real turns from conversation_turns."""
        if not self._store._enabled:
            return 0

        def _read():
            with self._store._engine.connect() as conn:
                result = conn.execute(
                    select(func.count(ConversationTurn.id))
                    .where(ConversationTurn.session_id == session_id)
                ).scalar()
                return result or 0

        return await asyncio.to_thread(_read)

    async def _count_tools(self, session_id: str) -> int:
        """Counts tools executed in the session."""
        if not self._store._enabled:
            return 0
        turns = await self._store.get_conversation_turns(session_id)
        return sum(turn.total_tool_calls for turn in turns)

    async def _sum_tokens(self, session_id: str) -> dict[str, int]:
        """Sums tokens_in and tokens_out from all turns."""
        if not self._store._enabled:
            return {"in": 0, "out": 0}
        turns = await self._store.get_conversation_turns(session_id)
        total_in = sum(
            sum(c["tokens_in"] for c in json.loads(turn.llm_calls or "[]"))
            for turn in turns
        )
        total_out = sum(
            sum(c["tokens_out"] for c in json.loads(turn.llm_calls or "[]"))
            for turn in turns
        )
        return {"in": total_in, "out": total_out}

    async def get_session(self, session_id: str) -> Optional[SessionItem]:
        """Returns a session item by ID with real count."""
        if not self._store._enabled:
            return None

        meta = await self._store.get_session(session_id)
        if not meta:
            return None

        real_turns = await self._count_turns(session_id)
        real_tools = await self._count_tools(session_id)
        tokens = await self._sum_tokens(session_id)

        return SessionItem(
            session_id=meta.session_id,
            title=meta.title or "Untitled",
            status=meta.status,
            total_turns=real_turns,
            total_tools=real_tools,
            total_errors=meta.total_errors,
            updated_at=meta.updated_at or meta.created_at,
            tokens_in=tokens["in"],
            tokens_out=tokens["out"],
        )

    # ── History loading ─────────────────────────────────────────────────────

    async def load_session_history(self, session_id: str) -> list[ChatMessage]:
        """Rebuilds the full chat history of a session."""
        if not self._store._enabled:
            return []

        turns = await self._store.get_conversation_turns(session_id)
        messages: list[ChatMessage] = []

        for turn in turns:
            messages.append(ChatMessage(
                sender="user",
                content=turn.user_message,
                timestamp=turn.timestamp[:16] if turn.timestamp else "",
            ))

            tool_calls = self._parse_tool_calls(turn.tool_calls)
            if tool_calls:
                messages.append(ChatMessage(
                    sender="tool",
                    content="",
                    timestamp=turn.timestamp[:16] if turn.timestamp else "",
                    tool_calls=tool_calls,
                ))

            llm_calls = json.loads(turn.llm_calls or "[]")
            tokens_in = sum(c.get("tokens_in", 0) for c in llm_calls)
            tokens_out = sum(c.get("tokens_out", 0) for c in llm_calls)

            messages.append(ChatMessage(
                sender="agent",
                content=turn.response,
                timestamp=turn.timestamp[:16] if turn.timestamp else "",
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                duration_ms=turn.duration_ms,
                llm_calls=len(llm_calls),
            ))

        return messages

    def _parse_tool_calls(self, tool_calls_json: str) -> list[ToolCallItem]:
        """Parses tool_calls JSON from conversation_turns."""
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
        """Generates a readable summary of tool input."""
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

    # ── Context rebuild ────────────────────────────────────────────────

    async def rebuild_context(self, session_id: str, max_turns: int = 10) -> None:
        """Loads the last N turns of a session into the harness."""
        if not self._store._enabled:
            self._current_session_id = session_id
            return

        self._harness.reset()

        turns = await self._store.get_conversation_turns(session_id)
        if not turns:
            self._current_session_id = session_id
            return

        recent = turns[-max_turns:]

        for turn in recent:
            self._harness._context.add_user_message(turn.user_message)

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

            self._harness._context.add_assistant_response(turn.response)

        self._current_session_id = session_id
        logger.info("Context rebuilt for session %s with %d turns", session_id, len(recent))

    # ── Archive / Rename / Delete ─────────────────────────────────────

    async def archive_session(self, session_id: str) -> bool:
        """Archives a session."""
        if not self._store._enabled:
            return False
        ok = await self._store.archive_session(session_id)
        if ok and self._current_session_id == session_id:
            self._current_session_id = None
        return ok

    async def rename_session(self, session_id: str, new_title: str) -> bool:
        """Renames a session (updates title)."""
        if not self._store._enabled:
            return False
        return await self._store.update_session_stats(
            session_id=session_id,
            title=new_title,
        )

    async def delete_session(self, session_id: str) -> bool:
        """
        Physically deletes a session and all its data.
        ONLY for archived sessions.
        """
        if not self._store._enabled:
            return False

        meta = await self._store.get_session(session_id)
        if not meta or meta.status != "archived":
            logger.warning("Cannot delete non-archived session %s", session_id)
            return False

        return await self._store.delete_session_data(session_id)

    # ── Automatic compaction ────────────────────────────────────────────────

    async def maybe_compact(self, session_id: str) -> bool:
        """If a session has multiples of _COMPACTION_INTERVAL turns..."""
        if not self._store._enabled:
            return False

        last_turn = await self._store.get_last_turn_number(session_id)
        if last_turn < _COMPACTION_INTERVAL:
            return False

        if last_turn % _COMPACTION_INTERVAL != 0:
            return False

        logger.info("Compaction triggered for session %s at turn %d", session_id, last_turn)
        return False

    # ── Properties ──────────────────────────────────────────────────────────

    @property
    def current_session_id(self) -> str | None:
        return self._current_session_id

    def set_current_session(self, session_id: str) -> None:
        self._current_session_id = session_id
