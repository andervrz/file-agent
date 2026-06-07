# MODULE_MAP_PHASE2.md — File Agent
## Mapa de Módulos Fase 2: CLI + Memoria TinyDB

> **Complementa:** MODULE_MAP.md (Fase 1)
> **Cubre:** agent/cli/, agent/memory/store.py, main.py refactorizado
> **Principio:** Los módulos de Fase 1 no se modifican. Todo es aditivo.

---

## Diagrama de Dependencias — Fase 2

```
main.py
  └── bootstrap()
        ├── AgentHarness          (Fase 1 — sin cambios)
        ├── TinyDBMemoryStore     (memory/store.py — NUEVO)
        └── AgentConfig

      └── run_repl()              (cli/repl.py — NUEVO)
            ├── handle_command()  (cli/commands.py — NUEVO)
            │     ├── TinyDBMemoryStore
            │     ├── TraceRecorder
            │     └── SessionStats
            ├── print_*()         (cli/display.py — NUEVO)
            │     └── Rich (Console, Panel, Markdown, Table, Spinner)
            └── AgentHarness.run()  (Fase 1 — sin cambios)


Flujo de datos por turno:
  repl.py
    → commands.py (¿es /comando? → handle → return)
    → harness.run() (texto libre → response + TurnTrace)
    → display.py (renderizar response + stats)
    → memory/store.py (guardar hechos del turno)
```

---

## Módulos Nuevos

---

## `agent/memory/store.py` — TinyDB Memory Store

**Propósito:** Reemplaza el scaffold vacío de Fase 1. Persistencia de hechos,
resúmenes de sesión y preferencias en un archivo JSON via TinyDB.
Misma interfaz pública → el harness no necesita cambios.

**Dependencias externas:** `tinydb`

### Modelos

```python
class Fact(BaseModel):
    """Hecho extraído de una conversación."""
    topic: str              # categoría: "paths", "tools", "preferences"
    content: str            # el hecho en lenguaje natural
    source: str             # "conversación" | "tool_result"
    timestamp: str          # ISO 8601
    session_id: str         # UUID de la sesión donde se capturó

class SessionSummary(BaseModel):
    """Resumen de una sesión de trabajo."""
    session_id: str
    summary: str            # descripción breve de lo que se hizo
    tools_used: list[str]   # nombres de tools ejecutados
    total_turns: int
    timestamp: str          # ISO 8601

class MemorySearchResult(BaseModel):
    """Resultado de búsqueda en memoria."""
    doc_id: int             # ID interno de TinyDB
    fact: Fact
    relevance: float        # 0.0-1.0 — simple keyword match score
```

### Clase Principal

```python
class TinyDBMemoryStore:
    """
    Memoria persistente con TinyDB.
    Un archivo JSON — sin servidor, sin dependencias adicionales.
    
    Tablas internas:
    - facts       → hechos extraídos de conversaciones
    - sessions    → resúmenes de sesiones
    - preferences → preferencias del usuario
    """

    def __init__(self, path: str | Path, enabled: bool = False):
        """
        Si enabled=False → todas las operaciones son no-ops.
        Si el directorio no existe → se crea automáticamente.
        """

    # ── escritura ──

    async def save_fact(self, fact: Fact) -> int:
        """
        Guarda un hecho en la tabla 'facts'.
        Retorna el doc_id asignado por TinyDB.
        Si enabled=False → retorna -1 sin hacer nada.
        Usa asyncio.to_thread() → no bloquea el event loop.
        """

    async def save_session(self, summary: SessionSummary) -> int:
        """
        Guarda un resumen de sesión en la tabla 'sessions'.
        Se llama al finalizar run_repl() limpiamente (exit/quit).
        """

    async def save_preference(self, key: str, value: str) -> None:
        """
        Guarda o actualiza una preferencia del usuario.
        Usa upsert: si existe la key, la actualiza.
        """

    # ── lectura ──

    async def search(self, query: str, limit: int = 10) -> list[MemorySearchResult]:
        """
        Búsqueda de hechos por contenido.
        v2: keyword matching simple (sin embeddings).
        v3: semántico con embeddings.
        
        Retorna lista ordenada por relevancia descendente.
        Si enabled=False → retorna [].
        """

    async def get_recent(self, n: int = 5) -> list[Fact]:
        """
        Retorna los últimos N hechos ordenados por timestamp.
        """

    async def list_all(self) -> list[MemorySearchResult]:
        """
        Retorna todos los hechos. Útil para /memory command.
        """

    async def get_preference(self, key: str) -> str | None:
        """
        Retorna el valor de una preferencia por key.
        Retorna None si no existe.
        """

    # ── eliminación ──

    async def delete(self, doc_id: int) -> bool:
        """
        Elimina un hecho por su doc_id.
        Retorna True si existía y se eliminó.
        """

    async def clear_all(self) -> None:
        """
        Elimina todos los hechos. Para /memory clear.
        Pide confirmación antes de ejecutar (en commands.py).
        """

    # ── stats ──

    async def count(self) -> dict[str, int]:
        """
        Retorna conteo por tabla: {"facts": 42, "sessions": 7, "preferences": 3}
        """
```

**Conectado a:**
- `cli/commands.py` → llama `list_all()`, `search()`, `delete()`
- `cli/repl.py` → llama `save_fact()` al final de cada turno
- `main.py` → instanciado en `bootstrap()`
- `agent/core/config.py` → recibe `MemoryConfig.path` y `.enabled`

---

## `agent/cli/display.py` — Componentes Rich

**Propósito:** Toda la lógica de renderizado Rich en un solo módulo.
`repl.py` y `commands.py` importan funciones de aquí — nunca usan Rich directamente.
Separación total entre lógica y presentación.

**Dependencias externas:** `rich`

### Modelos de datos para display

```python
class TurnStats(BaseModel):
    """Estadísticas de un turno — para la stats bar."""
    tokens_in: int
    tokens_out: int
    total_tools: int
    duration_ms: int
    skill_activated: str | None
    had_errors: bool

class SessionStats(BaseModel):
    """Estadísticas acumuladas de la sesión."""
    session_id: str              # UUID corto para el prompt
    total_turns: int
    total_tokens_in: int
    total_tokens_out: int
    total_tools_executed: int
    total_errors: int
    start_time: datetime
    model: str
```

### Funciones públicas

```python
def get_console() -> Console:
    """
    Retorna la instancia global de Rich Console.
    Un solo Console en toda la app → evitar duplicación de output.
    """

def print_banner(config: AgentConfig) -> None:
    """
    Banner de inicio.
    
    Muestra:
    - Nombre y versión del agente
    - Modelo LLM activo
    - Número de skills cargadas
    - Estado de memoria (habilitada/deshabilitada)
    - Lista de comandos disponibles
    
    Ejemplo visual:
    ╭─────────────────────────────────────────╮
    │  File Agent  v2.0.0                     │
    │  gpt-oss:20b  ·  Ollama Cloud           │
    │  3 skills  ·  memoria habilitada        │
    │  /help para comandos                    │
    ╰─────────────────────────────────────────╯
    """

def print_tool_start(name: str, input_summary: str) -> None:
    """
    Muestra inicio de ejecución de tool (antes de ejecutar).
    Formato: ⚡ list_directory  /home/ANDERVRZ/...
    Se llama ANTES de ejecutar para feedback inmediato.
    """

def print_tool_result(
    name: str,
    input_summary: str,
    duration_ms: int,
    is_error: bool,
) -> None:
    """
    Actualiza o añade resultado de tool.
    Formato: ⚡ list_directory  /home/...  12ms  ✓
             ⚡ delete_file     /etc/passwd        ✗
    Verde para éxito, rojo para error.
    """

def print_response(content: str, stats: TurnStats) -> None:
    """
    Renderiza la respuesta final del agente.
    
    - Usa Rich Markdown para renderizar **bold**, `code`, listas
    - Panel con borde color según had_errors (green/yellow)
    - Stats bar al pie: tokens ↑842 ↓156 · tools 3 · 350ms · skill: file-management
    """

def print_help() -> None:
    """
    Panel de ayuda completo con todos los comandos.
    Dos columnas: comando | descripción.
    """

def print_trace(trace: TurnTrace, verbose: bool = False) -> None:
    """
    Renderiza un TurnTrace en terminal.
    
    Modo normal:
    ┌─ Trace [turn_id_corto] ──────────────────┐
    │ 🕐 2026-06-05 10:30:00                   │
    │ 💬 "lista mis archivos en Downloads"     │
    │ 🎯 Skill: file-management                │
    │ 🔧 Tools: list_directory, move_file (x2) │
    │ 🤖 LLM calls: 2  ·  tokens ↑1200 ↓450   │
    │ ⏱  Total: 2.3s                           │
    └──────────────────────────────────────────┘
    
    Modo verbose (verbose=True):
    Muestra también inputs/outputs de cada tool.
    """

def print_traces_list(traces: list[TurnTrace]) -> None:
    """
    Lista compacta de múltiples traces.
    Una línea por trace con timestamp, mensaje y stats.
    """

def print_stats(stats: SessionStats) -> None:
    """
    Panel de estadísticas de la sesión actual.
    
    ╭─ Sesión [id] ────────────────────────────╮
    │ Duración:   45 minutos                   │
    │ Turnos:     12                           │
    │ Tokens:     ↑8,421  ↓3,156              │
    │ Tools:      34 ejecutados                │
    │ Errores:    2                            │
    │ Modelo:     gpt-oss:20b                  │
    ╰──────────────────────────────────────────╯
    """

def print_memory_list(results: list[MemorySearchResult]) -> None:
    """
    Tabla de hechos de memoria.
    Columnas: ID | Topic | Content | Timestamp
    """

def print_error(message: str) -> None:
    """Mensaje de error en rojo. Para errores del sistema, no del agente."""

def print_info(message: str) -> None:
    """Mensaje informativo en dim. Para confirmaciones y feedback."""

def format_session_prompt(session_id: str) -> str:
    """
    Retorna el prompt formateado para el REPL.
    Ejemplo: "[a1b2] ❯ "
    Usa los primeros 4 chars del UUID.
    """
```

**Conectado a:**
- `cli/repl.py` → importa todas las funciones `print_*`
- `cli/commands.py` → importa `print_help`, `print_trace`, `print_stats`, `print_memory_list`
- `agent/traces/models.py` → recibe `TurnTrace` en `print_trace`
- `agent/core/config.py` → recibe `AgentConfig` en `print_banner`

---

## `agent/cli/commands.py` — Handlers de Comandos

**Propósito:** Detecta comandos `/xxx` y los despacha.
Si el input no es un comando → retorna `CommandResult(handled=False)`.
El `repl.py` decide qué hacer con el resultado.
Cada handler es una función async independiente.

### Modelos

```python
class CommandResult(BaseModel):
    """Resultado de procesar un posible comando."""
    handled: bool           # True si era /comando y se procesó
    should_exit: bool       # True si el agente debe cerrar
    should_clear: bool      # True si debe limpiar pantalla y contexto
```

### Función principal de dispatch

```python
async def handle_command(
    text: str,
    harness: AgentHarness,
    memory: TinyDBMemoryStore,
    recorder: TraceRecorder,
    session: SessionStats,
) -> CommandResult:
    """
    Entry point del módulo.
    
    1. Verifica si text empieza con '/'
    2. Si no → CommandResult(handled=False)
    3. Si sí → parsea comando y args, despacha al handler correcto
    4. Si comando desconocido → muestra error y retorna handled=True
    
    Comandos reconocidos:
    /exit, /quit  → _handle_exit()
    /clear        → _handle_clear()
    /help         → _handle_help()
    /traces       → _handle_traces()
    /traces N     → _handle_traces(n=N)
    /stats        → _handle_stats()
    /memory       → _handle_memory()
    /memory buscar <q> → _handle_memory_search()
    /memory clear → _handle_memory_clear()
    /model        → _handle_model()
    """
```

### Handlers internos (funciones privadas)

```python
async def _handle_exit(session: SessionStats, memory: TinyDBMemoryStore) -> CommandResult:
    """
    Guarda resumen de sesión en memoria antes de salir.
    Muestra mensaje de despedida con stats finales.
    Retorna CommandResult(handled=True, should_exit=True).
    """

async def _handle_clear(harness: AgentHarness) -> CommandResult:
    """
    Llama harness.reset() → limpia contexto.
    print_info("Historial limpiado.").
    Retorna CommandResult(handled=True, should_clear=True).
    """

async def _handle_help() -> CommandResult:
    """
    Llama display.print_help().
    Retorna CommandResult(handled=True).
    """

async def _handle_traces(recorder: TraceRecorder, n: int = 3) -> CommandResult:
    """
    Lee el .jsonl del día actual (o días anteriores si n es grande).
    Parsea los últimos N TurnTrace.
    Llama display.print_traces_list(traces).
    Si n == 1 → llama display.print_trace(trace, verbose=True).
    """

async def _handle_stats(session: SessionStats) -> CommandResult:
    """
    Llama display.print_stats(session).
    """

async def _handle_memory(memory: TinyDBMemoryStore) -> CommandResult:
    """
    Llama memory.list_all().
    Si vacío → print_info("No hay hechos guardados.").
    Si no → display.print_memory_list(results).
    """

async def _handle_memory_search(memory: TinyDBMemoryStore, query: str) -> CommandResult:
    """
    Llama memory.search(query).
    Muestra resultados con display.print_memory_list().
    """

async def _handle_memory_clear(memory: TinyDBMemoryStore) -> CommandResult:
    """
    Pide confirmación: "¿Eliminar todos los hechos? (s/n)"
    Si confirma → memory.clear_all() → print_info("Memoria limpiada.")
    """

async def _handle_model(config: AgentConfig) -> CommandResult:
    """
    Muestra modelo activo, temperatura, num_ctx, num_predict.
    """
```

**Conectado a:**
- `cli/repl.py` → llama `handle_command()` en cada turno
- `cli/display.py` → importa funciones `print_*`
- `agent/memory/store.py` → llama `list_all()`, `search()`, `clear_all()`, `save_session()`
- `agent/traces/recorder.py` → lee .jsonl para `/traces`
- `agent/loop/harness.py` → llama `reset()` para `/clear`
- `agent/core/config.py` → recibe `AgentConfig` para `/model`

---

## `agent/cli/repl.py` — Loop Principal

**Propósito:** Orquesta el REPL completo. Conecta input → command/harness → display → memory.
Es el único módulo que habla con todos los demás de la capa CLI.
Toda la lógica async del loop vive aquí.

### Función principal

```python
async def run_repl(
    harness: AgentHarness,
    memory: TinyDBMemoryStore,
    config: AgentConfig,
) -> None:
    """
    Loop principal del REPL.
    
    INICIALIZACIÓN:
    1. Crear SessionStats con UUID de sesión
    2. display.print_banner(config)
    3. Actualizar {HOME} en system_prompt si aplica
    
    LOOP (por turno):
    1. Prompt: await asyncio.to_thread(Prompt.ask, format_session_prompt(session.id))
    2. strip() del input
    3. Si vacío → continue
    4. result = await handle_command(text, harness, memory, recorder, session)
    5. Si result.handled:
       - Si result.should_exit → break
       - Si result.should_clear → console.clear() → continue
       - Continue (comando ya procesado)
    6. Si no handled → texto libre al agente:
       a. display.print_tool_start() por cada tool (via callback)
       b. response = await harness.run(text)
       c. Construir TurnStats desde el último trace
       d. display.print_response(response, stats)
       e. session.update(stats)  → acumular totales
       f. Si memory.enabled → extraer_y_guardar_hechos(response, harness)
    
    FINALIZACIÓN (después del break):
    1. Si memory.enabled → memory.save_session(session_summary)
    2. display.print_info("Sesión guardada. Adiós.")
    
    MANEJO DE ERRORES:
    - KeyboardInterrupt → break limpio
    - EOFError → break limpio
    """
```

### Función auxiliar de extracción de hechos

```python
async def _extract_and_save_facts(
    user_message: str,
    response: str,
    turn_trace: TurnTrace,
    memory: TinyDBMemoryStore,
    session_id: str,
) -> None:
    """
    Extracción simple de hechos relevantes para guardar en memoria.
    
    Fase 2 — keyword-based:
    - Si tool_result contiene paths absolutos → save_fact(topic="paths")
    - Si response menciona preferencias del usuario → save_fact(topic="preferences")
    - Si turno tuvo > 3 tools exitosos → save_fact(topic="operaciones")
    
    Fase 3 — LLM-based extraction (diferido).
    """
```

### Función de integración con tool display

```python
def _make_tool_display_callback(console) -> Callable:
    """
    Retorna un callback que el harness llama al ejecutar cada tool.
    Permite mostrar herramientas inline mientras se ejecutan.
    
    Nota: En Fase 2 se muestra post-ejecución leyendo el último trace.
    En Fase 3 se integra directamente en el harness con callbacks.
    """
```

**Conectado a:**
- `cli/display.py` → importa todas las funciones `print_*`
- `cli/commands.py` → llama `handle_command()`
- `agent/loop/harness.py` → llama `run()` y `reset()`
- `agent/memory/store.py` → llama `save_fact()` y `save_session()`
- `agent/traces/recorder.py` → lee último trace para construir `TurnStats`
- `agent/core/config.py` → recibe `AgentConfig`

---

## `agent/main.py` — Entry Point Refactorizado

**Propósito:** Solo inicialización y arranque. Sin lógica de negocio.

```python
# agent/main.py

import asyncio
from .core.config import load_config, Settings
from .loop.harness import AgentHarness
from .cli.repl import run_repl
from .memory.store import TinyDBMemoryStore

# Importaciones de Fase 1 que se mueven a bootstrap()
from .loop.context import ConversationContext
from .skills.loader import SkillLoader
from .skills.matcher import SkillMatcher
from .tools.base import PathSafeguard
from .tools.file_tools import build_file_tools
from .tools.command_tool import build_command_tool
from .tools.registry import ToolRegistry
from .traces.recorder import TraceRecorder


async def bootstrap() -> tuple[AgentHarness, TinyDBMemoryStore, AgentConfig]:
    """
    Inicializa todos los componentes en orden.
    Retorna (harness, memory, config) listos para usar.
    
    Orden:
    1. load_config()
    2. PathSafeguard
    3. ToolRegistry + tools
    4. OllamaClient
    5. SkillLoader + SkillMatcher
    6. ConversationContext
    7. TraceRecorder
    8. TinyDBMemoryStore     ← nuevo en Fase 2
    9. AgentHarness
    """

async def async_main() -> None:
    harness, memory, config = await bootstrap()
    await run_repl(harness, memory, config)

def main() -> None:
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
```

**Conectado a:**
- `cli/repl.py` → llama `run_repl()`
- Todos los módulos de Fase 1 → instanciados en `bootstrap()`
- `memory/store.py` → instanciado en `bootstrap()`

---

## Flujo Completo — Un Turno con Memoria

```
[a1b2] ❯ mueve todos los .py de Downloads a python_moduls
           │
           ▼
commands.py: handle_command("mueve...") → handled=False
           │
           ▼
repl.py: harness.run("mueve todos los .py...")
           │
           ▼
harness: LLM → tool_calls: [search_files, move_file×23]
           │
           ▼
display.py: print_tool_result() × 24
  ⚡ search_files   Downloads/*.py          45ms  ✓
  ⚡ move_file      app.py → python_moduls   8ms  ✓
  ⚡ move_file      cache.py → ...           7ms  ✓
  ... 21 más
           │
           ▼
display.py: print_response(response, stats)
  ╭─ Agente ─────────────────────────────────────────╮
  │  Moví **23 archivos** `.py` a `python_moduls/`   │
  ╰──────────────────────────────────────────────────╯
  tokens ↑1842 ↓156  ·  tools 24  ·  2.3s  ·  skill: file-management
           │
           ▼
session.update(stats)  → acumula totales
           │
           ▼
repl.py: _extract_and_save_facts()
  → memory.save_fact(topic="operaciones",
      content="Movió 23 archivos .py de Downloads a python_moduls")
           │
           ▼
[a1b2] ❯ _  ← siguiente prompt
```

---

## Flujo Completo — Comando /traces

```
[a1b2] ❯ /traces 2
           │
           ▼
commands.py: handle_command("/traces 2") → handled=True
           │
           ▼
_handle_traces(recorder, n=2)
  → lee traces/2026-06-05.jsonl
  → parsea últimos 2 TurnTrace
           │
           ▼
display.py: print_traces_list([trace1, trace2])
  ┌─ Trace [a1b2] ─────────────────────────────────┐
  │ 10:30  "mueve todos los .py..."                │
  │ Tools: search_files + move_file×23  ·  2.3s    │
  └────────────────────────────────────────────────┘
  ┌─ Trace [c3d4] ─────────────────────────────────┐
  │ 10:15  "lista archivos en Documents"           │
  │ Tools: list_directory  ·  120ms                │
  └────────────────────────────────────────────────┘
           │
           ▼
CommandResult(handled=True, should_exit=False, should_clear=False)
           │
           ▼
[a1b2] ❯ _  ← siguiente prompt (sin llamar al harness)
```

---

## Tests Nuevos — Fase 2

```
tests/
├── unit/
│   ├── test_memory_store.py      ← TinyDBMemoryStore (save, search, delete)
│   ├── test_display.py           ← funciones print_* (smoke tests)
│   ├── test_commands.py          ← handle_command con mocks
│   └── test_session_stats.py     ← SessionStats acumulación
└── integration/
    └── test_memory_integration.py ← repl + memory + harness mock
```

### Principio de tests Fase 2

- `test_memory_store.py` → usa `tmp_path` de pytest para el .json
- `test_display.py` → smoke tests (no crashean, retornan None)
- `test_commands.py` → mocks de harness, memory, recorder
- Los 206 tests de Fase 1 siguen corriendo sin modificaciones

---

## Resumen de Conexiones

```
main.py
  ↓ bootstrap()
  ↓ run_repl()

cli/repl.py
  ← usa → cli/display.py          (renderizado)
  ← usa → cli/commands.py         (comandos /xxx)
  ← usa → agent/loop/harness.py   (procesamiento de mensajes)
  ← usa → agent/memory/store.py   (guardar hechos)
  ← usa → agent/traces/recorder.py (leer traces para /traces)

cli/commands.py
  ← usa → cli/display.py
  ← usa → agent/memory/store.py
  ← usa → agent/traces/recorder.py
  ← usa → agent/loop/harness.py   (reset para /clear)

cli/display.py
  ← usa → rich (Console, Panel, Markdown, Table, Spinner, Text)
  ← usa → agent/traces/models.py  (TurnTrace para print_trace)
  ← usa → agent/core/config.py    (AgentConfig para print_banner)

agent/memory/store.py
  ← usa → tinydb (TinyDB, Query)
  ← usa → agent/core/config.py    (MemoryConfig)
```

---

*Fin del documento — MODULE_MAP_PHASE2.md v1.0.0*
*Leer junto con MODULE_MAP.md (Fase 1) antes de escribir código.*
