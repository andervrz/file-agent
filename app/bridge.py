# app/bridge.py
"""
bridge.py — AsyncBridge con fix crítico de session_id y callback de tools.

Responsabilidades:
  - Ejecutar coroutines del agente en thread dedicado con asyncio event loop
  - Pasar session_id obligatorio a harness.run()
  - Callbacks no-bloqueantes para la UI de CustomTkinter
  - Retornar tokens I/O separados al callback
  - Reset de sesión y shutdown limpio
  - Notificar tool calls en tiempo real a la UI
  - Ejecutar tools directamente desde la UI

CAMBIO (v2.1):
  - run_tool() notifica el callback de tool calls (toast en /commands).
  - reset_context() usa coroutine nativa en vez de asyncio.to_thread().
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Callable

from agent.loop.harness import AgentHarness
from agent.traces.models import ToolTrace
from agent.tools.base import ToolResult

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
        self._on_tool_call: Callable[[ToolTrace], None] | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self, harness: AgentHarness) -> None:
        """Arranca el bridge con un harness ya inicializado."""
        self._harness = harness

        if self._on_tool_call:
            harness.set_tool_callback(self._on_tool_call)

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

    # ── Callback registration ──────────────────────────────────────────────────

    def register_tool_callback(self, callback: Callable[[ToolTrace], None]) -> None:
        """Registra un callback que recibe cada ToolTrace en tiempo real."""
        self._on_tool_call = callback
        if self._harness:
            self._harness.set_tool_callback(callback)

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def harness(self) -> AgentHarness | None:
        """Expone el harness para acceso a registry, config, etc."""
        return self._harness

    @property
    def is_ready(self) -> bool:
        return self._ready.is_set() and self._loop is not None

    @property
    def session_id(self) -> str | None:
        return self._session_id

    # ── Agent Execution ────────────────────────────────────────────────────────

    def run_agent(
        self,
        message: str,
        on_done: Callable[[str, int, int], None],
    ) -> None:
        """
        Ejecuta el agente con el mensaje del usuario.

        FIX CRÍTICO: pasa session_id a harness.run() para que SQLite
        guarde los turnos correctamente.
        Retorna tokens_in y tokens_out al callback.
        """
        if self._loop is None or self._harness is None:
            on_done("[Error: Agent not initialized]", 0, 0)
            return

        if not self._session_id:
            on_done("[Error: No active session]", 0, 0)
            return

        async def _task() -> tuple[str, int, int]:
            try:
                response = await self._harness.run(
                    user_message=message,
                    session_id=self._session_id,
                )
                return response, 0, 0
            except Exception as e:
                logger.exception("Agent run failed")
                return f"[Unexpected error: {e}]", 0, 0

        def _on_future_done(fut) -> None:
            try:
                response, tokens_in, tokens_out = fut.result()
            except Exception as e:
                response = f"[Error: {e}]"
                tokens_in = 0
                tokens_out = 0
            on_done(response, tokens_in, tokens_out)

        future = asyncio.run_coroutine_threadsafe(_task(), self._loop)
        future.add_done_callback(_on_future_done)

    # ── Ejecutar tool directamente desde la UI ─────────────────────────────────

    def run_tool(
        self,
        tool_name: str,
        on_done: Callable[[ToolResult], None],
        **kwargs,
    ) -> None:
        """
        Ejecuta una tool específica del registry en el bridge loop.
        Usado por /commands que necesitan ejecutar tools (ej. /search, /browser).
        """
        if self._loop is None or self._harness is None:
            on_done(ToolResult(
                tool_use_id="cmd",
                tool_name=tool_name,
                content="[Error: Agent not initialized]",
                is_error=True,
            ))
            return

        async def _task() -> ToolResult:
            try:
                registry = self._harness.tool_registry
                t0 = time.perf_counter()
                result = await registry.execute(
                    tool_name, tool_use_id=f"cmd-{tool_name}", **kwargs
                )
                duration_ms = int((time.perf_counter() - t0) * 1000)

                # NUEVO: notificar callback de tool calls para toast en UI
                if self._on_tool_call:
                    trace = ToolTrace(
                        name=tool_name,
                        input=kwargs,
                        output=result.content[:500],
                        is_error=result.is_error,
                        duration_ms=duration_ms,
                    )
                    self._on_tool_call(trace)

                return result
            except Exception as e:
                logger.exception("Tool execution failed")
                return ToolResult(
                    tool_use_id="cmd",
                    tool_name=tool_name,
                    content=f"[Tool error: {e}]",
                    is_error=True,
                )

        def _on_future_done(fut):
            try:
                result = fut.result()
            except Exception as e:
                result = ToolResult(
                    tool_use_id="cmd",
                    tool_name=tool_name,
                    content=f"[Error: {e}]",
                    is_error=True,
                )
            on_done(result)

        future = asyncio.run_coroutine_threadsafe(_task(), self._loop)
        future.add_done_callback(_on_future_done)

    # ── Context Reset ──────────────────────────────────────────────────────────

    def reset_context(self) -> None:
        """
        Limpia el contexto de conversación del harness.
        FIX: usa coroutine nativa en vez de asyncio.to_thread().
        """
        if self._loop is None or self._harness is None:
            return

        async def _reset() -> None:
            self._harness.reset()

        asyncio.run_coroutine_threadsafe(_reset(), self._loop)
