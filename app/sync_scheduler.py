"""
Sincronización automática Excel → PostgreSQL + Token de Drive ULTRA-RESISTENTE
✅ Token renovado proactivamente cada 2 minutos
✅ Auto-recuperación en errores con backoff exponencial
✅ Heartbeat continuo para detectar problemas antes de que afecten operaciones
"""

from apscheduler.schedulers.background import BackgroundScheduler
from app.sync_excel import sincronizar_excel_completo
import datetime
import time
import threading

# ═══════════════════════════════════════════════════════════════════
# ESTADO GLOBAL DEL TOKEN (para diagnóstico y recuperación)
# ═══════════════════════════════════════════════════════════════════

_token_status = {
    "last_refresh": None,
    "last_success": None,
    "consecutive_errors": 0,
    "total_refreshes": 0,
    "is_healthy": True,
    "last_error": None
}
_status_lock = threading.Lock()

MAX_CONSECUTIVE_ERRORS = 5  # Después de esto, forzar limpieza total
REFRESH_INTERVAL_SECONDS = 120  # Renovar cada 2 minutos (más seguro)


def get_token_status():
    """Retorna el estado actual del token de Drive (para diagnóstico)"""
    with _status_lock:
        return dict(_token_status)


def _update_token_status(success: bool, error: str = None):
    """Actualiza el estado del token"""
    with _status_lock:
        _token_status["last_refresh"] = datetime.datetime.now().isoformat()
        if success:
            _token_status["last_success"] = datetime.datetime.now().isoformat()
            _token_status["consecutive_errors"] = 0
            _token_status["is_healthy"] = True
            _token_status["total_refreshes"] += 1
            _token_status["last_error"] = None
        else:
            _token_status["consecutive_errors"] += 1
            _token_status["last_error"] = error
            if _token_status["consecutive_errors"] >= MAX_CONSECUTIVE_ERRORS:
                _token_status["is_healthy"] = False


# ═══════════════════════════════════════════════════════════════════
# RENOVACIÓN DE TOKEN ULTRA-RESISTENTE
# ═══════════════════════════════════════════════════════════════════

def verificar_drive_token():
    """
    Verifica y RENUEVA el token de Drive de forma ultra-resistente.
    - Reintenta hasta 3 veces con backoff exponencial
    - Limpia cache si hay errores consecutivos
    - Nunca propaga excepciones (no tumba el scheduler)
    """
    timestamp = datetime.datetime.now().strftime('%H:%M:%S')
    
    for intento in range(3):
        try:
            from app.drive_uploader import (
                get_authenticated_service,
                clear_service_cache,
                clear_token_cache
            )
            
            # Si hay muchos errores consecutivos, limpiar todo primero
            with _status_lock:
                if _token_status["consecutive_errors"] >= 3:
                    print(f"[{timestamp}] 🧹 Limpiando cache por errores acumulados...")
                    clear_service_cache()
                    if _token_status["consecutive_errors"] >= MAX_CONSECUTIVE_ERRORS:
                        clear_token_cache()
            
            print(f"[{timestamp}] 🔄 Renovando token de Drive (intento {intento+1}/3)...")
            
            # Obtener servicio (esto renueva el token internamente si es necesario)
            service = get_authenticated_service()
            
            # Test REAL: hacer una operación en Drive para verificar que funciona
            result = service.files().list(
                pageSize=1, 
                fields="files(id, name)"
            ).execute()
            
            _update_token_status(success=True)
            print(f"[{timestamp}] ✅ Token válido y funcionando (renovación #{_token_status['total_refreshes']})")
            return True  # Éxito
            
        except Exception as e:
            error_msg = str(e)
            print(f"[{timestamp}] ⚠️ Error intento {intento+1}/3: {error_msg[:100]}")
            
            # Si es error de autenticación grave, limpiar cache
            if any(x in error_msg.lower() for x in ['invalid_grant', 'unauthorized', 'revoked']):
                try:
                    from app.drive_uploader import clear_service_cache, clear_token_cache
                    clear_service_cache()
                    clear_token_cache()
                except:
                    pass
            
            # Esperar con backoff exponencial antes de reintentar
            if intento < 2:
                wait_time = 2 ** (intento + 1)  # 2, 4 segundos
                print(f"[{timestamp}] ⏳ Esperando {wait_time}s antes de reintentar...")
                time.sleep(wait_time)
    
    # Todos los intentos fallaron
    _update_token_status(success=False, error=error_msg[:200] if 'error_msg' in dir() else "Unknown error")
    print(f"[{timestamp}] ❌ Token NO renovado después de 3 intentos")
    
    # NO lanzar excepción - el scheduler debe seguir funcionando
    return False


def _heartbeat_drive():
    """
    Heartbeat silencioso que verifica el estado del token sin hacer logging excesivo.
    Útil para detectar problemas entre renovaciones.
    """
    try:
        from app.drive_uploader import _service_cache
        
        if _service_cache:
            # Solo verificar si ya hay servicio en cache
            _service_cache.files().list(pageSize=1, fields="files(id)").execute()
            return True
    except:
        # Si falla, la próxima renovación programada lo arreglará
        pass
    return False


# ═══════════════════════════════════════════════════════════════════
# SINCRONIZACIÓN EXCEL (con pre-verificación de token)
# ═══════════════════════════════════════════════════════════════════

def sync_excel_con_verificacion():
    """
    Sincroniza Excel verificando primero que el token de Drive esté válido.
    Si el token está caído, intenta recuperarlo antes de sincronizar.
    """
    timestamp = datetime.datetime.now().strftime('%H:%M:%S')
    
    # Pre-verificar estado del token
    with _status_lock:
        if not _token_status["is_healthy"]:
            print(f"[{timestamp}] ⚠️ Token no saludable, intentando recuperar antes de sync...")
            verificar_drive_token()
    
    try:
        sincronizar_excel_completo()
    except Exception as e:
        print(f"[{timestamp}] ❌ Error en sync Excel: {str(e)[:100]}")
        # Si falló por token, intentar recuperar para la próxima vez
        if any(x in str(e).lower() for x in ['unauthorized', 'invalid', 'token']):
            verificar_drive_token()


# ═══════════════════════════════════════════════════════════════════
# LIMPIEZA QUINCENAL
# ═══════════════════════════════════════════════════════════════════

def ejecutar_vaciado_quincenal():
    """
    🗑️ Ejecuta el vaciado de la Hoja Kactus si es día 1 o 16 del mes.
    La función vaciar_hoja_kactus_quincenal() verifica internamente la fecha.
    """
    try:
        from app.sync_excel import vaciar_hoja_kactus_quincenal
        hoy = datetime.datetime.now()
        print(f"[{hoy.strftime('%H:%M:%S')}] 📋 Verificando limpieza quincenal (día {hoy.day})...")
        vaciar_hoja_kactus_quincenal()
    except Exception as e:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ⚠️ Error en limpieza quincenal: {e}")


# ═══════════════════════════════════════════════════════════════════
# INICIALIZADOR DEL SCHEDULER
# ═══════════════════════════════════════════════════════════════════

def iniciar_sincronizacion_automatica():
    """
    Inicia scheduler de sincronización automática ULTRA-RESISTENTE
    
    ⏱️ Token Drive: Cada 2 MINUTOS (más seguro que 5)
    ⏱️ Excel Sync: Cada 1 MINUTO
    ⏱️ Heartbeat: Cada 30 segundos (verificación silenciosa)
    """
    
    scheduler = BackgroundScheduler(
        job_defaults={
            'coalesce': True,  # Si se acumulan jobs, ejecutar solo 1
            'max_instances': 1,  # Solo 1 instancia de cada job
            'misfire_grace_time': 30  # 30 segundos de gracia si se pierde un job
        }
    )
    
    # ✅ PRIMERO: Renovación de token de Drive (cada 2 minutos = más seguro)
    scheduler.add_job(
        verificar_drive_token,
        'interval',
        seconds=REFRESH_INTERVAL_SECONDS,  # 120 segundos = 2 minutos
        id='verificar_drive_token',
        name='Renovación Token Drive',
        replace_existing=True
    )
    
    # ✅ Sincronización de Excel (cada 60 segundos, con pre-verificación)
    scheduler.add_job(
        sync_excel_con_verificacion,
        'interval',
        seconds=60,
        id='sync_excel_to_postgresql',
        name='Sincronización Excel → PostgreSQL',
        replace_existing=True
    )
    
    # ✅ Heartbeat silencioso (cada 30 segundos, solo verifica)
    scheduler.add_job(
        _heartbeat_drive,
        'interval',
        seconds=30,
        id='heartbeat_drive',
        name='Heartbeat Drive (silencioso)',
        replace_existing=True
    )
    
    # ✅ Limpieza quincenal de Hoja Kactus (día 1 y 16 a las 00:30)
    scheduler.add_job(
        ejecutar_vaciado_quincenal,
        'cron',
        hour=0,
        minute=30,
        id='vaciado_quincenal_kactus',
        name='Limpieza quincenal Hoja Kactus',
        replace_existing=True
    )
    
    scheduler.start()
    
    print("=" * 60)
    print("🔄 SINCRONIZACIÓN AUTOMÁTICA ULTRA-RESISTENTE ACTIVADA")
    print("=" * 60)
    print("   • Token Drive: cada 2 minutos (renovación proactiva)")
    print("   • Excel → PostgreSQL: cada 1 minuto")
    print("   • Heartbeat Drive: cada 30 segundos (monitoreo)")
    print("   • Limpieza Kactus: quincenal (día 1 y 16)")
    print("=" * 60)
    
    # CRÍTICO: Renovar token PRIMERO antes de cualquier otra cosa
    print("\n🚀 Iniciando renovación inicial del token...")
    token_ok = verificar_drive_token()
    
    if token_ok:
        print("✅ Token inicial válido, ejecutando sync inicial...")
        sync_excel_con_verificacion()
    else:
        print("⚠️ Token inicial con problemas, se reintentará automáticamente")
    
    return scheduler