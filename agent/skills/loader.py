# agent/skills/loader.py
import logging
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class SkillMetadata(BaseModel):
    name: str
    version: str
    description: str
    tags: list[str]
    path: Path = Path(".")


class LoadedSkill(BaseModel):
    metadata: SkillMetadata
    body: str


class SkillLoader:
    def __init__(self, skills_path: str | Path):
        self._path = Path(skills_path)

    def load_metadata(self) -> list[SkillMetadata]:
        skills: list[SkillMetadata] = []

        # FIX: loguear cuando el path no existe en lugar de fallar silenciosamente.
        # Causa más frecuente de Skills: 0 en el banner.
        if not self._path.exists():
            logger.warning(
                "Skills path not found — Skills will show as 0. "
                "Run the agent from the project root or use an absolute path. "
                "Resolved path: %s",
                self._path.resolve(),
            )
            return skills

        loaded = 0
        for skill_dir in self._path.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                logger.debug("Skipping %s — no SKILL.md found", skill_dir.name)
                continue
            frontmatter = self._parse_frontmatter(skill_file.read_text(encoding="utf-8"))
            if frontmatter:
                skills.append(
                    SkillMetadata(
                        name=frontmatter.get("name", skill_dir.name),
                        version=frontmatter.get("version", "1.0.0"),
                        description=frontmatter.get("description", ""),
                        tags=frontmatter.get("tags", []),
                        path=skill_dir,
                    )
                )
                loaded += 1
            else:
                logger.warning(
                    "Skill %s has no valid frontmatter — skipped", skill_dir.name
                )

        logger.info("Loaded %d skill(s) from %s", loaded, self._path.resolve())
        return skills

    def load_body(self, skill_name: str) -> str:
        for skill_dir in self._path.iterdir():
            if not skill_dir.is_dir():
                continue
            if skill_dir.name == skill_name:
                content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
                return self._extract_body(content)
        raise FileNotFoundError(f"skill not found: {skill_name}")

    def _parse_frontmatter(self, content: str) -> dict | None:
        if not content.startswith("---"):
            return None
        parts = content.split("---", 2)
        if len(parts) < 3:
            return None
        import yaml
        try:
            return yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError as e:
            logger.warning("YAML parse error in frontmatter: %s", e)
            return None

    def _extract_body(self, content: str) -> str:
        if not content.startswith("---"):
            return content
        parts = content.split("---", 2)
        if len(parts) < 3:
            return content
        return parts[2].strip()