# agent/tools/backup_tool.py
from __future__ import annotations

import asyncio
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .base import BaseTool, PathSafeguard, ToolResult

_EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".mypy_cache"}
_EXCLUDE_EXTS = {".pyc", ".pyo"}


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

            size = await asyncio.to_thread(
                _create_backup, source, backup_path, fmt
            )
            return ToolResult(
                tool_use_id=tool_use_id,
                content=f"Backup creado: {backup_path} ({_format_size(size)})",
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


def _should_exclude(path: Path) -> bool:
    return path.name in _EXCLUDE_DIRS or path.suffix in _EXCLUDE_EXTS


def _create_backup(source: Path, dest: Path, fmt: str) -> int:
    if fmt == "zip":
        return _create_zip(source, dest)
    return _create_targz(source, dest)


def _create_zip(source: Path, dest: Path) -> int:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        if source.is_file():
            zf.write(source, source.name)
        else:
            for item in source.rglob("*"):
                if any(_should_exclude(p) for p in item.parents) or _should_exclude(item):
                    continue
                zf.write(item, item.relative_to(source.parent))
    return dest.stat().st_size


def _create_targz(source: Path, dest: Path) -> int:
    with tarfile.open(dest, "w:gz") as tf:
        if source.is_file():
            tf.add(source, arcname=source.name)
        else:
            for item in source.rglob("*"):
                if any(_should_exclude(p) for p in item.parents) or _should_exclude(item):
                    continue
                tf.add(item, arcname=item.relative_to(source.parent))
    return dest.stat().st_size


def _format_size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f}KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f}MB"
    return f"{n / 1024 ** 3:.1f}GB"
