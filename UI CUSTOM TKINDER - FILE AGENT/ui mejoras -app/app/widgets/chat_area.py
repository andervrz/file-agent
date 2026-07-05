# app/widgets/chat_area.py
"""
widgets/chat_area.py — Chat area with CTkTextbox and collapsible tool panel.

FIXES:
  - Stats per agent message (↑tokens ↓tokens · duration · llm_calls)
  - Right-click context menu with copy/paste/clear
  - Public show_tool_alert for real-time tool call notifications
"""
from __future__ import annotations

import tkinter as tk
import customtkinter as ctk

from ..theme import (
    FONT_BODY,
    FONT_BODY_BOLD,
    FONT_SMALL,
    FONT_STATS,
    COLOR_BG_PRIMARY,
    COLOR_TEXT_PRIMARY,
    TAG_USER,
    TAG_AGENT,
    TAG_TOOL,
    TAG_ERROR,
    TAG_SYSTEM,
    TAG_TIMESTAMP,
    TAG_SENDER,
    TAG_STATS,
    get_tag_colors,
    ChatMessage,
    ToolCallItem,
    TOOL_PANEL_H,
)


class ChatArea(ctk.CTkFrame):
    """
    Chat container: tool panel (top) + textbox (bottom).
    """

    def __init__(self, master, on_clear_callback=None, on_delete_session_callback=None, **kwargs) -> None:
        super().__init__(master, fg_color=COLOR_BG_PRIMARY, **kwargs)

        self._on_clear = on_clear_callback
        self._on_delete = on_delete_session_callback

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── Tool Panel (collapsible) ───────────────────────────────────────
        self._tool_panel = _ToolPanel(self)
        self._tool_panel.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))

        # ── Chat Textbox ───────────────────────────────────────────────────
        self._textbox = ctk.CTkTextbox(
            self,
            wrap="word",
            font=FONT_BODY,
            corner_radius=10,
            border_width=0,
            fg_color=COLOR_BG_PRIMARY,
            text_color=COLOR_TEXT_PRIMARY,
            activate_scrollbars=True,
        )
        self._textbox.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        self._textbox.configure(state="disabled")

        # Tags for underlying tkinter.Text
        self._tb = self._textbox._textbox
        self._create_tags()

        # Right-click menu
        self._context_menu = self._build_context_menu()

        self._tb.bind("<Button-3>", self._show_context_menu)  # Linux/Windows
        # self._tb.bind("<Button-2>", self._show_context_menu)  # macOS

        # State
        self._tool_panel_visible = False
        self._hide_tool_panel()

    # ── Tags ─────────────────────────────────────────────────────────────────

    def _create_tags(self) -> None:
        """Creates color tags for the CTkTextbox."""
        mode = ctk.get_appearance_mode()
        colors = get_tag_colors(mode)

        self._tb.tag_configure(TAG_USER, foreground=colors[TAG_USER], font=FONT_BODY_BOLD)
        self._tb.tag_configure(TAG_AGENT, foreground=colors[TAG_AGENT], font=FONT_BODY_BOLD)
        self._tb.tag_configure(TAG_TOOL, foreground=colors[TAG_TOOL], font=FONT_SMALL)
        self._tb.tag_configure(TAG_ERROR, foreground=colors[TAG_ERROR], font=FONT_SMALL)
        self._tb.tag_configure(TAG_SYSTEM, foreground=colors[TAG_SYSTEM], font=FONT_SMALL)
        self._tb.tag_configure(TAG_TIMESTAMP, foreground=colors[TAG_TIMESTAMP], font=FONT_SMALL)
        self._tb.tag_configure(TAG_SENDER, foreground=colors[TAG_SENDER], font=FONT_BODY_BOLD)
        self._tb.tag_configure(TAG_STATS, foreground=colors[TAG_STATS], font=FONT_STATS)

    def recreate_tags(self) -> None:
        """Recreates tags when theme changes (light/dark)."""
        # Do not delete, just reconfigure
        mode = ctk.get_appearance_mode()
        colors = get_tag_colors(mode)
        for tag in (TAG_USER, TAG_AGENT, TAG_TOOL, TAG_ERROR, TAG_SYSTEM, 
                    TAG_TIMESTAMP, TAG_SENDER, TAG_STATS):
            self._tb.tag_configure(tag, foreground=colors[tag])

    # ── Context Menu ─────────────────────────────────────────────────────────

    def _build_context_menu(self) -> tk.Menu:
        """Builds the right-click context menu."""
        menu = tk.Menu(self, tearoff=0, bg="#2b2b2b", fg="white",
                       activebackground="#404040", activeforeground="white")

        menu.add_command(label="Copy", command=self._copy_selection)
        menu.add_command(label="Paste", command=self._paste)
        menu.add_separator()
        menu.add_command(label="Clear Chat", command=self._clear_from_menu)
        if self._on_delete:
            menu.add_command(label="Delete Session", command=self._delete_from_menu)
        return menu

    def _show_context_menu(self, event) -> None:
        """Shows the context menu at cursor position."""
        try:
            self._context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._context_menu.grab_release()

    def _copy_selection(self) -> None:
        """Copies selection to clipboard."""
        try:
            selected = self._tb.selection_get()
            self.clipboard_clear()
            self.clipboard_append(selected)
        except tk.TclError:
            pass  # No selection

    def _paste(self) -> None:
        """FIX: enables textbox before inserting, then disables again."""
        try:
            text = self.clipboard_get()
            self._textbox.configure(state="normal")
            self._tb.insert("insert", text)
            self._textbox.configure(state="disabled")
        except tk.TclError:
            pass

    def _clear_from_menu(self) -> None:
        if self._on_clear:
            self._on_clear()

    def _delete_from_menu(self) -> None:
        if self._on_delete:
            self._on_delete()

    # ── Messages ─────────────────────────────────────────────────────────────

    def add_message(self, msg: ChatMessage) -> None:
        """Adds a message to the chat with formatting and tags."""
        self._textbox.configure(state="normal")

        tag = self._sender_to_tag(msg.sender)

        # Timestamp + Sender
        self._tb.insert("end", f"\n[{msg.timestamp}] ", TAG_TIMESTAMP)
        self._tb.insert("end", f"{msg.sender.upper()}\n", TAG_SENDER)

        # Tool calls if applicable
        if msg.tool_calls:
            self._show_tool_panel(msg.tool_calls)

        # Content
        self._tb.insert("end", f"{msg.content}\n")

        # Stats for agent messages
        if msg.sender == "agent" and (msg.tokens_in or msg.tokens_out):
            stats_line = (
                f"  ↑{msg.tokens_in} ↓{msg.tokens_out} · "
                f"{msg.llm_calls} LLM call{'s' if msg.llm_calls != 1 else ''} · "
                f"{msg.duration_ms}ms"
            )
            self._tb.insert("end", f"{stats_line}\n", TAG_STATS)

        self._textbox.configure(state="disabled")
        self._textbox.see("end")

    def add_system_message(self, text: str) -> None:
        """Adds a system message (gray, italic)."""
        self._textbox.configure(state="normal")
        self._tb.insert("end", f"\n{text}\n", TAG_SYSTEM)
        self._textbox.configure(state="disabled")
        self._textbox.see("end")

    def clear(self) -> None:
        """Clears the entire chat."""
        self._textbox.configure(state="normal")
        self._textbox.delete("1.0", "end")
        self._textbox.configure(state="disabled")
        self._hide_tool_panel()

    def _sender_to_tag(self, sender: str) -> str:
        return {
            "user": TAG_USER,
            "agent": TAG_AGENT,
            "tool": TAG_TOOL,
            "system": TAG_SYSTEM,
            "error": TAG_ERROR,
        }.get(sender, TAG_SYSTEM)

    # ── Tool Panel ───────────────────────────────────────────────────────────

    def show_tool_alert(self, tool_item: ToolCallItem) -> None:
        """Public: shows a real-time tool call alert in the tool panel."""
        self._show_tool_panel([tool_item])

    def _show_tool_panel(self, tool_calls: list[ToolCallItem]) -> None:
        """Shows the tool panel with results."""
        self._tool_panel.update_tools(tool_calls)
        self._tool_panel.grid()
        self._tool_panel_visible = True

    def _hide_tool_panel(self) -> None:
        """Hides the tool panel."""
        self._tool_panel.grid_remove()
        self._tool_panel_visible = False


# ─── Internal Tool Panel ─────────────────────────────────────────────────────

class _ToolPanel(ctk.CTkFrame):
    """
    Collapsible panel that shows tool calls for a turn.
    """

    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, fg_color=("gray92", "gray15"), corner_radius=8, **kwargs)

        self._labels: list[ctk.CTkLabel] = []

    def update_tools(self, tool_calls: list[ToolCallItem]) -> None:
        """Updates panel content with new tool calls."""
        for lbl in self._labels:
            lbl.destroy()
        self._labels = []

        for tc in tool_calls:
            icon = "✗" if tc.is_error else "✓"
            color = "#EF4444" if tc.is_error else "#10B981"
            duration = f"{tc.duration_ms}ms" if tc.duration_ms > 0 else "—"

            lbl = ctk.CTkLabel(
                self,
                text=f"  ⚡ {tc.name:<18} {tc.summary:<45} {duration:<8} {icon}",
                font=FONT_SMALL,
                text_color=color,
                anchor="w",
            )
            lbl.pack(fill="x", padx=8, pady=2)
            self._labels.append(lbl)
