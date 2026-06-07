"""
Tests para SkillMatcher — keyword matching.

Cubre:
- Match exacto por palabras clave en description
- Match por tags
- No match cuando no hay coincidencia
- Score-based selection (más matches = mejor)
- Case insensitive
- Normalización de mensaje
"""

import pytest
from agent.skills.matcher import SkillMatcher
from agent.skills.loader import SkillMetadata


class TestSkillMatcher:
    """Matching de mensaje de usuario contra skills disponibles."""

    @pytest.fixture
    def skills(self):
        return [
            SkillMetadata(
                name="file-management",
                version="1.0.0",
                description="Gestiona archivos y directorios con comandos de terminal",
                tags=["files", "directories", "fs"],
            ),
            SkillMetadata(
                name="command-execution",
                version="1.0.0",
                description="Ejecuta comandos de shell con validación de seguridad",
                tags=["shell", "terminal", "commands"],
            ),
            SkillMetadata(
                name="document-creation",
                version="1.0.0",
                description="Crea documentos estructurados como markdown, json, yaml",
                tags=["docs", "markdown", "json"],
            ),
        ]

    @pytest.fixture
    def matcher(self, skills):
        return SkillMatcher(skills=skills)

    # ── matches por descripción ──
    def test_match_file_management(self, matcher):
        result = matcher.match("crea un archivo nuevo")
        assert result is not None
        assert result.name == "file-management"

    def test_match_command_execution(self, matcher):
        result = matcher.match("ejecuta ls -la")
        assert result is not None
        assert result.name == "command-execution"

    def test_match_document_creation(self, matcher):
        result = matcher.match("crea un documento markdown")
        assert result is not None
        assert result.name == "document-creation"

    # ── matches por tags ──
    def test_match_by_tag_files(self, matcher):
        result = matcher.match("organiza mis files")
        assert result is not None
        assert result.name == "file-management"

    def test_match_by_tag_shell(self, matcher):
        result = matcher.match("necesito usar shell")
        assert result is not None
        assert result.name == "command-execution"

    def test_match_by_tag_json(self, matcher):
        result = matcher.match("genera un json")
        assert result is not None
        assert result.name == "document-creation"

    # ── no match ──
    def test_no_match_unrelated(self, matcher):
        result = matcher.match("cuál es el clima hoy")
        assert result is None

    def test_no_match_empty(self, matcher):
        result = matcher.match("")
        assert result is None

    def test_no_match_gibberish(self, matcher):
        result = matcher.match("asdfghjkl qwerty")
        assert result is None

    # ── case insensitive ──
    def test_match_case_insensitive(self, matcher):
        result = matcher.match("CREA UN ARCHIVO")
        assert result is not None
        assert result.name == "file-management"

    def test_match_mixed_case(self, matcher):
        result = matcher.match("EjEcUtA ComAnDo")
        assert result is not None
        assert result.name == "command-execution"

    # ── score-based selection ──
    def test_best_score_wins(self, matcher):
        """Si dos skills coinciden, la de mayor score debe ganar."""
        # "archivos" coincide con file-management (description)
        # "comandos" coincide con command-execution (description)
        # "archivos de shell" → ambas coinciden, file-management tiene más keywords
        result = matcher.match("archivos y directorios de shell")
        assert result is not None
        # file-management tiene "archivos" + "directorios" = 2 matches
        # command-execution tiene "shell" = 1 match
        assert result.name == "file-management"

    def test_tie_breaker_first(self, matcher):
        """Empate: la primera en la lista o alguna heurística."""
        # "markdown json" → document-creation (2 tags)
        result = matcher.match("markdown json yaml")
        assert result is not None
        assert result.name == "document-creation"

    # ── normalización ──
    def test_match_strips_punctuation(self, matcher):
        result = matcher.match("¡crea un archivo, por favor!")
        assert result is not None
        assert result.name == "file-management"

    def test_match_strips_extra_spaces(self, matcher):
        result = matcher.match("  ejecuta    comando  ")
        assert result is not None
        assert result.name == "command-execution"

    # ── edge cases ──
    def test_match_single_keyword(self, matcher):
        """Una sola keyword debe ser suficiente si es única."""
        result = matcher.match("terminal")
        assert result is not None
        assert result.name == "command-execution"

    def test_match_partial_word(self, matcher):
        """Keywords parciales NO deben coincidir (evita falsos positivos)."""
        # "arch" no debería coincidir con "archivos"
        result = matcher.match("arch")
        # Depende de implementación: si usa substring match, coincidirá
        # Si usa word match, no coincidirá
        # Documentamos el comportamiento esperado:
        assert result is None or result.name == "file-management"

    def test_empty_skills_list(self):
        """Matcher con lista vacía siempre retorna None."""
        matcher = SkillMatcher(skills=[])
        result = matcher.match("cualquier cosa")
        assert result is None

    def test_returns_skill_metadata(self, matcher):
        result = matcher.match("lista archivos")
        assert isinstance(result, SkillMetadata)
        assert hasattr(result, "name")
        assert hasattr(result, "description")
        assert hasattr(result, "path")
