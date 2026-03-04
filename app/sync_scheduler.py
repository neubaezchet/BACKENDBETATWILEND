"""
Sincronización automática Excel → PostgreSQL + Token de Drive ULTRA-RESISTENTE
✅ Token renovado proactivamente cada 2 minutos
✅ Auto-recuperación en errores con backoff exponencial
✅ Heartbeat continuo para detectar problemas antes de que afecten operaciones
✅ Recuperación de emergencia automática si todo falla
✅ Lock global para evitar race conditions SSL entre threads
"""

from apscheduler.schedulers.background import BackgroundScheduler
from app.sync_excel import sincronizar_excel_completo
import datetime
import time
import threading

# ═══════════════════════════════════════════════════════════════════
# LOCK GLOBAL PARA OPERACIONES DE GOOGLE API
# Previene segmentation faults por SSL race conditions
# ═══════════════════════════════════════════════════════════════════

_google_api_lock = threading.Lock()
_api_in_progress = False  # Flag para heartbeat (evita esperar)

# ═══════════════════════════════════════════════════════════════════
# ESTADO GLOBAL DEL TOKEN (para diagnóstico y recuperación)
# ═══════════════════════════════════════════════════════════════════

_token_status = {
    "last_refresh": None,
    "last_success": None,
    "consecutive_errors": 0,
    "total_refreshes": 0,
    "is_healthy": True,
    "last_error": None,
    "emergency_mode": False
}
_status_lock = threading.Lock()

MAX_CONSECUTIVE_ERRORS = 3  # Después de esto, activar modo emergencia
REFRESH_INTERVAL_SECONDS = 120  # Renovar cada 2 minutos


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
            _token_status["emergency_mode"] = False
        else:
            _token_status["consecutive_errors"] += 1
            _token_status["last_error"] = error
            if _token_status["consecutive_errors"] >= MAX_CONSECUTIVE_ERRORS:
                _token_status["is_healthy"] = False
                _token_status["emergency_mode"] = True


# ═══════════════════════════════════════════════════════════════════
# RENOVACIÓN DE TOKEN ULTRA-RESISTENTE
# ═══════════════════════════════════════════════════════════════════

def verificar_drive_token():
    """
    Verifica y RENUEVA el token de Drive de forma ultra-resistente.
    - Usa lock global para evitar race conditions SSL
    - Reintenta hasta 5 veces con backoff exponencial
    - Regeneración forzada si hay errores acumulados
    - NUNCA propaga excepciones (no tumba el scheduler)
    """
    global _api_in_progress
    timestamp = datetime.datetime.now().strftime('%H:%M:%S')
    
    # Usar lock global para evitar SSL race conditions
    with _google_api_lock:
        _api_in_progress = True
        try:
            return _verificar_drive_token_internal(timestamp)
        finally:
            _api_in_progress = False


def _verificar_drive_token_internal(timestamp):
    """Implementación interna de verificación de token (ya con lock)"""
    
    # Verificar si estamos en modo emergencia
    with _status_lock:
        emergency = _token_status["emergency_mode"]
        consecutive = _token_status["consecutive_errors"]
    
    if emergency or consecutive >= 2:
        print(f"[{timestamp}] 🚨 MODO EMERGENCIA - Intentando regeneración forzada...")
        try:
            from app.drive_uploader import force_regenerate_token
            service = force_regenerate_token()
            if service:
                _update_token_status(success=True)
                print(f"[{timestamp}] ✅ Recuperación de emergencia EXITOSA")
                return True
        except Exception as e:
            print(f"[{timestamp}] ❌ Regeneración forzada falló: {str(e)[:80]}")
    
    # Intento normal de renovación
    for intento in range(5):
        try:
            from app.drive_uploader import (
                get_authenticated_service,
                clear_service_cache,
                clear_token_cache,
                force_regenerate_token
            )
            
            print(f"[{timestamp}] 🔄 Renovando token (intento {intento+1}/5)...")
            
            # En intentos > 2, limpiar cache primero
            if intento >= 2:
                print(f"[{timestamp}] 🧹 Limpiando cache por intentos fallidos...")
                clear_service_cache()
                if intento >= 3:
                    clear_token_cache()
            
            # En intento 4, intentar regeneración forzada
            if intento == 4:
                print(f"[{timestamp}] 🔥 Último intento - regeneración forzada...")
                service = force_regenerate_token()
                if service:
                    _update_token_status(success=True)
                    print(f"[{timestamp}] ✅ Token regenerado en último intento")
                    return True
                continue
            
            # Obtener servicio (esto renueva el token internamente)
            service = get_authenticated_service()
            
            # Test REAL: operación en Drive
            service.files().list(pageSize=1, fields="files(id)").execute()
            
            _update_token_status(success=True)
            print(f"[{timestamp}] ✅ Token válido (renovación #{_token_status['total_refreshes']})")
            return True
            
        except Exception as e:
            error_msg = str(e)[:100]
            print(f"[{timestamp}] ⚠️ Error intento {intento+1}/5: {error_msg}")
            
            # Esperar con backoff exponencial (máximo 20 segundos)
            if intento < 4:
                wait_time = min(2 ** (intento + 1), 20)
                print(f"[{timestamp}] ⏳ Esperando {wait_time}s...")
                time.sleep(wait_time)
    
    # Todos los intentos fallaron
    _update_token_status(success=False, error=error_msg if 'error_msg' in dir() else "Unknown")
    print(f"[{timestamp}] ❌ Token NO renovado - próximo intento en 2 min")
    
    # NO lanzar excepción - el scheduler debe seguir funcionando
    return False


def _heartbeat_drive():
    """
    Heartbeat que verifica el estado del token.
    Si otra operación está en progreso, salta este heartbeat.
    """
    global _api_in_progress
    
    # Si hay otra operación de API en progreso, saltar heartbeat
    if _api_in_progress:
        return True  # No es un error, simplemente omitimos
    
    # Intentar obtener el lock sin bloquear
    if not _google_api_lock.acquire(blocking=False):
        return True  # Otra operación tiene el lock, omitir
    
    try:
        _api_in_progress = True
        from app.drive_uploader import _service_cache
        
        if _service_cache:
            _service_cache.files().list(pageSize=1, fields="files(id)").execute()
            return True
        else:
            # No hay servicio en cache, forzar renovación
            with _status_lock:
                if _token_status["is_healthy"]:
                    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 💓 Heartbeat: Sin cache, forzando renovación...")
            # Llamar a la implementación interna porque ya tenemos el lock
            _verificar_drive_token_internal(datetime.datetime.now().strftime('%H:%M:%S'))
    except Exception as e:
        # Problema detectado, activar renovación
        with _status_lock:
            _token_status["is_healthy"] = False
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 💔 Heartbeat falló: {str(e)[:50]}")
        _verificar_drive_token_internal(datetime.datetime.now().strftime('%H:%M:%S'))
    finally:
        _api_in_progress = False
        _google_api_lock.release()
    return False


# ═══════════════════════════════════════════════════════════════════
# SINCRONIZACIÓN EXCEL (con protección total)
# ═══════════════════════════════════════════════════════════════════

def sync_excel_con_verificacion():
    """
    Sincroniza Excel con máxima protección.
    - Usa lock global para evitar race conditions SSL
    - Verifica token antes de sincronizar
    - Si falla, recupera y reintenta
    - NUNCA propaga excepciones
    """
    global _api_in_progress
    timestamp = datetime.datetime.now().strftime('%H:%M:%S')
    
    # Usar lock global para evitar SSL race conditions
    with _google_api_lock:
        _api_in_progress = True
        try:
            # Pre-verificar estado del token
            with _status_lock:
                healthy = _token_status["is_healthy"]
            
            if not healthy:
                print(f"[{timestamp}] ⚠️ Token no saludable, recuperando antes de sync...")
                _verificar_drive_token_internal(timestamp)
            
            sincronizar_excel_completo()
            
        except Exception as e:
            error_str = str(e).lower()
            print(f"[{timestamp}] ❌ Error en sync Excel: {str(e)[:80]}")
            
            # Si es error de token, intentar recuperar
            if any(x in error_str for x in ['unauthorized', 'invalid', 'token', 'credential', '401', '403']):
                print(f"[{timestamp}] 🔄 Error de token detectado, recuperando...")
                with _status_lock:
                    _token_status["is_healthy"] = False
                _verificar_drive_token_internal(timestamp)
        finally:
            _api_in_progress = False


# ═══════════════════════════════════════════════════════════════════
# LIMPIEZA QUINCENAL
# ═══════════════════════════════════════════════════════════════════

def ejecutar_vaciado_quincenal():
    """Ejecuta la limpieza de Hoja Kactus si es día 1 o 16."""
    global _api_in_progress
    
    # Usar lock global para evitar SSL race conditions
    with _google_api_lock:
        _api_in_progress = True
        try:
            from app.sync_excel import vaciar_hoja_kactus_quincenal
            hoy = datetime.datetime.now()
            print(f"[{hoy.strftime('%H:%M:%S')}] 📋 Verificando limpieza quincenal (día {hoy.day})...")
            vaciar_hoja_kactus_quincenal()
        except Exception as e:
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ⚠️ Error en limpieza: {e}")
        finally:
            _api_in_progress = False


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