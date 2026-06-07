"""
Configuración compartida para todos los tests del File Agent.

Fixtures globales:
- tmp_path con estructura de proyecto
- event_loop para tests async
- monkeypatch para variables de entorno
"""

import pytest
import asyncio
from pathlib import Path


@pytest.fixture(scope="session")
def event_loop():
    """Crea un event loop para toda la sesión de tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def agent_yaml_minimal(tmp_path):
    """Genera un agent.yaml mínimo válido para tests."""
    yaml = tmp_path / "agent.yaml"
    yaml.write_text("""
agent:
  name: "Test Agent"
  version: "1.0.0"
  description: "Agente de prueba"
llm:
  provider: "ollama"
  host: "https://ollama.com"
  model: "gpt-oss:20b"
  temperature: 0.1
  num_ctx: 4096
  num_predict: 1024
system_prompt: "Eres File Agent."
tools:
  enabled:
    - create_file
    - read_file
    - list_directory
    - move_file
    - copy_file
    - delete_file
    - create_directory
    - search_files
    - run_command
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
    safe: [cat, ls, grep, find, head, tail, wc, pwd, echo, date]
    moderate: [touch, mkdir, cp, mv, chmod, ln]
    dangerous: [rm, rmdir, dd, truncate]
    blocked: [sudo, su, bash, sh, python, pip, apt, curl, wget, nc]
  require_confirmation: [dangerous]
  blocked_paths:
    - /etc
    - /sys
    - /usr
    - /bin
  timeout_seconds:
    safe: 10
    moderate: 30
    dangerous: 60
""")
    return yaml


@pytest.fixture
def env_vars(monkeypatch):
    """Set de variables de entorno mínimas para tests."""
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key-12345")
    monkeypatch.setenv("OLLAMA_HOST", "https://test.ollama.com")
    monkeypatch.setenv("AGENT_YAML_PATH", "agent.yaml")
    monkeypatch.setenv("TRACES_DIR", "./traces")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
