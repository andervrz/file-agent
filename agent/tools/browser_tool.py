# agent/tools/browser_tool.py
"""
BrowserTool — control del navegador web con Playwright.

El browser se inicializa lazy en el primer uso y se mantiene vivo
durante toda la sesión del agente. Una sola página activa a la vez.

Acciones disponibles:
    open        → navegar a URL o abrir archivo local (auto file://)
    search      → buscar en DuckDuckGo
    click       → hacer clic en un elemento por texto visible o selector CSS
    type        → escribir texto en el elemento activo o un selector
    read        → extraer texto visible de la página actual
    screenshot  → tomar captura de pantalla → ~/Pictures/screenshots/
    back        → ir a la página anterior
    forward     → ir a la página siguiente
    close       → cerrar el navegador y liberar recursos

Apertura de archivos locales (file://):
    El navegador puede renderizar de forma nativa:
    - PDFs        → visor integrado con zoom y búsqueda
    - Imágenes    → png, jpg, gif, svg, webp, bmp, ico
    - HTML        → renderizado completo
    - Video       → mp4, webm, ogv  (player HTML5)
    - Audio       → mp3, wav, ogg, flac (player HTML5)
    - Texto/Código → txt, json, xml, csv, py, md (texto formateado)

    Si se pasa una ruta absoluta en 'url', se convierte automáticamente
    a file:///ruta — no hace falta que el usuario recuerde la sintaxis.
"""
from __future__ import annotations

import asyncio
import os
import platform
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from .base import BaseTool, PathSafeguard, ToolResult

_MAX_PAGE_TEXT  = 6_000
_NAV_TIMEOUT    = 15_000
_SCREENSHOT_DIR = Path.home() / "Pictures" / "screenshots"

# Extensiones que el navegador renderiza de forma nativa (sin descarga)
_BROWSER_RENDERABLE: frozenset[str] = frozenset({
    # Documentos
    ".pdf",
    # Web
    ".html", ".htm", ".xhtml",
    # Imágenes
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico", ".avif",
    # Video (HTML5)
    ".mp4", ".webm", ".ogv",
    # Audio (HTML5)
    ".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a",
    # Texto / Código (mostrado como texto plano en el browser)
    ".txt", ".json", ".xml", ".csv", ".md", ".rst",
    ".py", ".js", ".ts", ".css", ".sh", ".yaml", ".yml", ".toml", ".ini",
})

# Extensiones que el navegador descarga en lugar de abrir — no tiene sentido
_BROWSER_DOWNLOADS: frozenset[str] = frozenset({
    ".docx", ".doc", ".odt",
    ".xlsx", ".xls", ".ods",
    ".pptx", ".ppt", ".odp",
    ".zip", ".tar", ".gz", ".tar.gz", ".rar", ".7z",
    ".exe", ".deb", ".rpm", ".dmg", ".iso",
})


def _has_display() -> bool:
    return bool(
        os.environ.get("DISPLAY")
        or os.environ.get("WAYLAND_DISPLAY")
        or platform.system() in ("Darwin", "Windows")
    )


def _to_url(raw: str) -> tuple[str, str | None]:
    """
    Convierte una ruta o URL a la URL final + mensaje de advertencia opcional.

    /home/user/doc.pdf      → file:///home/user/doc.pdf
    ~/Downloads/doc.pdf     → file:///home/user/Downloads/doc.pdf
    file:///ruta            → sin cambios
    https://example.com     → sin cambios
    example.com             → https://example.com
    """
    raw = raw.strip()

    # Ya es una URL completa
    if raw.startswith(("http://", "https://", "file://")):
        return raw, None

    # Ruta absoluta o relativa al home
    candidate = Path(raw).expanduser()
    if candidate.is_absolute() or raw.startswith("~"):
        resolved = candidate.resolve()
        ext = resolved.suffix.lower()

        if not resolved.exists():
            return f"file://{resolved}", f"⚠ Archivo no encontrado: {resolved}"

        if ext in _BROWSER_DOWNLOADS:
            return (
                f"file://{resolved}",
                f"⚠ '{ext}' no es renderizable en el navegador — "
                f"el navegador lo descargará. "
                f"Usa open_file para abrirlo con la aplicación correcta.",
            )

        if ext and ext not in _BROWSER_RENDERABLE:
            return (
                f"file://{resolved}",
                f"⚠ Extensión '{ext}' no reconocida — "
                f"el navegador puede descargarlo en lugar de mostrarlo.",
            )

        return f"file://{resolved}", None

    # Dominio sin esquema
    return f"https://{raw}", None


class BrowserTool(BaseTool):
    name = "browser"
    description = (
        "Controla el navegador web: navega a URLs o abre archivos locales "
        "(PDF, imágenes, HTML, video, audio, código), busca en internet, "
        "hace clic en elementos, escribe texto en formularios, lee el contenido "
        "de páginas y toma capturas de pantalla. "
        "Para abrir un archivo local pasa su ruta en 'url' — se convierte "
        "automáticamente a file:///ruta."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "open", "search", "click", "type",
                    "read", "screenshot", "back", "forward", "close",
                ],
                "description": (
                    "open: navegar a URL o abrir archivo local | "
                    "search: buscar en DuckDuckGo | "
                    "click: clic en elemento | "
                    "type: escribir texto | "
                    "read: leer contenido de la página | "
                    "screenshot: captura de pantalla | "
                    "back/forward: navegación | "
                    "close: cerrar navegador"
                ),
            },
            "url": {
                "type": "string",
                "description": (
                    "URL (https://...) o ruta local absoluta (/home/user/doc.pdf). "
                    "Las rutas locales se convierten automáticamente a file://. "
                    "Tipos abribles en el navegador: PDF, imágenes, HTML, "
                    "video MP4/WebM, audio MP3/WAV, texto, JSON, CSV, código fuente."
                ),
            },
            "query": {
                "type": "string",
                "description": "Texto de búsqueda (para action=search)",
            },
            "selector": {
                "type": "string",
                "description": (
                    "Texto visible o selector CSS del elemento "
                    "(para action=click y action=type). "
                    "Ejemplos: 'Iniciar sesión', '#submit', 'input[type=email]'"
                ),
            },
            "text": {
                "type": "string",
                "description": "Texto a escribir (para action=type)",
            },
            "headless": {
                "type": "boolean",
                "default": False,
                "description": "True = sin ventana visible (default: False)",
            },
        },
        "required": ["action"],
    }

    def __init__(self, safeguard: PathSafeguard):
        self._safeguard = safeguard
        self._playwright  = None
        self._browser     = None
        self._page        = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def _ensure_browser(self, headless: bool = False) -> str | None:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return (
                "Playwright no está instalado. Ejecuta:\n"
                "  uv add playwright\n"
                "  uv run playwright install chromium"
            )

        if not _has_display() and not headless:
            headless = True

        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = await self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                locale="es-ES",
            )
            self._page = await context.new_page()
            self._page.set_default_timeout(_NAV_TIMEOUT)

        return None

    async def _close_browser(self) -> None:
        if self._page:
            await self._page.close()
            self._page = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    # ── Execute ───────────────────────────────────────────────────────────────

    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        action   = kwargs.get("action", "").lower()
        headless = kwargs.get("headless", False)

        if action == "close":
            return await self._handle_close(tool_use_id)

        error = await self._ensure_browser(headless)
        if error:
            return ToolResult(tool_use_id=tool_use_id, content=error, is_error=True)

        try:
            match action:
                case "open":       return await self._handle_open(tool_use_id, kwargs)
                case "search":     return await self._handle_search(tool_use_id, kwargs)
                case "click":      return await self._handle_click(tool_use_id, kwargs)
                case "type":       return await self._handle_type(tool_use_id, kwargs)
                case "read":       return await self._handle_read(tool_use_id)
                case "screenshot": return await self._handle_screenshot(tool_use_id)
                case "back":       return await self._handle_back(tool_use_id)
                case "forward":    return await self._handle_forward(tool_use_id)
                case _:
                    return ToolResult(
                        tool_use_id=tool_use_id,
                        content=(
                            f"Acción desconocida: '{action}'. "
                            "Usa: open, search, click, type, read, "
                            "screenshot, back, forward, close."
                        ),
                        is_error=True,
                    )
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_use_id,
                content=f"Error en browser ({action}): {e}",
                is_error=True,
            )

    # ── Handlers ─────────────────────────────────────────────────────────────

    async def _handle_open(self, tool_use_id: str, kwargs: dict) -> ToolResult:
        raw = kwargs.get("url", "").strip()
        if not raw:
            return ToolResult(
                tool_use_id=tool_use_id,
                content=(
                    "Debes especificar 'url'. Puede ser:\n"
                    "  • Una URL web:      https://example.com\n"
                    "  • Una ruta local:   /home/ANDERVRZ/Downloads/doc.pdf"
                ),
                is_error=True,
            )

        url, warning = _to_url(raw)

        # Si el archivo no existe, retornar error antes de navegar
        if warning and "no encontrado" in warning:
            return ToolResult(
                tool_use_id=tool_use_id,
                content=warning,
                is_error=True,
            )

        response = await self._page.goto(url, wait_until="domcontentloaded")
        title  = await self._page.title()
        status = response.status if response else "?"

        lines = [f"✓ Abriendo: {url}"]
        if url.startswith("file://"):
            path_display = url.replace("file://", "")
            lines[0] = f"✓ Abriendo archivo local: {path_display}"
        lines += [
            f"  Título: {title}",
            f"  Estado: {status}",
        ]
        if warning:
            lines.append(f"\n{warning}")

        return ToolResult(tool_use_id=tool_use_id, content="\n".join(lines))

    async def _handle_search(self, tool_use_id: str, kwargs: dict) -> ToolResult:
        query = kwargs.get("query", "").strip()
        if not query:
            return ToolResult(
                tool_use_id=tool_use_id,
                content="Debes especificar 'query' con el texto a buscar.",
                is_error=True,
            )
        encoded = urllib.parse.quote_plus(query)
        url = f"https://duckduckgo.com/?q={encoded}&ia=web"
        await self._page.goto(url, wait_until="domcontentloaded")

        try:
            results_text = await self._page.evaluate("""
                () => {
                    const results = document.querySelectorAll('[data-result="result"]');
                    if (!results.length) return null;
                    return Array.from(results).slice(0, 5).map(r => {
                        const title   = r.querySelector('h2')?.innerText || '';
                        const snippet = r.querySelector('[data-result="snippet"]')?.innerText || '';
                        const link    = r.querySelector('a')?.href || '';
                        return title + '\\n' + snippet + '\\n' + link;
                    }).join('\\n\\n');
                }
            """)
        except Exception:
            results_text = None

        content = f"✓ Búsqueda: '{query}'\n\n"
        if results_text:
            content += results_text[:_MAX_PAGE_TEXT]
        else:
            content += "Usa action=read para ver el contenido completo."

        return ToolResult(tool_use_id=tool_use_id, content=content)

    async def _handle_click(self, tool_use_id: str, kwargs: dict) -> ToolResult:
        selector = kwargs.get("selector", "").strip()
        if not selector:
            return ToolResult(
                tool_use_id=tool_use_id,
                content="Debes especificar 'selector' (texto visible o selector CSS).",
                is_error=True,
            )
        try:
            locator = self._page.get_by_text(selector, exact=False)
            if await locator.count() > 0:
                await locator.first.click()
            else:
                await self._page.click(selector)
            await self._page.wait_for_load_state("domcontentloaded")
            title = await self._page.title()
            return ToolResult(
                tool_use_id=tool_use_id,
                content=(
                    f"✓ Clic en '{selector}'\n"
                    f"  Página: {title}\n"
                    f"  URL: {self._page.url}"
                ),
            )
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_use_id,
                content=f"No se encontró el elemento '{selector}': {e}",
                is_error=True,
            )

    async def _handle_type(self, tool_use_id: str, kwargs: dict) -> ToolResult:
        text     = kwargs.get("text", "")
        selector = kwargs.get("selector", "").strip()
        if not text:
            return ToolResult(
                tool_use_id=tool_use_id,
                content="Debes especificar 'text' con el texto a escribir.",
                is_error=True,
            )
        if selector:
            await self._page.fill(selector, text)
        else:
            await self._page.keyboard.type(text)
        preview = text[:60] + ("..." if len(text) > 60 else "")
        return ToolResult(
            tool_use_id=tool_use_id,
            content=f"✓ Texto escrito: '{preview}'",
        )

    async def _handle_read(self, tool_use_id: str) -> ToolResult:
        title = await self._page.title()
        url   = self._page.url
        text  = await self._page.evaluate("""
            () => {
                ['script','style','nav','footer','header','aside']
                    .forEach(t => document.querySelectorAll(t).forEach(e => e.remove()));
                return document.body?.innerText
                    || document.documentElement.innerText
                    || '';
            }
        """)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        clean = "\n".join(lines)
        if len(clean) > _MAX_PAGE_TEXT:
            clean = clean[:_MAX_PAGE_TEXT] + f"\n... [truncado a {_MAX_PAGE_TEXT} chars]"

        return ToolResult(
            tool_use_id=tool_use_id,
            content=f"Página: {title}\nURL: {url}\n\n{clean}",
        )

    async def _handle_screenshot(self, tool_use_id: str) -> ToolResult:
        _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts       = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest     = _SCREENSHOT_DIR / f"screenshot_{ts}.png"
        await self._page.screenshot(path=str(dest), full_page=False)
        title = await self._page.title()
        return ToolResult(
            tool_use_id=tool_use_id,
            content=(
                f"✓ Captura guardada: {dest}\n"
                f"  Página: {title}\n"
                f"  URL: {self._page.url}"
            ),
        )

    async def _handle_back(self, tool_use_id: str) -> ToolResult:
        await self._page.go_back(wait_until="domcontentloaded")
        title = await self._page.title()
        return ToolResult(
            tool_use_id=tool_use_id,
            content=f"✓ Atrás → {title}  |  {self._page.url}",
        )

    async def _handle_forward(self, tool_use_id: str) -> ToolResult:
        await self._page.go_forward(wait_until="domcontentloaded")
        title = await self._page.title()
        return ToolResult(
            tool_use_id=tool_use_id,
            content=f"✓ Adelante → {title}  |  {self._page.url}",
        )

    async def _handle_close(self, tool_use_id: str) -> ToolResult:
        if self._browser is None:
            return ToolResult(
                tool_use_id=tool_use_id,
                content="El navegador no estaba abierto.",
            )
        await self._close_browser()
        return ToolResult(tool_use_id=tool_use_id, content="✓ Navegador cerrado.")