# agent/tools/diff_tool.py
from __future__ import annotations

import asyncio
import difflib
from pathlib import Path

from .base import BaseTool, PathSafeguard, ToolResult


class DiffFilesTool(BaseTool):
    name = "diff_files"
    description = "Compara dos archivos de texto y muestra sus diferencias."
    input_schema = {
        "type": "object",
        "properties": {
            "file1": {"type": "string", "description": "Primer archivo"},
            "file2": {"type": "string", "description": "Segundo archivo"},
            "context_lines": {
                "type": "integer",
                "default": 3,
                "description": "Líneas de contexto alrededor de cada cambio",
            },
        },
        "required": ["file1", "file2"],
    }

    def __init__(self, safeguard: PathSafeguard):
        self._safeguard = safeguard

    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        try:
            file1 = self._safeguard.validate(kwargs["file1"])
            file2 = self._safeguard.validate(kwargs["file2"])
            context = int(kwargs.get("context_lines", 3))

            for f in (file1, file2):
                if not f.exists():
                    return ToolResult(
                        tool_use_id=tool_use_id,
                        content=f"Archivo no encontrado: {f}",
                        is_error=True,
                    )
                if f.stat().st_size > 5 * 1024 * 1024:
                    return ToolResult(
                        tool_use_id=tool_use_id,
                        content=f"Archivo demasiado grande para diff (máx 5MB): {f.name}",
                        is_error=True,
                    )

            result = await asyncio.to_thread(_compute_diff, file1, file2, context)
            return ToolResult(tool_use_id=tool_use_id, content=result)

        except PermissionError as e:
            return ToolResult(tool_use_id=tool_use_id, content=str(e), is_error=True)
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_use_id,
                content=f"Error al comparar archivos: {e}",
                is_error=True,
            )


# ── Funciones auxiliares ───────────────────────────────────────────────────────

def _compute_diff(file1: Path, file2: Path, context: int) -> str:
    lines1 = file1.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    lines2 = file2.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)

    diff = list(
        difflib.unified_diff(
            lines1,
            lines2,
            fromfile=str(file1),
            tofile=str(file2),
            n=context,
        )
    )

    if not diff:
        return f"Los archivos son idénticos: {file1.name} y {file2.name}"

    # Resumen
    added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

    output = "".join(diff)
    if len(output) > 5_000:
        output = output[:5_000] + "\n... [diff truncado a 5KB]"

    summary = f"\n— {added} líneas añadidas, {removed} eliminadas —"
    return output + summary
