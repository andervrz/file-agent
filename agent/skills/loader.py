# agent/skills/loader.py
from pathlib import Path

from pydantic import BaseModel


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
        if not self._path.exists():
            return skills
        for skill_dir in self._path.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
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
        except yaml.YAMLError:
            return None

    def _extract_body(self, content: str) -> str:
        if not content.startswith("---"):
            return content
        parts = content.split("---", 2)
        if len(parts) < 3:
            return content
        return parts[2].strip()