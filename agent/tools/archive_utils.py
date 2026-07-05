# agent/tools/archive_utils.py
"""
Utilidades compartidas para operaciones de archivo comprimido.

Extraído de backup_tool.py y archive_tool.py para eliminar duplicación (DRY).
"""
from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path


# ─── Constantes compartidas ──────────────────────────────────────────────────

_EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".mypy_cache"}
_EXCLUDE_EXTS = {".pyc", ".pyo"}


# ─── Funciones públicas ──────────────────────────────────────────────────────

def should_exclude(path: Path) -> bool:
    """Determina si un archivo o directorio debe excluirse del backup/archivo."""
    return path.name in _EXCLUDE_DIRS or path.suffix in _EXCLUDE_EXTS


def should_exclude_path(path: Path) -> bool:
    """Verifica si alguna parte del path está en exclusiones."""
    return any(should_exclude(p) for p in path.parents) or should_exclude(path)


def format_size(n: int) -> str:
    """Formatea tamaño en bytes a unidad legible."""
    if n < 1024:
        return f"{n}B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f}KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f}MB"
    return f"{n / 1024 ** 3:.1f}GB"


def create_zip_archive(
    source: Path,
    dest: Path,
    exclude_fn: callable = should_exclude_path,
) -> int:
    """
    Crea un archivo ZIP desde source (archivo o directorio).

    Returns: tamaño en bytes del archivo creado.
    """
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        if source.is_file():
            zf.write(source, source.name)
        else:
            for item in source.rglob("*"):
                if exclude_fn(item):
                    continue
                zf.write(item, item.relative_to(source.parent))
    return dest.stat().st_size


def create_tar_archive(
    source: Path,
    dest: Path,
    mode: str = "w:gz",
    exclude_fn: callable = should_exclude_path,
) -> int:
    """
    Crea un archivo TAR desde source (archivo o directorio).

    Args:
        mode: "w:gz" para tar.gz, "w" para tar plano, "w:bz2" para bz2

    Returns: tamaño en bytes del archivo creado.
    """
    with tarfile.open(dest, mode) as tf:
        if source.is_file():
            tf.add(source, arcname=source.name)
        else:
            for item in source.rglob("*"):
                if exclude_fn(item):
                    continue
                tf.add(item, arcname=item.relative_to(source.parent))
    return dest.stat().st_size


def extract_zip_archive(archive: Path, dest: Path) -> int:
    """
    Extrae un archivo ZIP a dest.

    Returns: número de archivos extraídos.
    """
    with zipfile.ZipFile(archive, "r") as zf:
        # Zip slip protection
        for member in zf.namelist():
            member_path = (dest / member).resolve()
            if not str(member_path).startswith(str(dest.resolve())):
                raise ValueError(f"Zip slip detectado: {member}")
        zf.extractall(dest)
        return len(zf.namelist())


def extract_tar_archive(archive: Path, dest: Path) -> int:
    """
    Extrae un archivo TAR/TAR.GZ/TGZ a dest.

    Returns: número de archivos extraídos.
    """
    with tarfile.open(archive, "r:*") as tf:
        # Tar slip protection
        for member in tf.getmembers():
            member_path = (dest / member.name).resolve()
            if not str(member_path).startswith(str(dest.resolve())):
                raise ValueError(f"Tar slip detectado: {member.name}")
        tf.extractall(dest)
        return len(tf.getmembers())


def list_zip_contents(archive: Path) -> list[tuple[str, int]]:
    """
    Lista contenido de un ZIP.

    Returns: lista de (nombre, tamaño_bytes).
    """
    with zipfile.ZipFile(archive, "r") as zf:
        return [(info.filename, info.file_size) for info in zf.infolist()]


def list_tar_contents(archive: Path) -> list[tuple[str, int]]:
    """
    Lista contenido de un TAR.

    Returns: lista de (nombre, tamaño_bytes).
    """
    with tarfile.open(archive, "r:*") as tf:
        return [(member.name, member.size) for member in tf.getmembers()]
