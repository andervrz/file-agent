# agent/tools/archive_tool.py
from __future__ import annotations

import asyncio
import tarfile
import zipfile
from pathlib import Path

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
                    result = await asyncio.to_thread(
                        _create_archive, path, destination, fmt
                    )
                case "extract":
                    result = await asyncio.to_thread(
                        _extract_archive, path, destination
                    )
                case "list":
                    result = await asyncio.to_thread(_list_archive, path)
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


# ── Funciones auxiliares ───────────────────────────────────────────────────────

def _create_archive(source: Path, dest: Path | None, fmt: str) -> str:
    if not source.exists():
        raise FileNotFoundError(f"No existe: {source}")

    if dest is None:
        dest = source.parent / f"{source.name}.{fmt}"
    elif dest.is_dir():
        dest = dest / f"{source.name}.{fmt}"

    if fmt == "zip":
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            if source.is_file():
                zf.write(source, source.name)
            else:
                for item in source.rglob("*"):
                    zf.write(item, item.relative_to(source.parent))
    else:
        mode = "w:gz" if fmt == "tar.gz" else "w"
        with tarfile.open(dest, mode) as tf:
            tf.add(source, arcname=source.name)

    size = dest.stat().st_size
    return f"Archivo creado: {dest} ({_fmt_size(size)})"


def _extract_archive(archive: Path, dest: Path | None) -> str:
    if not archive.exists():
        raise FileNotFoundError(f"No existe: {archive}")

    if dest is None:
        dest = archive.parent / archive.stem
    dest.mkdir(parents=True, exist_ok=True)

    name = archive.name.lower()

    if name.endswith(".zip"):
        with zipfile.ZipFile(archive, "r") as zf:
            # Zip slip protection
            for member in zf.namelist():
                member_path = (dest / member).resolve()
                if not str(member_path).startswith(str(dest.resolve())):
                    raise ValueError(f"Zip slip detectado: {member}")
            zf.extractall(dest)
            count = len(zf.namelist())
    elif name.endswith((".tar.gz", ".tgz", ".tar")):
        with tarfile.open(archive, "r:*") as tf:
            # Tar slip protection
            for member in tf.getmembers():
                member_path = (dest / member.name).resolve()
                if not str(member_path).startswith(str(dest.resolve())):
                    raise ValueError(f"Tar slip detectado: {member.name}")
            tf.extractall(dest)
            count = len(tf.getmembers())
    else:
        raise ValueError(f"Formato no reconocido: {archive.suffix}")

    return f"Extraídos {count} archivos en {dest}"


def _list_archive(archive: Path) -> str:
    if not archive.exists():
        raise FileNotFoundError(f"No existe: {archive}")

    name = archive.name.lower()
    lines: list[str] = [f"Contenido de {archive.name}:\n"]

    if name.endswith(".zip"):
        with zipfile.ZipFile(archive, "r") as zf:
            for info in zf.infolist():
                size = _fmt_size(info.file_size)
                lines.append(f"  {info.filename:<50} {size}")
    elif name.endswith((".tar.gz", ".tgz", ".tar")):
        with tarfile.open(archive, "r:*") as tf:
            for member in tf.getmembers():
                size = _fmt_size(member.size)
                lines.append(f"  {member.name:<50} {size}")
    else:
        raise ValueError(f"Formato no reconocido: {archive.suffix}")

    lines.append(f"\nTotal: {len(lines) - 2} elementos")
    if len(lines) > 52:
        lines = lines[:52] + ["... [lista truncada a 50 elementos]"]
    return "\n".join(lines)


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f}KB"
    return f"{n / 1024 ** 2:.1f}MB"
