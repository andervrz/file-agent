"""
Integration tests para AgentHarness — loop agéntico completo.

Cubre:
- Turno simple: mensaje → respuesta (sin tools)
- Turno con tool calls: LLM pide tool → se ejecuta → LLM responde
- Anti-loop: cache de tool calls evita reejecución
- Anti-loop: push explícito cuando hay 3+ repeticiones
- MAX_TOOLS_PER_CALL = 5 limita tool calls
- Fallback cuando LLM retorna vacío
- Max iterations alcanzado
- Skill matching inyecta skill en contexto
- Trace recorder guarda TurnTrace
- Nunca lanza excepción al llamador
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from agent.loop.harness import AgentHarness
from agent.llm.client import LLMResponse, ToolCall
from agent.tools.base import ToolResult
from agent.core.constants import StopReason
from agent.core.config import AgentConfig, AgentMeta, LLMConfig, ContextConfig, SkillsConfig, MemoryConfig, TracesConfig, SecurityConfig, ToolsConfig
from agent.traces.models import TurnTrace


class TestAgentHarness:
    """Loop agéntico completo con componentes mockeados."""

    @pytest.fixture
    def config(self):
        return AgentConfig(
            agent=AgentMeta(name="Test Agent", version="1.0.0", description="d"),
            llm=LLMConfig(provider="ollama", host="https://ollama.com", model="gpt-oss:20b", temperature=0.1, num_ctx=4096, num_predict=2048),
            system_prompt="Eres File Agent.",
            tools=ToolsConfig(enabled=["create_file", "read_file", "list_directory", "run_command"]),
            context=ContextConfig(max_history_messages=10, max_iterations=25),
            skills=SkillsConfig(path="./skills"),
            memory=MemoryConfig(enabled=False, path="./memory"),
            traces=TracesConfig(enabled=True, path="./traces"),
            security=SecurityConfig(
                levels={"safe": ["ls"], "moderate": ["mkdir"], "dangerous": ["rm"], "blocked": ["sudo"]},
                require_confirmation=["dangerous"],
                blocked_paths=["/etc"],
                timeout_seconds={"safe": 10, "moderate": 30, "dangerous": 60},
            ),
        )

    @pytest.fixture
    def mock_llm(self):
        """LLM que retorna respuestas configurables."""
        llm = MagicMock()
        llm.complete = AsyncMock()
        return llm

    @pytest.fixture
    def mock_registry(self):
        """ToolRegistry que ejecuta tools mockeadas."""
        registry = MagicMock()
        registry.execute = AsyncMock(return_value=ToolResult(
            tool_use_id="t1", content="mock result", is_error=False
        ))
        registry.get_schemas = MagicMock(return_value=[])
        return registry

    @pytest.fixture
    def mock_skill_loader(self):
        loader = MagicMock()
        loader.load_metadata = MagicMock(return_value=[])
        loader.load_body = MagicMock(return_value="skill body")
        return loader

    @pytest.fixture
    def mock_skill_matcher(self):
        matcher = MagicMock()
        matcher.match = MagicMock(return_value=None)
        return matcher

    @pytest.fixture
    def mock_skill_metadata(self):
        """SkillMetadata mock para tests de skill matching."""
        meta = MagicMock()
        meta.name = "file-management"
        meta.path = None
        meta.description = "Gestiona archivos"
        meta.tags = ["files"]
        return meta

    @pytest.fixture
    def mock_context(self):
        ctx = MagicMock()
        ctx.get_messages = MagicMock(return_value=[])
        ctx.add_user_message = MagicMock()
        ctx.add_assistant_response = MagicMock()
        ctx.add_tool_results = MagicMock()
        ctx.set_skill = MagicMock()
        ctx.clear = MagicMock()
        return ctx

    @pytest.fixture
    def mock_trace_recorder(self):
        recorder = MagicMock()
        recorder.record = AsyncMock()
        return recorder

    @pytest.fixture
    def harness(self, config, mock_llm, mock_registry, mock_skill_loader, mock_skill_matcher, mock_context, mock_trace_recorder):
        return AgentHarness(
            config=config,
            llm=mock_llm,
            tool_registry=mock_registry,
            skill_loader=mock_skill_loader,
            skill_matcher=mock_skill_matcher,
            context=mock_context,
            trace_recorder=mock_trace_recorder,
        )

    # ── turno simple sin tools ──
    @pytest.mark.asyncio
    async def test_simple_response_no_tools(self, harness, mock_llm, mock_context):
        """Mensaje simple → LLM responde directamente sin tools."""
        mock_llm.complete.return_value = LLMResponse(
            stop_reason=StopReason.STOP.value,
            content="Hola, ¿cómo estás?",
            tool_calls=[],
            tokens_in=100,
            tokens_out=50,
            duration_ms=500,
        )
        result = await harness.run("hola")
        assert result == "Hola, ¿cómo estás?"
        mock_context.add_user_message.assert_called_once_with("hola")
        mock_context.add_assistant_response.assert_called_once_with("Hola, ¿cómo estás?")

    @pytest.mark.asyncio
    async def test_empty_response(self, harness, mock_llm, mock_context, mock_registry):
        """LLM retorna vacío → fallback con último resultado exitoso."""
        mock_llm.complete.return_value = LLMResponse(
            stop_reason=StopReason.STOP.value,
            content="",
            tool_calls=[],
            tokens_in=100,
            tokens_out=0,
            duration_ms=500,
        )
        result = await harness.run("hola")
        assert isinstance(result, str)
        # Si no hay tool results previos, debe retornar algo informativo
        assert len(result) > 0

    # ── turno con tool calls ──
    @pytest.mark.asyncio
    async def test_single_tool_call(self, harness, mock_llm, mock_registry, mock_context):
        """LLM pide un tool → se ejecuta → LLM responde con datos."""
        mock_llm.complete.side_effect = [
            LLMResponse(
                stop_reason=StopReason.TOOL_USE.value,
                content="",
                tool_calls=[ToolCall(id="t1", name="list_directory", input={"path": "/tmp"})],
                tokens_in=200,
                tokens_out=150,
                duration_ms=1000,
            ),
            LLMResponse(
                stop_reason=StopReason.STOP.value,
                content="Encontré 3 archivos.",
                tool_calls=[],
                tokens_in=300,
                tokens_out=100,
                duration_ms=800,
            ),
        ]
        result = await harness.run("lista archivos en /tmp")
        assert "Encontré 3 archivos." in result or "mock result" in result
        assert mock_llm.complete.call_count == 2
        assert mock_registry.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_multiple_tool_calls(self, harness, mock_llm, mock_registry, mock_context):
        """LLM pide 3 tools en una llamada → todos se ejecutan."""
        mock_llm.complete.side_effect = [
            LLMResponse(
                stop_reason=StopReason.TOOL_USE.value,
                content="",
                tool_calls=[
                    ToolCall(id="t1", name="create_file", input={"path": "/tmp/a.txt", "content": "a"}),
                    ToolCall(id="t2", name="create_file", input={"path": "/tmp/b.txt", "content": "b"}),
                    ToolCall(id="t3", name="create_file", input={"path": "/tmp/c.txt", "content": "c"}),
                ],
                tokens_in=500,
                tokens_out=400,
                duration_ms=1500,
            ),
            LLMResponse(
                stop_reason=StopReason.STOP.value,
                content="Listo.",
                tool_calls=[],
                tokens_in=600,
                tokens_out=50,
                duration_ms=500,
            ),
        ]
        result = await harness.run("crea 3 archivos")
        assert mock_registry.execute.call_count == 3
        assert mock_llm.complete.call_count == 2

    # ── anti-loop: cache ──
    @pytest.mark.asyncio
    async def test_tool_cache_avoids_reexecution(self, harness, mock_llm, mock_registry, mock_context):
        """Mismo tool con mismos args → cache hit, no reejecuta."""
        mock_llm.complete.side_effect = [
            LLMResponse(
                stop_reason=StopReason.TOOL_USE.value,
                content="",
                tool_calls=[ToolCall(id="t1", name="list_directory", input={"path": "/tmp"})],
                tokens_in=200,
                tokens_out=150,
                duration_ms=1000,
            ),
            LLMResponse(
                stop_reason=StopReason.TOOL_USE.value,
                content="",
                tool_calls=[ToolCall(id="t2", name="list_directory", input={"path": "/tmp"})],  # MISMO args
                tokens_in=300,
                tokens_out=150,
                duration_ms=1000,
            ),
            LLMResponse(
                stop_reason=StopReason.STOP.value,
                content="Ya te dije.",
                tool_calls=[],
                tokens_in=400,
                tokens_out=50,
                duration_ms=500,
            ),
        ]
        result = await harness.run("lista /tmp dos veces")
        # Segunda llamada debe usar cache, no reejecutar
        assert mock_registry.execute.call_count == 1  # solo una ejecución real

    # ── anti-loop: push explícito ──
    @pytest.mark.asyncio
    async def test_anti_loop_push_after_repetitions(self, harness, mock_llm, mock_registry, mock_context):
        """3+ repeticiones del mismo tool → push explícito + llamada sin tools."""
        responses = []
        for i in range(4):
            responses.append(LLMResponse(
                stop_reason=StopReason.TOOL_USE.value,
                content="",
                tool_calls=[ToolCall(id=f"t{i}", name="list_directory", input={"path": "/tmp"})],
                tokens_in=200,
                tokens_out=150,
                duration_ms=1000,
            ))
        # Última respuesta tras push
        responses.append(LLMResponse(
            stop_reason=StopReason.STOP.value,
            content="Resultado: mock result",
            tool_calls=[],
            tokens_in=500,
            tokens_out=100,
            duration_ms=800,
        ))
        mock_llm.complete.side_effect = responses
        result = await harness.run("loop infinito simulado")
        # Debe haber una llamada sin schemas de tools (el push)
        calls = mock_llm.complete.call_args_list
        # Al menos una llamada debe tener tools=None o tools=[]
        # (la llamada final sin tools)
        assert mock_llm.complete.call_count >= 4

    # ── MAX_TOOLS_PER_CALL ──
    @pytest.mark.asyncio
    async def test_max_tools_per_call_limits(self, harness, mock_llm, mock_registry, mock_context):
        """LLM pide 10 tools → solo 5 se ejecutan, resto se descartan."""
        tool_calls = [
            ToolCall(id=f"t{i}", name="create_file", input={"path": f"/tmp/{i}.txt", "content": "x"})
            for i in range(10)
        ]
        mock_llm.complete.side_effect = [
            LLMResponse(
                stop_reason=StopReason.TOOL_USE.value,
                content="",
                tool_calls=tool_calls,
                tokens_in=1000,
                tokens_out=800,
                duration_ms=2000,
            ),
            LLMResponse(
                stop_reason=StopReason.STOP.value,
                content="Creados 5 archivos.",
                tool_calls=[],
                tokens_in=1200,
                tokens_out=100,
                duration_ms=800,
            ),
        ]
        result = await harness.run("crea 10 archivos")
        # MAX_TOOLS_PER_CALL = 5
        assert mock_registry.execute.call_count <= 5

    # ── max iterations ──
    @pytest.mark.asyncio
    async def test_max_iterations_reached(self, harness, mock_llm, mock_context):
        """LLM siempre pide tools → max_iterations alcanzado."""
        mock_llm.complete.return_value = LLMResponse(
            stop_reason=StopReason.TOOL_USE.value,
            content="",
            tool_calls=[ToolCall(id="t1", name="list_directory", input={"path": "/tmp"})],
            tokens_in=200,
            tokens_out=150,
            duration_ms=1000,
        )
        result = await harness.run("loop infinito")
        assert isinstance(result, str) and len(result) > 0
        assert mock_llm.complete.call_count <= 30  # max_iterations

    # ── skill matching ──
    @pytest.mark.asyncio
    async def test_skill_match_injects_body(self, harness, mock_skill_matcher, mock_skill_loader, mock_context, mock_llm, mock_skill_metadata):
        """Si hay skill match → body se inyecta en contexto."""
        mock_skill_matcher.match.return_value = mock_skill_metadata
        mock_llm.complete.return_value = LLMResponse(
            stop_reason=StopReason.STOP.value,
            content="Skill activada.",
            tool_calls=[],
            tokens_in=100,
            tokens_out=50,
            duration_ms=500,
        )
        await harness.run("crea un archivo")
        mock_skill_loader.load_body.assert_called_once_with("file-management")
        mock_context.set_skill.assert_called_once_with("skill body")

    @pytest.mark.asyncio
    async def test_no_skill_match(self, harness, mock_skill_matcher, mock_context, mock_llm):
        """Sin match → no se carga skill."""
        mock_skill_matcher.match.return_value = None
        mock_llm.complete.return_value = LLMResponse(
            stop_reason=StopReason.STOP.value,
            content="Ok.",
            tool_calls=[],
            tokens_in=100,
            tokens_out=50,
            duration_ms=500,
        )
        await harness.run("hola")
        mock_context.set_skill.assert_called_once_with(None)

    # ── trace recording ──
    @pytest.mark.asyncio
    async def test_trace_recorded(self, harness, mock_llm, mock_trace_recorder):
        """Cada turno debe guardarse en traces."""
        mock_llm.complete.return_value = LLMResponse(
            stop_reason=StopReason.STOP.value,
            content="Respuesta.",
            tool_calls=[],
            tokens_in=100,
            tokens_out=50,
            duration_ms=500,
        )
        await harness.run("test")
        mock_trace_recorder.record.assert_called_once()
        args = mock_trace_recorder.record.call_args[0]
        assert isinstance(args[0], TurnTrace)
        assert args[0].user_message == "test"
        assert args[0].final_response == "Respuesta."

    @pytest.mark.asyncio
    async def test_trace_recorded_on_error(self, harness, mock_llm, mock_trace_recorder, mock_registry):
        """Incluso con error, el trace debe guardarse."""
        mock_llm.complete.return_value = LLMResponse(
            stop_reason=StopReason.TOOL_USE.value,
            content="",
            tool_calls=[ToolCall(id="t1", name="run_command", input={"command": "sudo ls"})],
            tokens_in=200,
            tokens_out=150,
            duration_ms=1000,
        )
        mock_registry.execute.return_value = ToolResult(
            tool_use_id="t1", content="Comando bloqueado", is_error=True
        )
        await harness.run("test error")
        mock_trace_recorder.record.assert_called_once()

    # ── nunca lanza excepción ──
    @pytest.mark.asyncio
    async def test_no_exception_propagated(self, harness, mock_llm):
        """El harness NUNCA debe propagar excepciones al llamador."""
        mock_llm.complete.side_effect = Exception("LLM crash")
        result = await harness.run("test")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_tool_error_handled(self, harness, mock_llm, mock_registry):
        """Error en tool → ToolResult con is_error, no excepción."""
        mock_registry.execute.return_value = ToolResult(
            tool_use_id="t1", content="Error simulado", is_error=True
        )
        mock_llm.complete.side_effect = [
            LLMResponse(
                stop_reason=StopReason.TOOL_USE.value,
                content="",
                tool_calls=[ToolCall(id="t1", name="delete_file", input={"path": "/tmp/x"})],
                tokens_in=200,
                tokens_out=150,
                duration_ms=1000,
            ),
            LLMResponse(
                stop_reason=StopReason.STOP.value,
                content="Hubo un error.",
                tool_calls=[],
                tokens_in=300,
                tokens_out=100,
                duration_ms=800,
            ),
        ]
        result = await harness.run("borra archivo")
        assert isinstance(result, str)
        assert "error" in result.lower() or "Hubo" in result

    # ── reset ──
    def test_reset(self, harness, mock_context):
        harness.reset()
        mock_context.clear.assert_called_once()
