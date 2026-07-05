# app/services/command_service.py
"""
command_service.py — Ejecutor de /commands para la GUI de File Agent.

Responsabilidades:
  - Parsear comandos con shlex (soporta comillas y argumentos)
  - Despachar a handlers internos por match/case
  - Ejecutar tools vía AsyncBridge.run_tool() para /search, /browser
  - Consultar SessionManager, MemoryService, AgentConfig para /stats, /model, /traces, /memory
  - Undo vía git subprocess para /undo
  - Retornar siempre str formateado para mostrar en el chat

Principio: puro, sin tocar widgets. La UI solo recibe strings.
"""
from __future__ import annotations

import asyncio
import logging
import shlex
from typing import Callable

from agent.core.config import AgentConfig
from agent.tools.base import ToolResult

from ..bridge import AsyncBridge
from .session_manager import SessionManager
from .memory_service import MemoryService

logger = logging.getLogger(__name__)


class CommandService:
    """
    Servicio puro de ejecución de /commands.
    No conoce CustomTkinter ni widgets.
    """

    def __init__(
        self,
        bridge: AsyncBridge,
        config: AgentConfig,
        session_manager: SessionManager,
        memory_service: MemoryService,
    ) -> None:
        self._bridge = bridge
        self._config = config
        self._session_manager = session_manager
        self._memory_service = memory_service

    # ── Entry point ────────────────────────────────────────────────────────────

    async def execute(self, cmd_str: str) -> str:
        """Parsea y ejecuta un comando. Retorna string para mostrar en chat."""
        try:
            parts = shlex.split(cmd_str.strip())
        except ValueError:
            parts = cmd_str.strip().split()
        if not parts:
            return ""

        base = parts[0].lower()
        args = parts[1:]

        match base:
            case "/help" | "/?":
                return self._cmd_help()
            case "/tools":
                return await self._cmd_tools()
            case "/clear":
                return "[CLEAR]"  # Señal para que app.py limpie el chat
            case "/exit" | "/quit":
                return "[EXIT]"
            case "/stats":
                return await self._cmd_stats()
            case "/model":
                return self._cmd_model()
            case "/mcp":
                return await self._cmd_mcp()
            case "/undo":
                return await self._cmd_undo()
            case "/traces":
                return await self._cmd_traces(args)
            case "/memory":
                return await self._cmd_memory(args)
            case "/search":
                return await self._cmd_search(args)
            case "/browser":
                return await self._cmd_browser(args)
            case _:
                return f"Unknown command: {base}. Type /help for available commands."

    # ── Tier 1: Simple commands (sin argumentos) ───────────────────────────────

    def _cmd_help(self) -> str:
        return (
            "📖 Available commands:\n\n"
            "Simple commands:\n"
            "  /help              Show this help\n"
            "  /tools             List all available tools\n"
            "  /clear             Clear chat visually\n"
            "  /stats             Session dashboard (turns, tools, tokens)\n"
            "  /model             Model & system configuration\n"
            "  /mcp               MCP tools loaded from config\n"
            "  /undo              Revert uncommitted git changes\n"
            "  /exit              Close application\n\n"
            "Commands with arguments:\n"
            "  /traces [N]        Last N conversation turns (default: 5)\n"
            "  /memory            List recent memory facts\n"
            "  /memory <query>    Search memory facts by text\n"
            "  /memory clear      Delete all memory facts\n"
            "  /search <query>    Search text inside files (default: current dir)\n"
            "  /browser open <url>      Open URL in browser\n"
            "  /browser search <query>  Search DuckDuckGo\n"
            "  /browser read            Read current page content\n"
            "  /browser screenshot      Take screenshot\n"
            "  /browser close           Close browser\n\n"
            "Keyboard shortcuts:\n"
            "  Ctrl+L   Clear chat\n"
            "  Ctrl+?   Command palette\n"
            "  Enter    Send message"
        )

    async def _cmd_tools(self) -> str:
        harness = self._bridge.harness
        if not harness:
            return "⚠️ Agent not initialized."

        registry = harness.tool_registry
        schemas = registry.get_schemas()
        if not schemas:
            return "No tools loaded."

        categories: dict[str, list[str]] = {}
        for schema in schemas:
            fn = schema.get("function", {})
            name = fn.get("name", "unknown")
            desc = fn.get("description", "No description")

            cat = "Other"
            if any(x in name for x in (
                "file", "directory", "read_file", "create_file",
                "delete_file", "delete_directory", "move_file",
                "copy_file", "search_files", "find_in_files",
                "list_directory", "create_directory"
            )):
                cat = "File system"
            elif name == "run_command":
                cat = "Shell"
            elif name == "git":
                cat = "Git"
            elif name in ("web_search", "browser"):
                cat = "Web & Browser"
            elif name in ("create_word", "create_excel", "create_presentation", "read_pdf"):
                cat = "Documents"
            elif name in ("diff_files", "backup", "archive", "open_file", "create_from_template"):
                cat = "Utilities"

            line = f"  • {name:<28} {desc[:55]}{'…' if len(desc) > 55 else ''}"
            categories.setdefault(cat, []).append(line)

        lines = [f"📦 Available tools ({len(schemas)} total):\n"]
        for cat in sorted(categories.keys()):
            lines.append(f"\n{cat}:")
            lines.extend(sorted(categories[cat]))

        return "\n".join(lines)

    async def _cmd_stats(self) -> str:
        if not self._session_manager:
            return "⚠️ Session manager not available."

        session_id = self._bridge.session_id
        if not session_id:
            return "⚠️ No active session."

        session = await self._session_manager.get_session(session_id)
        if not session:
            return "⚠️ Session not found."

        model = self._config.llm.model if self._config else "unknown"
        return (
            f"📊 Session Stats\n\n"
            f"  ID:      {session.short_id}\n"
            f"  Title:   {session.title}\n"
            f"  Model:   {model}\n"
            f"  Turns:   {session.total_turns}\n"
            f"  Tools:   {session.total_tools}\n"
            f"  Errors:  {session.total_errors}\n"
            f"  Tokens:  ↑{session.tokens_in:,} ↓{session.tokens_out:,}"
        )

    def _cmd_model(self) -> str:
        if not self._config:
            return "⚠️ Config not loaded."

        cfg = self._config
        return (
            f"⚙️  Model Configuration\n\n"
            f"  Model:         {cfg.llm.model}\n"
            f"  Temperature:   {cfg.llm.temperature}\n"
            f"  Max tokens:    {cfg.llm.max_tokens}\n"
            f"  Skills path:   {cfg.skills.path}\n"
            f"  Memory:        {'enabled' if getattr(cfg.memory, 'enabled', False) else 'disabled'}\n"
            f"  Working dir:   {getattr(cfg.agent, 'working_directory', 'unknown')}"
        )

    async def _cmd_mcp(self) -> str:
        harness = self._bridge.harness
        if not harness:
            return "⚠️ Agent not initialized."

        registry = harness.tool_registry
        schemas = registry.get_schemas()

        standard_tools = {
            "create_file", "read_file", "list_directory", "move_file", "copy_file",
            "delete_file", "delete_directory", "create_directory", "search_files",
            "find_in_files", "run_command", "git", "web_search", "browser",
            "backup", "archive", "diff_files", "open_file", "read_pdf",
            "create_word", "create_excel", "create_presentation",
            "create_from_template",
        }

        mcp_tools = []
        for schema in schemas:
            name = schema.get("function", {}).get("name", "")
            if name not in standard_tools:
                mcp_tools.append(name)

        if not mcp_tools:
            return "🔗 No MCP tools detected. All tools are built-in."

        lines = [f"🔗 MCP Tools ({len(mcp_tools)}):\n"]
        for name in sorted(mcp_tools):
            lines.append(f"  • {name}")
        return "\n".join(lines)

    async def _cmd_undo(self) -> str:
        """Revierte cambios no commiteados vía git checkout."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "rev-parse", "--git-dir",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                return "⚠️ No git repository found. Undo not available."

            proc2 = await asyncio.create_subprocess_exec(
                "git", "status", "--short",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc2.communicate()
            changes = stdout.decode().strip()
            if not changes:
                return "✓ No uncommitted changes to undo."

            proc3 = await asyncio.create_subprocess_exec(
                "git", "checkout", "--", ".",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr3 = await proc3.communicate()
            if proc3.returncode != 0:
                return f"⚠️ Undo failed: {stderr3.decode().strip()}"

            return f"✓ Undo complete. Reverted:\n{changes}"

        except Exception as e:
            return f"⚠️ Undo error: {e}"

    # ── Tier 2: Commands with arguments ────────────────────────────────────────

    async def _cmd_traces(self, args: list[str]) -> str:
        if not self._session_manager:
            return "⚠️ Session manager not available."

        session_id = self._bridge.session_id
        if not session_id:
            return "⚠️ No active session."

        try:
            n = int(args[0]) if args else 5
        except ValueError:
            n = 5

        turns = await self._session_manager.get_recent_turns(session_id, limit=n)
        if not turns:
            return "No traces found."

        lines = [f"📋 Last {len(turns)} turns:\n"]
        for i, turn in enumerate(turns, 1):
            ts = turn.timestamp[:16] if turn.timestamp else "?"
            user_msg = turn.user_message[:50] if turn.user_message else "?"
            tools = []
            try:
                import json
                tool_calls = json.loads(turn.tool_calls or "[]")
                tools = [t.get("name", "?") for t in tool_calls]
            except Exception:
                pass
            tools_str = f"  |  tools: {', '.join(tools)}" if tools else ""
            lines.append(f"{i}. [{ts}] {user_msg}…{tools_str}")

        return "\n".join(lines)

    async def _cmd_memory(self, args: list[str]) -> str:
        if not self._memory_service:
            return "⚠️ Memory service not available."

        if args and args[0].lower() == "clear":
            remaining = await self._memory_service.clear_all()
            if remaining == 0:
                return "✓ Memory cleared."
            return f"⚠️ Memory not fully cleared ({remaining} facts remain)."

        query = " ".join(args) if args else ""

        if query:
            facts = await self._memory_service.search_facts(query, limit=10)
        else:
            facts = await self._memory_service.get_recent_facts(n=10)

        if not facts:
            return "🧠 No facts found."

        lines = [f"🧠 Memory facts ({len(facts)}):\n"]
        for i, fact in enumerate(facts, 1):
            topic = fact.topic[:20]
            content = fact.content[:70]
            ellipsis = "…" if len(fact.content) > 70 else ""
            lines.append(f"{i}. [{topic}] {content}{ellipsis}")

        return "\n".join(lines)

    async def _cmd_search(self, args: list[str]) -> str:
        if not args:
            return "Usage: /search <query>"

        query = " ".join(args)

        harness = self._bridge.harness
        if not harness:
            return "⚠️ Agent not initialized."

        result = await harness.tool_registry.execute(
            "find_in_files",
            tool_use_id="cmd-search",
            directory=".",
            pattern=query,
            max_results=50,
        )
        return result.content

    async def _cmd_browser(self, args: list[str]) -> str:
        if not args:
            return (
                "Usage: /browser open <url> | /browser search <query> | "
                "/browser read | /browser screenshot | /browser close"
            )

        subcmd = args[0].lower()
        harness = self._bridge.harness
        if not harness:
            return "⚠️ Agent not initialized."

        match subcmd:
            case "open":
                if len(args) < 2:
                    return "Usage: /browser open <url>"
                result = await harness.tool_registry.execute(
                    "browser", tool_use_id="cmd-browser", action="open", url=args[1]
                )
                return result.content

            case "search":
                if len(args) < 2:
                    return "Usage: /browser search <query>"
                result = await harness.tool_registry.execute(
                    "browser", tool_use_id="cmd-browser",
                    action="search", query=" ".join(args[1:])
                )
                return result.content

            case "read":
                result = await harness.tool_registry.execute(
                    "browser", tool_use_id="cmd-browser", action="read"
                )
                return result.content

            case "screenshot":
                result = await harness.tool_registry.execute(
                    "browser", tool_use_id="cmd-browser", action="screenshot"
                )
                return result.content

            case "close":
                result = await harness.tool_registry.execute(
                    "browser", tool_use_id="cmd-browser", action="close"
                )
                return result.content

            case _:
                return f"Unknown browser subcommand: {subcmd}"
