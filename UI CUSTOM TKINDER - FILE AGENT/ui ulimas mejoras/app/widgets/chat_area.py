# app/widgets/chat_area.py
"""
widgets/chat_area.py — Área de chat con CTkTextbox y tool panel temporal (toast).

Responsabilidades:
  - Renderizar mensajes con tags de color (user, agent, system, error)
  - Panel de tool calls como notificación temporal de 3 segundos (toast)
  - Scroll automático al final
  - Recreación de tags al cambiar tema (light/dark)
  - Mostrar tokens I/O en mensajes del agente
  - NO renderizar tool calls como mensajes de chat (solo toast)

CAMBIO (v2.1):
  - Límite de ~2000 líneas para prevenir degradación con historial largo.
  - tag_configure en vez de tag_delete/tag_recreate (theme switch instantáneo).
  - Tool toast con pool de 10 labels pre-creados (zero destroy/create en hot path).
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

# Límite de líneas en el textbox. ~2000 líneas = ~500-700 mensajes.
_MAX_CHAT_LINES = 2000
# Cuántas líneas eliminar de golpe cuando se excede el límite.
_TRUNCATE_CHUNK = 200


class ChatArea(ctk.CTkFrame):
    """
    Contenedor del chat: tool panel toast (arriba) + textbox (abajo).
    """

    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, fg_color=COLOR_BG_PRIMARY, **kwargs)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)  # textbox expande

        # ── Tool Panel (toast temporal) ────────────────────────────────────
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
        self._tool_panel_timer: str | None = None
        self._hide_tool_panel()

    # ── Tags (crear una sola vez, reconfigurar en theme switch) ───────────────

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
        """
        Reconfigura colores de tags existentes al cambiar de tema.
        CAMBIO: usa tag_configure en vez de tag_delete + recreate.
        tag_delete escanea todo el texto (O(n)) — lento con historial largo.
        """
        mode = ctk.get_appearance_mode()
        colors = get_tag_colors(mode)

        for tag in (TAG_USER, TAG_AGENT, TAG_TOOL, TAG_ERROR, TAG_SYSTEM, TAG_TIMESTAMP, TAG_SENDER):
            self._tb.tag_configure(tag, foreground=colors[tag])

    # ── Mensajes (con truncamiento automático) ────────────────────────────────

    def add_message(self, msg: ChatMessage) -> None:
        """Añade un mensaje al chat con formato y tags."""
        # FIX: NO renderizar tool calls como mensajes de chat
        if msg.sender == "tool":
            return

        self._textbox.configure(state="normal")

        tag = self._sender_to_tag(msg.sender)

        # Timestamp + Sender
        self._tb.insert("end", f"\n[{msg.timestamp}] ", TAG_TIMESTAMP)
        self._tb.insert("end", f"{msg.sender.upper()}\n", TAG_SENDER)

        # Contenido
        self._tb.insert("end", f"{msg.content}\n")

        # Tokens I/O para mensajes del agente
        if msg.sender == "agent" and (msg.tokens_in > 0 or msg.tokens_out > 0):
            self._tb.insert(
                "end",
                f"  [tokens ↑{msg.tokens_in:,} ↓{msg.tokens_out:,}]\n",
                TAG_TIMESTAMP,
            )

        # Truncar si excede límite de líneas
        self._maybe_truncate()

        self._textbox.configure(state="disabled")
        self._textbox.see("end")

    def _maybe_truncate(self) -> None:
        """
        Elimina líneas antiguas si el historial excede _MAX_CHAT_LINES.
        Usa delete por bloque (más rápido que línea por línea).
        """
        end_idx = self._tb.index("end-1c")
        line_count = int(end_idx.split(".")[0])
        if line_count > _MAX_CHAT_LINES:
            # Eliminar un bloque grande de una vez (más eficiente)
            self._tb.delete("1.0", f"{_TRUNCATE_CHUNK}.0")

    def add_system_message(self, text: str) -> None:
        """Añade un mensaje de sistema (gris, itálica)."""
        self._textbox.configure(state="normal")
        self._tb.insert("end", f"\n{text}\n", TAG_SYSTEM)
        self._maybe_truncate()
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

    # ── Tool Panel (Toast) ───────────────────────────────────────────────────

    def show_tool_toast(self, tool_calls: list[ToolCallItem]) -> None:
        """Muestra el panel de tools como toast y programa auto-hide en 3 seg."""
        # Cancelar timer previo si existe
        if self._tool_panel_timer is not None:
            self.after_cancel(self._tool_panel_timer)
            self._tool_panel_timer = None

        self._tool_panel.update_tools(tool_calls)
        self._tool_panel.grid()
        self._tool_panel_visible = True

        # Auto-hide después de 3 segundos
        self._tool_panel_timer = self.after(3000, self._hide_tool_panel)

    def _hide_tool_panel(self) -> None:
        """Oculta el panel de tools y limpia el timer."""
        if self._tool_panel_timer is not None:
            self.after_cancel(self._tool_panel_timer)
            self._tool_panel_timer = None
        self._tool_panel.grid_remove()
        self._tool_panel_visible = False


# ─── Tool Panel Interno (con pool de labels) ────────────────────────────────

class _ToolPanel(ctk.CTkFrame):
    """
    Panel temporal que muestra los tool calls de un turno (toast notification).
    Usa un pool de 10 labels pre-creados para evitar destroy/create en hot path.
    """

    _POOL_SIZE = 10

    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, fg_color=("gray92", "gray15"), corner_radius=8, **kwargs)

        # Pre-crear pool de labels invisibles
        self._pool: list[ctk.CTkLabel] = []
        self._active_count = 0

        for _ in range(self._POOL_SIZE):
            lbl = ctk.CTkLabel(
                self,
                anchor="w",
                font=FONT_SMALL,
            )
            self._pool.append(lbl)

    def update_tools(self, tool_calls: list[ToolCallItem]) -> None:
        """
        Actualiza el contenido del panel con nuevos tool calls.
        Reutiliza labels del pool. Cero destroy/create.
        """
        count = min(len(tool_calls), self._POOL_SIZE)

        # Ocultar sobrantes del burst anterior
        for i in range(count, self._active_count):
            self._pool[i].pack_forget()

        # Actualizar/reutilizar labels necesarios
        for i in range(count):
            tc = tool_calls[i]
            icon = "✗" if tc.is_error else "✓"
            color = "#EF4444" if tc.is_error else "#10B981"
            duration = f"{tc.duration_ms}ms" if tc.duration_ms > 0 else "—"

            lbl = self._pool[i]
            lbl.configure(
                text=f"  ⚡ {tc.name:<18} {tc.summary:<45} {duration:<8} {icon}",
                text_color=color,
            )

            if i >= self._active_count:
                lbl.pack(fill="x", padx=8, pady=2)

        self._active_count = count
