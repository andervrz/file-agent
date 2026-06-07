# agent/cli/repl.py
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from rich.prompt import Prompt

from ..core.config import AgentConfig
from ..loop.harness import AgentHarness
from ..memory.store import TinyDBMemoryStore, Fact
from ..traces.recorder import TraceRecorder
from .commands import handle_command
from . import display
from .display import SessionStats, get_console


async def run_repl(
    harness: AgentHarness,
    memory: TinyDBMemoryStore,
    recorder: TraceRecorder,
    config: AgentConfig,
    skills_count: int = 0,
) -> None:
    """
    Loop principal del REPL.

    Flujo por turno:
    1. Prompt con session ID corto
    2. Input del usuario
    3. Si es /comando → handle_command()
    4. Si es texto → harness.run() con spinner
    5. Leer trace recién escrito → mostrar tools + response
    6. Actualizar SessionStats
    7. Extraer y guardar hechos en memoria (si habilitada)
    """
    console = get_console()
    session = SessionStats(
        session_id=str(uuid.uuid4()),
        model=config.llm.model,
    )

    display.print_banner(config, skills_count, memory._enabled)

    while True:
        try:
            prompt_str = display.format_prompt(session.session_id) + " "
            user_input = await asyncio.to_thread(
                Prompt.ask,
                prompt_str,
                console=console,
            )
        except (KeyboardInterrupt, EOFError):
            console.print()
            display.print_info("Interrupción recibida. Saliendo...")
            break

        text = user_input.strip()
        if not text:
            continue

        # Compatibilidad con comandos sin slash
        if text.lower() in ("exit", "quit", "salir"):
            text = "/exit"
        elif text.lower() == "clear":
            text = "/clear"
        elif text.lower() == "help":
            text = "/help"

        # ── Comandos especiales /xxx ──────────────────────────────────────────
        result = await handle_command(
            text=text,
            harness=harness,
            memory=memory,
            recorder=recorder,
            session=session,
            config=config,
        )

        if result.handled:
            if result.should_exit:
                break
            if result.should_clear:
                console.clear()
                display.print_banner(config, skills_count, memory._enabled)
            continue

        # ── Texto libre → agente ──────────────────────────────────────────────
        try:
            with console.status("[dim]Procesando...[/dim]", spinner="dots"):
                response = await harness.run(text)

            # Leer el trace recién escrito para mostrar tools y stats
            traces = await recorder.read_recent(1)
            last_trace = traces[-1] if traces else None

            # Mostrar tools ejecutados
            if last_trace and last_trace.tool_calls:
                console.print()
                for tool in last_trace.tool_calls:
                    display.print_tool_result(
                        name=tool.name,
                        input_dict=tool.input,
                        duration_ms=tool.duration_ms,
                        is_error=tool.is_error,
                    )

            # Mostrar respuesta
            display.print_response(response, last_trace)

            # Actualizar stats de sesión
            if last_trace:
                session.update_from_trace(last_trace)

            # Guardar hechos en memoria
            if memory._enabled and last_trace:
                await _extract_and_save_facts(
                    user_message=text,
                    trace=last_trace,
                    memory=memory,
                    session_id=session.session_id,
                )

        except Exception as e:
            display.print_error(f"Error inesperado: {e}")


# ─── Extracción de hechos ─────────────────────────────────────────────────────

async def _extract_and_save_facts(
    user_message: str,
    trace,
    memory: TinyDBMemoryStore,
    session_id: str,
) -> None:
    """
    Fase 2: extracción simple basada en heurísticas.
    Fase 3: extracción LLM-based (diferido).
    """
    if trace.total_tool_calls == 0:
        return

    # Solo guardar si hubo operaciones exitosas significativas
    successful = [t for t in trace.tool_calls if not t.is_error]
    if not successful:
        return

    tool_names = list({t.name for t in successful})

    # Hecho sobre la operación realizada
    fact = Fact(
        topic="operaciones",
        content=f"{user_message[:80]} → {', '.join(tool_names[:3])}",
        source="conversación",
        timestamp=datetime.now(timezone.utc).isoformat(),
        session_id=session_id,
    )
    await memory.save_fact(fact)