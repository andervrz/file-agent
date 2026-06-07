# agent/llm/client.py
import time
import uuid
from dataclasses import dataclass, field

from ollama import AsyncClient

from ..core.config import LLMConfig


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class LLMResponse:
    stop_reason: str
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0


class OllamaClient:
    def __init__(self, config: LLMConfig, api_key: str):
        self._client = AsyncClient(
            host=config.host,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        self._config = config

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        start = time.perf_counter()

        options = {
            "temperature": self._config.temperature,
            "num_ctx":     self._config.num_ctx,
            "num_predict": self._config.num_predict,
        }

        kwargs: dict = {
            "model":    self._config.model,
            "messages": messages,
            "options":  options,
        }
        if tools:
            kwargs["tools"] = tools

        response = await self._client.chat(**kwargs)
        duration_ms = int((time.perf_counter() - start) * 1000)

        # Parsear tool calls
        tool_calls: list[ToolCall] = []
        if response.message.tool_calls:
            for tc in response.message.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=str(uuid.uuid4()),
                        name=tc.function.name,
                        input=dict(tc.function.arguments),
                    )
                )

        content = response.message.content or ""

        if tool_calls:
            stop_reason = "tool_calls"
        else:
            stop_reason = getattr(response, "done_reason", None) or "stop"

        return LLMResponse(
            stop_reason=stop_reason,
            content=content,
            tool_calls=tool_calls,
            tokens_in=getattr(response, "prompt_eval_count", 0) or 0,
            tokens_out=getattr(response, "eval_count", 0) or 0,
            duration_ms=duration_ms,
        )