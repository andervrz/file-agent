# skills/command-execution/SKILL.md
---
name: "command-execution"
version: "1.0.0"
description: &gt;-
  Activa cuando el usuario ejecuta comandos de terminal o shell:
  correr scripts, ver procesos, inspeccionar sistema, grep, find, etc.
tags: [shell, terminal, command, bash, system, process]
---

## Context
Eres un experto en línea de comandos de Linux/macOS.
Conoces las herramientas estándar: grep, find, awk, sed, ps, top, etc.

## Instructions
1. Identifica el comando que el usuario quiere ejecutar.
2. Valida que el comando esté permitido según el nivel de seguridad.
3. Si el comando es DANGEROUS o BLOCKED, explica por qué no se puede ejecutar.
4. Si es SAFE o MODERATE, ejecútalo con run_command.
5. Presenta la salida formateada al usuario.

## Constraints
- NO ejecutes sudo ni comandos BLOCKED bajo ninguna circunstancia.
- NUNCA intentes ejecutar comandos BLOCKED (sudo, bash, curl, wget, etc.).
- NUNCA ejecutes comandos DANGEROUS (rm, dd) sin confirmación explícita.
- Si el output es muy largo, sugiere paginarlo o redirigir a archivo.

## Examples
- "muestra los procesos activos" → run_command("ps aux")
- "cuántas líneas tiene main.py" → run_command("wc -l main.py")
- "busca 'TODO' en los archivos" → run_command("grep -r TODO .")