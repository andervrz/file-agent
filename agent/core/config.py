# agent/core/config.py
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentMeta(BaseModel):
    name: str
    version: str
    description: str


class LLMConfig(BaseModel):
    provider: str
    host: str
    model: str
    temperature: float = 0.1
    num_ctx: int = 4096
    num_predict: int = 1024


class ContextConfig(BaseModel):
    max_history_messages: int = 10
    max_iterations: int = 15


class SkillsConfig(BaseModel):
    path: str = "./skills"


class MemoryConfig(BaseModel):
    enabled: bool = False
    path: str = "./memory"


class TracesConfig(BaseModel):
    enabled: bool = True
    path: str = "./traces"


class SecurityConfig(BaseModel):
    levels: dict[str, list[str]] = Field(default_factory=dict)
    require_confirmation: list[str] = Field(default_factory=list)
    blocked_paths: list[str] = Field(default_factory=list)
    timeout_seconds: dict[str, int] = Field(default_factory=dict)


class ToolsConfig(BaseModel):
    enabled: list[str] = Field(default_factory=list)


class AgentConfig(BaseModel):
    agent: AgentMeta
    llm: LLMConfig
    system_prompt: str
    tools: ToolsConfig
    context: ContextConfig
    skills: SkillsConfig
    memory: MemoryConfig
    traces: TracesConfig
    security: SecurityConfig


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ollama_api_key: str = ""
    ollama_host: str = "https://ollama.com"
    agent_yaml_path: str = "agent.yaml"
    traces_dir: str = "./traces"
    log_level: str = "INFO"


def load_config(yaml_path: str | Path | None = None) -> tuple[AgentConfig, Settings]:
    if yaml_path is None:
        yaml_path = "agent.yaml"
    path = Path(yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path.resolve()}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    agent_config = AgentConfig.model_validate(raw)
    settings = Settings()
    
    # Inyectar home real del sistema operativo en el system_prompt
    home = str(Path.home())
    agent_config.system_prompt = agent_config.system_prompt.replace("{HOME}", home)
    
    return agent_config, settings