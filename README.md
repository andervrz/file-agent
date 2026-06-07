# 🤖 File Agent

> Agente de gestión de archivos y terminal con lenguaje natural — sin frameworks, 100% async.

## ¿Qué es?

File Agent es un agente de productividad que corre desde la terminal y permite gestionar archivos,
ejecutar comandos shell, crear documentos office, controlar versiones con git y más —
todo usando lenguaje natural en español o inglés.

Construido desde cero sobre el SDK de Ollama, sin LangChain ni frameworks agenticos.
El harness controla. El LLM razona.

---

## Stack

| Componente | Tecnología |
|------------|-----------|
| LLM | `gpt-oss:20b` vía Ollama Cloud |
| Loop agéntico | Harness propio — sin frameworks |
| Memoria | TinyDB (JSON local) |
| Terminal UI | Rich |
| Validación | Pydantic v2 |
| Config | YAML + pydantic-settings |
| Package manager | uv |

---

## Capacidades

### Tools disponibles

| Tool | Descripción |
|------|-------------|
| `create_file` | Crea archivos con contenido |
| `read_file` | Lee archivos (límite 50KB) |
| `list_directory` | Lista directorios con tamaños |
| `move_file` | Mueve o renombra |
| `copy_file` | Copia preservando metadata |
| `delete_file` | Elimina con confirmación |
| `create_directory` | Crea directorios |
| `search_files` | Busca por patrón glob |
| `run_command` | Shell con niveles SAFE/MODERATE/DANGEROUS |
| `backup` | Backup comprimido con timestamp |
| `git` | Control completo de git (status, add, commit, push, pull, clone...) |
| `read_pdf` | Extrae texto de PDFs |
| `create_word` | Crea documentos Word (.docx) |
| `create_excel` | Crea hojas Excel (.xlsx) |
| `create_presentation` | Crea presentaciones PowerPoint (.pptx) |
| `archive` | Crea, extrae y lista zip/tar.gz |
| `create_from_template` | Crea archivos desde plantillas |
| `diff_files` | Compara dos archivos de texto |
| `find_in_files` | Busca texto dentro de archivos |

### Seguridad de comandos shell

```
SAFE      → cat, ls, grep, find, head, tail, wc, pwd, echo...
MODERATE  → touch, mkdir, cp, mv, chmod...
DANGEROUS → rm, rmdir, dd, truncate (requiere confirmación)
BLOCKED   → sudo, bash, sh, curl, wget, pip...
```

### Skills (context engineering)

El agente activa skills específicas según el contexto:

- `file-management` — gestión de archivos y directorios
- `command-execution` — comandos de terminal
- `document-creation` — documentos markdown y texto
- `document-management` — Word, Excel, PPTX, PDF
- `version-control` — git y backups

### Comandos del REPL

```
/help              → panel de ayuda
/traces            → últimos 3 traces del día
/traces N          → últimos N traces
/stats             → estadísticas de la sesión
/memory            → hechos guardados en memoria
/memory buscar X   → buscar en memoria
/memory clear      → limpiar memoria
/model             → modelo activo y config
/clear             → limpiar contexto
/exit              → salir
```

---

## Instalación

### Prerrequisitos

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) instalado
- Cuenta en [Ollama Cloud](https://ollama.com) con API key

### Setup

```bash
# 1. Clonar el repositorio
git clone https://github.com/andervrz/file-agent.git
cd file-agent

# 2. Crear entorno virtual e instalar dependencias
uv sync

# 3. Configurar variables de entorno
cp .env.example .env
# Editar .env y agregar tu OLLAMA_API_KEY

# 4. Activar entorno
source .venv/bin/activate
```

### Variables de entorno

```bash
# .env
OLLAMA_API_KEY=tu_api_key_de_ollama_cloud
OLLAMA_HOST=https://ollama.com
AGENT_YAML_PATH=agent.yaml
TRACES_DIR=./traces
LOG_LEVEL=INFO
```

---

## Uso

```bash
uv run python -m agent.main
```

### Ejemplos

```
❯ lista los archivos en Downloads
❯ mueve todos los .py de Downloads a python_moduls/
❯ haz un backup del proyecto file-agent
❯ git status
❯ git commit -m "feat: nueva funcionalidad"
❯ crea un Word con el informe del mes
❯ léeme el PDF curriculum.pdf
❯ busca 'asyncio' en todos los archivos .py
❯ compara config_old.yaml con config_new.yaml
❯ crea un README para mi proyecto
```

---

## Estructura del Proyecto

```
file-agent/
├── AGENT.md                ← arquitectura y principios
├── MODULE_MAP.md           ← mapa de módulos Fase 1
├── MODULE_MAP_PHASE2.md    ← mapa de módulos Fase 2
├── MODULE_MAP_PHASE2_5.md  ← mapa de módulos Fase 2.5
├── PHASE_2.md              ← spec Fase 2
├── PHASE_2_5.md            ← spec Fase 2.5
├── agent.yaml              ← config del agente
├── pyproject.toml
├── .env.example
│
├── skills/                 ← skills SKILL.md
│   ├── file-management/
│   ├── command-execution/
│   ├── document-creation/
│   ├── document-management/
│   ├── version-control/
│   └── templates/          ← plantillas para create_from_template
│
└── agent/
    ├── main.py             ← entry point
    ├── core/               ← config, constants
    ├── cli/                ← REPL, display, commands
    ├── tools/              ← todos los tools
    ├── llm/                ← cliente Ollama
    ├── loop/               ← harness agéntico, context
    ├── skills/             ← loader, matcher
    ├── traces/             ← recorder, models
    └── memory/             ← TinyDB store
```

---

## Fases de Desarrollo

| Fase | Estado | Descripción |
|------|--------|-------------|
| **Fase 1** | ✅ Completa | Loop agéntico, 9 tools, skills, traces, 206 tests |
| **Fase 2** | ✅ Completa | TinyDB memory, CLI Rich, /commands |
| **Fase 2.5** | ✅ Completa | 10 tools nuevos: git, PDF, Office, archive, templates... |
| **Fase 3** | 🔄 Planificada | Playwright — interacción con el navegador |

---

## Tests

```bash
uv run pytest tests/ -v
```

206 tests passing en Fase 1. Tests de Fase 2.5 en progreso.

---

## Principios de Diseño

```
1. El harness controla. El LLM razona.
2. Sin frameworks — SDK directo a Ollama.
3. Async 100% — ningún I/O bloquea el event loop.
4. Pydantic v2 en todo el borde.
5. Config sobre código — agent.yaml es la fuente de verdad.
6. Progressive disclosure — skills cargan solo cuando hay match.
7. Fail loudly — errores explícitos, nunca silenciosos.
```

---

## Autor

**@andervrz** — AI Engineer en construcción.
Proyecto construido como portfolio de agentic AI engineering.

---

## Licencia

MIT
