"""
widgets/command_palette.py — CTkToplevel para comandos tipo /help, /traces, /stats, /memory.

Responsabilidades:
  - Lista de comandos disponibles con descripción
  - Ejecución de comandos sin escribir en el chat
  - Atajo de teclado Ctrl+?
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

        self.title("Comandos")
        self.geometry("500x400")
        self.resizable(False, True)
        self.transient(master)
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── Search ─────────────────────────────────────────────────────────
        self._search = ctk.CTkEntry(
            self,
            placeholder_text="Escribe un comando…",
            font=FONT_BODY,
            corner_radius=8,
        )
        self._search.grid(row=0, column=0, padx=15, pady=15, sticky="ew")
        self._search.bind("<Return>", lambda _e: self._execute_selected())
        self._search.bind("<Escape>", lambda _e: self._close())
        self.after(100, self._search.focus_set)

        # ── Command List ───────────────────────────────────────────────────
        self._list_frame = ctk.CTkScrollableFrame(
            self,
            fg_color=COLOR_BG_PRIMARY,
            corner_radius=8,
        )
        self._list_frame.grid(row=1, column=0, padx=15, pady=(0, 15), sticky="nsew")
        self._list_frame.grid_columnconfigure(0, weight=1)

        self._commands: list[tuple[str, str, str]] = [
            ("/help", "Mostrar ayuda", "Comandos disponibles"),
            ("/clear", "Limpiar chat", "Borra el historial visual"),
            ("/traces", "Ver traces", "Últimos traces del día"),
            ("/traces 5", "Ver 5 traces", "Número configurable"),
            ("/stats", "Estadísticas", "Tokens, turnos, tools"),
            ("/memory", "Listar memoria", "Hechos guardados"),
            ("/memory buscar", "Buscar en memoria", "Filtrar por texto"),
            ("/memory clear", "Limpiar memoria", "Eliminar todos los hechos"),
            ("/model", "Modelo activo", "Configuración LLM"),
            ("/exit", "Salir", "Cerrar aplicación"),
        ]

        self._buttons: list[ctk.CTkButton] = []
        self._render_list()

    def _render_list(self) -> None:
        """Renderiza la lista de comandos filtrada."""
        for btn in self._buttons:
            btn.destroy()
        self._buttons = []

        query = self._search.get().lower()

        for cmd, desc, detail in self._commands:
            if query and query not in cmd and query not in desc.lower():
                continue

            btn = ctk.CTkButton(
                self._list_frame,
                text=f"{cmd:<16} {desc}",
                anchor="w",
                font=FONT_SMALL,
                fg_color="transparent",
                hover_color=("gray85", "gray25"),
                command=lambda c=cmd: self._execute(c),
            )
            btn.pack(fill="x", pady=1)
            self._buttons.append(btn)

    def _execute_selected(self) -> None:
        """Ejecuta el primer comando visible o el texto ingresado."""
        text = self._search.get().strip()
        if text.startswith("/"):
            self._execute(text)
        elif self._buttons:
            self._buttons[0].invoke()

    def _execute(self, command: str) -> None:
        """Ejecuta un comando y cierra la paleta."""
        self._on_command(command)
        self._close()

    def _close(self) -> None:
        """Cierra la paleta."""
        if self._on_close:
            self._on_close()
        self.destroy()
