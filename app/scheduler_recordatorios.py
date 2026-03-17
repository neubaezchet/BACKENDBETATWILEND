"""
Sistema de Recordatorios Automáticos
- 3 días: recordatorio al empleado
- 5 días: recordatorio al empleado + alerta al jefe
- Cada 3 días adicionales: recordatorio al empleado
Ejecuta cada día a las 9 AM
"""

from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from app.database import SessionLocal, Case, EstadoCaso
from app.ia_redactor import redactar_recordatorio_7dias, redactar_alerta_jefe_7dias
from app.email_templates import get_email_template_universal
import os
from app.n8n_notifier import enviar_a_n8n

def send_html_email(to_email: str, subject: str, html_body: str, caso=None, whatsapp_message=None) -> bool:
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
        
        # CC empresa — desde DIRECTORIO (correos_notificacion area='empresas')
        if hasattr(caso, 'company_id') and caso.company_id:
            try:
                from app.database import SessionLocal as _SL
                from app.database import CorreoNotificacion
                _db = _SL()
                correos = _db.query(CorreoNotificacion).filter(
                    CorreoNotificacion.area == 'empresas',
                    CorreoNotificacion.activo == True
                ).all()
                emails_dir = []
                for c in correos:
                    if (c.company_id is None or c.company_id == caso.company_id) and c.email and c.email.strip():
                        emails_dir.append(c.email.strip())
                if emails_dir:
                    cc_email = ",".join(emails_dir)
                _db.close()
            except Exception as e:
                print(f"⚠️ Error obteniendo CC directorio en recordatorios: {e}")
        
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
        whatsapp_message=whatsapp_message,
        adjuntos_base64=[]
    )
    
    if resultado:
        print(f"✅ Email enviado a {to_email} (CC empresa: {cc_email or 'N/A'}, CC BD: {correo_bd or 'N/A'}, WhatsApp: {whatsapp or 'N/A'})")
        return True
    
    print(f"❌ Error enviando email a {to_email}")
    return False


def verificar_casos_pendientes():
    """
    Verifica casos incompletos/ilegibles y envía recordatorios:
    - 3 días sin respuesta → recordatorio al empleado (+ WhatsApp)
    - 5 días sin respuesta → segundo recordatorio al empleado + alerta al jefe
    - Cada 3 días adicionales → recordatorio al empleado
    Usa recordatorios_count para rastrear cuántos se han enviado.
    """
    db = SessionLocal()
    
    try:
        print(f"\n{'='*60}")
        print(f"🔍 Verificación de recordatorios - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")
        
        ahora = datetime.now()

        # Todos los casos incompletos/ilegibles activos
        casos_pendientes = db.query(Case).filter(
            Case.estado.in_([EstadoCaso.INCOMPLETA, EstadoCaso.ILEGIBLE, EstadoCaso.INCOMPLETA_ILEGIBLE]),
        ).all()

        print(f"📊 Casos en estado incompleta/ilegible: {len(casos_pendientes)}")

        if not casos_pendientes:
            print(f"✅ No hay casos pendientes que requieran recordatorio\n")
            return

        recordatorios_enviados = 0
        alertas_jefe_enviadas = 0
        
        for caso in casos_pendientes:
            try:
                empleado = caso.empleado
                if not empleado:
                    continue

                # ✅ VERIFICAR SI EL EMPLEADO SIGUE ACTIVO EN LA EMPRESA
                # Si se retiró (activo=False), no enviar recordatorios
                if not empleado.activo:
                    print(f"   ⏭️ {caso.serial}: Empleado {empleado.nombre} ya no está activo, omitiendo recordatorios")
                    continue

                dias_sin_respuesta = (ahora - caso.updated_at).days
                count = caso.recordatorios_count or 0

                # Determinar si toca enviar recordatorio
                enviar_empleado = False
                enviar_jefe = False

                if count == 0 and dias_sin_respuesta >= 3:
                    # Primer recordatorio: 3 días → empleado
                    enviar_empleado = True
                elif count == 1 and dias_sin_respuesta >= 5:
                    # Segundo recordatorio: 5 días → empleado + jefe
                    enviar_empleado = True
                    enviar_jefe = True
                elif count >= 2 and dias_sin_respuesta >= (5 + (count - 1) * 3):
                    # Recordatorios adicionales cada 3 días después del día 5
                    enviar_empleado = True

                if not enviar_empleado and not enviar_jefe:
                    continue

                print(f"\n📧 Procesando caso {caso.serial}:")
                print(f"   • Empleado: {empleado.nombre}")
                print(f"   • Estado: {caso.estado.value}")
                print(f"   • Días sin respuesta: {dias_sin_respuesta}")
                print(f"   • Recordatorios previos: {count}")

                # EMAIL AL EMPLEADO
                if enviar_empleado and caso.email_form:
                    print(f"   • Generando recordatorio con IA (día {dias_sin_respuesta})...")
                    checks_guardados_emp = caso.metadata_form.get('checks_seleccionados', []) if caso.metadata_form else []
                    contenido_ia = redactar_recordatorio_7dias(
                        empleado.nombre,
                        caso.serial,
                        caso.estado.value,
                        dias_sin_respuesta=dias_sin_respuesta,
                        checks_seleccionados=checks_guardados_emp
                    )
                    html_email = get_email_template_universal(
                        tipo_email='recordatorio',
                        nombre=empleado.nombre,
                        serial=caso.serial,
                        empresa=caso.empresa.nombre if caso.empresa else 'N/A',
                        tipo_incapacidad=caso.tipo.value if caso.tipo else 'General',
                        telefono=caso.telefono_form,
                        email=caso.email_form,
                        link_drive=caso.drive_link,
                        checks_seleccionados=checks_guardados_emp,
                        contenido_ia=contenido_ia
                    )
                    
                    # Construir WhatsApp con motivos si hay checks guardados
                    wa_msg = None
                    checks_guardados = caso.metadata_form.get('checks_seleccionados', []) if caso.metadata_form else []
                    if checks_guardados:
                        try:
                            from app.checks_disponibles import CHECKS_DISPONIBLES
                            from app.n8n_notifier import _parsear_serial_wa
                            from app.ia_redactor import DOCUMENTOS_REQUERIDOS
                            _ced, _fechas = _parsear_serial_wa(caso.serial)
                            _ftxt = f" {_fechas}" if _fechas else ""
                            wa_l = [f"🔔 *Recordatorio - Documentación Pendiente*", f"Incapacidad{_ftxt}", ""]
                            motivos = [CHECKS_DISPONIBLES[c]['label'] for c in checks_guardados if c in CHECKS_DISPONIBLES]
                            if motivos:
                                wa_l.append("*Motivo:*")
                                for m in motivos[:5]:
                                    wa_l.append(f"• {m}")
                                wa_l.append("")
                            tipo_v = caso.tipo.value.lower().replace(' ', '_') if caso.tipo else 'enfermedad_general'
                            sop = DOCUMENTOS_REQUERIDOS.get(tipo_v, [])
                            if sop:
                                wa_l.append("*Soportes requeridos:*")
                                for s in sop[:5]:
                                    wa_l.append(f"• {s}")
                                wa_l.append("")
                            wa_l.extend(["Enviar en *PDF escaneado*, completo y legible.", "", "Subir documentos: https://repogemin.vercel.app/", "", "_Automatico por Incapacidades_"])
                            wa_msg = "\n".join(wa_l)
                        except Exception as e:
                            print(f"   ⚠️ Error construyendo WhatsApp: {e}")

                    fechas_str = f" ({caso.fecha_inicio.strftime('%d/%m/%Y')} al {caso.fecha_fin.strftime('%d/%m/%Y')})" if caso.fecha_inicio and caso.fecha_fin else ""
                    asunto_rec = f"CC {caso.cedula} - {caso.serial}{fechas_str} - Recordatorio - {empleado.nombre} - {caso.empresa.nombre if caso.empresa else 'N/A'}"
                    
                    if send_html_email(
                        caso.email_form,
                        asunto_rec,
                        html_email,
                        caso=caso,
                        whatsapp_message=wa_msg
                    ):
                        recordatorios_enviados += 1
                        print(f"   ✅ Recordatorio enviado a empleado")
                    else:
                        print(f"   ❌ Error enviando recordatorio")

                # EMAIL AL JEFE (solo a los 5 días)
                if enviar_jefe and empleado.jefe_email:
                    print(f"   • Generando alerta para jefe (5 días) {empleado.jefe_nombre}...")
                    checks_jefe = caso.metadata_form.get('checks_seleccionados', []) if caso.metadata_form else []
                    motivo_jefe = ""
                    if checks_jefe:
                        from app.checks_disponibles import CHECKS_DISPONIBLES
                        motivos_list = [CHECKS_DISPONIBLES[c]['descripcion'] for c in checks_jefe if c in CHECKS_DISPONIBLES]
                        motivo_jefe = "; ".join(motivos_list[:3]) if motivos_list else ""
                    f_inicio = caso.fecha_inicio.strftime('%d/%m/%Y') if caso.fecha_inicio else ""
                    f_fin = caso.fecha_fin.strftime('%d/%m/%Y') if caso.fecha_fin else ""
                    contenido_jefe = redactar_alerta_jefe_7dias(
                        empleado.jefe_nombre,
                        empleado.nombre,
                        caso.serial,
                        caso.empresa.nombre if caso.empresa else 'N/A',
                        fecha_inicio=f_inicio,
                        fecha_fin=f_fin,
                        motivo=motivo_jefe,
                        dias_sin_respuesta=dias_sin_respuesta
                    )
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
                        empleado_nombre=empleado.nombre
                    )
                    # ✅ Adjuntar PDF si existe (desde CaseDocument)
                    adjuntos_jefe = []
                    try:
                        import base64 as _b64j
                        import os as _osjefe
                        from app.database import CaseDocument as _CDoc
                        docs_jefe = db.query(_CDoc).filter(_CDoc.case_id == caso.id).limit(3).all()
                        for doc in docs_jefe:
                            if doc.file_path and _osjefe.path.exists(doc.file_path):
                                with open(doc.file_path, 'rb') as _f:
                                    adjuntos_jefe.append({'filename': _osjefe.path.basename(doc.file_path), 'content': _b64j.b64encode(_f.read()).decode('utf-8'), 'mimetype': 'application/pdf'})
                    except Exception as _ej:
                        print(f"   ⚠️ Sin adjunto para jefe: {_ej}")
                    resultado_jefe = enviar_a_n8n(
                        tipo_notificacion='alerta_jefe',
                        email=empleado.jefe_email,
                        serial=caso.serial,
                        subject=f"📊 Seguimiento - Incapacidad {caso.serial} - {empleado.nombre} - {caso.empresa.nombre if caso.empresa else 'N/A'}",
                        html_content=html_jefe,
                        cc_email=None,
                        adjuntos_base64=adjuntos_jefe,
                        drive_link=caso.drive_link
                    )
                    if resultado_jefe:
                        alertas_jefe_enviadas += 1
                        print(f"   ✅ Alerta enviada a jefe")
                    else:
                        print(f"   ❌ Error enviando alerta al jefe")
                elif enviar_jefe:
                    print(f"   ⚠️ Sin email de jefe en el sistema")

                # Actualizar contador
                caso.recordatorios_count = count + 1
                caso.recordatorio_enviado = True
                caso.fecha_recordatorio = ahora
                db.commit()
                print(f"   ✅ Caso {caso.serial} → recordatorios_count={count + 1}")
            except Exception as e:
                print(f"   ❌ Error procesando caso {caso.serial}: {e}")
                db.rollback()
        
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
        id='recordatorios_3_5_dias',
        name='Recordatorios incompletas (3d empleado, 5d jefe)',
        replace_existing=True
    )
    
    scheduler.start()
    
    print("✅ Scheduler de recordatorios iniciado")
    print("   • Frecuencia: Diaria a las 9:00 AM")
    print("   • 3 días → recordatorio empleado")
    print("   • 5 días → recordatorio empleado + alerta jefe")
    print("   • Cada 3 días después → recordatorio empleado")
    
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