"""
Tests para constants.py — Enums del dominio.

Cubre:
- Valores de enum correctos
- Comparación de enums
- Uso en traces y lógica de negocio
"""

import pytest
from agent.core.constants import SecurityLevel, StopReason, SkillStatus


class TestSecurityLevel:
    """Niveles de seguridad para comandos de shell."""

    def test_safe_value(self):
        assert SecurityLevel.SAFE == "safe"
        assert SecurityLevel.SAFE.value == "safe"

    def test_moderate_value(self):
        assert SecurityLevel.MODERATE == "moderate"

    def test_dangerous_value(self):
        assert SecurityLevel.DANGEROUS == "dangerous"

    def test_blocked_value(self):
        assert SecurityLevel.BLOCKED == "blocked"

    def test_comparison(self):
        assert SecurityLevel.SAFE != SecurityLevel.DANGEROUS
        assert SecurityLevel.BLOCKED == SecurityLevel.BLOCKED

    def test_membership(self):
        assert "safe" in [e.value for e in SecurityLevel]
        assert "blocked" in [e.value for e in SecurityLevel]

    def test_from_string(self):
        assert SecurityLevel("safe") == SecurityLevel.SAFE
        assert SecurityLevel("dangerous") == SecurityLevel.DANGEROUS

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            SecurityLevel("invalid")

    def test_ordering_not_defined(self):
        """StrEnum hereda de str — soporta comparación alfabética, no por jerarquía."""
        assert SecurityLevel.BLOCKED < SecurityLevel.SAFE
        assert not (SecurityLevel.SAFE < SecurityLevel.DANGEROUS)
        

class TestStopReason:
    """Razones de parada del loop agéntico."""

    def test_stop_value(self):
        assert StopReason.STOP == "stop"

    def test_tool_use_value(self):
        assert StopReason.TOOL_USE == "tool_calls"

    def test_max_tokens_value(self):
        assert StopReason.MAX_TOKENS == "length"

    def test_max_iter_value(self):
        assert StopReason.MAX_ITER == "max_iter"

    def test_error_value(self):
        assert StopReason.ERROR == "error"

    def test_all_values_unique(self):
        values = [e.value for e in StopReason]
        assert len(values) == len(set(values))

    def test_from_string(self):
        assert StopReason("stop") == StopReason.STOP
        assert StopReason("tool_calls") == StopReason.TOOL_USE

    def test_used_in_harness_logic(self):
        """Los valores deben coincidir con lo que Ollama retorna."""
        # Ollama usa "stop", "tool_calls", "length"
        assert StopReason.STOP.value == "stop"
        assert StopReason.TOOL_USE.value == "tool_calls"
        assert StopReason.MAX_TOKENS.value == "length"


class TestSkillStatus:
    """Estados de matching de skills."""

    def test_matched_value(self):
        assert SkillStatus.MATCHED == "matched"

    def test_no_match_value(self):
        assert SkillStatus.NO_MATCH == "no_match"

    def test_disabled_value(self):
        assert SkillStatus.DISABLED == "disabled"

    def test_from_string(self):
        assert SkillStatus("matched") == SkillStatus.MATCHED
        assert SkillStatus("no_match") == SkillStatus.NO_MATCH
        assert SkillStatus("disabled") == SkillStatus.DISABLED

    def test_all_values(self):
        assert set(SkillStatus) == {SkillStatus.MATCHED, SkillStatus.NO_MATCH, SkillStatus.DISABLED}


class TestEnumIntegration:
    """Uso conjunto de enums en lógica de negocio."""

    def test_security_level_in_dict(self):
        levels = {
            SecurityLevel.SAFE: ["ls", "cat"],
            SecurityLevel.MODERATE: ["touch"],
            SecurityLevel.DANGEROUS: ["rm"],
        }
        assert "ls" in levels[SecurityLevel.SAFE]

    def test_stop_reason_switch(self):
        """Simula el switch de stop_reason en el harness."""
        def handle_stop(reason: StopReason) -> str:
            match reason:
                case StopReason.STOP:
                    return "final"
                case StopReason.TOOL_USE:
                    return "tools"
                case StopReason.MAX_TOKENS:
                    return "truncated"
                case StopReason.MAX_ITER:
                    return "max_iter"
                case StopReason.ERROR:
                    return "error"
            return "unknown"

        assert handle_stop(StopReason.STOP) == "final"
        assert handle_stop(StopReason.TOOL_USE) == "tools"
        assert handle_stop(StopReason.MAX_TOKENS) == "truncated"

    def test_skill_status_in_trace(self):
        """SkillStatus puede serializarse en traces."""
        status = SkillStatus.MATCHED
        assert status.value == "matched"
        # En JSON se serializa como string
        import json
        assert json.dumps(status.value) == '"matched"'
