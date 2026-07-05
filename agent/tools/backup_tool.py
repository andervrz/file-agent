# agent/tools/backup_tool.py
"""
BackupTool — crea una copia de seguridad comprimida de un archivo o directorio.

Usa archive_utils.py para operaciones de archivo (DRY con ArchiveTool).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from .archive_utils import create_zip_archive, create_tar_archive, format_size
from .base import BaseTool, PathSafeguard, ToolResult


class BackupTool(BaseTool):
    name = "backup"
    description = "Crea una copia de seguridad comprimida de un archivo o directorio."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Archivo o directorio a respaldar",
            },
            "destination": {
                "type": "string",
                "description": "Directorio donde guardar el backup (opcional)",
            },
            "format": {
                "type": "string",
                "enum": ["zip", "tar.gz"],
                "default": "zip",
            },
        },
        "required": ["path"],
    }

    def __init__(self, safeguard: PathSafeguard):
        self._safeguard = safeguard

    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        try:
            source = self._safeguard.validate(kwargs["path"])
            fmt = kwargs.get("format", "zip")

            if not source.exists():
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=f"No existe: {source}",
                    is_error=True,
                )

            # Resolve destination
            dest_dir = source.parent
            if kwargs.get("destination"):
                dest_dir = self._safeguard.validate(kwargs["destination"])
                dest_dir.mkdir(parents=True, exist_ok=True)

            backup_name = _generate_name(source.name, fmt)
            backup_path = dest_dir / backup_name

            if fmt == "zip":
                size = await asyncio.to_thread(create_zip_archive, source, backup_path)
            else:
                size = await asyncio.to_thread(create_tar_archive, source, backup_path)

            return ToolResult(
                tool_use_id=tool_use_id,
                content=f"Backup creado: {backup_path} ({format_size(size)})",
            )
        except PermissionError as e:
            return ToolResult(tool_use_id=tool_use_id, content=str(e), is_error=True)
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_use_id,
                content=f"Error al crear backup: {e}",
                is_error=True,
            )


# ── Funciones auxiliares ───────────────────────────────────────────────────────

def _generate_name(basename: str, fmt: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{basename}_{ts}.{fmt}"
