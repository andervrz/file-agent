"""
Tests para SkillLoader — parseo de SKILL.md.

Cubre:
- load_metadata() parsea frontmatter YAML
- load_body() retorna markdown sin frontmatter
- Múltiples skills en el directorio
- SKILL.md sin frontmatter
- Campos opcionales (tags vacíos)
- Paths correctos
"""

import pytest
from pathlib import Path

from agent.skills.loader import SkillLoader, SkillMetadata


class TestSkillLoader:
    """Carga de skills desde archivos markdown."""

    @pytest.fixture
    def skills_dir(self, tmp_path):
        """Directorio con 3 skills de ejemplo."""
        base = tmp_path / "skills"

        # Skill 1: file-management
        fm = base / "file-management"
        fm.mkdir(parents=True)
        (fm / "SKILL.md").write_text("""---
name: "file-management"
version: "1.0.0"
description: "Gestiona archivos y directorios con comandos de terminal"
tags: [files, directories, fs]
---

## Context
Eres un experto en gestión de archivos.

## Instructions
1. Usa paths absolutos.
2. Verifica existencia antes de operar.

## Examples
- "crea un archivo" → create_file
""")

        # Skill 2: command-execution
        ce = base / "command-execution"
        ce.mkdir(parents=True)
        (ce / "SKILL.md").write_text("""---
name: "command-execution"
version: "1.0.0"
description: "Ejecuta comandos de shell con validación de seguridad"
tags: [shell, terminal, commands]
---

## Context
Eres un experto en terminal.

## Constraints
NO ejecutes sudo.
""")

        # Skill 3: document-creation
        dc = base / "document-creation"
        dc.mkdir(parents=True)
        (dc / "SKILL.md").write_text("""---
name: "document-creation"
version: "1.0.0"
description: "Crea documentos estructurados como markdown, json, yaml"
tags: [docs, markdown, json]
---

## Context
Eres un experto en documentos.
""")

        return base

    @pytest.fixture
    def loader(self, skills_dir):
        return SkillLoader(skills_path=skills_dir)

    # ── load_metadata ──
    def test_load_metadata_count(self, loader):
        metadata = loader.load_metadata()
        assert len(metadata) == 3

    def test_load_metadata_names(self, loader):
        metadata = loader.load_metadata()
        names = [m.name for m in metadata]
        assert "file-management" in names
        assert "command-execution" in names
        assert "document-creation" in names

    def test_load_metadata_versions(self, loader):
        metadata = loader.load_metadata()
        for m in metadata:
            assert m.version == "1.0.0"

    def test_load_metadata_descriptions(self, loader):
        metadata = loader.load_metadata()
        descs = {m.name: m.description for m in metadata}
        assert "archivos" in descs["file-management"]
        assert "shell" in descs["command-execution"]
        assert "documentos" in descs["document-creation"]

    def test_load_metadata_tags(self, loader):
        metadata = loader.load_metadata()
        fm = next(m for m in metadata if m.name == "file-management")
        assert "files" in fm.tags
        assert "directories" in fm.tags

    def test_load_metadata_paths(self, loader, skills_dir):
        metadata = loader.load_metadata()
        fm = next(m for m in metadata if m.name == "file-management")
        assert fm.path == skills_dir / "file-management"

    def test_load_metadata_returns_skill_metadata(self, loader):
        metadata = loader.load_metadata()
        for m in metadata:
            assert isinstance(m, SkillMetadata)

    # ── load_body ──
    def test_load_body_file_management(self, loader):
        body = loader.load_body("file-management")
        assert "## Context" in body
        assert "Eres un experto en gestión de archivos" in body
        assert "---" not in body  # frontmatter debe estar removido

    def test_load_body_command_execution(self, loader):
        body = loader.load_body("command-execution")
        assert "## Constraints" in body
        assert "NO ejecutes sudo" in body

    def test_load_body_no_frontmatter(self, loader):
        """El body NO debe contener el frontmatter YAML."""
        body = loader.load_body("document-creation")
        assert "name: \"document-creation\"" not in body
        assert "version: \"1.0.0\"" not in body

    def test_load_body_not_found(self, loader):
        """Skill inexistente debe lanzar error claro."""
        with pytest.raises((FileNotFoundError, ValueError, KeyError)):
            loader.load_body("nonexistent-skill")

    # ── edge cases ──
    def test_empty_skills_dir(self, tmp_path):
        empty = tmp_path / "empty_skills"
        empty.mkdir()
        loader = SkillLoader(tmp_path)
        metadata = loader.load_metadata()
        assert metadata == []

    def test_skill_without_frontmatter(self, tmp_path):
        """SKILL.md sin frontmatter debe manejarse."""
        base = tmp_path / "bad_skill"
        base.mkdir()
        (base / "SKILL.md").write_text("No frontmatter here. Just markdown.")
        loader = SkillLoader(tmp_path / "bad_skill")
        # load_metadata debe manejar esto sin crash
        metadata = loader.load_metadata()
        # Puede retornar vacío o parsear lo que pueda
        assert isinstance(metadata, list)

    def test_skill_with_empty_tags(self, tmp_path):
        base = tmp_path / "no_tags"
        base.mkdir()
        (base / "SKILL.md").write_text("""---
name: "no-tags"
version: "1.0.0"
description: "Skill sin tags"
tags: []
---

Body here.
""")
        loader = SkillLoader(tmp_path)
        metadata = loader.load_metadata()
        assert len(metadata) == 1
        assert metadata[0].tags == []

    def test_skill_path_is_path_object(self, loader):
        metadata = loader.load_metadata()
        for m in metadata:
            assert isinstance(m.path, Path)

    def test_load_metadata_is_fast(self, loader):
        """load_metadata debe ser rápido — solo parsea frontmatter, no cuerpo."""
        import time
        start = time.perf_counter()
        metadata = loader.load_metadata()
        elapsed = time.perf_counter() - start
        assert elapsed < 0.1  # debe ser casi instantáneo
        assert len(metadata) == 3
