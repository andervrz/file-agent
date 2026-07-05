# app/main.py
"""
File Agent UI — CustomTkinter desktop application.

Integra el agente async con una interfaz gráfica moderna.
Usa un thread dedicado para el event loop de asyncio,
permitiendo que CustomTkinter mantenga el control de la UI.

Uso (desarrollo):
    uv pip install -e .
    python -m app.main

Uso (instalado):
    file-agent
"""
from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import customtkinter as ctk

from agent.main import bootstrap

logger = logging.getLogger(__name__)

# ── Constantes de UI ────────────────────────────────────────────────────────

WIDTH = 1200
HEIGHT = 800
SIDEBAR_W = 260
INPUT_H = 60
FONT_FAMILY = "SF Pro Display" if sys.platform == "darwin" else "Segoe UI"

# Colores para tags de mensajes (nombres de tag de tkinter.Text)
TAG_USER = "user"
TAG_AGENT = "agent"
_TAG_TOOL = "tool"
_TAG_ERROR = "error"
_TAG_SYSTEM = "system"

# Colores estáticos para tkinter.Text tags (no soporta tuplas light/dark)
_COLOR_USER = "#3B82F6"      # azul
_COLOR_AGENT = "#10B981"     # verde
_COLOR_TOOL = "#F59E0B"      # naranja
_COLOR_ERROR = "#EF4444"     # rojo
_COLOR_SYSTEM = "#888888"    # gris (estático — no hay modo dark dinámico en Text tags)


# ── Async bridge ─────────────────────────────────────────────────────────────

class AsyncBridge:
    """
    Ejecuta coroutines de agente en un thread dedicado con su propio
    asyncio event loop.  Desde el main thread de Tkinter se usa
    run_coroutine_threadsafe() + callbacks para no bloquear la UI.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._harness = None
        self._memory = None
        self._recorder = None
        self._config = None
        self._skills_count = 0
        self._ready = threading.Event()

    def start(self) -> None:
        def _run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._harness, self._memory, self._recorder, self._config, self._skills_count = self._loop.run_until_complete(bootstrap())
            except Exception:
                logger.exception("Bootstrap failed")
            self._ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=_run_loop, daemon=True, name="asyncio-agent")
        self._thread.start()
        self._ready.wait(timeout=30.0)

    def run_agent(self, message: str, on_done: Callable[[str], None]) -> None:
        if self._loop is None or self._harness is None:
            on_done("[Error: Agente no inicializado]")
            return

        async def _task() -> str:
            try:
                return await self._harness.run(message)
            except Exception as e:
                logger.exception("Agent run failed")
                return f"[Error inesperado: {e}]"

        future = asyncio.run_coroutine_threadsafe(_task(), self._loop)
        future.add_done_callback(lambda fut: on_done(fut.result()))

    def reset(self) -> None:
        if self._loop and self._harness:
            asyncio.run_coroutine_threadsafe(
                asyncio.to_thread(self._harness.reset), self._loop
            )

    def stop(self) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5.0)


# ── Aplicación principal ─────────────────────────────────────────────────────

class FileAgentApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.title("File Agent  —  v1.8.0")
        self.geometry(f"{WIDTH}x{HEIGHT}")
        self.minsize(900, 600)

        # Grid principal
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── Sidebar ──────────────────────────────────────────────────────────
        self._build_sidebar()

        # ── Área de chat ───────────────────────────────────────────────────
        self._build_chat_area()

        # ── Input ────────────────────────────────────────────────────────────
        self._build_input_area()

        # ── Async bridge ───────────────────────────────────────────────────
        self._bridge = AsyncBridge()
        self._show_system("Inicializando agente…")
        self.after(100, self._init_agent)

        # Atajos
        self.bind("<Return>", lambda _e: self._on_send())
        self.bind("<Control-l>", lambda _e: self._clear_chat())
        self.bind("<Control-t>", lambda _e: self._toggle_theme())

        # Estado
        self._pending = False

    # ── Builders ────────────────────────────────────────────────────────────

    def _build_sidebar(self) -> None:
        self.sidebar = ctk.CTkFrame(self, width=SIDEBAR_W, corner_radius=0)
        self.sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.sidebar.grid_propagate(False)

        # Logo / título
        self.sidebar.grid_rowconfigure(0, weight=0)
        self.sidebar.grid_rowconfigure(1, weight=0)
        self.sidebar.grid_rowconfigure(2, weight=1)
        self.sidebar.grid_rowconfigure(3, weight=0)

        title = ctk.CTkLabel(
            self.sidebar,
            text="📁  File Agent",
            font=(FONT_FAMILY, 20, "bold"),
        )
        title.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")

        subtitle = ctk.CTkLabel(
            self.sidebar,
            text="Gestión de archivos, terminal\ny navegador web",
            font=(FONT_FAMILY, 12),
            text_color=("gray40", "gray60"),
        )
        subtitle.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="w")

        # Historial (scrollable)
        self.history_frame = ctk.CTkScrollableFrame(
            self.sidebar, label_text="Historial", corner_radius=8
        )
        self.history_frame.grid(row=2, column=0, padx=15, pady=10, sticky="nsew")
        self.history_frame.grid_columnconfigure(0, weight=1)

        # Botones inferiores
        btn_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        btn_frame.grid(row=3, column=0, padx=15, pady=15, sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=1)

        self.new_chat_btn = ctk.CTkButton(
            btn_frame,
            text="+  Nueva conversación",
            command=self._on_new_chat,
            font=(FONT_FAMILY, 12),
        )
        self.new_chat_btn.grid(row=0, column=0, pady=(0, 8), sticky="ew")

        self.theme_btn = ctk.CTkSegmentedButton(
            btn_frame,
            values=["Light", "System", "Dark"],
            command=self._on_theme_change,
            font=(FONT_FAMILY, 11),
        )
        self.theme_btn.set("System")
        self.theme_btn.grid(row=1, column=0, sticky="ew")

    def _build_chat_area(self) -> None:
        self.chat_frame = ctk.CTkFrame(self, corner_radius=12)
        self.chat_frame.grid(row=0, column=1, padx=15, pady=(15, 0), sticky="nsew")
        self.chat_frame.grid_columnconfigure(0, weight=1)
        self.chat_frame.grid_rowconfigure(0, weight=1)

        self.chat_box = ctk.CTkTextbox(
            self.chat_frame,
            wrap="word",
            font=(FONT_FAMILY, 14),
            corner_radius=10,
            border_width=0,
            fg_color=("gray95", "gray13"),
            text_color=("gray10", "gray90"),
            activate_scrollbars=True,
        )
        self.chat_box.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.chat_box.configure(state="disabled")

        # Tags de color para tkinter.Text subyacente — COLORES ESTÁTICOS
        tb = self.chat_box._textbox
        tb.tag_configure(TAG_USER, foreground=_COLOR_USER, font=(FONT_FAMILY, 14, "bold"))
        tb.tag_configure(TAG_AGENT, foreground=_COLOR_AGENT, font=(FONT_FAMILY, 14, "bold"))
        tb.tag_configure(_TAG_TOOL, foreground=_COLOR_TOOL, font=(FONT_FAMILY, 12, "italic"))
        tb.tag_configure(_TAG_ERROR, foreground=_COLOR_ERROR, font=(FONT_FAMILY, 12))
        tb.tag_configure(_TAG_SYSTEM, foreground=_COLOR_SYSTEM, font=(FONT_FAMILY, 12, "italic"))

    def _build_input_area(self) -> None:
        self.input_frame = ctk.CTkFrame(self, height=INPUT_H, corner_radius=12)
        self.input_frame.grid(row=1, column=1, padx=15, pady=15, sticky="ew")
        self.input_frame.grid_columnconfigure(0, weight=1)
        self.input_frame.grid_rowconfigure(0, weight=1)

        self.entry = ctk.CTkEntry(
            self.input_frame,
            placeholder_text="Escribe tu mensaje…  (Enter para enviar, Ctrl+L limpiar, Ctrl+T tema)",
            font=(FONT_FAMILY, 14),
            corner_radius=10,
            border_width=2,
        )
        self.entry.grid(row=0, column=0, padx=(15, 10), pady=15, sticky="nsew")
        self.entry.bind("<Return>", lambda _e: self._on_send())

        self.send_btn = ctk.CTkButton(
            self.input_frame,
            text="Enviar",
            width=100,
            command=self._on_send,
            font=(FONT_FAMILY, 13, "bold"),
        )
        self.send_btn.grid(row=0, column=1, padx=(0, 15), pady=15)

        self.progress = ctk.CTkProgressBar(self.input_frame, mode="indeterminate", height=4)
        self.progress.grid(row=1, column=0, columnspan=2, padx=15, pady=(0, 10), sticky="ew")
        self.progress.set(0)
        self.progress.grid_remove()

    # ── Acciones ────────────────────────────────────────────────────────────

    def _init_agent(self) -> None:
        """Arranca el bridge async en background."""
        try:
            self._bridge.start()
            self._show_system(
                f"✓ Agente listo  —  {self._bridge._skills_count} skills cargadas\n"
                f"Modelo: {self._bridge._config.llm.model}\n"
                "Escribe un mensaje para comenzar."
            )
        except Exception as e:
            self._show_system(f"✗ Error al iniciar agente: {e}", tag=_TAG_ERROR)

    def _on_send(self) -> None:
        text = self.entry.get().strip()
        if not text or self._pending:
            return

        self._append_message("Tú", text, TAG_USER)
        self.entry.delete(0, "end")
        self._set_pending(True)

        def _callback(response: str) -> None:
            self.after(0, lambda: self._on_response(response))

        self._bridge.run_agent(text, _callback)

    def _on_response(self, response: str) -> None:
        self._set_pending(False)
        if response.startswith("[") and "Error" in response:
            self._append_message("Agente", response, _TAG_ERROR)
        else:
            self._append_message("Agente", response, TAG_AGENT)

    def _on_new_chat(self) -> None:
        self._bridge.reset()
        self.chat_box.configure(state="normal")
        self.chat_box.delete("1.0", "end")
        self.chat_box.configure(state="disabled")
        for w in self.history_frame.winfo_children():
            w.destroy()
        self._show_system("Nueva conversación iniciada.")

    def _clear_chat(self, _event=None) -> None:
        self.chat_box.configure(state="normal")
        self.chat_box.delete("1.0", "end")
        self.chat_box.configure(state="disabled")

    def _toggle_theme(self, _event=None) -> None:
        current = ctk.get_appearance_mode()
        next_mode = {"Light": "Dark", "Dark": "System", "System": "Light"}.get(current, "System")
        ctk.set_appearance_mode(next_mode)
        self.theme_btn.set(next_mode)

    def _on_theme_change(self, value: str) -> None:
        ctk.set_appearance_mode(value)

    # ── Helpers de UI ───────────────────────────────────────────────────────

    def _append_message(self, sender: str, text: str, tag: str) -> None:
        self.chat_box.configure(state="normal")
        ts = time.strftime("%H:%M")
        self.chat_box.insert("end", f"\n[{ts}] {sender}\n", tag)
        self.chat_box.insert("end", f"{text}\n")
        self.chat_box.configure(state="disabled")
        self.chat_box.see("end")

        # Añadir al historial lateral si es mensaje del usuario
        if tag == TAG_USER:
            self._add_history_item(text[:40] + "…" if len(text) > 40 else text)

    def _show_system(self, text: str, tag: str = _TAG_SYSTEM) -> None:
        self.chat_box.configure(state="normal")
        self.chat_box.insert("end", f"\n{text}\n", tag)
        self.chat_box.configure(state="disabled")
        self.chat_box.see("end")

    def _set_pending(self, pending: bool) -> None:
        self._pending = pending
        self.send_btn.configure(state="disabled" if pending else "normal")
        self.entry.configure(state="disabled" if pending else "normal")
        if pending:
            self.progress.grid()
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.grid_remove()

    def _add_history_item(self, preview: str) -> None:
        btn = ctk.CTkButton(
            self.history_frame,
            text=preview,
            anchor="w",
            fg_color="transparent",
            text_color=("black", "white"),
            hover_color=("gray90", "gray20"),
            font=(FONT_FAMILY, 12),
            height=28,
            command=lambda p=preview: self.entry.insert(0, p),
        )
        btn.pack(fill="x", pady=2, padx=5)

    def destroy(self) -> None:
        self._bridge.stop()
        super().destroy()


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    app = FileAgentApp()
    app.mainloop()


if __name__ == "__main__":
    main()
