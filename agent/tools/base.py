# agent/tools/base.py
from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    tool_use_id: str = Field(..., description="ID del tool call del LLM")
    content: str = Field(..., description="Resultado de la ejecución")
    is_error: bool = False


class BaseTool(ABC):
    name: str
    description: str
    input_schema: dict

    @abstractmethod
    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        """Ejecuta el tool. Siempre retorna ToolResult, nunca lanza."""

    def to_ollama_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


class PathSafeguard:
    def __init__(self, blocked_paths: list[str]):
        self._blocked = [Path(p).resolve() for p in blocked_paths]

    def validate(self, path: str | Path) -> Path:
        target = Path(path).expanduser().resolve()
        for blocked in self._blocked:
            try:
                target.relative_to(blocked)
                raise PermissionError(f"Path blocked by security policy: {target}")
            except ValueError:
                continue
        return target