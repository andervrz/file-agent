# app/widgets/session_dialog.py
"""
widgets/session_dialog.py — CTkToplevel para crear, renombrar, archivar o eliminar sesiones.

Responsabilidades:
  - Diálogo modal para nueva sesión (título editable)
  - Confirmación antes de archivar
  - Confirmación antes de eliminar permanentemente
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
    COLOR_ERROR,
)


class SessionDialog(ctk.CTkToplevel):
    """
    Diálogo modal para gestión de sesiones.
    """

    def __init__(
        self,
        master,
        mode: str,  # "create" | "rename" | "archive" | "delete"
        session_title: str = "",
        on_confirm: Callable[[str], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)

        self._mode = mode
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel

        self.title(self._get_title())
        self.geometry(self._get_geometry())
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
                placeholder_text="Session name…",
                corner_radius=8,
            )
            self._entry.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
            if session_title:
                self._entry.insert(0, session_title)
            self._entry.bind("<Return>", lambda _e: self._confirm())
            self.after(100, self._entry.focus_set)
        elif mode == "delete":
            # Mode delete: mensaje de advertencia
            msg = ctk.CTkLabel(
                self,
                text="This action cannot be undone.\nAll data will be permanently lost.",
                font=FONT_BODY,
                text_color=COLOR_ERROR,
            )
            msg.grid(row=1, column=0, padx=20, pady=10)
        else:
            # Mode archive: mensaje de confirmación
            msg = ctk.CTkLabel(
                self,
                text=f"Archive session\n\"{session_title}\"?",
                font=FONT_BODY,
                text_color=COLOR_TEXT_PRIMARY,
            )
            msg.grid(row=1, column=0, padx=20, pady=10)

        # ── Botones ────────────────────────────────────────────────────────
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=2, column=0, padx=20, pady=(10, 20), sticky="e")

        cancel_btn = ctk.CTkButton(
            btn_frame,
            text="Cancel",
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
            fg_color=self._get_confirm_color(),
            hover_color=self._get_confirm_hover_color(),
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
            "create": "New session",
            "rename": "Rename session",
            "archive": "Archive session",
            "delete": "Delete session",
        }.get(self._mode, "Session")

    def _get_geometry(self) -> str:
        return {
            "delete": "400x200",
        }.get(self._mode, "400x180")

    def _get_header_text(self) -> str:
        return {
            "create": "Create new session",
            "rename": "Rename session",
            "archive": "Confirm archive",
            "delete": "⚠️  Confirm permanent deletion",
        }.get(self._mode, "")

    def _get_confirm_text(self) -> str:
        return {
            "create": "Create",
            "rename": "Save",
            "archive": "Archive",
            "delete": "Delete",
        }.get(self._mode, "OK")

    def _get_confirm_color(self) -> str:
        return {
            "delete": "#DC2626",  # rojo
        }.get(self._mode, None)

    def _get_confirm_hover_color(self) -> str:
        return {
            "delete": "#B91C1C",  # rojo oscuro
        }.get(self._mode, None)
