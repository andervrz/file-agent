# agent/tools/mcp_client.py
"""
MCPClientAdapter — conecta el file-agent a cualquier servidor MCP remoto.

Flujo:
  1. MCPClientAdapter.load_tools()  → abre sesión MCP, llama list_tools(),
                                       instancia un MCPProxyTool por cada tool.
  2. Los MCPProxyTool se registran en el ToolRegistry igual que cualquier BaseTool.
  3. Cada llamada a MCPProxyTool.execute() abre una sesión efímera al servidor MCP,
     ejecuta el tool y retorna el resultado como ToolResult.

Transportes soportados:
  - Streamable HTTP  (producción, recomendado — Tavily, etc.)
  - SSE              (legacy, algunos servidores locales)

Ejemplo de uso con Tavily:
    adapter = MCPClientAdapter(
        name="tavily",
        url="https://mcp.tavily.com/mcp/",
        api_key="tvly-...",
        api_key_param="tavilyApiKey",   # key va en el query param de la URL
    )
    tools = await adapter.load_tools()
    for tool in tools:
        registry.register(tool)
"""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

from .base import BaseTool, PathSafeguard, ToolResult

logger = logging.getLogger(__name__)

# Máximo de caracteres del contenido de respuesta MCP que se envía al LLM
_MAX_CONTENT = 8_000


def _build_url(base_url: str, api_key: str, api_key_param: str) -> str:
    """
    Agrega el API key como query parameter si está configurado.

    "https://mcp.tavily.com/mcp/" + key="tvly-X" + param="tavilyApiKey"
    → "https://mcp.tavily.com/mcp/?tavilyApiKey=tvly-X"
    """
    if not api_key or not api_key_param:
        return base_url
    parsed = urlparse(base_url)
    existing = parse_qs(parsed.query)
    existing[api_key_param] = [api_key]
    new_query = urlencode({k: v[0] for k, v in existing.items()})
    return urlunparse(parsed._replace(query=new_query))


def _extract_text(content_blocks: list) -> str:
    """Extrae texto de los content blocks que retorna el MCP SDK."""
    parts: list[str] = []
    for block in content_blocks:
        if hasattr(block, "text"):
            parts.append(block.text)
        elif isinstance(block, dict) and "text" in block:
            parts.append(block["text"])
    return "\n".join(parts)


# ─── MCPProxyTool ─────────────────────────────────────────────────────────────

class MCPProxyTool(BaseTool):
    """
    Proxy que convierte un tool MCP descubierto en un BaseTool del file-agent.

    Cada execute() abre una sesión MCP efímera (stateless), llama al tool
    y cierra la sesión. Compatible con servidores Streamable HTTP stateless
    como Tavily.
    """

    def __init__(
        self,
        tool_name: str,
        tool_description: str,
        tool_input_schema: dict,
        server_url: str,
        headers: dict[str, str],
        transport: str = "streamable-http",
    ) -> None:
        self._name            = tool_name
        self._description     = tool_description
        self._input_schema    = tool_input_schema
        self._server_url      = server_url
        self._headers         = headers
        self._transport       = transport

    # BaseTool protocol — propiedades en lugar de class vars
    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict:
        return self._input_schema

    def to_ollama_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self._name,
                "description": self._description,
                "parameters": self._input_schema,
            },
        }

    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        try:
            result_text = await self._call_mcp(kwargs)
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=self._name,
                content=result_text,
            )
        except ImportError:
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=self._name,
                content=(
                    "El SDK de MCP no está instalado. Ejecuta:\n"
                    "  uv add 'mcp>=1.0.0,<2'"
                ),
                is_error=True,
            )
        except Exception as e:
            logger.exception("MCPProxyTool '%s' error", self._name)
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=self._name,
                content=f"Error en tool MCP '{self._name}': {e}",
                is_error=True,
            )

    async def _call_mcp(self, arguments: dict) -> str:
        """Abre sesión MCP efímera, llama el tool y retorna el texto."""
        if self._transport == "streamable-http":
            return await self._call_streamable_http(arguments)
        return await self._call_sse(arguments)

    async def _call_streamable_http(self, arguments: dict) -> str:
        from mcp.client.streamable_http import streamablehttp_client
        from mcp import ClientSession

        async with streamablehttp_client(
            self._server_url,
            headers=self._headers,
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(self._name, arguments)
                is_error = getattr(result, "isError", False)
                text = _extract_text(result.content)
                if not text:
                    text = "Tool ejecutado sin output."
                if len(text) > _MAX_CONTENT:
                    text = text[:_MAX_CONTENT] + f"\n... [truncado a {_MAX_CONTENT} chars]"
                if is_error:
                    raise RuntimeError(text)
                return text

    async def _call_sse(self, arguments: dict) -> str:
        from mcp.client.sse import sse_client
        from mcp import ClientSession

        async with sse_client(self._server_url, headers=self._headers) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                result = await session.call_tool(self._name, arguments)
                is_error = getattr(result, "isError", False)
                text = _extract_text(result.content)
                if is_error:
                    raise RuntimeError(text or "Error sin mensaje")
                return text or "Tool ejecutado sin output."


# ─── MCPClientAdapter ─────────────────────────────────────────────────────────

class MCPClientAdapter:
    """
    Descubre los tools de un servidor MCP remoto y los convierte a BaseTool.

    Parámetros
    ----------
    name           : Nombre identificador del servidor (ej. "tavily", "context7")
    url            : URL base del servidor MCP
    api_key        : API key (vacío si usa OAuth u otro método)
    api_key_param  : Nombre del query param donde va la key (ej. "tavilyApiKey")
                     Mutuamente excluyente con api_key_header.
    api_key_header : Nombre del header HTTP donde va la key (ej. "CONTEXT7_API_KEY")
                     Si ambos están vacíos con key presente → Authorization: Bearer
    headers        : Headers HTTP adicionales
    transport      : "streamable-http" (default) | "sse"
    """

    def __init__(
        self,
        name: str,
        url: str,
        api_key: str = "",
        api_key_param: str = "",
        api_key_header: str = "",
        headers: dict[str, str] | None = None,
        transport: str = "streamable-http",
    ) -> None:
        self._name      = name
        self._transport = transport

        # Construir URL final con API key en query param si aplica
        self._url = _build_url(url, api_key, api_key_param)

        # Headers base
        self._headers: dict[str, str] = headers or {}

        if api_key:
            if api_key_header:
                # Header personalizado (ej. Context7: CONTEXT7_API_KEY)
                self._headers.setdefault(api_key_header, api_key)
            elif not api_key_param:
                # Fallback: Authorization Bearer
                self._headers.setdefault("Authorization", f"Bearer {api_key}")

    async def load_tools(self) -> list[MCPProxyTool]:
        """
        Conecta al servidor MCP, descubre los tools disponibles y
        retorna una lista de MCPProxyTool listos para registrar.
        """
        try:
            tools = await self._discover_tools()
            logger.info(
                "MCP server '%s': %d tool(s) cargados → %s",
                self._name,
                len(tools),
                [t.name for t in tools],
            )
            return tools
        except ImportError:
            logger.error(
                "SDK MCP no instalado. Ejecuta: uv add 'mcp>=1.0.0,<2'"
            )
            return []
        except Exception as e:
            logger.error(
                "No se pudo conectar al servidor MCP '%s': %s",
                self._name, e,
            )
            return []

    async def _discover_tools(self) -> list[MCPProxyTool]:
        if self._transport == "streamable-http":
            return await self._discover_streamable_http()
        return await self._discover_sse()

    async def _discover_streamable_http(self) -> list[MCPProxyTool]:
        from mcp.client.streamable_http import streamablehttp_client
        from mcp import ClientSession

        async with streamablehttp_client(
            self._url,
            headers=self._headers,
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                return self._build_proxies(tools_result.tools)

    async def _discover_sse(self) -> list[MCPProxyTool]:
        from mcp.client.sse import sse_client
        from mcp import ClientSession

        async with sse_client(self._url, headers=self._headers) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                return self._build_proxies(tools_result.tools)

    def _build_proxies(self, mcp_tools: list) -> list[MCPProxyTool]:
        proxies: list[MCPProxyTool] = []
        for t in mcp_tools:
            schema = t.inputSchema or {"type": "object", "properties": {}}
            if isinstance(schema, dict) and "properties" not in schema:
                schema["properties"] = {}
            proxies.append(
                MCPProxyTool(
                    tool_name=t.name,
                    tool_description=t.description or "",
                    tool_input_schema=schema,
                    server_url=self._url,
                    headers=self._headers,
                    transport=self._transport,
                )
            )
        return proxies
