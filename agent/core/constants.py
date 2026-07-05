# agent/core/constants.py
from enum import StrEnum


# ─── Enums ────────────────────────────────────────────────────────────────────

class SecurityLevel(StrEnum):
    SAFE      = "safe"
    MODERATE  = "moderate"
    DANGEROUS = "dangerous"
    BLOCKED   = "blocked"


class StopReason(StrEnum):
    STOP       = "stop"
    TOOL_USE   = "tool_calls"
    MAX_TOKENS = "length"
    MAX_ITER   = "max_iter"
    ERROR      = "error"


class SkillStatus(StrEnum):
    MATCHED  = "matched"
    NO_MATCH = "no_match"
    DISABLED = "disabled"


# ─── Path aliases ─────────────────────────────────────────────────────────────
# Carpetas estándar ES + EN → resueltas por GuardRails.pre_process()

PATH_ALIASES: dict[str, str] = {
    "downloads":  "{HOME}/Downloads",
    "descargas":  "{HOME}/Downloads",
    "documents":  "{HOME}/Documents",
    "documentos": "{HOME}/Documents",
    "desktop":    "{HOME}/Desktop",
    "escritorio": "{HOME}/Desktop",
    "pictures":   "{HOME}/Pictures",
    "imágenes":   "{HOME}/Pictures",
    "imagenes":   "{HOME}/Pictures",
    "music":      "{HOME}/Music",
    "música":     "{HOME}/Music",
    "musica":     "{HOME}/Music",
    "videos":     "{HOME}/Videos",
}


# ─── Hallucination markers ────────────────────────────────────────────────────
# Strings que indican que el LLM inventó un resultado sin llamar tools.
#
# FIX: agregados prefijos de output de tools reales. Cuando el modelo copia
# literalmente el formato de respuesta de un tool ("File created: /home/...")
# sin haberlo ejecutado, se detecta como alucinación.
# Observado en turn 9110abc9: final_response era exactamente texto de tool output.

HALLUCINATION_MARKERS: tuple[str, ...] = (
    # Markers XML que el modelo puede inventar
    "<tool_response>",
    "</tool_response>",
    "<tool_result>",
    "</tool_result>",
    "[TOOL OUTPUT]",
    "[tool_output]",
    "Simulando resultado",
    "Como si hubiera ejecutado",
    # FIX: prefijos de output real de tools — si aparecen en una respuesta
    # de tipo STOP (sin tool_calls), el modelo está copiando resultados del
    # historial de contexto en lugar de ejecutar tools reales.
    "File created: /",
    "Directory created: /",
    "File not found: /",
    "Directory not found: /",
    "Moved: /",
    "Copied: /",
    "Deleted: /",
    "Backup creado: /",
)


# ─── PDF enforcement ──────────────────────────────────────────────────────────

PDF_TOOL_NAME: str = "read_pdf"
PDF_EXTENSIONS: tuple[str, ...] = (".pdf",)
PDF_KEYWORDS: tuple[str, ...] = (
    "leer pdf", "lee el pdf", "léeme el pdf",
    "contenido del pdf", "qué dice el pdf",
    "muéstrame el pdf", "muestra el pdf",
    "extrae el pdf", "abre el pdf",
    "read pdf", "read the pdf", "show pdf",
    "pdf content", "extract pdf",
)


# ─── Loop limits ─────────────────────────────────────────────────────────────
# Fuente de verdad para umbrales del harness

MAX_IDENTICAL_TOOL_CALLS: int = 2
MAX_TOTAL_ITERATIONS:     int = 25
MAX_TOOLS_PER_CALL:       int = 5
MAX_TOKENS_WARNING:       int = 50_000

# ─── System message prefix ────────────────────────────────────────────────────
# Prefijo de mensajes de corrección del sistema.
# Usado en harness para filtrar mensajes internos que no deben llegar al usuario.

SYSTEM_MSG_PREFIX: str = "[Sistema:"