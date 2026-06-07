"""
Tests para ConversationContext.

Cubre:
- System prompt como primer mensaje
- add_user_message / add_assistant_response
- add_tool_results con formato correcto
- _trim() respeta max_history
- Skill injection en el contexto
- Anti-loop: formato de errores no expone API interna
- Context poisoning prevention con prefijo [ERROR]
"""

import pytest
from agent.loop.context import ConversationContext
from agent.tools.base import ToolResult


class TestConversationContext:
    """Suite de contexto conversacional — corazón del state management."""

    @pytest.fixture
    def ctx(self):
        return ConversationContext(
            max_history=4,
            system_prompt="Eres File Agent. NO eres ChatGPT."
        )

    # ── system prompt ──
    def test_system_prompt_first_message(self, ctx):
        messages = ctx.get_messages()
        assert messages[0]["role"] == "system"
        assert "File Agent" in messages[0]["content"]
        assert "NO eres ChatGPT" in messages[0]["content"]

    def test_system_prompt_persists_after_messages(self, ctx):
        ctx.add_user_message("hola")
        ctx.add_assistant_response("hola de vuelta")
        messages = ctx.get_messages()
        assert messages[0]["role"] == "system"

    # ── historial básico ──
    def test_add_user_message(self, ctx):
        ctx.add_user_message("crea un archivo")
        messages = ctx.get_messages()
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "crea un archivo"

    def test_add_assistant_response(self, ctx):
        ctx.add_user_message("hola")
        ctx.add_assistant_response("hola!")
        messages = ctx.get_messages()
        assert messages[-1]["role"] == "assistant"
        assert messages[-1]["content"] == "hola!"

    # ── tool results ──
    def test_add_tool_results_success(self, ctx):
        ctx.add_user_message("lista archivos")
        ctx.add_tool_results([
            ToolResult(tool_use_id="t1", content="file1.txt\nfile2.txt", is_error=False)
        ])
        messages = ctx.get_messages()
        tool_msg = messages[-1]
        assert tool_msg["role"] == "tool"
        assert "file1.txt" in tool_msg["content"]
        assert "[ERROR]" not in tool_msg["content"]

    def test_add_tool_results_error_no_expose_api(self, ctx):
        """Errores NO deben invitar al LLM a explicar parámetros técnicos (Bug 6)."""
        ctx.add_tool_results([
            ToolResult(tool_use_id="t2", content="Permission denied", is_error=True)
        ])
        messages = ctx.get_messages()
        error_msg = messages[-1]["content"]
        assert "[ERROR]" not in error_msg  # El formato viejo invitaba a explicar
        assert "Error en operación" in error_msg
        assert "NO expliques" in error_msg or "NO muestres" in error_msg

    def test_add_tool_results_multiple(self, ctx):
        results = [
            ToolResult(tool_use_id="t3", content="ok", is_error=False),
            ToolResult(tool_use_id="t4", content="fail", is_error=True),
        ]
        ctx.add_tool_results(results)
        messages = ctx.get_messages()
        assert len([m for m in messages if m["role"] == "tool"]) == 2

    # ── trimming ──
    def test_trim_respects_max_history(self, ctx):
        """max_history=4 → máximo 4 pares user/assistant + system prompt."""
        for i in range(10):
            ctx.add_user_message(f"msg {i}")
            ctx.add_assistant_response(f"resp {i}")

        messages = ctx.get_messages()
        # system prompt + 4 pares = 9 mensajes
        assert len(messages) == 9
        assert messages[0]["role"] == "system"
        # Los más recientes deben estar presentes
        assert messages[-1]["content"] == "resp 9"
        assert messages[-2]["content"] == "msg 9"
        # Los más antiguos deben haber sido eliminados
        assert "msg 0" not in [m["content"] for m in messages]

    def test_trim_keeps_system_prompt(self, ctx):
        for i in range(20):
            ctx.add_user_message(f"msg {i}")
            ctx.add_assistant_response(f"resp {i}")
        messages = ctx.get_messages()
        assert messages[0]["role"] == "system"

    # ── skill injection ──
    def test_set_skill_injects_body(self, ctx):
        skill_body = "## Context\nEres experto en archivos.\n## Instructions\n1. Verifica paths"
        ctx.set_skill(skill_body)
        ctx.add_user_message("hola")
        messages = ctx.get_messages()
        # El body debe estar cerca del system prompt, antes del mensaje del usuario
        assert skill_body in messages[1]["content"] or skill_body in messages[0]["content"]

    def test_set_skill_none_clears(self, ctx):
        ctx.set_skill("body aquí")
        ctx.set_skill(None)
        ctx.add_user_message("hola")
        messages = ctx.get_messages()
        assert "body aquí" not in [m["content"] for m in messages]

    def test_skill_persists_across_turns(self, ctx):
        ctx.set_skill("skill body")
        ctx.add_user_message("hola")
        ctx.add_assistant_response("hola!")
        ctx.add_user_message("adios")
        messages = ctx.get_messages()
        assert "skill body" in [m["content"] for m in messages]

    # ── clear ──
    def test_clear_keeps_skill(self, ctx):
        ctx.set_skill("skill body")
        ctx.add_user_message("hola")
        ctx.add_assistant_response("hola!")
        ctx.clear()
        ctx.add_user_message("nuevo")
        messages = ctx.get_messages()
        assert messages[0]["role"] == "system"
        assert "skill body" in [m["content"] for m in messages]
        assert "hola" not in [m["content"] for m in messages]
        assert "nuevo" in [m["content"] for m in messages]

    def test_clear_without_skill(self, ctx):
        ctx.add_user_message("hola")
        ctx.add_assistant_response("hola!")
        ctx.clear()
        messages = ctx.get_messages()
        assert len(messages) == 1  # solo system prompt

    # ── anti-loop / context poisoning ──
    def test_error_format_prevents_context_poisoning(self, ctx):
        """El formato de error debe prevenir que el LLM asuma éxito (Bug 6)."""
        ctx.add_tool_results([
            ToolResult(tool_use_id="t5", content="File not found", is_error=True)
        ])
        messages = ctx.get_messages()
        content = messages[-1]["content"]
        # Debe contener instrucción explícita de no asumir éxito
        assert "NO asumas éxito" in content or "no asumas éxito" in content or "Reporta este error" in content

    def test_tool_results_with_name_field(self, ctx):
        """Ollama espera 'name' en mensajes de tool."""
        ctx.add_tool_results([
            ToolResult(tool_use_id="t6", content="output", is_error=False)
        ])
        messages = ctx.get_messages()
        assert "name" in messages[-1]

    # ── edge cases ──
    def test_empty_messages(self, ctx):
        messages = ctx.get_messages()
        assert len(messages) == 1  # solo system prompt
        assert messages[0]["role"] == "system"

    def test_get_messages_returns_copy(self, ctx):
        ctx.add_user_message("hola")
        m1 = ctx.get_messages()
        m2 = ctx.get_messages()
        assert m1 is not m2
        m1.append({"role": "user", "content": "injected"})
        assert len(ctx.get_messages()) == 2  # no se modificó el interno

    def test_max_history_zero(self):
        """max_history=0 debe mantener solo system prompt."""
        ctx = ConversationContext(max_history=0, system_prompt="sys")
        ctx.add_user_message("hola")
        ctx.add_assistant_response("hola!")
        messages = ctx.get_messages()
        assert len(messages) == 1
        assert messages[0]["role"] == "system"
