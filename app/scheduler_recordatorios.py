"""
Sistema de Recordatorios Automáticos
Ejecuta cada día a las 9 AM para verificar casos pendientes > 7 días
"""

from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from app.database import SessionLocal, Case, EstadoCaso
from app.ia_redactor import redactar_recordatorio_7dias, redactar_alerta_jefe_7dias
from app.email_templates import get_email_template_universal
import os
from app.n8n_notifier import enviar_a_n8n

def send_html_email(to_email: str, subject: str, html_body: str, caso=None) -> bool:
    """Envía email usando N8N con copias a empresa y empleado BD"""
    tipo_map = {
        'Recordatorio': 'recordatorio',
        'Seguimiento': 'alerta_jefe'
    }
    
    tipo_notificacion = 'recordatorio'
    for key, value in tipo_map.items():
        if key in subject:
            tipo_notificacion = value
            break
    
    # ✅ Obtener TODOS los emails de copia si hay caso
    correo_bd = None
    cc_email = None
    whatsapp = None
    
    if caso:
        # CC empleado BD
        if hasattr(caso, 'empleado') and caso.empleado:
            if hasattr(caso.empleado, 'correo') and caso.empleado.correo:
                correo_bd = caso.empleado.correo
        
        # CC empresa
        if hasattr(caso, 'empresa') and caso.empresa:
            if hasattr(caso.empresa, 'email_copia') and caso.empresa.email_copia:
                cc_email = caso.empresa.email_copia
        
        # WhatsApp
        if hasattr(caso, 'telefono_form') and caso.telefono_form:
            whatsapp = caso.telefono_form
    
    resultado = enviar_a_n8n(
        tipo_notificacion=tipo_notificacion,
        email=to_email,
        serial=caso.serial if caso else 'AUTO',
        subject=subject,
        html_content=html_body,
        cc_email=cc_email,
        correo_bd=correo_bd,
        whatsapp=whatsapp,
        adjuntos_base64=[]
    )
    
    if resultado:
        print(f"✅ Email enviado a {to_email} (CC empresa: {cc_email or 'N/A'}, CC BD: {correo_bd or 'N/A'}, WhatsApp: {whatsapp or 'N/A'})")
        return True
    
    print(f"❌ Error enviando email a {to_email}")
    return False


def verificar_casos_pendientes():
    """
    Verifica casos incompletos/ilegibles sin respuesta después de 7 días
    Envía recordatorios a empleadas y alertas a jefes
    """
    db = SessionLocal()
    
    try:
        print(f"\n{'='*60}")
        print(f"🔍 Verificación de recordatorios - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")
        
        # Calcular fecha límite (hace 7 días)
        fecha_limite = datetime.now() - timedelta(days=7)
        
        # Buscar casos pendientes
        casos_pendientes = db.query(Case).filter(
            Case.estado.in_([
                EstadoCaso.INCOMPLETA, 
                EstadoCaso.ILEGIBLE, 
                EstadoCaso.INCOMPLETA_ILEGIBLE
            ]),
            Case.updated_at < fecha_limite,
            Case.recordatorio_enviado == False
        ).all()
        
        print(f"📊 Casos encontrados para recordatorio: {len(casos_pendientes)}")
        
        if not casos_pendientes:
            print(f"✅ No hay casos pendientes que requieran recordatorio\n")
            return
        
        recordatorios_enviados = 0
        alertas_jefe_enviadas = 0
        
        for caso in casos_pendientes:
            try:
                empleado = caso.empleado
                
                if not empleado:
                    print(f"⚠️ Caso {caso.serial} sin empleado asignado, omitiendo...")
                    continue
                
                print(f"\n📧 Procesando caso {caso.serial}:")
                print(f"   • Empleado: {empleado.nombre}")
                print(f"   • Estado: {caso.estado.value}")
                print(f"   • Días sin respuesta: {(datetime.now() - caso.updated_at).days}")
                
                # ========== EMAIL A LA EMPLEADA ==========
                if caso.email_form:
                    print(f"   • Generando recordatorio con IA...")
                    
                    # Redactar con IA
                    contenido_ia = redactar_recordatorio_7dias(
                        empleado.nombre,
                        caso.serial,
                        caso.estado.value
                    )
                    
                    # Insertar en plantilla HTML
                    html_email = get_email_template_universal(
                        tipo_email='recordatorio',
                        nombre=empleado.nombre,
                        serial=caso.serial,
                        empresa=caso.empresa.nombre if caso.empresa else 'N/A',
                        tipo_incapacidad=caso.tipo.value if caso.tipo else 'General',
                        telefono=caso.telefono_form,
                        email=caso.email_form,
                        link_drive=caso.drive_link,
                        contenido_ia=contenido_ia  # ✅ Contenido generado por IA
                    )
                    
                    # Enviar
                    if send_html_email(
                        caso.email_form,
                        f"Incapacidad {caso.serial} - {empleado.nombre} - {caso.empresa.nombre if caso.empresa else 'N/A'}",
                        html_email,
                        caso=caso
                    ):
                        recordatorios_enviados += 1
                        print(f"   ✅ Recordatorio enviado a empleada")
                    else:
                        print(f"   ❌ Error enviando recordatorio")
                
                # ========== EMAIL AL JEFE ==========
                if empleado.jefe_email and empleado.jefe_nombre:
                    print(f"   • Generando alerta para jefe ({empleado.jefe_nombre})...")
                    
                    # Redactar con IA
                    contenido_jefe = redactar_alerta_jefe_7dias(
                        empleado.jefe_nombre,
                        empleado.nombre,
                        caso.serial,
                        caso.empresa.nombre if caso.empresa else 'N/A'
                    )
                    
                    # Insertar en plantilla
                    html_jefe = get_email_template_universal(
                        tipo_email='alerta_jefe',
                        nombre=empleado.jefe_nombre,
                        serial=caso.serial,
                        empresa=caso.empresa.nombre if caso.empresa else 'N/A',
                        tipo_incapacidad=caso.tipo.value if caso.tipo else 'General',
                        telefono=caso.telefono_form,
                        email=caso.email_form,
                        link_drive=caso.drive_link,
                        contenido_ia=contenido_jefe,
                        empleado_nombre=empleado.nombre  # Dato adicional para el jefe
                    )
                    
                    # Enviar
                    if send_html_email(
                        empleado.jefe_email,
                        f"📊 Seguimiento - Incapacidad {caso.serial} - {empleado.nombre} - {caso.empresa.nombre if caso.empresa else 'N/A'}",
                        html_jefe,
                        caso=None  # No agregar CCs al jefe
                    ):
                        alertas_jefe_enviadas += 1
                        print(f"   ✅ Alerta enviada a jefe")
                    else:
                        print(f"   ❌ Error enviando alerta al jefe")
                else:
                    print(f"   ⚠️ Sin datos de jefe en el sistema")
                
                # Marcar como enviado
                caso.recordatorio_enviado = True
                caso.fecha_recordatorio = datetime.now()
                db.commit()
                
                print(f"   ✅ Caso {caso.serial} marcado como recordatorio enviado")
                
            except Exception as e:
                print(f"   ❌ Error procesando caso {caso.serial}: {e}")
                db.rollback()
                continue
        
        print(f"\n{'='*60}")
        print(f"📊 RESUMEN:")
        print(f"   • Recordatorios a empleadas: {recordatorios_enviados}")
        print(f"   • Alertas a jefes: {alertas_jefe_enviadas}")
        print(f"   • Total procesados: {len(casos_pendientes)}")
        print(f"{'='*60}\n")
        
    except Exception as e:
        print(f"❌ Error general en verificación: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


def iniciar_scheduler_recordatorios():
    """
    Inicia el scheduler de recordatorios
    Se ejecuta todos los días a las 9:00 AM
    """
    scheduler = BackgroundScheduler()
    
    # ✅ Agregar job: Todos los días a las 9 AM
    scheduler.add_job(
        verificar_casos_pendientes,
        'cron',
        hour=9,
        minute=0,
        id='recordatorios_7dias',
        name='Verificación de recordatorios 7 días',
        replace_existing=True
    )
    
    scheduler.start()
    
    print("✅ Scheduler de recordatorios iniciado")
    print("   • Frecuencia: Diaria a las 9:00 AM")
    print("   • Job ID: recordatorios_7dias")
    
    return scheduler


def test_recordatorios_manual():
    """
    Función para probar recordatorios manualmente (debugging)
    Ejecutar: python -c "from app.scheduler_recordatorios import test_recordatorios_manual; test_recordatorios_manual()"
    """
    print("🧪 MODO TEST - Ejecutando verificación manual de recordatorios...\n")
    verificar_casos_pendientes()
    print("\n✅ Test completado")


if __name__ == "__main__":
    # Para testing local
    test_recordatorios_manual()