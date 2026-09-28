"""
DIAGNÓSTICO DE WHATSAPP BUSINESS — solo lectura.
=================================================
Responde una sola pregunta: ¿este backend puede recibir y contestar mensajes
de WhatsApp ahora mismo, y si no, qué falta exactamente?

Existe porque el arranque de un número de WhatsApp tiene cuatro piezas en dos
consolas distintas (Railway y Meta) y cuando una falta el síntoma es el mismo:
silencio. Este endpoint las revisa contra la API de Meta en vivo y devuelve la
lista de pendientes en español, en vez de dejar que alguien adivine.

Además expone las dos acciones del arranque que en 2026 ya NO existen como
botón: desde junio de 2026 Meta solo permite registrar un número por API
(WhatsApp Manager dejó de poder hacerlo), y suscribir la app a la cuenta es un
POST. Van aquí, y no en un curl a mano, porque el token vive en Railway: así
nunca tiene que salir a una terminal ni al historial de comandos.

Autenticación: el mismo JWT admin del resto del panel (get_current_user).
"""

import logging
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.database import AdminUser
from app.email_service import (
    WHATSAPP_API_BASE_URL,
    WHATSAPP_API_TOKEN,
    WHATSAPP_API_VERSION,
    WHATSAPP_PHONE_ID_FINAL,
    WHATSAPP_WABA_ID,
)
from app.routes.radicacion import get_current_user
from app.routes.whatsapp_webhook import (
    WHATSAPP_APP_SECRET,
    WHATSAPP_WEBHOOK_VERIFY_TOKEN,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/whatsapp", tags=["WhatsApp"])

# Campos que Meta expone del número. `status` es el que dice si quedó
# registrado (CONNECTED) o solo verificado.
CAMPOS_NUMERO = (
    "id,display_phone_number,verified_name,code_verification_status,"
    "quality_rating,platform_type,status,name_status"
)

TIMEOUT = 15.0

# Los dos únicos permisos que pide Cloud API. Falta el de management y el
# registro del número falla con un error 200 que no explica nada.
PERMISOS_REQUERIDOS = ("whatsapp_business_management", "whatsapp_business_messaging")


def _graph(ruta: str, params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Llama al Graph API y nunca lanza: el diagnóstico siempre responde algo."""
    if not WHATSAPP_API_TOKEN:
        return {"error": "Sin WHATSAPP_BUSINESS_API_TOKEN: no se puede consultar a Meta"}
    try:
        resp = requests.get(
            f"{WHATSAPP_API_BASE_URL}/{ruta}",
            params=params or {},
            headers={"Authorization": f"Bearer {WHATSAPP_API_TOKEN}"},
            timeout=TIMEOUT,
        )
    except Exception as e:
        logger.warning(f"Diagnóstico WhatsApp: fallo consultando {ruta}: {e}")
        return {"error": f"No se pudo contactar a Meta: {e}"}

    try:
        datos = resp.json()
    except ValueError:
        return {"error": f"Meta respondió {resp.status_code} con un cuerpo no-JSON"}

    if resp.status_code >= 400:
        # El mensaje de Meta es la mitad del diagnóstico ("token expirado",
        # "el número no pertenece a esta cuenta"): se devuelve textual.
        detalle = (datos.get("error") or {}).get("message") or str(datos)[:300]
        return {"error": f"Meta {resp.status_code}: {detalle}"}
    return datos


@router.get("/diagnostico")
def diagnostico(
    request: Request,
    user: AdminUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Estado real del canal de WhatsApp. Devuelve `listo_para_recibir` y, si es
    false, `pendientes` con el paso que falta.

    Nunca devuelve el token ni el App Secret: solo si están puestos.
    """
    pendientes: List[str] = []

    configuracion = {
        "token": bool(WHATSAPP_API_TOKEN),
        "phone_number_id": WHATSAPP_PHONE_ID_FINAL or None,
        "waba_id": WHATSAPP_WABA_ID or None,
        "app_secret": bool(WHATSAPP_APP_SECRET),
        "verify_token": bool(WHATSAPP_WEBHOOK_VERIFY_TOKEN),
        "api_version": WHATSAPP_API_VERSION,
    }

    if not WHATSAPP_API_TOKEN:
        pendientes.append("Falta WHATSAPP_BUSINESS_API_TOKEN en Railway (token permanente del System User).")
    if not WHATSAPP_PHONE_ID_FINAL:
        pendientes.append("Falta WHATSAPP_PHONE_NUMBER_ID en Railway (identificador del número, no el número).")
    if not WHATSAPP_WEBHOOK_VERIFY_TOKEN:
        pendientes.append("Falta WHATSAPP_WEBHOOK_VERIFY_TOKEN en Railway: sin él Meta no puede verificar la URL del webhook (responde 403).")
    if not WHATSAPP_APP_SECRET:
        pendientes.append("Falta WHATSAPP_APP_SECRET en Railway: sin él no se valida la firma de los webhooks entrantes.")
    if not WHATSAPP_WABA_ID:
        pendientes.append("Falta WHATSAPP_WABA_ID en Railway: sin él no se puede verificar si la app quedó suscrita a la cuenta.")

    # ── El token ─────────────────────────────────────────────────────────
    # Se revisa primero porque un token vencido o sin permisos hace fallar
    # todo lo de abajo con errores que apuntan al lado equivocado.
    token: Dict[str, Any] = {}
    if WHATSAPP_API_TOKEN:
        # debug_token se autentica con el mismo token que inspecciona.
        crudo = _graph(
            "debug_token",
            {"input_token": WHATSAPP_API_TOKEN, "access_token": WHATSAPP_API_TOKEN},
        )
        if crudo.get("error"):
            token = {"error": crudo["error"]}
            pendientes.append(f"No se pudo validar el token — {crudo['error']}")
        else:
            datos = crudo.get("data") or {}
            caduca = datos.get("expires_at")
            permisos = datos.get("scopes") or []
            faltantes = [p for p in PERMISOS_REQUERIDOS if p not in permisos]
            token = {
                "valido": bool(datos.get("is_valid")),
                "tipo": datos.get("type"),
                "app_id": datos.get("app_id"),
                # expires_at = 0 significa que no caduca (System User permanente).
                "permanente": caduca == 0,
                "caduca_en": None if caduca == 0 else caduca,
                "permisos": permisos,
                "permisos_faltantes": faltantes,
            }
            if not datos.get("is_valid"):
                pendientes.append("El token no es válido (vencido o revocado): genera uno nuevo de System User.")
            elif caduca != 0:
                pendientes.append(
                    "El token CADUCA: es temporal, no de System User permanente. "
                    "El canal se va a caer solo cuando expire."
                )
            if faltantes:
                pendientes.append(
                    f"Al token le faltan permisos: {', '.join(faltantes)}. "
                    "Se agregan al generarlo en Configuración del negocio → Usuarios del sistema."
                )

    # ── El número ────────────────────────────────────────────────────────
    numero: Dict[str, Any] = {}
    if WHATSAPP_PHONE_ID_FINAL:
        numero = _graph(WHATSAPP_PHONE_ID_FINAL, {"fields": CAMPOS_NUMERO})
        estado = (numero.get("status") or "").upper()
        numero["registrado"] = estado == "CONNECTED"
        if numero.get("error"):
            pendientes.append(f"No se pudo leer el número en Meta — {numero['error']}")
        elif not numero["registrado"]:
            pendientes.append(
                f"El número aparece como '{numero.get('status') or 'sin registrar'}' en Meta. "
                "Registrarlo con POST /admin/whatsapp/registrar (un PIN de 6 dígitos). "
                "No se puede registrar desde WhatsApp Manager: desde junio de 2026 Meta "
                "solo permite el registro por API. Lo que sí se hace en WhatsApp Manager "
                "es verificar la propiedad del número (código por SMS o llamada), y eso "
                "va antes del registro."
            )

    # ── La suscripción de webhooks de la cuenta ──────────────────────────
    # Detrás del proxy de Railway url_for puede devolver http://; Meta exige
    # https y esta URL se copia y pega tal cual en la consola.
    url_webhook = str(request.url_for("recibir_webhook"))
    if url_webhook.startswith("http://") and "localhost" not in url_webhook:
        url_webhook = "https://" + url_webhook[len("http://"):]
    webhook: Dict[str, Any] = {"url_esperada": url_webhook}
    if WHATSAPP_WABA_ID:
        suscritas = _graph(f"{WHATSAPP_WABA_ID}/subscribed_apps")
        if suscritas.get("error"):
            webhook["error"] = suscritas["error"]
            pendientes.append(f"No se pudo leer las apps suscritas — {suscritas['error']}")
        else:
            apps = suscritas.get("data") or []
            webhook["apps_suscritas"] = [
                {
                    "id": (a.get("whatsapp_business_api_data") or {}).get("id"),
                    "nombre": (a.get("whatsapp_business_api_data") or {}).get("name"),
                }
                for a in apps
            ]
            webhook["esta_suscrita"] = bool(apps)
            if not apps:
                pendientes.append(
                    "Ninguna app está suscrita a esta cuenta de WhatsApp: en Meta → "
                    "WhatsApp → Configuración de la API, botón 'Suscribir webhooks'. "
                    "Sin esto los mensajes entrantes nunca llegan al backend."
                )

    return {
        "listo_para_recibir": not pendientes,
        "pendientes": pendientes,
        "configuracion": configuracion,
        "token": token,
        "numero": numero,
        "webhook": webhook,
    }


# ═══════════════════════════════════════════════════════════════════════
# ACCIONES DE ARRANQUE — escriben en Meta, requieren el mismo JWT admin
# ═══════════════════════════════════════════════════════════════════════

# Meta bloquea el número 72 horas al décimo intento de registro (error 133016),
# así que estos endpoints no reintentan nunca solos: devuelven el error textual
# y se detienen. Un reintento automático aquí cuesta tres días de canal caído.
LIMITE_REGISTROS_72H = 10


class RegistrarNumero(BaseModel):
    pin: str = Field(
        ...,
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
        description=(
            "PIN de verificación en dos pasos de 6 dígitos. Si el número aún no "
            "tiene verificación en dos pasos, ESTE PIN queda como el definitivo: "
            "hay que guardarlo, Meta lo vuelve a pedir después."
        ),
    )


def _graph_post(ruta: str, cuerpo: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """POST al Graph API. No reintenta: ver LIMITE_REGISTROS_72H."""
    if not WHATSAPP_API_TOKEN:
        raise HTTPException(400, "Falta WHATSAPP_BUSINESS_API_TOKEN en Railway.")
    try:
        resp = requests.post(
            f"{WHATSAPP_API_BASE_URL}/{ruta}",
            json=cuerpo or {},
            headers={
                "Authorization": f"Bearer {WHATSAPP_API_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=TIMEOUT,
        )
    except Exception as e:
        # Sin respuesta de Meta no se sabe si la acción se aplicó: 502 para que
        # quien llame consulte el diagnóstico antes de volver a intentar.
        logger.error(f"WhatsApp: fallo POST {ruta}: {e}")
        raise HTTPException(502, f"No se pudo contactar a Meta: {e}")

    try:
        datos = resp.json()
    except ValueError:
        datos = {}

    if resp.status_code >= 400:
        err = datos.get("error") or {}
        codigo = err.get("code")
        mensaje = err.get("message") or f"Meta respondió {resp.status_code}"
        if codigo == 133016:
            mensaje = (
                "Meta bloqueó el número por 72 horas: se superaron los 10 intentos "
                f"de registro en esa ventana ({mensaje})"
            )
        logger.error(f"WhatsApp POST {ruta} → {resp.status_code} código={codigo}")
        raise HTTPException(400, mensaje)

    return datos


@router.post("/registrar")
def registrar_numero(
    body: RegistrarNumero,
    user: AdminUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Registra el número en Cloud API. Requiere que la propiedad del número ya
    esté verificada en WhatsApp Manager (código por SMS o llamada).

    El PIN no se guarda ni se registra en logs en ningún momento.
    """
    if not WHATSAPP_PHONE_ID_FINAL:
        raise HTTPException(400, "Falta WHATSAPP_PHONE_NUMBER_ID en Railway.")

    logger.info(f"WhatsApp: registrando número {WHATSAPP_PHONE_ID_FINAL} (pedido por {user.email})")
    datos = _graph_post(
        f"{WHATSAPP_PHONE_ID_FINAL}/register",
        {"messaging_product": "whatsapp", "pin": body.pin},
    )
    return {
        "exito": bool(datos.get("success")),
        "respuesta_meta": datos,
        "recordatorio": (
            "Guarda el PIN: queda como la verificación en dos pasos del número y "
            "Meta lo exige para re-registrar o cambiar el nombre visible."
        ),
    }


@router.post("/suscribir-webhooks")
def suscribir_webhooks(
    user: AdminUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Suscribe esta app a los webhooks de la cuenta de WhatsApp (equivale al botón
    'Suscribir webhooks' de la consola). Es idempotente: repetirlo no duplica.

    Ojo: esto conecta la cuenta con la app, pero la URL del callback y el campo
    'messages' se configuran en la app (Meta → WhatsApp → Configuración). Sin
    las dos mitades no entra ningún mensaje.
    """
    if not WHATSAPP_WABA_ID:
        raise HTTPException(400, "Falta WHATSAPP_WABA_ID en Railway.")

    logger.info(f"WhatsApp: suscribiendo app a WABA {WHATSAPP_WABA_ID} (pedido por {user.email})")
    datos = _graph_post(f"{WHATSAPP_WABA_ID}/subscribed_apps")
    return {"exito": bool(datos.get("success")), "respuesta_meta": datos}
