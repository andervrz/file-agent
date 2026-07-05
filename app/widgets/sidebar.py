# app/widgets/sidebar.py
"""
widgets/sidebar.py — Sidebar con lista de sesiones, stats y controles.

Responsabilidades:
  - Lista de sesiones agrupadas por fecha (Today, Yesterday, etc.)
  - Indicador de sesión activa
  - Botón "New session"
  - Stats del modelo y sesión actual
  - Search box para filtrar sesiones
  - Menú contextual (click derecho) con archive, rename, delete
  - Toggle visual Active / Archived sobre la lista de sesiones

CAMBIO (v2.1):
  - Pool de widgets reutilizables: grid_remove/grid en vez de destroy/create.
  - Actualización de texto/estado en botones existentes (zero widget churn).
  - Agrupación por fecha con orden estable (Today, Yesterday, N days ago, fecha).
"""
from __future__ import annotations

import customtkinter as ctk
from typing import Callable
from datetime import datetime, timezone

from ..entities import SessionItem
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
)


class Sidebar(ctk.CTkFrame):
    """
    Sidebar izquierdo: título, search, toggle Active/Archived, lista, stats, controles.
    """

    def __init__(
        self,
        master,
        on_new_session: Callable[[], None],
        on_select_session: Callable[[str], None],
        on_archive_session: Callable[[str, str], None],
        on_rename_session: Callable[[str, str], None],
        on_delete_session: Callable[[str, str], None],
        on_toggle_trash: Callable[[], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, width=SIDEBAR_W, corner_radius=0, fg_color=COLOR_BG_SECONDARY, **kwargs)
        self.grid_propagate(False)

        self._on_new_session = on_new_session
        self._on_select_session = on_select_session
        self._on_archive_session = on_archive_session
        self._on_rename_session = on_rename_session
        self._on_delete_session = on_delete_session
        self._on_toggle_trash = on_toggle_trash

        # Pool de widgets reutilizables
        self._session_buttons: dict[str, _SessionButton] = {}
        self._group_labels: list[ctk.CTkLabel] = []
        self._current_session_id: str | None = None
        self._showing_trash = False

        # Grid layout
        self.grid_rowconfigure(4, weight=1)  # lista de sesiones expande
        self.grid_columnconfigure(0, weight=1)

        # ── Header ───────────────────────────────────────────────────────
        self._build_header()

        # ── Search ───────────────────────────────────────────────────────
        self._build_search()

        # ── View Toggle (Active / Archived) ──────────────────────────────
        self._build_view_toggle()

        # ── Session List ─────────────────────────────────────────────────
        self._session_frame = ctk.CTkScrollableFrame(
            self,
            label_text="Sessions",
            corner_radius=8,
            fg_color=COLOR_BG_SECONDARY,
        )
        self._session_frame.grid(row=4, column=0, padx=15, pady=10, sticky="nsew")
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
            text="File management, terminal\nand web browser",
            font=FONT_SUBTITLE,
            text_color=COLOR_TEXT_SECONDARY,
        )
        subtitle.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="w")

    def _build_search(self) -> None:
        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._filter_sessions())

        search_entry = ctk.CTkEntry(
            self,
            placeholder_text="Search session…",
            font=FONT_SMALL,
            corner_radius=8,
            height=32,
            textvariable=self._search_var,
        )
        search_entry.grid(row=2, column=0, padx=15, pady=(0, 5), sticky="ew")

    def _build_view_toggle(self) -> None:
        """Toggle visual Active / Archived justo encima de la lista."""
        self._view_toggle = ctk.CTkSegmentedButton(
            self,
            values=["Active", "Archived"],
            command=self._on_view_toggle,
            font=FONT_TINY,
        )
        self._view_toggle.set("Active")
        self._view_toggle.grid(row=3, column=0, padx=15, pady=(0, 5), sticky="ew")

    def _build_stats(self) -> None:
        self._stats_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._stats_frame.grid(row=5, column=0, padx=15, pady=10, sticky="ew")

        self._stats_labels: dict[str, ctk.CTkLabel] = {}
        stats = [
            ("model", "Model:"),
            ("turns", "Turns:"),
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
        btn_frame.grid(row=6, column=0, padx=15, pady=15, sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=1)

        new_btn = ctk.CTkButton(
            btn_frame,
            text="+  New session",
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

    # ── Session Management (pool reutilizable) ────────────────────────────────

    def set_sessions(self, sessions: list[SessionItem]) -> None:
        """
        Actualiza la lista de sesiones reutilizando widgets existentes.
        Zero destroy/create en el hot path. Solo grid_remove/ocultar sobrantes.
        """
        # 1. Ocultar todo lo existente
        for btn in self._session_buttons.values():
            btn.grid_remove()
        for lbl in self._group_labels:
            lbl.grid_remove()

        # 2. Filtrar según vista
        if self._showing_trash:
            filtered = [s for s in sessions if s.status == "archived"]
            self._session_frame.configure(label_text="Archived Sessions")
        else:
            filtered = [s for s in sessions if s.status == "active"]
            self._session_frame.configure(label_text="Sessions")

        # 3. Agrupar por fecha
        grouped = self._group_by_date(filtered)

        # 4. Reutilizar o crear widgets
        needed_session_ids: set[str] = set()
        group_idx = 0
        btn_idx = 0

        for group_name, items in grouped.items():
            # Reutilizar o crear label de grupo
            if group_idx < len(self._group_labels):
                group_lbl = self._group_labels[group_idx]
                group_lbl.configure(text=group_name)
                group_lbl.grid()
            else:
                group_lbl = ctk.CTkLabel(
                    self._session_frame,
                    text=group_name,
                    font=FONT_TINY,
                    text_color=COLOR_TEXT_MUTED,
                    anchor="w",
                )
                group_lbl.grid(sticky="w", pady=(8, 2))
                self._group_labels.append(group_lbl)
            group_idx += 1

            for item in items:
                needed_session_ids.add(item.session_id)

                if item.session_id in self._session_buttons:
                    # Reutilizar botón existente
                    btn = self._session_buttons[item.session_id]
                    btn.update_item(item)
                    btn.grid(sticky="ew", pady=2)
                else:
                    # Crear nuevo botón
                    btn = _SessionButton(
                        self._session_frame,
                        item=item,
                        on_select=lambda sid=item.session_id: self._select_session(sid),
                        on_archive=lambda sid=item.session_id, t=item.title: self._on_archive_session(sid, t),
                        on_rename=lambda sid=item.session_id, t=item.title: self._on_rename_session(sid, t),
                        on_delete=lambda sid=item.session_id, t=item.title: self._on_delete_session(sid, t),
                        showing_trash=self._showing_trash,
                    )
                    btn.grid(sticky="ew", pady=2)
                    self._session_buttons[item.session_id] = btn
                btn_idx += 1

        # 5. Destruir solo los que ya no existen (raro, pero necesario)
        stale_ids = set(self._session_buttons.keys()) - needed_session_ids
        for sid in stale_ids:
            self._session_buttons[sid].destroy()
            del self._session_buttons[sid]

        # 6. Ocultar labels de grupo sobrantes
        for i in range(group_idx, len(self._group_labels)):
            self._group_labels[i].grid_remove()

    def set_active_session(self, session_id: str) -> None:
        """Marca una sesión como activa (indicador visual)."""
        self._current_session_id = session_id
        for sid, btn in self._session_buttons.items():
            btn.set_active(sid == session_id)

    def update_stats(self, model: str, turns: int, tools: int, tokens_in: int, tokens_out: int) -> None:
        """Actualiza las estadísticas mostradas."""
        self._stats_labels["model"].configure(text=f"Model: {model}")
        self._stats_labels["turns"].configure(text=f"Turns: {turns}")
        self._stats_labels["tools"].configure(text=f"Tools: {tools}")
        self._stats_labels["tokens"].configure(text=f"Tokens: ↑{tokens_in:,} ↓{tokens_out:,}")

    # ── View Toggle ───────────────────────────────────────────────────────────

    def _on_view_toggle(self, value: str) -> None:
        self._showing_trash = (value == "Archived")
        if self._on_toggle_trash:
            self._on_toggle_trash()

    def set_view(self, view: str) -> None:
        """Cambia la vista desde código (ej. auto-switch al archivar)."""
        if view in ("Active", "Archived"):
            self._view_toggle.set(view)
            self._showing_trash = (view == "Archived")

    def is_showing_trash(self) -> bool:
        return self._showing_trash

    # ── Internals ──────────────────────────────────────────────────────────────

    def _group_by_date(self, sessions: list[SessionItem]) -> dict[str, list[SessionItem]]:
        """Agrupa sesiones por fecha relativa con orden estable."""
        groups: dict[str, list[SessionItem]] = {}
        for s in sessions:
            key = s.relative_time
            if key not in groups:
                groups[key] = []
            groups[key].append(s)

        # Orden estable: Today → Yesterday → N days ago → fechas
        priority = {"Today": 0, "Yesterday": 1}
        sorted_keys = sorted(groups.keys(), key=lambda k: priority.get(k, 2))
        return {k: groups[k] for k in sorted_keys}

    def _filter_sessions(self) -> None:
        """Filtra sesiones por texto de búsqueda."""
        query = self._search_var.get().lower()
        for sid, btn in self._session_buttons.items():
            visible = query in btn.title.lower() or query in sid.lower()
            if visible:
                btn.grid()
            else:
                btn.grid_remove()

    def _select_session(self, session_id: str) -> None:
        self._on_select_session(session_id)

    def _on_theme_change(self, value: str) -> None:
        ctk.set_appearance_mode(value)


# ─── Session Button (con update_item reutilizable) ──────────────────────────

class _SessionButton(ctk.CTkFrame):
    """
    Botón de sesión individual con indicador activo, título, preview y timestamp.
    Soporta menú contextual (click derecho) para archive/rename/delete.
    """

    def __init__(
        self,
        master,
        item: SessionItem,
        on_select: Callable[[], None],
        on_archive: Callable[[], None],
        on_rename: Callable[[], None],
        on_delete: Callable[[], None],
        showing_trash: bool = False,
    ) -> None:
        super().__init__(master, fg_color="transparent", corner_radius=6, height=50)
        self.grid_propagate(False)

        self._on_select = on_select
        self._on_archive = on_archive
        self._on_rename = on_rename
        self._on_delete = on_delete
        self._showing_trash = showing_trash
        self.title = item.title

        # Indicador de estado (círculo coloreado)
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
        info_text = f"{item.total_turns} turns · {item.relative_time}"
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

        # Menú contextual (click derecho)
        self._context_menu = None
        self.bind("<Button-3>", self._show_context_menu)
        self._title_lbl.bind("<Button-3>", self._show_context_menu)
        self._info_lbl.bind("<Button-3>", self._show_context_menu)

    def update_item(self, item: SessionItem) -> None:
        """
        Actualiza texto y callbacks sin destruir/recreate el widget.
        Llamado al reutilizar un botón del pool.
        """
        self._item = item
        self.title = item.title

        self._title_lbl.configure(text=item.display_title)

        info_text = f"{item.total_turns} turns · {item.relative_time}"
        self._info_lbl.configure(text=info_text)

        # Actualizar callbacks (necesario si el item cambió de ID, aunque raro)
        self._on_select = item.on_select or self._on_select
        self._on_archive = item.on_archive or self._on_archive
        self._on_rename = item.on_rename or self._on_rename
        self._on_delete = item.on_delete or self._on_delete

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

    def _show_context_menu(self, event) -> None:
        """Muestra menú contextual con opciones de sesión."""
        if self._context_menu is not None:
            self._context_menu.destroy()

        self._context_menu = ctk.CTkToplevel(self)
        self._context_menu.overrideredirect(True)
        self._context_menu.geometry(f"+{event.x_root}+{event.y_root}")

        if self._showing_trash:
            self._add_menu_item("🗑️  Delete permanently", self._on_delete)
        else:
            self._add_menu_item("✏️  Rename", self._on_rename)
            self._add_menu_item("📦  Archive", self._on_archive)
            self._add_menu_item("🗑️  Delete", self._on_delete)

    def _add_menu_item(self, text: str, command: Callable[[], None]) -> None:
        btn = ctk.CTkButton(
            self._context_menu,
            text=text,
            anchor="w",
            font=FONT_TINY,
            fg_color="transparent",
            hover_color=("gray85", "gray25"),
            command=lambda: (command(), self._context_menu.destroy()),
        )
        btn.pack(fill="x", padx=2, pady=1)
