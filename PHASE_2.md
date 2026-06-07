# PHASE_2.md — File Agent
## Especificación: CLI Mejorado + Memoria Persistente (TinyDB)

> **Fase:** 2 de 3
> **Versión:** 2.0.0
> **Estado:** Planificación — pendiente de implementación
> **Prerequisito:** Fase 1 completa — 206/206 tests passing

---

## 1. Resumen de Cambios

### Qué cambia

| Componente | Fase 1 | Fase 2 |
|------------|--------|--------|
| Memoria | Scaffold vacío (`store.py`) | TinyDB — documentos JSON persistentes |
| CLI | `main.py` monolítico | Módulo `cli/` separado con REPL, display, commands |
| Interfaz | Panels básicos Rich | TUI inspirada en Kilo CLI / Claude Code |
| Comandos | exit, clear, help | + traces, stats, memory, model |
| Respuestas | Plain text en panel | Markdown renderizado con Rich |
| Tool display | Línea simple | Bloque con duración + resultado |
| Session info | Ninguna | Header con modelo, sesión, tokens |

### Qué NO cambia

- El harness agéntico — sin modificaciones
- Los tools (file_tools, command_tool) — sin modificaciones
- El cliente LLM (OllamaClient) — sin modificaciones
- El sistema de Skills — sin modificaciones
- Los traces .jsonl — sin modificaciones
- Los 206 tests existentes — deben seguir passing

---

## 2. Nueva Dependencia — TinyDB

```bash
uv add tinydb
```

### Por qué TinyDB sobre Markdown

| Criterio | Markdown | TinyDB |
|----------|---------|--------|
| Queries | grep manual | `db.search(Q.topic == "paths")` |
| Estructura | texto libre | documentos JSON tipados |
| Peso | 0 | ~50KB, puro Python, 0 dependencias externas |
| Servidor | no | no |
| Migración futura | manual | misma interfaz, cambiar backend |

### Estructura de la base de datos

```
memory/
└── memory.json    ← único archivo, gestionado por TinyDB
```

#### Tablas (TinyDB las llama "tables")

```python
db = TinyDB("memory/memory.json")

# Tabla 1: hechos extraídos de conversaciones
facts = db.table("facts")
# {
#   "topic": "paths",
#   "content": "El home del usuario es /home/ANDERVRZ",
#   "source": "conversación",
#   "timestamp": "2026-06-05T10:30:00"
# }

# Tabla 2: resúmenes de sesión
sessions = db.table("sessions")
# {
#   "session_id": "uuid",
#   "summary": "Usuario organizó archivos .py en Downloads",
#   "tools_used": ["list_directory", "move_file"],
#   "timestamp": "2026-06-05T10:35:00"
# }

# Tabla 3: preferencias del usuario
preferences = db.table("preferences")
# {
#   "key": "preferred_editor",
#   "value": "Sublime Text",
#   "timestamp": "2026-06-05T10:40:00"
# }
```

---

## 3. Nueva Estructura de Carpetas

```
agent/
├── main.py              ← solo entry point (5 líneas)
│
├── cli/                 ← NUEVO módulo CLI
│   ├── __init__.py
│   ├── repl.py          ← loop principal del REPL async
│   ├── display.py       ← Rich: banner, panels, tool display, Markdown
│   └── commands.py      ← handlers: exit, clear, help, traces, stats, memory
│
└── memory/
    ├── __init__.py
    └── store.py         ← TinyDB implementation (reemplaza scaffold)
```

---

## 4. CLI — Diseño Visual

### Banner de inicio (inspirado en Kilo CLI)

```
╭─────────────────────────────────────────────────────╮
│  File Agent  v2.0.0                                 │
│  Modelo: gpt-oss:20b  ·  Ollama Cloud               │
│  Skills: 3 activas  ·  Memoria: habilitada          │
│  /help para comandos  ·  /exit para salir            │
╰─────────────────────────────────────────────────────╯
```

### Prompt

```
# Formato: [sesión corta] usuario ❯
[a1b2] ❯ 
```

### Tool execution display (inspirado en Claude Code)

```
  ⚡ list_directory  /home/ANDERVRZ/Downloads          12ms  ✓
  ⚡ move_file       app.py → python_moduls/           8ms   ✓
  ⚡ run_command     ls -la                            45ms  ✓
```

### Respuesta con Markdown renderizado

```
╭─ Agente ───────────────────────────────────────────╮
│                                                     │
│  Moví **23 archivos** `.py` a `python_moduls/`:    │
│                                                     │
│  - app.py                                           │
│  - cache.py                                         │
│  - ... y 21 más                                     │
│                                                     │
│  ✅ Operación completada en 340ms                   │
╰─────────────────────────────────────────────────────╯
```

### Barra de stats (al final de cada turno)

```
  tokens ↑842 ↓156  ·  tools 3  ·  350ms  ·  skill: file-management
```

---

## 5. Nuevos Comandos

| Comando | Descripción |
|---------|-------------|
| `/exit` o `/quit` | Salir del agente |
| `/clear` | Limpiar historial de contexto y pantalla |
| `/help` | Mostrar panel de ayuda completo |
| `/traces` | Mostrar el último trace del día actual |
| `/traces N` | Mostrar los últimos N traces |
| `/stats` | Estadísticas de la sesión actual |
| `/memory` | Listar hechos guardados en TinyDB |
| `/memory buscar <query>` | Buscar en la memoria |
| `/model` | Mostrar modelo activo y configuración LLM |

### Prefijo `/` vs texto libre

Los comandos especiales usan `/` como prefijo para no confundirse con instrucciones al agente:

```
[a1b2] ❯ /traces 3          ← comando especial
[a1b2] ❯ lista mis archivos  ← va al agente
```

---

## 6. Sistema de Memoria — TinyDB

### `agent/memory/store.py` — Implementación completa

```python
class TinyDBMemoryStore:
    """
    Memoria persistente con TinyDB.
    
    Operaciones:
    - save_fact(topic, content)   → guarda un hecho
    - search(query)               → búsqueda por texto
    - save_session(id, summary)   → guarda resumen de sesión
    - get_recent(n)               → últimos N hechos
    - list_all()                  → todos los hechos
    - delete(doc_id)              → eliminar por ID
    """
```

### Integración con el harness

Al finalizar cada turno exitoso, el harness extrae hechos relevantes y los guarda:

```
Turno: "el home del usuario es /home/ANDERVRZ"
  → Memory.save_fact(topic="paths", content="home=/home/ANDERVRZ")

Turno complejo con 5+ tools:
  → Memory.save_session(summary="Organizó archivos Python en Downloads")
```

La extracción de hechos es simple en Fase 2: keywords + contexto del tool result.
LLM-based extraction se difiere a Fase 3.

---

## 7. `cli/display.py` — Componentes Rich

```python
# Funciones públicas del módulo

def print_banner(config: AgentConfig) -> None:
    """Banner de inicio con modelo, skills, memoria."""

def print_tool_execution(name: str, input_summary: str, duration_ms: int, is_error: bool) -> None:
    """Línea de ejecución de tool inline."""

def print_response(content: str, stats: TurnStats) -> None:
    """Panel de respuesta con Markdown renderizado + stats."""

def print_trace(trace: TurnTrace) -> None:
    """Trace completo formateado en terminal."""

def print_help() -> None:
    """Panel de ayuda con todos los comandos."""

def print_stats(session: SessionStats) -> None:
    """Estadísticas de la sesión actual."""

def print_memory(facts: list[dict]) -> None:
    """Lista de hechos de memoria."""
```

---

## 8. `cli/commands.py` — Handlers

```python
# Cada comando retorna CommandResult

class CommandResult(BaseModel):
    handled: bool         # True si era un comando especial
    should_exit: bool     # True si el agente debe cerrar
    should_clear: bool    # True si debe limpiar pantalla

async def handle_command(
    text: str,
    harness: AgentHarness,
    memory: TinyDBMemoryStore,
    recorder: TraceRecorder,
    session: SessionStats,
) -> CommandResult:
    """
    Detecta comandos /xxx y los despacha.
    Si no es comando → CommandResult(handled=False)
    """
```

---

## 9. `cli/repl.py` — Loop Principal

```python
async def run_repl(
    harness: AgentHarness,
    memory: TinyDBMemoryStore,
    config: AgentConfig,
) -> None:
    """
    Loop principal del REPL.
    
    Flujo por turno:
    1. Prompt con session_id corto
    2. Input del usuario
    3. Si es /comando → handle_command()
    4. Si es texto → harness.run() con display de tools inline
    5. Render de respuesta con Markdown
    6. Stats bar
    7. (Si memoria habilitada) → extraer y guardar hechos
    """
```

---

## 10. `main.py` — Entry Point Limpio

```python
# agent/main.py — solo 10 líneas
import asyncio
from .core.config import load_config, Settings
from .loop.harness import bootstrap
from .cli.repl import run_repl

async def async_main() -> None:
    harness, memory, config = await bootstrap()
    await run_repl(harness, memory, config)

def main() -> None:
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
```

---

## 11. `bootstrap()` — Actualizado

La función `bootstrap()` se mueve a `main.py` y retorna una tupla:

```python
async def bootstrap() -> tuple[AgentHarness, TinyDBMemoryStore, AgentConfig]:
    config, settings = load_config()
    
    # ... inicialización existente ...
    
    memory = TinyDBMemoryStore(
        path=config.memory.path,
        enabled=config.memory.enabled,
    )
    
    return harness, memory, config
```

---

## 12. Orden de Construcción — Fase 2

```
Paso 1: TinyDB store
  → agent/memory/store.py completo
  → tests/unit/test_memory_store.py

Paso 2: CLI display
  → agent/cli/display.py
  → tests/unit/test_display.py (básicos)

Paso 3: CLI commands
  → agent/cli/commands.py
  → tests/unit/test_commands.py

Paso 4: CLI repl
  → agent/cli/repl.py
  → integración con display + commands

Paso 5: main.py refactor
  → entry point limpio
  → bootstrap actualizado

Paso 6: Tests de integración
  → tests/integration/test_memory_integration.py
  → uv run pytest → todos passing
```

---

## 13. Dependencias Finales Fase 2

```toml
# pyproject.toml — agregar
dependencies = [
    "ollama",
    "pydantic>=2.0",
    "pydantic-settings",
    "pyyaml>=6.0",
    "rich>=13.0",
    "tinydb",          # ← nuevo en Fase 2
]
```

---

## 14. Compatibilidad con Tests Existentes

Los 206 tests de Fase 1 no deben modificarse ni romperse.
Todos los cambios son aditivos:

- `main.py` refactorizado pero `bootstrap()` sigue existiendo
- `memory/store.py` reemplaza scaffold → misma interfaz pública
- `cli/` es nuevo — no afecta módulos existentes
- `harness.py` sin cambios — solo recibe `memory` como param opcional

---

*Fin del documento — PHASE_2.md v1.0.0*
*Implementar en el orden definido en sección 12.*
