"""
Sistema ULTRA-ROBUSTO de Auto-Renovación de Tokens
- Renueva cada 30 min (token dura 60)
- 5 reintentos con backoff
- Alertas automáticas si falla
- NUNCA se cae
"""

import os
import json
import time
from datetime import datetime
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from apscheduler.schedulers.background import BackgroundScheduler

TOKEN_FILE = Path("/tmp/google_token.json")
CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN")

def renovar_token_drive():
    """Renovación con REINTENTOS y ALERTAS"""
    
    print(f"\n{'='*60}")
    print(f"🔄 [{datetime.now()}] Renovando token...")
    
    # Validar credenciales
    if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
        mensaje = "❌ Faltan credenciales. Revisa variables de entorno."
        print(mensaje)
        enviar_alerta_critica(mensaje)
        return False
    
    # REINTENTAR hasta 5 veces
    for intento in range(1, 6):
        try:
            print(f"   Intento {intento}/5...")
            
            # Crear credenciales
            creds = Credentials(
                token=None,
                refresh_token=REFRESH_TOKEN,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
                scopes=["https://www.googleapis.com/auth/drive.file"]
            )
            
            # Renovar
            creds.refresh(Request())
            
            # Guardar
            token_data = {
                'token': creds.token,
                'refresh_token': REFRESH_TOKEN,
                'token_uri': creds.token_uri,
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET,
                'scopes': creds.scopes,
                'expiry': creds.expiry.isoformat() if creds.expiry else None
            }
            
            TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(TOKEN_FILE, 'w') as f:
                json.dump(token_data, f)
            
            # Calcular minutos restantes
            if creds.expiry:
                minutos = (creds.expiry - datetime.utcnow()).total_seconds() / 60
                print(f"✅ Token renovado (válido {minutos:.1f} min)")
            else:
                print(f"✅ Token renovado")
            
            return True
        
        except Exception as e:
            error = str(e)
            
            # Si es invalid_grant = REFRESH_TOKEN revocado
            if 'invalid_grant' in error.lower():
                mensaje = (
                    "🚨 CRÍTICO: REFRESH_TOKEN REVOCADO\n\n"
                    "SOLUCIÓN:\n"
                    "1. Ejecuta: python regenerar_token.py\n"
                    "2. Actualiza GOOGLE_REFRESH_TOKEN en Render\n"
                    "3. Reinicia el servicio"
                )
                print(mensaje)
                enviar_alerta_critica(mensaje)
                return False
            
            # Para otros errores, reintentar
            print(f"   ⚠️ Error: {error}")
            
            if intento < 5:
                espera = 2 ** intento  # 2, 4, 8, 16, 32 segundos
                print(f"   Esperando {espera}s...")
                time.sleep(espera)
            else:
                mensaje = f"❌ Falló después de 5 intentos: {error}"
                print(mensaje)
                enviar_alerta_fallo(mensaje)
                return False
    
    return False


def enviar_alerta_critica(mensaje: str):
    """Alerta ROJA por email"""
    try:
        from app.n8n_notifier import enviar_a_n8n
        
        html = f"""
        <div style="background:#fee2e2;border:3px solid #dc2626;padding:20px;border-radius:8px;">
            <h2 style="color:#991b1b;">🚨 CRÍTICO - TOKEN DE DRIVE</h2>
            <pre style="background:white;padding:15px;border-radius:4px;">{mensaje}</pre>
            <p style="color:#7f1d1d;"><strong>ACCIÓN INMEDIATA REQUERIDA</strong></p>
        </div>
        """
        
        enviar_a_n8n(
            tipo_notificacion='extra',
            email='xoblaxbaezaospino@gmail.com',
            serial='CRITICAL',
            subject='🚨 CRÍTICO: Token Drive Revocado',
            html_content=html,
            cc_email=None,
            correo_bd=None,
            adjuntos_base64=[]
        )
    except:
        pass


def enviar_alerta_fallo(mensaje: str):
    """Alerta NARANJA por email"""
    try:
        from app.n8n_notifier import enviar_a_n8n
        
        html = f"""
        <div style="background:#fef3c7;border:2px solid #f59e0b;padding:20px;border-radius:8px;">
            <h2 style="color:#92400e;">⚠️ Advertencia - Token Drive</h2>
            <p>{mensaje}</p>
            <p>El sistema reintentará en 30 minutos.</p>
        </div>
        """
        
        enviar_a_n8n(
            tipo_notificacion='extra',
            email='xoblaxbaezaospino@gmail.com',
            serial='WARNING',
            subject='⚠️ Advertencia: Token Drive',
            html_content=html,
            cc_email=None,
            correo_bd=None,
            adjuntos_base64=[]
        )
    except:
        pass


def iniciar_scheduler_token():
    """Inicia el scheduler - RENUEVA CADA 30 MIN"""
    
    scheduler = BackgroundScheduler(
        timezone="America/Bogota",
        job_defaults={'coalesce': True, 'max_instances': 1}
    )
    
    # Cada 30 minutos (token dura 60)
    scheduler.add_job(
        renovar_token_drive,
        trigger='interval',
        minutes=30,
        id='renovar_token',
        replace_existing=True
    )
    
    # Renovar AHORA al iniciar
    scheduler.add_job(
        renovar_token_drive,
        id='renovar_inicial',
        replace_existing=True
    )
    
    scheduler.start()
    
    print("✅ Sistema ROBUSTO de tokens iniciado")
    print("   • Frecuencia: cada 30 min")
    print("   • Reintentos: 5 con backoff")
    print("   • Alertas: automáticas")
    
    return scheduler

