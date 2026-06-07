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


async def bootstrap() -> tuple[AgentHarness, TinyDBMemoryStore, TraceRecorder, AgentConfig, int]:
    """
    Inicializa todos los componentes en orden.
    Retorna (harness, memory, recorder, config, skills_count).
    """
    config, settings = load_config()

    if not settings.ollama_api_key:
        print("[ERROR] OLLAMA_API_KEY no configurada en .env")
        sys.exit(1)

    # Seguridad de paths
    safeguard = PathSafeguard(config.security.blocked_paths)

    # Tool registry
    registry = ToolRegistry()
    for tool in build_file_tools(safeguard, config.tools.enabled):
        registry.register(tool)
    if "run_command" in config.tools.enabled:
        registry.register(build_command_tool(config.security, safeguard))

    # LLM client
    llm = OllamaClient(config.llm, settings.ollama_api_key)

    # Skills
    skill_loader = SkillLoader(config.skills.path)
    skills_metadata = skill_loader.load_metadata()
    skill_matcher = SkillMatcher(skills_metadata)

    # Context
    home = str(Path.home())
    system_prompt = config.system_prompt.replace("{HOME}", home)
    context = ConversationContext(
        max_history=config.context.max_history_messages,
        system_prompt=system_prompt,
    )

    # Traces
    recorder = TraceRecorder(config.traces.path, config.traces.enabled)

    # Memory
    memory = TinyDBMemoryStore(config.memory.path, config.memory.enabled)

    # Harness
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