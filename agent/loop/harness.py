# agent/loop/harness.py
"""
AgentHarness — orquesta el loop de interacción LLM + tools.

Ahora acepta session_id opcional para vincular traces con memoria persistente.
Callback opcional para notificar tool calls en tiempo real a la UI.
Integración con MemoryService para inyección de contexto pre-turno y
extracción post-turno.
"""
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Callable

from ..core.config import AgentConfig
from ..core.constants import (
    MAX_IDENTICAL_TOOL_CALLS,
    MAX_TOOLS_PER_CALL,
    SYSTEM_MSG_PREFIX,
    StopReason,
)
from ..core.guardrails import GuardRails
from ..llm.client import OllamaClient
from ..skills.loader import SkillLoader
from ..skills.matcher import SkillMatcher
from ..tools.base import ToolResult
from ..tools.registry import ToolRegistry
from ..traces.models import LLMCallTrace, ToolTrace, TurnTrace
from ..traces.recorder import TraceRecorder
from .context import ConversationContext

logger = logging.getLogger(__name__)

_FAKE_MUTATION_CORRECTION = (
    "[Sistema: Afirmaste completar la operación pero no ejecutaste ningún tool. "
    "Ejecuta el tool correspondiente AHORA. "
    "No respondas con texto hasta haber llamado el tool.]"
)

_HALLUCINATION_CORRECTION = (
    "[Sistema: Tu respuesta contiene markers de resultado ficticio. "
    "Ejecuta el tool real para obtener los datos. "
    "No inventes resultados.]"
)

_FALLBACK_ERROR = (
    "No pude completar la operación. "
    "Intenta reformulando la solicitud con más detalle."
)


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
        guardrails: GuardRails,
        memory_service=None,  # NUEVO: opcional, para inyección de contexto
    ):
        self._config = config
        self._llm = llm
        self._registry = tool_registry
        self._loader = skill_loader
        self._matcher = skill_matcher
        self._context = context
        self._recorder = trace_recorder
        self._guardrails = guardrails
        self._memory_service = memory_service  # NUEVO
        # callback opcional para notificar tool calls en tiempo real
        self._on_tool_call: Callable[[ToolTrace], None] | None = None

    # ── NUEVO: Properties públicas para acceso desde UI ────────────────────────

    @property
    def tool_registry(self) -> ToolRegistry:
        """Expone el registry para que CommandService liste y ejecute tools."""
        return self._registry

    @property
    def config(self) -> AgentConfig:
        """Expone la config para que CommandService muestre /model."""
        return self._config

    @property
    def trace_recorder(self) -> TraceRecorder:
        """Expone el recorder para lectura de traces (si se necesita)."""
        return self._recorder

    # ── NUEVO: setter para el callback de tool calls ───────────────────────────

    def set_tool_callback(self, cb: Callable[[ToolTrace], None] | None) -> None:
        """Registra un callback que se dispara tras cada tool call ejecutado."""
        self._on_tool_call = cb

    async def run(self, user_message: str, session_id: str | None = None) -> str:
        """
        Ejecuta un turno completo y retorna solo la respuesta final (str).
        """
        trace = await self._run_turn(user_message, session_id)
        return trace.final_response

    async def run_with_trace(
        self, user_message: str, session_id: str | None = None
    ) -> TurnTrace:
        """
        Ejecuta un turno completo y retorna el TurnTrace íntegro.
        """
        return await self._run_turn(user_message, session_id)

    async def _run_turn(
        self, user_message: str, session_id: str | None = None
    ) -> TurnTrace:
        """
        Ejecuta un turno completo: skill matching -> LLM -> tools -> guardrails -> trace.
        CON MEMORIA: inyecta contexto relevante pre-turno, extrae memoria post-turno.
        """
        start = time.perf_counter()
        turn_id = str(uuid.uuid4())
        skill_name: str | None = None

        # ── NUEVO: Inyección de contexto de memoria pre-turno ──────────────
        memory_context = ""
        if self._memory_service and session_id:
            try:
                memory_context = await self._memory_service.build_memory_context(
                    session_id=session_id,
                    user_message=user_message,
                    tool_calls=[],
                )
            except Exception as e:
                logger.warning("Memory context injection failed: %s", e)

        processed_message = self._guardrails.pre_process(user_message)

        # Si hay contexto de memoria, prepend al mensaje del usuario
        if memory_context:
            processed_message = f"{memory_context}\n\n{processed_message}"

        match = self._matcher.match(processed_message)
        if match:
            skill_name = match.name
            body = self._loader.load_body(match.name)
            self._context.set_skill(body)
        else:
            self._context.set_skill(None)

        self._context.add_user_message(processed_message)

        llm_traces: list[LLMCallTrace] = []
        tool_traces: list[ToolTrace] = []
        final_response = ""
        had_errors = False

        # FIX: tool_cache por sesión, no por instancia de harness
        tool_cache: dict[tuple[str, str], ToolResult] = {}

        try:
            for _iteration in range(self._config.context.max_iterations):

                # FIX: tools de ESTA iteración -- reset cada vuelta del loop
                tools_this_iteration: list[str] = []

                messages = self._context.get_messages()
                tools = self._registry.get_schemas()
                llm_resp = await self._llm.complete(messages, tools)

                llm_traces.append(
                    LLMCallTrace(
                        model=self._config.llm.model,
                        tokens_in=llm_resp.tokens_in,
                        tokens_out=llm_resp.tokens_out,
                        stop_reason=llm_resp.stop_reason,
                        duration_ms=llm_resp.duration_ms,
                    )
                )

                if llm_resp.stop_reason == StopReason.STOP:
                    raw = llm_resp.content or ""
                    tool_names_so_far = [t.name for t in tool_traces]

                    # Guardrail 1: markers de alucinación
                    if self._guardrails.detect_hallucination(raw):
                        had_errors = True
                        cleaned = self._guardrails.clean_response(raw)
                        if cleaned:
                            final_response = cleaned
                            self._context.add_assistant_response(final_response)
                            break
                        self._context.add_assistant_response(_HALLUCINATION_CORRECTION)
                        continue

                    # Guardrail 2: mutación sin tools
                    if self._guardrails.detect_fake_mutation(
                        user_message,
                        raw,
                        tools_this_iteration,
                        turn_has_prior_tool_calls=len(tool_traces) > 0,
                    ):
                        had_errors = True
                        self._context.add_assistant_response(_FAKE_MUTATION_CORRECTION)
                        continue

                    # Guardrail 3: PDF con tool incorrecto
                    pdf_warning = self._guardrails.validate_pdf_tool(
                        user_message, tool_names_so_far
                    )
                    if pdf_warning:
                        self._context.add_assistant_response(pdf_warning)
                        correction = await self._llm.complete(
                            self._context.get_messages(), tools
                        )
                        llm_traces.append(
                            LLMCallTrace(
                                model=self._config.llm.model,
                                tokens_in=correction.tokens_in,
                                tokens_out=correction.tokens_out,
                                stop_reason=correction.stop_reason,
                                duration_ms=correction.duration_ms,
                            )
                        )
                        if correction.content:
                            raw = correction.content

                    # FIX: nunca exponer mensajes de sistema como respuesta final
                    if raw.startswith(SYSTEM_MSG_PREFIX):
                        raw = _FALLBACK_ERROR
                        had_errors = True

                    final_response = raw or "Operación completada."
                    self._context.add_assistant_response(final_response)
                    break

                if llm_resp.stop_reason == StopReason.MAX_TOKENS:
                    final_response = llm_resp.content + "\n[Respuesta truncada por límite de tokens]"
                    self._context.add_assistant_response(final_response)
                    break

                if llm_resp.tool_calls:
                    tool_calls = llm_resp.tool_calls[:MAX_TOOLS_PER_CALL]
                    if len(llm_resp.tool_calls) > MAX_TOOLS_PER_CALL:
                        self._context.add_assistant_response(
                            f"[Sistema: Se limitaron {len(llm_resp.tool_calls)} tool calls "
                            f"a {MAX_TOOLS_PER_CALL}. Para lote usa run_command.]"
                        )

                    tool_results: list[ToolResult] = []
                    for tc in tool_calls:
                        cache_key = (tc.name, str(tc.input))
                        if cache_key in tool_cache:
                            cached = tool_cache[cache_key]
                            tool_results.append(cached)
                            tool_traces.append(
                                ToolTrace(
                                    name=tc.name,
                                    input=tc.input,
                                    output=cached.content[:500],
                                    is_error=cached.is_error,
                                    duration_ms=0,
                                )
                            )
                            tools_this_iteration.append(tc.name)
                            # NUEVO: notificar callback si existe
                            if self._on_tool_call:
                                self._on_tool_call(tool_traces[-1])
                            continue

                        t0 = time.perf_counter()
                        result = await self._registry.execute(
                            tc.name, tc.id, **tc.input
                        )
                        duration_ms = int((time.perf_counter() - t0) * 1000)
                        tool_results.append(result)
                        tools_this_iteration.append(tc.name)

                        if result.is_error:
                            had_errors = True
                        else:
                            tool_cache[cache_key] = result

                        tool_traces.append(
                            ToolTrace(
                                name=tc.name,
                                input=tc.input,
                                output=result.content[:500],
                                is_error=result.is_error,
                                duration_ms=duration_ms,
                            )
                        )
                        # NUEVO: notificar callback si existe
                        if self._on_tool_call:
                            self._on_tool_call(tool_traces[-1])

                    self._context.add_tool_results(tool_results)

                    # Anti-loop: mismo tool+args N veces consecutivas
                    recent = [
                        (t.name, str(t.input))
                        for t in tool_traces[-MAX_IDENTICAL_TOOL_CALLS:]
                    ]
                    if (
                        len(recent) == MAX_IDENTICAL_TOOL_CALLS
                        and len(set(recent)) == 1
                    ):
                        self._context.add_assistant_response(
                            "[Sistema: Ya tienes los datos en el historial. "
                            "Responde al usuario con esos datos. NO llames más tools.]"
                        )
                        final_messages = self._context.get_messages()
                        final_resp = await self._llm.complete(final_messages, tools=None)
                        llm_traces.append(
                            LLMCallTrace(
                                model=self._config.llm.model,
                                tokens_in=final_resp.tokens_in,
                                tokens_out=final_resp.tokens_out,
                                stop_reason=final_resp.stop_reason,
                                duration_ms=final_resp.duration_ms,
                            )
                        )
                        candidate = final_resp.content or self._build_fallback(tool_results)
                        # FIX: no exponer mensajes de sistema al usuario
                        if candidate.startswith(SYSTEM_MSG_PREFIX):
                            candidate = self._build_fallback(tool_results)
                        final_response = candidate
                        self._context.add_assistant_response(final_response)
                        break

                    continue

            else:
                final_response = (
                    "⚠️ Máximo de iteraciones alcanzado. "
                    "El agente no pudo completar la tarea."
                )
                self._context.add_assistant_response(final_response)

        except Exception as e:
            logger.exception(
                "harness.run() unhandled exception",
                extra={"turn_id": turn_id, "user_message": user_message[:80]},
            )
            final_response = (
                f"Error inesperado ({type(e).__name__}). "
                "Por favor intenta de nuevo."
            )
            had_errors = True

        # FIX: garantía final -- ningún mensaje de sistema llega al usuario
        if final_response.startswith(SYSTEM_MSG_PREFIX):
            final_response = _FALLBACK_ERROR
            had_errors = True

        total_duration_ms = int((time.perf_counter() - start) * 1000)
        turn_trace = TurnTrace(
            turn_id=turn_id,
            session_id=session_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            user_message=user_message,
            skill_activated=skill_name,
            llm_calls=llm_traces,
            tool_calls=tool_traces,
            final_response=final_response,
            total_duration_ms=total_duration_ms,
            total_llm_calls=len(llm_traces),
            total_tool_calls=len(tool_traces),
            had_errors=had_errors,
        )
        await self._recorder.record(turn_trace)

        # ── NUEVO: Extracción de memoria post-turno ──────────────────────────
        if self._memory_service and session_id:
            try:
                tool_calls_data = [
                    {"name": t.name, "input": t.input, "is_error": t.is_error}
                    for t in tool_traces
                ]
                await self._memory_service.extract_from_turn(
                    session_id=session_id,
                    user_message=user_message,
                    response=final_response,
                    tool_calls=tool_calls_data,
                )
                logger.debug("Memory extraction completed for turn %s", turn_id[:8])
            except Exception as e:
                logger.warning("Memory extraction failed: %s", e)

        return turn_trace

    def _build_fallback(self, tool_results: list[ToolResult]) -> str:
        for result in reversed(tool_results):
            if not result.is_error:
                return f"Resultado obtenido:\n\n{result.content}"
        return _FALLBACK_ERROR

    def reset(self) -> None:
        self._context.clear()
        self._context.set_skill(None)
