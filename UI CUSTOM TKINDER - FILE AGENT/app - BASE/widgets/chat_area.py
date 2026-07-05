"""
widgets/chat_area.py — Área de chat con CTkTextbox y tool panel collapsible.

Responsabilidades:
  - Renderizar mensajes con tags de color (user, agent, tool, system, error)
  - Panel de tool calls collapsible sobre el chat
  - Scroll automático al final
  - Recreación de tags al cambiar tema (light/dark)
"""
from __future__ import annotations

import customtkinter as ctk

from ..theme import (
    FONT_BODY,
    FONT_BODY_BOLD,
    FONT_SMALL,
    COLOR_BG_PRIMARY,
    COLOR_TEXT_PRIMARY,
    TAG_USER,
    TAG_AGENT,
    TAG_TOOL,
    TAG_ERROR,
    TAG_SYSTEM,
    TAG_TIMESTAMP,
    TAG_SENDER,
    get_tag_colors,
    ChatMessage,
    ToolCallItem,
    TOOL_PANEL_H,
)


class ChatArea(ctk.CTkFrame):
    """
    Contenedor del chat: tool panel (arriba) + textbox (abajo).
    """

    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, fg_color=COLOR_BG_PRIMARY, **kwargs)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)  # textbox expande

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

        # Tags de tkinter.Text subyacente
        self._tb = self._textbox._textbox
        self._create_tags()

        # Estado
        self._tool_panel_visible = False
        self._hide_tool_panel()

    # ── Tags ─────────────────────────────────────────────────────────────────

    def _create_tags(self) -> None:
        """Crea los tags de color para el CTkTextbox."""
        mode = ctk.get_appearance_mode()
        colors = get_tag_colors(mode)

        self._tb.tag_configure(TAG_USER, foreground=colors[TAG_USER], font=FONT_BODY_BOLD)
        self._tb.tag_configure(TAG_AGENT, foreground=colors[TAG_AGENT], font=FONT_BODY_BOLD)
        self._tb.tag_configure(TAG_TOOL, foreground=colors[TAG_TOOL], font=FONT_SMALL)
        self._tb.tag_configure(TAG_ERROR, foreground=colors[TAG_ERROR], font=FONT_SMALL)
        self._tb.tag_configure(TAG_SYSTEM, foreground=colors[TAG_SYSTEM], font=FONT_SMALL)
        self._tb.tag_configure(TAG_TIMESTAMP, foreground=colors[TAG_TIMESTAMP], font=FONT_SMALL)
        self._tb.tag_configure(TAG_SENDER, foreground=colors[TAG_SENDER], font=FONT_BODY_BOLD)

    def recreate_tags(self) -> None:
        """Recrea los tags al cambiar de tema (light/dark)."""
        for tag in (TAG_USER, TAG_AGENT, TAG_TOOL, TAG_ERROR, TAG_SYSTEM, TAG_TIMESTAMP, TAG_SENDER):
            self._tb.tag_delete(tag)
        self._create_tags()

    # ── Mensajes ─────────────────────────────────────────────────────────────

    def add_message(self, msg: ChatMessage) -> None:
        """Añade un mensaje al chat con formato y tags."""
        self._textbox.configure(state="normal")

        tag = self._sender_to_tag(msg.sender)

        # Timestamp + Sender
        self._tb.insert("end", f"\n[{msg.timestamp}] ", TAG_TIMESTAMP)
        self._tb.insert("end", f"{msg.sender.upper()}\n", TAG_SENDER)

        # Tool calls si aplica
        if msg.tool_calls:
            self._show_tool_panel(msg.tool_calls)

        # Contenido
        self._tb.insert("end", f"{msg.content}\n")

        self._textbox.configure(state="disabled")
        self._textbox.see("end")

    def add_system_message(self, text: str) -> None:
        """Añade un mensaje de sistema (gris, itálica)."""
        self._textbox.configure(state="normal")
        self._tb.insert("end", f"\n{text}\n", TAG_SYSTEM)
        self._textbox.configure(state="disabled")
        self._textbox.see("end")

    def clear(self) -> None:
        """Limpia todo el chat."""
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

    def _show_tool_panel(self, tool_calls: list[ToolCallItem]) -> None:
        """Muestra el panel de tools con los resultados."""
        self._tool_panel.update_tools(tool_calls)
        self._tool_panel.grid()
        self._tool_panel_visible = True

    def _hide_tool_panel(self) -> None:
        """Oculta el panel de tools."""
        self._tool_panel.grid_remove()
        self._tool_panel_visible = False


# ─── Tool Panel Interno ─────────────────────────────────────────────────────

class _ToolPanel(ctk.CTkFrame):
    """
    Panel collapsible que muestra los tool calls de un turno.
    """

    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, fg_color=("gray92", "gray15"), corner_radius=8, **kwargs)

        self._labels: list[ctk.CTkLabel] = []

    def update_tools(self, tool_calls: list[ToolCallItem]) -> None:
        """Actualiza el contenido del panel con nuevos tool calls."""
        # Limpiar anteriores
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
