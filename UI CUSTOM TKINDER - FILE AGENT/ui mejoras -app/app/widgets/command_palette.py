"""
widgets/command_palette.py — CTkToplevel for commands like /help, /stats, /memory, /model.

Responsibilities:
  - List of available commands with description
  - Execute commands without typing in chat
  - Keyboard shortcut Ctrl+?
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
    Command palette style VS Code / Slack — search and execute commands.
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
            ("/help", "Show help", "List all available commands"),
            ("/clear", "Clear chat", "Clears the visual chat history"),
            ("/stats", "Statistics", "Tokens, turns, tools for current session"),
            ("/memory", "List memory", "Show saved memory facts"),
            ("/memory search", "Search memory", "Search facts by keyword"),
            ("/memory clear", "Clear memory", "Delete all saved facts"),
            ("/model", "Active model", "Show current LLM configuration"),
            ("/exit", "Exit", "Close application"),
        ]

        self._buttons: list[ctk.CTkButton] = []
        self._last_query = ""
        self._render_list()

        # Debounced search: only re-render when query actually changes
        self._search.bind("<KeyRelease>", self._on_search_key)

    def _on_search_key(self, _event=None) -> None:
        """Debounced search: only re-render if query changed."""
        query = self._search.get().lower()
        if query != self._last_query:
            self._last_query = query
            self._render_list()

    def _render_list(self) -> None:
        """Renders the filtered command list."""
        for btn in self._buttons:
            btn.destroy()
        self._buttons = []

        query = self._search.get().lower()

        for cmd, desc, detail in self._commands:
            if query and query not in cmd and query not in desc.lower() and query not in detail.lower():
                continue

            btn = ctk.CTkButton(
                self._list_frame,
                text=f"{cmd:<18} {desc}",
                anchor="w",
                font=FONT_SMALL,
                fg_color="transparent",
                hover_color=("gray85", "gray25"),
                command=lambda c=cmd: self._execute(c),
            )
            btn.pack(fill="x", pady=1)
            self._buttons.append(btn)

    def _execute_selected(self) -> None:
        """Executes the first visible command or the typed text."""
        text = self._search.get().strip()
        if text.startswith("/"):
            self._execute(text)
        elif self._buttons:
            self._buttons[0].invoke()

    def _execute(self, command: str) -> None:
        """Executes a command and closes the palette."""
        self._on_command(command)
        self._close()

    def _close(self) -> None:
        """Closes the palette."""
        if self._on_close:
            self._on_close()
        self.destroy()
