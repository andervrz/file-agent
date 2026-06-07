# agent/main.py
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from .core.config import load_config, AgentConfig, Settings
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
from .memory.store import TinyDBMemoryStore
from .cli.repl import run_repl

# Fase 2.5 tools
from .tools.backup_tool import BackupTool
from .tools.git_tool import GitTool
from .tools.pdf_tool import ReadPDFTool
from .tools.office_tools import CreateWordTool, CreateExcelTool, CreatePresentationTool
from .tools.archive_tool import ArchiveTool
from .tools.template_tool import CreateFromTemplateTool
from .tools.diff_tool import DiffFilesTool
from .tools.find_in_files_tool import FindInFilesTool


async def bootstrap() -> tuple[AgentHarness, TinyDBMemoryStore, TraceRecorder, AgentConfig, int]:
    config, settings = load_config()

    if not settings.ollama_api_key:
        print("[ERROR] OLLAMA_API_KEY no configurada en .env")
        sys.exit(1)

    safeguard = PathSafeguard(config.security.blocked_paths)

    registry = ToolRegistry()
    for tool in build_file_tools(safeguard, config.tools.enabled):
        registry.register(tool)
    if "run_command" in config.tools.enabled:
        registry.register(build_command_tool(config.security, safeguard))

    phase_25_tools = [
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
    ]
    for tool in phase_25_tools:
        if tool.name in config.tools.enabled:
            registry.register(tool)

    llm = OllamaClient(config.llm, settings.ollama_api_key)

    skill_loader = SkillLoader(config.skills.path)
    skills_metadata = skill_loader.load_metadata()
    skill_matcher = SkillMatcher(skills_metadata)

    home = str(Path.home())
    system_prompt = config.system_prompt.replace("{HOME}", home)
    context = ConversationContext(
        max_history=config.context.max_history_messages,
        system_prompt=system_prompt,
    )

    recorder = TraceRecorder(config.traces.path, config.traces.enabled)
    memory = TinyDBMemoryStore(config.memory.path, config.memory.enabled)

    harness = AgentHarness(
        config=config,
        llm=llm,
        tool_registry=registry,
        skill_loader=skill_loader,
        skill_matcher=skill_matcher,
        context=context,
        trace_recorder=recorder,
    )

    return harness, memory, recorder, config, len(skills_metadata)


async def async_main() -> None:
    harness, memory, recorder, config, skills_count = await bootstrap()
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
