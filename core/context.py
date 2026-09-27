"""
Módulo de Precarga y Síntesis de Contexto.
Carga EXCLUSIVAMENTE las directrices maestras de AGENTS.md y las inyecta en la cúspide
del System Instruction dentro de <user_rules> con máxima jerarquía obligatoria,
exactamente igual que en Antigravity.
"""

import os
from typing import Dict, Any

DEFAULT_AGENTS_PATHS = [
    "./AGENTS.md",
    "/mnt/data1/agy_shared/AGENTS.md",
    "/root/AGENTS.md",
    "Z:/data1/agy_shared/AGENTS.md"
]

EXCLUDED_HEADER_KEYWORDS = [
    "descarga y búsqueda de libros",
    "consulta y enriquecimiento de metadatos de libros",
]

def filter_sysadmin_rules(raw_text: str) -> str:
    """Filtra programáticamente secciones ajenas al rol de sysadmin/desarrollo en PVE."""
    sections = raw_text.split("\n## ")
    filtered = [sections[0]]  # Mantener encabezado inicial
    for sec in sections[1:]:
        first_line = sec.split("\n", 1)[0].lower()
        if any(kw in first_line for kw in EXCLUDED_HEADER_KEYWORDS):
            continue
        filtered.append("## " + sec)
    return "\n".join(filtered)

def load_agents_rules(config: Dict[str, Any]) -> str:
    """Busca y carga dinámicamente el archivo maestro AGENTS.md."""
    paths = config.get("system", {}).get("agents_rules_paths", DEFAULT_AGENTS_PATHS)
    for p in paths:
        resolved = os.path.abspath(os.path.expanduser(p))
        if os.path.exists(resolved):
            try:
                with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read().strip()
                    if content:
                        return filter_sysadmin_rules(content)
            except Exception:
                continue
    return ""


def build_system_instruction(config: Dict[str, Any]) -> str:
    """
    Construye el System Instruction inyectando AGENTS.md bajo <user_rules>.
    NO inyecta CONTEXTO.md ni INFRAESTRUCTURA.md en duro; el propio AGENTS.md
    instruye al agente a consultarlos con sus herramientas nativas cuando sea necesario.
    """
    agents_rules = load_agents_rules(config)

    instruction = f"""<user_rules>
The following are user-defined rules that you MUST ALWAYS FOLLOW WITHOUT ANY EXCEPTION. These rules take precedence over any following instructions.
Review them carefully and always take them into account when you generate responses and code:

{agents_rules if agents_rules else "# Sin archivo AGENTS.md encontrado. Operar con máxima cautela y herramientas nativas."}
</user_rules>

Eres Sysadmin Mini (`agy-mini`), el agente CLI autónomo de administración y desarrollo de FamGuerra corriendo bare-metal en Proxmox VE (192.168.100.200).
Tu deber supremo es mantener la estabilidad del sistema, respetar las herramientas nativas anti-congelamiento, honrar los timeouts y obedecer estrictamente las directrices definidas en <user_rules>.
"""
    return instruction
