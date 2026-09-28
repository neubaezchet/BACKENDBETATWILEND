"""
Prompts de los agentes de Browserbase, versionados en el repo.

Hasta ahora el paso a paso de cada bot vivía SOLO dentro de Browserbase: no se
podía revisar en un diff, ni saber quién lo cambió, ni reconstruirlo si se
borraba el agente. Aquí vive la fuente de verdad; Browserbase es solo el
destino donde se publica con `python -m app.agentes.sincronizar <eps_key>`.
"""

from app.agentes import compensar, compensar_reportes

# eps_key (el mismo de EmpresaBotConfig.bot_nombre / RadicacionSkill.eps_key)
AGENTES = {
    "compensar": compensar,
}

# Agentes de solo lectura que bajan los reportes del portal (motor del recobro).
# Van aparte porque se publican como agentes distintos en Browserbase y se
# registran en RadicacionSkill.agent_id_reportes, no en agent_id.
AGENTES_REPORTES = {
    "compensar": compensar_reportes,
}


def motivo_para(eps_key: str, tipo_incapacidad: str) -> str:
    """Traduce el tipo interno a la etiqueta exacta del desplegable de esa EPS.

    Cada portal nombra distinto lo mismo ("maternidad" es "Licencia de
    maternidad" en Compensar), y un motivo que no coincide con ninguna opción
    deja el combo vacío o elige mal: la EPS la rechaza semanas después.
    Las EPS sin mapeo propio reciben el texto legible de siempre.
    """
    modulo = AGENTES.get((eps_key or "").strip().lower())
    if modulo and hasattr(modulo, "motivo_portal"):
        return modulo.motivo_portal(tipo_incapacidad)
    return (tipo_incapacidad or "").replace("_", " ").title()


__all__ = [
    "AGENTES", "AGENTES_REPORTES", "motivo_para",
    "compensar", "compensar_reportes",
]
