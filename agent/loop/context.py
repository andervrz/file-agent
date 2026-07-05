# agent/loop/context.py
from ..tools.base import ToolResult


class ConversationContext:
    def __init__(self, max_history: int, system_prompt: str):
        self._max_history = max_history
        self._system_prompt = system_prompt
        self._messages: list[dict] = []
        self._active_skill_body: str | None = None

    def set_skill(self, body: str | None) -> None:
        self._active_skill_body = body

    def add_user_message(self, text: str) -> None:
        self._messages.append({"role": "user", "content": text})

    def add_assistant_response(self, content: str) -> None:
        self._messages.append({"role": "assistant", "content": content})

    def add_tool_results(self, results: list[ToolResult]) -> None:
        for result in results:
            if result.is_error:
                # Formato que NO invita al LLM a explicar la API interna
                content = (
                    f"Error en operación: {result.content}. "
                    f"Reporta este error al usuario de forma simple. "
                    f"NO expliques parámetros técnicos, schemas ni formato de tools."
                )
            else:
                content = result.content

            # FIX: usar el nombre real del tool en lugar del hardcodeado "tool"
            self._messages.append({
                "role": "tool",
                "name": result.tool_name or "tool",
                "content": content,
            })

    def get_messages(self) -> list[dict]:
        system_messages: list[dict] = []
        system_messages.append({"role": "system", "content": self._system_prompt})
        if self._active_skill_body:
            system_messages.append({
                "role": "system",
                "content": self._active_skill_body,
            })
        trimmed = self._trim()
        return system_messages + trimmed

    def clear(self) -> None:
        self._messages = []

    def _trim(self) -> list[dict]:
        """
        Retorna los últimos N turnos completos.

        FIX: el trim anterior cortaba por número de mensajes, lo que podía
        dejar tool results huérfanos (sin el assistant que los pidió) o
        un assistant sin los tool results que referencia.

        Ahora se reconstruye por turnos: cada turno = un user message + todo
        lo que viene después (assistant, tool results) hasta el siguiente user.
        Se mantienen los últimos max_history turnos completos.
        """
        if not self._messages:
            return []

        # Partir en turnos por cada mensaje de rol "user"
        turns: list[list[dict]] = []
        current: list[dict] = []
        for msg in self._messages:
            if msg["role"] == "user" and current:
                turns.append(current)
                current = []
            current.append(msg)
        if current:
            turns.append(current)

        # Mantener los últimos max_history turnos
        kept = turns[-self._max_history:] if len(turns) > self._max_history else turns
        return [msg for turn in kept for msg in turn]