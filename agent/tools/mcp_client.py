# agent/tools/mcp_client.py
"""
MCPClientAdapter — conecta el file-agent a cualquier servidor MCP remoto o local.

Transportes soportados:
  - stdio            (recomendado para Context7 — evita el bug GET 405 del SDK)
  - streamable-http  (stateless, para Tavily, etc.)
  - sse              (legacy, algunos servidores locales)

Flujo:
  1. MCPClientAdapter.load_tools()  → abre sesión MCP, llama list_tools(),
                                       instancia un MCPProxyTool por cada tool.
  2. Los MCPProxyTool se registran en el ToolRegistry igual que cualquier BaseTool.
  3. Cada llamada a MCPProxyTool.execute() abre una sesión MCP efímera,
     ejecuta el tool y retorna el resultado como ToolResult.

Configuración en agent.yaml (ejemplos):

  # ── Context7 vía stdio (RECOMENDADO) ──────────────────────────────────────
  - name: "context7"
    command: "npx"
    args: ["-y", "@upstash/context7-mcp", "--api-key", "YOUR_API_KEY"]
    transport: "stdio"
    enabled: true

  # ── Context7 vía stdio con API key desde .env ─────────────────────────────
  - name: "context7"
    command: "npx"
    args: ["-y", "@upstash/context7-mcp"]
    api_key_env: "CONTEXT7_API_KEY"      # se inyecta como --api-key $VALUE
    transport: "stdio"
    enabled: true

  # ── Tavily vía streamable-http ────────────────────────────────────────────
  - name: "tavily"
    url: "https://mcp.tavily.com/mcp/"
    api_key_env: "TAVILY_API_KEY"
    api_key_param: "tavilyApiKey"
    transport: "streamable-http"
    enabled: true

  # ── Context7 remoto (NO recomendado — bug GET 405 del SDK) ───────────────
  - name: "context7"
    url: "https://mcp.context7.com/mcp"
    api_key_env: "CONTEXT7_API_KEY"
    api_key_header: "CONTEXT7_API_KEY"
    transport: "streamable-http"
    enabled: false
"""
from __future__ import annotations

import asyncio
import logging
import os
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

from .base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Máximo de caracteres del contenido de respuesta MCP que se envía al LLM
_MAX_CONTENT = 8_000


def _resolve_api_key(cfg: dict) -> str:
    """
    Resuelve la API key desde .env (os.environ).
    Orden de prioridad:
      1. api_key_env  → lee os.environ[valor]
      2. Valor literal en 'api_key' (si está en el YAML)
      3. Cadena vacía (tier gratuito / sin auth)
    """
    env_var = cfg.get("api_key_env", "")
    if env_var:
        key = os.environ.get(env_var, "")
        if key:
            return key
        logger.warning(
            "MCP server '%s': variable de entorno '%s' no definida",
            cfg.get("name", "?"), env_var,
        )
    return cfg.get("api_key", "")


def _build_stdio_args(cfg: dict) -> list[str]:
    """
    Construye los args para stdio. Si hay api_key_env y el comando es
    @upstash/context7-mcp, inyecta --api-key automáticamente si no está ya.
    """
    args = list(cfg.get("args", []))
    key = _resolve_api_key(cfg)
    cmd = cfg.get("command", "")

    if key and "--api-key" not in args:
        # Heurística: si el comando es npx/bunx/deno y el paquete es context7,
        # añadimos --api-key al final.
        if "context7-mcp" in " ".join(args) or "context7" in cmd:
            args.extend(["--api-key", key])

    return args


def _build_url(base_url: str, api_key: str, api_key_param: str) -> str:
    """
    Agrega el API key como query parameter si está configurado.
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
    y cierra la sesión.
    """

    def __init__(
        self,
        tool_name: str,
        tool_description: str,
        tool_input_schema: dict,
        server_url: str = "",
        headers: dict[str, str] | None = None,
        transport: str = "streamable-http",
        command: str = "",
        args: list[str] | None = None,
    ) -> None:
        self._name            = tool_name
        self._description     = tool_description
        self._input_schema    = tool_input_schema
        self._server_url      = server_url
        self._headers         = headers or {}
        self._transport       = transport
        self._command         = command
        self._args            = args or []

    # BaseTool protocol
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
        except ImportError as ie:
            logger.error("SDK MCP no instalado: %s", ie)
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
        if self._transport == "stdio":
            return await self._call_stdio(arguments)
        if self._transport == "streamable-http":
            return await self._call_streamable_http(arguments)
        return await self._call_sse(arguments)

    # ── stdio ────────────────────────────────────────────────────────────────
    async def _call_stdio(self, arguments: dict) -> str:
        from mcp.client.stdio import stdio_client, StdioServerParameters
        from mcp import ClientSession

        params = StdioServerParameters(
            command=self._command,
            args=self._args,
            env=None,
        )
        async with stdio_client(params) as (read_stream, write_stream):
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

    # ── streamable-http ────────────────────────────────────────────────────────
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

    # ── sse ────────────────────────────────────────────────────────────────────
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
    Descubre los tools de un servidor MCP remoto o local y los convierte a BaseTool.

    Parámetros (todos opcionales según transporte):
    ----------
    name           : Nombre identificador del servidor (ej. "tavily", "context7")
    url            : URL base del servidor MCP (para http/sse)
    command        : Comando a ejecutar (para stdio, ej. "npx")
    args           : Argumentos del comando (para stdio)
    api_key        : API key literal (no recomendado, usa api_key_env)
    api_key_param  : Nombre del query param donde va la key (ej. "tavilyApiKey")
    api_key_header : Nombre del header HTTP donde va la key (ej. "CONTEXT7_API_KEY")
    headers        : Headers HTTP adicionales
    transport      : "stdio" | "streamable-http" (default) | "sse"
    """

    def __init__(
        self,
        name: str,
        url: str = "",
        command: str = "",
        args: list[str] | None = None,
        api_key: str = "",
        api_key_param: str = "",
        api_key_header: str = "",
        headers: dict[str, str] | None = None,
        transport: str = "streamable-http",
    ) -> None:
        self._name      = name
        self._transport = transport

        # stdio config
        self._command   = command
        self._args      = args or []

        # HTTP config
        self._url = _build_url(url, api_key, api_key_param)
        self._headers: dict[str, str] = headers or {}
        if api_key:
            if api_key_header:
                self._headers.setdefault(api_key_header, api_key)
            elif not api_key_param:
                self._headers.setdefault("Authorization", f"Bearer {api_key}")

    # ── Factory desde dict (agent.yaml) ──────────────────────────────────────
    @classmethod
    def from_config(cls, cfg: dict) -> "MCPClientAdapter":
        """
        Crea un adapter desde un dict de configuración (agent.yaml).
        Resuelve automáticamente la API key desde .env / os.environ.
        """
        transport = cfg.get("transport", "streamable-http")
        key = _resolve_api_key(cfg)

        # stdio: construir args con key inyectada si aplica
        if transport == "stdio":
            cmd = cfg.get("command", "")
            raw_args = list(cfg.get("args", []))
            # Si la key viene de env y no está en args, inyectarla
            if key and "--api-key" not in raw_args:
                if "context7-mcp" in " ".join(raw_args) or "context7" in cmd:
                    raw_args.extend(["--api-key", key])
            return cls(
                name=cfg["name"],
                command=cmd,
                args=raw_args,
                transport="stdio",
            )

        # http / sse
        return cls(
            name=cfg["name"],
            url=cfg.get("url", ""),
            api_key=key,
            api_key_param=cfg.get("api_key_param", ""),
            api_key_header=cfg.get("api_key_header", ""),
            headers=cfg.get("headers"),
            transport=transport,
        )

    async def load_tools(self) -> list[MCPProxyTool]:
        """
        Conecta al servidor MCP, descubre los tools disponibles y
        retorna una lista de MCPProxyTool listos para registrar.
        """
        try:
            tools = await self._discover_tools()
            logger.info(
                "MCP server '%s': %d tool(s) cargados → %s",
                self._name, len(tools), [t.name for t in tools],
            )
            return tools
        except ImportError:
            logger.error("SDK MCP no instalado. Ejecuta: uv add 'mcp>=1.0.0,<2'")
            return []
        except Exception as e:
            logger.error("No se pudo conectar al servidor MCP '%s': %s", self._name, e)
            return []

    async def _discover_tools(self) -> list[MCPProxyTool]:
        if self._transport == "stdio":
            return await self._discover_stdio()
        if self._transport == "streamable-http":
            return await self._discover_streamable_http()
        return await self._discover_sse()

    # ── stdio discovery ──────────────────────────────────────────────────────
    async def _discover_stdio(self) -> list[MCPProxyTool]:
        from mcp.client.stdio import stdio_client, StdioServerParameters
        from mcp import ClientSession

        params = StdioServerParameters(
            command=self._command,
            args=self._args,
            env=None,
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                return self._build_proxies(tools_result.tools)

    # ── streamable-http discovery ────────────────────────────────────────────
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

    # ── sse discovery ────────────────────────────────────────────────────────
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
                    command=self._command,
                    args=self._args,
                )
            )
        return proxies
