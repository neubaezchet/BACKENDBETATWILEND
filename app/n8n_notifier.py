"""
Notificador n8n - Reemplaza Brevo
IncaBaeza - 2024
VERSIÓN MEJORADA: Manejo robusto de timeouts y respuestas lentas
"""

import os
import requests
from typing import List, Optional

N8N_WEBHOOK_URL = os.environ.get(
    "N8N_WEBHOOK_URL", 
    "https://n8n-incaneurobaeza.onrender.com/webhook/incapacidades"
)

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
    adjuntos_base64: Optional[List[dict]] = None
) -> bool:
    """
    Envía notificación a n8n para procesamiento de emails
    
    Args:
        tipo_notificacion: 'confirmacion', 'incompleta', 'ilegible', 'completa', 
                          'eps', 'tthh', 'extra', 'recordatorio', 'alerta_jefe'
        email: Email del destinatario principal (del formulario)
        serial: Serial del caso
        subject: Asunto del email
        html_content: HTML del email generado
        cc_email: Email de copia de la empresa (Hoja 2)
        correo_bd: Email del empleado en BD (Hoja 1)
        whatsapp: Número de WhatsApp
        whatsapp_message: Mensaje personalizado para WhatsApp (opcional)
        adjuntos_base64: Lista de adjuntos en base64
    
    Returns:
        bool: True si se envió correctamente O si el error es tolerable (timeout)
    """
    
    # ✅ CONSTRUIR LISTA DE CCs
    cc_list = []
    
    print(f"📧 DEBUG n8n_notifier:")
    print(f"   email (TO): {email}")
    print(f"   correo_bd: {correo_bd}")
    print(f"   cc_email: {cc_email}")
    
    # Agregar correo del empleado en BD (si existe y es diferente al principal)
    if correo_bd:
        print(f"   ✓ correo_bd existe: {correo_bd}")
        if correo_bd.strip():
            print(f"   ✓ correo_bd no está vacío")
            if correo_bd.lower() != email.lower():
                cc_list.append(correo_bd.strip())
                print(f"   ✓ correo_bd agregado a cc_list")
            else:
                print(f"   ✗ correo_bd es igual al TO, no se agrega")
        else:
            print(f"   ✗ correo_bd está vacío después de strip()")
    else:
        print(f"   ✗ correo_bd es None o False")
    
    # Agregar correo de la empresa (si existe)
    if cc_email:
        print(f"   ✓ cc_email existe: {cc_email}")
        if cc_email.strip():
            print(f"   ✓ cc_email no está vacío")
            # Evitar duplicados
            if cc_email.strip().lower() not in [c.lower() for c in cc_list]:
                cc_list.append(cc_email.strip())
                print(f"   ✓ cc_email agregado a cc_list")
            else:
                print(f"   ✗ cc_email ya existe en cc_list")
        else:
            print(f"   ✗ cc_email está vacío después de strip()")
    else:
        print(f"   ✗ cc_email es None o False")
    
    print(f"   📧 cc_list final: {cc_list}")
    
    # ✅ PAYLOAD CORRECTO para n8n
    payload = {
        "tipo_notificacion": tipo_notificacion,
        "email": email,
        "serial": serial,
        "subject": subject,
        "html_content": html_content,
        "cc_email": ",".join(cc_list) if cc_list else "",
        "whatsapp": whatsapp or "",
        "whatsapp_message": whatsapp_message or "",
        "adjuntos": adjuntos_base64 if adjuntos_base64 else []
    }
    
    try:
        print(f"📤 Enviando a n8n:")
        print(f"   📧 TO: {email}")
        print(f"   📧 CC: {', '.join(cc_list) if cc_list else 'ninguno'}")
        print(f"   📱 WhatsApp: {whatsapp or 'ninguno'}")
        print(f"   📋 Serial: {serial}")
        print(f"   📝 Subject: {subject}")
        
        # ✅ TIMEOUT AUMENTADO A 45 SEGUNDOS
        # Emails con adjuntos pueden tardar mucho
        response = requests.post(
            N8N_WEBHOOK_URL,
            json=payload,
            timeout=45,  # ← AUMENTADO de 15 a 45
            headers={
                "Content-Type": "application/json",
                "User-Agent": "IncaNeurobaeza-Backend/2.0"
            }
        )
        
        # ✅ VERIFICAR MÚLTIPLES STATUS CODES
        if response.status_code in [200, 201, 204]:
            print(f"✅ Email enviado via n8n: {serial} ({tipo_notificacion})")
            try:
                data = response.json()
                print(f"   Respuesta n8n: {data}")
            except:
                print("   (Sin JSON en respuesta, pero status OK)")
            return True
        
        elif response.status_code == 202:
            # ✅ ACCEPTED - n8n recibió pero aún procesa
            print(f"✅ n8n aceptó la solicitud (202 Accepted): {serial}")
            print("   Los emails se enviarán en background")
            return True
        
        elif response.status_code in [408, 504]:
            # ✅ TIMEOUT DEL SERVIDOR - Probablemente se envió
            print(f"⚠️ Timeout del servidor n8n (status {response.status_code}): {serial}")
            print("   Asumiendo que el email se enviará de todas formas")
            return True  # ← TOLERAR timeout del servidor
        
        else:
            # ❌ ERROR REAL
            print(f"❌ Error en n8n ({response.status_code}): {serial}")
            try:
                error_data = response.json()
                print(f"   Error detail: {error_data}")
            except:
                print(f"   Response text: {response.text[:200]}")
            return False
            
    except requests.exceptions.Timeout:
        # ✅ TIMEOUT - Pero el webhook PROBABLEMENTE se ejecutó
        print(f"⚠️ Timeout esperando respuesta de n8n (>45s): {serial}")
        print("   El email probablemente se está enviando en background")
        print("   Esto es NORMAL para emails con adjuntos pesados")
        return True  # ← TOLERAR timeout del cliente
    
    except requests.exceptions.ConnectionError as e:
        # ❌ ERROR DE CONEXIÓN - n8n no responde
        print(f"❌ Error de conexión con n8n: {N8N_WEBHOOK_URL}")
        print(f"   Error: {e}")
        return False
    
    except requests.exceptions.RequestException as e:
        # ❌ OTROS ERRORES DE REQUEST
        print(f"❌ Error en request a n8n: {serial}")
        print(f"   Error: {e}")
        return False
    
    except Exception as e:
        # ❌ ERROR INESPERADO
        print(f"❌ Error inesperado en enviar_a_n8n: {serial}")
        print(f"   Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def verificar_n8n_activo() -> bool:
    """
    Verifica si n8n está respondiendo (para health checks)
    Timeout corto para no bloquear
    """
    try:
        health_url = N8N_WEBHOOK_URL.replace("/webhook/incapacidades", "/healthz")
        response = requests.get(health_url, timeout=5)
        return response.status_code == 200
    except:
        # Si n8n no tiene endpoint /healthz, intentar el webhook con HEAD
        try:
            response = requests.head(N8N_WEBHOOK_URL, timeout=5)
            return response.status_code in [200, 405]  # 405 = Method Not Allowed es OK
        except:
            return False


def enviar_a_n8n_async(
    tipo_notificacion: str, 
    email: str, 
    serial: str, 
    subject: str,
    html_content: str, 
    **kwargs
) -> None:
    """
    Versión asíncrona (fire-and-forget) para casos no críticos
    No espera respuesta de n8n
    """
    import threading
    
    def _enviar():
        enviar_a_n8n(
            tipo_notificacion=tipo_notificacion,
            email=email,
            serial=serial,
            subject=subject,
            html_content=html_content,
            **kwargs
        )
    
    thread = threading.Thread(target=_enviar, daemon=True)
    thread.start()
    print(f"🚀 Email en cola para envío asíncrono: {serial}")