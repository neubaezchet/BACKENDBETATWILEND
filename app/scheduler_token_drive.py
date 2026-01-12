"""
Scheduler para auto-renovación del Access Token de Google Drive
Se ejecuta cada 45 minutos para evitar que expire (expira a los 60 min)
"""

from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import os

def renovar_token_drive():
    """
    Fuerza la renovación del token de Drive
    """
    try:
        from app.drive_uploader import get_authenticated_service, TOKEN_FILE
        import json
        
        print(f"🔄 [{datetime.now()}] Iniciando renovación automática de token...")
        
        # Obtener servicio (esto automáticamente renueva el token si es necesario)
        service = get_authenticated_service()
        
        # Test: hacer una petición mínima
        service.files().list(pageSize=1, fields="files(id)").execute()
        
        # Verificar info del token
        if TOKEN_FILE.exists():
            with open(TOKEN_FILE, 'r') as f:
                token_data = json.load(f)
                expiry_str = token_data.get('expiry')
                if expiry_str:
                    from datetime import datetime as dt
                    expiry = dt.fromisoformat(expiry_str)
                    now = dt.utcnow()
                    remaining_minutes = (expiry - now).total_seconds() / 60
                    print(f"✅ Token renovado exitosamente. Expira en {remaining_minutes:.1f} minutos")
                else:
                    print(f"✅ Token renovado exitosamente")
        else:
            print(f"⚠️ TOKEN_FILE no encontrado, pero servicio activo")
        
        return True
        
    except Exception as e:
        print(f"❌ Error renovando token: {e}")
        import traceback
        traceback.print_exc()
        return False


def iniciar_scheduler_token():
    """
    Inicia el scheduler que renueva el token cada 45 minutos
    """
    scheduler = BackgroundScheduler(
        timezone="America/Bogota",
        job_defaults={
            'coalesce': True,  # Combinar ejecuciones perdidas
            'max_instances': 1  # Solo una instancia a la vez
        }
    )
    
    # Renovar token cada 45 minutos (el token expira a los 60)
    scheduler.add_job(
        renovar_token_drive,
        trigger='interval',
        minutes=45,
        id='renovar_token_drive',
        name='Auto-renovación Token Drive',
        replace_existing=True
    )
    
    # Ejecutar inmediatamente al iniciar
    scheduler.add_job(
        renovar_token_drive,
        id='renovar_token_drive_startup',
        name='Renovación inicial de token',
        replace_existing=True
    )
    
    scheduler.start()
    print("✅ Scheduler de renovación de token iniciado (cada 45 min)")
    
    return scheduler

