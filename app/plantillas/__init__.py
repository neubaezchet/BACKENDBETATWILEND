"""
Plantillas de WhatsApp versionadas en el repo.

Mismo criterio que `app/agentes/`: una plantilla escrita a mano en WhatsApp
Manager queda fuera de todo diff y es irreconstruible. Aquí viven el texto, las
variables y la categoría; `sincronizar.py` las publica en Meta.
"""

from app.plantillas.whatsapp import (
    PLANTILLAS,
    IDIOMA,
    componentes_para_crear,
    payload_para_crear,
    payload_para_enviar,
)

__all__ = [
    "PLANTILLAS",
    "IDIOMA",
    "componentes_para_crear",
    "payload_para_crear",
    "payload_para_enviar",
]
