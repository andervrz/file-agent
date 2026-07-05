"""
app.py — FileAgentApp: orquestador CTk + state.

Responsabilidades:
  - Inicializar CustomTkinter y layout principal
  - Coordinar sidebar, chat_area, input_bar, dialogs
  - Gestionar ciclo de vida de sesiones vía SessionManager
  - Bridge async para comunicación con el agente
  - Reaccionar a cambios de tema
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from typing import Callable

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


class FileAgentApp(ctk.CTk):
    """
    Aplicación principal de File Agent con CustomTkinter.
    """

    def __init__(self) -> None:
        super().__init__()

        # ── Configuración CustomTkinter ──────────────────────────────────
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.title("File Agent — v1.8.0")
        self.geometry(f"{WIDTH}x{HEIGHT}")
        self.minsize(900, 600)

        # Grid principal
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── Estado ───────────────────────────────────────────────────────
        self._config: AgentConfig | None = None
        self._session_manager: SessionManager | None = None
        self._memory_service: MemoryService | None = None
        self._bridge = AsyncBridge()
        self._current_session: SessionItem | None = None

        # ── Widgets ──────────────────────────────────────────────────────
        self._sidebar: Sidebar | None = None
        self._chat_area: ChatArea | None = None
        self._input_bar: InputBar | None = None

        # ── Inicialización lazy ────────────────────────────────────────
        self._show_loading()
        self.after(100, self._init_async)

        # ── Atajos globales ──────────────────────────────────────────────
        self.bind("<Control-l>", lambda _e: self._clear_chat())
        self.bind("<Control-q>", lambda _e: self._on_exit())
        self.bind("<Control-question>", lambda _e: self._open_command_palette())
        self.bind("<Escape>", lambda _e: self._on_escape())

    # ── Inicialización ─────────────────────────────────────────────────────────

    def _show_loading(self) -> None:
        """Muestra pantalla de carga mientras bootstrap corre."""
        self._loading_lbl = ctk.CTkLabel(
            self,
            text="Inicializando File Agent…",
            font=FONT_TITLE,
            text_color=COLOR_TEXT_PRIMARY,
        )
        self._loading_lbl.place(relx=0.5, rely=0.5, anchor="center")

    def _init_async(self) -> None:
        """Arranca el bootstrap en el bridge thread."""
        try:
            harness, memory, recorder, config, skills_count = asyncio.run(bootstrap())
        except Exception as e:
            logger.exception("Bootstrap failed")
            self._loading_lbl.configure(text=f"Error: {e}")
            return

        self._config = config
        self._session_manager = SessionManager(memory, harness)
        self._memory_service = MemoryService(memory)
        self._bridge.start(harness)

        # Crear sesión inicial
        asyncio.run_coroutine_threadsafe(
            self._create_initial_session(), self._bridge._loop
        )

        # Construir UI
        self._loading_lbl.destroy()
        self._build_ui(skills_count)

    async def _create_initial_session(self) -> None:
        """Crea la primera sesión del usuario."""
        session = await self._session_manager.create_session()
        self._bridge.set_session(session.session_id)
        self._current_session = session

    # ── Builders ───────────────────────────────────────────────────────────────

    def _build_ui(self, skills_count: int) -> None:
        """Construye todos los widgets de la UI."""

        # Sidebar
        self._sidebar = Sidebar(
            self,
            on_new_session=self._on_new_session,
            on_select_session=self._on_select_session,
            on_archive_session=self._on_archive_session,
            on_rename_session=self._on_rename_session,
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

        # Cargar sesiones existentes
        self._refresh_sidebar()

        # Mensaje inicial
        self._chat_area.add_system_message(
            f"✓ Agente listo — {skills_count} skills cargadas\n"
            f"Modelo: {self._config.llm.model if self._config else 'unknown'}\n"
            "Escribe un mensaje para comenzar."
        )

    # ── Acciones de Sesión ───────────────────────────────────────────────────────

    def _on_new_session(self) -> None:
        """Abre diálogo para crear nueva sesión."""
        def _create(title: str) -> None:
            future = asyncio.run_coroutine_threadsafe(
                self._session_manager.create_session(title), self._bridge._loop
            )
            session = future.result(timeout=5.0)
            self._bridge.set_session(session.session_id)
            self._current_session = session
            self._chat_area.clear()
            self._chat_area.add_system_message(f"Nueva sesión: {session.title}")
            self._refresh_sidebar()

        SessionDialog(self, mode="create", on_confirm=_create)

    def _on_select_session(self, session_id: str) -> None:
        """Carga una sesión existente."""
        if self._current_session and self._current_session.session_id == session_id:
            return

        # Rebuild context en el bridge
        future = asyncio.run_coroutine_threadsafe(
            self._session_manager.rebuild_context(session_id), self._bridge._loop
        )
        future.result(timeout=10.0)

        self._bridge.set_session(session_id)

        # Cargar historial visual
        future = asyncio.run_coroutine_threadsafe(
            self._session_manager.load_session_history(session_id), self._bridge._loop
        )
        messages = future.result(timeout=10.0)

        self._chat_area.clear()
        for msg in messages:
            self._chat_area.add_message(msg)

        # Actualizar sesión actual
        future = asyncio.run_coroutine_threadsafe(
            self._session_manager.get_session(session_id), self._bridge._loop
        )
        self._current_session = future.result(timeout=5.0)
        self._sidebar.set_active_session(session_id)

    def _on_archive_session(self, session_id: str) -> None:
        """Archiva una sesión."""
        def _confirm(_: str) -> None:
            future = asyncio.run_coroutine_threadsafe(
                self._session_manager.archive_session(session_id), self._bridge._loop
            )
            if future.result(timeout=5.0):
                self._refresh_sidebar()
                if self._current_session and self._current_session.session_id == session_id:
                    self._chat_area.add_system_message("Sesión archivada.")

        SessionDialog(
            self,
            mode="archive",
            session_title=self._current_session.title if self._current_session else "",
            on_confirm=_confirm,
        )

    def _on_rename_session(self, session_id: str, current_title: str) -> None:
        """Renombra una sesión."""
        def _confirm(new_title: str) -> None:
            future = asyncio.run_coroutine_threadsafe(
                self._session_manager.rename_session(session_id, new_title),
                self._bridge._loop,
            )
            if future.result(timeout=5.0):
                self._refresh_sidebar()

        SessionDialog(
            self,
            mode="rename",
            session_title=current_title,
            on_confirm=_confirm,
        )

    def _refresh_sidebar(self) -> None:
        """Recarga la lista de sesiones en el sidebar."""
        future = asyncio.run_coroutine_threadsafe(
            self._session_manager.list_sessions(), self._bridge._loop
        )
        sessions = future.result(timeout=5.0)
        self._sidebar.set_sessions(sessions)
        if self._current_session:
            self._sidebar.set_active_session(self._current_session.session_id)

    # ── Acciones de Chat ─────────────────────────────────────────────────────────

    def _on_send(self, text: str) -> None:
        """Envía mensaje al agente."""
        if not self._bridge.session_id:
            self._chat_area.add_system_message("Error: No hay sesión activa.")
            return

        # Mostrar mensaje del usuario
        self._chat_area.add_message(ChatMessage(sender="user", content=text))
        self._input_bar.set_pending(True)

        def _on_done(response: str) -> None:
            self.after(0, lambda: self._handle_response(response))

        self._bridge.run_agent(text, on_done=_on_done)

    def _handle_response(self, response: str) -> None:
        """Procesa la respuesta del agente."""
        self._input_bar.set_pending(False)

        if response.startswith("[") and "Error" in response:
            self._chat_area.add_message(ChatMessage(sender="error", content=response))
        else:
            self._chat_area.add_message(ChatMessage(sender="agent", content=response))

        # Actualizar stats
        self._refresh_sidebar()

        # Extracción automática de facts (consolidación)
        # Nota: en v1 lo hacemos de forma fire-and-forget
        # En v2 se puede hacer con LLM para extraer facts semánticos

    def _clear_chat(self) -> None:
        """Limpia el área de chat visualmente."""
        self._chat_area.clear()

    def _open_command_palette(self) -> None:
        """Abre la paleta de comandos."""
        def _exec(cmd: str) -> None:
            self._handle_command(cmd)

        CommandPalette(self, on_command=_exec)

    def _handle_command(self, cmd: str) -> None:
        """Ejecuta un comando de la paleta."""
        cmd = cmd.strip().lower()

        if cmd in ("/exit", "/quit"):
            self._on_exit()
        elif cmd == "/clear":
            self._clear_chat()
        elif cmd.startswith("/traces"):
            self._chat_area.add_system_message("Comando /traces: usar CLI por ahora.")
        elif cmd == "/stats":
            self._refresh_sidebar()
        elif cmd == "/memory":
            self._chat_area.add_system_message("Comando /memory: usar CLI por ahora.")
        elif cmd == "/model":
            model = self._config.llm.model if self._config else "unknown"
            self._chat_area.add_system_message(f"Modelo: {model}")
        else:
            self._chat_area.add_system_message(f"Comando no implementado: {cmd}")

    def _on_escape(self) -> None:
        """Cierra diálogos abiertos o limpía selección."""
        # Por ahora, no-op. En v2 podría cerrar modales.

    def _on_exit(self) -> None:
        """Cierra la aplicación limpiamente."""
        self._bridge.stop()
        self.destroy()

    # ── Theme Handling ───────────────────────────────────────────────────────────

    def _on_theme_change(self, value: str) -> None:
        """Cambia el tema y recrea los tags del chat."""
        ctk.set_appearance_mode(value)
        if self._chat_area:
            self._chat_area.recreate_tags()
