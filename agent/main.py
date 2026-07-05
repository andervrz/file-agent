# agent/main.py
"""
Bootstrap del agente — inicializa todos los componentes.

Inyecta MemoryService en AgentHarness para inyección de contexto
pre-turno y extracción post-turno.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from .core.config import load_config, AgentConfig
from .core.guardrails import GuardRails
from .loop.context import ConversationContext
from .loop.harness import AgentHarness
from .llm.client import OllamaClient
from .skills.loader import SkillLoader
from .skills.matcher import SkillMatcher
from .tools.base import PathSafeguard
from .tools.file_tools import build_file_tools
from .tools.command_tool import build_command_tool
from .tools.registry import ToolRegistry
from .traces.recorder import TraceRecorder
from .memory.store import SQLiteMemoryStore
from .memory.memory_service import MemoryService

# Fase 2.5
from .tools.backup_tool import BackupTool
from .tools.git_tool import GitTool
from .tools.pdf_tool import ReadPDFTool
from .tools.office_tools import CreateWordTool, CreateExcelTool, CreatePresentationTool
from .tools.archive_tool import ArchiveTool
from .tools.template_tool import CreateFromTemplateTool
from .tools.diff_tool import DiffFilesTool
from .tools.find_in_files_tool import FindInFilesTool

# Fase 3
from .tools.open_file_tool import OpenFileTool
from .tools.browser_tool import BrowserTool
from .tools.web_search_tool import WebSearchTool
from .tools.mcp_client import MCPClientAdapter

logger = logging.getLogger(__name__)


async def _load_mcp_tools(config, settings, registry: ToolRegistry) -> int:
    """
    Carga los tools de cada servidor MCP configurado en agent.yaml.

    Soporta stdio (Context7) y streamable-http (Tavily).
    La API key se resuelve desde .env vía Settings.
    """
    if not config.mcp_servers:
        return 0
    total = 0
    for mcp_cfg in config.mcp_servers:
        if not mcp_cfg.enabled:
            continue

        # Convertir config Pydantic a dict para from_config()
        cfg_dict = mcp_cfg.model_dump()

        # Resolver API key desde .env si aplica
        if mcp_cfg.api_key_env:
            cfg_dict["api_key"] = settings.get_mcp_api_key(mcp_cfg.api_key_env)

        adapter = MCPClientAdapter.from_config(cfg_dict)
        tools = await adapter.load_tools()
        for tool in tools:
            registry.register(tool)
            total += 1
    return total


async def bootstrap() -> tuple[AgentHarness, SQLiteMemoryStore, TraceRecorder, AgentConfig, int, MemoryService | None]:
    config, settings = load_config()

    if not settings.ollama_api_key:
        print("[ERROR] OLLAMA_API_KEY no configurada en .env")
        sys.exit(1)

    home = str(Path.home())
    guardrails = GuardRails(home=home)
    safeguard  = PathSafeguard(config.security.blocked_paths)
    registry   = ToolRegistry()

    # Fase 1
    for tool in build_file_tools(safeguard, config.tools.enabled):
        registry.register(tool)
    if "run_command" in config.tools.enabled:
        registry.register(build_command_tool(config.security, safeguard))

    # Fase 2.5 + 3
    phase_tools = [
        BackupTool(safeguard),
        GitTool(safeguard),
        ReadPDFTool(safeguard),
        CreateWordTool(safeguard),
        CreateExcelTool(safeguard),
        CreatePresentationTool(safeguard),
        ArchiveTool(safeguard),
        CreateFromTemplateTool(safeguard, config.skills.path),
        DiffFilesTool(safeguard),
        FindInFilesTool(safeguard),
        OpenFileTool(safeguard),
        BrowserTool(safeguard),
    ]
    for tool in phase_tools:
        if tool.name in config.tools.enabled:
            registry.register(tool)

    # WebSearchTool
    if "web_search" in config.tools.enabled and settings.tavily_api_key:
        registry.register(WebSearchTool(api_key=settings.tavily_api_key))

    # MCP servers
    await _load_mcp_tools(config, settings, registry)

    llm           = OllamaClient(config.llm, settings.ollama_api_key)
    skill_loader  = SkillLoader(config.skills.path)
    skills_meta   = skill_loader.load_metadata()
    skill_matcher = SkillMatcher(skills_meta)

    system_prompt = config.system_prompt.replace("{HOME}", home)
    context = ConversationContext(
        max_history=config.context.max_history_messages,
        system_prompt=system_prompt,
    )

    recorder = TraceRecorder(config.traces.path, config.traces.enabled)

    # Memoria SQLite
    memory = SQLiteMemoryStore(config.memory.path, config.memory.enabled)
    memory_service: MemoryService | None = None
    if config.memory.enabled:
        recorder.set_memory_store(memory)
        memory_service = MemoryService(memory)
        logger.info("MemoryService initialized")

    harness = AgentHarness(
        config=config,
        llm=llm,
        tool_registry=registry,
        skill_loader=skill_loader,
        skill_matcher=skill_matcher,
        context=context,
        trace_recorder=recorder,
        guardrails=guardrails,
        memory_service=memory_service,
    )

    return harness, memory, recorder, config, len(skills_meta), memory_service


async def async_main() -> None:
    from agent.cli.repl import run_repl
    harness, memory, recorder, config, skills_count, memory_service = await bootstrap()
    await run_repl(
        harness=harness,
        memory=memory,
        recorder=recorder,
        config=config,
        skills_count=skills_count,
    )


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
