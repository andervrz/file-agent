# agent/tools/archive_tool.py
"""
ArchiveTool — crea, extrae o lista archivos comprimidos (zip, tar.gz).

Usa archive_utils.py para operaciones de archivo (DRY con BackupTool).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from .archive_utils import (
    create_zip_archive,
    create_tar_archive,
    extract_zip_archive,
    extract_tar_archive,
    list_zip_contents,
    list_tar_contents,
    format_size,
)
from .base import BaseTool, PathSafeguard, ToolResult


class ArchiveTool(BaseTool):
    name = "archive"
    description = "Crea, extrae o lista archivos comprimidos (zip, tar.gz)."
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "extract", "list"],
                "description": "Acción a realizar",
            },
            "path": {
                "type": "string",
                "description": "Archivo o directorio fuente",
            },
            "destination": {
                "type": "string",
                "description": "Destino (opcional para create/extract)",
            },
            "format": {
                "type": "string",
                "enum": ["zip", "tar.gz", "tar"],
                "default": "zip",
                "description": "Formato (solo para action=create)",
            },
        },
        "required": ["action", "path"],
    }

    def __init__(self, safeguard: PathSafeguard):
        self._safeguard = safeguard

    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        try:
            action = kwargs.get("action", "").lower()
            path = self._safeguard.validate(kwargs["path"])
            dest_str = kwargs.get("destination", "")
            fmt = kwargs.get("format", "zip")

            destination = self._safeguard.validate(dest_str) if dest_str else None

            match action:
                case "create":
                    result = await self._handle_create(path, destination, fmt)
                case "extract":
                    result = await self._handle_extract(path, destination)
                case "list":
                    result = await self._handle_list(path)
                case _:
                    return ToolResult(
                        tool_use_id=tool_use_id,
                        content=f"Acción desconocida: {action}. Usa create, extract o list.",
                        is_error=True,
                    )

            return ToolResult(tool_use_id=tool_use_id, content=result)

        except PermissionError as e:
            return ToolResult(tool_use_id=tool_use_id, content=str(e), is_error=True)
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_use_id,
                content=f"Error en archive: {e}",
                is_error=True,
            )

    async def _handle_create(
        self, source: Path, dest: Path | None, fmt: str
    ) -> str:
        if not source.exists():
            raise FileNotFoundError(f"No existe: {source}")

        if dest is None:
            dest = source.parent / f"{source.name}.{fmt}"
        elif dest.is_dir():
            dest = dest / f"{source.name}.{fmt}"

        if fmt == "zip":
            size = await asyncio.to_thread(create_zip_archive, source, dest)
        else:
            mode = "w:gz" if fmt == "tar.gz" else "w"
            size = await asyncio.to_thread(create_tar_archive, source, dest, mode)

        return f"Archivo creado: {dest} ({format_size(size)})"

    async def _handle_extract(self, archive: Path, dest: Path | None) -> str:
        if not archive.exists():
            raise FileNotFoundError(f"No existe: {archive}")

        if dest is None:
            dest = archive.parent / archive.stem
        dest.mkdir(parents=True, exist_ok=True)

        name = archive.name.lower()

        if name.endswith(".zip"):
            count = await asyncio.to_thread(extract_zip_archive, archive, dest)
        elif name.endswith((".tar.gz", ".tgz", ".tar")):
            count = await asyncio.to_thread(extract_tar_archive, archive, dest)
        else:
            raise ValueError(f"Formato no reconocido: {archive.suffix}")

        return f"Extraídos {count} archivos en {dest}"

    async def _handle_list(self, archive: Path) -> str:
        if not archive.exists():
            raise FileNotFoundError(f"No existe: {archive}")

        name = archive.name.lower()
        lines: list[str] = [f"Contenido de {archive.name}:\n"]

        if name.endswith(".zip"):
            items = await asyncio.to_thread(list_zip_contents, archive)
            for filename, size in items:
                lines.append(f"  {filename:<50} {format_size(size)}")
        elif name.endswith((".tar.gz", ".tgz", ".tar")):
            items = await asyncio.to_thread(list_tar_contents, archive)
            for filename, size in items:
                lines.append(f"  {filename:<50} {format_size(size)}")
        else:
            raise ValueError(f"Formato no reconocido: {archive.suffix}")

        lines.append(f"\nTotal: {len(lines) - 2} elementos")
        if len(lines) > 52:
            lines = lines[:52] + ["... [lista truncada a 50 elementos]"]
        return "\n".join(lines)
