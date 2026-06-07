# agent/tools/template_tool.py
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from string import Template

from .base import BaseTool, PathSafeguard, ToolResult


class CreateFromTemplateTool(BaseTool):
    name = "create_from_template"
    description = "Crea un archivo desde un template predefinido con variables."
    input_schema = {
        "type": "object",
        "properties": {
            "template": {
                "type": "string",
                "description": "Nombre del template (readme, python_module, journal_entry, meeting_notes, spec)",
            },
            "output_path": {
                "type": "string",
                "description": "Ruta del archivo a crear",
            },
            "variables": {
                "type": "string",
                "description": '"KEY=valor,KEY2=valor2" — variables a sustituir (opcional)',
            },
        },
        "required": ["template", "output_path"],
    }

    def __init__(self, safeguard: PathSafeguard, skills_path: str):
        self._safeguard = safeguard
        self._templates_path = Path(skills_path) / "templates"

    async def execute(self, tool_use_id: str, **kwargs) -> ToolResult:
        try:
            template_name = kwargs.get("template", "").strip()
            output_path = self._safeguard.validate(kwargs["output_path"])
            variables_str = kwargs.get("variables", "")

            # Buscar template
            template_path = _find_template(self._templates_path, template_name)
            if not template_path:
                available = _list_templates(self._templates_path)
                return ToolResult(
                    tool_use_id=tool_use_id,
                    content=f"Template '{template_name}' no encontrado.\nDisponibles: {available}",
                    is_error=True,
                )

            variables = _parse_variables(variables_str)
            result = await asyncio.to_thread(
                _render_template, template_path, output_path, variables
            )
            return ToolResult(tool_use_id=tool_use_id, content=result)

        except PermissionError as e:
            return ToolResult(tool_use_id=tool_use_id, content=str(e), is_error=True)
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_use_id,
                content=f"Error al crear desde template: {e}",
                is_error=True,
            )


# ── Funciones auxiliares ───────────────────────────────────────────────────────

def _find_template(templates_path: Path, name: str) -> Path | None:
    """Busca {name}.* en el directorio de templates."""
    if not templates_path.exists():
        return None
    for path in templates_path.iterdir():
        if path.stem == name and path.is_file():
            return path
    return None


def _list_templates(templates_path: Path) -> str:
    if not templates_path.exists():
        return "(directorio de templates no encontrado)"
    names = [p.stem for p in templates_path.iterdir() if p.is_file()]
    return ", ".join(sorted(names)) if names else "(ninguno)"


def _parse_variables(variables_str: str) -> dict[str, str]:
    """'KEY=val,KEY2=val2' → {'KEY': 'val', 'KEY2': 'val2'} + auto vars."""
    now = datetime.now(timezone.utc)
    auto: dict[str, str] = {
        "DATE": now.strftime("%Y-%m-%d"),
        "DATETIME": now.strftime("%Y-%m-%d %H:%M:%S"),
        "YEAR": now.strftime("%Y"),
        "MONTH": now.strftime("%m"),
        "AUTHOR": "ANDERVRZ",
        "PROJECT_NAME": "Proyecto",
        "DESCRIPTION": "",
        "PARTICIPANTS": "",
        "MODULE_NAME": "modulo",
    }

    if variables_str:
        for pair in variables_str.split(","):
            pair = pair.strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                auto[k.strip().upper()] = v.strip()

    return auto


def _render_template(
    template_path: Path, output_path: Path, variables: dict[str, str]
) -> str:
    content = template_path.read_text(encoding="utf-8")
    rendered = Template(content).safe_substitute(variables)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    return f"Archivo creado desde template '{template_path.stem}': {output_path}"
