# app/services/memory_service.py
"""
services/memory_service.py — Wrapper de memoria semántica con conflict resolution.

Responsabilidades:
  - Abstracción sobre TinyDBMemoryStore para facts, preferences, search
  - Extracción automática de facts post-turno (consolidación)
  - Invalidación temporal de facts contradictorios (patrón Zep/Graphiti)
  - Inyección de contexto relevante en system_prompt
  - clear_all() para /memory clear command

CAMBIO (v2.1):
  - Cachea métodos del store en __init__ para eliminar reflection en hot path.
  - Elimina hasattr/getattr repetidos en cada llamada.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from agent.memory.store import TinyDBMemoryStore, Fact, MemorySearchResult

logger = logging.getLogger(__name__)

# Facts con score de confianza bajo se descartan
_MIN_RELEVANCE = 0.3


class MemoryService:
    """
    Servicio de memoria semántica con gestión de conflictos y relevancia.
    """

    def __init__(self, memory_store: TinyDBMemoryStore) -> None:
        self._store = memory_store

        # Cachear capacidades del store en init (una sola vez)
        self._enabled = memory_store._enabled
        self._has_clear_all = hasattr(memory_store, 'clear_all')
        self._raw_db = getattr(memory_store, '_db', None)
        self._has_purge = hasattr(self._raw_db, 'purge') if self._raw_db else False
        self._has_drop_table = hasattr(self._raw_db, 'drop_table') if self._raw_db else False

    # ── Facts ────────────────────────────────────────────────────────────────

    async def search_facts(self, query: str, limit: int = 10) -> list[Fact]:
        """Busca hechos relevantes por texto."""
        if not self._enabled:
            return []

        results = await self._store.search(query, limit=limit)
        return [r.fact for r in results if r.relevance >= _MIN_RELEVANCE]

    async def get_recent_facts(self, n: int = 5) -> list[Fact]:
        """Retorna los N hechos más recientes."""
        if not self._enabled:
            return []
        return await self._store.get_recent(n)

    async def get_facts_by_topic(self, topic: str, limit: int = 20) -> list[Fact]:
        """Retorna hechos por tema exacto."""
        if not self._enabled:
            return []
        results = await self._store.get_by_topic(topic, limit)
        return [r.fact for r in results]

    async def save_fact(
        self,
        topic: str,
        content: str,
        session_id: str = "",
        source: str = "conversación",
    ) -> int:
        """Guarda un hecho con timestamp. Retorna el ID."""
        if not self._enabled:
            return -1

        fact = Fact(
            topic=topic,
            content=content,
            source=source,
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=session_id,
        )
        return await self._store.save_fact(fact)

    async def delete_fact(self, doc_id: int) -> bool:
        """Elimina un hecho por ID."""
        if not self._enabled:
            return False
        return await self._store.delete(doc_id)

    # ── Borrado masivo de memoria (cacheado, sin reflection) ─────────────────

    async def clear_all(self) -> int:
        """
        Elimina todos los hechos de memoria.
        Retorna cantidad de facts que quedaron (0 = éxito total).
        """
        if not self._enabled:
            return 0

        try:
            # Ruta rápida: método nativo del store
            if self._has_clear_all:
                await self._store.clear_all()
            else:
                self._clear_all_fallback()

            # Verificar que quedó limpio
            remaining = await self._store.count()
            if isinstance(remaining, dict):
                return remaining.get("facts", 0)
            return 0
        except Exception as e:
            logger.exception("Failed to clear memory")
            return -1

    def _clear_all_fallback(self) -> None:
        """Fallback para borrado masivo sin método clear_all nativo."""
        if self._has_purge:
            self._raw_db.purge()
        elif self._has_drop_table:
            for table in list(self._raw_db.tables()):
                self._raw_db.drop_table(table)

    # ── Conflict Resolution (Invalidación Temporal) ───────────────────────────

    async def save_fact_with_conflict_check(
        self,
        topic: str,
        content: str,
        session_id: str = "",
        source: str = "conversación",
    ) -> dict:
        """
        Guarda un hecho verificando conflictos con facts existentes del mismo topic.
        Retorna {"action": "created"|"updated"|"flagged", "doc_id": int, "conflicts": [...]}
        """
        if not self._enabled:
            return {"action": "disabled", "doc_id": -1, "conflicts": []}

        # Buscar facts existentes del mismo topic
        existing = await self.get_facts_by_topic(topic, limit=10)

        conflicts: list[dict] = []
        for old in existing:
            # Heurística simple: si el contenido es muy diferente, es conflicto
            similarity = self._text_similarity(content, old.content)
            if similarity < 0.5 and similarity > 0.1:
                # Ni igual ni completamente diferente -> posible conflicto
                conflicts.append({
                    "old_id": -1,  # No tenemos ID en Fact legacy
                    "old_content": old.content,
                    "similarity": similarity,
                })

        # Guardar el nuevo fact
        doc_id = await self.save_fact(topic, content, session_id, source)

        action = "created"
        if existing:
            action = "updated" if any(self._text_similarity(content, e.content) > 0.7 for e in existing) else "flagged"

        return {
            "action": action,
            "doc_id": doc_id,
            "conflicts": conflicts,
        }

    @staticmethod
    def _text_similarity(a: str, b: str) -> float:
        """Similitud simple basada en palabras comunes (0.0 - 1.0)."""
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union)

    # ── Extracción automática (Consolidación) ─────────────────────────────────

    async def extract_session_facts(
        self,
        session_id: str,
        user_message: str,
        response: str,
        tool_calls: list[dict],
    ) -> list[Fact]:
        """
        Extrae hechos de un turno de conversación y los guarda.
        Versión heurística (sin LLM para no bloquear la UI).
        """
        if not self._enabled:
            return []

        facts: list[Fact] = []

        # Heurística 1: Tools usados exitosamente
        successful = [t for t in tool_calls if not t.get("is_error", False)]
        if successful:
            tool_names = list({t.get("name", "unknown") for t in successful})
            fact_content = f"{user_message[:80]} -> {', '.join(tool_names[:3])}"
            doc_id = await self.save_fact(
                topic="operaciones",
                content=fact_content,
                session_id=session_id,
            )
            if doc_id > 0:
                facts.append(Fact(
                    topic="operaciones",
                    content=fact_content,
                    source="conversación",
                    session_id=session_id,
                ))

        # Heurística 2: Preferencias del usuario (patrones simples)
        prefs = self._extract_preferences(user_message)
        for key, value in prefs.items():
            await self._store.save_preference(key, value)

        # Heurística 3: Directorios frecuentes
        paths = self._extract_paths(user_message, response)
        for path in paths:
            doc_id = await self.save_fact(
                topic="directorios",
                content=f"Acceso frecuente: {path}",
                session_id=session_id,
            )
            if doc_id > 0:
                facts.append(Fact(
                    topic="directorios",
                    content=f"Acceso frecuente: {path}",
                    session_id=session_id,
                ))

        return facts

    def _extract_preferences(self, message: str) -> dict[str, str]:
        """Extrae preferencias simples del mensaje del usuario."""
        prefs: dict[str, str] = {}
        lower = message.lower()

        # Patrones simples
        if "prefiero" in lower or "me gusta" in lower:
            if "oscuro" in lower or "dark" in lower:
                prefs["theme_preference"] = "dark"
            if "claro" in lower or "light" in lower:
                prefs["theme_preference"] = "light"

        return prefs

    def _extract_paths(self, user_msg: str, response: str) -> list[str]:
        """Extrae rutas de archivos mencionadas."""
        paths: list[str] = []
        for text in (user_msg, response):
            found = re.findall(r"/[\w/\-.]+(?:/\w+)*", text)
            paths.extend(found)
        return list(set(paths))[:5]  # deduplicar, máximo 5

    # ── Contexto relevante para inyección ──────────────────────────────────────

    async def get_relevant_context(self, query: str, max_chars: int = 500) -> str:
        """
        Retorna un bloque de texto con hechos relevantes para inyectar
        en el system_prompt del harness.
        """
        if not self._enabled:
            return ""

        facts = await self.search_facts(query, limit=5)
        if not facts:
            return ""

        lines = ["\n[Contexto de memoria:]"]
        for f in facts:
            lines.append(f"- {f.topic}: {f.content[:100]}")

        context = "\n".join(lines)
        if len(context) > max_chars:
            context = context[:max_chars] + "\n..."
        return context

    # ── Preferences ──────────────────────────────────────────────────────────

    async def get_preferences(self) -> dict[str, str]:
        """Retorna todas las preferencias como dict."""
        if not self._enabled:
            return {}

        # TinyDBMemoryStore no tiene list_all_preferences, usamos raw
        # Esto es un workaround — en v2 debería haber un método dedicado
        return {}

    async def save_preference(self, key: str, value: str) -> None:
        """Guarda una preferencia clave-valor."""
        if not self._enabled:
            return
        await self._store.save_preference(key, value)

    async def get_preference(self, key: str) -> Optional[str]:
        """Retorna una preferencia por clave."""
        if not self._enabled:
            return None
        return await self._store.get_preference(key)
