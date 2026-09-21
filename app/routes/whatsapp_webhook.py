"""
Webhook de WhatsApp Business (Meta Graph API) — canal de entrada del bot
conversacional de incapacidades.

Requiere en Railway:
  WHATSAPP_WEBHOOK_VERIFY_TOKEN  -> string propio, se configura también en
                                     Meta Business Suite al registrar la URL.
  WHATSAPP_APP_SECRET            -> App Secret de la app de Meta (Configuración
                                     básica), usado para validar la firma
                                     X-Hub-Signature-256 de cada webhook.
Reutiliza WHATSAPP_BUSINESS_API_TOKEN / WHATSAPP_PHONE_NUMBER_ID ya configuradas
para el envío saliente (mismo número/app).
"""

import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response

from app.database import SessionLocal
from app.services import whatsapp_bot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook/whatsapp", tags=["WhatsApp Webhook"])

WHATSAPP_WEBHOOK_VERIFY_TOKEN = os.environ.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN")
WHATSAPP_APP_SECRET = os.environ.get("WHATSAPP_APP_SECRET")

if not WHATSAPP_WEBHOOK_VERIFY_TOKEN:
    logger.warning("⚠️ WHATSAPP_WEBHOOK_VERIFY_TOKEN no configurado — el handshake de verificación con Meta fallará.")
if not WHATSAPP_APP_SECRET:
    logger.warning("⚠️ WHATSAPP_APP_SECRET no configurado — no se valida la firma de los webhooks entrantes.")


@router.get("")
async def verificar_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Handshake de verificación que Meta exige al registrar la URL del webhook."""
    if (
        hub_mode == "subscribe"
        and WHATSAPP_WEBHOOK_VERIFY_TOKEN
        and hub_verify_token == WHATSAPP_WEBHOOK_VERIFY_TOKEN
    ):
        return Response(content=hub_challenge or "", media_type="text/plain")
    return Response(status_code=403)


def _firma_valida(cuerpo_crudo: bytes, firma_header: str) -> bool:
    if not firma_header or "=" not in firma_header:
        return False
    _, firma_recibida = firma_header.split("=", 1)
    firma_esperada = hmac.new(WHATSAPP_APP_SECRET.encode(), cuerpo_crudo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(firma_esperada, firma_recibida)


def _procesar_en_background(telefono: str, message_id: str, mensaje: dict) -> None:
    db = SessionLocal()
    try:
        whatsapp_bot.procesar_mensaje_entrante(db, telefono, message_id, mensaje)
    except Exception as e:
        logger.error(f"Error en background procesando WhatsApp de {telefono}: {e}")
    finally:
        db.close()


@router.post("")
async def recibir_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Recibe mensajes/estados de WhatsApp. Responde 200 de inmediato (Meta
    reintenta el POST si no lo hace a tiempo) y procesa cada mensaje en
    background para no bloquear el webhook con consultas a BD/Drive.
    """
    cuerpo_crudo = await request.body()

    if WHATSAPP_APP_SECRET:
        firma = request.headers.get("x-hub-signature-256", "")
        if not _firma_valida(cuerpo_crudo, firma):
            logger.warning("⚠️ Firma inválida en webhook de WhatsApp — solicitud rechazada.")
            return Response(status_code=403)

    try:
        payload = await request.json()
    except Exception:
        return Response(status_code=200)  # cuerpo no-JSON: nada que procesar

    if payload.get("object") != "whatsapp_business_account":
        return Response(status_code=200)

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {}) or {}
            for mensaje in value.get("messages", []) or []:
                telefono = mensaje.get("from")
                message_id = mensaje.get("id")
                if telefono and message_id:
                    background_tasks.add_task(_procesar_en_background, telefono, message_id, mensaje)
            # Los "statuses" (delivered/read/failed) no requieren acción del bot por ahora.

    return Response(status_code=200)
