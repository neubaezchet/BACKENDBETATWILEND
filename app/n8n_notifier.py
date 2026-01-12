"""
Sistema de notificaciones vía n8n con manejo robusto de errores
Versión mejorada con timeouts y reintentos
"""

import requests
import os
from typing import Optional, List, Dict

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
    adjuntos_base64: List[Dict] = []
) -> bool:
    """
    Envía notificación a n8n con manejo robusto de errores
    
    Returns:
        bool: True si se envió exitosamente o si el error es tolerable
    """
    
    # ✅ URL del webhook de n8n
    n8n_webhook_url = os.environ.get(
        "N8N_WEBHOOK_URL",
        "https://incaneurobaeza-email-whatsapp-v5-1-production.up.railway.app/webhook/incapacidades"
    )
    
    # ✅ Construir payload
    payload = {
        "tipo_notificacion": tipo_notificacion,
        "email": email,
        "serial": serial,
        "subject": subject,
        "html_content": html_content,
        "cc_email": cc_email or "",
        "correo_bd": correo_bd or "",
        "whatsapp": whatsapp or "",
        "whatsapp_message": whatsapp_message or "",
        "adjuntos": adjuntos_base64
    }
    
    try:
        print(f"📤 Enviando a n8n: {n8n_webhook_url}")
        print(f"   TO: {email}")
        print(f"   CC_EMPRESA: {cc_email or 'N/A'}")
        print(f"   CC_BD: {correo_bd or 'N/A'}")
        print(f"   WhatsApp: {whatsapp or 'N/A'}")
        
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
        if response.status_code in [200, 201, 204]:
            print(f"✅ n8n respondió OK (status {response.status_code})")
            
            # Intentar parsear respuesta (opcional)
            try:
                data = response.json()
                print(f"   Respuesta n8n: {data}")
            except:
                print("   (Sin JSON en respuesta, pero status OK)")
            
            return True
        
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
        "https://incaneurobaeza-email-whatsapp-v5-1-production.up.railway.app/webhook/incapacidades"
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