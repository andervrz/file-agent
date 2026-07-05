"""
widgets/input_bar.py — Barra de input con CTkEntry, botón enviar y acciones rápidas.

Responsabilidades:
  - Input de mensaje con placeholder
  - Botón enviar (Enter también funciona)
  - Botón limpiar chat (🗑️)
  - Botón command palette (?)
  - Progress bar indeterminada durante procesamiento
"""
from __future__ import annotations

import customtkinter as ctk
from typing import Callable

from ..theme import (
    FONT_BODY,
    FONT_BUTTON,
    COLOR_BG_PRIMARY,
    COLOR_TEXT_PRIMARY,
    INPUT_H,
)


class InputBar(ctk.CTkFrame):
    """
    Barra de input con entry, botón enviar y acciones rápidas.
    """

    def __init__(
        self,
        master,
        on_send: Callable[[str], None],
        on_clear: Callable[[], None],
        on_command_palette: Callable[[], None],
        **kwargs,
    ) -> None:
        super().__init__(master, height=INPUT_H, corner_radius=12, fg_color=COLOR_BG_PRIMARY, **kwargs)

        self._on_send = on_send
        self._on_clear = on_clear
        self._on_command_palette = on_command_palette
        self._pending = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── Entry ──────────────────────────────────────────────────────────
        self._entry = ctk.CTkEntry(
            self,
            placeholder_text="Escribe tu mensaje…  (Enter para enviar, Ctrl+L limpiar, Ctrl+? comandos)",
            font=FONT_BODY,
            corner_radius=10,
            border_width=2,
            fg_color=COLOR_BG_PRIMARY,
            text_color=COLOR_TEXT_PRIMARY,
        )
        self._entry.grid(row=0, column=0, padx=(15, 10), pady=15, sticky="nsew")
        self._entry.bind("<Return>", lambda _e: self._handle_send())

        # ── Botón Enviar ─────────────────────────────────────────────────
        self._send_btn = ctk.CTkButton(
            self,
            text="➤",
            width=50,
            command=self._handle_send,
            font=FONT_BUTTON,
            corner_radius=10,
        )
        self._send_btn.grid(row=0, column=1, padx=(0, 5), pady=15)

        # ── Botón Limpiar ────────────────────────────────────────────────
        self._clear_btn = ctk.CTkButton(
            self,
            text="🗑️",
            width=40,
            command=self._on_clear,
            font=FONT_BUTTON,
            corner_radius=10,
            fg_color="transparent",
            hover_color=("gray85", "gray25"),
        )
        self._clear_btn.grid(row=0, column=2, padx=(0, 5), pady=15)

        # ── Botón Comandos ───────────────────────────────────────────────
        self._cmd_btn = ctk.CTkButton(
            self,
            text="?",
            width=40,
            command=self._on_command_palette,
            font=FONT_BUTTON,
            corner_radius=10,
            fg_color="transparent",
            hover_color=("gray85", "gray25"),
        )
        self._cmd_btn.grid(row=0, column=3, padx=(0, 15), pady=15)

        # ── Progress Bar ───────────────────────────────────────────────────
        self._progress = ctk.CTkProgressBar(
            self,
            mode="indeterminate",
            height=4,
            corner_radius=2,
        )
        self._progress.grid(row=1, column=0, columnspan=4, padx=15, pady=(0, 10), sticky="ew")
        self._progress.set(0)
        self._progress.grid_remove()

    # ── Acciones ───────────────────────────────────────────────────────────────

    def _handle_send(self) -> None:
        """Envía el mensaje si no está pendiente."""
        if self._pending:
            return
        text = self._entry.get().strip()
        if not text:
            return
        self._entry.delete(0, "end")
        self._on_send(text)

    def set_pending(self, pending: bool) -> None:
        """Activa/desactiva el estado de procesamiento."""
        self._pending = pending
        state = "disabled" if pending else "normal"
        self._entry.configure(state=state)
        self._send_btn.configure(state=state)

        if pending:
            self._progress.grid()
            self._progress.start()
        else:
            self._progress.stop()
            self._progress.grid_remove()

    def focus(self) -> None:
        """Pone el foco en el entry."""
        self._entry.focus_set()
