# app/widgets/sidebar.py
"""
widgets/sidebar.py — Sidebar with session list, stats and controls.

FIXES:
  - Inline rename with double-click (CTkEntry overlay)
  - Right-click context menu: Rename / Archive / Delete (if archived)
  - Toggle "Show Archived"
  - Stats: Model / Turns / Tools / Tokens (English)
  - Real counter from conversation_turns
  - Proper CTkScrollableFrame widget packing
"""
from __future__ import annotations

import customtkinter as ctk
import tkinter as tk
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
    Left sidebar: title, session list, stats, controls.
    """

    def __init__(
        self,
        master,
        on_new_session: Callable[[], None],
        on_select_session: Callable[[str], None],
        on_archive_session: Callable[[str], None],
        on_rename_session: Callable[[str, str], None],
        on_delete_session: Callable[[str], None] | None = None,
        on_theme_change: Callable[[str], None] | None = None,
        on_show_archived: Callable[[bool], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, width=SIDEBAR_W, corner_radius=0, fg_color=COLOR_BG_SECONDARY, **kwargs)
        self.grid_propagate(False)

        self._on_new_session = on_new_session
        self._on_select_session = on_select_session
        self._on_archive_session = on_archive_session
        self._on_rename_session = on_rename_session
        self._on_delete_session = on_delete_session
        self._on_theme_change = on_theme_change
        self._on_show_archived = on_show_archived

        self._session_buttons: dict[str, _SessionButton] = {}
        self._current_session_id: str | None = None
        self._show_archived = False

        # Grid layout
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_search()
        self._build_session_list()
        self._build_stats()
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
        search_entry.grid(row=3, column=0, padx=15, pady=(0, 10), sticky="ew")

    def _build_session_list(self) -> None:
        # Toggle archived
        self._archived_toggle = ctk.CTkSwitch(
            self,
            text="Show Archived",
            font=FONT_TINY,
            command=self._toggle_archived,
        )
        self._archived_toggle.grid(row=4, column=0, padx=15, pady=(0, 5), sticky="w")

        # Scrollable frame
        self._session_scroll = ctk.CTkScrollableFrame(
            self,
            label_text="Sessions",
            corner_radius=8,
            fg_color=COLOR_BG_SECONDARY,
        )
        self._session_scroll.grid(row=5, column=0, padx=15, pady=10, sticky="nsew")
        self._session_scroll.grid_columnconfigure(0, weight=1)

        # The internal frame where we place widgets
        self._session_frame = self._session_scroll

    def _build_stats(self) -> None:
        self._stats_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._stats_frame.grid(row=6, column=0, padx=15, pady=10, sticky="ew")

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
        btn_frame.grid(row=7, column=0, padx=15, pady=15, sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=1)

        new_btn = ctk.CTkButton(
            btn_frame,
            text="+  New Session",
            command=self._on_new_session,
            font=FONT_SMALL,
            corner_radius=8,
        )
        new_btn.grid(row=0, column=0, pady=(0, 8), sticky="ew")

        # Theme toggle
        if self._on_theme_change:
            self._theme_btn = ctk.CTkSegmentedButton(
                btn_frame,
                values=["Light", "System", "Dark"],
                command=self._on_theme_change,
                font=FONT_TINY,
            )
            self._theme_btn.set("System")
            self._theme_btn.grid(row=1, column=0, sticky="ew")

    # ── Session Management ─────────────────────────────────────────────────────

    def set_sessions(self, sessions: list[SessionItem], show_archived: bool = False) -> None:
        """Updates the full session list."""
        # Destroy old buttons
        for btn in self._session_buttons.values():
            btn.destroy()
        self._session_buttons = {}

        # Filter by toggle
        visible = sessions if show_archived else [s for s in sessions if s.status == "active"]

        if not visible:
            # Show "No sessions" label
            empty_lbl = ctk.CTkLabel(
                self._session_frame,
                text="No sessions found",
                font=FONT_TINY,
                text_color=COLOR_TEXT_MUTED,
            )
            empty_lbl.pack(fill="x", padx=10, pady=10)
            self._session_buttons["__empty__"] = empty_lbl  # type: ignore
            return

        grouped = self._group_by_date(visible)

        for group_name, items in grouped.items():
            group_lbl = ctk.CTkLabel(
                self._session_frame,
                text=group_name,
                font=FONT_TINY,
                text_color=COLOR_TEXT_MUTED,
                anchor="w",
            )
            group_lbl.pack(fill="x", padx=8, pady=(8, 2))

            for item in items:
                btn = _SessionButton(
                    self._session_frame,
                    item=item,
                    on_select=lambda sid=item.session_id: self._select_session(sid),
                    on_archive=lambda sid=item.session_id: self._on_archive_session(sid),
                    on_rename=lambda sid=item.session_id, t=item.title: self._on_rename_session(sid, t),
                    on_delete=self._on_delete_session and (lambda sid=item.session_id: self._on_delete_session(sid)),
                    on_start_rename=lambda sid=item.session_id, t=item.title, b=None: self._start_inline_rename(sid, t, b),
                )
                btn.pack(fill="x", padx=4, pady=2)
                self._session_buttons[item.session_id] = btn

    def set_active_session(self, session_id: str) -> None:
        """Marks a session as active."""
        self._current_session_id = session_id
        for sid, btn in self._session_buttons.items():
            if sid == "__empty__":
                continue
            btn.set_active(sid == session_id)

    def update_stats(self, model: str, turns: int, tools: int, tokens: int) -> None:
        """Updates displayed statistics."""
        self._stats_labels["model"].configure(text=f"Model: {model}")
        self._stats_labels["turns"].configure(text=f"Turns: {turns}")
        self._stats_labels["tools"].configure(text=f"Tools: {tools}")
        self._stats_labels["tokens"].configure(text=f"Tokens: {tokens:,}")

    # ── Inline Rename ──────────────────────────────────────────────────────────

    def _start_inline_rename(self, session_id: str, current_title: str, button) -> None:
        """Starts inline rename mode for a session."""
        btn = self._session_buttons.get(session_id)
        if not btn or session_id == "__empty__":
            return

        entry = ctk.CTkEntry(
            btn,
            font=FONT_SMALL,
            height=24,
        )
        entry.insert(0, current_title)
        entry.place(relx=0.15, rely=0.2, relwidth=0.8)

        def _save(_event=None):
            new_title = entry.get().strip()
            entry.destroy()
            if new_title and new_title != current_title:
                self._on_rename_session(session_id, new_title)

        def _cancel(_event=None):
            entry.destroy()

        entry.bind("<Return>", _save)
        entry.bind("<Escape>", _cancel)
        entry.bind("<FocusOut>", _save)
        entry.focus_set()

    # ── Internals ──────────────────────────────────────────────────────────────

    def _group_by_date(self, sessions: list[SessionItem]) -> dict[str, list[SessionItem]]:
        """Groups sessions by relative date."""
        groups: dict[str, list[SessionItem]] = {}
        for s in sessions:
            key = s.relative_time
            if key not in groups:
                groups[key] = []
            groups[key].append(s)
        priority = {"Today": 0, "Yesterday": 1}
        sorted_keys = sorted(groups.keys(), key=lambda k: priority.get(k, 2))
        return {k: groups[k] for k in sorted_keys}

    def _filter_sessions(self) -> None:
        """Filters sessions by search text."""
        query = self._search_var.get().lower()
        for sid, btn in self._session_buttons.items():
            if sid == "__empty__":
                continue
            visible = query in btn._item.title.lower() or query in sid.lower()
            if visible:
                btn.pack(fill="x", padx=4, pady=2)
            else:
                btn.pack_forget()

    def _select_session(self, session_id: str) -> None:
        self._on_select_session(session_id)

    def _toggle_archived(self) -> None:
        """FIX: properly invokes the callback passed from app."""
        self._show_archived = bool(self._archived_toggle.get())
        if self._on_show_archived:
            self._on_show_archived(self._show_archived)


# ─── Session Button ─────────────────────────────────────────────────────────

class _SessionButton(ctk.CTkFrame):
    """
    Individual session button with active indicator, title, preview and timestamp.
    Supports double-click for inline rename and right-click for context menu.
    """

    def __init__(
        self,
        master,
        item: SessionItem,
        on_select: Callable[[], None],
        on_archive: Callable[[], None],
        on_rename: Callable[[], None],
        on_delete: Callable[[], None] | None = None,
        on_start_rename: Callable | None = None,
    ) -> None:
        super().__init__(master, fg_color="transparent", corner_radius=6, height=50)
        self.grid_propagate(False)

        self._item = item
        self._on_select = on_select
        self._on_archive = on_archive
        self._on_rename = on_rename
        self._on_delete = on_delete
        self._on_start_rename = on_start_rename

        # Status indicator
        self._indicator = ctk.CTkLabel(
            self,
            text="●",
            font=("", 10),
            text_color=COLOR_TEXT_MUTED,
            width=20,
        )
        self._indicator.grid(row=0, column=0, rowspan=2, padx=(8, 0), pady=4)

        # Title
        self._title_lbl = ctk.CTkLabel(
            self,
            text=item.display_title,
            font=FONT_SMALL,
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        self._title_lbl.grid(row=0, column=1, sticky="w", padx=(4, 8), pady=(4, 0))

        # Secondary info
        info_text = f"{item.total_turns} turns · {item.relative_time}"
        self._info_lbl = ctk.CTkLabel(
            self,
            text=info_text,
            font=FONT_TINY,
            text_color=COLOR_TEXT_SECONDARY,
            anchor="w",
        )
        self._info_lbl.grid(row=1, column=1, sticky="w", padx=(4, 8), pady=(0, 4))

        # Click handlers
        for widget in (self, self._title_lbl, self._info_lbl):
            widget.bind("<Button-1>", lambda _e: on_select())
            widget.bind("<Double-Button-1>", lambda _e: self._start_rename())

        # Right-click menu
        self._context_menu = self._build_context_menu()
        for widget in (self, self._title_lbl, self._info_lbl):
            widget.bind("<Button-3>", self._show_context_menu)

        # Hover
        self.bind("<Enter>", self._on_hover)
        self.bind("<Leave>", self._on_leave)

    def _build_context_menu(self) -> tk.Menu:
        menu = tk.Menu(self, tearoff=0, bg="#2b2b2b", fg="white",
                       activebackground="#404040", activeforeground="white")
        menu.add_command(label="Rename", command=self._start_rename)
        menu.add_command(label="Archive", command=self._on_archive)
        if self._item.status == "archived" and self._on_delete:
            menu.add_command(label="Delete", command=self._on_delete)
        return menu

    def _show_context_menu(self, event) -> None:
        try:
            self._context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._context_menu.grab_release()

    def _start_rename(self, _event=None) -> None:
        if self._on_start_rename:
            self._on_start_rename(self._item.session_id, self._item.title, self)

    def set_active(self, active: bool) -> None:
        """FIX: dynamic color based on current appearance mode."""
        mode = ctk.get_appearance_mode()
        idx = 0 if mode == "Light" else 1
        color = COLOR_ACCENT[idx] if active else COLOR_TEXT_MUTED
        self._indicator.configure(text_color=color)
        if active:
            self.configure(fg_color=("gray85", "gray25"))
        else:
            self.configure(fg_color="transparent")

    def _on_hover(self, _event=None) -> None:
        mode = ctk.get_appearance_mode()
        idx = 0 if mode == "Light" else 1
        if self._indicator.cget("text_color") != COLOR_ACCENT[idx]:
            self.configure(fg_color=("gray88", "gray22"))

    def _on_leave(self, _event=None) -> None:
        mode = ctk.get_appearance_mode()
        idx = 0 if mode == "Light" else 1
        if self._indicator.cget("text_color") != COLOR_ACCENT[idx]:
            self.configure(fg_color="transparent")
