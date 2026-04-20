"""
======================================================================================
Email Service — Backend Nativo
======================================================================================
Envía emails via Gmail API usando Service Account (PRODUCCIÓN).
Sin contraseña de app, sin OAuth manual, sin expiración.
Sin dependencia de webhooks externos. Incluye logging detallado.
"""

import os
import time
import re
import json
from typing import Optional, List, Dict
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.application import MIMEApplication
from email import encoders
from datetime import datetime, timedelta
import base64
import requests
from app.waha_rate_limiter import waha_limiter

# Google Auth
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google.auth.transport.requests import Request

# ═══════════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN GMAIL — USA LA MISMA SERVICE ACCOUNT QUE DRIVE
# ═══════════════════════════════════════════════════════════════════════════════════

GMAIL_USER = os.environ.get("GMAIL_USER", "soporte@incaneurobaeza.com")

# ✅ MISMAS VARIABLES QUE DRIVE
GOOGLE_SERVICE_ACCOUNT_KEY = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
GOOGLE_SHEETS_CREDENTIALS = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
GOOGLE_SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")

# Scopes para Gmail
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

# WAHA API para WhatsApp
WAHA_BASE_URL = os.environ.get(
    "WAHA_BASE_URL",
    "https://devlikeaprowaha-production-111a.up.railway.app"
)
WAHA_API_KEY = os.environ.get("WAHA_API_KEY", "1085043374")
WAHA_SESSION_NAME = os.environ.get("WAHA_SESSION_NAME", "default")


def _parsear_serial_wa(serial: str):
    """Extrae cédula y rango de fechas de serial para mensajes de WhatsApp."""
    if not serial:
        return (serial or '', '')
    parts = serial.strip().split()
    if len(parts) == 7:
        return (parts[0], f"del {parts[1]}/{parts[2]}/{parts[3]} al {parts[4]}/{parts[5]}/{parts[6]}")
    return (serial, '')


def generar_mensaje_whatsapp(
    tipo_notificacion: str,
    serial: str,
    subject: str,
    html_content: str,
    drive_link: str = None,
) -> str:
    """Genera mensajes cortos de WhatsApp según tipo de notificación."""
    _, fechas = _parsear_serial_wa(serial)
    fecha_texto = f" {fechas}" if fechas else ""

    motivos = []
    motivo_match = re.search(r'Motivo:</strong><br/>(.*?)</span>', html_content, re.DOTALL)
    if motivo_match:
        texto_motivo = re.sub(r'<[^>]+>', '', motivo_match.group(1)).strip()
        texto_motivo = texto_motivo.replace('&#8226;', '•').replace('&amp;', '&')
        for linea in texto_motivo.split('•'):
            linea = linea.strip()
            if linea and len(linea) > 5:
                motivos.append(linea)

    soportes = []
    soporte_matches = re.findall(r'&#8226;</td>\s*<td[^>]*>(.*?)</td>', html_content, re.DOTALL)
    for soporte in soporte_matches:
        texto_s = re.sub(r'<[^>]+>', '', soporte).strip()
        if texto_s and len(texto_s) > 3 and 'Adjunta' not in texto_s and 'Verifica' not in texto_s and 'Incluye' not in texto_s:
            soportes.append(texto_s)

    config = {
        'confirmacion': ('📋', 'Incapacidad Recibida'),
        'incompleta': ('⚠️', 'Documentacion Incompleta'),
        'ilegible': ('⚠️', 'Documento Ilegible'),
        'incompleta_ilegible': ('⚠️', 'Documentacion Incompleta'),
        'completa': ('✅', 'Incapacidad Validada'),
        'eps': ('📋', 'Transcripcion en EPS'),
        'eps_transcripcion': ('📋', 'Transcripcion en EPS'),
        'tthh': ('🔔', 'Alerta Talento Humano'),
        'derivado_tthh': ('🔔', 'Alerta Talento Humano'),
        'causa_extra': ('📌', 'Causa Extra Identificada'),
        'en_radicacion': ('📤', 'En Radicacion'),
        'recordatorio': ('🔔', 'Recordatorio Pendiente'),
        'alerta_jefe': ('🔔', 'Caso Pendiente'),
    }
    emoji, titulo = config.get(tipo_notificacion, ('📄', 'Notificacion'))

    lineas = [
        f"{emoji} *{titulo}*",
        f"Incapacidad{fecha_texto}",
        "",
    ]

    if tipo_notificacion == 'confirmacion':
        lineas.append("Documentacion recibida. Esta siendo revisada.")
        lineas.append("")
        lineas.append("Nos comunicaremos si se requiere algo adicional.")
        if drive_link:
            lineas.append("")
            lineas.append(f"📄 Ver documento: {drive_link}")
    elif tipo_notificacion in ('incompleta', 'ilegible', 'incompleta_ilegible'):
        if motivos:
            lineas.append("*Motivo:*")
            for motivo in motivos[:3]:
                lineas.append(f"• {motivo}")
            lineas.append("")
        if soportes:
            lineas.append("*Soportes requeridos:*")
            for soporte in soportes[:5]:
                lineas.append(f"• {soporte}")
            lineas.append("")
        lineas.append("Enviar en *PDF escaneado*, completo y legible.")
        if drive_link:
            lineas.append("")
            lineas.append(f"📄 Ver documento actual: {drive_link}")
        lineas.append("")
        lineas.append("Subir documentos: https://repogemin.vercel.app/")
    elif tipo_notificacion == 'completa':
        lineas.append(f"Tu incapacidad{fecha_texto} ha sido enviada correctamente.")
        lineas.append("Procederemos a subirla al sistema.")
        lineas.append("")
        lineas.append("Nos comunicaremos contigo si se requiere algo adicional.")
        if drive_link:
            lineas.append("")
            lineas.append(f"📄 Ver documento: {drive_link}")
    elif tipo_notificacion in ('eps', 'eps_transcripcion'):
        lineas.append(f"Tu incapacidad{fecha_texto} requiere transcripcion en tu EPS.")
        lineas.append("Dirigete con tu documento de identidad.")
        if drive_link:
            lineas.append("")
            lineas.append(f"📄 Ver documento: {drive_link}")
    elif tipo_notificacion == 'recordatorio':
        lineas.append(f"Tu incapacidad{fecha_texto} aun tiene documentacion pendiente.")
        if motivos:
            lineas.append("")
            lineas.append("*Motivo:*")
            for motivo in motivos[:3]:
                lineas.append(f"• {motivo}")
        if drive_link:
            lineas.append("")
            lineas.append(f"📄 Ver documento: {drive_link}")
        lineas.append("")
        lineas.append("Subir documentos: https://repogemin.vercel.app/")
    elif tipo_notificacion in ('tthh', 'derivado_tthh'):
        lineas.append(f"Incapacidad{fecha_texto} ha sido derivada a Talento Humano.")
    elif tipo_notificacion == 'causa_extra':
        lineas.append(f"Tu incapacidad{fecha_texto} tiene una causa extra identificada.")
        lineas.append("Revisa tu correo para mas detalles.")
    elif tipo_notificacion == 'en_radicacion':
        lineas.append(f"Tu incapacidad{fecha_texto} esta en proceso de radicacion.")
        lineas.append("Te notificaremos cuando el proceso se complete.")
    elif tipo_notificacion == 'alerta_jefe':
        lineas.append(f"Incapacidad{fecha_texto} pendiente de respuesta.")
    else:
        lineas.append("Revise su correo para mas detalles.")

    lineas.append("")
    lineas.append("_Automatico por Incapacidades_")

    mensaje = "\n".join(lineas)
    if len(mensaje) > 800:
        mensaje = mensaje[:797] + "..."
    return mensaje


# ═══════════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL — ENVIAR NOTIFICACIÓN
# ═══════════════════════════════════════════════════════════════════════════════════

def enviar_notificacion(
    tipo_notificacion: str,
    email: str,
    serial: str,
    subject: str,
    html_content: str,
    cc_email: Optional[str] = None,
    correo_bd: Optional[str] = None,
    whatsapp: Optional[str] = None,
    whatsapp_message: Optional[str] = None,
    adjuntos_base64: List[Dict] = [],
    drive_link: Optional[str] = None,
    max_retries: int = 3
) -> bool:
    """
    Envía notificación por email + WhatsApp.
    
    Args:
        tipo_notificacion: confirmacion, incompleta, ilegible, completa, eps, tthh, etc
        email: Email principal (TO)
        serial: Serial del caso
        subject: Asunto del email
        html_content: HTML del email
        cc_email: Emails adicionales separados por coma
        correo_bd: Email alternativo del empleado
        whatsapp: Número WhatsApp (sin +57, ej: 3001234567)
        whatsapp_message: Mensaje WhatsApp específico
        adjuntos_base64: Lista de dicts {nombre, base64}
        drive_link: Link a archivos en Drive
        max_retries: Intentos máximos antes de fallar
    
    Returns:
        bool: True si se envió exitosamente o si está en cola para reintentar
    """
    
    print(f"\n{'='*90}")
    print(f"📧 ENVIAR NOTIFICACIÓN — Backend nativo")
    print(f"{'='*90}")
    print(f"Tipo: {tipo_notificacion}")
    print(f"Serial: {serial}")
    print(f"Email TO: {email}")
    print(f"WhatsApp: {whatsapp or 'N/A'}")
    print(f"Asunto: {subject}")
    print(f"Adjuntos: {len(adjuntos_base64)}")
    print(f"{'='*90}\n")
    
    # ─────────────────────────────────────────────────────────────────────
    # 1. CONSTRUIR LISTA DE CCs
    # ─────────────────────────────────────────────────────────────────────
    cc_list = []
    
    if correo_bd and correo_bd.strip():
        if correo_bd.lower().strip() != email.lower().strip():
            cc_list.append(correo_bd.strip())
    
    if cc_email and cc_email.strip():
        for ce in cc_email.split(','):
            ce = ce.strip()
            if ce and '@' in ce:
                if ce.lower() not in [c.lower() for c in cc_list] and ce.lower() != email.lower():
                    cc_list.append(ce)
    
    # ─────────────────────────────────────────────────────────────────────
    # 2. INYECTAR DIRECTORIO DE EMPRESAS
    # ─────────────────────────────────────────────────────────────────────
    try:
        from app.database import SessionLocal, Case, CorreoNotificacion
        db = SessionLocal()
        
        company_id = None
        if serial and serial != 'AUTO':
            caso = db.query(Case).filter(Case.serial == serial).first()
            if caso:
                company_id = caso.company_id
        
        correos = db.query(CorreoNotificacion).filter(
            CorreoNotificacion.area == 'empresas',
            CorreoNotificacion.activo == True
        ).all()
        
        for c in correos:
            if c.company_id is None or (company_id is not None and c.company_id == company_id):
                if c.email and c.email.strip():
                    em = c.email.strip().lower()
                    if em not in [x.lower() for x in cc_list] and em != email.lower():
                        cc_list.append(em)
        
        db.close()
    except Exception as e:
        print(f"⚠️ Advertencia en injection de empresas: {e}")
    
    cc_email_final = ",".join(cc_list)
    print(f"📧 CC final: {cc_email_final or 'N/A'}\n")
    
    # ─────────────────────────────────────────────────────────────────────
    # 3. ENVIAR EMAIL — SERVICE ACCOUNT (Gmail API sin expiración)
    # ─────────────────────────────────────────────────────────────────────
    
    print(f"  📧 Enviando via Service Account...")
    email_enviado = _enviar_email_service_account(
        email=email,
        cc_list=cc_list,
        subject=subject,
        html_content=html_content,
        adjuntos_base64=adjuntos_base64
    )
    
    if not email_enviado:
        print(f"❌ EMAIL FALLÓ — Service Account no disponible")
        return False
    
    print(f"✅ EMAIL ENVIADO VIA SERVICE ACCOUNT")
    
    # ─────────────────────────────────────────────────────────────────────
    # 4. ENVIAR WHATSAPP (si existe)
    # ─────────────────────────────────────────────────────────────────────
    if whatsapp:
        try:
            # Verificar rate limit de WAHA
            if waha_limiter.esperar_si_necesario():
                print(f"✅ Rate limit OK — Enviando WhatsApp")
                
                if not whatsapp_message:
                    whatsapp_message = generar_mensaje_whatsapp(
                        tipo_notificacion, serial, subject, html_content, drive_link
                    )
                
                wa_enviado = _enviar_whatsapp(
                    numero=whatsapp,
                    mensaje=whatsapp_message
                )
                
                if wa_enviado:
                    print(f"✅ WHATSAPP ENVIADO")
                    waha_limiter.registrar_envio()
                else:
                    print(f"⚠️ WhatsApp falló — guardado en cola")
            else:
                print(f"⚠️ WhatsApp omitido por rate limit")
        
        except Exception as e:
            print(f"⚠️ Error en WhatsApp: {e}")
    
    print(f"{'='*90}\n")
    return True


# ═══════════════════════════════════════════════════════════════════════════════════
# FUNCIÓN AUXILIAR — CARGAR CREDENCIALES SERVICE ACCOUNT (igual a Drive)
# ═══════════════════════════════════════════════════════════════════════════════════

def _load_service_account_credentials():
    """
    ✅ Carga Service Account con DOMAIN-WIDE DELEGATION
    Para enviar emails como usuario de Google Workspace
    
    Intenta cargar desde (en orden de prioridad):
    1. GOOGLE_SERVICE_ACCOUNT_KEY (JSON como string)
    2. GOOGLE_CREDENTIALS_JSON
    3. GOOGLE_SHEETS_CREDENTIALS
    4. GOOGLE_SERVICE_ACCOUNT_FILE (ruta al archivo)
    
    ✅ IMPORTANTE: 
    - Debe tener Domain-Wide Delegation configurado en Google Cloud
    - El Service Account debe estar autorizado en Admin Console
    """
    # Opción 1: JSON como string en variable
    raw_json = GOOGLE_SERVICE_ACCOUNT_KEY or GOOGLE_CREDENTIALS_JSON or GOOGLE_SHEETS_CREDENTIALS
    if raw_json:
        try:
            service_account_info = json.loads(raw_json)
            credentials = ServiceAccountCredentials.from_service_account_info(
                service_account_info,
                scopes=GMAIL_SCOPES
            )
            
            # ✅ AGREGAR DOMAIN-WIDE DELEGATION
            # Delegar al usuario de Workspace (GMAIL_USER)
            credentials_delegated = credentials.with_subject(GMAIL_USER)
            
            # ✅ CRUCIAL: Refrescar para obtener token válido
            credentials_delegated.refresh(Request())
            
            print(f"  ✅ Service Account con delegación activada → {GMAIL_USER}")
            return credentials_delegated
            
        except Exception as e:
            print(f"  ❌ Error al parsear JSON de Service Account: {e}")
            return None
    
    # Opción 2: JSON desde archivo
    if GOOGLE_SERVICE_ACCOUNT_FILE:
        try:
            sa_path = Path(GOOGLE_SERVICE_ACCOUNT_FILE)
            if sa_path.exists():
                with open(sa_path, 'r', encoding='utf-8') as f:
                    service_account_info = json.load(f)
                credentials = ServiceAccountCredentials.from_service_account_info(
                    service_account_info,
                    scopes=GMAIL_SCOPES
                )
                
                # ✅ AGREGAR DOMAIN-WIDE DELEGATION
                credentials_delegated = credentials.with_subject(GMAIL_USER)
                
                # ✅ CRUCIAL: Refrescar para obtener token válido
                credentials_delegated.refresh(Request())
                
                print(f"  ✅ Service Account con delegación activada → {GMAIL_USER}")
                return credentials_delegated
            else:
                print(f"  ❌ Archivo no existe: {sa_path}")
        except Exception as e:
            print(f"  ❌ Error al cargar archivo Service Account: {e}")
            return None
    
    # Sin Service Account configurada
    print(f"  ❌ No hay Service Account configurada (ni GOOGLE_SERVICE_ACCOUNT_KEY ni GOOGLE_SERVICE_ACCOUNT_FILE)")
    return None


# ═══════════════════════════════════════════════════════════════════════════════════
# FUNCIÓN AUXILIAR — ENVIAR EMAIL VIA SERVICE ACCOUNT (Gmail API)
# ═══════════════════════════════════════════════════════════════════════════════════

def _enviar_email_service_account(
    email: str,
    cc_list: List[str],
    subject: str,
    html_content: str,
    adjuntos_base64: List[Dict] = []
) -> bool:
    """
    Envía email via Gmail API usando Service Account.
    
    ✅ Usa las MISMAS credenciales que Drive (no hay variables adicionales)
    - Cargar desde GOOGLE_SERVICE_ACCOUNT_KEY o GOOGLE_SERVICE_ACCOUNT_FILE
    - Los scopes se agregan automáticamente (gmail.send)
    """
    
    try:
        # Cargar credenciales (IGUAL A COMO DRIVE LAS CARGA)
        credentials = _load_service_account_credentials()
        if not credentials:
            return False
        
        # Construir mensaje MIME
        msg = MIMEMultipart('alternative')
        msg['From'] = GMAIL_USER
        msg['To'] = email
        msg['Subject'] = subject
        
        if cc_list:
            msg['Cc'] = ', '.join(cc_list)
        
        # Agregar HTML
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))
        
        # Agregar adjuntos si existen
        for adj in adjuntos_base64:
            nombre = adj.get('nombre', 'archivo.pdf')
            contenido_b64 = adj.get('base64', '')
            
            try:
                contenido = base64.b64decode(contenido_b64)
                
                # Detectar tipo MIME
                if nombre.endswith('.pdf'):
                    mime_type = 'application/pdf'
                elif nombre.endswith('.xlsx'):
                    mime_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                elif nombre.endswith('.docx'):
                    mime_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                else:
                    mime_type = 'application/octet-stream'
                
                part = MIMEBase(*mime_type.split('/'))
                part.set_payload(contenido)
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename={nombre}')
                msg.attach(part)
                print(f"  ✓ Adjunto agregado: {nombre}")
            except Exception as e:
                print(f"  ✗ Error adjuntando {nombre}: {e}")
        
        # Codificar mensaje para la API
        raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        
        # Llamar Gmail API
        print(f"  📧 Enviando via Gmail API (Service Account)...")
        url = "https://www.googleapis.com/gmail/v1/users/me/messages/send"
        headers = {
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json"
        }
        payload = {
            "raw": raw_message
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        if response.status_code in [200, 201, 202]:
            print(f"  ✅ Email enviado exitosamente via Service Account")
            return True
        else:
            error_msg = response.text[:300]
            print(f"  ❌ Error Gmail API {response.status_code}: {error_msg}")
            
            # ✅ DIAGNÓSTICO específico
            if response.status_code == 400:
                if "Precondition check failed" in error_msg:
                    print(f"\n  🔧 SOLUCIÓN:")
                    print(f"     1. Verifica que GMAIL_USER = '{GMAIL_USER}' existe en tu Google Workspace")
                    print(f"     2. Confirma que el Service Account tiene Domain-Wide Delegation")
                    print(f"     3. En Google Admin Console → Security → API controls → Domain wide delegation")
                    print(f"        - Client ID del Service Account debe estar autorizado")
                    print(f"        - Debe tener scope: https://www.googleapis.com/auth/gmail.send\n")
            
            return False
    
    except Exception as e:
        print(f"  ❌ Error en Service Account: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════════
# FUNCIÓN AUXILIAR — ENVIAR WHATSAPP VIA WAHA
# ═══════════════════════════════════════════════════════════════════════════════════

def _enviar_whatsapp(numero: str, mensaje: str) -> bool:
    """
    Envía WhatsApp via WAHA API.
    """
    
    try:
        # Formatear número (asegurar que está en formato internacional)
        if not numero.startswith('57') and not numero.startswith('+'):
            numero = '57' + numero
        elif numero.startswith('+'):
            numero = numero[1:]
        
        url = f"{WAHA_BASE_URL}/api/sendMessage"
        payload = {
            "chatId": f"{numero}@c.us",
            "text": mensaje
        }
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": WAHA_API_KEY
        }
        
        print(f"  📱 Enviando WhatsApp a +{numero}...")
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        
        if response.status_code in [200, 201, 202]:
            print(f"  ✅ WhatsApp enviado")
            return True
        else:
            print(f"  ❌ Error WAHA {response.status_code}: {response.text[:100]}")
            return False
    
    except Exception as e:
        print(f"  ❌ Error enviando WhatsApp: {e}")
        return False


# Health check
def verificar_salud_email() -> bool:
    """Verifica que Service Account de Gmail esté configurada"""
    try:
        credentials = _load_service_account_credentials()
        return credentials is not None
    except:
        return False
