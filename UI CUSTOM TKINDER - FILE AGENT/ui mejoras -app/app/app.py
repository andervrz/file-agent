"""
app.py — FileAgentApp: CTk orchestrator + state.

Responsibilities:
  - Initialize CustomTkinter and main layout
  - Coordinate sidebar, chat_area, input_bar, dialogs
  - Manage session lifecycle via SessionManager
  - Async bridge for agent communication
  - React to theme changes
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from typing import Callable, TypeVar

import customtkinter as ctk

from agent.main import bootstrap
from agent.core.config import AgentConfig

from .theme import (
    WIDTH,
    HEIGHT,
    FONT_TITLE,
    COLOR_BG_PRIMARY,
    COLOR_TEXT_PRIMARY,
    ChatMessage,
    ToolCallItem,
    SessionItem,
)
from .bridge import AsyncBridge
from .services.session_manager import SessionManager
from .services.memory_service import MemoryService
from .widgets.sidebar import Sidebar
from .widgets.chat_area import ChatArea
from .widgets.input_bar import InputBar
from .widgets.session_dialog import SessionDialog
from .widgets.command_palette import CommandPalette

logger = logging.getLogger(__name__)

T = TypeVar("T")


class FileAgentApp(ctk.CTk):
    """
    Main File Agent application with CustomTkinter.
    """

    def __init__(self) -> None:
        super().__init__()

        # ── CustomTkinter Config ──────────────────────────────────
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.title("File Agent — v2.0.0")
        self.geometry(f"{WIDTH}x{HEIGHT}")
        self.minsize(900, 600)

        # Main grid
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── State ───────────────────────────────────────────────────────
        self._config: AgentConfig | None = None
        self._session_manager: SessionManager | None = None
        self._memory_service: MemoryService | None = None
        self._bridge = AsyncBridge()
        self._current_session: SessionItem | None = None
        self._skills_count: int = 0
        self._ui_built: bool = False

        # ── Widgets ──────────────────────────────────────────────────────
        self._sidebar: Sidebar | None = None
        self._chat_area: ChatArea | None = None
        self._input_bar: InputBar | None = None

        # ── Lazy init ────────────────────────────────────────
        self._show_loading()
        self.after(100, self._init_async)

        # ── Global shortcuts ──────────────────────────────────────
        self.bind("<Control-l>", lambda _e: self._clear_chat())
        self.bind("<Control-q>", lambda _e: self._on_exit())
        self.bind("<Control-question>", lambda _e: self._open_command_palette())
        self.bind("<Escape>", lambda _e: self._on_escape())

        # ── Clean shutdown ──────────────────────────────────
        self.protocol("WM_DELETE_WINDOW", self._on_exit)

    # ── Async Helper (NON-BLOCKING) ─────────────────────────────────

    def _run_async(
        self,
        coro,
        on_success: Callable[[T], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        timeout: float = 10.0,
    ) -> None:
        """
        Ejecuta una coroutine en el bridge thread y notifica al main thread
        via polling. NUNCA bloquea el hilo de UI.
        """
        future = asyncio.run_coroutine_threadsafe(coro, self._bridge._loop)

        def _poll():
            if not future.done():
                self.after(100, _poll)
                return
            try:
                result = future.result(timeout=0)
                if on_success:
                    on_success(result)
            except Exception as e:
                logger.error("Async operation failed: %s", e)
                if on_error:
                    on_error(e)

        self.after(100, _poll)

    # ── Initialization ─────────────────────────────────────────────

    def _show_loading(self) -> None:
        """Shows loading screen while bootstrap runs."""
        self._loading_lbl = ctk.CTkLabel(
            self,
            text="Initializing File Agent…",
            font=FONT_TITLE,
            text_color=COLOR_TEXT_PRIMARY,
        )
        self._loading_lbl.place(relx=0.5, rely=0.5, anchor="center")

    def _init_async(self) -> None:
        """Starts bootstrap in bridge thread NON-BLOCKING."""
        def _bootstrap():
            return asyncio.run(bootstrap())

        self._bootstrap_future = self._bridge._executor.submit(_bootstrap)
        self._check_bootstrap()

    def _check_bootstrap(self) -> None:
        """Polls bootstrap completion without blocking the main thread."""
        if self._bootstrap_future.done():
            try:
                harness, memory, recorder, config, skills_count = self._bootstrap_future.result(timeout=5.0)
            except Exception as e:
                logger.exception("Bootstrap failed")
                self._loading_lbl.configure(text=f"Error: {e}")
                return

            self._config = config
            self._skills_count = skills_count
            self._session_manager = SessionManager(memory, harness)
            self._memory_service = MemoryService(memory)
            self._bridge.start(harness, recorder)

            # Build UI first, then load sessions
            self._loading_lbl.destroy()
            self._build_ui(skills_count)
            self._ui_built = True

            # Now load or create session
            self.after(100, lambda: self._init_session_or_create())
        else:
            self.after(100, self._check_bootstrap)

    def _init_session_or_create(self) -> None:
        """Loads the last active session or creates a new one."""

        def _on_sessions_loaded(sessions):
            logger.info("Loaded %d sessions from DB", len(sessions))
            active = [s for s in sessions if s.status == "active"]
            if active:
                latest = max(active, key=lambda s: s.updated_at or "")
                logger.info("Loading latest active session: %s", latest.session_id)
                self._on_select_session(latest.session_id, skip_rebuild=False)
            else:
                logger.info("No active sessions found, creating new one")
                self._create_new_session()

        def _on_error(e):
            logger.error("Failed to load sessions: %s", e)
            self._create_new_session()

        self._run_async(
            self._session_manager.list_sessions(),
            on_success=_on_sessions_loaded,
            on_error=_on_error,
        )

    def _create_new_session(self, title: str | None = None) -> None:
        """Creates a new session."""

        def _on_created(session):
            logger.info("Created new session: %s (%s)", session.session_id, session.title)
            self._bridge.set_session(session.session_id)
            self._current_session = session

            self._chat_area.clear()
            self._chat_area.add_system_message(f"New session: {session.title}")

            self._sidebar.set_sessions([session], show_archived=False)
            self._sidebar.set_active_session(session.session_id)
            self._update_sidebar_stats()

        def _on_error(e):
            logger.error("Failed to create session: %s", e)

        self._run_async(
            self._session_manager.create_session(title),
            on_success=_on_created,
            on_error=_on_error,
        )

    # ── Builders ─────────────────────────────────────────────────────────────

    def _build_ui(self, skills_count: int) -> None:
        """Builds all UI widgets."""

        # Sidebar
        self._sidebar = Sidebar(
            self,
            on_new_session=lambda: self._on_new_session(),
            on_select_session=self._on_select_session,
            on_archive_session=self._on_archive_session,
            on_rename_session=self._on_rename_session,
            on_delete_session=self._on_delete_session,
            on_theme_change=self._on_theme_change,
            on_show_archived=self._on_toggle_archived,
        )
        self._sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")

        # Chat Area
        self._chat_area = ChatArea(self)
        self._chat_area.grid(row=0, column=1, padx=15, pady=(15, 0), sticky="nsew")

        # Input Bar
        self._input_bar = InputBar(
            self,
            on_send=self._on_send,
            on_clear=self._clear_chat,
            on_command_palette=self._open_command_palette,
        )
        self._input_bar.grid(row=1, column=1, padx=15, pady=15, sticky="ew")

        # Welcome message
        self._chat_area.add_system_message(
            f"✓ Agent ready — {skills_count} skills loaded\n"
            f"Model: {self._config.llm.model if self._config else 'unknown'}\n"
            "Type a message to start."
        )

    # ── Session Actions ────────────────────────────────────────────────────

    def _on_new_session(self) -> None:
        """Creates new session automatically (no dialog)."""
        self._create_new_session()

    def _on_select_session(self, session_id: str, skip_rebuild: bool = False) -> None:
        """Loads an existing session."""
        if self._current_session and self._current_session.session_id == session_id:
            return

        def _after_rebuild(_ok):
            # Load visual history
            def _on_history(messages):
                logger.info("Loaded %d messages for session %s", len(messages), session_id)
                self._chat_area.clear()
                for msg in messages:
                    self._chat_area.add_message(msg)

                # Update current session
                def _on_session(session):
                    self._current_session = session
                    logger.info("Session loaded: %s", session.title if session else "None")
                    self._sidebar.set_active_session(session_id)
                    self._refresh_sidebar()
                    self._update_sidebar_stats()

                def _on_session_error(e):
                    logger.error("Failed to get session: %s", e)

                self._run_async(
                    self._session_manager.get_session(session_id),
                    on_success=_on_session,
                    on_error=_on_session_error,
                )

            def _on_history_error(e):
                logger.error("Failed to load history: %s", e)
                self._chat_area.add_system_message(f"Error loading session history: {e}")

            self._run_async(
                self._session_manager.load_session_history(session_id),
                on_success=_on_history,
                on_error=_on_history_error,
            )

        def _on_rebuild_error(e):
            logger.error("Failed to rebuild context: %s", e)
            self._chat_area.add_system_message(f"Error loading session: {e}")

        if not skip_rebuild:
            self._run_async(
                self._session_manager.rebuild_context(session_id),
                on_success=_after_rebuild,
                on_error=_on_rebuild_error,
            )
        else:
            _after_rebuild(True)

    def _on_archive_session(self, session_id: str) -> None:
        """Archives a session."""

        def _on_success(ok):
            if ok:
                self._refresh_sidebar()
                if (self._current_session
                        and self._current_session.session_id == session_id):
                    self._chat_area.add_system_message("Session archived.")
                    self._current_session = None
                    self._bridge.clear_session()

        def _on_error(e):
            logger.error("Archive failed: %s", e)

        self._run_async(
            self._session_manager.archive_session(session_id),
            on_success=_on_success,
            on_error=_on_error,
        )

    def _on_rename_session(self, session_id: str, new_title: str) -> None:
        """Renames a session."""

        def _on_success(ok):
            if ok:
                self._refresh_sidebar()

        def _on_error(e):
            logger.error("Rename failed: %s", e)

        self._run_async(
            self._session_manager.rename_session(session_id, new_title),
            on_success=_on_success,
            on_error=_on_error,
        )

    def _on_delete_session(self, session_id: str) -> None:
        """Physically deletes an archived session."""
        from tkinter import messagebox
        if not messagebox.askyesno(
            "Delete Session",
            "This will permanently delete the session and all its data.\n"
            "This action cannot be undone.\n\n"
            "Are you sure?"
        ):
            return

        def _on_success(ok):
            if ok:
                self._refresh_sidebar()
                if (self._current_session
                        and self._current_session.session_id == session_id):
                    self._current_session = None
                    self._bridge.clear_session()
                    self._chat_area.clear()
                    self._chat_area.add_system_message("Session deleted.")

        def _on_error(e):
            logger.error("Delete failed: %s", e)

        self._run_async(
            self._session_manager.delete_session(session_id),
            on_success=_on_success,
            on_error=_on_error,
        )

    def _on_toggle_archived(self, show: bool) -> None:
        """Shows/hides archived sessions."""
        self._refresh_sidebar(show_archived=show)

    def _refresh_sidebar(self, show_archived: bool = False) -> None:
        """Reloads session list in the sidebar."""

        def _on_success(sessions):
            status = "archived" if show_archived else "active"
            logger.info("Refreshing sidebar with %d %s sessions", len(sessions), status)
            self._sidebar.set_sessions(sessions, show_archived=show_archived)
            if self._current_session:
                self._sidebar.set_active_session(self._current_session.session_id)

        def _on_error(e):
            logger.error("Refresh sidebar failed: %s", e)

        status = "archived" if show_archived else "active"
        self._run_async(
            self._session_manager.list_sessions(status=status),
            on_success=_on_success,
            on_error=_on_error,
        )

    def _update_sidebar_stats(self) -> None:
        """Updates sidebar stats from current session."""
        if not self._current_session or not self._config:
            return
        total_tokens = self._current_session.tokens_in + self._current_session.tokens_out
        self._sidebar.update_stats(
            model=self._config.llm.model,
            turns=self._current_session.total_turns,
            tools=self._current_session.total_tools,
            tokens=total_tokens,
        )

    # ── Chat Actions ─────────────────────────────────────────────────────

    def _on_send(self, text: str) -> None:
        """Sends message to the agent."""
        if text.startswith("/"):
            self._handle_command(text)
            return

        if not self._bridge.session_id:
            self._chat_area.add_system_message("Error: No active session.")
            return

        # Show user message
        self._chat_area.add_message(ChatMessage(sender="user", content=text))
        self._input_bar.set_pending(True)

        def _on_tool_call(name: str, input_dict: dict, duration_ms: int, is_error: bool) -> None:
            """Real-time callback for each tool call."""
            self.after(0, lambda: self._chat_area.show_tool_alert(
                ToolCallItem(name=name, duration_ms=duration_ms, is_error=is_error,
                           summary=self._format_tool_summary(name, input_dict))
            ))

        def _on_done(response: str, trace) -> None:
            self.after(0, lambda: self._handle_response(response, trace, text))

        self._bridge.run_agent(text, on_done=_on_done, on_tool_call=_on_tool_call)

    def _handle_response(self, response: str, trace, user_message: str = "") -> None:
        """Processes agent response with metrics and memory extraction."""
        self._input_bar.set_pending(False)

        # Extract metrics from trace
        tokens_in = sum(c.tokens_in for c in trace.llm_calls) if trace else 0
        tokens_out = sum(c.tokens_out for c in trace.llm_calls) if trace else 0
        total_tools = len(trace.tool_calls) if trace else 0
        duration_ms = trace.total_duration_ms if trace else 0
        llm_calls_count = len(trace.llm_calls) if trace else 0

        # Update local session
        if self._current_session:
            self._current_session.total_turns += 1
            self._current_session.total_tools += total_tools

        # Build tool calls for the agent message
        agent_tool_calls: list[ToolCallItem] = []
        if trace and trace.tool_calls:
            for tc in trace.tool_calls:
                agent_tool_calls.append(ToolCallItem(
                    name=tc.name,
                    duration_ms=tc.duration_ms,
                    is_error=tc.is_error,
                    summary=self._format_tool_summary(tc.name, tc.input),
                ))

        # Show agent message with stats and tool calls
        msg = ChatMessage(
            sender="agent",
            content=response,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_ms=duration_ms,
            llm_calls=llm_calls_count,
            tool_calls=agent_tool_calls,
        )
        self._chat_area.add_message(msg)

        # ── Memory extraction hookup ─────────────────────────────
        if self._memory_service and self._bridge.session_id and trace:
            tool_calls_raw = [
                {
                    "name": tc.name,
                    "input": tc.input,
                    "is_error": tc.is_error,
                    "duration_ms": tc.duration_ms,
                }
                for tc in trace.tool_calls
            ]

            def _on_extract_done(facts):
                if facts:
                    logger.debug("Extracted %d facts", len(facts))

            def _on_extract_error(e):
                logger.debug("Fact extraction failed: %s", e)

            self._run_async(
                self._memory_service.extract_session_facts(
                    session_id=self._bridge.session_id,
                    user_message=user_message,
                    response=response,
                    tool_calls=tool_calls_raw,
                ),
                on_success=_on_extract_done,
                on_error=_on_extract_error,
            )

        # Update sidebar stats
        self._update_sidebar_stats()

        # Update session list
        self._refresh_sidebar()

    def _format_tool_summary(self, name: str, input_dict: dict) -> str:
        """Formats tool input for the alert."""
        try:
            if name in ("list_directory", "read_file", "create_directory"):
                return str(input_dict.get("path", ""))[:55]
            if name in ("move_file", "copy_file"):
                src = input_dict.get("source", "")
                dst = input_dict.get("destination", "")
                return f"{src} → {dst}"[:55]
            if name == "run_command":
                return str(input_dict.get("command", ""))[:55]
            if input_dict:
                return str(list(input_dict.values())[0])[:55]
        except Exception:
            pass
        return name

    def _clear_chat(self) -> None:
        """Clears the chat area visually."""
        self._chat_area.clear()

    def _open_command_palette(self) -> None:
        """Opens the command palette."""
        def _exec(cmd: str) -> None:
            self._handle_command(cmd)

        CommandPalette(self, on_command=_exec)

    def _handle_command(self, cmd: str) -> None:
        """Executes a palette command."""
        cmd = cmd.strip().lower()

        if cmd in ("/exit", "/quit"):
            self._on_exit()
        elif cmd == "/clear":
            self._clear_chat()
        elif cmd == "/stats":
            self._show_stats()
        elif cmd == "/memory":
            self._show_memory()
        elif cmd.startswith("/memory "):
            subcmd = cmd[8:].strip()
            if subcmd == "clear":
                self._clear_memory()
            elif subcmd == "search" or subcmd.startswith("search "):
                query = subcmd[7:].strip() if subcmd.startswith("search ") else ""
                self._search_memory(query)
            else:
                self._search_memory(subcmd)
        elif cmd == "/model":
            model = self._config.llm.model if self._config else "unknown"
            self._chat_area.add_system_message(f"Model: {model}")
        elif cmd == "/help":
            self._show_help()
        else:
            self._chat_area.add_system_message(f"Command not implemented: {cmd}")

    def _show_help(self) -> None:
        """Shows help message in chat."""
        help_text = (
            "Available commands:\n"
            "  /help           — Show this help\n"
            "  /clear          — Clear chat history\n"
            "  /stats          — Show session statistics\n"
            "  /memory         — Show saved memory facts\n"
            "  /memory search <query> — Search memory facts\n"
            "  /memory clear   — Delete all memory facts\n"
            "  /model          — Show active LLM model\n"
            "  /exit           — Exit application"
        )
        self._chat_area.add_system_message(help_text)

    def _show_memory(self) -> None:
        """Shows saved memory facts in chat."""
        if not self._memory_service:
            self._chat_area.add_system_message("Memory service not available.")
            return

        def _on_success(facts):
            if not facts:
                self._chat_area.add_system_message("No memory facts saved yet.")
                return
            lines = ["Saved memory facts:"]
            for f in facts:
                lines.append(f"  • [{f.topic}] {f.content[:100]}")
            self._chat_area.add_system_message("\n".join(lines))

        def _on_error(e):
            logger.error("Failed to load memory: %s", e)
            self._chat_area.add_system_message(f"Error loading memory: {e}")

        self._run_async(
            self._memory_service.get_recent_facts(n=20),
            on_success=_on_success,
            on_error=_on_error,
        )

    def _search_memory(self, query: str) -> None:
        """Searches memory facts by query."""
        if not self._memory_service:
            self._chat_area.add_system_message("Memory service not available.")
            return
        if not query:
            self._chat_area.add_system_message("Usage: /memory search <query>")
            return

        def _on_success(facts):
            if not facts:
                self._chat_area.add_system_message(f"No memory facts found for '{query}'.")
                return
            lines = [f"Memory search results for '{query}':"]
            for i, f in enumerate(facts, 1):
                lines.append(f"  {i}. [{f.topic}] {f.content[:100]}")
            self._chat_area.add_system_message("\n".join(lines))

        def _on_error(e):
            logger.error("Failed to search memory: %s", e)
            self._chat_area.add_system_message(f"Error searching memory: {e}")

        self._run_async(
            self._memory_service.search_facts(query, limit=10),
            on_success=_on_success,
            on_error=_on_error,
        )

    def _clear_memory(self) -> None:
        """Clears all memory facts."""
        if not self._memory_service:
            self._chat_area.add_system_message("Memory service not available.")
            return

        from tkinter import messagebox
        if not messagebox.askyesno(
            "Clear Memory",
            "This will permanently delete all saved memory facts.\n"
            "This action cannot be undone.\n\n"
            "Are you sure?"
        ):
            return

        def _on_success(_):
            self._chat_area.add_system_message("All memory facts cleared.")

        def _on_error(e):
            logger.error("Failed to clear memory: %s", e)
            self._chat_area.add_system_message(f"Error clearing memory: {e}")

        self._run_async(
            self._memory_service.clear_all(),
            on_success=_on_success,
            on_error=_on_error,
        )

    def _show_stats(self) -> None:
        """Shows current session stats in chat."""
        if not self._current_session:
            self._chat_area.add_system_message("No active session.")
            return

        lines = [
            f"Session: {self._current_session.title}",
            f"Turns: {self._current_session.total_turns}",
            f"Tools: {self._current_session.total_tools}",
            f"Errors: {self._current_session.total_errors}",
        ]
        self._chat_area.add_system_message("\n".join(lines))

    def _on_escape(self) -> None:
        """Closes open dialogs or clears selection."""
        pass

    def _on_exit(self) -> None:
        """Cleanly closes the application."""
        self._bridge.stop()
        self.destroy()

    # ── Theme Handling ─────────────────────────────────────────────────

    def _on_theme_change(self, value: str) -> None:
        """Changes theme and recreates chat tags."""
        ctk.set_appearance_mode(value)
        if self._chat_area:
            self._chat_area.recreate_tags()
