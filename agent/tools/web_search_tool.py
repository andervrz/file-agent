# agent/tools/web_search_tool.py
"""
WebSearchTool — búsqueda web en tiempo real via Tavily REST API.

Usa el SDK oficial tavily-python que llama directamente a la REST API
(https://api.tavily.com/search) — compatible con keys de tipo 'dev'
del plan gratuito (1000 requests/mes).

Acciones:
    search  → búsqueda web general
    extract → extraer contenido de una URL específica
    news    → búsqueda enfocada en noticias recientes
"""
from __future__ import annotations

import asyncio
import logging

from .base import BaseTool, PathSafeguard, ToolResult

logger = logging.getLogger(__name__)

_MAX_CONTENT = 6_000


# Importar excepciones de Tavily con fallback si no están disponibles
try:
    from tavily.errors import ForbiddenError, RateLimitError
except ImportError:
    ForbiddenError = Exception
    RateLimitError = Exception


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Búsqueda web en tiempo real. Obtiene información actualizada de internet: "
        "noticias, precios, resultados deportivos, documentación, cualquier consulta "
        "que requiera datos actuales. Más rápido que el navegador para obtener información."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "extract", "news"],
                "default": "search",
                "description": (
                    "search: búsqueda general | "
                    "extract: extraer contenido de una URL | "
                    "news: búsqueda de noticias recientes"
                ),
            },
            "query": {
                "type": "string",
                "description": "Consulta de búsqueda o URL (para action=extract)",
            },
            "max_results": {
                "type": "integer",
                "default": 5,
                "description": "Número de resultados (1-10, default 5)",
            },
        },
        "required": ["query"],
    }

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        action      = kwargs.get("action", "search")
        query       = kwargs.get("query", "").strip()
        max_results = int(kwargs.get("max_results", 5))

        if not query:
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=self.name,
                content="Debes especificar una consulta en el parámetro 'query'.",
                is_error=True,
            )

        try:
            from tavily import TavilyClient
        except ImportError:
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=self.name,
                content=(
                    "tavily-python no está instalado. Ejecuta:\n"
                    "  uv add tavily-python"
                ),
                is_error=True,
            )

        try:
            client = TavilyClient(api_key=self._api_key)

            match action:
                case "search":
                    result = await asyncio.to_thread(
                        client.search,
                        query,
                        max_results=max_results,
                        search_depth="basic",
                        include_answer=True,
                    )
                    return ToolResult(
                        tool_use_id=tool_use_id,
                        tool_name=self.name,
                        content=self._format_search(query, result),
                    )

                case "news":
                    result = await asyncio.to_thread(
                        client.search,
                        query,
                        max_results=max_results,
                        search_depth="basic",
                        topic="news",
                        include_answer=True,
                    )
                    return ToolResult(
                        tool_use_id=tool_use_id,
                        tool_name=self.name,
                        content=self._format_search(query, result, label="Noticias"),
                    )

                case "extract":
                    # FIX: Tavily extract espera urls como LISTA de strings, no string
                    result = await asyncio.to_thread(
                        client.extract,
                        urls=[query],
                    )
                    return ToolResult(
                        tool_use_id=tool_use_id,
                        tool_name=self.name,
                        content=self._format_extract(query, result),
                    )

                case _:
                    return ToolResult(
                        tool_use_id=tool_use_id,
                        tool_name=self.name,
                        content=f"Acción desconocida: '{action}'. Usa: search, news, extract.",
                        is_error=True,
                    )

        except ForbiddenError:
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=self.name,
                content=(
                    "🔑 API key de Tavily inválida o sin permisos.\n\n"
                    "Pasos para solucionar:\n"
                    "1. Registrate en https://tavily.com\n"
                    "2. Generá una API key (plan gratuito: 1000 búsquedas/mes)\n"
                    "3. Agregá TAVILY_API_KEY=tvly-... a tu archivo .env\n"
                    "4. Reiniciá el agente\n\n"
                    "Nota: las keys 'dev' no funcionan con búsqueda directa."
                ),
                is_error=True,
            )

        except RateLimitError:
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=self.name,
                content="⏳ Límite de requests de Tavily alcanzado. Intentá en unos minutos.",
                is_error=True,
            )

        except Exception as e:
            logger.exception("WebSearchTool error")
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=self.name,
                content=f"Error en búsqueda web: {e}",
                is_error=True,
            )

    # ── Formatters ────────────────────────────────────────────────────────────

    def _format_search(self, query: str, result: dict, label: str = "Búsqueda") -> str:
        lines = [f"🔍 {label}: '{query}'\n"]

        # Respuesta directa de Tavily si está disponible
        answer = result.get("answer")
        if answer:
            lines.append(f"**Respuesta directa:** {answer}\n")

        # Resultados individuales
        results = result.get("results", [])
        for i, r in enumerate(results, 1):
            title   = r.get("title", "Sin título")
            url     = r.get("url", "")
            content = r.get("content", "")[:300]
            score   = r.get("score", 0)
            lines.append(f"{i}. **{title}**")
            lines.append(f"   {url}")
            if content:
                lines.append(f"   {content}")
            lines.append("")

        output = "\n".join(lines)
        if len(output) > _MAX_CONTENT:
            output = output[:_MAX_CONTENT] + "\n... [truncado]"
        return output

    def _format_extract(self, url: str, result: dict) -> str:
        lines = [f"📄 Extracción de: {url}\n"]
        results = result.get("results", [])
        for r in results:
            raw_content = r.get("raw_content") or r.get("content", "")
            if raw_content:
                lines.append(raw_content[:_MAX_CONTENT])
        failed = result.get("failed_results", [])
        if failed:
            lines.append(f"\n⚠ URLs fallidas: {failed}")
        output = "\n".join(lines)
        if len(output) > _MAX_CONTENT:
            output = output[:_MAX_CONTENT] + "\n... [truncado]"
        return output
