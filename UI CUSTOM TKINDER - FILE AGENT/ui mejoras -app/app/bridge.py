"""
bridge.py — AsyncBridge con callback on_tool_call para UI en tiempo real.

Responsabilidades:
  - Ejecutar coroutines del agente en thread dedicado con asyncio event loop
  - Pasar session_id obligatorio a harness.run()
  - Callbacks no-bloqueantes para la UI de CustomTkinter
  - on_tool_call: notifica en tiempo real cada tool call ejecutado
  - Reset de sesión y shutdown limpio
"""
from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from agent.loop.harness import AgentHarness
from agent.traces.recorder import TraceRecorder

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
        self._recorder: TraceRecorder | None = None
        self._ready = threading.Event()
        self._session_id: str | None = None
        self._executor = ThreadPoolExecutor(max_workers=1)

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self, harness: AgentHarness, recorder: TraceRecorder) -> None:
        """Arranca el bridge con un harness ya inicializado."""
        self._harness = harness
        self._recorder = recorder

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
        self._executor.shutdown(wait=False)
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5.0)

    # ── Session Management ─────────────────────────────────────────────────────

    def set_session(self, session_id: str) -> None:
        self._session_id = session_id

    def clear_session(self) -> None:
        self._session_id = None

    # ── Agent Execution ────────────────────────────────────────────────────────

    def run_agent(
        self,
        message: str,
        on_done: Callable[[str, object], None],
        on_tool_call: Callable[[str, dict, int, bool], None] | None = None,
    ) -> None:
        """
        Ejecuta el agente con el mensaje del usuario.

        Args:
            message: Mensaje del usuario.
            on_done: Callback con (response, trace). Trace es TurnTrace o None.
            on_tool_call: Callback en tiempo real con (name, input_dict, duration_ms, is_error).
        """
        if self._loop is None or self._harness is None:
            on_done("[Error: Agent not initialized]", None)
            return

        if not self._session_id:
            on_done("[Error: No active session]", None)
            return

        async def _task() -> tuple[str, object]:
            try:
                trace = await self._harness.run_with_trace(
                    user_message=message,
                    session_id=self._session_id,
                )
                
                # Notificar tool calls en tiempo real (simulado — el harness 
                # actual no expone callback intermedio, así que leemos del trace)
                if on_tool_call and trace.tool_calls:
                    for tc in trace.tool_calls:
                        on_tool_call(tc.name, tc.input, tc.duration_ms, tc.is_error)
                
                return trace.final_response, trace
            except Exception as e:
                logger.exception("Agent run failed")
                return f"[Unexpected error: {e}]", None

        def _on_done(fut):
            """Callback robusto con try/except — nunca deja la UI colgada."""
            try:
                response, trace = fut.result()
            except Exception as e:
                logger.exception("Agent run callback failed")
                on_done(f"[Error: {e}]", None)
            else:
                on_done(response, trace)

        future = asyncio.run_coroutine_threadsafe(_task(), self._loop)
        future.add_done_callback(_on_done)

    # ── Context Reset ──────────────────────────────────────────────────────────

    def reset_context(self) -> None:
        """Limpia el contexto de conversación del harness."""
        if self._loop and self._harness:
            self._loop.call_soon_threadsafe(self._harness.reset)

    # ── Properties ───────────────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        return self._ready.is_set() and self._loop is not None

    @property
    def session_id(self) -> str | None:
        return self._session_id
