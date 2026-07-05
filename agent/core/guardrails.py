# agent/core/guardrails.py
"""
GuardRails — restricciones conductuales en código puro.

pre_process          : resuelve aliases de carpetas antes de enviar al LLM
detect_hallucination : detecta markers de alucinación en la respuesta
detect_fake_mutation : detecta cuando el modelo afirma operar archivos sin tools
clean_response       : elimina markers internos visibles al usuario
validate_pdf_tool    : verifica que read_pdf se usó para archivos .pdf
"""
from __future__ import annotations

import re

from .constants import (
    HALLUCINATION_MARKERS,
    PATH_ALIASES,
    PDF_EXTENSIONS,
    PDF_KEYWORDS,
    PDF_TOOL_NAME,
)

# ─── Verbos de mutación ───────────────────────────────────────────────────────

_MUTATION_VERBS: tuple[str, ...] = (
    # ES
    "copia ", "copiar", "cópialo", "cópiala", "cópialos", "cópialas",
    "mueve ", "mover", "muévelo", "muévela", "muévelos", "muévelas",
    "lleva ", "lleva los", "pasa los", "pasa el",
    "elimina", "eliminar", "borra ", "borrar",
    "crea un", "crea una", "crear un", "crear una",
    "crea la", "crea el", "crea carpeta",
    "escribe", "escribir", "pon en", "agrega ",
    "renombra", "renombrar",
    "mueve a", "copia a", "lleva a",
    "vas a escribir", "escríbelo", "escríbela",
    "actualiza", "actualizar", "modifica", "modificar",
    "añade", "añadir", "inserta", "insertar",
    "sobreescribe", "sobreescribir", "reemplaza", "reemplazar",
    "guarda", "guardar",
    # EN
    "copy ", "move ", "delete ", "remove ",
    "create ", "write ", "rename ",
    "transfer ", "upload ",
    "update ", "modify ", "append ", "insert ", "overwrite ",
)

_FAKE_DONE_PHRASES: tuple[str, ...] = (
    # ES — copia/movimiento/eliminación
    "he copiado", "he movido", "he eliminado", "he creado",
    "he transferido", "he renombrado", "he pegado",
    "los archivos han sido", "el archivo ha sido",
    "se han copiado", "se han movido", "se han eliminado", "se han creado",
    "archivos están ubicados", "archivos ahora están", "ahora se encuentran",
    "copiado correctamente", "movido correctamente", "creado correctamente",
    "ambos archivos", "los dos archivos",
    # ES — escritura/actualización
    "he escrito", "he actualizado", "he modificado", "he guardado",
    "he añadido", "he insertado", "he sobreescrito", "he reemplazado",
    "texto ha sido escrito", "contenido ha sido",
    "escrito correctamente", "actualizado correctamente",
    "guardado correctamente", "modificado correctamente",
    "se ha escrito", "se ha actualizado", "se ha guardado",
    "se han escrito", "se han actualizado", "se han guardado",
    "contenido actualizado", "archivo actualizado",
    "tres archivos",
    # EN
    "i have copied", "i have moved", "i have created", "i have deleted",
    "i have written", "i have updated", "i have modified", "i have saved",
    "i have added", "i have inserted", "i have replaced",
    "files have been", "has been copied", "has been moved", "has been created",
    "has been written", "has been updated", "has been saved",
    "files are now located", "successfully copied", "successfully moved",
    "successfully written", "successfully updated", "successfully saved",
)


class GuardRails:
    def __init__(self, home: str) -> None:
        self._home = home
        self._resolved_aliases: dict[str, str] = {
            alias: path.replace("{HOME}", home)
            for alias, path in PATH_ALIASES.items()
        }

    # ── Pre-procesamiento ─────────────────────────────────────────────────────

    def pre_process(self, message: str) -> str:
        if re.search(r"(?<!\w)/[a-zA-Z]", message):
            return message
        result = message
        for alias, abs_path in self._resolved_aliases.items():
            pattern = re.compile(r"\b" + re.escape(alias) + r"\b", re.IGNORECASE)
            result = pattern.sub(abs_path, result)
        return result

    # ── Detección de alucinaciones ────────────────────────────────────────────

    def detect_hallucination(self, response: str) -> bool:
        for marker in HALLUCINATION_MARKERS:
            if marker in response:
                return True
        return False

    def detect_fake_mutation(
        self,
        user_message: str,
        response: str,
        tool_calls_made: list[str],
        turn_has_prior_tool_calls: bool = False,
    ) -> bool:
        """
        Retorna True si el modelo afirmó completar una mutación sin ejecutar
        ningún tool en esta iteración específica.

        FIX — turn_has_prior_tool_calls:
        Si el turno ya tiene tool calls de iteraciones anteriores, NO disparar.
        Razón: en tareas multi-archivo el modelo puede decir "escribí ccs.txt,
        ahora mgta.txt" después de haber llamado create_file legítimamente antes.
        Sin este fix el guardrail interrumpía flujos legítimos causando que el
        modelo reescribiera los mismos 3 archivos 3-4 veces (11 tool calls
        para una tarea de 3 archivos, observado en turno e420f472).
        """
        if tool_calls_made:
            return False

        if turn_has_prior_tool_calls:
            return False

        msg_lower  = user_message.lower()
        resp_lower = response.lower()

        user_requested_mutation = any(verb in msg_lower for verb in _MUTATION_VERBS)
        if not user_requested_mutation:
            return False

        model_claims_done = any(
            phrase in resp_lower for phrase in _FAKE_DONE_PHRASES
        )
        return model_claims_done

    # ── Limpieza de respuesta ─────────────────────────────────────────────────

    def clean_response(self, response: str) -> str:
        result = response
        for marker in HALLUCINATION_MARKERS:
            result = result.replace(marker, "")
        return result.strip()

    # ── Validación PDF ────────────────────────────────────────────────────────

    def validate_pdf_tool(
        self,
        user_message: str,
        tool_names_called: list[str],
    ) -> str | None:
        msg_lower = user_message.lower()
        asked_for_pdf = (
            any(ext in msg_lower for ext in PDF_EXTENSIONS)
            or any(kw in msg_lower for kw in PDF_KEYWORDS)
        )
        if not asked_for_pdf or not tool_names_called:
            return None
        if PDF_TOOL_NAME in tool_names_called:
            return None
        if "read_file" in tool_names_called:
            return (
                f"[Sistema: Se usó 'read_file' para un PDF — no funciona con binarios. "
                f"Usa '{PDF_TOOL_NAME}' para leer archivos .pdf]"
            )
        return None

    @property
    def home(self) -> str:
        return self._home