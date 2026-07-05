# app/app.py
"""
app.py — FileAgentApp: orquestador CTk + state.

Responsabilidades:
  - Inicializar CustomTkinter y layout principal
  - Coordinar sidebar, chat_area, input_bar, dialogs
  - Gestionar ciclo de vida de sesiones vía SessionManager
  - Bridge async para comunicación con el agente
  - Notificación de tool calls en tiempo real (toast de 3 segundos)
  - Stats en tiempo real con tokens I/O separados
  - Menú contextual y papelera
  - DELEGAR /commands a CommandService
  - Integrar MemoryService para carga de sesión y contexto

CAMBIO (v2.2): Imports desde app.entities. MemoryService.load_session()
al cambiar de sesión. NUNCA bloquear el UI thread.

FIX (v2.2.1):
  - _rebuilt_sessions: set para evitar rebuilds repetidos
  - _on_send: intercepta /commands antes de enviar al LLM
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from typing import Callable

import customtkinter as ctk

from agent.core.config import AgentConfig
from agent.traces.models import ToolTrace
from agent.memory.memory_service import MemoryService

from .theme import (
    WIDTH,
    HEIGHT,
    FONT_TITLE,
    COLOR_BG_PRIMARY,
    COLOR_TEXT_PRIMARY,
)
from .entities import ChatMessage, ToolCallItem, SessionItem
from .bridge import AsyncBridge
from .services.session_manager import SessionManager
from .services.command_service import CommandService
from .widgets.sidebar import Sidebar
from .widgets.chat_area import ChatArea
from .widgets.input_bar import InputBar
from .widgets.session_dialog import SessionDialog
from .widgets.command_palette import CommandPalette

logger = logging.getLogger(__name__)


def _format_tool_summary(inp: dict) -> str:
    """Genera un resumen legible del input del tool."""
    name = inp.get("name", "")
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


class FileAgentApp(ctk.CTk):
    """
    Aplicación principal de File Agent con CustomTkinter.
    Recibe todas las dependencias inyectadas (eager init).
    """

    def __init__(
        self,
        bridge: AsyncBridge,
        config: AgentConfig,
        session_manager: SessionManager,
        memory_service: MemoryService,
        command_service: CommandService,
        current_session: SessionItem,
        skills_count: int,
    ) -> None:
        super().__init__()

        # ── Configuración CustomTkinter ──────────────────────────────────
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.title("File Agent — v2.2.1")
        self.geometry(f"{WIDTH}x{HEIGHT}")
        self.minsize(900, 600)

        # Grid principal
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── Estado (inyectado, no creado) ───────────────────────────────
        self._config = config
        self._session_manager = session_manager
        self._memory_service = memory_service
        self._command_service = command_service
        self._bridge = bridge
        self._current_session = current_session

        # FIX 1: Set de sesiones ya rebuildadas en esta ejecución
        self._rebuilt_sessions: set[str] = set()

        # Acumulador de tool calls para el turno actual
        self._current_tool_calls: list[ToolCallItem] = []
        self._tool_debounce_id: str | None = None

        # ── Widgets ──────────────────────────────────────────────────────
        self._sidebar: Sidebar | None = None
        self._chat_area: ChatArea | None = None
        self._input_bar: InputBar | None = None

        # Build UI directamente (no hay lazy init)
        self._build_ui(skills_count)
        self._refresh_sidebar()

        # ── Atajos globales ──────────────────────────────────────────────
        self.bind("<Control-l>", lambda _e: self._clear_chat())
        self.bind("<Control-q>", lambda _e: self._on_exit())
        self.bind("<Control-question>", lambda _e: self._open_command_palette())
        self.bind("<Escape>", lambda _e: self._on_escape())

    # ── Helpers async → UI thread ──────────────────────────────────────────────

    def _run_async(
        self,
        coro,
        on_success: Callable | None = None,
        on_error: Callable[[Exception], None] | None = None,
        pending: bool = False,
    ) -> None:
        """
        Helper KISS: ejecuta una coroutine en el bridge loop y entrega
        el resultado de vuelta al UI thread vía self.after(0, ...).
        NUNCA bloquea.
        """
        if pending:
            self._input_bar.set_pending(True)

        def _callback(fut: asyncio.Future):
            try:
                result = fut.result()
                if on_success:
                    self.after(0, lambda r=result: on_success(r))
            except Exception as e:
                logger.exception("Async operation failed")
                if on_error:
                    self.after(0, lambda err=e: on_error(err))
                else:
                    self.after(
                        0,
                        lambda err=e: self._chat_area.add_system_message(
                            f"⚠️ Error: {err}"
                        ),
                    )
            finally:
                if pending:
                    self.after(0, lambda: self._input_bar.set_pending(False))

        future = asyncio.run_coroutine_threadsafe(coro, self._bridge._loop)
        future.add_done_callback(_callback)

    # ── Builders ───────────────────────────────────────────────────────────────

    def _build_ui(self, skills_count: int) -> None:
        """Construye todos los widgets de la UI."""

        # Registrar callback de tool calls en el bridge
        self._bridge.register_tool_callback(self._on_tool_call)

        # Sidebar
        self._sidebar = Sidebar(
            self,
            on_new_session=self._on_new_session,
            on_select_session=self._on_select_session,
            on_archive_session=self._on_archive_session,
            on_rename_session=self._on_rename_session,
            on_delete_session=self._on_delete_session,
            on_toggle_trash=self._on_toggle_trash,
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

        # Mensaje inicial
        self._chat_area.add_system_message(
            f"✓ Agent ready — {skills_count} skills loaded\n"
            f"Model: {self._config.llm.model if self._config else 'unknown'}\n"
            "Type a message to start."
        )

    # ── Tool calls en tiempo real (con debounce) ───────────────────────────────

    def _on_tool_call(self, trace: ToolTrace) -> None:
        """
        Recibe un ToolTrace desde el Harness mientras se ejecuta el turno.
        Thread-safe: se ejecuta en el thread del bridge, usamos after() para Tkinter.
        """
        item = ToolCallItem(
            name=trace.name,
            duration_ms=trace.duration_ms,
            is_error=trace.is_error,
            summary=_format_tool_summary(trace.input),
        )
        self._current_tool_calls.append(item)

        # Cancelar debounce previo
        if self._tool_debounce_id is not None:
            self.after_cancel(self._tool_debounce_id)

        # Debounce 80ms: solo renderizar el último burst de tool calls
        self._tool_debounce_id = self.after(80, self._flush_tool_toast)

    def _flush_tool_toast(self) -> None:
        """Ejecuta SIEMPRE en el UI thread."""
        self._tool_debounce_id = None
        self._chat_area.show_tool_toast(self._current_tool_calls.copy())

    # ── Acciones de Sesión (TODAS async, NUNCA bloqueantes) ────────────────────

    def _on_new_session(self) -> None:
        """Abre diálogo para crear nueva sesión."""

        def _create(title: str) -> None:
            self._run_async(
                self._session_manager.create_session(title),
                on_success=lambda session: self._after_new_session(session),
                pending=True,
            )

        SessionDialog(self, mode="create", on_confirm=_create)

    def _after_new_session(self, session: SessionItem) -> None:
        """Callback en UI thread tras crear sesión."""
        self._bridge.set_session(session.session_id)
        self._current_session = session
        self._chat_area.clear()
        self._chat_area.add_system_message(f"New session: {session.title}")
        # NUEVO: cargar working cache de memoria
        self._run_async(
            self._memory_service.load_session(session.session_id),
            on_success=lambda _: logger.debug("Memory cache loaded for new session"),
        )
        self._refresh_sidebar()

    def _on_select_session(self, session_id: str) -> None:
        """Carga una sesión existente. NUNCA bloquea."""
        if self._current_session and self._current_session.session_id == session_id:
            return

        # FIX 1: Si ya rebuildamos esta sesión en esta ejecución, solo cargar historial visual
        if session_id in self._rebuilt_sessions:
            self._chat_area.add_system_message("⏳ Loading session…")
            self._input_bar.set_pending(True)
            self._run_async(
                self._session_manager.load_session_history(session_id),
                on_success=lambda messages: self._after_load_history(session_id, messages),
                on_error=lambda e: self._on_session_error(e, "loading history"),
            )
            return

        self._chat_area.add_system_message("⏳ Loading session…")
        self._input_bar.set_pending(True)

        # Paso 1: Rebuild context
        self._run_async(
            self._session_manager.rebuild_context(session_id),
            on_success=lambda _: self._after_rebuild_context(session_id),
            on_error=lambda e: self._on_session_error(e, "rebuilding context"),
            pending=False,  # El pending se maneja manualmente en la cadena
        )

    def _after_rebuild_context(self, session_id: str) -> None:
        """Paso 2: Cargar historial + memoria."""
        # Marcar como rebuildada
        self._rebuilt_sessions.add(session_id)

        # NUEVO: cargar working cache de memoria para la sesión
        self._run_async(
            self._memory_service.load_session(session_id),
            on_success=lambda _: self._after_load_memory(session_id),
            on_error=lambda e: self._on_session_error(e, "loading memory cache"),
        )

    def _after_load_memory(self, session_id: str) -> None:
        """Paso 3: Cargar historial de chat."""
        self._run_async(
            self._session_manager.load_session_history(session_id),
            on_success=lambda messages: self._after_load_history(session_id, messages),
            on_error=lambda e: self._on_session_error(e, "loading history"),
        )

    def _after_load_history(self, session_id: str, messages: list[ChatMessage]) -> None:
        """Paso 4: Aplicar a UI y cargar session metadata."""
        self._bridge.set_session(session_id)
        self._chat_area.clear()
        for msg in messages:
            self._chat_area.add_message(msg)

        self._run_async(
            self._session_manager.get_session(session_id),
            on_success=lambda session: self._after_get_session(session_id, session),
            on_error=lambda e: self._on_session_error(e, "loading session"),
        )

    def _after_get_session(self, session_id: str, session: SessionItem | None) -> None:
        """Finaliza la carga de sesión."""
        if session:
            self._current_session = session
            self._sidebar.set_active_session(session_id)
            self._update_sidebar_stats()
        self._input_bar.set_pending(False)

    def _on_session_error(self, error: Exception, phase: str) -> None:
        """Manejo centralizado de errores de sesión."""
        logger.exception("Failed during %s", phase)
        self._chat_area.add_system_message(f"⚠️ Error {phase}: {error}")
        self._input_bar.set_pending(False)

    def _on_archive_session(self, session_id: str, session_title: str = "") -> None:
        """Archiva una sesión. Si es la actual, auto-switch a vista Archived."""

        def _confirm(_: str) -> None:
            self._run_async(
                self._session_manager.archive_session(session_id),
                on_success=lambda ok: self._after_archive(session_id, session_title, ok),
                pending=True,
            )

        SessionDialog(
            self,
            mode="archive",
            session_title=session_title,
            on_confirm=_confirm,
        )

    def _after_archive(self, session_id: str, session_title: str, ok: bool) -> None:
        if not ok:
            self._chat_area.add_system_message("⚠️ Failed to archive session.")
            return

        was_current = (
            self._current_session
            and self._current_session.session_id == session_id
        )
        if was_current:
            # NUEVO: consolidar memoria antes de cambiar vista
            self._run_async(
                self._memory_service.consolidate_session(session_id),
                on_success=lambda result: logger.debug("Consolidation: %s", result),
            )
            self._sidebar.set_view("Archived")
            self._chat_area.add_system_message(
                f"📦 Session archived: {session_title}\n"
                "Switched to Archived view."
            )
        self._refresh_sidebar()

    def _on_rename_session(self, session_id: str, current_title: str) -> None:
        """Renombra una sesión."""

        def _confirm(new_title: str) -> None:
            self._run_async(
                self._session_manager.rename_session(session_id, new_title),
                on_success=lambda ok: self._after_rename(ok),
                pending=True,
            )

        SessionDialog(
            self,
            mode="rename",
            session_title=current_title,
            on_confirm=_confirm,
        )

    def _after_rename(self, ok: bool) -> None:
        if ok:
            self._refresh_sidebar()

    def _on_delete_session(self, session_id: str, session_title: str = "") -> None:
        """Elimina físicamente una sesión."""

        def _confirm(_: str) -> None:
            self._run_async(
                self._session_manager.delete_session(session_id),
                on_success=lambda ok: self._after_delete(session_id, ok),
                pending=True,
            )

        SessionDialog(
            self,
            mode="delete",
            session_title=session_title,
            on_confirm=_confirm,
        )

    def _after_delete(self, session_id: str, ok: bool) -> None:
        if not ok:
            self._chat_area.add_system_message("⚠️ Failed to delete session.")
            return

        self._refresh_sidebar()
        if (
            self._current_session
            and self._current_session.session_id == session_id
        ):
            self._current_session = None
            self._chat_area.add_system_message("Session deleted.")

    def _on_toggle_trash(self) -> None:
        """Alterna entre sesiones activas y papelera."""
        self._refresh_sidebar()

    def _refresh_sidebar(self) -> None:
        """Recarga la lista completa de sesiones en el sidebar. NUNCA bloquea."""
        coro = (
            self._session_manager.list_archived_sessions()
            if self._sidebar.is_showing_trash()
            else self._session_manager.list_sessions()
        )

        def _on_success(sessions: list[SessionItem]) -> None:
            self._sidebar.set_sessions(sessions)
            if self._current_session:
                self._sidebar.set_active_session(self._current_session.session_id)
            self._update_sidebar_stats()

        self._run_async(coro, on_success=_on_success)

    def _update_current_stats(self) -> None:
        """Consulta la DB para stats reales de la sesión actual. NUNCA bloquea."""
        if not self._current_session or not self._session_manager:
            return

        def _on_success(session: SessionItem | None) -> None:
            if session:
                self._current_session = session
                self._update_sidebar_stats()
                self._sidebar.set_active_session(session.session_id)

        self._run_async(
            self._session_manager.get_session(self._current_session.session_id),
            on_success=_on_success,
        )

    def _update_sidebar_stats(self) -> None:
        """Actualiza las stats del sidebar con la sesión actual."""
        if not self._current_session:
            return
        model = self._config.llm.model if self._config else "unknown"
        self._sidebar.update_stats(
            model=model,
            turns=self._current_session.total_turns,
            tools=self._current_session.total_tools,
            tokens_in=self._current_session.tokens_in,
            tokens_out=self._current_session.tokens_out,
        )

    # ── Acciones de Chat ─────────────────────────────────────────────────────────

    def _on_send(self, text: str) -> None:
        """Envía mensaje al agente."""
        if not self._bridge.session_id:
            self._chat_area.add_system_message("Error: No active session.")
            return

        # FIX 2: Interceptar /commands antes de enviar al LLM
        stripped = text.strip()
        if stripped.startswith("/"):
            self._chat_area.add_message(ChatMessage(sender="user", content=stripped))
            self._handle_command(stripped)
            return

        # Reset acumulador de tools para este turno
        self._current_tool_calls = []

        # Mostrar mensaje del usuario
        self._chat_area.add_message(ChatMessage(sender="user", content=text))
        self._input_bar.set_pending(True)

        def _on_done(response: str, tokens_in: int = 0, tokens_out: int = 0) -> None:
            self.after(0, lambda: self._handle_response(response, tokens_in, tokens_out))

        self._bridge.run_agent(text, on_done=_on_done)

    def _handle_response(self, response: str, tokens_in: int = 0, tokens_out: int = 0) -> None:
        """Procesa la respuesta del agente."""
        self._input_bar.set_pending(False)

        if response.startswith("[") and "Error" in response:
            self._chat_area.add_message(ChatMessage(sender="error", content=response))
        else:
            self._chat_area.add_message(
                ChatMessage(
                    sender="agent",
                    content=response,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                )
            )

        # Actualizar stats en tiempo real
        self._update_current_stats()

    def _clear_chat(self) -> None:
        """Limpia el área de chat visualmente."""
        self._chat_area.clear()

    def _open_command_palette(self) -> None:
        """Abre la paleta de comandos."""

        def _exec(cmd: str) -> None:
            self._handle_command(cmd)

        CommandPalette(self, on_command=_exec)

    # ── Command Handling delegado a CommandService ─────────────────────────────

    def _handle_command(self, cmd_str: str) -> None:
        """Delega todo el procesamiento de /commands a CommandService."""
        if not self._command_service:
            self._chat_area.add_system_message("⚠️ Command service not available.")
            return

        def _on_result(result: str) -> None:
            self.after(0, lambda: self._chat_area.add_system_message(result))

        # Ejecutar en el bridge loop para acceso async a servicios
        future = asyncio.run_coroutine_threadsafe(
            self._command_service.execute(cmd_str), self._bridge._loop
        )

        def _on_future_done(fut):
            try:
                result = fut.result()
            except Exception as e:
                result = f"⚠️ Command error: {e}"
            _on_result(result)

        future.add_done_callback(_on_future_done)

    def _on_escape(self) -> None:
        """Cierra diálogos abiertos o limpia selección."""
        pass

    def _on_exit(self) -> None:
        """Cierra la aplicación limpiamente."""
        # NUEVO: flush memoria antes de cerrar
        if self._memory_service:
            self._run_async(
                self._memory_service.flush(),
                on_success=lambda _: logger.debug("Memory flushed on exit"),
            )
        self._bridge.stop()
        self.destroy()

    # ── Theme Handling ─────────────────────────────────────────────────────────

    def _on_theme_change(self, value: str) -> None:
        """Cambia el tema y recrea los tags del chat."""
        ctk.set_appearance_mode(value)
        if self._chat_area:
            self._chat_area.recreate_tags()
