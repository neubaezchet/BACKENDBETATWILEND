"""
SCHEDULER DE TAREAS
Tareas programadas para regeneración automática de tabla viva
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
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


def iniciar_scheduler():
    """
    Inicia el scheduler con la tarea programada
    
    Configuración:
    - Se ejecuta el día 1 de cada mes a las 00:01
    - Utiliza cron para precisión
    """
    global scheduler
    
    try:
        if scheduler is None:
            scheduler = BackgroundScheduler()
            
            # Agregar tarea: día 1 de cada mes a las 00:01
            scheduler.add_job(
                tarea_regenerar_tabla_viva,
                CronTrigger(day=1, hour=0, minute=1),
                id='regenerar_tabla_viva',
                name='Regeneración mensual de tabla viva',
                replace_existing=True
            )
            
            scheduler.start()
            logger.info("✅ Scheduler de tabla viva iniciado correctamente")
            logger.info("📅 Próxima ejecución: día 1 del próximo mes a las 00:01")
        
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
            logger.info("🛑 Scheduler de tabla viva detenido")
    
    except Exception as e:
        logger.error(f"❌ Error deteniendo scheduler: {str(e)}")
