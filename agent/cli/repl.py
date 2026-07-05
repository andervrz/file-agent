# agent/cli/repl.py
"""
Loop principal del REPL.

Ahora persiste cada turno en SQLite (conversation_turns) y mantiene
metadatos de sesión actualizados en tiempo real.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from rich.prompt import Prompt

from ..core.config import AgentConfig
from ..loop.harness import AgentHarness
from ..memory.store import TinyDBMemoryStore, Fact, SessionSummary
from ..memory.models_sqlmodel import SessionMetadata
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
    Loop principal del REPL con persistencia de sesiones.

    Flujo:
    1. Crear sesión en SQLite
    2. Prompt → input del usuario
    3. Si es /comando → handle_command()
    4. Si es texto → harness.run(session_id=...) con spinner
    5. Guardar turno en SQLite + actualizar stats de sesión
    6. Extraer y guardar hechos en memoria
    """
    console = get_console()
    session_id = str(uuid.uuid4())
    session = SessionStats(
        session_id=session_id,
        model=config.llm.model,
    )

    # ── Crear sesión en memoria persistente ─────────────────────────────────
    if memory._enabled:
        await memory.create_session(
            session_id=session_id,
            title=f"Sesión {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
        )
        # Inyectar memory store en recorder para persistencia dual
        recorder.set_memory_store(memory)

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

        # ── Texto libre → agente (con session_id) ─────────────────────────────
        try:
            with console.status("[dim]Procesando...[/dim]", spinner="dots"):
                # FIX: run_with_trace() retorna el TurnTrace directamente en
                # vez de releerlo desde el JSONL vía recorder.read_recent(1).
                # El patrón anterior dependía de traces.enabled=true como
                # efecto colateral: con traces deshabilitados, read_recent()
                # retornaba [] y el panel de tools, las stats de sesión y la
                # extracción de hechos dejaban de funcionar silenciosamente,
                # pese a no tener relación conceptual con el logging a disco.
                trace = await harness.run_with_trace(text, session_id=session_id)

            response = trace.final_response

            # Mostrar tools ejecutados
            if trace.tool_calls:
                console.print()
                for tool in trace.tool_calls:
                    display.print_tool_result(
                        name=tool.name,
                        input_dict=tool.input,
                        duration_ms=tool.duration_ms,
                        is_error=tool.is_error,
                    )

            # Mostrar respuesta
            display.print_response(response, trace)

            # Actualizar stats de sesión
            session.update_from_trace(trace)
            # Persistir stats actualizadas en SQLite
            if memory._enabled:
                await memory.update_session_stats(
                    session_id=session_id,
                    total_turns=session.total_turns,
                    total_tools=session.total_tools,
                    total_errors=session.total_errors,
                )

            # Guardar hechos en memoria
            if memory._enabled:
                await _extract_and_save_facts(
                    user_message=text,
                    trace=trace,
                    memory=memory,
                    session_id=session_id,
                )

        except Exception as e:
            display.print_error(f"Error inesperado: {e}")

    # ── Al salir: archivar sesión ───────────────────────────────────────────
    # FIX: único punto de persistencia al cerrar — cubre /exit, Ctrl+C y EOF
    # por igual. Antes, commands.py._handle_exit guardaba un SessionSummary
    # (solo en la ruta /exit) y este bloque guardaba OTRO incondicionalmente,
    # causando doble escritura al salir con /exit.
    #
    # archive_session() corre siempre que memory esté habilitada, incluso con
    # 0 turnos, para no dejar sesiones huérfanas en estado "active" (p.ej.
    # Ctrl+C inmediato tras crear la sesión). El SessionSummary solo se
    # guarda si hubo actividad real (total_turns > 0), igual que el
    # comportamiento original de _handle_exit.
    if memory._enabled:
        await memory.archive_session(session_id)
        if session.total_turns > 0:
            summary = SessionSummary(
                session_id=session.session_id,
                summary=f"Sesión de {session.total_turns} turnos, {session.total_tools} tools",
                tools_used=[],
                total_turns=session.total_turns,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            await memory.save_session(summary)


# ─── Extracción de hechos ─────────────────────────────────────────────────────

async def _extract_and_save_facts(
    user_message: str,
    trace,
    memory: TinyDBMemoryStore,
    session_id: str,
) -> None:
    """Extrae hechos de un turno y los guarda en memoria semántica."""
    if trace.total_tool_calls == 0:
        return

    successful = [t for t in trace.tool_calls if not t.is_error]
    if not successful:
        return

    tool_names = list({t.name for t in successful})

    fact = Fact(
        topic="operaciones",
        content=f"{user_message[:80]} → {', '.join(tool_names[:3])}",
        source="conversación",
        timestamp=datetime.now(timezone.utc).isoformat(),
        session_id=session_id,
    )
    await memory.save_fact(fact)
