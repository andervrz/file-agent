"""
widgets/sidebar.py — Sidebar con lista de sesiones, stats y controles.

Responsabilidades:
  - Lista de sesiones agrupadas por fecha (Hoy, Ayer, etc.)
  - Indicador de sesión activa
  - Botón "Nueva sesión"
  - Stats del modelo y sesión actual
  - Search box para filtrar sesiones
"""
from __future__ import annotations

import customtkinter as ctk
from typing import Callable
from datetime import datetime, timezone

from ..theme import (
    FONT_TITLE,
    FONT_SUBTITLE,
    FONT_SMALL,
    FONT_TINY,
    COLOR_BG_SECONDARY,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_TEXT_MUTED,
    COLOR_ACCENT,
    SIDEBAR_W,
    SessionItem,
)


class Sidebar(ctk.CTkFrame):
    """
    Sidebar izquierdo: título, lista de sesiones, stats, controles.
    """

    def __init__(
        self,
        master,
        on_new_session: Callable[[], None],
        on_select_session: Callable[[str], None],
        on_archive_session: Callable[[str], None],
        on_rename_session: Callable[[str, str], None],
        **kwargs,
    ) -> None:
        super().__init__(master, width=SIDEBAR_W, corner_radius=0, fg_color=COLOR_BG_SECONDARY, **kwargs)
        self.grid_propagate(False)

        self._on_new_session = on_new_session
        self._on_select_session = on_select_session
        self._on_archive_session = on_archive_session
        self._on_rename_session = on_rename_session

        self._session_buttons: dict[str, _SessionButton] = {}
        self._current_session_id: str | None = None

        # Grid layout
        self.grid_rowconfigure(2, weight=1)  # lista de sesiones expande
        self.grid_columnconfigure(0, weight=1)

        # ── Header ───────────────────────────────────────────────────────
        self._build_header()

        # ── Search ───────────────────────────────────────────────────────
        self._build_search()

        # ── Session List ─────────────────────────────────────────────────
        self._session_frame = ctk.CTkScrollableFrame(
            self,
            label_text="Sesiones",
            corner_radius=8,
            fg_color=COLOR_BG_SECONDARY,
        )
        self._session_frame.grid(row=2, column=0, padx=15, pady=10, sticky="nsew")
        self._session_frame.grid_columnconfigure(0, weight=1)

        # ── Stats ────────────────────────────────────────────────────────
        self._build_stats()

        # ── Controls ─────────────────────────────────────────────────────
        self._build_controls()

    # ── Builders ───────────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        title = ctk.CTkLabel(
            self,
            text="📁  File Agent",
            font=FONT_TITLE,
            text_color=COLOR_TEXT_PRIMARY,
        )
        title.grid(row=0, column=0, padx=20, pady=(20, 5), sticky="w")

        subtitle = ctk.CTkLabel(
            self,
            text="Gestión de archivos, terminal\ny navegador web",
            font=FONT_SUBTITLE,
            text_color=COLOR_TEXT_SECONDARY,
        )
        subtitle.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="w")

    def _build_search(self) -> None:
        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._filter_sessions())

        search_entry = ctk.CTkEntry(
            self,
            placeholder_text="Buscar sesión…",
            font=FONT_SMALL,
            corner_radius=8,
            height=32,
            textvariable=self._search_var,
        )
        search_entry.grid(row=3, column=0, padx=15, pady=(0, 10), sticky="ew")

    def _build_stats(self) -> None:
        self._stats_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._stats_frame.grid(row=4, column=0, padx=15, pady=10, sticky="ew")

        self._stats_labels: dict[str, ctk.CTkLabel] = {}
        stats = [
            ("modelo", "Modelo:"),
            ("turnos", "Turnos:"),
            ("tools", "Tools:"),
            ("tokens", "Tokens:"),
        ]
        for i, (key, text) in enumerate(stats):
            lbl = ctk.CTkLabel(
                self._stats_frame,
                text=f"{text} —",
                font=FONT_TINY,
                text_color=COLOR_TEXT_SECONDARY,
                anchor="w",
            )
            lbl.grid(row=i, column=0, sticky="w", pady=1)
            self._stats_labels[key] = lbl

    def _build_controls(self) -> None:
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=5, column=0, padx=15, pady=15, sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=1)

        new_btn = ctk.CTkButton(
            btn_frame,
            text="+  Nueva sesión",
            command=self._on_new_session,
            font=FONT_SMALL,
            corner_radius=8,
        )
        new_btn.grid(row=0, column=0, pady=(0, 8), sticky="ew")

        # Theme toggle
        self._theme_btn = ctk.CTkSegmentedButton(
            btn_frame,
            values=["Light", "System", "Dark"],
            command=self._on_theme_change,
            font=FONT_TINY,
        )
        self._theme_btn.set("System")
        self._theme_btn.grid(row=1, column=0, sticky="ew")

    # ── Session Management ─────────────────────────────────────────────────────

    def set_sessions(self, sessions: list[SessionItem]) -> None:
        """Actualiza la lista completa de sesiones."""
        # Limpiar anteriores
        for btn in self._session_buttons.values():
            btn.destroy()
        self._session_buttons = {}

        # Agrupar por fecha
        grouped = self._group_by_date(sessions)

        row = 0
        for group_name, items in grouped.items():
            # Header de grupo
            group_lbl = ctk.CTkLabel(
                self._session_frame,
                text=group_name,
                font=FONT_TINY,
                text_color=COLOR_TEXT_MUTED,
                anchor="w",
            )
            group_lbl.grid(row=row, column=0, sticky="w", pady=(8, 2))
            row += 1

            for item in items:
                btn = _SessionButton(
                    self._session_frame,
                    item=item,
                    on_select=lambda sid=item.session_id: self._select_session(sid),
                    on_archive=lambda sid=item.session_id: self._on_archive_session(sid),
                    on_rename=lambda sid=item.session_id, t=item.title: self._on_rename_session(sid, t),
                )
                btn.grid(row=row, column=0, sticky="ew", pady=2)
                self._session_buttons[item.session_id] = btn
                row += 1

    def set_active_session(self, session_id: str) -> None:
        """Marca una sesión como activa (indicador visual)."""
        self._current_session_id = session_id
        for sid, btn in self._session_buttons.items():
            btn.set_active(sid == session_id)

    def update_stats(self, model: str, turns: int, tools: int, tokens: int) -> None:
        """Actualiza las estadísticas mostradas."""
        self._stats_labels["modelo"].configure(text=f"Modelo: {model}")
        self._stats_labels["turnos"].configure(text=f"Turnos: {turns}")
        self._stats_labels["tools"].configure(text=f"Tools: {tools}")
        self._stats_labels["tokens"].configure(text=f"Tokens: {tokens:,}")

    # ── Internals ──────────────────────────────────────────────────────────────

    def _group_by_date(self, sessions: list[SessionItem]) -> dict[str, list[SessionItem]]:
        """Agrupa sesiones por fecha relativa."""
        groups: dict[str, list[SessionItem]] = {}
        for s in sessions:
            key = s.relative_time
            if key not in groups:
                groups[key] = []
            groups[key].append(s)
        # Ordenar: Hoy, Ayer, luego cronológico inverso
        priority = {"Hoy": 0, "Ayer": 1}
        sorted_keys = sorted(groups.keys(), key=lambda k: priority.get(k, 2))
        return {k: groups[k] for k in sorted_keys}

    def _filter_sessions(self) -> None:
        """Filtra sesiones por texto de búsqueda."""
        query = self._search_var.get().lower()
        for sid, btn in self._session_buttons.items():
            visible = query in btn.title.lower() or query in sid.lower()
            btn.grid() if visible else btn.grid_remove()

    def _select_session(self, session_id: str) -> None:
        self._on_select_session(session_id)

    def _on_theme_change(self, value: str) -> None:
        ctk.set_appearance_mode(value)


# ─── Session Button ─────────────────────────────────────────────────────────

class _SessionButton(ctk.CTkFrame):
    """
    Botón de sesión individual con indicador activo, título, preview y timestamp.
    """

    def __init__(
        self,
        master,
        item: SessionItem,
        on_select: Callable[[], None],
        on_archive: Callable[[], None],
        on_rename: Callable[[], None],
    ) -> None:
        super().__init__(master, fg_color="transparent", corner_radius=6, height=50)
        self.grid_propagate(False)

        self._item = item
        self._on_select = on_select
        self.title = item.title

        # Indicador de estado (circulo coloreado)
        self._indicator = ctk.CTkLabel(
            self,
            text="●",
            font=("", 10),
            text_color=COLOR_TEXT_MUTED,
            width=20,
        )
        self._indicator.grid(row=0, column=0, rowspan=2, padx=(8, 0), pady=4)

        # Título
        self._title_lbl = ctk.CTkLabel(
            self,
            text=item.display_title,
            font=FONT_SMALL,
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        self._title_lbl.grid(row=0, column=1, sticky="w", padx=(4, 8), pady=(4, 0))

        # Info secundaria: turnos + tiempo relativo
        info_text = f"{item.total_turns} turnos · {item.relative_time}"
        self._info_lbl = ctk.CTkLabel(
            self,
            text=info_text,
            font=FONT_TINY,
            text_color=COLOR_TEXT_SECONDARY,
            anchor="w",
        )
        self._info_lbl.grid(row=1, column=1, sticky="w", padx=(4, 8), pady=(0, 4))

        # Click handler
        self.bind("<Button-1>", lambda _e: on_select())
        self._title_lbl.bind("<Button-1>", lambda _e: on_select())
        self._info_lbl.bind("<Button-1>", lambda _e: on_select())

        # Hover
        self.bind("<Enter>", self._on_hover)
        self.bind("<Leave>", self._on_leave)

    def set_active(self, active: bool) -> None:
        """Cambia el color del indicador según estado activo."""
        color = COLOR_ACCENT[0] if active else COLOR_TEXT_MUTED
        self._indicator.configure(text_color=color)
        if active:
            self.configure(fg_color=("gray85", "gray25"))
        else:
            self.configure(fg_color="transparent")

    def _on_hover(self, _event=None) -> None:
        if self._indicator.cget("text_color") != COLOR_ACCENT[0]:
            self.configure(fg_color=("gray88", "gray22"))

    def _on_leave(self, _event=None) -> None:
        if self._indicator.cget("text_color") != COLOR_ACCENT[0]:
            self.configure(fg_color="transparent")
