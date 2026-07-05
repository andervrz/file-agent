# agent/tools/registry.py
from .base import BaseTool, ToolResult


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get_schemas(self) -> list[dict]:
        return [tool.to_ollama_schema() for tool in self._tools.values()]

    async def execute(self, name: str, tool_use_id: str, **kwargs) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=name,
                content=f"Tool not found: {name}",
                is_error=True,
            )
        try:
            result = await tool.execute(tool_use_id=tool_use_id, **kwargs)
            # FIX: inyectar tool_name si el tool no lo puso
            if not result.tool_name:
                result = result.model_copy(update={"tool_name": name})
            return result
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=name,
                content=f"Execution error: {e}",
                is_error=True,
            )