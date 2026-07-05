# agent/tools/find_in_files_tool.py
from __future__ import annotations

import asyncio
from pathlib import Path

from .base import BaseTool, PathSafeguard, ToolResult

# FIX: agregadas extensiones web comunes faltantes (.php, .vue, .jsx, .tsx)
_TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml",
    ".toml", ".csv", ".html", ".css", ".xml", ".sh", ".env",
    ".cfg", ".ini", ".log", ".rst", ".sql", ".go", ".rs", ".rb",
    ".java", ".c", ".cpp", ".h", ".hpp", ".kt", ".swift",
    ".php", ".vue", ".jsx", ".tsx",  # ← FIX: agregados
}

_SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "node_modules",
    ".mypy_cache", "dist", "build", ".pytest_cache",
}


class FindInFilesTool(BaseTool):
    name = "find_in_files"
    description = "Busca texto dentro de archivos en un directorio."
    input_schema = {
        "type": "object",
        "properties": {
            "directory": {"type": "string", "description": "Directorio donde buscar"},
            "pattern": {"type": "string", "description": "Texto a buscar"},
            "file_pattern": {
                "type": "string",
                "default": "*",
                "description": 'Filtro de archivos, ej: "*.py"',
            },
            "recursive": {"type": "boolean", "default": True},
            "case_sensitive": {"type": "boolean", "default": False},
            "max_results": {"type": "integer", "default": 50},
        },
        "required": ["directory", "pattern"],
    }

    def __init__(self, safeguard: PathSafeguard):
        self._safeguard = safeguard

    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        try:
            directory = self._safeguard.validate(kwargs["directory"])
            pattern = kwargs.get("pattern", "")
            file_pattern = kwargs.get("file_pattern", "*")
            recursive = kwargs.get("recursive", True)
            case_sensitive = kwargs.get("case_sensitive", False)
            max_results = int(kwargs.get("max_results", 50))

            if not directory.exists():
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=f"Directorio no encontrado: {directory}",
                    is_error=True,
                )

            if not pattern:
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content="Debes especificar un texto a buscar.",
                    is_error=True,
                )

            matches, files_with_match, files_checked = await asyncio.to_thread(
                _search,
                directory,
                pattern,
                file_pattern,
                recursive,
                case_sensitive,
                max_results,
            )

            if not matches:
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=(
                        f"No se encontró '{pattern}' en {files_checked} archivos revisados."
                    ),
                )

            header = (
                f"{len(matches)} coincidencias en {files_with_match} archivos "
                f"({files_checked} revisados):\n\n"
            )
            output = header + "\n".join(matches)

            if len(output) > 8_000:
                output = output[:8_000] + "\n... [resultados truncados]"

            return ToolResult(tool_use_id=tool_use_id, content=output)

        except PermissionError as e:
            return ToolResult(tool_use_id=tool_use_id, content=str(e), is_error=True)
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_use_id,
                content=f"Error en búsqueda: {e}",
                is_error=True,
            )


# ── Funciones auxiliares ───────────────────────────────────────────────────────

def _search(
    directory: Path,
    pattern: str,
    file_pattern: str,
    recursive: bool,
    case_sensitive: bool,
    max_results: int,
) -> tuple[list[str], int, int]:
    search_fn = directory.rglob if recursive else directory.glob
    needle = pattern if case_sensitive else pattern.lower()

    matches: list[str] = []
    files_with_match = 0
    files_checked = 0

    for file_path in search_fn(file_pattern):
        if not file_path.is_file():
            continue

        # Saltar directorios excluidos
        if any(part in _SKIP_DIRS for part in file_path.parts):
            continue

        # Solo archivos de texto
        if file_pattern == "*" and file_path.suffix.lower() not in _TEXT_EXTENSIONS:
            continue

        files_checked += 1
        file_matches: list[str] = []

        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for line_num, line in enumerate(text.splitlines(), start=1):
            haystack = line if case_sensitive else line.lower()
            if needle in haystack:
                # Formato: ruta/archivo.py:42: contenido
                short_path = str(file_path)
                file_matches.append(f"{short_path}:{line_num}: {line.strip()[:120]}")
                if len(matches) + len(file_matches) >= max_results:
                    break

        if file_matches:
            files_with_match += 1
            matches.extend(file_matches)

        if len(matches) >= max_results:
            break

    return matches, files_with_match, files_checked
