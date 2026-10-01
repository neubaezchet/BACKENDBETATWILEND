"""
SERVICIO DE ALERTAS 180 DÍAS - Envío automático de emails
==========================================================
Analiza empleados cercanos a 180 días, envía emails de alerta
a Talento Humano y correos configurados.

Usa el flujo existente: Python → servicio de notificaciones → Gmail SMTP
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.database import (
    Alerta180Log, Case, Employee, Company, CorreoNotificacion, get_utc_now
)
from app.services.prorroga_detector import analizar_historial_empleado

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# CONSTANTES
# ═══════════════════════════════════════════════════════════

# No re-enviar la misma alerta en este período (días)
PERIODO_NO_REPETIR = 7


# ═══════════════════════════════════════════════════════════
# EJECUCIÓN PRINCIPAL
# ═══════════════════════════════════════════════════════════

def ejecutar_revision_alertas(db: Session, empresa: str = "all") -> dict:
    """
    Revisa TODAS las cédulas, detecta quiénes se acercan a 150/170/180 días
    y envía correos a los destinatarios configurados.
    
    Retorna resumen de alertas enviadas.
    """
    # 1. Obtener todas las cédulas con incapacidades
    query = db.query(Case.cedula).distinct()
    if empresa != "all":
        query = query.join(Company, Case.company_id == Company.id).filter(Company.nombre == empresa)
    
    cedulas = [r[0] for r in query.all() if r[0]]
    
    alertas_enviadas = []
    alertas_omitidas = []
    errores = []
    
    for cedula in cedulas:
        try:
            analisis = analizar_historial_empleado(db, cedula)
            
            if not analisis.get("alertas_180"):
                continue
            
            for alerta in analisis["alertas_180"]:
                # La clave incluye la cadena: una persona puede tener dos o tres
                # cadenas abiertas por patologías distintas y cada una llega a
                # sus hitos por su cuenta. Deduplicar solo por tipo silenciaba la
                # segunda cadena — justo la que nadie estaba mirando.
                clave = _clave_alerta(alerta)

                if _alerta_reciente(db, cedula, clave):
                    alertas_omitidas.append({
                        "cedula": cedula,
                        "tipo": clave,
                        "motivo": f"Ya enviada en los últimos {PERIODO_NO_REPETIR} días"
                    })
                    continue
                
                # Obtener destinatarios
                destinatarios = _obtener_destinatarios(db, cedula)
                
                if not destinatarios:
                    alertas_omitidas.append({
                        "cedula": cedula,
                        "tipo": alerta["tipo"],
                        "motivo": "Sin correos configurados para alertas"
                    })
                    continue
                
                # Enviar alerta
                resultado = _enviar_alerta_email(
                    db=db,
                    cedula=cedula,
                    nombre=analisis.get("nombre", cedula),
                    alerta=alerta,
                    destinatarios=destinatarios,
                )
                
                if resultado["enviado"]:
                    alertas_enviadas.append(resultado)
                else:
                    errores.append(resultado)
        
        except Exception as e:
            errores.append({
                "cedula": cedula,
                "error": str(e)
            })
            logger.error(f"Error revisando alertas para {cedula}: {e}")
    
    return {
        "total_empleados_revisados": len(cedulas),
        "alertas_enviadas": len(alertas_enviadas),
        "alertas_omitidas": len(alertas_omitidas),
        "errores": len(errores),
        "detalle_enviadas": alertas_enviadas,
        "detalle_omitidas": alertas_omitidas[:20],
        "detalle_errores": errores[:20],
    }


# ═══════════════════════════════════════════════════════════
# FUNCIONES AUXILIARES
# ═══════════════════════════════════════════════════════════

def _clave_alerta(alerta: dict) -> str:
    """
    Identidad de una alerta para no repetirla: el hito y la cadena a la que
    pertenece. Cabe en `Alerta180Log.tipo_alerta` (String(50)).
    """
    tipo = alerta.get("tipo", "ALERTA")
    cadena = alerta.get("cadena_id")
    return f"{tipo}#c{cadena}"[:50] if cadena is not None else tipo[:50]


def _alerta_reciente(db: Session, cedula: str, tipo_alerta: str) -> bool:
    """Verifica si ya se envió esta misma alerta recientemente"""
    # get_utc_now, no datetime.now(): `created_at` se guarda en UTC y en Colombia
    # la hora local va 5 h atrás, así que comparar contra la local movía la
    # ventana de 7 días y podía reenviar una alerta antes de tiempo.
    limite = get_utc_now() - timedelta(days=PERIODO_NO_REPETIR)

    existente = db.query(Alerta180Log).filter(
        Alerta180Log.cedula == cedula,
        Alerta180Log.tipo_alerta == tipo_alerta,
        Alerta180Log.enviado_ok == True,
        Alerta180Log.created_at >= limite,
    ).first()
    
    return existente is not None


def _obtener_destinatarios(db: Session, cedula: str) -> List[str]:
    """
    Obtiene los correos a los que enviar la alerta 180 días para un empleado.
    
    Flujo: SOLO correos del DIRECTORIO (correos_notificacion area='alerta_180')
    Ya NO usa contacto_email de la empresa — todo viene del directorio.
    """
    # Obtener empresa del empleado
    empleado = db.query(Employee).filter(Employee.cedula == cedula).first()
    company_id = empleado.company_id if empleado else None
    
    emails = set()
    
    # Correos de notificación area='alerta_180' del DIRECTORIO (admin portal)
    correos_180 = db.query(CorreoNotificacion).filter(
        CorreoNotificacion.area == 'alerta_180',
        CorreoNotificacion.activo == True,
    ).all()
    for c in correos_180:
        # Si el correo es global (sin empresa) o de la misma empresa
        if c.company_id is None or c.company_id == company_id:
            if c.email and c.email.strip():
                emails.add(c.email.strip())
    
    if emails:
        logger.info(f"📧 Directorio alerta_180 → {len(emails)} emails para CC {cedula}: {list(emails)}")
    else:
        logger.warning(f"⚠️ Sin emails en directorio alerta_180 para CC {cedula} (company_id={company_id})")
    
    return list(emails)


def _enviar_alerta_email(
    db: Session,
    cedula: str,
    nombre: str,
    alerta: dict,
    destinatarios: List[str],
) -> dict:
    """Envía el email de alerta vía servicio nativo y registra en el log"""
    
    tipo = _clave_alerta(alerta)
    dias = alerta.get("dias_acumulados", 0)
    codigos = alerta.get("codigos_involucrados", [])
    codigos_str = ", ".join(codigos) if codigos else "N/A"

    # Generar HTML del email
    html = _generar_html_alerta(nombre, cedula, alerta)
    subject = _generar_subject(alerta, nombre)
    
    # ✅ FIX: Obtener CC empresa del directorio para incluir en alertas 180
    cc_empresa = None
    try:
        empleado = db.query(Employee).filter(Employee.cedula == cedula).first()
        if empleado and empleado.company_id:
            correos_empresa = db.query(CorreoNotificacion).filter(
                CorreoNotificacion.area == 'empresas',
                CorreoNotificacion.activo == True
            ).all()
            emails_cc = []
            for c in correos_empresa:
                if (c.company_id is None or c.company_id == empleado.company_id) and c.email and c.email.strip():
                    emails_cc.append(c.email.strip())
            if emails_cc:
                cc_empresa = ",".join(emails_cc)
                logger.info(f"📧 CC empresa (directorio) para alerta 180: {cc_empresa}")
    except Exception as e:
        logger.warning(f"⚠️ Error obteniendo CC empresa para alerta 180: {e}")
    
    # Enviar a todos los destinatarios
    exitos = 0
    fallos = 0
    
    for email_dest in destinatarios:
        try:
            from app.email_service import enviar_notificacion

            resultado = enviar_notificacion(
                tipo_notificacion="alerta_180",
                email=email_dest,
                serial=f"ALERTA-180-{cedula}",
                subject=subject,
                html_content=html,
                cc_email=cc_empresa,  # ✅ FIX: Incluir CC empresa del directorio
                correo_bd=None,
                whatsapp=None,
                whatsapp_message=None,
                adjuntos_base64=[],
            )
            
            if resultado:
                exitos += 1
                logger.info(f"✅ Alerta 180 enviada: {email_dest} → {nombre} ({cedula}) - {dias}d")
            else:
                fallos += 1
                logger.warning(f"❌ Fallo envío alerta: {email_dest}")
        except Exception as e:
            fallos += 1
            logger.error(f"Error enviando alerta a {email_dest}: {e}")
    
    # Registrar en log
    log = Alerta180Log(
        cedula=cedula,
        tipo_alerta=tipo,
        dias_acumulados=dias,
        cadena_codigos_cie10=codigos_str,
        emails_enviados=", ".join(destinatarios),
        enviado_ok=exitos > 0,
    )
    db.add(log)
    db.commit()
    
    return {
        "cedula": cedula,
        "nombre": nombre,
        "tipo": tipo,
        "dias": dias,
        "destinatarios": destinatarios,
        "enviados_ok": exitos,
        "fallos": fallos,
        "enviado": exitos > 0,
    }


# ═══════════════════════════════════════════════════════════
# TEMPLATES HTML DE ALERTA
# ═══════════════════════════════════════════════════════════

def _generar_subject(alerta: dict, nombre: str) -> str:
    """
    El asunto dice el hito, el origen y quién paga. Antes todos los asuntos
    hablaban de "180 días" aunque la alerta fuera del día 120 o del 540, y en
    una cadena laboral eso mandaba a mirar al fondo de pensiones, que no tiene
    nada que ver.
    """
    tipo = alerta.get("tipo", "ALERTA")
    dias = alerta.get("dias_acumulados", 0)
    etiqueta = alerta.get("etiqueta", "")
    marca = f" [{etiqueta}]" if etiqueta else ""

    # El diagnóstico va en el asunto: una persona con dos cadenas abiertas
    # recibe dos alertas del día 150 el mismo día, y sin el diagnóstico son
    # indistinguibles en la bandeja.
    dx = (alerta.get("diagnostico_base") or "").strip()
    dx_marca = f" — {dx[:40]}" if dx else ""

    if tipo == "PRORROGA_CORTADA":
        return f"⚠️ PRÓRROGA CORTADA: {nombre} lleva 30+ días sin incapacidad — Verificar cadena de prórroga"
    if tipo == "ORIGEN_AMBIGUO":
        return (f"⚠️ ORIGEN SIN CONFIRMAR: {nombre} ({dias}d){dx_marca} "
                f"— Definir si se radica a EPS/AFP o a ARL")

    hito_dia = alerta.get("hito_dia")
    responsable = alerta.get("responsable_actual", "")
    if alerta.get("hito_alcanzado"):
        icono = "⛔" if alerta.get("severidad") == "critica" else "🔴"
        return (f"{icono} {nombre}{marca} alcanzó el día {hito_dia} ({dias}d acumulados)"
                f"{dx_marca} — Paga {responsable}")
    restantes = alerta.get("dias_restantes")
    return (f"🟡 {nombre}{marca}: faltan {restantes}d para el día {hito_dia} "
            f"({dias}d acumulados){dx_marca} — Monitorear")


def _generar_html_alerta(nombre: str, cedula: str, alerta: dict) -> str:
    """Genera el HTML del correo de alerta 180 días"""
    tipo = alerta.get("tipo", "ALERTA_TEMPRANA")
    dias = alerta.get("dias_acumulados", 0)
    severidad = alerta.get("severidad", "media")
    mensaje = alerta.get("mensaje", "")
    normativa = alerta.get("normativa", "")
    codigos = alerta.get("codigos_involucrados", [])
    dias_restantes = alerta.get("dias_restantes")
    dias_excedidos = alerta.get("dias_excedidos")
    dias_hueco = alerta.get("dias_hueco")
    fecha_corte = alerta.get("fecha_corte")
    
    # Colores según severidad
    colors = {
        "critica": {"bg": "#DC2626", "light": "#FEE2E2", "text": "#991B1B", "icon": "⛔"},
        "alta": {"bg": "#EA580C", "light": "#FFEDD5", "text": "#9A3412", "icon": "🔴"},
        "media": {"bg": "#CA8A04", "light": "#FEF9C3", "text": "#854D0E", "icon": "🟡"},
    }
    c = colors.get(severidad, colors["media"])
    
    # Override color para PRORROGA_CORTADA
    if tipo == "PRORROGA_CORTADA":
        c = {"bg": "#7C3AED", "light": "#EDE9FE", "text": "#5B21B6", "icon": "⚠️"}
    
    codigos_html = ""
    if codigos:
        codigos_html = " ".join(
            f'<span style="background:#EDE9FE;color:#5B21B6;padding:2px 8px;border-radius:4px;font-size:12px;font-family:monospace;">{code}</span>'
            for code in codigos
        )
    
    # La escala de la barra depende del origen: 540 días en enfermedad general
    # (donde el pagador cambia en el 181 y otra vez en el 541) y 360 en origen
    # laboral, donde paga la ARL y no hay traslado al fondo de pensiones.
    escala = alerta.get("escala_dias") or 180
    etiqueta = alerta.get("etiqueta") or "Incapacidad prolongada"
    responsable = alerta.get("responsable_actual")
    hito_dia = alerta.get("hito_dia")
    barra_progreso = min(dias / escala * 100, 100)
    barra_color = c["bg"]

    marca_hito = ""
    if hito_dia:
        marca_hito = (f'<div style="position:absolute;left:{min(hito_dia / escala * 100, 100)}%;'
                      f'top:0;bottom:0;width:2px;background:#111827;"></div>')

    # Qué cadena es: el diagnóstico base y el número de cadena. Sin esto, dos
    # correos de la misma persona el mismo día no se pueden distinguir.
    diagnostico = (alerta.get("diagnostico_base") or "").strip()
    cadena_id = alerta.get("cadena_id")
    dx_html = ""
    if diagnostico or cadena_id:
        detalle = diagnostico or "Sin diagnóstico en el soporte"
        sufijo = f' <span style="color:#9CA3AF;font-size:11px;">(cadena #{cadena_id})</span>' if cadena_id else ""
        dx_html = f"""
        <tr>
            <td style="padding:8px 12px;color:#6B7280;font-size:13px;">Patología de esta cadena:</td>
            <td style="padding:8px 12px;font-size:13px;">{detalle}{sufijo}</td>
        </tr>"""

    responsable_html = ""
    if responsable:
        responsable_html = f"""
        <tr style="background:#F9FAFB;">
            <td style="padding:8px 12px;color:#6B7280;font-size:13px;">Responsable del pago hoy:</td>
            <td style="padding:8px 12px;font-weight:bold;font-size:15px;color:{c['text']};">{responsable}</td>
        </tr>
        <tr>
            <td colspan="2" style="padding:0 12px 8px;color:#6B7280;font-size:11px;">{alerta.get('nota_responsable') or ''}</td>
        </tr>"""

    casos_especiales = alerta.get("casos_especiales") or []
    casos_html = ""
    if casos_especiales:
        items = "".join(f"<li>{c_}</li>" for c_ in casos_especiales)
        casos_html = f"""
        <div style="background:#FEF3C7;border:1px solid #FCD34D;border-radius:8px;padding:12px;margin-bottom:20px;">
            <p style="margin:0 0 6px;font-size:12px;color:#92400E;font-weight:bold;">
                Para que la EPS siga pagando hay que acreditar UNO de estos casos:
            </p>
            <ol style="margin:0;padding-left:18px;color:#92400E;font-size:12px;line-height:1.7;">{items}</ol>
        </div>"""
    
    # Las acciones dependen del hito: cada hito tiene una gestión distinta y ante
    # una entidad distinta. Radicar ante quien no debe pagar es perder el tiempo.
    acciones = {
        "HIT-120": [
            "<strong>Exigir a la EPS el concepto de rehabilitación</strong> — es su obligación emitirlo antes del día 120",
            "Dejar la solicitud por escrito con número de radicado: es la prueba si la EPS incumple",
        ],
        "HIT-150": [
            "<strong>Verificar que la EPS ya envió el concepto a la AFP</strong> (fecha límite: día 150)",
            "Si no lo envió, <strong>la EPS sigue pagando después del día 180</strong> — guardar la evidencia del incumplimiento",
        ],
        "HIT-180": [
            "<strong>Radicar ante la AFP</strong> el subsidio a partir del día 181",
            "Si la EPS no envió el concepto de rehabilitación antes del día 150, <strong>seguir cobrando a la EPS</strong>, no a la AFP",
            "Confirmar que la AFP recibió el concepto y abrió el trámite",
        ],
        "HIT-540": [
            "<strong>Preparar el cierre del subsidio de la AFP</strong> (termina en el día 540)",
            "Verificar el estado de la calificación de pérdida de capacidad laboral (PCL)",
        ],
        "HIT-541": [
            "<strong>Acreditar ante la EPS uno de los casos especiales</strong> para que reanude el pago",
            "Sin uno de esos casos acreditados, no hay pagador: el caso debe resolverse por calificación de PCL",
        ],
        "HIT-LAB-180": [
            "<strong>Solicitar a la ARL la prórroga del subsidio</strong> (hasta 180 días más)",
            "<strong>No radicar ante EPS ni AFP</strong>: en origen laboral paga la ARL desde el día 1",
        ],
        "HIT-LAB-360": [
            "<strong>Iniciar la calificación de PCL</strong> ante la ARL / Junta de Calificación",
            "Reunir la historia clínica completa y el concepto del médico tratante",
        ],
        "ORIGEN_AMBIGUO": [
            "<strong>Confirmar el origen de la incapacidad</strong> (laboral o enfermedad general): de eso depende quién paga y ante quién se radica",
            "Revisar el dictamen de origen de la ARL o de la Junta si ya existe",
        ],
        "PRORROGA_CORTADA": [
            f"<strong>Solicitar al empleado los certificados de incapacidad faltantes</strong> que puedan llenar el hueco de {dias_hueco} días",
            "<strong>Investigar por qué se interrumpió la cadena de prórroga</strong> — ¿El empleado fue dado de alta? ¿Cambió de EPS? ¿Certificado sin radicar?",
        ],
    }.get(tipo, [])

    acciones_html = "".join(f"<li>{a}</li>" for a in acciones)

    restantes_html = ""
    if dias_restantes is not None:
        restantes_html = f"""
        <tr>
            <td style="padding:8px 12px;color:#6B7280;font-size:13px;">Días restantes para el día {hito_dia or escala}:</td>
            <td style="padding:8px 12px;font-weight:bold;color:{c['text']};font-size:16px;">{dias_restantes} días</td>
        </tr>"""
    elif dias_excedidos is not None:
        restantes_html = f"""
        <tr>
            <td style="padding:8px 12px;color:#6B7280;font-size:13px;">Días EXCEDIDOS del límite:</td>
            <td style="padding:8px 12px;font-weight:bold;color:#DC2626;font-size:16px;">+{dias_excedidos} días</td>
        </tr>"""
    
    # Fila especial para PRORROGA_CORTADA
    hueco_html = ""
    if tipo == "PRORROGA_CORTADA" and dias_hueco:
        hueco_html = f"""
        <tr style="background:#EDE9FE;">
            <td style="padding:8px 12px;color:#5B21B6;font-size:13px;font-weight:bold;">⚠️ Días sin incapacidad (hueco):</td>
            <td style="padding:8px 12px;font-weight:bold;color:#7C3AED;font-size:18px;">{dias_hueco} días</td>
        </tr>
        <tr>
            <td style="padding:8px 12px;color:#6B7280;font-size:13px;">Fecha de corte de cadena:</td>
            <td style="padding:8px 12px;font-family:monospace;color:#5B21B6;">{fecha_corte or 'N/A'}</td>
        </tr>"""
    
    return f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:650px;margin:0 auto;background:#ffffff;">
        <!-- Header -->
        <div style="background:{c['bg']};padding:20px 30px;border-radius:12px 12px 0 0;">
            <h1 style="color:white;margin:0;font-size:20px;">{c['icon']} Alerta de Incapacidad — {etiqueta}</h1>
            <p style="color:rgba(255,255,255,0.9);margin:5px 0 0;font-size:13px;">Sistema Automático de Detección CIE-10 — IncaNeurobaeza</p>
        </div>
        
        <!-- Body -->
        <div style="padding:25px 30px;border:1px solid #E5E7EB;border-top:none;">
            <!-- Tipo de alerta -->
            <div style="background:{c['light']};border:1px solid {c['bg']}30;border-radius:8px;padding:15px;margin-bottom:20px;">
                <p style="margin:0;color:{c['text']};font-weight:bold;font-size:14px;">{mensaje}</p>
            </div>
            
            <!-- Barra de progreso de la cadena -->
            <div style="margin-bottom:20px;">
                <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                    <span style="font-size:11px;color:#6B7280;">{etiqueta} — progreso de esta cadena</span>
                    <span style="font-size:11px;font-weight:bold;color:{c['text']};">{dias}/{escala} días</span>
                </div>
                <div style="position:relative;background:#E5E7EB;border-radius:10px;height:14px;overflow:hidden;">
                    <div style="background:{barra_color};height:100%;border-radius:10px;width:{barra_progreso}%;transition:width 0.5s;"></div>
                    {marca_hito}
                </div>
            </div>

            <!-- Datos del empleado -->
            <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
                <tr style="background:#F9FAFB;">
                    <td style="padding:8px 12px;color:#6B7280;font-size:13px;width:40%;">Empleado:</td>
                    <td style="padding:8px 12px;font-weight:bold;font-size:14px;">{nombre}</td>
                </tr>
                <tr>
                    <td style="padding:8px 12px;color:#6B7280;font-size:13px;">Cédula:</td>
                    <td style="padding:8px 12px;font-family:monospace;">{cedula}</td>
                </tr>
                {dx_html}
                <tr style="background:#F9FAFB;">
                    <td style="padding:8px 12px;color:#6B7280;font-size:13px;">Días acumulados:</td>
                    <td style="padding:8px 12px;font-weight:bold;color:{c['text']};font-size:18px;">{dias} días</td>
                </tr>
                {responsable_html}
                {restantes_html}
                {hueco_html}
                <tr{'  style="background:#F9FAFB;"' if dias_restantes is None and dias_excedidos is None and not hueco_html else ''}>
                    <td style="padding:8px 12px;color:#6B7280;font-size:13px;">Códigos CIE-10:</td>
                    <td style="padding:8px 12px;">{codigos_html or '<span style="color:#9CA3AF;">Sin códigos</span>'}</td>
                </tr>
            </table>
            
            <!-- Normativa -->
            {f'''
            <div style="background:#EFF6FF;border:1px solid #BFDBFE;border-radius:8px;padding:12px;margin-bottom:20px;">
                <p style="margin:0;font-size:12px;color:#1E40AF;">
                    <strong>📋 Marco Legal:</strong> {normativa}
                </p>
            </div>''' if normativa else ''}

            {casos_html}

            <!-- Acciones recomendadas -->
            <div style="background:#F9FAFB;border-radius:8px;padding:15px;margin-bottom:20px;">
                <h3 style="margin:0 0 8px;font-size:13px;color:#374151;">📌 Acciones recomendadas:</h3>
                <ul style="margin:0;padding-left:18px;color:#4B5563;font-size:12px;line-height:1.8;">
                    {acciones_html}
                    <li>Revisar el historial completo del empleado en el dashboard de IncaNeurobaeza</li>
                    <li>Verificar que las prórrogas estén debidamente soportadas con CIE-10</li>
                    <li>Coordinar con el médico tratante la evolución del caso</li>
                    <li>Documentar toda la gestión para auditoría</li>
                </ul>
            </div>
        </div>
        
        <!-- Footer -->
        <div style="background:#F3F4F6;padding:15px 30px;border-radius:0 0 12px 12px;border:1px solid #E5E7EB;border-top:none;">
            <p style="margin:0;font-size:10px;color:#9CA3AF;text-align:center;">
                Este correo fue generado automáticamente por el Sistema de Incapacidades IncaNeurobaeza.<br>
                Motor CIE-10 2026 — Detección automática de prórrogas y de hitos de pago<br>
                <em>Para configurar destinatarios, acceda al Dashboard → Alertas 180 Días</em>
            </p>
        </div>
    </div>
    """
