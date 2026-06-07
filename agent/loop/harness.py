# agent/loop/harness.py
import time
import uuid

from ..core.config import AgentConfig
from ..core.constants import StopReason
from ..llm.client import OllamaClient
from ..skills.loader import SkillLoader
from ..skills.matcher import SkillMatcher
from ..tools.base import ToolResult
from ..tools.registry import ToolRegistry
from ..traces.models import LLMCallTrace, ToolTrace, TurnTrace
from ..traces.recorder import TraceRecorder
from .context import ConversationContext


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
        self._config = config
        self._llm = llm
        self._registry = tool_registry
        self._loader = skill_loader
        self._matcher = skill_matcher
        self._context = context
        self._recorder = trace_recorder

    async def run(self, user_message: str) -> str:
        start = time.perf_counter()
        turn_id = str(uuid.uuid4())
        skill_name: str | None = None

        # Skill matching — siempre llama set_skill (con body o None)
        match = self._matcher.match(user_message)
        if match:
            skill_name = match.name
            body = self._loader.load_body(match.name)
            self._context.set_skill(body)
        else:
            self._context.set_skill(None)

        self._context.add_user_message(user_message)

        llm_traces: list[LLMCallTrace] = []
        tool_traces: list[ToolTrace] = []
        final_response = ""
        had_errors = False
        tool_cache: dict[tuple[str, str], ToolResult] = {}

        MAX_TOOLS_PER_CALL = 5

        try:
            for iteration in range(self._config.context.max_iterations):
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
                    # Fix 1: fallback cuando content es vacío
                    final_response = llm_resp.content or "Operación completada."
                    self._context.add_assistant_response(final_response)
                    break

                if llm_resp.stop_reason == StopReason.MAX_TOKENS:
                    final_response = (
                        llm_resp.content + "\n[Respuesta truncada por límite de tokens]"
                    )
                    self._context.add_assistant_response(final_response)
                    break

                if llm_resp.tool_calls:
                    tool_calls = llm_resp.tool_calls[:MAX_TOOLS_PER_CALL]
                    if len(llm_resp.tool_calls) > MAX_TOOLS_PER_CALL:
                        self._context.add_assistant_response(
                            f"[Sistema: Se limitaron {len(llm_resp.tool_calls)} tool calls "
                            f"a {MAX_TOOLS_PER_CALL}. Para operaciones en lote usa run_command.]"
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
                            continue

                        t0 = time.perf_counter()
                        result = await self._registry.execute(
                            tc.name,
                            tc.id,
                            **tc.input,
                        )
                        duration_ms = int((time.perf_counter() - t0) * 1000)
                        tool_results.append(result)
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
                    self._context.add_tool_results(tool_results)

                    # Anti-loop: mismo tool+args 3 veces seguidas
                    recent = [(t.name, str(t.input)) for t in tool_traces[-3:]]
                    if len(recent) == 3 and len(set(recent)) == 1:
                        self._context.add_assistant_response(
                            "[Sistema: Ya tienes los datos necesarios en el historial. "
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
                        final_response = (
                            final_resp.content or self._build_fallback(tool_results)
                        )
                        self._context.add_assistant_response(final_response)
                        break

                    continue

            else:
                # for...else: se agotaron las iteraciones sin break
                final_response = (
                    "⚠️ Máximo de iteraciones alcanzado. "
                    "El agente no pudo completar la tarea."
                )
                self._context.add_assistant_response(final_response)

        except Exception as e:
            # Fix 3: nunca propagar excepciones al llamador
            final_response = "Error al procesar la solicitud. Por favor intenta de nuevo."
            had_errors = True

        total_duration_ms = int((time.perf_counter() - start) * 1000)
        turn_trace = TurnTrace(
            turn_id=turn_id,
            timestamp=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
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
        return final_response

    def _build_fallback(self, tool_results: list[ToolResult]) -> str:
        """Construye fallback con los datos del último tool exitoso."""
        for result in reversed(tool_results):
            if not result.is_error:
                return f"Resultado obtenido:\n\n{result.content}"
        return "La operación se completó pero no se pudo generar una respuesta detallada."

    def reset(self) -> None:
        self._context.clear()
        self._context.set_skill(None)