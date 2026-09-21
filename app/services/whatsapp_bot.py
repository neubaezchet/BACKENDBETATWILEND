"""
Bot conversacional de WhatsApp — módulo Incapacidades.

Flujo: tipo de documento -> número de documento -> confirmación de identidad
(o selección de empresa si la cédula existe en varias empresas) -> menú de
consultas (histórico de incapacidades / histórico de radicados / soporte).

Router de módulos: `WhatsAppConversacion.modulo` deja preparado el mismo
webhook para futuros bots (cartera, servicio automovilístico) — hoy solo
existe el handler de "incapacidades", registrado en HANDLERS_POR_MODULO.
"""

import io
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.database import Case, Company, Employee, WhatsAppConversacion, get_utc_now
from app.email_service import (
    WHATSAPP_API_BASE_URL,
    WHATSAPP_API_TOKEN,
    WHATSAPP_PHONE_ID_FINAL,
    _WHATSAPP_BUSINESS_AVAILABLE,
)

import requests

logger = logging.getLogger(__name__)

# ── Pasos del flujo (módulo incapacidades) ──────────────────────────────
PASO_INICIO = "inicio"
PASO_TIPO_DOC = "esperando_tipo_doc"
PASO_NUM_DOC = "esperando_num_doc"
PASO_ELEGIR_EMPRESA = "esperando_empresa"
PASO_CONFIRMAR = "esperando_confirmacion"
PASO_MENU = "menu"
PASO_SOPORTE_RADICADO = "esperando_radicado_soporte"

MAX_INTENTOS_CONFIRMACION = 3
SESSION_TIMEOUT = timedelta(minutes=20)
UMBRAL_EXCEL = 5  # más de esta cantidad de radicados -> se envía Excel en vez de texto

TIPOS_DOCUMENTO = [
    ("CC", "Cédula de ciudadanía"),
    ("CE", "Cédula de extranjería"),
    ("TI", "Tarjeta de identidad"),
    ("PA", "Pasaporte"),
    ("RC", "Registro civil"),
]


# ═══════════════════════════════════════════════════════════════════════
# ENVÍO — Graph API (texto, botones, listas, marcar leído)
# ═══════════════════════════════════════════════════════════════════════

def _headers() -> dict:
    return {
        "Authorization": f"Bearer {WHATSAPP_API_TOKEN}",
        "Content-Type": "application/json",
    }


def _post_mensaje(payload: dict) -> Optional[dict]:
    if not _WHATSAPP_BUSINESS_AVAILABLE:
        logger.warning("WhatsApp Business API no configurada; se omite el envío del bot.")
        return None
    url = f"{WHATSAPP_API_BASE_URL}/{WHATSAPP_PHONE_ID_FINAL}/messages"
    try:
        resp = requests.post(url, json=payload, headers=_headers(), timeout=15)
        if resp.status_code in (200, 201, 202):
            return resp.json()
        logger.error(f"Error enviando mensaje de WhatsApp bot ({resp.status_code}): {resp.text[:300]}")
        return None
    except Exception as e:
        logger.error(f"Excepción enviando mensaje de WhatsApp bot: {e}")
        return None


def marcar_leido_y_escribiendo(message_id: str) -> None:
    """Best-effort: marca el mensaje entrante como leído y muestra 'escribiendo...'."""
    if not message_id:
        return
    _post_mensaje({
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
        "typing_indicator": {"type": "text"},
    })


def enviar_texto(telefono: str, texto: str) -> Optional[dict]:
    return _post_mensaje({
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "text",
        "text": {"preview_url": True, "body": texto},
    })


def enviar_botones(telefono: str, texto: str, botones: list) -> Optional[dict]:
    """`botones`: lista de (id, title). Máximo 3 — límite de la API de Meta."""
    return _post_mensaje({
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": texto},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": bid, "title": title}}
                    for bid, title in botones
                ]
            },
        },
    })


def enviar_lista(telefono: str, texto: str, boton_texto: str, filas: list) -> Optional[dict]:
    """`filas`: lista de (id, title, description). Máximo 10 — límite de la API de Meta."""
    return _post_mensaje({
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": texto},
            "action": {
                "button": boton_texto,
                "sections": [
                    {
                        "title": "Opciones",
                        "rows": [
                            {"id": rid, "title": title[:24], "description": (desc or "")[:72]}
                            for rid, title, desc in filas
                        ],
                    }
                ],
            },
        },
    })


# ═══════════════════════════════════════════════════════════════════════
# PARSEO DEL MENSAJE ENTRANTE
# ═══════════════════════════════════════════════════════════════════════

def extraer_entrada(mensaje: dict) -> tuple:
    """Devuelve (tipo_entrada, valor): tipo_entrada en {'texto','boton','lista','otro'}."""
    tipo = mensaje.get("type")
    if tipo == "text":
        return "texto", (mensaje.get("text", {}).get("body") or "").strip()
    if tipo == "interactive":
        interactive = mensaje.get("interactive", {}) or {}
        if interactive.get("type") == "button_reply":
            return "boton", interactive.get("button_reply", {}).get("id", "")
        if interactive.get("type") == "list_reply":
            return "lista", interactive.get("list_reply", {}).get("id", "")
    return "otro", ""


# ═══════════════════════════════════════════════════════════════════════
# HELPERS DE SESIÓN
# ═══════════════════════════════════════════════════════════════════════

def _obtener_o_crear_sesion(db: Session, telefono: str) -> WhatsAppConversacion:
    sesion = db.query(WhatsAppConversacion).filter(WhatsAppConversacion.telefono == telefono).first()
    if not sesion:
        sesion = WhatsAppConversacion(
            telefono=telefono, modulo="incapacidades", paso=PASO_INICIO, datos_json={},
        )
        db.add(sesion)
        db.flush()
    return sesion


def _reset(sesion: WhatsAppConversacion) -> None:
    sesion.paso = PASO_INICIO
    sesion.datos_json = {}
    sesion.intentos_confirmacion = 0


def _fmt_fecha(fecha) -> str:
    if not fecha:
        return "N/A"
    try:
        return fecha.strftime("%d/%m/%Y")
    except Exception:
        return str(fecha)


# ═══════════════════════════════════════════════════════════════════════
# GENERACIÓN DE EXCEL (>5 radicados) — subido a Drive, se envía el link
# ═══════════════════════════════════════════════════════════════════════

def _subir_excel_bot(df: pd.DataFrame, empresa_nombre: str, cedula: str, tipo_reporte: str) -> Optional[str]:
    try:
        from app.utils.excel_formatter import ExcelFormatter
        from app.drive_uploader import get_authenticated_service, create_folder_if_not_exists, GOOGLE_SHARED_DRIVE_ID
        from googleapiclient.http import MediaIoBaseUpload

        contenido = ExcelFormatter.crear_excel(df, titulo=tipo_reporte)
        service = get_authenticated_service()

        base_folder_id = GOOGLE_SHARED_DRIVE_ID if GOOGLE_SHARED_DRIVE_ID != "root" else "root"
        main_folder_id = create_folder_if_not_exists(service, "Incapacidades", base_folder_id)
        empresa_folder_id = create_folder_if_not_exists(service, empresa_nombre or "Sin_Empresa", main_folder_id)
        bot_folder_id = create_folder_if_not_exists(service, "WhatsApp_Bot", empresa_folder_id)

        filename = f"{tipo_reporte}_{cedula}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        media = MediaIoBaseUpload(
            io.BytesIO(contenido),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            resumable=True,
        )
        file = service.files().create(
            body={"name": filename, "parents": [bot_folder_id]},
            media_body=media,
            fields="id,webViewLink",
            supportsAllDrives=True,
        ).execute()

        try:
            service.permissions().create(
                fileId=file.get("id"),
                body={"role": "reader", "type": "anyone"},
                supportsAllDrives=True,
            ).execute()
        except Exception as e:
            logger.warning(f"No se pudo hacer público el Excel del bot: {e}")

        return file.get("webViewLink") or f"https://drive.google.com/file/d/{file.get('id')}/view"
    except Exception as e:
        logger.error(f"Error subiendo Excel del bot de WhatsApp: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════
# CONSULTAS DE NEGOCIO
# ═══════════════════════════════════════════════════════════════════════

def _casos_empleado(db: Session, employee_id: int) -> list:
    return (
        db.query(Case)
        .filter(Case.employee_id == employee_id)
        .order_by(Case.fecha_inicio.desc())
        .all()
    )


def _responder_historico_incapacidades(db: Session, telefono: str, datos: dict) -> None:
    casos = _casos_empleado(db, datos.get("employee_id"))
    if not casos:
        enviar_texto(telefono, "No encontramos incapacidades registradas a tu nombre.")
        return

    if len(casos) > UMBRAL_EXCEL:
        df = pd.DataFrame([{
            "Radicado": c.serial,
            "Fecha inicio": c.fecha_inicio,
            "Fecha fin": c.fecha_fin,
            "Diagnóstico": c.diagnostico,
            "Estado": c.estado.value if c.estado else "",
        } for c in casos])
        link = _subir_excel_bot(df, datos.get("empresa_nombre"), datos.get("numero_documento"), "historico_incapacidades")
        if link:
            enviar_texto(telefono, f"Tienes {len(casos)} incapacidades registradas. Aquí está el detalle completo:\n{link}")
        else:
            enviar_texto(telefono, "Tienes varias incapacidades registradas, pero no pudimos generar el archivo. Intenta de nuevo más tarde.")
    else:
        lineas = [
            f"• {c.serial} — {_fmt_fecha(c.fecha_inicio)} a {_fmt_fecha(c.fecha_fin)} — "
            f"{c.diagnostico or 'Sin diagnóstico'} — {c.estado.value if c.estado else 'N/A'}"
            for c in casos
        ]
        enviar_texto(telefono, "Tu histórico de incapacidades:\n" + "\n".join(lineas))


def _responder_historico_radicados(db: Session, telefono: str, datos: dict) -> None:
    casos = _casos_empleado(db, datos.get("employee_id"))
    if not casos:
        enviar_texto(telefono, "No encontramos radicados asociados a tu documento.")
        return

    if len(casos) > UMBRAL_EXCEL:
        df = pd.DataFrame([{"Radicado": c.serial} for c in casos])
        link = _subir_excel_bot(df, datos.get("empresa_nombre"), datos.get("numero_documento"), "historico_radicados")
        if link:
            enviar_texto(telefono, f"Tienes {len(casos)} radicados. Aquí está tu listado completo:\n{link}")
        else:
            enviar_texto(telefono, "Tienes varios radicados, pero no pudimos generar el archivo. Intenta de nuevo más tarde.")
    else:
        seriales = "\n".join(f"• {c.serial}" for c in casos)
        enviar_texto(telefono, f"Tus radicados:\n{seriales}")


def _responder_soporte(db: Session, telefono: str, employee_id: int, serial: str) -> None:
    caso = (
        db.query(Case)
        .filter(Case.serial == serial, Case.employee_id == employee_id)
        .first()
    )
    if not caso:
        enviar_texto(telefono, f"No encontramos el radicado {serial} asociado a tu documento.")
    elif not caso.drive_link:
        enviar_texto(telefono, f"El radicado {serial} no tiene un soporte disponible todavía.")
    else:
        enviar_texto(telefono, f"Aquí tienes el soporte del radicado {serial}:\n{caso.drive_link}")


# ═══════════════════════════════════════════════════════════════════════
# MENÚ
# ═══════════════════════════════════════════════════════════════════════

def _enviar_menu(telefono: str, saludo: str = "¿Qué necesitas?") -> None:
    enviar_botones(telefono, saludo, [
        ("menu_hist_incap", "Hist. incapacidades"),
        ("menu_hist_radic", "Hist. radicados"),
        ("menu_soporte", "Soporte incapacidad"),
    ])


# ═══════════════════════════════════════════════════════════════════════
# HANDLERS POR PASO (módulo incapacidades)
# ═══════════════════════════════════════════════════════════════════════

def _handle_inicio(db: Session, sesion: WhatsAppConversacion, telefono: str, tipo_entrada: str, valor: str) -> None:
    enviar_lista(
        telefono,
        "¡Hola! Soy el asistente virtual de incapacidades. Para continuar, dime tu tipo de documento:",
        "Elegir tipo",
        [(codigo, nombre, None) for codigo, nombre in TIPOS_DOCUMENTO],
    )
    sesion.paso = PASO_TIPO_DOC


def _handle_tipo_doc(db: Session, sesion: WhatsAppConversacion, telefono: str, tipo_entrada: str, valor: str) -> None:
    codigos_validos = {c for c, _ in TIPOS_DOCUMENTO}
    if tipo_entrada != "lista" or valor not in codigos_validos:
        enviar_texto(telefono, "Por favor selecciona una opción válida de la lista.")
        return
    sesion.datos_json = {**(sesion.datos_json or {}), "tipo_documento": valor}
    enviar_texto(telefono, "Perfecto. Ahora escribe tu número de documento (sin puntos ni espacios).")
    sesion.paso = PASO_NUM_DOC


def _handle_num_doc(db: Session, sesion: WhatsAppConversacion, telefono: str, tipo_entrada: str, valor: str) -> None:
    numero = re.sub(r"\D", "", valor or "") if tipo_entrada == "texto" else ""
    if not numero:
        enviar_texto(telefono, "No reconocí un número de documento válido. Escríbelo solo con dígitos.")
        return

    empleados = (
        db.query(Employee)
        .filter(Employee.cedula == numero, Employee.activo == True)  # noqa: E712
        .all()
    )
    datos = {**(sesion.datos_json or {}), "numero_documento": numero}

    if not empleados:
        enviar_texto(telefono, "No encontramos ese documento registrado. Verifica el número o comunícate con Talento Humano de tu empresa.")
        _reset(sesion)
        return

    if len(empleados) == 1:
        emp = empleados[0]
        empresa = db.query(Company).filter(Company.id == emp.company_id).first()
        datos.update({
            "employee_id": emp.id,
            "company_id": emp.company_id,
            "nombre": emp.nombre,
            "empresa_nombre": empresa.nombre if empresa else None,
        })
        sesion.datos_json = datos
        enviar_botones(
            telefono,
            f"¿Eres {emp.nombre}, de la empresa {empresa.nombre if empresa else 'registrada'}?",
            [("confirmar_si", "Sí"), ("confirmar_no", "No")],
        )
        sesion.paso = PASO_CONFIRMAR
    else:
        # Misma cédula en varias empresas (multi-tenant) — el usuario elige la suya
        # antes de confirmar identidad. Este paso es genérico y lo reutilizará
        # cualquier módulo futuro (cartera, servicio automovilístico) que necesite
        # identificar al empleado antes de mostrar su propio menú.
        filas = []
        for emp in empleados:
            empresa = db.query(Company).filter(Company.id == emp.company_id).first()
            filas.append((f"empresa_{emp.id}", empresa.nombre if empresa else "Empresa", emp.nombre))
        sesion.datos_json = datos
        enviar_lista(telefono, "Encontramos tu documento en varias empresas. ¿Cuál es la tuya?", "Elegir empresa", filas)
        sesion.paso = PASO_ELEGIR_EMPRESA


def _handle_elegir_empresa(db: Session, sesion: WhatsAppConversacion, telefono: str, tipo_entrada: str, valor: str) -> None:
    if tipo_entrada != "lista" or not valor.startswith("empresa_"):
        enviar_texto(telefono, "Por favor selecciona una empresa de la lista.")
        return

    try:
        emp_id = int(valor.split("_", 1)[1])
    except (IndexError, ValueError):
        enviar_texto(telefono, "Hubo un problema con tu selección, empecemos de nuevo.")
        _reset(sesion)
        return

    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    datos = sesion.datos_json or {}
    if not emp or emp.cedula != datos.get("numero_documento"):
        enviar_texto(telefono, "Hubo un problema con tu selección, empecemos de nuevo.")
        _reset(sesion)
        return

    empresa = db.query(Company).filter(Company.id == emp.company_id).first()
    datos.update({
        "employee_id": emp.id,
        "company_id": emp.company_id,
        "nombre": emp.nombre,
        "empresa_nombre": empresa.nombre if empresa else None,
    })
    sesion.datos_json = datos
    _enviar_menu(telefono, f"Listo, {emp.nombre} de {empresa.nombre if empresa else 'tu empresa'}. ¿Qué necesitas?")
    sesion.paso = PASO_MENU


def _handle_confirmar(db: Session, sesion: WhatsAppConversacion, telefono: str, tipo_entrada: str, valor: str) -> None:
    if tipo_entrada != "boton" or valor not in ("confirmar_si", "confirmar_no"):
        enviar_texto(telefono, "Por favor usa los botones Sí / No.")
        return

    if valor == "confirmar_si":
        nombre = (sesion.datos_json or {}).get("nombre", "")
        _enviar_menu(telefono, f"Gracias {nombre}. ¿Qué necesitas?")
        sesion.paso = PASO_MENU
        return

    intentos = (sesion.intentos_confirmacion or 0) + 1
    sesion.intentos_confirmacion = intentos
    if intentos >= MAX_INTENTOS_CONFIRMACION:
        enviar_texto(telefono, "Por seguridad no pudimos verificar tu identidad. Comunícate con Talento Humano de tu empresa.")
        _reset(sesion)
    else:
        enviar_texto(telefono, "Entendido, verifiquemos de nuevo tus datos.")
        _handle_inicio(db, sesion, telefono, tipo_entrada, valor)


def _handle_menu(db: Session, sesion: WhatsAppConversacion, telefono: str, tipo_entrada: str, valor: str) -> None:
    if tipo_entrada != "boton":
        _enviar_menu(telefono, "Por favor selecciona una opción del menú.")
        return

    datos = sesion.datos_json or {}
    if valor == "menu_hist_incap":
        _responder_historico_incapacidades(db, telefono, datos)
        _enviar_menu(telefono, "¿Necesitas algo más?")
    elif valor == "menu_hist_radic":
        _responder_historico_radicados(db, telefono, datos)
        _enviar_menu(telefono, "¿Necesitas algo más?")
    elif valor == "menu_soporte":
        enviar_texto(telefono, "Escribe el número de radicado del soporte que necesitas.")
        sesion.paso = PASO_SOPORTE_RADICADO
    else:
        _enviar_menu(telefono, "Por favor selecciona una opción del menú.")


def _handle_soporte_radicado(db: Session, sesion: WhatsAppConversacion, telefono: str, tipo_entrada: str, valor: str) -> None:
    if tipo_entrada != "texto" or not valor.strip():
        enviar_texto(telefono, "Escribe el número de radicado.")
        return

    serial = valor.strip().upper()
    datos = sesion.datos_json or {}
    _responder_soporte(db, telefono, datos.get("employee_id"), serial)
    _enviar_menu(telefono, "¿Necesitas algo más?")
    sesion.paso = PASO_MENU


HANDLERS = {
    PASO_INICIO: _handle_inicio,
    PASO_TIPO_DOC: _handle_tipo_doc,
    PASO_NUM_DOC: _handle_num_doc,
    PASO_ELEGIR_EMPRESA: _handle_elegir_empresa,
    PASO_CONFIRMAR: _handle_confirmar,
    PASO_MENU: _handle_menu,
    PASO_SOPORTE_RADICADO: _handle_soporte_radicado,
}


# ═══════════════════════════════════════════════════════════════════════
# ENTRADA PRINCIPAL — llamada desde el webhook (en background)
# ═══════════════════════════════════════════════════════════════════════

def procesar_mensaje_entrante(db: Session, telefono: str, message_id: str, mensaje_raw: dict) -> None:
    """
    Idempotente contra reintentos del webhook de Meta (compara `message_id`
    contra el último procesado en la sesión) y fail-safe: cualquier excepción
    durante el manejo del paso se atrapa, se avisa al usuario y se reinicia
    la sesión, sin tumbar el webhook.
    """
    sesion = _obtener_o_crear_sesion(db, telefono)

    if sesion.ultimo_message_id and sesion.ultimo_message_id == message_id:
        return  # reintento de Meta para un mensaje ya procesado

    ahora = get_utc_now()
    if sesion.updated_at and sesion.paso != PASO_INICIO and (ahora - sesion.updated_at) > SESSION_TIMEOUT:
        _reset(sesion)

    marcar_leido_y_escribiendo(message_id)
    tipo_entrada, valor = extraer_entrada(mensaje_raw)

    handler = HANDLERS.get(sesion.paso, _handle_inicio)
    try:
        handler(db, sesion, telefono, tipo_entrada, valor)
    except Exception as e:
        logger.error(f"Error procesando paso '{sesion.paso}' de WhatsApp bot para {telefono}: {e}")
        enviar_texto(telefono, "Tuvimos un problema procesando tu mensaje. Por favor intenta de nuevo en unos minutos.")
        _reset(sesion)

    sesion.ultimo_message_id = message_id
    db.add(sesion)
    db.commit()
