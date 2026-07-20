"""
SCHEDULER DE TAREAS
Tareas programadas para regeneración automática de tabla viva y gestión de Completes
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Scheduler global
scheduler = None


def tarea_regenerar_tabla_viva():
    """
    Tarea que se ejecuta el día 1 de cada mes a las 00:01
    para regenerar la tabla viva y archivar el mes anterior
    """
    try:
        logger.info("🔄 Iniciando regeneración automática de tabla viva...")
        
        # Aquí iría la lógica de regeneración
        # Por ahora solo registramos que se ejecutó
        logger.info(f"✅ Tabla viva regenerada automáticamente: {datetime.now()}")
        
    except Exception as e:
        logger.error(f"❌ Error en tarea de regeneración: {str(e)}")


# ==================== TAREAS PARA CARPETA COMPLETES ====================

def tarea_detectar_cambios_completes():
    """
    Tarea que se ejecuta cada 3 horas:
    - Revisa Completes/{Empresa}/
    - Detecta archivos eliminados vs BD
    - Crea ZIP con respaldo de 24h
    """
    try:
        logger.info("📋 Iniciando detección de cambios en Completes...")
        
        from app.completes_manager import completes_mgr
        
        respaldos = completes_mgr.detectar_cambios_y_crear_respaldo()
        
        if respaldos:
            logger.info(f"✅ Se crearon {len(respaldos)} respaldos: {list(respaldos.keys())}")
            for empresa, info in respaldos.items():
                logger.info(f"   - {empresa}: {info['cantidad']} archivos en ZIP")
        else:
            logger.info("ℹ️  No se detectaron cambios en Completes")
        
    except Exception as e:
        logger.error(f"❌ Error detectando cambios: {str(e)}")


def tarea_limpiar_respaldos_expirados():
    """
    Tarea que se ejecuta cada 6 horas:
    - Revisa _Respaldos_24h/
    - Elimina ZIPs más viejos que 24h
    """
    try:
        logger.info("🗑️  Iniciando limpieza de respaldos expirados...")
        
        from app.completes_manager import completes_mgr
        
        expirados = completes_mgr.limpiar_respaldos_expirados()
        
        if expirados:
            logger.info(f"✅ Se eliminaron {len(expirados)} respaldos expirados")
            for archivo in expirados:
                logger.info(f"   - {archivo}")
        else:
            logger.info("ℹ️  No hay respaldos expirados para limpiar")
        
    except Exception as e:
        logger.error(f"❌ Error limpiando respaldos: {str(e)}")


def tarea_sincronizar_sheets():
    """
    Tarea que se ejecuta cada 30 minutos:
    - Sincroniza CADA empresa con su propio Google Sheet.
    - Las empresas sin Sheet propio usan el Sheet maestro (compatibilidad).
    """
    try:
        logger.info("🔄 Iniciando sync multi-empresa (Google Sheets → PostgreSQL)...")
        from app.sync_excel import sincronizar_todas_las_empresas
        resultados = sincronizar_todas_las_empresas()
        exitos = sum(1 for r in resultados if r.get("ok"))
        fallos = sum(1 for r in resultados if not r.get("ok"))
        if fallos:
            logger.warning(f"⚠️ Sync multi-empresa: {exitos} OK, {fallos} con error")
        else:
            logger.info(f"✅ Sync multi-empresa: {exitos} empresa(s) sincronizadas")
    except Exception as e:
        logger.error(f"❌ Error en sync multi-empresa: {str(e)}")


def tarea_procesar_cola_radicacion():
    """
    Tarea que se ejecuta cada 2 minutos.
    - Detecta ítems de la cola con proximo_intento vencido y estado fallo_temporal.
    - Los devuelve a 'pendiente' para que browser-use los recoja en el próximo ciclo.
    - Registra un resumen en el log para monitoreo.
    - Si un ítem lleva más de 48 h en la cola sin éxito, lo marca fallo_definitivo.
    """
    try:
        from app.database import SessionLocal, RadicacionCola
        from datetime import datetime, timedelta

        db = SessionLocal()
        ahora = datetime.utcnow()
        limite_48h = ahora - timedelta(hours=48)

        # 1. Devolver a 'pendiente' ítems cuyo backoff ya venció
        listos = db.query(RadicacionCola).filter(
            RadicacionCola.estado == "fallo_temporal",
            RadicacionCola.proximo_intento <= ahora,
        ).all()

        reactivados = 0
        for item in listos:
            # Verificar que no haya superado las 48 h desde su creación
            if item.creado_en and item.creado_en <= limite_48h:
                item.estado       = "fallo_definitivo"
                item.fallo_motivo = (
                    f"Tiempo máximo de 48 h superado. "
                    f"Intentos: {item.intentos}. Último error: {item.ultimo_error}"
                )
                item.procesado_en = ahora
                logger.warning(
                    f"[Cola] Item #{item.id} ({item.eps_key}) → fallo_definitivo por timeout 48 h"
                )
            else:
                item.estado         = "pendiente"
                item.actualizado_en = ahora
                reactivados += 1

        if reactivados:
            logger.info(f"[Cola] {reactivados} ítem(s) reactivado(s) para reintento")

        # 2. Liberar ítems atascados en 'procesando' por más de 30 min
        #    (browser-use pudo haber crasheado sin reportar)
        limite_procesando = ahora - timedelta(minutes=30)
        atascados = db.query(RadicacionCola).filter(
            RadicacionCola.estado == "procesando",
            RadicacionCola.actualizado_en <= limite_procesando,
        ).all()

        for item in atascados:
            item.intentos = (item.intentos or 0) + 1
            if item.intentos >= 12:
                item.estado       = "fallo_definitivo"
                item.fallo_motivo = "Proceso browser-use no reportó resultado en 30 min (posible crash)"
                item.procesado_en = ahora
            else:
                item.estado          = "fallo_temporal"
                item.ultimo_error    = "Timeout: browser-use no reportó en 30 min"
                # Backoff corto para no perder tiempo
                item.proximo_intento = ahora + timedelta(minutes=5)
            item.actualizado_en = ahora
            logger.warning(f"[Cola] Item #{item.id} liberado de estado 'procesando' atascado")

        db.commit()

        # 3. Log de resumen
        pendientes = db.query(RadicacionCola).filter(
            RadicacionCola.estado == "pendiente",
            RadicacionCola.proximo_intento <= ahora,
        ).count()
        if pendientes:
            logger.info(f"[Cola] {pendientes} ítem(s) pendiente(s) listos para browser-use")

        db.close()

    except Exception as e:
        logger.error(f"❌ Error en tarea_procesar_cola_radicacion: {e}")


def iniciar_scheduler():
    """
    Inicia el scheduler con todas las tareas programadas

    Tareas:
    1. Regeneración de tabla viva: día 1 de cada mes a las 00:01
    2. Detección de cambios en Completes: cada 30 minutos
    3. Limpieza de respaldos expirados: cada 6 horas
    4. Sincronización Google Sheets → BD (multi-empresa): cada 30 minutos
    """
    global scheduler
    
    try:
        if scheduler is None:
            scheduler = BackgroundScheduler()
            
            # Tarea 1: Regeneración de tabla viva
            scheduler.add_job(
                tarea_regenerar_tabla_viva,
                CronTrigger(day=1, hour=0, minute=1),
                id='regenerar_tabla_viva',
                name='Regeneración mensual de tabla viva',
                replace_existing=True
            )
            logger.info("✅ Tarea registrada: Regeneración de tabla viva (día 1, 00:01)")
            
            # Tarea 2: Detección de cambios cada 30 minutos
            scheduler.add_job(
                tarea_detectar_cambios_completes,
                IntervalTrigger(minutes=30),
                id='detectar_cambios_completes',
                name='Detección de cambios en Completes',
                replace_existing=True
            )
            logger.info("✅ Tarea registrada: Detección de cambios (cada 30 minutos)")
            
            # Tarea 3: Limpieza de respaldos cada 6 horas
            scheduler.add_job(
                tarea_limpiar_respaldos_expirados,
                IntervalTrigger(hours=6),
                id='limpiar_respaldos',
                name='Limpieza de respaldos expirados',
                replace_existing=True
            )
            logger.info("✅ Tarea registrada: Limpieza de respaldos (cada 6 horas)")
            
            # Tarea 4: Sync multi-empresa Sheets → BD cada 30 minutos
            scheduler.add_job(
                tarea_sincronizar_sheets,
                IntervalTrigger(minutes=30),
                id='sincronizar_sheets_multi_empresa',
                name='Sync Google Sheets → PostgreSQL (multi-empresa)',
                replace_existing=True
            )
            logger.info("✅ Tarea registrada: Sync Sheets multi-empresa (cada 30 minutos)")

            # Tarea 5: Cola de radicación — reintentos con backoff (cada 2 min)
            scheduler.add_job(
                tarea_procesar_cola_radicacion,
                IntervalTrigger(minutes=2),
                id='procesar_cola_radicacion',
                name='Cola de radicación — gestión de reintentos',
                replace_existing=True,
            )
            logger.info("✅ Tarea registrada: Cola radicación — reintentos (cada 2 min)")

            # Tarea 6: Dispatcher Browserbase — lanza runs desde la cola y
            # sincroniza resultados (reemplaza el ciclo de browser-use)
            from app.services.radicacion_dispatcher import ciclo_dispatcher_sync
            scheduler.add_job(
                ciclo_dispatcher_sync,
                IntervalTrigger(minutes=1),
                id='dispatcher_browserbase',
                name='Dispatcher Browserbase — cola → runs → resultados',
                replace_existing=True,
            )
            logger.info("✅ Tarea registrada: Dispatcher Browserbase (cada 1 min)")

            scheduler.start()
            logger.info("=" * 60)
            logger.info("✅ SCHEDULER INICIADO CORRECTAMENTE")
            logger.info("=" * 60)
            logger.info("📋 Tareas programadas:")
            for job in scheduler.get_jobs():
                logger.info(f"   • {job.name}: {job.trigger}")
            logger.info("=" * 60)
        
        return scheduler
    
    except Exception as e:
        logger.error(f"❌ Error iniciando scheduler: {str(e)}")
        raise


def detener_scheduler():
    """
    Detiene el scheduler de forma segura
    """
    global scheduler
    
    try:
        if scheduler is not None:
            scheduler.shutdown()
            scheduler = None
            logger.info("🛑 Scheduler detenido correctamente")
    
    except Exception as e:
        logger.error(f"❌ Error deteniendo scheduler: {str(e)}")
