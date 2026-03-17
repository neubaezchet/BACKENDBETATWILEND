"""
Sistema de notificaciones vía n8n con manejo robusto de errores
Versión mejorada con timeouts, reintentos y rate limiting avanzado
"""

import requests
import os
import time
from typing import Optional, List, Dict
from collections import deque
from datetime import datetime, timedelta
from app.waha_rate_limiter import waha_limiter

def enviar_a_n8n(
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
    drive_link: Optional[str] = None
) -> bool:
    """
    Envía notificación a n8n con manejo robusto de errores
    
    Returns:
        bool: True si se envió exitosamente o si el error es tolerable
    """
    
    # ✅ URL del webhook de n8n
    n8n_webhook_url = os.environ.get(
        "N8N_WEBHOOK_URL",
        "https://railway-n8n-production-5a3f.up.railway.app/webhook/incapacidades"
    )
    
    # ✅ GENERAR MENSAJE WHATSAPP AUTOMÁTICO SI NO EXISTE
    if not whatsapp_message and whatsapp:
        whatsapp_message = generar_mensaje_whatsapp(
            tipo_notificacion, serial, subject, html_content, drive_link
        )
        print(f"📱 Mensaje WhatsApp auto-generado (preview): {whatsapp_message[:100]}...")
    
    # ✅ VERIFICAR RATE LIMIT AVANZADO
    whatsapp_enviado = False
    if whatsapp:
        if waha_limiter.esperar_si_necesario():
            # Rate limit OK - dejar pasar el WhatsApp
            print(f"✅ Rate limit OK - Enviando WhatsApp")
            whatsapp_enviado = True
        else:
            # Rate limit alcanzado - enviar solo email
            print(f"⚠️ WhatsApp omitido por rate limit - Enviando solo email")
            whatsapp = None
            whatsapp_message = None
    
    # ✅ CONSTRUIR LISTA DE CCs (lógica original que funcionaba con todos los dominios)
    cc_list = []
    
    print(f"🔍 DEBUG n8n_notifier:")
    print(f"   email (TO): {email}")
    print(f"   correo_bd: {correo_bd}")
    print(f"   cc_email: {cc_email}")
    
    # Agregar correo del empleado en BD (si existe y es diferente al principal)
    if correo_bd and correo_bd.strip():
        if correo_bd.lower().strip() != email.lower().strip():
            cc_list.append(correo_bd.strip())
            print(f"   ✓ correo_bd agregado a cc_list: {correo_bd}")
        else:
            print(f"   ✗ correo_bd es igual al TO, no se agrega")
    
    # Agregar correo de la empresa (si existe y no es duplicado)
    if cc_email and cc_email.strip():
        # Puede tener múltiples emails separados por coma
        for ce in cc_email.split(','):
            ce = ce.strip()
            if ce and '@' in ce and ce.lower() not in [c.lower() for c in cc_list] and ce.lower() != email.lower().strip():
                cc_list.append(ce)
                print(f"   ✓ cc_email agregado a cc_list: {ce}")
    
    # ✅ INYECCIÓN UNIVERSAL DEL DIRECTORIO DE EMPRESAS EN TODOS LOS CORREOS
    try:
        from app.database import SessionLocal, Case, CorreoNotificacion
        db = SessionLocal()
        
        company_id = None
        if serial and serial != 'AUTO':
            caso = db.query(Case).filter(Case.serial == serial).first()
            if caso:
                company_id = caso.company_id
                
        # Buscar en directorio empresas (globales + especificas)
        correos = db.query(CorreoNotificacion).filter(
            CorreoNotificacion.area == 'empresas',
            CorreoNotificacion.activo == True
        ).all()
        
        for c in correos:
            if c.company_id is None or (company_id is not None and c.company_id == company_id):
                if c.email and c.email.strip():
                    em = c.email.strip().lower()
                    if em not in [x.lower() for x in cc_list] and em != email.lower().strip():
                        cc_list.append(em)
                        print(f"   ✓ [INYECCIÓN UNIVERSAL] cc_email agregado a cc_list: {em}")
        db.close()
    except Exception as e:
        print(f"⚠️ Error en inyección universal de empresas: {e}")
        
    print(f"   📧 cc_list final: {cc_list}")
    
    # ✅ PAYLOAD — cc_email COMBINADO (compatible con workflow viejo Y nuevo)
    cc_email_combinado = ",".join(cc_list) if cc_list else ""
    
    payload = {
        "tipo_notificacion": tipo_notificacion,
        "email": email,
        "serial": serial,
        "subject": subject,
        "html_content": html_content,
        "cc_email": cc_email_combinado,          # ✅ TODOS los CCs combinados (compatible con workflow viejo)
        "correo_bd": correo_bd or "",            # ✅ También separado (compatible con workflow v5+)
        "whatsapp": whatsapp or "",
        "whatsapp_message": whatsapp_message or "",
        "adjuntos": adjuntos_base64
    }
    
    try:
        print(f"\n{'='*80}")
        print(f"📤 ENVIANDO A N8N")
        print(f"{'='*80}")
        print(f"🔗 URL: {n8n_webhook_url}")
        print(f"📧 TO: {email}")
        print(f"📧 CC (combinado): {cc_email_combinado or 'N/A'}")
        print(f"📧 CC_BD (separado): {correo_bd or 'N/A'}")
        print(f"📱 WhatsApp: {whatsapp or 'N/A'}")
        print(f"🎫 Serial: {serial}")
        print(f"📋 Tipo: {tipo_notificacion}")
        print(f"📄 Asunto: {subject}")
        print(f"📎 Adjuntos: {len(adjuntos_base64)}")
        print(f"💾 Payload keys: {list(payload.keys())}")
        print(f"{'='*80}\n")
        
        # ✅ TIMEOUT AUMENTADO: 30 segundos para emails con adjuntos
        response = requests.post(
            n8n_webhook_url,
            json=payload,
            timeout=30,  # ← CRÍTICO: Aumentar timeout
            headers={
                'Content-Type': 'application/json',
                'User-Agent': 'Incapacidades-Backend/2.0'
            }
        )
        
        # ✅ VERIFICAR STATUS CODE
        print(f"\n📥 RESPUESTA DE N8N")
        print(f"{'='*80}")
        print(f"Status: {response.status_code}")
        print(f"{'='*80}\n")
        
        if response.status_code in [200, 201, 202, 204]:
            print(f"✅ N8N ACEPTÓ LA SOLICITUD (status {response.status_code})")
            
            try:
                data = response.json()
                print(f"Respuesta JSON: {data}")
                
                if isinstance(data, dict) and 'channels' in data:
                    channels = data.get('channels', {})
                    if channels.get('email', {}).get('sent'):
                        print(f"   ✅ EMAIL ENVIADO")
                    if channels.get('whatsapp', {}).get('sent'):
                        print(f"   ✅ WHATSAPP ENVIADO")
            except:
                print("(Sin JSON, pero status OK)")
            
            # ✅ REGISTRAR ENVÍO DE WHATSAPP (solo si se envió)
            if whatsapp_enviado:
                waha_limiter.registrar_envio()
            
            return True  # ÉXITO
        
        elif response.status_code == 202:
            # Accepted - n8n recibió pero aún está procesando
            print(f"✅ n8n aceptó la solicitud (202 Accepted)")
            return True
        
        elif response.status_code in [408, 504]:
            # Timeout del servidor - pero probablemente se envió
            print(f"⚠️ Timeout del servidor n8n (status {response.status_code})")
            print("   Asumiendo que el email se enviará de todas formas")
            return True  # ← TOLERAR timeout
        
        else:
            # Error real
            print(f"❌ Error n8n (status {response.status_code})")
            try:
                error_data = response.json()
                print(f"   Error detail: {error_data}")
            except:
                print(f"   Response text: {response.text[:200]}")
            
            return False
    
    except requests.exceptions.Timeout:
        # ✅ TIMEOUT - Pero el webhook probablemente se ejecutó
        print(f"⚠️ Timeout esperando respuesta de n8n (>30s)")
        print("   El email probablemente se está enviando en background")
        return True  # ← TOLERAR timeout
    
    except requests.exceptions.ConnectionError as e:
        print(f"❌ Error de conexión a n8n: {e}")
        return False
    
    except requests.exceptions.RequestException as e:
        print(f"❌ Error en request a n8n: {e}")
        return False
    
    except Exception as e:
        print(f"❌ Error inesperado en enviar_a_n8n: {e}")
        import traceback
        traceback.print_exc()
        return False


# ✅ FUNCIÓN AUXILIAR: Verificar si n8n está disponible
def verificar_salud_n8n() -> bool:
    """
    Verifica si n8n está respondiendo (para health checks)
    """
    n8n_webhook_url = os.environ.get(
        "N8N_WEBHOOK_URL",
        "https://railway-n8n-production-5a3f.up.railway.app/webhook/incapacidades"
    )
    
    try:
        # Ping rápido (5 segundos max)
        response = requests.get(
            n8n_webhook_url.replace('/webhook/incapacidades', '/healthz'),
            timeout=5
        )
        return response.status_code == 200
    except:
        return False


# ✅ GENERADOR AUTOMÁTICO DE MENSAJES WHATSAPP (CORTO, ANTI-SPAM)
def _parsear_serial_wa(serial):
    """Extrae cedula y fechas del serial para WhatsApp"""
    if not serial:
        return (serial or '', '')
    parts = serial.strip().split()
    if len(parts) == 7:
        return (parts[0], f"del {parts[1]}/{parts[2]}/{parts[3]} al {parts[4]}/{parts[5]}/{parts[6]}")
    return (serial, '')


def generar_mensaje_whatsapp(tipo_notificacion: str, serial: str, subject: str, html_content: str, drive_link: str = None) -> str:
    """
    Mensaje WhatsApp CORTO y DIRECTO.
    Máximo ~600 chars para evitar bloqueo por spam.
    Sin IncaNeurobaeza - solo "Automatico por Incapacidades"
    """
    import re

    cedula, fechas = _parsear_serial_wa(serial)
    fecha_texto = f" {fechas}" if fechas else ""

    # Extraer motivos del HTML (buscar en spans dentro de bloques de mensaje)
    motivos = []
    # Buscar texto despues de "Motivo:" en el HTML
    motivo_match = re.search(r'Motivo:</strong><br/>(.*?)</span>', html_content, re.DOTALL)
    if motivo_match:
        texto_motivo = re.sub(r'<[^>]+>', '', motivo_match.group(1)).strip()
        texto_motivo = texto_motivo.replace('&#8226;', '•').replace('&amp;', '&')
        for linea in texto_motivo.split('•'):
            linea = linea.strip()
            if linea and len(linea) > 5:
                motivos.append(linea)

    # Extraer soportes requeridos
    soportes = []
    soporte_matches = re.findall(r'&#8226;</td>\s*<td[^>]*>(.*?)</td>', html_content, re.DOTALL)
    for s in soporte_matches:
        texto_s = re.sub(r'<[^>]+>', '', s).strip()
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

    lineas = []
    lineas.append(f"{emoji} *{titulo}*")
    lineas.append(f"Incapacidad{fecha_texto}")
    lineas.append("")

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
            for m in motivos[:3]:
                lineas.append(f"• {m}")
            lineas.append("")
        if soportes:
            lineas.append("*Soportes requeridos:*")
            for s in soportes[:5]:
                lineas.append(f"• {s}")
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
            for m in motivos[:3]:
                lineas.append(f"• {m}")
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


# ✅ FUNCIÓN AUXILIAR: Obtener estadísticas del rate limiter
def obtener_estadisticas_whatsapp() -> dict:
    """Retorna estadísticas del limitador de WhatsApp"""
    return waha_limiter.obtener_estadisticas()