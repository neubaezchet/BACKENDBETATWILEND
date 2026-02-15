"""
SERVICIO DE ALERTAS 180 DÍAS - Envío automático de emails
==========================================================
Analiza empleados cercanos a 180 días, envía emails de alerta
a Talento Humano y correos configurados.

Usa el flujo existente: Python → n8n webhook → Gmail SMTP
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.database import (
    AlertaEmail, Alerta180Log, Case, Employee, Company, get_utc_now
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
                # Verificar si ya se envió esta alerta recientemente
                ya_enviada = _alerta_reciente(db, cedula, alerta["tipo"])
                
                if ya_enviada:
                    alertas_omitidas.append({
                        "cedula": cedula,
                        "tipo": alerta["tipo"],
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

def _alerta_reciente(db: Session, cedula: str, tipo_alerta: str) -> bool:
    """Verifica si ya se envió esta misma alerta recientemente"""
    limite = datetime.now() - timedelta(days=PERIODO_NO_REPETIR)
    
    existente = db.query(Alerta180Log).filter(
        Alerta180Log.cedula == cedula,
        Alerta180Log.tipo_alerta == tipo_alerta,
        Alerta180Log.enviado_ok == True,
        Alerta180Log.created_at >= limite,
    ).first()
    
    return existente is not None


def _obtener_destinatarios(db: Session, cedula: str) -> List[str]:
    """
    Obtiene los correos a los que enviar la alerta para un empleado.
    
    Prioridad:
    1. Emails configurados en alerta_emails para la empresa del empleado
    2. Emails globales (company_id IS NULL)
    3. contacto_email de la empresa como fallback
    """
    # Obtener empresa del empleado
    empleado = db.query(Employee).filter(Employee.cedula == cedula).first()
    company_id = empleado.company_id if empleado else None
    
    emails = set()
    
    # 1. Emails específicos de la empresa
    if company_id:
        empresa_emails = db.query(AlertaEmail).filter(
            AlertaEmail.company_id == company_id,
            AlertaEmail.activo == True,
        ).all()
        for e in empresa_emails:
            emails.add(e.email)
    
    # 2. Emails globales
    globales = db.query(AlertaEmail).filter(
        AlertaEmail.company_id.is_(None),
        AlertaEmail.activo == True,
    ).all()
    for e in globales:
        emails.add(e.email)
    
    # 3. Fallback: contacto_email de la empresa
    if not emails and company_id:
        company = db.query(Company).filter(Company.id == company_id).first()
        if company and company.contacto_email:
            emails.add(company.contacto_email)
    
    return list(emails)


def _enviar_alerta_email(
    db: Session,
    cedula: str,
    nombre: str,
    alerta: dict,
    destinatarios: List[str],
) -> dict:
    """Envía el email de alerta vía n8n y registra en el log"""
    
    tipo = alerta.get("tipo", "ALERTA_TEMPRANA")
    dias = alerta.get("dias_acumulados", 0)
    codigos = alerta.get("codigos_involucrados", [])
    codigos_str = ", ".join(codigos) if codigos else "N/A"
    
    # Generar HTML del email
    html = _generar_html_alerta(nombre, cedula, alerta)
    subject = _generar_subject(tipo, nombre, dias)
    
    # Enviar a todos los destinatarios
    exitos = 0
    fallos = 0
    
    for email_dest in destinatarios:
        try:
            from app.n8n_notifier import enviar_a_n8n
            
            resultado = enviar_a_n8n(
                tipo_notificacion="alerta_180",
                email=email_dest,
                serial=f"ALERTA-180-{cedula}",
                subject=subject,
                html_content=html,
                cc_email=None,
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

def _generar_subject(tipo: str, nombre: str, dias: int) -> str:
    """Genera el asunto del correo según el tipo de alerta"""
    if tipo == "LIMITE_180_SUPERADO":
        return f"⛔ URGENTE: {nombre} SUPERÓ 180 días de incapacidad ({dias}d) — Acción inmediata requerida"
    elif tipo == "ALERTA_CRITICA":
        return f"🔴 ALERTA CRÍTICA: {nombre} cerca del límite 180 días ({dias}d) — {180 - dias}d restantes"
    else:
        return f"🟡 AVISO: {nombre} se acerca a 150 días de incapacidad ({dias}d) — Monitorear"


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
    
    # Colores según severidad
    colors = {
        "critica": {"bg": "#DC2626", "light": "#FEE2E2", "text": "#991B1B", "icon": "⛔"},
        "alta": {"bg": "#EA580C", "light": "#FFEDD5", "text": "#9A3412", "icon": "🔴"},
        "media": {"bg": "#CA8A04", "light": "#FEF9C3", "text": "#854D0E", "icon": "🟡"},
    }
    c = colors.get(severidad, colors["media"])
    
    codigos_html = ""
    if codigos:
        codigos_html = " ".join(
            f'<span style="background:#EDE9FE;color:#5B21B6;padding:2px 8px;border-radius:4px;font-size:12px;font-family:monospace;">{code}</span>'
            for code in codigos
        )
    
    barra_progreso = min(dias / 180 * 100, 100)
    barra_color = c["bg"]
    
    restantes_html = ""
    if dias_restantes is not None:
        restantes_html = f"""
        <tr>
            <td style="padding:8px 12px;color:#6B7280;font-size:13px;">Días restantes para 180:</td>
            <td style="padding:8px 12px;font-weight:bold;color:{c['text']};font-size:16px;">{dias_restantes} días</td>
        </tr>"""
    elif dias_excedidos is not None:
        restantes_html = f"""
        <tr>
            <td style="padding:8px 12px;color:#6B7280;font-size:13px;">Días EXCEDIDOS del límite:</td>
            <td style="padding:8px 12px;font-weight:bold;color:#DC2626;font-size:16px;">+{dias_excedidos} días</td>
        </tr>"""
    
    return f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:650px;margin:0 auto;background:#ffffff;">
        <!-- Header -->
        <div style="background:{c['bg']};padding:20px 30px;border-radius:12px 12px 0 0;">
            <h1 style="color:white;margin:0;font-size:20px;">{c['icon']} Alerta de Incapacidad — Ley 776/2002</h1>
            <p style="color:rgba(255,255,255,0.9);margin:5px 0 0;font-size:13px;">Sistema Automático de Detección CIE-10 — IncaNeurobaeza</p>
        </div>
        
        <!-- Body -->
        <div style="padding:25px 30px;border:1px solid #E5E7EB;border-top:none;">
            <!-- Tipo de alerta -->
            <div style="background:{c['light']};border:1px solid {c['bg']}30;border-radius:8px;padding:15px;margin-bottom:20px;">
                <p style="margin:0;color:{c['text']};font-weight:bold;font-size:14px;">{mensaje}</p>
            </div>
            
            <!-- Barra de progreso 180 días -->
            <div style="margin-bottom:20px;">
                <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                    <span style="font-size:11px;color:#6B7280;">Progreso hacia 180 días</span>
                    <span style="font-size:11px;font-weight:bold;color:{c['text']};">{dias}/180 días</span>
                </div>
                <div style="background:#E5E7EB;border-radius:10px;height:14px;overflow:hidden;">
                    <div style="background:{barra_color};height:100%;border-radius:10px;width:{barra_progreso}%;transition:width 0.5s;"></div>
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
                <tr style="background:#F9FAFB;">
                    <td style="padding:8px 12px;color:#6B7280;font-size:13px;">Días acumulados:</td>
                    <td style="padding:8px 12px;font-weight:bold;color:{c['text']};font-size:18px;">{dias} días</td>
                </tr>
                {restantes_html}
                <tr{'  style="background:#F9FAFB;"' if dias_restantes is None and dias_excedidos is None else ''}>
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
            
            <!-- Acciones recomendadas -->
            <div style="background:#F9FAFB;border-radius:8px;padding:15px;margin-bottom:20px;">
                <h3 style="margin:0 0 8px;font-size:13px;color:#374151;">📌 Acciones recomendadas:</h3>
                <ul style="margin:0;padding-left:18px;color:#4B5563;font-size:12px;line-height:1.8;">
                    {'<li><strong>Iniciar trámite ante Fondo de Pensiones</strong> para continuidad de pago al 50%</li>' if tipo == 'LIMITE_180_SUPERADO' else ''}
                    {'<li><strong>Preparar documentación</strong> para eventual traslado a Fondo de Pensiones</li>' if tipo == 'ALERTA_CRITICA' else ''}
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
                Motor CIE-10 2026 — Detección automática de prórrogas — Ley 776/2002<br>
                <em>Para configurar destinatarios, acceda al Dashboard → Alertas 180 Días</em>
            </p>
        </div>
    </div>
    """
