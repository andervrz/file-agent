# agent/cli/commands.py
from __future__ import annotations

from pydantic import BaseModel

from ..core.config import AgentConfig
from ..loop.harness import AgentHarness
from ..memory.store import TinyDBMemoryStore, SessionSummary
from ..traces.recorder import TraceRecorder
from . import display
from .display import SessionStats


# ─── Resultado de comando ─────────────────────────────────────────────────────

class CommandResult(BaseModel):
    handled: bool = False
    should_exit: bool = False
    should_clear: bool = False


# ─── Dispatcher ───────────────────────────────────────────────────────────────

async def handle_command(
    text: str,
    harness: AgentHarness,
    memory: TinyDBMemoryStore,
    recorder: TraceRecorder,
    session: SessionStats,
    config: AgentConfig,
) -> CommandResult:
    """
    Detecta comandos /xxx y los despacha al handler correcto.
    Si el input no empieza con '/' → CommandResult(handled=False).
    """
    if not text.startswith("/"):
        return CommandResult(handled=False)

    parts = text.strip().split(maxsplit=2)
    cmd = parts[0].lower()
    args = parts[1:] if len(parts) > 1 else []

    match cmd:
        case "/exit" | "/quit":
            return await _handle_exit(session, memory)

        case "/clear":
            return await _handle_clear(harness)

        case "/help":
            return await _handle_help()

        case "/traces":
            n = int(args[0]) if args and args[0].isdigit() else 3
            return await _handle_traces(recorder, n)

        case "/stats":
            return await _handle_stats(session)

        case "/memory":
            if args and args[0].lower() == "buscar":
                query = args[1] if len(args) > 1 else ""
                return await _handle_memory_search(memory, query)
            if args and args[0].lower() == "clear":
                return await _handle_memory_clear(memory)
            return await _handle_memory(memory)

        case "/model":
            return await _handle_model(config)

        case _:
            display.print_error(f"Comando desconocido: {cmd}  —  escribe /help para ver los disponibles.")
            return CommandResult(handled=True)


# ─── Handlers ─────────────────────────────────────────────────────────────────

async def _handle_exit(session: SessionStats, memory: TinyDBMemoryStore) -> CommandResult:
    if memory._enabled and session.total_turns > 0:
        from datetime import datetime, timezone
        summary = SessionSummary(
            session_id=session.session_id,
            summary=f"Sesión de {session.total_turns} turnos, {session.total_tools} tools",
            tools_used=[],
            total_turns=session.total_turns,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        await memory.save_session(summary)
    display.print_info("Sesión guardada. Adiós.")
    return CommandResult(handled=True, should_exit=True)


async def _handle_clear(harness: AgentHarness) -> CommandResult:
    harness.reset()
    display.print_info("Historial de contexto limpiado.")
    return CommandResult(handled=True, should_clear=True)


async def _handle_help() -> CommandResult:
    display.print_help()
    return CommandResult(handled=True)


async def _handle_traces(recorder: TraceRecorder, n: int) -> CommandResult:
    traces = await recorder.read_recent(n)
    if not traces:
        display.print_info("No hay traces para hoy. Inicia una conversación primero.")
    else:
        display.print_traces_list(traces)
    return CommandResult(handled=True)


async def _handle_stats(session: SessionStats) -> CommandResult:
    display.print_stats(session)
    return CommandResult(handled=True)


async def _handle_memory(memory: TinyDBMemoryStore) -> CommandResult:
    results = await memory.list_all()
    display.print_memory_list(results)
    return CommandResult(handled=True)


async def _handle_memory_search(memory: TinyDBMemoryStore, query: str) -> CommandResult:
    if not query:
        display.print_error("Uso: /memory buscar <texto>")
        return CommandResult(handled=True)
    results = await memory.search(query)
    if not results:
        display.print_info(f"No se encontraron hechos para: '{query}'")
    else:
        display.print_memory_list(results)
    return CommandResult(handled=True)


async def _handle_memory_clear(memory: TinyDBMemoryStore) -> CommandResult:
    console = display.get_console()
    confirm = await __import__("asyncio").to_thread(
        input, "¿Eliminar todos los hechos de memoria? (s/n): "
    )
    if confirm.strip().lower() in ("s", "si", "sí", "y", "yes"):
        await memory.clear_all()
        display.print_info("Memoria limpiada.")
    else:
        display.print_info("Operación cancelada.")
    return CommandResult(handled=True)


async def _handle_model(config: AgentConfig) -> CommandResult:
    console = display.get_console()
    console.print(
        f"\n  [dim]Provider:[/dim]     [white]{config.llm.provider}[/white]\n"
        f"  [dim]Modelo:[/dim]       [white]{config.llm.model}[/white]\n"
        f"  [dim]Host:[/dim]         [white]{config.llm.host}[/white]\n"
        f"  [dim]Temperature:[/dim]  [white]{config.llm.temperature}[/white]\n"
        f"  [dim]num_ctx:[/dim]      [white]{config.llm.num_ctx}[/white]\n"
        f"  [dim]num_predict:[/dim]  [white]{config.llm.num_predict}[/white]\n"
    )
    return CommandResult(handled=True)