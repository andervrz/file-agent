# app/main.py
"""
main.py — Entry point: splash ligero + bootstrap en thread + único root CTk.

Responsabilidades:
  1. Mostrar splash mínimo (tkinter puro, rápido, sin conflictos CTk).
  2. Ejecutar bootstrap async en thread dedicado — NUNCA bloquea el UI.
  3. Destruir splash completamente antes de crear el root CTk real.
  4. Inyectar dependencias en FileAgentApp y arrancar mainloop.
  5. Manejar errores fatales con dialog de fallback.

Principios:
  - SRP: cada función hace una sola cosa.
  - KISS: splash es tkinter puro (carga instantánea, sin tema CTk).
  - Zero bloqueo: el thread principal solo hace update() mientras carga.
"""
from __future__ import annotations

import asyncio
import logging
import queue
import sys
import threading
import time
import tkinter as tk

import customtkinter as ctk

from .app import FileAgentApp
from .bridge import AsyncBridge
from .services.command_service import CommandService
from .services.memory_service import MemoryService
from .services.session_manager import SessionManager


# ─── Splash (tkinter puro: rápido, cero dependencias de CTk) ─────────────────

def _show_splash(master: tk.Tk) -> tk.Toplevel:
    """Ventana splash sin decoración, centrada en pantalla."""
    splash = tk.Toplevel(master)
    splash.overrideredirect(True)
    splash.geometry("400x150")
    splash.configure(bg="#1a1a1a")

    # Centrar
    splash.update_idletasks()
    sw, sh = splash.winfo_screenwidth(), splash.winfo_screenheight()
    x, y = (sw // 2) - 200, (sh // 2) - 75
    splash.geometry(f"+{x}+{y}")

    # Contenido
    tk.Label(
        splash,
        text="Initializing File Agent…",
        font=("SF Pro Display", 18, "bold"),
        bg="#1a1a1a",
        fg="#f0f0f0",
    ).place(relx=0.5, rely=0.4, anchor="center")

    tk.Label(
        splash,
        text="Loading model, skills, and memory…",
        font=("SF Pro Display", 12),
        bg="#1a1a1a",
        fg="#888888",
    ).place(relx=0.5, rely=0.65, anchor="center")

    splash.update()
    return splash


def _destroy_splash(splash: tk.Toplevel | None, root: tk.Tk | None) -> None:
    """Destruye splash y su root dummy de forma segura."""
    if splash is not None:
        try:
            splash.destroy()
        except tk.TclError:
            pass
    if root is not None:
        try:
            root.destroy()
        except tk.TclError:
            pass


# ─── Bootstrap en thread background ───────────────────────────────────────────

def _bootstrap_thread(q: queue.Queue) -> None:
    """
    Ejecuta el bootstrap async en un thread con su propio event loop.
    Entrega el resultado vía Queue thread-safe.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        from agent.main import bootstrap

        harness, memory, recorder, config, skills_count = loop.run_until_complete(
            bootstrap()
        )
        q.put(("ok", (harness, memory, recorder, config, skills_count)))
    except Exception as exc:
        logging.exception("Bootstrap failed")
        q.put(("error", exc))
    finally:
        loop.close()


# ─── Error fatal (fallback visual) ──────────────────────────────────────────

def _show_fatal_error(error: Exception) -> None:
    """Dialog mínimo de error cuando la app no puede arrancar."""
    root = ctk.CTk()
    root.withdraw()

    dlg = ctk.CTkToplevel(root)
    dlg.title("Startup Error")
    dlg.geometry("500x220")
    dlg.resizable(False, False)
    dlg.transient(root)

    ctk.CTkLabel(
        dlg,
        text="Failed to start File Agent",
        font=("SF Pro Display", 16, "bold"),
        text_color="#EF4444",
    ).pack(pady=(20, 10))

    ctk.CTkLabel(
        dlg,
        text=str(error),
        font=("SF Pro Display", 12),
        wraplength=450,
    ).pack(pady=10)

    ctk.CTkButton(
        dlg,
        text="Exit",
        command=lambda: sys.exit(1),
        font=("SF Pro Display", 13, "bold"),
    ).pack(pady=20)

    dlg.protocol("WM_DELETE_WINDOW", lambda: sys.exit(1))
    dlg.mainloop()


# ─── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    # 1. Splash root mínimo (tkinter puro, oculto)
    splash_root = tk.Tk()
    splash_root.withdraw()
    splash = _show_splash(splash_root)

    # 2. Arrancar bootstrap en thread background
    result_q: queue.Queue = queue.Queue(maxsize=1)
    boot_thread = threading.Thread(target=_bootstrap_thread, args=(result_q,), name="bootstrap")
    boot_thread.start()

    # 3. Mantener splash vivo mientras carga (~60 FPS, bajo CPU)
    while boot_thread.is_alive():
        try:
            splash_root.update()
        except tk.TclError:
            break
        time.sleep(0.016)  # ~60 Hz, suficiente para que se sienta fluido

    # 4. Esperar a que el thread termine (ya debería, pero por seguridad)
    boot_thread.join(timeout=5.0)

    # 5. Destruir splash ANTES de crear el root CTk real
    _destroy_splash(splash, splash_root)

    # 6. Obtener resultado
    try:
        status, payload = result_q.get(block=False)
    except queue.Empty:
        status, payload = "error", Exception("Bootstrap timed out or crashed silently")

    if status == "error":
        _show_fatal_error(payload)
        sys.exit(1)

    # 7. Desempaquetar dependencias
    harness, memory, recorder, config, skills_count = payload

    # 8. Crear servicios (síncrono, liviano)
    session_manager = SessionManager(memory, harness)
    memory_service = MemoryService(memory)

    bridge = AsyncBridge()
    bridge.start(harness)

    command_service = CommandService(
        bridge=bridge,
        config=config,
        session_manager=session_manager,
        memory_service=memory_service,
    )

    # 9. Sesión inicial (única llamada async bloqueante antes de UI)
    try:
        session = asyncio.run(session_manager.get_or_create_empty_session())
    except Exception as exc:
        _show_fatal_error(exc)
        sys.exit(1)

    bridge.set_session(session.session_id)

    # 10. App CTk — ÚNICO root de la aplicación
    app = FileAgentApp(
        bridge=bridge,
        config=config,
        session_manager=session_manager,
        memory_service=memory_service,
        command_service=command_service,
        current_session=session,
        skills_count=skills_count,
    )
    app.mainloop()


if __name__ == "__main__":
    main()
