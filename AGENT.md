# AGENT.md — File Agent
## Documento Maestro de Especificación del Agente

> **Versión:** 1.0.0
> **Última actualización:** Junio 2026
> **Estado:** Activo — Fase 1 en desarrollo
> **Principio rector:** Código simple, limpio y bien estructurado. El harness controla. El LLM razona.

---

## Tabla de Contenidos

1. [Identidad del Agente](#1-identidad-del-agente)
2. [Capacidades y Funciones](#2-capacidades-y-funciones)
3. [Arquitectura del Sistema](#3-arquitectura-del-sistema)
4. [Stack Tecnológico](#4-stack-tecnológico)
5. [Principios de Ingeniería](#5-principios-de-ingeniería)
6. [Harness Engineering](#6-harness-engineering)
7. [Context Engineering](#7-context-engineering)
8. [Skills System](#8-skills-system)
9. [Tools y Niveles de Seguridad](#9-tools-y-niveles-de-seguridad)
10. [Traces y Observabilidad](#10-traces-y-observabilidad)
11. [Memoria Persistente](#11-memoria-persistente)
12. [Estructura del Proyecto](#12-estructura-del-proyecto)
13. [Convenciones de Código](#13-convenciones-de-código)
14. [Variables de Entorno](#14-variables-de-entorno)
15. [Fases de Desarrollo](#15-fases-de-desarrollo)
16. [Decisiones Rechazadas](#16-decisiones-rechazadas)

---

## 1. Identidad del Agente

### ¿Qué es este agente?

Un agente de gestión de archivos y terminal que opera completamente desde la línea de
comandos. Permite al usuario crear, leer, mover, copiar, eliminar y organizar archivos
y directorios usando lenguaje natural, además de ejecutar comandos de shell con niveles
de seguridad configurables.

### Propósito

Demostrar una implementación limpia de un agente con:
- Loop agéntico sin frameworks externos
- Harness de control determinista
- Context engineering con progressive disclosure via Skills
- Observabilidad completa con traces
- Seguridad por niveles configurables desde YAML

### Modelo LLM

```
Provider:  Ollama Cloud
Modelo:    gpt-oss:20b  (OpenAI open weights via Ollama)
Fallback:  gpt-oss:120b (cuando se requiere mayor razonamiento)
Tool use:  Nativo confirmado — retorna ToolCall objects
```

### Audiencia

- Desarrollador individual en máquina con recursos limitados
- Hardware: Pentium Core 2 Duo, 4GB RAM
- OS: Linux / macOS
- Interacción: terminal exclusivamente

---

## 2. Capacidades y Funciones

### Tools de Archivos (file_tools.py)

| Tool | Descripción | Seguridad |
|------|-------------|-----------|
| `create_file` | Crea archivo con contenido (txt, md, json, yaml, py, etc.) | MODERATE |
| `read_file` | Lee y retorna contenido de un archivo | SAFE |
| `move_file` | Mueve o renombra un archivo | MODERATE |
| `copy_file` | Copia un archivo a otra ubicación | MODERATE |
| `delete_file` | Elimina un archivo del sistema | DANGEROUS |
| `list_directory` | Lista contenido de un directorio con tamaños | SAFE |
| `create_directory` | Crea directorio (con subdirectorios si aplica) | MODERATE |
| `search_files` | Busca archivos por nombre o patrón glob | SAFE |

### Tool de Comandos (command_tool.py)

| Tool | Descripción |
|------|-------------|
| `run_command` | Ejecuta comandos de shell con validación de seguridad |

Comandos disponibles según nivel de seguridad definido en `agent.yaml`.

### Skills Disponibles

| Skill | Archivo | Activa cuando... |
|-------|---------|-----------------|
| `file-management` | `skills/file-management/SKILL.md` | el usuario gestiona archivos/directorios |
| `command-execution` | `skills/command-execution/SKILL.md` | el usuario ejecuta comandos de terminal |
| `document-creation` | `skills/document-creation/SKILL.md` | el usuario crea documentos estructurados |

---

## 3. Arquitectura del Sistema

```
┌─────────────────────────────────────────────────────────┐
│                    TERMINAL (Rich UI)                    │
│                   main.py — REPL loop                   │
└──────────────────────────┬──────────────────────────────┘
                           │ user input
                           ▼
┌─────────────────────────────────────────────────────────┐
│                   AGENT HARNESS                          │
│                  loop/harness.py                         │
│                                                          │
│  1. Skills Matcher → activa skill si hay match           │
│  2. Context Builder → arma messages con skill activa     │
│  3. LLM Call → Ollama AsyncClient                        │
│  4. Tool Calls? → ejecuta via ToolRegistry               │
│  5. Continúa loop o retorna respuesta final              │
│  6. Trace Recorder → guarda turno completo               │
└───────┬──────────┬──────────────┬───────────────────────┘
        │          │              │
        ▼          ▼              ▼
┌──────────┐ ┌──────────┐ ┌──────────────┐
│ OllamaLLM│ │  Tools   │ │   Traces     │
│  client  │ │ Registry │ │  Recorder    │
│  async   │ │file+cmd  │ │  .jsonl      │
└──────────┘ └──────────┘ └──────────────┘
        │          │
        ▼          ▼
┌──────────┐ ┌──────────────────────────────┐
│Ollama    │ │     PathSafeguard            │
│Cloud API │ │ SAFE/MODERATE/DANGEROUS/     │
│gpt-oss   │ │ BLOCKED validation           │
└──────────┘ └──────────────────────────────┘
```

### Flujo de un turno completo

```
1. Usuario escribe mensaje en terminal
2. Skills Matcher compara mensaje vs descriptions de skills (~40 tokens c/u)
3. Si hay match → carga SKILL.md completo en context
4. Context Builder arma: system_prompt + skill_body (si aplica) + historial + mensaje
5. LLM call → Ollama Cloud (gpt-oss:20b)
6. Response tiene tool_calls?
   └── Sí → ToolRegistry.execute() → PathSafeguard valida → ejecuta → resultado al context
   └── No → retorna texto al usuario
7. Si tool_calls → vuelve al paso 5 (max_iterations del harness)
8. Trace Recorder guarda el turno completo en .jsonl
9. Rich UI muestra respuesta final en panel
```

---

## 4. Stack Tecnológico

### Runtime

| Librería | Versión | Rol |
|----------|---------|-----|
| `ollama` | latest | AsyncClient — LLM principal + tool calling |
| `pydantic` | >=2.0 | Validación estricta en todo el borde |
| `pydantic-settings` | latest | Carga .env tipado |
| `pyyaml` | >=6.0 | Lee agent.yaml y SKILL.md frontmatter |
| `rich` | >=13.0 | Terminal UI — panels, spinner, prompt |

### Standard Library (sin instalar)

| Módulo | Uso |
|--------|-----|
| `asyncio` | async 100% — ningún I/O bloquea el event loop |
| `pathlib` | todas las operaciones de archivos |
| `shutil` | copy y move de archivos |
| `subprocess` | ejecución de comandos con timeout |
| `json` | serialización de traces |
| `datetime` | timestamps ISO en traces |
| `uuid` | IDs únicos por turno |
| `time` | medición de duración de pasos |
| `re` | validación de comandos en security levels |

### Package Manager

```bash
uv  # consistencia con proyectos anteriores del autor
```

---

## 5. Principios de Ingeniería

### Fundamentos aplicados al proyecto

```
1. El harness controla. El LLM razona.
   → Python decide cuándo parar, qué ejecutar, qué validar.
   → El LLM solo genera lenguaje y decide qué tools llamar.

2. Async sin excepción.
   → AsyncClient de Ollama para LLM calls.
   → asyncio.to_thread() para operaciones de archivo bloqueantes.
   → asyncio.create_subprocess_exec() para comandos shell.

3. Un módulo, una responsabilidad.
   → Cada archivo hace UNA cosa. Sin god objects.

4. Fail loudly.
   → Errores explícitos con contexto. Sin except: pass.
   → Errores registrados en traces con is_error=True.

5. Config sobre código.
   → agent.yaml define modelo, opciones, security levels, skills path.
   → Sin valores hardcodeados en el código.

6. Progressive disclosure.
   → Skills cargan solo cuando hay match.
   → Contexto mínimo y preciso en cada turno.

7. Código simple primero.
   → La solución más simple que funcione correctamente.
   → Complejidad solo cuando la necesidad es probada.
```

---

## 6. Harness Engineering

### Definición en este proyecto

El harness es la capa de infraestructura runtime que envuelve al LLM con todo
lo que necesita para comportarse de forma predecible y segura. Es la diferencia
entre un chatbot y un agente confiable.

### Componentes del harness

```python
# loop/harness.py — el corazón del agente

class AgentHarness:
    """
    Responsabilidades:
    - Controlar el loop agéntico (no el LLM)
    - Imponer max_iterations (evita loops infinitos)
    - Ejecutar tools vía ToolRegistry (no directamente)
    - Registrar cada turno en Traces
    - Manejar errores sin propagar al usuario crudamente
    """
    
    async def run(self, user_message: str) -> str:
        # 1. Matcher activa skill si hay match
        # 2. Context Builder arma el contexto
        # 3. Loop: LLM → tools → LLM → ... → respuesta final
        # 4. Trace Recorder guarda todo
        ...
```

### Control Flow del harness

```
max_iterations: 15      # definido en agent.yaml
timeout_per_tool: 30s   # por comando
max_output_size: 10KB   # trunca outputs grandes de comandos
stop_conditions:
  - stop_reason == "stop"    # LLM terminó normalmente
  - iterations >= max        # límite de seguridad
  - is_error and no_retry    # error no recuperable
```

### Principio de diseño

```
"Anytime you find an agent makes a mistake, you take the time
 to engineer a solution so that the agent never makes that
 specific mistake again." — Mitchell Hashimoto (Harness Engineering)
```

Los errores se documentan en este archivo y se corrigen en el harness,
no solo en el prompt.

---

## 7. Context Engineering

### Anatomía del contexto en cada turno

```
┌─────────────────────────────────────────┐
│  SYSTEM PROMPT (agent.yaml)             │  ~200 tokens — siempre presente
├─────────────────────────────────────────┤
│  SKILL BODY (si hay match)              │  ~500-1500 tokens — on demand
├─────────────────────────────────────────┤
│  HISTORIAL (últimos N mensajes)         │  configurable — max_history_messages
├─────────────────────────────────────────┤
│  TOOL RESULTS (turno actual)            │  variable — solo el turno presente
├─────────────────────────────────────────┤
│  MENSAJE DEL USUARIO                    │  variable
└─────────────────────────────────────────┘
```

### Reglas del context

```python
# loop/context.py

MAX_HISTORY    = agent.yaml → context.max_history_messages  # default: 10
SKILL_TOKENS   = ~30-50 tokens por skill en startup (solo name+description)
FULL_SKILL     = carga completa solo cuando matcher confirma match

# Context Poisoning Prevention:
# Si un tool retorna error → se marca is_error=True en el mensaje
# El sistema prompt instruye al LLM a no asumir éxito ante errores
```

### Lo que NUNCA va en el contexto

```
✗ Contenido completo de archivos grandes (>50KB)
✗ Outputs completos de comandos >10KB (se truncan)
✗ Skills que no corresponden al turno actual
✗ Historial más antiguo que max_history_messages
```

---

## 8. Skills System

### Especificación

Basado en el **Agent Skills Open Standard** (Anthropic, Dic 2025).
Formato definido en agentskills.io.

### Estructura de archivos

```
skills/
├── file-management/
│   └── SKILL.md
├── command-execution/
│   └── SKILL.md
└── document-creation/
    └── SKILL.md
```

### Formato de SKILL.md

```markdown
---
name: "nombre-skill"
version: "1.0.0"
description: >-
  Descripción precisa de cuándo activar esta skill.
  Esta descripción es lo que el matcher compara contra
  el mensaje del usuario. Debe ser específica y clara.
tags: [tag1, tag2]
---

## Context
Rol y conocimiento de dominio para esta skill.

## Instructions
Pasos concretos que el agente debe seguir.

## Constraints
Reglas duras — lo que el agente NUNCA debe hacer en esta skill.

## Examples
Ejemplos de input → acción esperada.
```

### Cómo funciona el loader

```python
# agent/skills/loader.py

# Startup: carga solo frontmatter de cada SKILL.md
# ~30-50 tokens por skill — progressive disclosure

# On match: carga el body completo
# Se inyecta en el contexto ANTES del historial
```

### Cómo funciona el matcher

```python
# agent/skills/matcher.py

# Compara el mensaje del usuario contra cada description
# Estrategia v1: keyword matching simple y rápido
# Estrategia v2 (Fase 2): LLM-based matching para mayor precisión

# Retorna: skill_name | None
```

---

## 9. Tools y Niveles de Seguridad

### Niveles de seguridad (configurados en agent.yaml)

```yaml
security:
  levels:
    safe:      [cat, ls, grep, find, head, tail, wc, pwd, echo,
                date, which, file, stat, du, df, sort, uniq, cut]
    moderate:  [touch, mkdir, cp, mv, chmod, ln]
    dangerous: [rm, rmdir, dd, truncate]
    blocked:   [sudo, su, bash, sh, python, pip, apt, curl,
                wget, nc, eval, exec, source, chmod +x]

  require_confirmation: [dangerous]
  timeout_seconds:
    safe:      10
    moderate:  30
    dangerous: 60
```

### PathSafeguard

```python
# agent/tools/base.py — PathSafeguard

# Valida cada path antes de cualquier operación:
# 1. Resuelve path absoluto con Path.resolve()
# 2. Verifica que no esté en blocked_paths del agent.yaml
# 3. Si está bloqueado → ToolResult(is_error=True)
```

### Confirmación para operaciones DANGEROUS

El system prompt instruye al LLM a pedir confirmación explícita
del usuario ANTES de llamar tools con nivel DANGEROUS (rm, dd, etc.).
La confirmación la maneja el LLM en la conversación, no el código.

---

## 10. Traces y Observabilidad

### ¿Qué es un trace en este agente?

Un registro completo de un turno conversacional — desde que el usuario
escribe hasta que el agente responde. Incluye cada llamada al LLM,
cada tool ejecutado y sus duraciones.

### Estructura de un trace (Pydantic v2)

```python
# agent/traces/models.py

class ToolTrace(BaseModel):
    name: str
    input: dict
    output: str
    is_error: bool
    duration_ms: int

class LLMCallTrace(BaseModel):
    model: str
    tokens_in: int       # si Ollama los retorna
    tokens_out: int
    stop_reason: str
    duration_ms: int

class TurnTrace(BaseModel):
    turn_id: str         # UUID
    timestamp: str       # ISO 8601
    user_message: str
    skill_activated: str | None
    llm_calls: list[LLMCallTrace]
    tool_calls: list[ToolTrace]
    final_response: str
    total_duration_ms: int
    total_llm_calls: int
    total_tool_calls: int
    had_errors: bool
```

### Almacenamiento

```
traces/
└── 2026-06-04.jsonl    ← un archivo por día
                           un JSON por línea por turno
```

### ¿Por qué .jsonl?

- Append-only: no sobreescribe, agrega al final
- Una línea = un turno = un JSON completo
- Fácil de leer con `tail -f traces/2026-06-04.jsonl`
- Fácil de procesar con `jq` o Python

---

## 11. Memoria Persistente

### Fase 1 — Sin memoria (scaffold presente)

```python
# agent/memory/store.py — scaffold para Fase 2

class MarkdownMemoryStore:
    """
    Fase 2: Memoria persistente en archivos Markdown.
    
    Estructura planeada:
    memory/
    ├── sessions/
    │   └── {session_id}.md     ← resumen de sesión
    ├── facts/
    │   └── {topic}.md          ← hechos extraídos
    └── index.md                ← índice de memorias
    
    Fase 3: Migrar a SQLite para queries estructuradas.
    """
    enabled: bool = False
```

### Fase 2 — Markdown Memory

- Resúmenes automáticos de sesión al finalizar
- Extracción de hechos relevantes por tópico
- Índice de memorias para búsqueda rápida
- Sin dependencias externas — solo pathlib + markdown

### Fase 3 — SQLite Migration

- Misma interfaz, diferente backend
- Queries estructuradas para recuperación semántica

---

## 12. Estructura del Proyecto

```
file-agent/
│
├── AGENT.md               ← este documento (source of truth)
├── agent.yaml             ← config del agente: modelo, opciones, security
├── pyproject.toml         ← dependencias + pytest config
├── .env                   ← API keys (NO en git)
├── .env.example           ← template sin valores reales
├── .gitignore
│
├── skills/                ← archivos SKILL.md
│   ├── file-management/
│   │   └── SKILL.md
│   ├── command-execution/
│   │   └── SKILL.md
│   └── document-creation/
│       └── SKILL.md
│
├── traces/                ← generado en runtime
│   └── YYYY-MM-DD.jsonl
│
├── memory/                ← generado en Fase 2
│
└── agent/                 ← código fuente
    ├── __init__.py
    ├── main.py            ← entry point: Rich REPL + asyncio.run()
    │
    ├── core/
    │   ├── __init__.py
    │   ├── config.py      ← load agent.yaml + .env con Pydantic v2
    │   └── constants.py   ← enums: SecurityLevel, StopReason, SkillStatus
    │
    ├── skills/
    │   ├── __init__.py
    │   ├── loader.py      ← lee SKILL.md files, parsea frontmatter YAML
    │   └── matcher.py     ← match user message → skill name | None
    │
    ├── tools/
    │   ├── __init__.py
    │   ├── base.py        ← BaseTool, ToolResult, PathSafeguard
    │   ├── registry.py    ← ToolRegistry: register + execute
    │   ├── file_tools.py  ← 8 tools de archivos con pathlib + asyncio.to_thread
    │   └── command_tool.py ← run_command con validación SAFE/MODERATE/DANGEROUS/BLOCKED
    │
    ├── llm/
    │   ├── __init__.py
    │   └── client.py      ← OllamaClient: AsyncClient wrapper + parse tool_calls
    │
    ├── loop/
    │   ├── __init__.py
    │   ├── harness.py     ← AgentHarness: loop agéntico principal
    │   └── context.py     ← ConversationContext: historial + skill injection
    │
    ├── traces/
    │   ├── __init__.py
    │   ├── models.py      ← TurnTrace, LLMCallTrace, ToolTrace (Pydantic v2)
    │   └── recorder.py    ← async writer a .jsonl
    │
    └── memory/
        ├── __init__.py
        └── store.py       ← scaffold Fase 2
```

---

## 13. Convenciones de Código

### Naming

```python
snake_case          # variables, funciones, archivos
PascalCase          # clases, modelos Pydantic
SCREAMING_SNAKE     # constantes
kebab-case          # nombres de skills y directorios
```

### Async

```python
# SIEMPRE — toda operación I/O es async
async def read_file(path: str) -> ToolResult:
    content = await asyncio.to_thread(Path(path).read_text)
    ...

# Para comandos shell
proc = await asyncio.create_subprocess_exec(
    *cmd_parts,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
```

### Pydantic v2

```python
# Todos los modelos con model_config cuando aplica
class TurnTrace(BaseModel):
    model_config = ConfigDict(frozen=True)
    
    turn_id: str
    timestamp: str
    ...

# Field con descripción en modelos de API
class ToolResult(BaseModel):
    tool_use_id: str = Field(..., description="ID del tool call del LLM")
    content: str    = Field(..., description="Resultado de la ejecución")
    is_error: bool  = Field(default=False)
```

### Error Handling

```python
# SIEMPRE específico, NUNCA silencioso
try:
    result = await asyncio.to_thread(Path(path).read_text)
except PermissionError as e:
    return ToolResult(tool_use_id=tid, content=f"Permission denied: {path}", is_error=True)
except FileNotFoundError:
    return ToolResult(tool_use_id=tid, content=f"File not found: {path}", is_error=True)

# NUNCA:
except Exception:
    pass  ← prohibido
```

### Type hints

```python
# SIEMPRE en funciones públicas — Python 3.11+ nativo
async def execute(self, tool_use_id: str, **kwargs) -> ToolResult: ...
def get_schemas(self) -> list[dict]: ...
def match(self, message: str) -> str | None: ...
```

---

## 14. Variables de Entorno

```bash
# .env.example

# === Ollama Cloud ===
OLLAMA_API_KEY=           # API key de Ollama Cloud — REQUERIDA
OLLAMA_HOST=https://ollama.com

# === Agent Config ===
AGENT_YAML_PATH=agent.yaml   # path al archivo de config
LOG_LEVEL=INFO               # DEBUG | INFO | WARNING | ERROR

# === Traces ===
TRACES_DIR=./traces          # directorio para .jsonl files

# === Memory (Fase 2) ===
MEMORY_DIR=./memory          # directorio para archivos .md
```

---

## 15. Fases de Desarrollo

### Fase 1 — Agente Base (ACTUAL)

```
✅ Loop agéntico async sin frameworks
✅ Tools: file_tools (8) + command_tool (1 con niveles de seguridad)
✅ Skills system con progressive disclosure
✅ Traces completos en .jsonl
✅ Rich terminal UI
✅ Config completa desde agent.yaml
✅ Pydantic v2 en todo el borde
✅ Memory scaffold (deshabilitado)
```

### Fase 2 — Memoria Persistente + Traces Avanzados

```
⬜ MarkdownMemoryStore: resúmenes de sesión automáticos
⬜ Extracción de hechos relevantes por tópico
⬜ Skill matcher con LLM (mayor precisión)
⬜ Traces con visualización Rich en terminal
⬜ Búsqueda en historial de traces
⬜ Session IDs persistentes entre reinicios
```

### Fase 3 — Playwright (Browser Interaction)

```
⬜ BrowserTool: navigate, click, type, screenshot, extract
⬜ Nueva skill: web-navigation/SKILL.md
⬜ Computer use pattern: screenshot → LLM → acción
⬜ Session de browser persistente por conversación
⬜ Integración con traces: cada acción de browser registrada
```

---

## 16. Decisiones Rechazadas

| Tecnología / Decisión | Razón del rechazo |
|-----------------------|-------------------|
| **LangChain / LlamaIndex** | Abstracción innecesaria. Harness propio da control total |
| **OpenAI Agents SDK** | Framework externo. Queremos el loop bajo nuestro control |
| **Anthropic SDK** | Reemplazado por Ollama como provider principal |
| **parse_terminal_input** | El LLM maneja sus propios tipos de output |
| **ChromaDB / sqlite-vec** | Sin necesidad de vector search en Fase 1 |
| **Redis / cache** | Sin evidencia de necesidad sin datos de uso reales |
| **Docker en Fase 1** | Frena iteración. Se añade cuando el código esté terminado |
| **JWT / OAuth** | OLLAMA_API_KEY en .env es suficiente para Fase 1 |
| **Multi-provider LLM** | Ollama Cloud es el provider. Anthropic se añade en Fase 2 si aplica |
| **ReAct pattern (JSON en prompt)** | gpt-oss:20b confirmado con tool calling nativo |
| **Streaming en tool calls** | Streaming solo para respuestas finales de texto |
| **Sync subprocess** | asyncio.create_subprocess_exec es la única opción aceptable |

---

*Fin del documento — AGENT.md v1.0.0*
*Cualquier cambio de arquitectura o scope se documenta aquí antes de tocar código.*