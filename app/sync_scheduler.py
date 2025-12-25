"""
Sincronización automática Excel → PostgreSQL + Verificación de Drive
Ejecuta cada 1 MINUTO (Excel) y cada 5 MINUTOS (Drive token)
"""

from apscheduler.schedulers.background import BackgroundScheduler
from app.sync_excel import sincronizar_excel_completo
import datetime

def verificar_drive_token():
    """Verifica y RENUEVA el token de Drive preventivamente"""
    try:
        from app.drive_uploader import get_authenticated_service
        
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 🔄 Renovando token de Drive preventivamente...")
        service = get_authenticated_service()
        
        # Test rápido: listar 1 archivo para forzar uso del token
        service.files().list(pageSize=1, fields="files(id)").execute()
        
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ✅ Token de Drive renovado y verificado")
    except Exception as e:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ⚠️ Error renovando token: {e}")

def iniciar_sincronizacion_automatica():
    """
    Inicia scheduler de sincronización automática
    ⏱️ Excel: Ejecuta cada 1 MINUTO
    ⏱️ Drive: Verifica cada 5 MINUTOS
    """
    
    scheduler = BackgroundScheduler()
    
    # ✅ Sincronización de Excel (cada 60 segundos)
    scheduler.add_job(
        sincronizar_excel_completo,
        'interval',
        seconds=60,
        id='sync_excel_to_postgresql',
        name='Sincronización Excel → PostgreSQL',
        replace_existing=True
    )
    
    # ✅ Verificación de Drive token (cada 5 minutos)
    scheduler.add_job(
        verificar_drive_token,
        'interval',
        minutes=5,
        id='verificar_drive_token',
        name='Verificación de Token de Google Drive',
        replace_existing=True
    )
    
    scheduler.start()
    
    print("🔄 Sincronización automática activada:")
    print("   • Excel → PostgreSQL: cada 1 minuto")
    print("   • Token de Drive: cada 5 minutos")
    
    # Ejecutar sync inicial inmediatamente
    sincronizar_excel_completo()
    verificar_drive_token()
    
    return scheduler