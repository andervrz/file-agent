# MODULE_MAP.md — File Agent
## Mapa de Módulos: Clases, Funciones y Conexiones

> **Propósito:** Referencia técnica de cada módulo del proyecto.
> Qué contiene, qué hace, cómo se conecta con el resto del sistema.
> Leer junto con AGENT.md antes de escribir código.

---

## Diagrama de Dependencias

```
main.py
  └── AgentHarness (loop/harness.py)
        ├── OllamaClient       (llm/client.py)
        │     └── AsyncClient  (ollama SDK)
        ├── SkillMatcher       (skills/matcher.py)
        │     └── SkillLoader  (skills/loader.py)
        ├── ConversationContext (loop/context.py)
        ├── ToolRegistry       (tools/registry.py)
        │     ├── FileTools    (tools/file_tools.py)
        │     │     └── PathSafeguard (tools/base.py)
        │     └── CommandTool  (tools/command_tool.py)
        │           └── PathSafeguard (tools/base.py)
        └── TraceRecorder      (traces/recorder.py)
              └── TurnTrace    (traces/models.py)

AgentConfig + Settings  (core/config.py)  ← inyectado en todos
SecurityLevel, StopReason, SkillStatus    ← importado donde se necesita
```

---

## Módulos Raíz del Proyecto

---

### `agent.yaml`

**Tipo:** Archivo de configuración YAML — no es código Python.

**Propósito:** Define toda la configuración del agente sin tocar código.
Es la única fuente de verdad para comportamiento configurable.

**Secciones:**

```yaml
agent:          # nombre, versión, descripción
llm:            # provider, model, temperature, num_ctx, num_predict, host
system_prompt:  # string multilinea — identidad y reglas del agente
tools:
  enabled: []   # lista de tools activos
context:
  max_history_messages: 10
  max_iterations: 15
skills:
  path: ./skills   # directorio donde viven los SKILL.md
memory:
  enabled: false
  path: ./memory
traces:
  enabled: true
  path: ./traces
security:
  levels:
    safe:      [cat, ls, grep, ...]
    moderate:  [touch, mkdir, cp, ...]
    dangerous: [rm, rmdir, dd, ...]
    blocked:   [sudo, bash, sh, ...]
  require_confirmation: [dangerous]
  blocked_paths:
    - /etc
    - /sys
    - /usr
    - /bin
  timeout_seconds:
    safe: 10
    moderate: 30
    dangerous: 60
```

**Conectado a:** `core/config.py` lo lee y lo convierte en modelos Pydantic.

---

### `pyproject.toml`

**Propósito:** Dependencias del proyecto y config de pytest.

```toml
[project.dependencies]
ollama            # AsyncClient para Ollama Cloud
pydantic>=2.0     # validación
pydantic-settings # carga .env
pyyaml>=6.0       # parsea agent.yaml y SKILL.md frontmatter
rich>=13.0        # terminal UI

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["."]
```

---

## `agent/core/`

---

### `agent/core/config.py`

**Propósito:** Carga `agent.yaml` y `.env`. Provee configuración tipada
con Pydantic v2 a todo el sistema. Punto de entrada único para config.

**Modelos Pydantic (todos `BaseModel`):**

```python
class LLMConfig(BaseModel):
    provider: str          # "ollama"
    host: str              # "https://ollama.com"
    model: str             # "gpt-oss:20b"
    temperature: float     # 0.1
    num_ctx: int           # 4096
    num_predict: int       # 1024

class ContextConfig(BaseModel):
    max_history_messages: int   # 10
    max_iterations: int         # 15

class SkillsConfig(BaseModel):
    path: str              # "./skills"

class MemoryConfig(BaseModel):
    enabled: bool          # False en Fase 1
    path: str              # "./memory"

class TracesConfig(BaseModel):
    enabled: bool          # True
    path: str              # "./traces"

class SecurityConfig(BaseModel):
    levels: dict[str, list[str]]     # safe/moderate/dangerous/blocked → comandos
    require_confirmation: list[str]  # ["dangerous"]
    blocked_paths: list[str]         # ["/etc", "/sys", ...]
    timeout_seconds: dict[str, int]  # safe:10, moderate:30, dangerous:60

class ToolsConfig(BaseModel):
    enabled: list[str]     # nombres de tools activos

class AgentMeta(BaseModel):
    name: str
    version: str
    description: str

class AgentConfig(BaseModel):
    """Configuración completa cargada desde agent.yaml."""
    agent: AgentMeta
    llm: LLMConfig
    system_prompt: str
    tools: ToolsConfig
    context: ContextConfig
    skills: SkillsConfig
    memory: MemoryConfig
    traces: TracesConfig
    security: SecurityConfig

class Settings(BaseSettings):
    """Variables de entorno desde .env."""
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ollama_api_key: str        # REQUERIDA
    ollama_host: str           # "https://ollama.com"
    agent_yaml_path: str       # "agent.yaml"
    traces_dir: str            # "./traces"
    log_level: str             # "INFO"
```

**Funciones:**

```python
def load_config(yaml_path: str | Path | None = None) -> tuple[AgentConfig, Settings]:
    """
    Lee agent.yaml + .env.
    Retorna (AgentConfig, Settings) como tupla.
    Lanza FileNotFoundError si agent.yaml no existe.
    Llamada UNA sola vez en main.py al arrancar.
    """
```

**Conectado a:**
- `main.py` → llama `load_config()` al startup
- Todos los módulos reciben `AgentConfig` y/o `Settings` via inyección de dependencia

---

### `agent/core/constants.py`

**Propósito:** Enums del dominio. Valores fijos que no cambian en runtime.
Importados donde se necesitan — sin instanciar nada.

**Enums:**

```python
class SecurityLevel(StrEnum):
    SAFE      = "safe"
    MODERATE  = "moderate"
    DANGEROUS = "dangerous"
    BLOCKED   = "blocked"

class StopReason(StrEnum):
    STOP          = "stop"        # LLM terminó normalmente
    TOOL_USE      = "tool_calls"  # LLM quiere llamar tools
    MAX_TOKENS    = "length"      # se cortó por tokens
    MAX_ITER      = "max_iter"    # harness impuso límite
    ERROR         = "error"       # error no recuperable

class SkillStatus(StrEnum):
    MATCHED   = "matched"     # skill activada en este turno
    NO_MATCH  = "no_match"    # ninguna skill coincidió
    DISABLED  = "disabled"    # skills deshabilitadas en config
```

**Conectado a:**
- `tools/command_tool.py` → usa `SecurityLevel`
- `loop/harness.py` → usa `StopReason`
- `skills/matcher.py` → usa `SkillStatus`
- `traces/models.py` → usa todos como valores en traces

---

## `agent/skills/`

---

### `agent/skills/loader.py`

**Propósito:** Lee los archivos `SKILL.md` del directorio `skills/`.
En startup carga solo frontmatter (name + description).
On demand carga el body completo cuando hay match.

**Modelos:**

```python
class SkillMetadata(BaseModel):
    """Lo que se carga al startup — ~40 tokens."""
    name: str
    version: str
    description: str      # usado por el matcher
    tags: list[str]
    path: Path            # path al directorio de la skill

class LoadedSkill(BaseModel):
    """Skill completa cargada on demand."""
    metadata: SkillMetadata
    body: str             # contenido markdown completo del SKILL.md
```

**Funciones:**

```python
class SkillLoader:
    def __init__(self, skills_path: str | Path):
        self._path = Path(skills_path)

    def load_metadata(self) -> list[SkillMetadata]:
        """
        Startup: recorre skills/ y parsea solo el frontmatter YAML
        de cada SKILL.md. Retorna lista de SkillMetadata.
        Rápido y liviano — no carga los bodies.
        """

    def load_body(self, skill_name: str) -> str:
        """
        On demand: carga el body completo del SKILL.md
        cuando el matcher confirma un match.
        Retorna el contenido markdown sin el frontmatter.
        """
```

**Conectado a:**
- `skills/matcher.py` → recibe lista de `SkillMetadata`
- `loop/context.py` → recibe `body` para inyectar en contexto
- `core/config.py` → recibe `skills.path` de `AgentConfig`

---

### `agent/skills/matcher.py`

**Propósito:** Compara el mensaje del usuario contra las descriptions
de todas las skills disponibles. Retorna el nombre de la skill que
coincide o `None` si ninguna aplica.

**Lógica v1:** keyword matching simple — rápido y predecible.
**Lógica v2 (Fase 2):** LLM-based matching para mayor precisión.

**Clases:**

```python
class SkillMatcher:
    def __init__(self, skills: list[SkillMetadata]):
        self._skills = skills

    def match(self, user_message: str) -> SkillMetadata | None:
        """
        v1: Compara palabras clave del mensaje contra la
        description y tags de cada skill.

        Estrategia:
        1. Normaliza el mensaje (lowercase, strip)
        2. Para cada skill, extrae keywords de su description
        3. Cuenta matches — retorna la skill con mayor score
        4. Si score == 0 → retorna None

        Retorna SkillMetadata de la skill ganadora o None.
        """
```

**Conectado a:**
- `skills/loader.py` → recibe `list[SkillMetadata]` en __init__
- `loop/harness.py` → llama `match()` al inicio de cada turno
- `loop/context.py` → si hay match, pide el body al loader

---

## `agent/tools/`

---

### `agent/tools/base.py`

**Propósito:** Clases base que todos los tools heredan.
Define el contrato que el `ToolRegistry` espera.
`PathSafeguard` protege contra acceso a paths bloqueados.

**Modelos y Clases:**

```python
class ToolResult(BaseModel):
    """Resultado de ejecutar cualquier tool."""
    tool_use_id: str    # ID del tool call del LLM — para correlación
    content: str        # texto del resultado (éxito o error)
    is_error: bool = False

class BaseTool(ABC):
    """Contrato que todo tool debe implementar."""
    name: str           # identificador único — coincide con el schema
    description: str    # descripción para el LLM
    input_schema: dict  # JSON schema de los parámetros

    @abstractmethod
    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        """Ejecuta el tool. Siempre retorna ToolResult, nunca lanza."""

    def to_ollama_schema(self) -> dict:
        """
        Convierte el tool al formato que Ollama espera:
        {"type": "function", "function": {name, description, parameters}}
        """

class PathSafeguard:
    """
    Valida paths antes de cualquier operación de archivo.
    Inyectada en todos los file tools y command tool.
    """
    def __init__(self, blocked_paths: list[str]):
        self._blocked = [Path(p).resolve() for p in blocked_paths]

    def validate(self, path: str | Path) -> Path:
        """
        1. Resuelve el path absoluto con expanduser + resolve
        2. Verifica que no esté bajo ningún blocked_path
        3. Si está bloqueado → lanza PermissionError con mensaje claro
        4. Retorna el Path resuelto y validado
        """
```

**Conectado a:**
- Todos los tools heredan de `BaseTool`
- `tools/registry.py` → usa `BaseTool.to_ollama_schema()`
- `loop/harness.py` → recibe `ToolResult` después de cada ejecución
- `traces/models.py` → `ToolResult.content` y `is_error` van al trace

---

### `agent/tools/registry.py`

**Propósito:** Registro central de todos los tools disponibles.
El harness solo habla con el registry — nunca con tools directamente.
Encapsula el dispatch: nombre de tool → instancia correcta.

**Clases:**

```python
class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Registra un tool por su nombre."""

    def get_schemas(self) -> list[dict]:
        """
        Retorna todos los schemas en formato Ollama.
        Se pasa al LLM en cada llamada para que sepa
        qué tools puede usar.
        """

    async def execute(
        self,
        name: str,
        tool_use_id: str,
        **kwargs
    ) -> ToolResult:
        """
        Dispatch: busca el tool por nombre y llama execute().
        Si el tool no existe → retorna ToolResult(is_error=True).
        Nunca lanza excepción — siempre retorna ToolResult.
        """
```

**Conectado a:**
- `main.py` → registra todos los tools al startup
- `loop/harness.py` → llama `execute()` y `get_schemas()`
- `llm/client.py` → recibe `get_schemas()` para pasarlos al LLM

---

### `agent/tools/file_tools.py`

**Propósito:** Los 8 tools de gestión de archivos con `pathlib`.
Todas las operaciones son async via `asyncio.to_thread()`.
Cada tool usa `PathSafeguard` antes de operar.

**Clases (una por tool):**

```python
class CreateFileTool(BaseTool):
    name = "create_file"
    # Parámetros: path(str), content(str), overwrite(bool=False)
    # Crea directorios padre si no existen
    # Si ya existe y overwrite=False → error

class ReadFileTool(BaseTool):
    name = "read_file"
    # Parámetros: path(str)
    # Límite: 50KB — trunca con aviso si es más grande

class ListDirectoryTool(BaseTool):
    name = "list_directory"
    # Parámetros: path(str), show_hidden(bool=False)
    # Retorna: lista formateada con íconos 📁📄 y tamaños

class MoveFileTool(BaseTool):
    name = "move_file"
    # Parámetros: source(str), destination(str)
    # Usa shutil.move — funciona entre filesystems

class CopyFileTool(BaseTool):
    name = "copy_file"
    # Parámetros: source(str), destination(str)
    # Usa shutil.copy2 — preserva metadata

class DeleteFileTool(BaseTool):
    name = "delete_file"
    # Parámetros: path(str)
    # Solo elimina si el path existe y está validado

class CreateDirectoryTool(BaseTool):
    name = "create_directory"
    # Parámetros: path(str)
    # Usa mkdir(parents=True, exist_ok=True)

class SearchFilesTool(BaseTool):
    name = "search_files"
    # Parámetros: directory(str), pattern(str), recursive(bool=True)
    # Usa rglob o glob según recursive
    # Limita resultados a 50 matches
```

**Función factory:**

```python
def build_file_tools(
    safeguard: PathSafeguard,
    enabled: list[str]
) -> list[BaseTool]:
    """
    Crea e instancia solo los tools que están en
    enabled (lista de agent.yaml → tools.enabled).
    Retorna lista lista para registrar en ToolRegistry.
    """
```

**Conectado a:**
- `tools/base.py` → hereda `BaseTool`, usa `PathSafeguard`, retorna `ToolResult`
- `tools/registry.py` → registrado aquí
- `main.py` → `build_file_tools()` llamado al startup
- `core/config.py` → recibe `SecurityConfig.blocked_paths` para `PathSafeguard`

---

### `agent/tools/command_tool.py`

**Propósito:** Ejecuta comandos de shell con validación de niveles
de seguridad. Un solo tool con lógica de dispatch interno.
Usa `asyncio.create_subprocess_exec()` — 100% async.

**Clases:**

```python
class CommandValidator:
    """
    Valida un comando contra los niveles de seguridad
    definidos en agent.yaml antes de ejecutarlo.
    """
    def __init__(self, security: SecurityConfig):
        self._security = security

    def validate(self, command: str) -> SecurityLevel:
        """
        1. Extrae el comando base (primera palabra)
        2. Busca en safe → moderate → dangerous → blocked
        3. Si está en blocked → lanza PermissionError
        4. Retorna el SecurityLevel del comando
        """

    def is_allowed(self, command: str) -> tuple[bool, SecurityLevel]:
        """
        Retorna (permitido: bool, nivel: SecurityLevel).
        blocked → (False, BLOCKED)
        resto   → (True, nivel correspondiente)
        """

class RunCommandTool(BaseTool):
    name = "run_command"
    description = "Ejecuta un comando de shell con validación de seguridad"
    # Parámetros: command(str)
    #
    # Flujo interno:
    # 1. CommandValidator.validate(command)
    # 2. Si BLOCKED → ToolResult(is_error=True, "Comando bloqueado")
    # 3. PathSafeguard.validate() si el comando opera sobre paths
    # 4. asyncio.create_subprocess_exec() con timeout según nivel
    # 5. Captura stdout + stderr
    # 6. Trunca output >10KB con aviso
    # 7. Retorna ToolResult con output

    async def execute(self, tool_use_id: str, command: str) -> ToolResult:
        ...
```

**Función factory:**

```python
def build_command_tool(
    security: SecurityConfig,
    safeguard: PathSafeguard
) -> RunCommandTool:
    """Instancia RunCommandTool con su validador y safeguard."""
```

**Conectado a:**
- `tools/base.py` → hereda `BaseTool`, usa `PathSafeguard`
- `tools/registry.py` → registrado aquí
- `core/config.py` → recibe `SecurityConfig` con los niveles
- `core/constants.py` → usa `SecurityLevel` enum

---

## `agent/llm/`

---

### `agent/llm/client.py`

**Propósito:** Wrapper async del `AsyncClient` de Ollama.
Abstrae la API de Ollama y retorna tipos propios del proyecto.
Un solo lugar donde se hace la llamada al LLM.

**Dataclasses:**

```python
@dataclass
class ToolCall:
    """Un tool call parseado de la respuesta del LLM."""
    id: str       # generado localmente si Ollama no provee uno
    name: str     # nombre del tool
    input: dict   # argumentos para ejecutar el tool

@dataclass
class LLMResponse:
    """Respuesta normalizada del LLM."""
    stop_reason: str          # "stop" | "tool_calls" | "length"
    content: str              # texto de la respuesta (vacío si hay tool calls)
    tool_calls: list[ToolCall] # lista de tools a ejecutar (vacía si es texto)
    tokens_in: int            # 0 si Ollama no retorna usage
    tokens_out: int           # 0 si Ollama no retorna usage
    duration_ms: int          # tiempo de la llamada en milisegundos
```

**Clases:**

```python
class OllamaClient:
    def __init__(self, config: LLMConfig, api_key: str):
        self._client = AsyncClient(
            host=config.host,
            headers={"Authorization": f"Bearer {api_key}"}
        )
        self._config = config

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """
        Llama al LLM con el historial y los schemas de tools.

        1. Construye kwargs: model, messages, options, tools
        2. Mide tiempo con time.perf_counter()
        3. Llama await self._client.chat(**kwargs)
        4. Parsea response.message.tool_calls → list[ToolCall]
        5. Extrae content texto si no hay tool calls
        6. Retorna LLMResponse normalizado

        Nunca hace streaming aquí — streaming solo para
        respuestas finales en main.py.
        """
```

**Conectado a:**
- `loop/harness.py` → llama `complete()` en cada iteración
- `core/config.py` → recibe `LLMConfig`
- `tools/registry.py` → recibe `get_schemas()` para pasar al LLM
- `traces/models.py` → `LLMCallTrace` se construye con datos de `LLMResponse`

---

## `agent/loop/`

---

### `agent/loop/context.py`

**Propósito:** Gestiona el historial de la conversación.
Aplica el límite de `max_history_messages`.
Inyecta el body de la skill activa en el contexto correcto.
Previene context poisoning marcando errores explícitamente.

**Clases:**

```python
class ConversationContext:
    def __init__(self, max_history: int):
        self._max_history = max_history
        self._messages: list[dict] = []
        self._active_skill_body: str | None = None

    def set_skill(self, body: str | None) -> None:
        """
        Activa o desactiva una skill para el turno actual.
        El body se inyecta como parte del primer mensaje
        de usuario cuando se construye el contexto.
        """

    def add_user_message(self, text: str) -> None:
        """Agrega mensaje del usuario al historial."""

    def add_assistant_response(self, content: str) -> None:
        """Agrega respuesta del LLM al historial."""

    def add_tool_results(self, results: list[ToolResult]) -> None:
        """
        Agrega resultados de tools en formato Ollama:
        [{"role": "tool", "content": "...", "name": "..."}]
        Marca errores con prefijo [ERROR] para prevenir
        context poisoning.
        """

    def get_messages(self) -> list[dict]:
        """
        Retorna el historial listo para pasar a Ollama.
        Aplica _trim() para respetar max_history.
        Si hay skill activa, inyecta su body al inicio.
        """

    def clear(self) -> None:
        """Limpia historial manteniendo la skill activa."""

    def _trim(self) -> None:
        """
        Mantiene solo los últimos max_history * 2 mensajes.
        (max_history pares user/assistant)
        """
```

**Conectado a:**
- `loop/harness.py` → usa todos los métodos en cada iteración
- `skills/loader.py` → recibe el body via `set_skill()`
- `tools/base.py` → recibe `list[ToolResult]` en `add_tool_results()`
- `core/config.py` → recibe `ContextConfig.max_history_messages`

---

### `agent/loop/harness.py`

**Propósito:** El corazón del agente. Orquesta el loop agéntico completo.
Python controla el flujo — el LLM solo razona y decide qué tools llamar.
Un turno de usuario = un `run()` completo.

**Clases:**

```python
class AgentHarness:
    def __init__(
        self,
        config: AgentConfig,
        llm: OllamaClient,
        tool_registry: ToolRegistry,
        skill_loader: SkillLoader,
        skill_matcher: SkillMatcher,
        context: ConversationContext,
        trace_recorder: TraceRecorder,
    ):
        # Todos los componentes inyectados — sin imports directos

    async def run(self, user_message: str) -> str:
        """
        Loop agéntico completo para un turno del usuario.

        FLUJO:
        1.  Skill matching: matcher.match(user_message)
            └── Si match → loader.load_body() → context.set_skill()
        2.  context.add_user_message(user_message)
        3.  Inicializa TurnTrace para observabilidad
        4.  LOOP (max_iterations):
            a. llm.complete(context.get_messages(), tool_registry.get_schemas())
            b. Registra LLMCallTrace
            c. Si stop_reason == STOP:
               └── context.add_assistant_response()
               └── Guarda TurnTrace
               └── Retorna response.content
            d. Si stop_reason == TOOL_USE:
               └── Para cada tool_call:
                   ├── tool_registry.execute(name, id, **input)
                   ├── Registra ToolTrace
                   └── context.add_tool_results([result])
               └── Continúa loop
            e. Si stop_reason == MAX_TOKENS:
               └── Retorna con aviso de truncamiento
        5.  Si itera == max_iterations:
            └── Retorna "⚠️ Máximo de iteraciones alcanzado"
        6.  trace_recorder.record(turn_trace) — siempre, incluso con error

        INVARIANTES:
        - Nunca lanza excepción al llamador (main.py)
        - Siempre retorna un string
        - Siempre guarda el trace
        """

    def reset(self) -> None:
        """Limpia el contexto para empezar conversación nueva."""
```

**Conectado a:**
- `llm/client.py` → llama `complete()` en el loop
- `tools/registry.py` → llama `execute()` y `get_schemas()`
- `skills/matcher.py` → llama `match()` al inicio de cada turno
- `skills/loader.py` → llama `load_body()` si hay match
- `loop/context.py` → usa todos sus métodos
- `traces/recorder.py` → llama `record()` al final de cada turno
- `traces/models.py` → construye `TurnTrace` durante el loop
- `core/constants.py` → usa `StopReason` para evaluar stop conditions

---

## `agent/traces/`

---

### `agent/traces/models.py`

**Propósito:** Modelos Pydantic v2 que representan la estructura
de un trace completo. Son inmutables (frozen=True) — se crean
al finalizar el turno, no se modifican.

**Modelos:**

```python
class ToolTrace(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str              # nombre del tool ejecutado
    input: dict            # argumentos que recibió
    output: str            # resultado (truncado si >500 chars)
    is_error: bool         # True si hubo error
    duration_ms: int       # cuánto tardó la ejecución

class LLMCallTrace(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str             # "gpt-oss:20b"
    tokens_in: int         # tokens de input (0 si no disponible)
    tokens_out: int        # tokens de output
    stop_reason: str       # "stop" | "tool_calls" | "length"
    duration_ms: int       # latencia de la llamada

class TurnTrace(BaseModel):
    model_config = ConfigDict(frozen=True)

    turn_id: str                    # UUID — identifica el turno
    timestamp: str                  # ISO 8601 — cuándo ocurrió
    user_message: str               # qué escribió el usuario
    skill_activated: str | None     # nombre de la skill o None
    llm_calls: list[LLMCallTrace]   # todas las llamadas al LLM
    tool_calls: list[ToolTrace]     # todos los tools ejecutados
    final_response: str             # respuesta final al usuario
    total_duration_ms: int          # tiempo total del turno
    total_llm_calls: int            # cuántas veces llamó al LLM
    total_tool_calls: int           # cuántos tools ejecutó
    had_errors: bool                # True si algún tool tuvo error
```

**Conectado a:**
- `loop/harness.py` → construye las instancias durante el loop
- `traces/recorder.py` → recibe `TurnTrace` para escribir a disco
- `core/constants.py` → usa valores de enums en los campos

---

### `agent/traces/recorder.py`

**Propósito:** Escribe los traces a disco en formato `.jsonl`.
Un archivo por día. Una línea JSON por turno.
Async — no bloquea el event loop.
Crea el directorio si no existe.

**Clases:**

```python
class TraceRecorder:
    def __init__(self, traces_path: str | Path, enabled: bool):
        self._path = Path(traces_path)
        self._enabled = enabled

    async def record(self, trace: TurnTrace) -> None:
        """
        Si enabled=False → no hace nada (traces deshabilitados).

        1. Genera filename: traces/YYYY-MM-DD.jsonl
        2. Crea directorio si no existe
        3. Serializa TurnTrace a JSON con model_dump_json()
        4. Hace append a .jsonl via asyncio.to_thread()
           (una línea JSON por turno)
        Nunca lanza excepción — error de escritura se loguea
        pero no interrumpe el agente.
        """

    def _get_file_path(self) -> Path:
        """Retorna path del archivo del día actual: YYYY-MM-DD.jsonl"""
```

**Conectado a:**
- `loop/harness.py` → llamado al final de cada turno con `TurnTrace`
- `traces/models.py` → recibe `TurnTrace` para serializar
- `core/config.py` → recibe `TracesConfig.path` y `TracesConfig.enabled`

---

## `agent/memory/`

---

### `agent/memory/store.py`

**Propósito:** Scaffold para la memoria persistente de Fase 2.
En Fase 1 todas las operaciones son no-ops (enabled=False).
La interfaz está definida para que Fase 2 solo implemente el cuerpo.

**Clases:**

```python
class MarkdownMemoryStore:
    """
    Fase 2: Memoria persistente en archivos Markdown.

    Estructura planeada:
    memory/
    ├── sessions/
    │   └── {session_id}.md   ← resumen de cada sesión
    ├── facts/
    │   └── {topic}.md        ← hechos extraídos por tópico
    └── index.md              ← índice searchable

    Fase 3: Migrar a SQLite manteniendo la misma interfaz.
    """
    def __init__(self, path: str | Path, enabled: bool = False):
        self._path = Path(path)
        self._enabled = enabled

    async def save(self, key: str, content: str) -> None:
        """Fase 2: guarda una entrada de memoria."""
        if not self._enabled:
            return
        # TODO Fase 2

    async def load(self, key: str) -> str | None:
        """Fase 2: carga una entrada de memoria por key."""
        if not self._enabled:
            return None
        # TODO Fase 2

    async def search(self, query: str) -> list[str]:
        """Fase 2: busca memorias por contenido."""
        if not self._enabled:
            return []
        # TODO Fase 2
```

**Conectado a:**
- `loop/harness.py` → instanciado pero no usado activamente en Fase 1
- `core/config.py` → recibe `MemoryConfig.path` y `MemoryConfig.enabled`

---

## `agent/main.py`

**Propósito:** Entry point del agente. Bootstrap de todos los componentes.
REPL loop con Rich UI. Manejo de comandos especiales.
La única función sync es `main()` — todo lo demás es async.

**Funciones:**

```python
async def bootstrap() -> AgentHarness:
    """
    Inicializa todos los componentes en orden correcto:

    1. load_config()                    → AgentConfig + Settings
    2. PathSafeguard(blocked_paths)     → para todos los tools
    3. build_file_tools(safeguard)      → lista de FileTool
    4. build_command_tool(security)     → RunCommandTool
    5. ToolRegistry() + register()      → registry listo
    6. OllamaClient(config, api_key)    → cliente LLM
    7. SkillLoader(skills_path)         → carga metadata
    8. SkillMatcher(skills_metadata)    → listo para matching
    9. ConversationContext(max_history) → historial vacío
    10. TraceRecorder(traces_path)      → writer listo
    11. AgentHarness(todos los anteriores) → agente listo

    Retorna AgentHarness configurado.
    """

async def async_main() -> None:
    """
    Loop principal del REPL:

    1. Bootstrap → AgentHarness
    2. Muestra banner con Rich
    3. LOOP:
       a. Prompt.ask() via asyncio.to_thread (no bloquea)
       b. Comandos especiales: exit, clear, help
       c. harness.run(user_input) con spinner Rich
       d. Muestra respuesta en Panel Rich
       e. Captura KeyboardInterrupt limpiamente
    """

def main() -> None:
    """Entry point sync. Llama asyncio.run(async_main())."""
```

**Comandos especiales del REPL:**

```
exit / quit   → cierra el agente limpiamente
clear         → harness.reset() + limpia terminal
help          → muestra panel con capacidades del agente
```

**Conectado a:**
- `core/config.py` → llama `load_config()` al arrancar
- `loop/harness.py` → instancia y llama `run()` en el loop
- Todos los tools → registrados en `bootstrap()`
- `skills/loader.py` → instanciado en `bootstrap()`
- `skills/matcher.py` → instanciado en `bootstrap()`
- `traces/recorder.py` → instanciado en `bootstrap()`

---

## Flujo Completo — Un Turno

```
Usuario escribe: "busca todos los archivos .py en este directorio"
       │
       ▼
main.py: harness.run("busca todos los archivos .py...")
       │
       ▼
harness.py: matcher.match(message)
       │   → keywords: "busca", "archivos", ".py"
       │   → match: "file-management" skill
       │
       ▼
harness.py: loader.load_body("file-management")
       │   → body del SKILL.md completo
       │
       ▼
context.py: set_skill(body) + add_user_message(message)
       │
       ▼
harness.py: llm.complete(context.get_messages(), registry.get_schemas())
       │   → Ollama Cloud: gpt-oss:20b
       │   → stop_reason: "tool_calls"
       │   → tool_calls: [ToolCall(name="search_files", input={...})]
       │
       ▼
harness.py: registry.execute("search_files", id, directory=".", pattern="*.py")
       │
       ▼
file_tools.py: SearchFilesTool.execute()
       │   → safeguard.validate(".")         → OK
       │   → asyncio.to_thread(rglob, "*.py") → lista de archivos
       │   → ToolResult(content="Found 12 files: ...")
       │
       ▼
context.py: add_tool_results([result])
       │
       ▼
harness.py: llm.complete(context.get_messages(), ...)  ← segunda llamada
       │   → stop_reason: "stop"
       │   → content: "Encontré 12 archivos Python: ..."
       │
       ▼
harness.py: trace_recorder.record(TurnTrace)
       │   → escribe a traces/2026-06-04.jsonl
       │
       ▼
main.py: muestra Panel Rich con la respuesta
```

---

*Fin del documento — MODULE_MAP.md v1.0.0*
*Actualizar cuando se agreguen clases o cambien conexiones entre módulos.*