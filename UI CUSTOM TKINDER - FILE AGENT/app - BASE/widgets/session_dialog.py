"""
widgets/session_dialog.py — CTkToplevel para crear, renombrar o archivar sesiones.

Responsabilidades:
  - Diálogo modal para nueva sesión (título editable)
  - Confirmación antes de archivar
  - Input validation básica
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
)


class SessionDialog(ctk.CTkToplevel):
    """
    Diálogo modal para gestión de sesiones.
    """

    def __init__(
        self,
        master,
        mode: str,  # "create" | "rename" | "archive"
        session_title: str = "",
        on_confirm: Callable[[str], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)

        self._mode = mode
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel

        self.title(self._get_title())
        self.geometry("400x180")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── Header ───────────────────────────────────────────────────────
        header = ctk.CTkLabel(
            self,
            text=self._get_header_text(),
            font=FONT_BODY_BOLD,
            text_color=COLOR_TEXT_PRIMARY,
        )
        header.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")

        # ── Input (solo create/rename) ────────────────────────────────────
        if mode in ("create", "rename"):
            self._entry = ctk.CTkEntry(
                self,
                font=FONT_BODY,
                placeholder_text="Nombre de la sesión…",
                corner_radius=8,
            )
            self._entry.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
            if session_title:
                self._entry.insert(0, session_title)
            self._entry.bind("<Return>", lambda _e: self._confirm())
            self.after(100, self._entry.focus_set)
        else:
            # Mode archive: mensaje de confirmación
            msg = ctk.CTkLabel(
                self,
                text=f"¿Archivar la sesión\n\"{session_title}\"?",
                font=FONT_BODY,
                text_color=COLOR_TEXT_PRIMARY,
            )
            msg.grid(row=1, column=0, padx=20, pady=10)

        # ── Botones ────────────────────────────────────────────────────────
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=2, column=0, padx=20, pady=(10, 20), sticky="e")

        cancel_btn = ctk.CTkButton(
            btn_frame,
            text="Cancelar",
            command=self._cancel,
            font=FONT_SMALL,
            fg_color="transparent",
            hover_color=("gray85", "gray25"),
        )
        cancel_btn.pack(side="left", padx=(0, 10))

        confirm_btn = ctk.CTkButton(
            btn_frame,
            text=self._get_confirm_text(),
            command=self._confirm,
            font=FONT_SMALL,
        )
        confirm_btn.pack(side="left")

    # ── Actions ────────────────────────────────────────────────────────────────

    def _confirm(self) -> None:
        if self._mode in ("create", "rename"):
            text = self._entry.get().strip()
            if not text:
                return
            if self._on_confirm:
                self._on_confirm(text)
        else:
            if self._on_confirm:
                self._on_confirm("")
        self.destroy()

    def _cancel(self) -> None:
        if self._on_cancel:
            self._on_cancel()
        self.destroy()

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _get_title(self) -> str:
        return {
            "create": "Nueva sesión",
            "rename": "Renombrar sesión",
            "archive": "Archivar sesión",
        }.get(self._mode, "Sesión")

    def _get_header_text(self) -> str:
        return {
            "create": "Crear nueva sesión",
            "rename": "Renombrar sesión",
            "archive": "Confirmar archivado",
        }.get(self._mode, "")

    def _get_confirm_text(self) -> str:
        return {
            "create": "Crear",
            "rename": "Guardar",
            "archive": "Archivar",
        }.get(self._mode, "OK")
