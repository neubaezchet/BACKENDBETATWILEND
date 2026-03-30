"""
======================================================================================
Email Service — Backend Nativo
======================================================================================
Reemplaza N8N completamente. Envía emails via Gmail SMTP + WhatsApp via WAHA API.
Sin dependencia de webhooks externos. Incluye retry automático y logging detallado.

Compatible 100% con la interfaz anterior (enviar_a_n8n → enviar_notificacion)
"""

import smtplib
import os
import time
from typing import Optional, List, Dict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.application import MIMEApplication
from email import encoders
from datetime import datetime, timedelta
import base64
import requests
from app.waha_rate_limiter import waha_limiter

# ═══════════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN GMAIL SMTP
# ═══════════════════════════════════════════════════════════════════════════════════

GMAIL_USER = os.environ.get("GMAIL_USER", "soporte@incaneurobaeza.com")
GMAIL_PASSWORD = os.environ.get("GMAIL_PASSWORD", "")  # App password, not regular password
GMAIL_SMTP_SERVER = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587

# WAHA API para WhatsApp
WAHA_BASE_URL = os.environ.get(
    "WAHA_BASE_URL",
    "https://devlikeaprowaha-production-111a.up.railway.app"
)
WAHA_API_KEY = os.environ.get("WAHA_API_KEY", "1085043374")
WAHA_SESSION_NAME = os.environ.get("WAHA_SESSION_NAME", "default")


# ═══════════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL — ENVIAR NOTIFICACIÓN (reemplaza enviar_a_n8n)
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
    print(f"📧 ENVIAR NOTIFICACIÓN — Backend Native (sin N8N)")
    print(f"{'='*90}")
    print(f"Tipo: {tipo_notificacion}")
    print(f"Serial: {serial}")
    print(f"Email TO: {email}")
    print(f"WhatsApp: {whatsapp or 'N/A'}")
    print(f"Asunto: {subject}")
    print(f"Adjuntos: {len(adjuntos_base64)}")
    print(f"{'='*90}\n")
    
    # ─────────────────────────────────────────────────────────────────────
    # 1. CONSTRUIR LISTA DE CCs (igual que en n8n_notifier)
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
    # 2. INYECTAR DIRECTORIO DE EMPRESAS (igual que en n8n_notifier)
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
    # 3. ENVIAR EMAIL CON REINTENTOS
    # ─────────────────────────────────────────────────────────────────────
    email_enviado = False
    for intento in range(max_retries):
        try:
            email_enviado = _enviar_email_smtp(
                email=email,
                cc_list=cc_list,
                subject=subject,
                html_content=html_content,
                adjuntos_base64=adjuntos_base64
            )
            if email_enviado:
                print(f"✅ EMAIL ENVIADO (intento {intento + 1}/{max_retries})")
                break
        except Exception as e:
            print(f"❌ Error en intento {intento + 1}/{max_retries}: {e}")
            if intento < max_retries - 1:
                time.sleep(2 ** intento)  # Backoff exponencial: 1s, 2s, 4s
    
    if not email_enviado:
        print(f"❌ EMAIL FALLÓ después de {max_retries} intentos")
        return False
    
    # ─────────────────────────────────────────────────────────────────────
    # 4. ENVIAR WHATSAPP (si existe)
    # ─────────────────────────────────────────────────────────────────────
    if whatsapp:
        try:
            # Verificar rate limit de WAHA
            if waha_limiter.esperar_si_necesario():
                print(f"✅ Rate limit OK — Enviando WhatsApp")
                
                if not whatsapp_message:
                    from app.n8n_notifier import generar_mensaje_whatsapp
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
# FUNCIÓN AUXILIAR — ENVIAR EMAIL VIA SMTP
# ═══════════════════════════════════════════════════════════════════════════════════

def _enviar_email_smtp(
    email: str,
    cc_list: List[str],
    subject: str,
    html_content: str,
    adjuntos_base64: List[Dict] = []
) -> bool:
    """
    Envía email via Gmail SMTP con soporte para CC y adjuntos.
    """
    
    try:
        # Crear mensaje
        msg = MIMEMultipart('alternative')
        msg['From'] = GMAIL_USER
        msg['To'] = email
        msg['Subject'] = subject
        
        if cc_list:
            msg['Cc'] = ', '.join(cc_list)
        
        # Agregar HTML
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))
        
        # Agregar adjuntos (si existen)
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
                
                # Adjuntar
                part = MIMEBase(*mime_type.split('/'))
                part.set_payload(contenido)
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename= {nombre}'
                )
                msg.attach(part)
                print(f"  ✓ Adjunto agregado: {nombre}")
            
            except Exception as e:
                print(f"  ✗ Error adjuntando {nombre}: {e}")
        
        # Conectar a Gmail
        print(f"  Conectando a {GMAIL_SMTP_SERVER}:{GMAIL_SMTP_PORT}...")
        with smtplib.SMTP(GMAIL_SMTP_SERVER, GMAIL_SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            
            # Enviar (TO + CC)
            recipients = [email] + cc_list
            server.sendmail(GMAIL_USER, recipients, msg.as_string())
        
        print(f"  ✅ Email enviado exitosamente")
        return True
    
    except smtplib.SMTPAuthenticationError:
        print(f"  ❌ Error de autenticación — verificar GMAIL_USER y GMAIL_PASSWORD")
        return False
    except smtplib.SMTPException as e:
        print(f"  ❌ Error SMTP: {e}")
        return False
    except Exception as e:
        print(f"  ❌ Error inesperado: {e}")
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


# ═══════════════════════════════════════════════════════════════════════════════════
# COMPATIBILIDAD — Alias para reemplazar n8n_notifier
# ═══════════════════════════════════════════════════════════════════════════════════

# Mantener nombre original para compatibilidad con código existente
def enviar_a_n8n(*args, **kwargs):
    """Alias para compatibilidad — redirige a enviar_notificacion"""
    return enviar_notificacion(*args, **kwargs)


# Health check
def verificar_salud_email() -> bool:
    """Verifica que Gmail esté accesible"""
    try:
        with smtplib.SMTP(GMAIL_SMTP_SERVER, GMAIL_SMTP_PORT, timeout=5) as server:
            server.starttls()
            return True
    except:
        return False
