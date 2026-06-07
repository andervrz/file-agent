# agent/tools/pdf_tool.py
from __future__ import annotations

import asyncio
from pathlib import Path

from .base import BaseTool, PathSafeguard, ToolResult

_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


class ReadPDFTool(BaseTool):
    name = "read_pdf"
    description = "Lee y extrae el texto de un archivo PDF."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Ruta al archivo PDF",
            },
            "pages": {
                "type": "string",
                "description": '"all" | "1" | "1-5" | "2,4,6"',
                "default": "all",
            },
            "max_chars": {
                "type": "integer",
                "description": "Máximo de caracteres a retornar",
                "default": 5000,
            },
        },
        "required": ["path"],
    }

    def __init__(self, safeguard: PathSafeguard):
        self._safeguard = safeguard

    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        try:
            path = self._safeguard.validate(kwargs["path"])
            pages = kwargs.get("pages", "all")
            max_chars = int(kwargs.get("max_chars", 5000))

            if not path.exists():
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=f"Archivo no encontrado: {path}",
                    is_error=True,
                )

            if path.suffix.lower() != ".pdf":
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=f"El archivo no es un PDF: {path.name}",
                    is_error=True,
                )

            if path.stat().st_size > _MAX_FILE_SIZE:
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=f"PDF demasiado grande (máximo 50MB): {path.name}",
                    is_error=True,
                )

            text = await asyncio.to_thread(_extract_text, path, pages, max_chars)
            return ToolResult(tool_use_id=tool_use_id, content=text)

        except PermissionError as e:
            return ToolResult(tool_use_id=tool_use_id, content=str(e), is_error=True)
        except ImportError:
            return ToolResult(
                tool_use_id=tool_use_id,
                content="pypdf no está instalado. Ejecuta: uv add pypdf",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_use_id,
                content=f"Error al leer PDF: {e}",
                is_error=True,
            )


# ── Funciones auxiliares ───────────────────────────────────────────────────────

def _parse_pages(pages_str: str, total: int) -> list[int]:
    """Retorna lista de índices base-0."""
    s = pages_str.strip().lower()
    if s == "all":
        return list(range(total))
    indices: list[int] = []
    for part in s.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            indices.extend(range(int(start) - 1, int(end)))
        else:
            indices.append(int(part) - 1)
    return [i for i in indices if 0 <= i < total]


def _extract_text(path: Path, pages: str, max_chars: int) -> str:
    import pypdf  # importación lazy — no falla al cargar el módulo

    reader = pypdf.PdfReader(str(path))
    total = len(reader.pages)
    page_indices = _parse_pages(pages, total)

    parts: list[str] = [f"PDF: {path.name}  ({total} páginas)\n"]
    for i in page_indices:
        text = reader.pages[i].extract_text() or ""
        if text.strip():
            if len(page_indices) > 1:
                parts.append(f"\n--- Página {i + 1} ---\n")
            parts.append(text)

    combined = "".join(parts)

    if len(combined.strip()) <= len(parts[0]):
        return (
            f"PDF: {path.name} ({total} páginas)\n"
            "⚠️ No se pudo extraer texto. El PDF puede ser escaneado "
            "(imagen) y requiere OCR."
        )

    if len(combined) > max_chars:
        combined = combined[:max_chars] + f"\n... [truncado a {max_chars} chars]"

    return combined
