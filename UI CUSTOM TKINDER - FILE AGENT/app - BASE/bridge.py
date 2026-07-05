"""
bridge.py — AsyncBridge con fix crítico de session_id.

Responsabilidades:
  - Ejecutar coroutines del agente en thread dedicado con asyncio event loop
  - Pasar session_id obligatorio a harness.run()
  - Callbacks no-bloqueantes para la UI de CustomTkinter
  - Reset de sesión y shutdown limpio
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Callable

from agent.loop.harness import AgentHarness

logger = logging.getLogger(__name__)


class AsyncBridge:
    """
    Ejecuta coroutines de agente en un thread dedicado con su propio
    asyncio event loop. Desde el main thread de Tkinter se usa
    run_coroutine_threadsafe() + callbacks para no bloquear la UI.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._harness: AgentHarness | None = None
        self._ready = threading.Event()
        self._session_id: str | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self, harness: AgentHarness) -> None:
        """Arranca el bridge con un harness ya inicializado."""
        self._harness = harness

        def _run_loop() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=_run_loop, daemon=True, name="asyncio-agent")
        self._thread.start()
        self._ready.wait(timeout=30.0)

    def stop(self) -> None:
        """Detiene el event loop y el thread."""
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5.0)

    # ── Session Management ─────────────────────────────────────────────────────

    def set_session(self, session_id: str) -> None:
        """Establece la sesión activa para todas las llamadas posteriores."""
        self._session_id = session_id

    def clear_session(self) -> None:
        """Limpia la sesión activa."""
        self._session_id = None

    # ── Agent Execution ────────────────────────────────────────────────────────

    def run_agent(
        self,
        message: str,
        on_done: Callable[[str], None],
        on_tool_call: Callable[[str, dict, int, bool], None] | None = None,
    ) -> None:
        """
        Ejecuta el agente con el mensaje del usuario.

        FIX CRÍTICO: pasa session_id a harness.run() para que SQLite
        guarde los turnos correctamente.
        """
        if self._loop is None or self._harness is None:
            on_done("[Error: Agente no inicializado]")
            return

        if not self._session_id:
            on_done("[Error: No hay sesión activa]")
            return

        async def _task() -> str:
            try:
                # FIX: session_id obligatorio — sin esto SQLite no guarda turnos
                return await self._harness.run(
                    user_message=message,
                    session_id=self._session_id,
                )
            except Exception as e:
                logger.exception("Agent run failed")
                return f"[Error inesperado: {e}]"

        future = asyncio.run_coroutine_threadsafe(_task(), self._loop)
        future.add_done_callback(lambda fut: on_done(fut.result()))

    # ── Context Reset ──────────────────────────────────────────────────────────

    def reset_context(self) -> None:
        """Limpia el contexto de conversación del harness."""
        if self._loop and self._harness:
            asyncio.run_coroutine_threadsafe(
                asyncio.to_thread(self._harness.reset), self._loop
            )

    # ── Properties ───────────────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        return self._ready.is_set() and self._loop is not None

    @property
    def session_id(self) -> str | None:
        return self._session_id
