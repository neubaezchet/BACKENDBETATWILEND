"""
Envío saliente de WhatsApp con manejo de la ventana de 24 horas.

**El problema que resuelve.** Meta solo acepta texto libre dentro de las 24
horas siguientes al último mensaje del colaborador. Pasado ese plazo devuelve
el error 131047 y el mensaje no llega. Todo lo que manda esta operación
(radicada, devuelta, pago reconocido, recordatorio de soporte) sale días
después de que la persona escribió, así que casi siempre cae fuera de la
ventana: sin plantilla, el aviso se pierde en silencio.

**Cómo decide.** Si la ventana está abierta manda texto libre — es gratis,
más flexible y no hay que pedirle permiso a Meta. Si está cerrada manda la
plantilla aprobada, que sí se factura. Y si Meta contesta 131047 aunque
creíamos la ventana abierta, reintenta **una sola vez** con la plantilla: la
cuenta local puede ir desfasada por un webhook perdido o por el reloj, y la
respuesta de Meta manda sobre lo que diga la base.

**Fail-safe.** Ninguna función de aquí levanta excepciones: si WhatsApp falla,
el correo y el guardado del caso tienen que seguir su curso. Devuelve siempre
un dict con lo que pasó, para que el llamador lo registre si quiere.

**Costo.** Cada plantilla enviada fuera de la ventana se cobra. La cadencia no
se decide aquí sino en `scheduler_recordatorios.py` (3 días → 5 días + jefe →
cada 3 días), de modo que el WhatsApp sale pegado al correo que ya existía y
no agrega un envío nuevo por día.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Sequence

import requests
from sqlalchemy.orm import Session

from app.database import WhatsAppConversacion
from app.email_service import (
    WHATSAPP_API_BASE_URL,
    WHATSAPP_API_TOKEN,
    WHATSAPP_PHONE_ID_FINAL,
    _WHATSAPP_BUSINESS_AVAILABLE,
)
from app.plantillas.whatsapp import PLANTILLAS, payload_para_enviar

logger = logging.getLogger(__name__)

VENTANA_HORAS = 24

# Margen de seguridad: si quedan menos de 15 minutos de ventana, se va directo
# por plantilla. Un mensaje que llega tarde por unos segundos se pierde entero,
# y reintentar cuesta más que haber mandado la plantilla de una.
MARGEN_MINUTOS = 15

# "Message failed to send because more than 24 hours have passed since the
# customer last replied to this number."
ERROR_FUERA_DE_VENTANA = 131047

TIMEOUT = 15


def _ahora() -> datetime:
    """
    Mismo reloj que el resto del repo. Ojo: `database.get_utc_now()` devuelve
    `datetime.now()` — hora local naive, pese al nombre — y es lo que queda
    guardado en `ultimo_entrante_en`. Comparar eso contra UTC correría la
    ventana 5 horas (Colombia es UTC-5) y mandaríamos texto libre cuando ya
    está cerrada. Se lee con el mismo reloj con el que se escribe.
    """
    return datetime.now()


def _normalizar(numero: str) -> str:
    """Mismo criterio que email_service._enviar_whatsapp_business."""
    numero = (numero or "").strip().replace(" ", "").replace("-", "")
    if numero.startswith("+"):
        numero = numero[1:]
    elif numero and not numero.startswith("57"):
        numero = "57" + numero
    return numero


def ultimo_entrante(db: Session, telefono: str) -> Optional[datetime]:
    """Cuándo escribió por última vez ese número, o None si nunca."""
    try:
        sesion = (
            db.query(WhatsAppConversacion)
            .filter(WhatsAppConversacion.telefono == _normalizar(telefono))
            .first()
        )
        if not sesion or not sesion.ultimo_entrante_en:
            return None
        return sesion.ultimo_entrante_en
    except Exception as e:
        logger.warning(f"No se pudo leer la ventana de {telefono}: {e}")
        return None


def ventana_abierta(db: Session, telefono: str) -> bool:
    """True si todavía se puede mandar texto libre a ese número."""
    marca = ultimo_entrante(db, telefono)
    if marca is None:
        return False
    limite = marca + timedelta(hours=VENTANA_HORAS) - timedelta(minutes=MARGEN_MINUTOS)
    return _ahora() < limite


def _post(payload: dict) -> tuple:
    """POST a Meta. Devuelve (ok, codigo_error, mensaje). Nunca levanta."""
    if not _WHATSAPP_BUSINESS_AVAILABLE:
        return False, None, "WhatsApp Business API no configurada"
    try:
        resp = requests.post(
            f"{WHATSAPP_API_BASE_URL}/{WHATSAPP_PHONE_ID_FINAL}/messages",
            json=payload,
            headers={
                "Authorization": f"Bearer {WHATSAPP_API_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=TIMEOUT,
        )
        if resp.status_code in (200, 201, 202):
            return True, None, ""
        try:
            err = resp.json().get("error", {})
            return False, err.get("code"), err.get("message", resp.text[:200])
        except Exception:
            return False, None, resp.text[:200]
    except Exception as e:
        return False, None, str(e)


def _payload_texto(telefono: str, texto: str) -> dict:
    return {
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "text",
        "text": {"preview_url": False, "body": texto},
    }


def notificar(
    db: Session,
    telefono: str,
    plantilla: str,
    valores: Sequence[str],
    texto_libre: Optional[str] = None,
    valor_boton_url: Optional[str] = None,
) -> dict:
    """
    Manda un aviso por WhatsApp eligiendo el canal que Meta permita.

    `plantilla` + `valores` son obligatorios porque son el único camino que
    funciona fuera de la ventana. `texto_libre` es opcional y solo se usa si la
    ventana está abierta; si no se pasa, se manda la plantilla siempre.

    Devuelve: {"enviado": bool, "via": "texto"|"plantilla"|None, "error": str|None}
    """
    if plantilla not in PLANTILLAS:
        logger.error(f"Plantilla desconocida: '{plantilla}'")
        return {"enviado": False, "via": None, "error": f"plantilla '{plantilla}' no existe"}

    numero = _normalizar(telefono)
    if not numero:
        return {"enviado": False, "via": None, "error": "teléfono vacío"}

    # 1) Ventana abierta y hay texto propio → texto libre (gratis y más rico).
    if texto_libre and ventana_abierta(db, numero):
        ok, codigo, mensaje = _post(_payload_texto(numero, texto_libre))
        if ok:
            return {"enviado": True, "via": "texto", "error": None}
        if codigo != ERROR_FUERA_DE_VENTANA:
            logger.warning(f"WhatsApp texto a {numero} falló: {mensaje}")
            return {"enviado": False, "via": "texto", "error": mensaje}
        # Meta dice que la ventana está cerrada aunque la BD creía que no.
        # Su palabra vale más que nuestra cuenta: se cae a plantilla.
        logger.info(f"Ventana cerrada para {numero} según Meta; se usa plantilla.")

    # 2) Plantilla.
    try:
        payload = payload_para_enviar(plantilla, numero, valores, valor_boton_url)
    except ValueError as e:
        logger.error(f"Plantilla '{plantilla}' mal llamada: {e}")
        return {"enviado": False, "via": "plantilla", "error": str(e)}

    ok, codigo, mensaje = _post(payload)
    if ok:
        return {"enviado": True, "via": "plantilla", "error": None}

    logger.warning(
        f"WhatsApp plantilla '{plantilla}' a {numero} falló "
        f"(code {codigo}): {mensaje}"
    )
    return {"enviado": False, "via": "plantilla", "error": mensaje}
