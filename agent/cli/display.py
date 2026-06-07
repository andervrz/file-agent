# agent/cli/display.py
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..core.config import AgentConfig
from ..traces.models import TurnTrace


# ─── Singleton console ────────────────────────────────────────────────────────

_console = Console()


def get_console() -> Console:
    return _console


# ─── Modelos de sesión ────────────────────────────────────────────────────────

class SessionStats(BaseModel):
    """Estadísticas acumuladas de la sesión activa."""

    session_id: str
    model: str
    total_turns: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_tools: int = 0
    total_errors: int = 0
    start_time: str = ""

    def model_post_init(self, __context) -> None:
        if not self.start_time:
            self.start_time = datetime.now(timezone.utc).isoformat()

    def update_from_trace(self, trace: TurnTrace) -> None:
        self.total_turns += 1
        self.total_tokens_in += sum(c.tokens_in for c in trace.llm_calls)
        self.total_tokens_out += sum(c.tokens_out for c in trace.llm_calls)
        self.total_tools += trace.total_tool_calls
        if trace.had_errors:
            self.total_errors += 1

    def elapsed_minutes(self) -> int:
        try:
            start = datetime.fromisoformat(self.start_time)
            delta = datetime.now(timezone.utc) - start.replace(tzinfo=timezone.utc)
            return int(delta.total_seconds() / 60)
        except Exception:
            return 0


# ─── Helpers internos ─────────────────────────────────────────────────────────

def _format_tool_input(name: str, input_dict: dict) -> str:
    """Convierte el dict de input a una línea corta legible."""
    try:
        if name in ("list_directory", "read_file", "create_directory"):
            return str(input_dict.get("path", ""))[:55]
        if name == "search_files":
            d = input_dict.get("directory", "")
            p = input_dict.get("pattern", "")
            return f"{d} [{p}]"[:55]
        if name in ("move_file", "copy_file"):
            src = Path(input_dict.get("source", "")).name
            dst = Path(input_dict.get("destination", "")).name
            return f"{src} → {dst}"[:55]
        if name == "create_file":
            return str(input_dict.get("path", ""))[:55]
        if name == "delete_file":
            return str(input_dict.get("path", ""))[:55]
        if name == "run_command":
            return str(input_dict.get("command", ""))[:55]
        if input_dict:
            return str(list(input_dict.values())[0])[:55]
    except Exception:
        pass
    return ""


def _short_id(session_id: str) -> str:
    return session_id[:4]


# ─── Funciones públicas ───────────────────────────────────────────────────────

def print_banner(config: AgentConfig, skills_count: int, memory_enabled: bool) -> None:
    memory_status = "[green]✓ habilitada[/green]" if memory_enabled else "[dim]deshabilitada[/dim]"
    content = (
        f"[bold cyan]File Agent[/bold cyan]  [dim]v{config.agent.version}[/dim]\n"
        f"[dim]Modelo:[/dim] [white]{config.llm.model}[/white]  [dim]·[/dim]  [dim]Ollama Cloud[/dim]\n"
        f"[dim]Skills:[/dim] [white]{skills_count}[/white]  [dim]·[/dim]  [dim]Memoria:[/dim] {memory_status}\n\n"
        f"[dim]/help  /traces  /stats  /memory  /exit[/dim]"
    )
    _console.print(Panel(content, border_style="cyan", padding=(0, 2)))
    _console.print()


def print_tool_result(
    name: str,
    input_dict: dict,
    duration_ms: int,
    is_error: bool,
) -> None:
    """Línea de resultado de tool — mostrada después de ejecutar."""
    summary = _format_tool_input(name, input_dict)
    status = "[red]✗[/red]" if is_error else "[green]✓[/green]"
    duration = f"[dim]{duration_ms}ms[/dim]" if duration_ms > 0 else "[dim]—[/dim]"
    _console.print(
        f"  [bold cyan]⚡[/bold cyan] [cyan]{name:<18}[/cyan] "
        f"[dim]{summary:<55}[/dim] {duration:<10} {status}"
    )


def print_response(content: str, trace: TurnTrace | None) -> None:
    """Panel de respuesta con Markdown renderizado + stats bar."""
    border = "yellow" if (trace and trace.had_errors) else "green"

    try:
        rendered = Markdown(content)
    except Exception:
        rendered = content  # type: ignore

    _console.print()
    _console.print(Panel(rendered, border_style=border, title="[bold]Agente[/bold]", padding=(1, 2)))

    if trace:
        tokens_in = sum(c.tokens_in for c in trace.llm_calls)
        tokens_out = sum(c.tokens_out for c in trace.llm_calls)
        skill = f"  [dim]·[/dim]  skill: [dim]{trace.skill_activated}[/dim]" if trace.skill_activated else ""
        _console.print(
            f"  [dim]tokens ↑{tokens_in} ↓{tokens_out}"
            f"  ·  tools {trace.total_tool_calls}"
            f"  ·  {trace.total_duration_ms}ms{skill}[/dim]"
        )
    _console.print()


def print_help() -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column(style="dim")

    commands = [
        ("/exit  /quit", "Salir del agente"),
        ("/clear", "Limpiar historial de contexto y pantalla"),
        ("/help", "Mostrar esta ayuda"),
        ("/traces", "Últimos 3 traces del día"),
        ("/traces N", "Últimos N traces"),
        ("/stats", "Estadísticas de la sesión actual"),
        ("/memory", "Listar hechos guardados en memoria"),
        ("/memory buscar <query>", "Buscar en memoria"),
        ("/memory clear", "Eliminar todos los hechos"),
        ("/model", "Modelo activo y configuración LLM"),
    ]
    for cmd, desc in commands:
        table.add_row(cmd, desc)

    _console.print(Panel(table, title="[bold]Ayuda[/bold]", border_style="blue", padding=(1, 1)))


def print_trace(trace: TurnTrace, verbose: bool = False) -> None:
    """Renderiza un TurnTrace individual."""
    tid = _short_id(trace.turn_id)
    tokens_in = sum(c.tokens_in for c in trace.llm_calls)
    tokens_out = sum(c.tokens_out for c in trace.llm_calls)

    try:
        ts = datetime.fromisoformat(trace.timestamp).strftime("%H:%M:%S")
    except Exception:
        ts = trace.timestamp[:19]

    tool_names = ", ".join(t.name for t in trace.tool_calls) if trace.tool_calls else "—"
    skill_line = f"\n  [dim]Skill:[/dim] {trace.skill_activated}" if trace.skill_activated else ""
    errors = " [red]⚠ errores[/red]" if trace.had_errors else ""

    content = (
        f"[dim]{ts}[/dim]  [white]{trace.user_message[:70]}[/white]{errors}\n"
        f"  [dim]Tools:[/dim] {tool_names[:60]}"
        f"{skill_line}\n"
        f"  [dim]LLM calls:[/dim] {trace.total_llm_calls}"
        f"  [dim]·[/dim]  [dim]tokens ↑{tokens_in} ↓{tokens_out}[/dim]"
        f"  [dim]·[/dim]  [dim]{trace.total_duration_ms}ms[/dim]"
    )

    if verbose and trace.tool_calls:
        content += "\n"
        for t in trace.tool_calls:
            summary = _format_tool_input(t.name, t.input)
            status = "[red]✗[/red]" if t.is_error else "[green]✓[/green]"
            content += f"\n  [cyan]{t.name}[/cyan]  [dim]{summary}[/dim]  {status}"

    _console.print(Panel(content, title=f"[dim]trace [{tid}][/dim]", border_style="dim"))


def print_traces_list(traces: list[TurnTrace]) -> None:
    if not traces:
        print_info("No hay traces para el día de hoy.")
        return
    for trace in traces:
        print_trace(trace, verbose=len(traces) == 1)


def print_stats(stats: SessionStats) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim", no_wrap=True)
    table.add_column(style="white")

    table.add_row("Sesión", _short_id(stats.session_id))
    table.add_row("Modelo", stats.model)
    table.add_row("Duración", f"{stats.elapsed_minutes()} min")
    table.add_row("Turnos", str(stats.total_turns))
    table.add_row("Tokens ↑", str(stats.total_tokens_in))
    table.add_row("Tokens ↓", str(stats.total_tokens_out))
    table.add_row("Tools", str(stats.total_tools))
    table.add_row("Errores", str(stats.total_errors))

    _console.print(
        Panel(table, title=f"[bold]Sesión [{_short_id(stats.session_id)}][/bold]", border_style="blue")
    )


def print_memory_list(results: list) -> None:
    if not results:
        print_info("No hay hechos guardados en memoria.")
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=5)
    table.add_column("Topic", style="cyan", width=14)
    table.add_column("Contenido", width=55)
    table.add_column("Timestamp", style="dim", width=20)

    for r in results:
        ts = r.fact.timestamp[:19] if r.fact.timestamp else ""
        table.add_row(
            str(r.doc_id),
            r.fact.topic,
            r.fact.content[:55],
            ts,
        )
    _console.print(table)


def print_error(message: str) -> None:
    _console.print(f"[red]✗[/red] {message}")


def print_info(message: str) -> None:
    _console.print(f"[dim]{message}[/dim]")


def format_prompt(session_id: str) -> str:
    return f"[bold green][{_short_id(session_id)}][/bold green] [bold]❯[/bold]"