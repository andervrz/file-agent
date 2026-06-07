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
                content=f"Tool not found: {name}",
                is_error=True,
            )
        try:
            return await tool.execute(tool_use_id=tool_use_id, **kwargs)
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_use_id,
                content=f"Execution error: {e}",
                is_error=True,
            )