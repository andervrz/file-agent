# agent/tools/file_tools.py
import asyncio
import shutil
from pathlib import Path

from .base import BaseTool, PathSafeguard, ToolResult


class CreateFileTool(BaseTool):
    name = "create_file"
    description = "Crea un archivo con contenido. Crea directorios padre si no existen."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "overwrite": {"type": "boolean", "default": False},
        },
        "required": ["path", "content"],
    }

    def __init__(self, safeguard: PathSafeguard):
        self._safeguard = safeguard

    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        try:
            path = self._safeguard.validate(kwargs["path"])
            content = kwargs.get("content", "")
            overwrite = kwargs.get("overwrite", False)
            if path.exists() and not overwrite:
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=f"File already exists: {path}",
                    is_error=True,
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_text, content, encoding="utf-8")
            return ToolResult(tool_use_id=tool_use_id, content=f"File created: {path}")
        except PermissionError as e:
            return ToolResult(tool_use_id=tool_use_id, content=str(e), is_error=True)


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Lee el contenido de un archivo. Límite 50KB."
    input_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    def __init__(self, safeguard: PathSafeguard):
        self._safeguard = safeguard

    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        try:
            path = self._safeguard.validate(kwargs["path"])
            if not path.exists():
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=f"File not found: {path}",
                    is_error=True,
                )
            size = path.stat().st_size
            if size > 50 * 1024:
                content = await asyncio.to_thread(path.read_text, encoding="utf-8")
                content = content[:50_000] + "\n... [truncated at 50KB]"
            else:
                content = await asyncio.to_thread(path.read_text, encoding="utf-8")
            return ToolResult(tool_use_id=tool_use_id, content=content)
        except PermissionError as e:
            return ToolResult(tool_use_id=tool_use_id, content=str(e), is_error=True)


class ListDirectoryTool(BaseTool):
    name = "list_directory"
    description = "Lista contenido de un directorio con íconos y tamaños."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "show_hidden": {"type": "boolean", "default": False},
        },
        "required": ["path"],
    }

    def __init__(self, safeguard: PathSafeguard):
        self._safeguard = safeguard

    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        try:
            path = self._safeguard.validate(kwargs["path"])
            show_hidden = kwargs.get("show_hidden", False)
            if not path.exists():
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=f"Directory not found: {path}",
                    is_error=True,
                )
            if not path.is_dir():
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=f"Not a directory: {path}",
                    is_error=True,
                )
            lines: list[str] = []
            entries = sorted(
                path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())
            )
            for entry in entries:
                if not show_hidden and entry.name.startswith("."):
                    continue
                icon = "📁" if entry.is_dir() else "📄"
                size = f" ({entry.stat().st_size} bytes)" if entry.is_file() else ""
                lines.append(f"{icon} {entry.name}{size}")
            return ToolResult(
                tool_use_id=tool_use_id,
                content="\n".join(lines) if lines else "(empty directory)",
            )
        except PermissionError as e:
            return ToolResult(tool_use_id=tool_use_id, content=str(e), is_error=True)


class MoveFileTool(BaseTool):
    name = "move_file"
    description = "Mueve o renombra un archivo o directorio."
    input_schema = {
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "destination": {"type": "string"},
        },
        "required": ["source", "destination"],
    }

    def __init__(self, safeguard: PathSafeguard):
        self._safeguard = safeguard

    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        try:
            source = self._safeguard.validate(kwargs["source"])
            destination = self._safeguard.validate(kwargs["destination"])
            if not source.exists():
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=f"Source not found: {source}",
                    is_error=True,
                )
            await asyncio.to_thread(shutil.move, str(source), str(destination))
            return ToolResult(
                tool_use_id=tool_use_id,
                content=f"Moved: {source} → {destination}",
            )
        except PermissionError as e:
            return ToolResult(tool_use_id=tool_use_id, content=str(e), is_error=True)


class CopyFileTool(BaseTool):
    name = "copy_file"
    description = "Copia un archivo a otra ubicación. Preserva metadata."
    input_schema = {
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "destination": {"type": "string"},
        },
        "required": ["source", "destination"],
    }

    def __init__(self, safeguard: PathSafeguard):
        self._safeguard = safeguard

    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        try:
            source = self._safeguard.validate(kwargs["source"])
            destination = self._safeguard.validate(kwargs["destination"])
            if not source.exists():
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=f"Source not found: {source}",
                    is_error=True,
                )
            if source.is_dir():
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=f"Use move_file for directories: {source}",
                    is_error=True,
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.copy2, str(source), str(destination))
            return ToolResult(
                tool_use_id=tool_use_id,
                content=f"Copied: {source} → {destination}",
            )
        except PermissionError as e:
            return ToolResult(tool_use_id=tool_use_id, content=str(e), is_error=True)


class DeleteFileTool(BaseTool):
    name = "delete_file"
    description = "Elimina un archivo. Requiere confirmación."
    input_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    def __init__(self, safeguard: PathSafeguard):
        self._safeguard = safeguard

    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        try:
            path = self._safeguard.validate(kwargs["path"])
            if not path.exists():
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=f"File not found: {path}",
                    is_error=True,
                )
            if path.is_dir():
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=f"Is a directory, not a file: {path}",
                    is_error=True,
                )
            await asyncio.to_thread(path.unlink)
            return ToolResult(tool_use_id=tool_use_id, content=f"Deleted: {path}")
        except PermissionError as e:
            return ToolResult(tool_use_id=tool_use_id, content=str(e), is_error=True)


class CreateDirectoryTool(BaseTool):
    name = "create_directory"
    description = "Crea un directorio con subdirectorios si aplica."
    input_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    def __init__(self, safeguard: PathSafeguard):
        self._safeguard = safeguard

    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        try:
            path = self._safeguard.validate(kwargs["path"])
            await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)
            return ToolResult(
                tool_use_id=tool_use_id,
                content=f"Directory created: {path}",
            )
        except PermissionError as e:
            return ToolResult(tool_use_id=tool_use_id, content=str(e), is_error=True)


class SearchFilesTool(BaseTool):
    name = "search_files"
    description = "Busca archivos por patrón glob. Límite 50 resultados."
    input_schema = {
        "type": "object",
        "properties": {
            "directory": {"type": "string"},
            "pattern": {"type": "string"},
            "recursive": {"type": "boolean", "default": True},
        },
        "required": ["directory", "pattern"],
    }

    def __init__(self, safeguard: PathSafeguard):
        self._safeguard = safeguard

    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        try:
            directory = self._safeguard.validate(kwargs["directory"])
            pattern = kwargs["pattern"]
            recursive = kwargs.get("recursive", True)
            if not directory.exists():
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=f"Directory not found: {directory}",
                    is_error=True,
                )
            matches = (
                list(directory.rglob(pattern))
                if recursive
                else list(directory.glob(pattern))
            )
            matches = sorted(matches)[:50]
            lines = [str(m) for m in matches]
            return ToolResult(
                tool_use_id=tool_use_id,
                content="\n".join(lines) if lines else "No matches found.",
            )
        except PermissionError as e:
            return ToolResult(tool_use_id=tool_use_id, content=str(e), is_error=True)


def build_file_tools(safeguard: PathSafeguard, enabled: list[str]) -> list[BaseTool]:
    all_tools: list[BaseTool] = [
        CreateFileTool(safeguard),
        ReadFileTool(safeguard),
        ListDirectoryTool(safeguard),
        MoveFileTool(safeguard),
        CopyFileTool(safeguard),
        DeleteFileTool(safeguard),
        CreateDirectoryTool(safeguard),
        SearchFilesTool(safeguard),
    ]
    return [t for t in all_tools if t.name in enabled]