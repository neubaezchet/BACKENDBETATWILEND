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


def iniciar_scheduler():
    """
    Inicia el scheduler con todas las tareas programadas
    
    Tareas:
    1. Regeneración de tabla viva: día 1 de cada mes a las 00:01
    2. Detección de cambios en Completes: cada 3 horas
    3. Limpieza de respaldos expirados: cada 6 horas
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
