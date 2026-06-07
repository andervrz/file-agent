# agent/tools/git_tool.py
from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

from .base import BaseTool, PathSafeguard, ToolResult

# ── Clasificación de comandos ─────────────────────────────────────────────────

_SAFE = {
    "status", "log", "diff", "show", "branch", "tag", "remote",
    "stash", "describe", "blame", "grep", "reflog", "shortlog",
    "ls-files", "ls-tree", "cat-file", "rev-parse", "rev-list",
    "count-objects", "config", "version", "help",
}

_MODERATE = {
    "init", "add", "commit", "checkout", "switch", "merge",
    "rebase", "cherry-pick", "rm", "mv", "restore", "worktree",
    "submodule", "notes", "tag",
}

_NETWORK = {
    "push", "pull", "clone", "fetch",
}

# Flags que requieren confirmación explícita del usuario
_DANGEROUS_FLAGS = {
    "--force", "-f",          # push --force
    "--hard",                  # reset --hard
}


class GitValidator:
    """Valida subcomandos y flags git antes de ejecutar."""

    def validate(self, command: str, args: str) -> tuple[bool, str]:
        """
        Retorna (permitido: bool, motivo_si_bloqueado: str).
        """
        cmd = command.strip().lower()
        all_args = args.lower() if args else ""

        allowed = cmd in _SAFE or cmd in _MODERATE or cmd in _NETWORK
        if not allowed:
            return False, f"Comando git '{cmd}' no reconocido o no permitido."

        # Detectar flags destructivos
        for flag in _DANGEROUS_FLAGS:
            if flag in all_args:
                return (
                    False,
                    f"'git {cmd} {flag}' es una operación destructiva. "
                    f"Pide confirmación explícita al usuario antes de ejecutar.",
                )

        # git clean sin -n (dry-run) es peligroso
        if cmd == "clean" and "-n" not in all_args and "--dry-run" not in all_args:
            return (
                False,
                "git clean sin --dry-run puede eliminar archivos. "
                "Usa 'git clean -n' primero para ver qué se eliminaría.",
            )

        return True, ""

    def timeout_for(self, command: str) -> int:
        if command in _NETWORK:
            return 120   # operaciones de red necesitan más tiempo
        if command in _MODERATE:
            return 30
        return 10


class GitTool(BaseTool):
    name = "git"
    description = (
        "Ejecuta comandos git: status, log, diff, add, commit, push, pull, "
        "clone, branch, merge, rebase y más."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Subcomando git (status, add, commit, push...)",
            },
            "args": {
                "type": "string",
                "description": "Argumentos adicionales (opcional)",
            },
            "path": {
                "type": "string",
                "description": "Directorio del repositorio (opcional, default: CWD)",
            },
        },
        "required": ["command"],
    }

    def __init__(self, safeguard: PathSafeguard):
        self._safeguard = safeguard
        self._validator = GitValidator()

    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        try:
            command = kwargs.get("command", "").strip()
            args = kwargs.get("args", "").strip()
            path_str = kwargs.get("path", "")

            if not command:
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content="Debes especificar un subcomando git.",
                    is_error=True,
                )

            # Validar comando
            allowed, reason = self._validator.validate(command, args)
            if not allowed:
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=reason,
                    is_error=True,
                )

            # Resolver directorio de trabajo
            cwd: Path | None = None
            if path_str:
                cwd = self._safeguard.validate(path_str)
                if not cwd.exists():
                    return ToolResult(
                        tool_use_id=tool_use_id,
                        content=f"Directorio no encontrado: {cwd}",
                        is_error=True,
                    )

            # Construir comando
            cmd_parts = ["git", command]
            if args:
                cmd_parts.extend(shlex.split(args))

            timeout = self._validator.timeout_for(command)

            # Ejecutar
            proc = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd) if cwd else None,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=f"timeout: git {command} excedió {timeout}s",
                    is_error=True,
                )

            output = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")

            # git a veces pone output informativo en stderr (ej: clone)
            combined = output
            if err and proc.returncode != 0:
                combined = f"{output}\n[stderr]\n{err}".strip()
            elif err and not output:
                combined = err  # algunos comandos usan solo stderr

            # Truncar output largo
            if len(combined) > 8_000:
                combined = combined[:8_000] + "\n... [output truncado a 8KB]"

            if not combined.strip():
                combined = f"git {command}: completado sin output."

            return ToolResult(
                tool_use_id=tool_use_id,
                content=combined,
                is_error=proc.returncode != 0,
            )

        except PermissionError as e:
            return ToolResult(tool_use_id=tool_use_id, content=str(e), is_error=True)
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_use_id,
                content=f"Error ejecutando git: {e}",
                is_error=True,
            )
