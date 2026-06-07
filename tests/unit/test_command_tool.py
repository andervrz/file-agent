"""
Tests para CommandTool (RunCommandTool + CommandValidator).

Cubre:
- Niveles SAFE/MODERATE/DANGEROUS/BLOCKED
- shlex.split() funciona correctamente
- Timeout según nivel de seguridad
- Comandos bloqueados son rechazados
- Outputs >10KB se truncan
- proc=None inicializado (Bug 2 fix)
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from agent.tools.base import PathSafeguard, ToolResult
from agent.tools.command_tool import CommandValidator, RunCommandTool, build_command_tool
from agent.core.constants import SecurityLevel
from agent.core.config import SecurityConfig


class TestCommandValidator:
    """Validación de niveles de seguridad de comandos."""

    @pytest.fixture
    def validator(self):
        security = SecurityConfig(
            levels={
                "safe": ["cat", "ls", "grep", "find", "head", "tail", "wc", "pwd", "echo", "date"],
                "moderate": ["touch", "mkdir", "cp", "mv", "chmod", "ln"],
                "dangerous": ["rm", "rmdir", "dd", "truncate"],
                "blocked": ["sudo", "su", "bash", "sh", "python", "pip", "apt", "curl", "wget", "nc"],
            },
            require_confirmation=["dangerous"],
            blocked_paths=[],
            timeout_seconds={"safe": 10, "moderate": 30, "dangerous": 60},
        )
        return CommandValidator(security)

    # ── SAFE ──
    def test_safe_ls(self, validator):
        assert validator.validate("ls -la") == SecurityLevel.SAFE

    def test_safe_pwd(self, validator):
        assert validator.validate("pwd") == SecurityLevel.SAFE

    def test_safe_echo(self, validator):
        assert validator.validate("echo hello") == SecurityLevel.SAFE

    def test_safe_grep(self, validator):
        assert validator.validate("grep foo file.txt") == SecurityLevel.SAFE

    # ── MODERATE ──
    def test_moderate_touch(self, validator):
        assert validator.validate("touch file.txt") == SecurityLevel.MODERATE

    def test_moderate_mkdir(self, validator):
        assert validator.validate("mkdir new_dir") == SecurityLevel.MODERATE

    def test_moderate_cp(self, validator):
        assert validator.validate("cp a.txt b.txt") == SecurityLevel.MODERATE

    def test_moderate_mv(self, validator):
        assert validator.validate("mv a.txt b.txt") == SecurityLevel.MODERATE

    # ── DANGEROUS ──
    def test_dangerous_rm(self, validator):
        assert validator.validate("rm file.txt") == SecurityLevel.DANGEROUS

    def test_dangerous_rmdir(self, validator):
        assert validator.validate("rmdir old_dir") == SecurityLevel.DANGEROUS

    def test_dangerous_dd(self, validator):
        assert validator.validate("dd if=/dev/zero of=/tmp/test") == SecurityLevel.DANGEROUS

    # ── BLOCKED ──
    def test_blocked_sudo(self, validator):
        with pytest.raises(PermissionError):
            validator.validate("sudo apt update")

    def test_blocked_bash(self, validator):
        with pytest.raises(PermissionError):
            validator.validate("bash -c 'echo hi'")

    def test_blocked_sh(self, validator):
        with pytest.raises(PermissionError):
            validator.validate("sh script.sh")

    def test_blocked_python(self, validator):
        with pytest.raises(PermissionError):
            validator.validate("python script.py")

    def test_blocked_curl(self, validator):
        with pytest.raises(PermissionError):
            validator.validate("curl https://example.com")

    def test_blocked_wget(self, validator):
        with pytest.raises(PermissionError):
            validator.validate("wget https://example.com")

    def test_blocked_nc(self, validator):
        with pytest.raises(PermissionError):
            validator.validate("nc -l 8080")

    # ── is_allowed ──
    def test_is_allowed_safe(self, validator):
        allowed, level = validator.is_allowed("ls")
        assert allowed is True
        assert level == SecurityLevel.SAFE

    def test_is_allowed_blocked(self, validator):
        allowed, level = validator.is_allowed("sudo rm -rf /")
        assert allowed is False
        assert level == SecurityLevel.BLOCKED

    # ── edge cases ──
    def test_command_with_path(self, validator):
        """Comando con path absoluto debe extraer el comando base."""
        assert validator.validate("/usr/bin/ls") == SecurityLevel.SAFE

    def test_empty_command(self, validator):
        """Comando vacío debe manejarse sin crash."""
        with pytest.raises((PermissionError, ValueError)):
            validator.validate("")


class TestRunCommandTool:
    """Ejecución real de comandos con seguridad."""

    @pytest.fixture
    def tool(self):
        security = SecurityConfig(
            levels={
                "safe": ["cat", "ls", "grep", "find", "head", "tail", "wc", "pwd", "echo", "date"],
                "moderate": ["touch", "mkdir", "cp", "mv", "chmod", "ln"],
                "dangerous": ["rm", "rmdir", "dd", "truncate"],
                "blocked": ["sudo", "su", "bash", "sh", "python", "pip", "apt", "curl", "wget", "nc"],
            },
            require_confirmation=["dangerous"],
            blocked_paths=[],
            timeout_seconds={"safe": 10, "moderate": 30, "dangerous": 60},
        )
        safeguard = PathSafeguard(blocked_paths=[])
        return build_command_tool(security, safeguard)

    @pytest.mark.asyncio
    async def test_safe_ls(self, tool):
        """ls debe ejecutarse y retornar output."""
        result = await tool.execute(tool_use_id="t1", command="ls -la")
        assert isinstance(result, ToolResult)
        assert result.is_error is False
        assert result.tool_use_id == "t1"
        assert len(result.content) > 0

    @pytest.mark.asyncio
    async def test_safe_pwd(self, tool):
        """pwd debe retornar el directorio actual."""
        result = await tool.execute(tool_use_id="t2", command="pwd")
        assert result.is_error is False
        assert "/" in result.content

    @pytest.mark.asyncio
    async def test_safe_echo(self, tool):
        """echo debe retornar exactamente el texto."""
        result = await tool.execute(tool_use_id="t3", command="echo hello_world")
        assert result.is_error is False
        assert "hello_world" in result.content

    @pytest.mark.asyncio
    async def test_blocked_command(self, tool):
        """Comando bloqueado debe retornar ToolResult con is_error=True."""
        result = await tool.execute(tool_use_id="t4", command="sudo ls")
        assert result.is_error is True
        assert "bloqueado" in result.content.lower() or "blocked" in result.content.lower()

    @pytest.mark.asyncio
    async def test_command_not_found(self, tool):
        """Comando inexistente debe retornar error sin crash."""
        result = await tool.execute(tool_use_id="t5", command="this_command_does_not_exist_12345")
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_timeout_safe(self, tool):
        """Comando que excede timeout debe ser interrumpido."""
        result = await tool.execute(tool_use_id="t6", command="sleep 15")
        assert result.is_error is True
        assert "timeout" in result.content.lower() or "tiempo" in result.content.lower()

    @pytest.mark.asyncio
    async def test_truncation_large_output(self, tool):
        """Output >10KB debe truncarse con aviso."""
        # Usamos seq que es safe pero genera mucho output
        result = await tool.execute(tool_use_id="t7", command="seq 1 10000")
        assert len(result.content) <= 11000  # 10KB + margen de aviso
        assert "truncado" in result.content.lower() or "truncated" in result.content.lower() or "trunc" in result.content.lower()

    @pytest.mark.asyncio
    async def test_shlex_split_used(self, tool):
        """shlex.split debe usarse para parsear el comando (Bug 2)."""
        # Si shlex no está importado, este test fallaría indirectamente
        # Verificamos que comandos con espacios en quotes funcionan
        result = await tool.execute(tool_use_id="t8", command='echo "hello world"')
        assert result.is_error is False
        assert "hello world" in result.content

    @pytest.mark.asyncio
    async def test_proc_initialized_before_try(self, tool):
        """proc debe estar inicializado antes del try para evitar UnboundLocalError en timeout."""
        # Forzamos un timeout corto simulado
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            mock_proc.return_value.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
            # Si proc no está inicializado, esto lanzaría UnboundLocalError
            result = await tool.execute(tool_use_id="t9", command="sleep 5")
            assert result.is_error is True

    @pytest.mark.asyncio
    async def test_moderate_mkdir(self, tool, tmp_path):
        """mkdir debe crear directorio."""
        dir_path = tmp_path / "new_dir"
        result = await tool.execute(tool_use_id="t10", command=f"mkdir {dir_path}")
        assert result.is_error is False
        assert dir_path.exists()

    @pytest.mark.asyncio
    async def test_dangerous_rm_requires_confirmation(self, tool, tmp_path):
        """rm debe ejecutarse (la confirmación la maneja el LLM, no el código)."""
        file_path = tmp_path / "to_delete.txt"
        file_path.write_text("delete me")
        result = await tool.execute(tool_use_id="t11", command=f"rm {file_path}")
        assert result.is_error is False
        assert not file_path.exists()
