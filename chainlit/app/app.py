# app.py
"""
Interfaz Chainlit para File Agent.

Corre en paralelo con la CLI — ambas usan el mismo AgentHarness.
Arrancar con:
    uv run chainlit run app.py -w
"""
from __future__ import annotations

import os  # <-- NUEVO: Importante para poder leer del .env
import re
from pathlib import Path

import chainlit as cl

from agent.main import bootstrap
from data_layer import SQLiteDataLayer

# ─── Data Layer Custom ───────────────────────────────────────────────────────

@cl.data_layer
def get_data_layer():
    Path("./memory").mkdir(parents=True, exist_ok=True)
    return SQLiteDataLayer("./memory/chainlit.db")


# ── Habilitar autenticación con el .env ───────────────────────────────────────
@cl.password_auth_callback
def auth_callback(username: str, password: str):
    """
    Valida las credenciales ingresadas en el formulario de login
    estrictamente contra las variables configuradas en el archivo .env.
    """
    env_user = os.getenv("CHAINLIT_USER")
    env_pass = os.getenv("CHAINLIT_PASSWORD")
    
    # Validación de seguridad: si las variables no están definidas en el .env,
    # rechazamos la autenticación inmediatamente para evitar accesos no deseados.
    if not env_user or not env_pass:
        print("[ERROR DE CONFIGURACIÓN] CHAINLIT_USER o CHAINLIT_PASSWORD no están definidos en el .env")
        return None
        
    if username == env_user and password == env_pass:
        # El 'identifier' se propaga a tu data_layer.py
        # Esto permite que SQLite sepa exactamente qué chats pertenecen a este usuario
        return cl.User(identifier=username, metadata={"role": "admin"})
    
    return None


# ─── Iconos por tool ─────────────────────────────────────────────────────────

_TOOL_ICONS: dict[str, str] = {
    "create_file":        "📝",
    "read_file":          "📖",
    "list_directory":     "📂",
    "move_file":          "✂️",
    "copy_file":          "📋",
    "delete_file":        "🗑️",
    "delete_directory":   "🗑️",
    "create_directory":   "📁",
    "search_files":       "🔍",
    "run_command":        "⚙️",
    "read_pdf":           "📄",
    "browser":            "🌐",
    "open_file":          "🖥️",
    "web_search":         "🔎",
    "git":                "🔀",
    "backup":             "💾",
    "archive":            "📦",
    "diff_files":         "↔️",
    "find_in_files":      "🔍",
    "create_word":        "📝",
    "create_excel":       "📊",
    "create_presentation":"📑",
    "create_from_template":"🗂️",
}

# Tipos de archivo que se ofrecen como descarga inline
_DOWNLOADABLE_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml",
    ".toml", ".csv", ".html", ".css", ".xml", ".sh", ".log",
    ".docx", ".xlsx", ".pptx", ".pdf",
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _format_tool_input(tool_name: str, input_dict: dict) -> str:
    """Convierte el input dict a una línea corta legible."""
    try:
        if tool_name in ("list_directory", "read_file", "create_directory",
                         "delete_file", "delete_directory", "open_file"):
            return str(input_dict.get("path", ""))
        if tool_name == "search_files":
            d = input_dict.get("directory", "")
            p = input_dict.get("pattern", "")
            return f"{d}  [{p}]"
        if tool_name in ("move_file", "copy_file"):
            src = Path(input_dict.get("source", "")).name
            dst = Path(input_dict.get("destination", "")).name
            return f"{src} → {dst}"
        if tool_name == "create_file":
            path    = input_dict.get("path", "")
            content = input_dict.get("content", "")
            preview = content[:80].replace("\n", " ")
            return f"{path}\n{preview}..."
        if tool_name == "run_command":
            return str(input_dict.get("command", ""))
        if tool_name == "browser":
            action = input_dict.get("action", "")
            target = input_dict.get("url") or input_dict.get("query") or input_dict.get("selector", "")
            return f"{action}: {target}"
        if tool_name == "web_search":
            action = input_dict.get("action", "search")
            query  = input_dict.get("query", "")
            return f"{action}: {query}"
        if tool_name == "git":
            cmd  = input_dict.get("command", "")
            args = input_dict.get("args", "")
            return f"git {cmd} {args}".strip()
        if input_dict:
            return str(list(input_dict.values())[0])[:150]
    except Exception:
        pass
    return str(input_dict)[:150]


def _collect_elements(tool_calls) -> list:
    """
    Extrae archivos creados y screenshots del agente para mostrarlos
    como elementos adjuntos en la respuesta.
    """
    elements: list = []
    seen: set[str] = set()

    for tool in tool_calls:
        if tool.is_error:
            continue

        # Archivos creados → ofrecer descarga
        if tool.name in ("create_file", "copy_file", "create_word",
                         "create_excel", "create_presentation"):
            path_str = (
                tool.input.get("path")
                or tool.input.get("output_path")
                or tool.input.get("destination")
            )
            if path_str and path_str not in seen:
                p = Path(path_str)
                if p.exists() and p.is_file() and p.suffix.lower() in _DOWNLOADABLE_EXTENSIONS:
                    if p.stat().st_size < 10 * 1024 * 1024:  # < 10MB
                        elements.append(
                            cl.File(name=p.name, path=str(p), display="inline")
                        )
                        seen.add(path_str)

        # Screenshots del browser → mostrar inline
        elif tool.name == "browser" and "screenshot" in str(tool.input):
            match = re.search(r'(/[\w/.-]+\.png)', tool.output)
            if match:
                png_path = Path(match.group(1))
                if png_path.exists() and str(png_path) not in seen:
                    elements.append(
                        cl.Image(name=png_path.name, path=str(png_path), display="inline")
                    )
                    seen.add(str(png_path))

    return elements


def _quick_actions() -> list[cl.Action]:
    """Botones de acceso rápido — equivalente a los comandos de la CLI."""
    return [
        cl.Action(name="btn_clear",  label="🗑️ Limpiar",  payload={"cmd": "clear"}),
        cl.Action(name="btn_traces", label="📊 Traces",   payload={"cmd": "traces"}),
        cl.Action(name="btn_memory", label="🧠 Memoria",  payload={"cmd": "memory"}),
        cl.Action(name="btn_stats",  label="📈 Stats",    payload={"cmd": "stats"}),
    ]


# ─── Lifecycle ────────────────────────────────────────────────────────────────

@cl.on_chat_start
async def on_chat_start() -> None:
    """Inicializa el harness y muestra el mensaje de bienvenida."""
    harness, memory, recorder, config, skills_count = await bootstrap()

    cl.user_session.set("harness",  harness)
    cl.user_session.set("memory",   memory)
    cl.user_session.set("recorder", recorder)
    cl.user_session.set("config",   config)
    cl.user_session.set("stats", {
        "turns": 0, "tools": 0, "errors": 0,
        "tokens_in": 0, "tokens_out": 0,
    })

    mem_status = "✓ habilitada" if memory._enabled else "deshabilitada"

    await cl.Message(
        content=(
            f"### File Agent `v{config.agent.version}`\n\n"
            f"| | |\n|---|---|\n"
            f"| Modelo | `{config.llm.model}` |\n"
            f"| Skills | `{skills_count}` |\n"
            f"| Memoria | {mem_status} |\n\n"
            "Puedo gestionar archivos, navegar la web, buscar "
            "información en tiempo real y ejecutar comandos de terminal."
        ),
        author="File Agent",
        actions=_quick_actions(),
    ).send()


# ─── Quick actions callbacks ──────────────────────────────────────────────────

@cl.action_callback("btn_clear")
async def on_clear(_action: cl.Action) -> None:
    harness = cl.user_session.get("harness")
    harness.reset()
    await cl.Message(
        content="✓ Historial de contexto limpiado.",
        author="Sistema",
        actions=_quick_actions(),
    ).send()


@cl.action_callback("btn_traces")
async def on_traces(_action: cl.Action) -> None:
    recorder = cl.user_session.get("recorder")
    traces   = await recorder.read_recent(5)

    if not traces:
        await cl.Message(
            content="No hay traces disponibles hoy.",
            author="Sistema",
            actions=_quick_actions(),
        ).send()
        return

    lines = ["**Últimos traces:**\n"]
    for t in reversed(traces):
        tok_in  = sum(c.tokens_in  for c in t.llm_calls)
        tok_out = sum(c.tokens_out for c in t.llm_calls)
        tools   = ", ".join(f"`{tc.name}`" for tc in t.tool_calls) or "—"
        status  = "⚠️" if t.had_errors else "✓"
        lines.append(
            f"{status} **{t.user_message[:60]}**\n"
            f"  Tools: {tools}\n"
            f"  ↑{tok_in}/↓{tok_out} tokens · {t.total_duration_ms}ms\n"
        )

    await cl.Message(
        content="\n".join(lines),
        author="Sistema",
        actions=_quick_actions(),
    ).send()


@cl.action_callback("btn_memory")
async def on_memory(_action: cl.Action) -> None:
    memory  = cl.user_session.get("memory")
    results = await memory.list_all()

    if not results:
        await cl.Message(
            content="No hay hechos guardados en memoria.",
            author="Sistema",
            actions=_quick_actions(),
        ).send()
        return

    lines = [f"**Memoria** ({len(results)} hechos):\n"]
    for r in results[:15]:
        lines.append(f"- `[{r.fact.topic}]` {r.fact.content[:90]}")

    await cl.Message(
        content="\n".join(lines),
        author="Sistema",
        actions=_quick_actions(),
    ).send()


@cl.action_callback("btn_stats")
async def on_stats(_action: cl.Action) -> None:
    stats = cl.user_session.get("stats", {})
    await cl.Message(
        content=(
            "**Estadísticas de sesión:**\n\n"
            f"| Métrica | Valor |\n|---|---|\n"
            f"| Turnos | `{stats.get('turns', 0)}` |\n"
            f"| Tools ejecutados | `{stats.get('tools', 0)}` |\n"
            f"| Tokens ↑ | `{stats.get('tokens_in', 0)}` |\n"
            f"| Tokens ↓ | `{stats.get('tokens_out', 0)}` |\n"
            f"| Errores | `{stats.get('errors', 0)}` |"
        ),
        author="Sistema",
        actions=_quick_actions(),
    ).send()


# ─── Main handler ─────────────────────────────────────────────────────────────

@cl.on_message
async def on_message(message: cl.Message) -> None:
    """
    Flujo por turno:
    1. Ejecutar harness.run()
    2. Leer el trace recién escrito
    3. Mostrar cada tool call como cl.Step colapsable
    4. Mostrar respuesta final con archivos adjuntos si aplica
    5. Actualizar stats de sesión
    """
    harness  = cl.user_session.get("harness")
    recorder = cl.user_session.get("recorder")
    stats    = cl.user_session.get("stats", {})

    # ── Ejecutar el agente ────────────────────────────────────────────────────
    response = await harness.run(message.content)

    # ── Leer trace ───────────────────────────────────────────────────────────
    traces     = await recorder.read_recent(1)
    last_trace = traces[-1] if traces else None

    # ── Mostrar tool steps ────────────────────────────────────────────────────
    if last_trace and last_trace.tool_calls:
        for tool in last_trace.tool_calls:
            icon        = _TOOL_ICONS.get(tool.name, "⚡")
            status_icon = "✗" if tool.is_error else "✓"
            duration    = f"{tool.duration_ms}ms" if tool.duration_ms else "—"

            async with cl.Step(
                name=f"{icon} {tool.name}  {status_icon}  {duration}",
                type="tool",
            ) as step:
                step.input  = _format_tool_input(tool.name, tool.input)
                step.output = tool.output[:600]
                if tool.is_error:
                    step.is_error = True

    # ── Construir respuesta ───────────────────────────────────────────────────
    elements: list = []
    if last_trace and last_trace.tool_calls:
        elements = _collect_elements(last_trace.tool_calls)

    # Stats inline al pie de la respuesta
    footer = ""
    if last_trace:
        tok_in  = sum(c.tokens_in  for c in last_trace.llm_calls)
        tok_out = sum(c.tokens_out for c in last_trace.llm_calls)
        skill   = f" · skill: `{last_trace.skill_activated}`" if last_trace.skill_activated else ""
        warn    = " ⚠️" if last_trace.had_errors else ""
        footer  = (
            f"\n\n---\n"
            f"*↑{tok_in} ↓{tok_out} tokens · "
            f"{last_trace.total_tool_calls} tools · "
            f"{last_trace.total_duration_ms}ms{skill}{warn}*"
        )

    await cl.Message(
        content=response + footer,
        author="File Agent",
        elements=elements or None,
        actions=_quick_actions(),
    ).send()

    # ── Actualizar stats de sesión ────────────────────────────────────────────
    if last_trace:
        stats["turns"]     = stats.get("turns",      0) + 1
        stats["tools"]     = stats.get("tools",      0) + last_trace.total_tool_calls
        stats["tokens_in"] = stats.get("tokens_in",  0) + sum(c.tokens_in  for c in last_trace.llm_calls)
        stats["tokens_out"]= stats.get("tokens_out", 0) + sum(c.tokens_out for c in last_trace.llm_calls)
        if last_trace.had_errors:
            stats["errors"] = stats.get("errors", 0) + 1
        cl.user_session.set("stats", stats)
