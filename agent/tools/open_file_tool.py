# agent/tools/open_file_tool.py
"""
OpenFileTool — abre un archivo con la aplicación por defecto del sistema.

Usa xdg-open (Linux), open (macOS), o start (Windows).
Lanza el proceso de forma no-bloqueante: el agente no espera a que
la aplicación se cierre, solo confirma que el lanzamiento fue exitoso.

Requiere sesión gráfica activa (DISPLAY o WAYLAND_DISPLAY en el entorno).
"""
from __future__ import annotations

import asyncio
import os
import platform
import shutil
from pathlib import Path

from .base import BaseTool, PathSafeguard, ToolResult

# Extensiones que tienen sentido abrir gráficamente
_OPENABLE_EXTENSIONS: frozenset[str] = frozenset({
    # Documentos
    ".pdf", ".docx", ".doc", ".odt", ".rtf", ".txt", ".md",
    # Hojas de cálculo
    ".xlsx", ".xls", ".ods", ".csv",
    # Presentaciones
    ".pptx", ".ppt", ".odp",
    # Imágenes
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".tiff",
    # Audio / Video
    ".mp3", ".wav", ".ogg", ".flac", ".mp4", ".mkv", ".avi", ".mov",
    # Web
    ".html", ".htm",
    # Código / texto
    ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".toml", ".sh",
    # Archivos comprimidos
    ".zip", ".tar", ".gz",
})


def _get_opener_command(path: Path) -> list[str] | None:
    """
    Retorna el comando completo para abrir un archivo según el sistema operativo.

    Windows: start es un built-in de cmd, no un ejecutable.
             Se debe usar: cmd /c start "" "path"
    Linux:   xdg-open
    macOS:   open
    """
    system = platform.system()
    if system == "Linux":
        opener = shutil.which("xdg-open")
        if opener:
            return [opener, str(path)]
        return None
    if system == "Darwin":
        opener = shutil.which("open")
        if opener:
            return [opener, str(path)]
        return None
    if system == "Windows":
        # "start" es built-in de cmd.exe, no un ejecutable standalone.
        # cmd /c start "" "path" — el "" es el título de la ventana (requerido)
        return ["cmd", "/c", "start", "", str(path)]
    return None


def _has_display() -> bool:
    """Verifica si hay un display gráfico disponible."""
    return bool(
        os.environ.get("DISPLAY")
        or os.environ.get("WAYLAND_DISPLAY")
        or platform.system() in ("Darwin", "Windows")
    )


class OpenFileTool(BaseTool):
    name = "open_file"
    description = (
        "Abre un archivo con la aplicación por defecto del sistema operativo. "
        "Funciona con PDFs, documentos Word/Excel/PowerPoint, imágenes, "
        "videos, audio, HTML y más. Requiere sesión gráfica activa."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Ruta absoluta del archivo a abrir",
            },
        },
        "required": ["path"],
    }

    def __init__(self, safeguard: PathSafeguard):
        self._safeguard = safeguard

    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        try:
            path = self._safeguard.validate(kwargs["path"])

            # ── Validaciones previas ──────────────────────────────────────────

            if not path.exists():
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=f"Archivo no encontrado: {path}",
                    is_error=True,
                )

            if path.is_dir():
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=(
                        f"'{path.name}' es una carpeta, no un archivo. "
                        "Para abrir carpetas usa list_directory."
                    ),
                    is_error=True,
                )

            # Verificar que la extensión tiene sentido abrir gráficamente
            ext = path.suffix.lower()
            if ext and ext not in _OPENABLE_EXTENSIONS:
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=(
                        f"Extensión '{ext}' no está en la lista de tipos abribles. "
                        f"Tipos soportados: PDF, Word, Excel, PowerPoint, imágenes, "
                        f"video, audio, HTML, código fuente, archivos comprimidos."
                    ),
                    is_error=True,
                )

            # Verificar display gráfico
            if not _has_display():
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=(
                        "No hay sesión gráfica disponible (DISPLAY / WAYLAND_DISPLAY "
                        "no están definidos). El agente está corriendo en modo headless "
                        "o por SSH sin reenvío X11. No es posible abrir aplicaciones gráficas."
                    ),
                    is_error=True,
                )

            # Obtener comando de apertura
            cmd_parts = _get_opener_command(path)
            if not cmd_parts:
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=(
                        "No se encontró xdg-open en el sistema. "
                        "Instálalo con: sudo apt install xdg-utils"
                    ),
                    is_error=True,
                )

            # ── Lanzar proceso de forma no-bloqueante ─────────────────────────
            # start_new_session=True desacopla el proceso del agente:
            # si el agente termina, la app gráfica sigue abierta.

            proc = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )

            # Esperar solo 2 segundos para detectar error de lanzamiento inmediato.
            # xdg-open retorna rápido si falla, o casi al instante si tiene éxito.
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=2.0)
                err_text = stderr.decode("utf-8", errors="replace").strip() if stderr else ""

                if proc.returncode and proc.returncode != 0:
                    msg = err_text or f"xdg-open retornó código {proc.returncode}"
                    return ToolResult(
                        tool_use_id=tool_use_id,
                        content=f"Error al abrir '{path.name}': {msg}",
                        is_error=True,
                    )

            except asyncio.TimeoutError:
                # Timeout = el proceso sigue corriendo = apertura exitosa
                # (comportamiento normal de xdg-open cuando la app se abre)
                pass

            return ToolResult(
                tool_use_id=tool_use_id,
                content=(
                    f"✓ Abriendo '{path.name}' con la aplicación por defecto.\n"
                    f"Ruta: {path}"
                ),
            )

        except PermissionError as e:
            return ToolResult(
                tool_use_id=tool_use_id,
                content=str(e),
                is_error=True,
            )
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_use_id,
                content=f"Error inesperado al abrir archivo: {e}",
                is_error=True,
            )
