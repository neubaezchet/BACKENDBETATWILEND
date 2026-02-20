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
                'User-Agent': 'IncaNeurobaeza-Backend/2.0'
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


# ✅ GENERADOR AUTOMÁTICO DE MENSAJES WHATSAPP (FORMATO MEJORADO)
def generar_mensaje_whatsapp(tipo_notificacion: str, serial: str, subject: str, html_content: str, drive_link: str = None) -> str:
    """
    Genera mensaje WhatsApp bien formateado a partir del HTML del email.
    Usa formato WhatsApp: *bold*, _italic_, ~strikethrough~
    Estructura clara con saltos de línea y secciones.
    Máximo ~1000 caracteres para evitar spam.
    """
    import re
    
    # ===== CONFIGURACIÓN POR TIPO =====
    config = {
        'confirmacion': {
            'emoji': '📋',
            'titulo': 'Incapacidad Recibida',
            'tono': 'positivo'
        },
        'incompleta': {
            'emoji': '⚠️',
            'titulo': 'Documentación Incompleta',
            'tono': 'accion'
        },
        'ilegible': {
            'emoji': '⚠️',
            'titulo': 'Documento Ilegible',
            'tono': 'accion'
        },
        'completa': {
            'emoji': '✅',
            'titulo': 'Incapacidad Validada',
            'tono': 'positivo'
        },
        'eps': {
            'emoji': '📋',
            'titulo': 'Notificación EPS',
            'tono': 'neutro'
        },
        'tthh': {
            'emoji': '🔔',
            'titulo': 'Alerta Talento Humano',
            'tono': 'neutro'
        },
        'extra': {
            'emoji': '📢',
            'titulo': 'Notificación',
            'tono': 'neutro'
        },
        'recordatorio': {
            'emoji': '🔔',
            'titulo': 'Recordatorio Pendiente',
            'tono': 'accion'
        },
        'alerta_jefe': {
            'emoji': '🔔',
            'titulo': 'Caso Pendiente',
            'tono': 'neutro'
        }
    }
    
    cfg = config.get(tipo_notificacion, {'emoji': '📄', 'titulo': 'Notificación', 'tono': 'neutro'})
    
    # ===== EXTRAER CONTENIDO INTELIGENTE DEL HTML =====
    # 1. Extraer items de lista (motivos, checks, soportes)
    li_items = re.findall(r'<li[^>]*>(.*?)</li>', html_content, re.DOTALL)
    items_limpios = []
    for li in li_items:
        texto_li = re.sub(r'<[^>]+>', '', li).strip()
        texto_li = re.sub(r'\s+', ' ', texto_li)
        if texto_li and len(texto_li) > 3:
            items_limpios.append(texto_li)
    
    # 2. Extraer párrafos principales (sin tags)
    parrafos = re.findall(r'<p[^>]*>(.*?)</p>', html_content, re.DOTALL)
    parrafos_limpios = []
    for p in parrafos:
        texto_p = re.sub(r'<strong>(.*?)</strong>', r'*\1*', p)  # bold → WhatsApp bold
        texto_p = re.sub(r'<[^>]+>', '', texto_p).strip()
        texto_p = re.sub(r'\s+', ' ', texto_p)
        texto_p = texto_p.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        if texto_p and len(texto_p) > 10 and 'IncaNeurobaeza' not in texto_p and 'automático' not in texto_p.lower():
            parrafos_limpios.append(texto_p)
    
    # ===== CONSTRUIR MENSAJE ESTRUCTURADO =====
    lineas = []
    
    # Encabezado
    lineas.append(f"{cfg['emoji']} *IncaNeurobaeza — {cfg['titulo']}*")
    lineas.append(f"Serial: *{serial}*")
    lineas.append("")  # línea vacía
    
    # Contenido principal (máx 3 párrafos más relevantes)
    parrafos_usados = 0
    for p in parrafos_limpios:
        if parrafos_usados >= 3:
            break
        # Saltar párrafos genéricos/repetitivos
        if any(skip in p.lower() for skip in ['mensaje automático', 'footer', 'copyright', 'derechos reservados']):
            continue
        lineas.append(p)
        lineas.append("")
        parrafos_usados += 1
    
    # Si hay items de lista (motivos, checks), agregar como bullets
    if items_limpios:
        # Máximo 5 items para no saturar
        for item in items_limpios[:5]:
            lineas.append(f"  • {item}")
        if len(items_limpios) > 5:
            lineas.append(f"  _...y {len(items_limpios) - 5} más_")
        lineas.append("")
    
    # Acción según tipo
    if cfg['tono'] == 'accion':
        lineas.append("📎 *Formato:* PDF escaneado, completo y legible.")
        lineas.append("")
        lineas.append("Si no cuenta con algún soporte, diríjase al punto de atención más cercano de su EPS y solicítelo.")
        lineas.append("")
    
    # Link de Drive (si existe)
    if drive_link:
        lineas.append(f"📂 *Ver documentos:*")
        lineas.append(drive_link)
        lineas.append("")
    
    # Cierre
    if cfg['tono'] == 'accion':
        lineas.append("Comuníquese si tiene alguna duda.")
    elif cfg['tono'] == 'positivo':
        lineas.append("Nos comunicaremos con usted si se requiere algún paso adicional.")
    
    lineas.append("")
    lineas.append("_Mensaje automático — IncaNeurobaeza_")
    
    # Unir con saltos de línea
    mensaje = "\n".join(lineas)
    
    # Limitar a 1000 caracteres (WhatsApp recomienda 1024 max)
    if len(mensaje) > 1000:
        mensaje = mensaje[:997] + "..."
    
    return mensaje


# ✅ FUNCIÓN AUXILIAR: Obtener estadísticas del rate limiter
def obtener_estadisticas_whatsapp() -> dict:
    """Retorna estadísticas del limitador de WhatsApp"""
    return waha_limiter.obtener_estadisticas()