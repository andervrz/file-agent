# agent/tools/command_tool.py
import asyncio
import shlex

from ..core.config import SecurityConfig
from ..core.constants import SecurityLevel
from .base import BaseTool, PathSafeguard, ToolResult


class CommandValidator:
    def __init__(self, security: SecurityConfig):
        self._security = security

    def validate(self, command: str) -> SecurityLevel:
        stripped = command.strip()
        if not stripped:
            raise ValueError("Command cannot be empty")
        base = stripped.split()[0]
        for level in [
            SecurityLevel.BLOCKED,
            SecurityLevel.DANGEROUS,
            SecurityLevel.MODERATE,
            SecurityLevel.SAFE,
        ]:
            cmds = self._security.levels.get(level.value, [])
            if base in cmds:
                if level == SecurityLevel.BLOCKED:
                    raise PermissionError(
                        f"Command blocked by security policy: {base}"
                    )
                return level
        return SecurityLevel.SAFE

    def is_allowed(self, command: str) -> tuple[bool, SecurityLevel]:
        try:
            level = self.validate(command)
            return (True, level)
        except (PermissionError, ValueError):
            return (False, SecurityLevel.BLOCKED)


class RunCommandTool(BaseTool):
    name = "run_command"
    description = "Ejecuta un comando de shell con validación de seguridad y timeout."
    input_schema = {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    }

    def __init__(self, security: SecurityConfig, safeguard: PathSafeguard):
        self._validator = CommandValidator(security)
        self._safeguard = safeguard
        self._timeouts = security.timeout_seconds

    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        command = kwargs.get("command", "")
        allowed, level = self._validator.is_allowed(command)

        if not allowed:
            return ToolResult(
                tool_use_id=tool_use_id,
                content=f"Command blocked by security policy: {command}",
                is_error=True,
            )

        timeout = self._timeouts.get(level.value, 30)
        proc = None

        try:
            proc = await asyncio.create_subprocess_exec(
                *shlex.split(command),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            output = stdout.decode("utf-8", errors="replace")
            err_text = stderr.decode("utf-8", errors="replace")
            if err_text:
                output += f"\n[stderr]\n{err_text}"
            if len(output) > 10_000:
                output = output[:10_000] + "\n... [output truncated at 10KB]"
            return ToolResult(
                tool_use_id=tool_use_id,
                content=output,
                is_error=proc.returncode != 0,
            )
        except asyncio.TimeoutError:
            if proc:
                proc.kill()
            return ToolResult(
                tool_use_id=tool_use_id,
                content=f"timeout: command exceeded {timeout}s — {command}",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_use_id,
                content=f"Command execution error: {e}",
                is_error=True,
            )


def build_command_tool(
    security: SecurityConfig, safeguard: PathSafeguard
) -> RunCommandTool:
    return RunCommandTool(security, safeguard)