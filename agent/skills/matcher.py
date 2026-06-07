# agent/skills/matcher.py
import re
from .loader import SkillMetadata


class SkillMatcher:
    def __init__(self, skills: list[SkillMetadata]):
        self._skills = skills

    def match(self, user_message: str) -> SkillMetadata | None:
        text = user_message.lower()
        words = {w for w in re.findall(r"[a-záéíóúñ]+", text) if len(w) >= 3}

        if not words:
            return None

        best: SkillMetadata | None = None
        best_score = 0.0

        for skill in self._skills:
            desc_words = set(re.findall(r"[a-záéíóúñ]+", skill.description.lower()))
            tag_words  = set(re.findall(r"[a-záéíóúñ]+", " ".join(skill.tags).lower()))

            # Palabras que están SOLO en tags (no en descripción)
            tag_only = tag_words - desc_words

            # Conteo sin duplicados: desc | tags
            combined  = len(words & (desc_words | tag_words))

            # Bonus por match en tag exclusivo
            tag_bonus = len(words & tag_only) * 0.5

            # Prefix match: "archivo" → "archivos"
            prefix = sum(
                1 for w in words
                for d in desc_words
                if d.startswith(w) and d != w and len(w) >= 4
            ) * 1.0

            score = combined + tag_bonus + prefix

            if score > best_score:
                best_score = score
                best = skill

        return best if best_score > 0 else None