"""
Tests para trace models — serialización Pydantic v2.

Cubre:
- ToolTrace serializa correctamente
- LLMCallTrace serializa correctamente
- TurnTrace serializa correctamente
- frozen=True — inmutabilidad
- model_dump_json() produce JSON válido
- Campos opcionales (skill_activated: str | None)
- Timestamps ISO 8601
- UUIDs únicos
"""

import json
import uuid
from datetime import datetime

import pytest
from pydantic import ValidationError

from agent.traces.models import ToolTrace, LLMCallTrace, TurnTrace


class TestToolTrace:
    """Trace de ejecución de un tool."""

    def test_basic_creation(self):
        trace = ToolTrace(
            name="create_file",
            input={"path": "/tmp/test.txt", "content": "hello"},
            output="File created",
            is_error=False,
            duration_ms=150,
        )
        assert trace.name == "create_file"
        assert trace.is_error is False
        assert trace.duration_ms == 150

    def test_error_tool(self):
        trace = ToolTrace(
            name="delete_file",
            input={"path": "/etc/passwd"},
            output="Permission denied",
            is_error=True,
            duration_ms=50,
        )
        assert trace.is_error is True
        assert "Permission denied" in trace.output

    def test_frozen_cannot_modify(self):
        trace = ToolTrace(
            name="read_file",
            input={"path": "/tmp/a.txt"},
            output="content",
            is_error=False,
            duration_ms=100,
        )
        with pytest.raises(ValidationError):
            trace.is_error = True

    def test_serialization(self):
        trace = ToolTrace(
            name="list_directory",
            input={"path": "/tmp"},
            output="file1\nfile2",
            is_error=False,
            duration_ms=200,
        )
        json_str = trace.model_dump_json()
        data = json.loads(json_str)
        assert data["name"] == "list_directory"
        assert data["input"] == {"path": "/tmp"}
        assert data["is_error"] is False
        assert data["duration_ms"] == 200

    def test_output_truncated_in_serialization(self):
        """Output >500 chars debe truncarse en el trace."""
        long_output = "A" * 1000
        trace = ToolTrace(
            name="run_command",
            input={"command": "cat bigfile"},
            output=long_output,
            is_error=False,
            duration_ms=500,
        )
        # El modelo debe truncar o almacenar completo según spec
        # Según MODULE_MAP: output truncado si >500 chars
        assert len(trace.output) <= 600  # 500 + margen


class TestLLMCallTrace:
    """Trace de una llamada al LLM."""

    def test_basic_creation(self):
        trace = LLMCallTrace(
            model="gpt-oss:20b",
            tokens_in=1200,
            tokens_out=800,
            stop_reason="stop",
            duration_ms=2500,
        )
        assert trace.model == "gpt-oss:20b"
        assert trace.tokens_in == 1200
        assert trace.stop_reason == "stop"

    def test_tool_calls_stop_reason(self):
        trace = LLMCallTrace(
            model="gpt-oss:20b",
            tokens_in=500,
            tokens_out=300,
            stop_reason="tool_calls",
            duration_ms=1800,
        )
        assert trace.stop_reason == "tool_calls"

    def test_max_tokens_stop_reason(self):
        trace = LLMCallTrace(
            model="gpt-oss:20b",
            tokens_in=4000,
            tokens_out=2048,
            stop_reason="length",
            duration_ms=3000,
        )
        assert trace.stop_reason == "length"

    def test_zero_tokens(self):
        """Ollama puede no retornar usage."""
        trace = LLMCallTrace(
            model="gpt-oss:20b",
            tokens_in=0,
            tokens_out=0,
            stop_reason="stop",
            duration_ms=1000,
        )
        assert trace.tokens_in == 0
        assert trace.tokens_out == 0

    def test_frozen(self):
        trace = LLMCallTrace(
            model="gpt-oss:20b",
            tokens_in=100,
            tokens_out=50,
            stop_reason="stop",
            duration_ms=500,
        )
        with pytest.raises(ValidationError):
            trace.duration_ms = 999

    def test_serialization(self):
        trace = LLMCallTrace(
            model="gpt-oss:20b",
            tokens_in=1000,
            tokens_out=500,
            stop_reason="tool_calls",
            duration_ms=2000,
        )
        data = json.loads(trace.model_dump_json())
        assert data["model"] == "gpt-oss:20b"
        assert data["stop_reason"] == "tool_calls"


class TestTurnTrace:
    """Trace completo de un turno conversacional."""

    @pytest.fixture
    def sample_turn(self):
        return TurnTrace(
            turn_id=str(uuid.uuid4()),
            timestamp=datetime.utcnow().isoformat(),
            user_message="crea un archivo",
            skill_activated="file-management",
            llm_calls=[
                LLMCallTrace(
                    model="gpt-oss:20b",
                    tokens_in=500,
                    tokens_out=200,
                    stop_reason="tool_calls",
                    duration_ms=1500,
                ),
                LLMCallTrace(
                    model="gpt-oss:20b",
                    tokens_in=700,
                    tokens_out=300,
                    stop_reason="stop",
                    duration_ms=1200,
                ),
            ],
            tool_calls=[
                ToolTrace(
                    name="create_file",
                    input={"path": "/tmp/test.txt", "content": "hello"},
                    output="File created",
                    is_error=False,
                    duration_ms=100,
                ),
            ],
            final_response="Archivo creado exitosamente.",
            total_duration_ms=2700,
            total_llm_calls=2,
            total_tool_calls=1,
            had_errors=False,
        )

    def test_creation(self, sample_turn):
        assert sample_turn.user_message == "crea un archivo"
        assert sample_turn.skill_activated == "file-management"
        assert sample_turn.total_llm_calls == 2
        assert sample_turn.total_tool_calls == 1
        assert sample_turn.had_errors is False

    def test_no_skill(self):
        turn = TurnTrace(
            turn_id=str(uuid.uuid4()),
            timestamp=datetime.utcnow().isoformat(),
            user_message="hola",
            skill_activated=None,
            llm_calls=[],
            tool_calls=[],
            final_response="¡Hola! ¿En qué puedo ayudarte?",
            total_duration_ms=500,
            total_llm_calls=0,
            total_tool_calls=0,
            had_errors=False,
        )
        assert turn.skill_activated is None
        assert turn.total_llm_calls == 0

    def test_with_errors(self):
        turn = TurnTrace(
            turn_id=str(uuid.uuid4()),
            timestamp=datetime.utcnow().isoformat(),
            user_message="borra /etc",
            skill_activated=None,
            llm_calls=[
                LLMCallTrace(
                    model="gpt-oss:20b",
                    tokens_in=300,
                    tokens_out=150,
                    stop_reason="tool_calls",
                    duration_ms=1000,
                ),
            ],
            tool_calls=[
                ToolTrace(
                    name="delete_file",
                    input={"path": "/etc/passwd"},
                    output="Permission denied",
                    is_error=True,
                    duration_ms=50,
                ),
            ],
            final_response="Error: no tienes permiso.",
            total_duration_ms=1050,
            total_llm_calls=1,
            total_tool_calls=1,
            had_errors=True,
        )
        assert turn.had_errors is True
        assert turn.tool_calls[0].is_error is True

    def test_frozen(self, sample_turn):
        with pytest.raises(ValidationError):
            sample_turn.had_errors = True

    def test_jsonl_format(self, sample_turn):
        """Debe producir una línea JSON válida para .jsonl."""
        json_str = sample_turn.model_dump_json()
        # Una línea JSON válida
        assert "\n" not in json_str  # no newlines en el JSON string
        data = json.loads(json_str)
        assert data["user_message"] == "crea un archivo"
        assert len(data["llm_calls"]) == 2
        assert len(data["tool_calls"]) == 1

    def test_uuid_format(self, sample_turn):
        """turn_id debe ser un UUID válido."""
        uuid.UUID(sample_turn.turn_id)  # no lanza error

    def test_iso_timestamp(self, sample_turn):
        """timestamp debe ser ISO 8601 parseable."""
        dt = datetime.fromisoformat(sample_turn.timestamp)
        assert isinstance(dt, datetime)

    def test_totals_match(self):
        """total_llm_calls y total_tool_calls deben coincidir con listas."""
        llm_calls = [
            LLMCallTrace(model="gpt-oss:20b", tokens_in=100, tokens_out=50, stop_reason="stop", duration_ms=500),
        ]
        tool_calls = [
            ToolTrace(name="ls", input={}, output="a.txt", is_error=False, duration_ms=100),
            ToolTrace(name="cat", input={}, output="content", is_error=False, duration_ms=50),
        ]
        turn = TurnTrace(
            turn_id=str(uuid.uuid4()),
            timestamp=datetime.utcnow().isoformat(),
            user_message="lista y lee",
            skill_activated=None,
            llm_calls=llm_calls,
            tool_calls=tool_calls,
            final_response="ok",
            total_duration_ms=650,
            total_llm_calls=len(llm_calls),
            total_tool_calls=len(tool_calls),
            had_errors=False,
        )
        assert turn.total_llm_calls == 1
        assert turn.total_tool_calls == 2

    def test_nested_serialization(self, sample_turn):
        """Los objetos anidados deben serializarse completamente."""
        data = json.loads(sample_turn.model_dump_json())
        assert data["llm_calls"][0]["model"] == "gpt-oss:20b"
        assert data["tool_calls"][0]["name"] == "create_file"
        assert data["tool_calls"][0]["input"]["path"] == "/tmp/test.txt"
