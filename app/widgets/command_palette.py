# app/widgets/command_palette.py
"""
widgets/command_palette.py — CTkToplevel para comandos tipo /help, /traces, /stats.

Responsabilidades:
  - Lista de comandos disponibles con descripción
  - Ejecución de comandos sin escribir en el chat
  - Atajo de teclado Ctrl+?
  - Filtrado en tiempo real al escribir

CAMBIO (v2.1):
  - Pool de botones reutilizables: grid_remove/grid en vez de destroy/create.
  - Typing fluido sin micro-stutters por churn de widgets.
"""
from __future__ import annotations

import customtkinter as ctk
from typing import Callable

from ..theme import (
    FONT_BODY,
    FONT_BODY_BOLD,
    FONT_SMALL,
    COLOR_BG_PRIMARY,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
)


class CommandPalette(ctk.CTkToplevel):
    """
    Paleta de comandos estilo VS Code / Slack — busca y ejecuta comandos.
    """

    def __init__(
        self,
        master,
        on_command: Callable[[str], None],
        on_close: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)

        self._on_command = on_command
        self._on_close = on_close

        self.title("Commands")
        self.geometry("500x400")
        self.resizable(False, True)
        self.transient(master)
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── Search ─────────────────────────────────────────────────────────
        self._search = ctk.CTkEntry(
            self,
            placeholder_text="Type a command…",
            font=FONT_BODY,
            corner_radius=8,
        )
        self._search.grid(row=0, column=0, padx=15, pady=15, sticky="ew")
        self._search.bind("<Return>", lambda _e: self._execute_selected())
        self._search.bind("<Escape>", lambda _e: self._close())
        self._search.bind("<KeyRelease>", lambda _e: self._apply_filter())
        self.after(100, self._search.focus_set)

        # ── Command List ───────────────────────────────────────────────────
        self._list_frame = ctk.CTkScrollableFrame(
            self,
            fg_color=COLOR_BG_PRIMARY,
            corner_radius=8,
        )
        self._list_frame.grid(row=1, column=0, padx=15, pady=(0, 15), sticky="nsew")
        self._list_frame.grid_columnconfigure(0, weight=1)

        # Lista estática de comandos (fuente de verdad)
        self._commands: list[tuple[str, str, str]] = [
            # Tier 1: Simple commands
            ("/help", "Show help", "Commands and keyboard shortcuts"),
            ("/tools", "List tools", "All available agent tools with descriptions"),
            ("/clear", "Clear chat", "Clear visual chat history"),
            ("/stats", "Session stats", "Turns, tools, errors, tokens"),
            ("/model", "Model config", "Active model, temperature, settings"),
            ("/mcp", "MCP tools", "External tools from MCP servers"),
            ("/undo", "Undo last change", "Revert uncommitted git changes"),
            ("/exit", "Exit", "Close application"),
            # Tier 2: Commands with arguments
            ("/traces", "View traces", "Last 5 conversation turns"),
            ("/traces 10", "View 10 traces", "Configurable count"),
            ("/memory", "List memory", "Recent memory facts"),
            ("/memory search", "Search memory", "Filter facts by text"),
            ("/memory clear", "Clear memory", "Delete all memory facts"),
            ("/search", "Search files", "Find text inside project files"),
            ("/browser open", "Open URL", "Open in browser"),
            ("/browser search", "Web search", "Search DuckDuckGo"),
            ("/browser read", "Read page", "Read current browser page"),
            ("/browser screenshot", "Screenshot", "Take browser screenshot"),
            ("/browser close", "Close browser", "Close browser instance"),
        ]

        # Pool de botones reutilizables (pre-creados)
        self._buttons: list[ctk.CTkButton] = []
        self._build_button_pool()

    def _build_button_pool(self) -> None:
        """Pre-crea un pool de botones para todos los comandos posibles."""
        for cmd, desc, detail in self._commands:
            btn = ctk.CTkButton(
                self._list_frame,
                text=f"{cmd:<20} {desc}",
                anchor="w",
                font=FONT_SMALL,
                fg_color="transparent",
                hover_color=("gray85", "gray25"),
                command=lambda c=cmd: self._execute(c),
            )
            self._buttons.append(btn)

        # Mostrar todos inicialmente
        self._apply_filter()

    def _apply_filter(self) -> None:
        """Filtra botones existentes sin destruir ni crear widgets."""
        query = self._search.get().lower().strip()

        for i, (cmd, desc, detail) in enumerate(self._commands):
            btn = self._buttons[i]

            # Decidir visibilidad
            visible = (
                not query
                or query in cmd
                or query in desc.lower()
                or query in detail.lower()
            )

            if visible:
                btn.configure(text=f"{cmd:<20} {desc}")
                if not btn.winfo_viewable():
                    btn.pack(fill="x", pady=1)
            else:
                btn.pack_forget()

    def _execute_selected(self) -> None:
        """Ejecuta el primer comando visible o el texto ingresado."""
        text = self._search.get().strip()
        if text.startswith("/"):
            self._execute(text)
            return

        # Buscar primer botón visible
        for btn in self._buttons:
            if btn.winfo_viewable():
                btn.invoke()
                return

    def _execute(self, command: str) -> None:
        """Ejecuta un comando y cierra la paleta."""
        self._on_command(command)
        self._close()

    def _close(self) -> None:
        """Cierra la paleta."""
        if self._on_close:
            self._on_close()
        self.destroy()
