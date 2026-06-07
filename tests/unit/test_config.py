"""
Tests para config.py — carga de agent.yaml y .env.

Cubre:
- load_config() retorna AgentConfig + Settings
- Pydantic valida tipos correctamente
- Valores por defecto cuando faltan campos
- FileNotFoundError si agent.yaml no existe
- Variables de entorno desde .env
"""

import os
import pytest
from pathlib import Path
from pydantic import ValidationError

from agent.core.config import (
    load_config,
    AgentConfig,
    AgentMeta,
    LLMConfig,
    ContextConfig,
    SkillsConfig,
    MemoryConfig,
    TracesConfig,
    SecurityConfig,
    ToolsConfig,
    Settings,
)


class TestLoadConfig:
    """Carga de configuración desde YAML + .env."""

    @pytest.fixture
    def valid_yaml(self, tmp_path):
        yaml = tmp_path / "agent.yaml"
        yaml.write_text("""
agent:
  name: "Test Agent"
  version: "1.0.0"
  description: "Test description"
llm:
  provider: "ollama"
  host: "https://ollama.com"
  model: "gpt-oss:20b"
  temperature: 0.1
  num_ctx: 4096
  num_predict: 2048
system_prompt: "Eres un agente de prueba."
tools:
  enabled:
    - create_file
    - read_file
context:
  max_history_messages: 10
  max_iterations: 25
skills:
  path: "./skills"
memory:
  enabled: false
  path: "./memory"
traces:
  enabled: true
  path: "./traces"
security:
  levels:
    safe: [ls, cat]
    moderate: [touch, mkdir]
    dangerous: [rm]
    blocked: [sudo]
  require_confirmation: [dangerous]
  blocked_paths:
    - /etc
  timeout_seconds:
    safe: 10
    moderate: 30
    dangerous: 60
""")
        return yaml

    def test_load_config_returns_tuple(self, valid_yaml):
        config, settings = load_config(valid_yaml)
        assert isinstance(config, AgentConfig)
        assert isinstance(settings, Settings)

    def test_agent_meta(self, valid_yaml):
        config, _ = load_config(valid_yaml)
        assert config.agent.name == "Test Agent"
        assert config.agent.version == "1.0.0"
        assert config.agent.description == "Test description"

    def test_llm_config(self, valid_yaml):
        config, _ = load_config(valid_yaml)
        assert config.llm.provider == "ollama"
        assert config.llm.model == "gpt-oss:20b"
        assert config.llm.temperature == 0.1
        assert config.llm.num_ctx == 4096
        assert config.llm.num_predict == 2048

    def test_system_prompt(self, valid_yaml):
        config, _ = load_config(valid_yaml)
        assert "Eres un agente de prueba" in config.system_prompt

    def test_tools_enabled(self, valid_yaml):
        config, _ = load_config(valid_yaml)
        assert "create_file" in config.tools.enabled
        assert "read_file" in config.tools.enabled

    def test_context_config(self, valid_yaml):
        config, _ = load_config(valid_yaml)
        assert config.context.max_history_messages == 10
        assert config.context.max_iterations == 25

    def test_security_config(self, valid_yaml):
        config, _ = load_config(valid_yaml)
        assert "rm" in config.security.levels["dangerous"]
        assert "sudo" in config.security.levels["blocked"]
        assert "/etc" in config.security.blocked_paths
        assert config.security.timeout_seconds["safe"] == 10

    def test_traces_config(self, valid_yaml):
        config, _ = load_config(valid_yaml)
        assert config.traces.enabled is True
        assert config.traces.path == "./traces"

    def test_memory_disabled(self, valid_yaml):
        config, _ = load_config(valid_yaml)
        assert config.memory.enabled is False

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml")

    def test_load_config_with_none_uses_default(self, monkeypatch, tmp_path):
        """Si yaml_path es None, usa el default (settings.agent_yaml_path)."""
        fake_yaml = tmp_path / "agent.yaml"
        fake_yaml.write_text("""
agent:
  name: "Default"
  version: "1.0.0"
  description: "d"
llm:
  provider: "ollama"
  host: "https://ollama.com"
  model: "gpt-oss:20b"
  temperature: 0.1
  num_ctx: 4096
  num_predict: 1024
system_prompt: "sys"
tools:
  enabled: []
context:
  max_history_messages: 10
  max_iterations: 15
skills:
  path: "./skills"
memory:
  enabled: false
  path: "./memory"
traces:
  enabled: true
  path: "./traces"
security:
  levels:
    safe: []
    moderate: []
    dangerous: []
    blocked: []
  require_confirmation: []
  blocked_paths: []
  timeout_seconds:
    safe: 10
    moderate: 30
    dangerous: 60
""")
        monkeypatch.setenv("AGENT_YAML_PATH", str(fake_yaml))
        monkeypatch.chdir(tmp_path)
        config, _ = load_config()
        assert config.agent.name == "Default"


class TestSettings:
    """Variables de entorno desde .env."""

    def test_settings_from_env(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_API_KEY", "test-key-123")
        monkeypatch.setenv("OLLAMA_HOST", "https://test.ollama.com")
        monkeypatch.setenv("AGENT_YAML_PATH", "custom.yaml")
        monkeypatch.setenv("TRACES_DIR", "/tmp/traces")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        settings = Settings()
        assert settings.ollama_api_key == "test-key-123"
        assert settings.ollama_host == "https://test.ollama.com"
        assert settings.agent_yaml_path == "custom.yaml"
        assert settings.traces_dir == "/tmp/traces"
        assert settings.log_level == "DEBUG"

    def test_settings_extra_ignore(self, monkeypatch):
        """Variables extra deben ser ignoradas, no lanzar error."""
        monkeypatch.setenv("OLLAMA_API_KEY", "key")
        monkeypatch.setenv("RANDOM_VAR", "should_be_ignored")
        settings = Settings()
        assert settings.ollama_api_key == "key"

    def test_settings_default_values(self, monkeypatch):
        """Sin .env, los valores por defecto deben cargarse."""
        # Limpiamos variables para forzar defaults
        for key in ["OLLAMA_API_KEY", "OLLAMA_HOST", "AGENT_YAML_PATH", "TRACES_DIR", "LOG_LEVEL"]:
            monkeypatch.delenv(key, raising=False)
        settings = Settings()
        assert settings.ollama_host == "https://ollama.com"
        assert settings.agent_yaml_path == "agent.yaml"
        assert settings.traces_dir == "./traces"
        assert settings.log_level == "INFO"


class TestPydanticValidation:
    """Validación estricta de tipos."""

    def test_llm_config_temperature_range(self):
        """temperature fuera de rango debe ser aceptada (Pydantic no valida rango sin Field)."""
        config = LLMConfig(
            provider="ollama",
            host="https://ollama.com",
            model="gpt-oss:20b",
            temperature=5.0,  # fuera de rango lógico pero válido como float
            num_ctx=4096,
            num_predict=1024,
        )
        assert config.temperature == 5.0

    def test_llm_config_invalid_type(self):
        """temperature como string debe fallar."""
        with pytest.raises(ValidationError):
            LLMConfig(
                provider="ollama",
                host="https://ollama.com",
                model="gpt-oss:20b",
                temperature="hot",  # invalido
                num_ctx=4096,
                num_predict=1024,
            )

    def test_security_config_missing_level(self):
        """SecurityConfig puede tener niveles vacíos."""
        config = SecurityConfig(
            levels={"safe": [], "moderate": [], "dangerous": [], "blocked": []},
            require_confirmation=[],
            blocked_paths=[],
            timeout_seconds={"safe": 10, "moderate": 30, "dangerous": 60},
        )
        assert config.levels["safe"] == []

    def test_agent_config_complete(self):
        """AgentConfig requiere todos los campos."""
        config = AgentConfig(
            agent=AgentMeta(name="x", version="1", description="d"),
            llm=LLMConfig(provider="o", host="h", model="m", temperature=0.1, num_ctx=1, num_predict=1),
            system_prompt="sys",
            tools=ToolsConfig(enabled=[]),
            context=ContextConfig(max_history_messages=1, max_iterations=1),
            skills=SkillsConfig(path="./s"),
            memory=MemoryConfig(enabled=False, path="./m"),
            traces=TracesConfig(enabled=True, path="./t"),
            security=SecurityConfig(
                levels={"safe": [], "moderate": [], "dangerous": [], "blocked": []},
                require_confirmation=[],
                blocked_paths=[],
                timeout_seconds={"safe": 1, "moderate": 1, "dangerous": 1},
            ),
        )
        assert config.agent.name == "x"
