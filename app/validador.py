"""
Router del Portal de Validadores - IncaNeurobaeza
Endpoints para gestión, validación y búsqueda de casos
"""

from fastapi import APIRouter, Depends, HTTPException, Header, UploadFile, File, Form, Request, Query, BackgroundTasks
from fastapi.responses import StreamingResponse, FileResponse
import requests
import io
import os
import tempfile
import base64
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import or_, and_, func
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from pydantic import BaseModel
import pandas as pd

from app.database import (
    get_db, Case, CaseDocument, CaseEvent, CaseNote, Employee, 
    Company, SearchHistory, EstadoCaso, EstadoDocumento, TipoIncapacidad,
    CorreoNotificacion, AlertaEmail, Alerta180Log, get_utc_now
)
from app.checks_disponibles import CHECKS_DISPONIBLES, obtener_checks_por_tipo
from app.email_templates import get_email_template_universal
from app.drive_manager import CaseFileOrganizer
from app.n8n_notifier import enviar_a_n8n  # ✅ NUEVO
from app.completes_manager import completes_mgr  # ✅ NUEVO - Sincronización Completes
from app.notification_queue import notification_queue, NotificacionPendiente  # ✅ Cola de notificaciones

router = APIRouter(prefix="/validador", tags=["Portal de Validadores"])

# ==================== MODELOS PYDANTIC ====================

class FiltrosCasos(BaseModel):
    empresa: Optional[str] = None
    estado: Optional[str] = None
    tipo: Optional[str] = None
    q: Optional[str] = None
    page: int = 1
    page_size: int = 20

class CambioEstado(BaseModel):
    estado: str
    motivo: Optional[str] = None
    documentos: Optional[List[Dict]] = None
    fecha_limite: Optional[str] = None

class NotaRapida(BaseModel):
    contenido: str
    es_importante: bool = False

class BusquedaRelacional(BaseModel):
    cedula: Optional[str] = None
    serial: Optional[str] = None
    nombre: Optional[str] = None
    tipo_incapacidad: Optional[str] = None
    eps: Optional[str] = None
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None

class BusquedaRelacionalRequest(BaseModel):
    filtros_globales: Optional[Dict[str, Any]] = None
    registros: List[BusquedaRelacional]

# ==================== UTILIDADES ====================

def verificar_token_admin(x_admin_token: str = Header(...)):
    """Verifica que el token de administrador sea válido"""
    admin_token = os.environ.get("ADMIN_TOKEN")
    
    if not admin_token:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN no configurado en el servidor")
    
    if x_admin_token != admin_token:
        raise HTTPException(status_code=403, detail="Token de administrador inválido")
    
    return True

def registrar_evento(db: Session, case_id: int, accion: str, actor: str = "Sistema", 
                     estado_anterior: str = None, estado_nuevo: str = None, 
                     motivo: str = None, metadata: dict = None):
    """Registra un evento en el historial del caso"""
    evento = CaseEvent(
        case_id=case_id,
        actor=actor,
        accion=accion,
        estado_anterior=estado_anterior,
        estado_nuevo=estado_nuevo,
        motivo=motivo,
        metadata_json=metadata
    )
    db.add(evento)
    db.commit()


def obtener_emails_empresa_directorio(company_id, db=None):
    """Obtiene emails CC por empresa.
    Busca en: 1) correos_notificacion area='empresas', 2) Company.email_copia como fallback."""
    emails = set()
    close_db = False
    try:
        if not db:
            from app.database import SessionLocal
            db = SessionLocal()
            close_db = True
        
        # Fuente 1: tabla correos_notificacion (directorio admin)
        correos = db.query(CorreoNotificacion).filter(
            CorreoNotificacion.area == 'empresas',
            CorreoNotificacion.activo == True
        ).all()
        
        for c in correos:
            if c.company_id is None or c.company_id == company_id:
                if c.email and c.email.strip():
                    emails.add(c.email.strip().lower())
        
        # Fuente 2: Company.email_copia (fallback directo)
        if company_id:
            company = db.query(Company).filter(Company.id == company_id).first()
            if company and company.email_copia:
                for em in company.email_copia.split(","):
                    em = em.strip().lower()
                    if em and "@" in em:
                        emails.add(em)
        
        emails = list(emails)
        if emails:
            print(f"📧 CC empresa → {len(emails)} emails para company_id={company_id}: {emails}")
        else:
            print(f"⚠️ CC empresa → Sin emails para company_id={company_id}")
    except Exception as e:
        print(f"⚠️ Error obteniendo emails CC empresa: {e}")
    finally:
        if close_db and db:
            db.close()
    
    return emails


def enviar_email_con_adjuntos(to_email, subject, html_body, adjuntos_paths=[], caso=None, db=None, whatsapp_message=None):
    """
    ✅ Sistema profesional de envío con copias por empresa, empleado Y WhatsApp
    """
    import base64
    from app.n8n_notifier import enviar_a_n8n
    
    # Convertir adjuntos a base64
    adjuntos_base64 = []
    for path in adjuntos_paths:
        if os.path.exists(path):
            try:
                with open(path, 'rb') as f:
                    content = base64.b64encode(f.read()).decode('utf-8')
                    adjuntos_base64.append({
                        'filename': os.path.basename(path),
                        'content': content,
                        'mimetype': 'application/pdf'
                    })
            except Exception as e:
                print(f"⚠️ Error procesando adjunto {path}: {e}")
    
    # Determinar tipo de notificación desde el subject
    tipo_map = {
        'Confirmación': 'confirmacion',
        'Incompleta': 'incompleta',
        'Ilegible': 'ilegible',
        'Validada': 'completa',
        'EPS': 'eps',
        'TTHH': 'tthh',
        'Extra': 'extra',
        'Recordatorio': 'recordatorio',
        'Seguimiento': 'alerta_jefe'
    }
    
    tipo_notificacion = 'confirmacion'
    for key, value in tipo_map.items():
        if key in subject:
            tipo_notificacion = value
            break
    
    # ✅ OBTENER EMAILS DE COPIA Y TELÉFONO
    # CC empresa ahora viene del DIRECTORIO (correos_notificacion area='empresas')
    cc_empresa = None
    correo_bd = None
    whatsapp = None
    
    if caso:
        # ✅ CC EMPRESA: Desde el DIRECTORIO (ya no usa Company.email_copia)
        if hasattr(caso, 'company_id') and caso.company_id:
            emails_dir = obtener_emails_empresa_directorio(caso.company_id)
            if emails_dir:
                cc_empresa = ",".join(emails_dir)
                print(f"📧 CC empresa (directorio): {cc_empresa}")
        
        # ✅ CC EMPLEADO: Correo del empleado en BD (se mantiene)
        if hasattr(caso, 'empleado') and caso.empleado:
            if hasattr(caso.empleado, 'correo') and caso.empleado.correo:
                correo_bd = caso.empleado.correo
                print(f"📧 CC empleado BD: {correo_bd}")
        
        if hasattr(caso, 'telefono_form') and caso.telefono_form:
            whatsapp = caso.telefono_form
            print(f"📱 WhatsApp: {whatsapp}")
    
    # ✅ Si no se pasó mensaje WhatsApp explícito, n8n_notifier lo genera automáticamente
    # (whatsapp_message ya viene del parámetro de la función)
    
    # Obtener drive_link si hay caso
    drive_link = caso.drive_link if caso and hasattr(caso, 'drive_link') else None
    
    # Enviar a n8n
    resultado = enviar_a_n8n(
        tipo_notificacion=tipo_notificacion,
        email=to_email,
        serial=caso.serial if caso else 'N/A',
        subject=subject,
        html_content=html_body,
        cc_email=cc_empresa,
        correo_bd=correo_bd,
        whatsapp=whatsapp,
        whatsapp_message=whatsapp_message,
        adjuntos_base64=adjuntos_base64,
        drive_link=drive_link
    )
    
    if resultado:
        print(f"✅ Email enviado: TO={to_email}, CC_EMPRESA={cc_empresa or 'N/A'}, CC_BD={correo_bd or 'N/A'}")
    else:
        print(f"❌ Error enviando email")
    
    return resultado


def send_html_email(to_email, subject, html_body, caso=None):
    """✅ Wrapper sin adjuntos"""
    return enviar_email_con_adjuntos(to_email, subject, html_body, [], caso=caso)

def enviar_email_con_adjuntos_temp(to_email, subject, html_body, adjuntos_paths=[], caso=None, db=None):
    """
    ✅ Sistema profesional de envío con copias por empresa, empleado Y WhatsApp
    """
    import base64
    from app.n8n_notifier import enviar_a_n8n
    
    # Convertir adjuntos a base64
    adjuntos_base64 = []
    for path in adjuntos_paths:
        if os.path.exists(path):
            try:
                with open(path, 'rb') as f:
                    content = base64.b64encode(f.read()).decode('utf-8')
                    adjuntos_base64.append({
                        'filename': os.path.basename(path),
                        'content': content,
                        'mimetype': 'application/pdf'
                    })
            except Exception as e:
                print(f"⚠️ Error procesando adjunto {path}: {e}")
    
    # Determinar tipo de notificación desde el subject
    tipo_map = {
        'Confirmación': 'confirmacion',
        'Incompleta': 'incompleta',
        'Ilegible': 'ilegible',
        'Validada': 'completa',
        'EPS': 'eps',
        'TTHH': 'tthh',
        'Extra': 'extra',
        'Recordatorio': 'recordatorio',
        'Seguimiento': 'alerta_jefe'
    }
    
    tipo_notificacion = 'confirmacion'
    for key, value in tipo_map.items():
        if key in subject:
            tipo_notificacion = value
            break
    
    # ✅ OBTENER EMAILS DE COPIA Y TELÉFONO
    # CC empresa ahora viene del DIRECTORIO (correos_notificacion area='empresas')
    cc_empresa = None
    correo_bd = None
    whatsapp = None
    
    if caso:
        # ✅ CC EMPRESA: Desde el DIRECTORIO (ya no usa Company.email_copia)
        if hasattr(caso, 'company_id') and caso.company_id:
            emails_dir = obtener_emails_empresa_directorio(caso.company_id)
            if emails_dir:
                cc_empresa = ",".join(emails_dir)
                print(f"📧 CC empresa (directorio): {cc_empresa}")
        
        # ✅ CC EMPLEADO: Correo del empleado en BD (se mantiene)
        if hasattr(caso, 'empleado') and caso.empleado:
            if hasattr(caso.empleado, 'correo') and caso.empleado.correo:
                correo_bd = caso.empleado.correo
                print(f"📧 CC empleado BD: {correo_bd}")
        
        if hasattr(caso, 'telefono_form') and caso.telefono_form:
            whatsapp = caso.telefono_form
            print(f"📱 WhatsApp: {whatsapp}")
    
    # ✅ El mensaje WhatsApp se genera automáticamente
    whatsapp_message = None
    
    # Obtener drive_link si hay caso
    drive_link = caso.drive_link if caso and hasattr(caso, 'drive_link') else None
    
    # Enviar a n8n
    resultado = enviar_a_n8n(
        tipo_notificacion=tipo_notificacion,
        email=to_email,
        serial=caso.serial if caso else 'N/A',
        subject=subject,
        html_content=html_body,
        cc_email=cc_empresa,
        correo_bd=correo_bd,
        whatsapp=whatsapp,
        whatsapp_message=whatsapp_message,
        adjuntos_base64=adjuntos_base64,
        drive_link=drive_link
    )
    
    if resultado:
        print(f"✅ Email enviado: TO={to_email}, CC_EMPRESA={cc_empresa or 'N/A'}, CC_BD={correo_bd or 'N/A'}")
    else:
        print(f"❌ Error enviando email")
    
    return resultado


def obtener_emails_presunto_fraude(empresa_nombre, db=None):
    """Retorna LISTA de emails para presunto fraude según la empresa.
    Busca SOLO en el directorio (correos_notificacion area='presunto_fraude').
    Ya NO usa contacto_email de la empresa — todo viene del directorio.
    """
    emails = set()
    close_db = False
    
    try:
        if not db:
            from app.database import SessionLocal
            db = SessionLocal()
            close_db = True
        
        empresa = db.query(Company).filter(Company.nombre == empresa_nombre).first()
        company_id = empresa.id if empresa else None
        
        # Correos de presunto_fraude del DIRECTORIO (globales o de la empresa)
        correos_pf = db.query(CorreoNotificacion).filter(
            CorreoNotificacion.area == 'presunto_fraude',
            CorreoNotificacion.activo == True
        ).all()
        for c in correos_pf:
            if c.company_id is None or c.company_id == company_id:
                if c.email and c.email.strip():
                    emails.add(c.email.strip())
        
        if emails:
            print(f"📧 Directorio presunto_fraude → {len(emails)} emails para '{empresa_nombre}': {list(emails)}")
        else:
            print(f"⚠️ Directorio presunto_fraude → Sin emails para '{empresa_nombre}'")
    except Exception as e:
        print(f"⚠️ Error buscando emails presunto fraude: {e}")
    finally:
        if close_db and db:
            db.close()
    
    # Fallback si no encontró nada en el directorio
    if not emails:
        fallback = os.environ.get('EMAIL_FRAUDE_DEFAULT', 'xoblaxbaezaospino@gmail.com')
        emails.add(fallback)
        print(f"⚠️ Usando fallback presunto fraude: {fallback}")
    
    return list(emails)


# ==================== ENDPOINTS ====================

@router.get("/diagnostico-directorio")
async def diagnostico_directorio(
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """Diagnóstico del directorio de correos y empresas"""
    empresas = db.query(Company).filter(Company.activa == True).all()
    correos = db.query(CorreoNotificacion).all()
    
    return {
        "empresas": [{
            "id": e.id, "nombre": e.nombre, "nit": e.nit,
            "contacto_email": e.contacto_email, "email_copia": e.email_copia
        } for e in empresas],
        "correos_notificacion": [{
            "id": c.id, "area": c.area, "email": c.email,
            "company_id": c.company_id, "activo": c.activo,
            "nombre_contacto": c.nombre_contacto
        } for c in correos],
        "total_empresas": len(empresas),
        "total_correos": len(correos)
    }


@router.put("/empresa/{empresa_id}/email-copia")
async def configurar_email_copia(
    empresa_id: int,
    datos: dict,
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """Configura email(s) de copia CC para una empresa. Separa múltiples con coma."""
    empresa = db.query(Company).filter(Company.id == empresa_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    
    email_copia = datos.get("email_copia", "").strip()
    empresa.email_copia = email_copia if email_copia else None
    db.commit()
    
    return {
        "status": "ok",
        "empresa": empresa.nombre,
        "email_copia": empresa.email_copia,
        "mensaje": f"Email CC para '{empresa.nombre}' actualizado a: {empresa.email_copia or '(vacío)'}"
    }


@router.get("/empresas")
async def listar_empresas(
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """Lista todas las empresas activas"""
    try:
        empresas = db.query(Company.nombre).filter(Company.activa == True).distinct().all()
        empresas_list = [e[0] for e in empresas if e[0]]
        
        print(f"✅ Empresas encontradas: {len(empresas_list)}")
        return empresas_list
    except Exception as e:
        print(f"❌ Error listando empresas: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/casos")
async def listar_casos(
    empresa: Optional[str] = None,
    estado: Optional[str] = None,
    tipo: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    incluir_historicos: bool = False,  # ✅ NUEVO: parámetro para incluir históricos en búsquedas
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    Lista casos con filtros avanzados
    
    ✅ FILTRO HISTÓRICO:
    - Por defecto (incluir_historicos=False): solo casos actuales (es_historico=False)
    - Con incluir_historicos=True: incluye casos históricos en la búsqueda manual
    - Casos históricos = sin PDF, solo registros base de datos para control quincenal
    """
    
    query = db.query(Case)
    
    # ✅ FILTRO HISTÓRICO - Excluir casos históricos por defecto
    if not incluir_historicos:
        query = query.filter(Case.es_historico == False)
    
    if empresa and empresa != "all" and empresa != "undefined":
        company = db.query(Company).filter(Company.nombre == empresa).first()
        if company:
            query = query.filter(Case.company_id == company.id)
    
    if estado and estado != "all" and estado != "undefined":
        try:
            query = query.filter(Case.estado == EstadoCaso[estado])
        except KeyError:
            pass
    
    if tipo and tipo != "all" and tipo != "undefined":
        try:
            query = query.filter(Case.tipo == TipoIncapacidad[tipo])
        except KeyError:
            pass
    
    if q:
        # Filtro por días: +N filtra dias_incapacidad >= N
        import re as _re
        dias_match = _re.match(r'^\+(\d+)$', q.strip())
        if dias_match:
            min_dias = int(dias_match.group(1))
            query = query.filter(Case.dias_incapacidad >= min_dias)
        else:
            query = query.join(Employee, Case.employee_id == Employee.id, isouter=True)
            query = query.filter(
                or_(
                    Case.serial.ilike(f"%{q}%"),
                    Case.cedula.ilike(f"%{q}%"),
                    Employee.nombre.ilike(f"%{q}%")
                )
            )
    
    total = query.count()
    
    offset = (page - 1) * page_size
    casos = query.order_by(Case.created_at.desc()).offset(offset).limit(page_size).all()
    
    items = []
    for caso in casos:
        empleado = caso.empleado if caso.empleado else None
        empresa_obj = caso.empresa if caso.empresa else None
        
        # Contar reenvíos desde metadata_form
        total_reenvios = 0
        if caso.metadata_form and isinstance(caso.metadata_form, dict):
            reenvios = caso.metadata_form.get('reenvios', [])
            if isinstance(reenvios, list):
                total_reenvios = len(reenvios)
        
        items.append({
            "id": caso.id,
            "serial": caso.serial,
            "cedula": caso.cedula,
            "nombre": empleado.nombre if empleado else "No registrado",
            "empresa": empresa_obj.nombre if empresa_obj else "Otra empresa",
            "tipo": caso.tipo.value if caso.tipo else None,
            "estado": caso.estado.value,
            "created_at": caso.created_at.isoformat(),
            "bloquea_nueva": caso.bloquea_nueva,
            "telefono_form": caso.telefono_form,
            "email_form": caso.email_form,
            "dias_incapacidad": caso.dias_incapacidad,
            "eps": caso.eps,
            "fecha_inicio": caso.fecha_inicio.isoformat() if caso.fecha_inicio else None,
            "fecha_fin": caso.fecha_fin.isoformat() if caso.fecha_fin else None,
            "total_reenvios": total_reenvios,
            "recordatorios_count": caso.recordatorios_count or 0
        })
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
    }

@router.get("/casos/tabla-viva")
async def obtener_tabla_viva(
    empresa: Optional[str] = None,
    periodo: Optional[str] = None,
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    Endpoint para Tabla Viva (Dashboard en tiempo real)
    
    ✅ FILTRO HISTÓRICO:
    - Solo muestra casos actuales (es_historico=False)
    - Excluye los 20,686+ registros históricos sin PDF
    - Los registros históricos siguen siendo buscables manualmente
    
    Parámetros:
    - empresa: Filtrar por empresa ("all" = todas)
    - periodo: mes_actual, trimestre, etc. (por ahora no implementado)
    
    Retorna:
    {
        "total": 123,
        "estadisticas": {
            "INCOMPLETA": 10,
            "EPS_TRANSCRIPCION": 5,
            "NUEVO": 20,
            ...
        }
    }
    """
    
    # Base query: solo casos actuales (no históricos)
    query = db.query(Case).filter(Case.es_historico == False)
    
    # Filtro por empresa
    if empresa and empresa != "all" and empresa != "undefined":
        company = db.query(Company).filter(Company.nombre == empresa).first()
        if company:
            query = query.filter(Case.company_id == company.id)
    
    # Total de casos actuales
    total = query.count()
    
    # Estadísticas por estado
    estadisticas = {
        "INCOMPLETA": query.filter(Case.estado == EstadoCaso.INCOMPLETA).count(),
        "EPS_TRANSCRIPCION": query.filter(Case.estado == EstadoCaso.EPS_TRANSCRIPCION).count(),
        "DERIVADO_TTHH": query.filter(Case.estado == EstadoCaso.DERIVADO_TTHH).count(),
        "COMPLETA": query.filter(Case.estado == EstadoCaso.COMPLETA).count(),
        "NUEVO": query.filter(Case.estado == EstadoCaso.NUEVO).count(),
        "CAUSA_EXTRA": query.filter(Case.estado == EstadoCaso.CAUSA_EXTRA).count(),
        "EN_REVISION": query.filter(Case.estado == EstadoCaso.EN_REVISION).count(),
        "EN_RADICACION": query.filter(Case.estado == EstadoCaso.EN_RADICACION).count(),
        "ILEGIBLE": query.filter(Case.estado == EstadoCaso.ILEGIBLE).count(),
    }
    
    return {
        "total": total,
        "estadisticas": estadisticas
    }

@router.get("/casos/{serial}")
async def detalle_caso(
    serial: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """Obtiene el detalle completo de un caso"""
    
    caso = db.query(Case).filter(Case.serial == serial).first()
    if not caso:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    
    empleado = caso.empleado
    empresa = caso.empresa
    documentos = caso.documentos
    eventos = db.query(CaseEvent).filter(CaseEvent.case_id == caso.id).order_by(CaseEvent.created_at.desc()).all()
    notas = db.query(CaseNote).filter(CaseNote.case_id == caso.id).order_by(CaseNote.created_at.desc()).all()
    
    return {
        "serial": caso.serial,
        "cedula": caso.cedula,
        "nombre": empleado.nombre if empleado else "No registrado",
        "empresa": empresa.nombre if empresa else "Otra empresa",
        "tipo": caso.tipo.value if caso.tipo else None,
        "subtipo": caso.subtipo,
        "dias_incapacidad": caso.dias_incapacidad,
        "estado": caso.estado.value,
        "eps": caso.eps,
        "fecha_inicio": caso.fecha_inicio.isoformat() if caso.fecha_inicio else None,
        "fecha_fin": caso.fecha_fin.isoformat() if caso.fecha_fin else None,
        "diagnostico": caso.diagnostico,
        "metadata_form": caso.metadata_form,
        "bloquea_nueva": caso.bloquea_nueva,
        "drive_link": caso.drive_link,
        "email_form": caso.email_form,
        "telefono_form": caso.telefono_form,
        "created_at": caso.created_at.isoformat(),
        "updated_at": caso.updated_at.isoformat(),
        "documentos": [
            {
                "id": doc.id,
                "doc_tipo": doc.doc_tipo,
                "requerido": doc.requerido,
                "estado_doc": doc.estado_doc.value,
                "drive_urls": doc.drive_urls,
                "version_actual": doc.version_actual,
                "observaciones": doc.observaciones
            }
            for doc in documentos
        ],
        "historial": [
            {
                "id": ev.id,
                "actor": ev.actor,
                "accion": ev.accion,
                "estado_anterior": ev.estado_anterior,
                "estado_nuevo": ev.estado_nuevo,
                "motivo": ev.motivo,
                "created_at": ev.created_at.isoformat()
            }
            for ev in eventos
        ],
        "notas": [
            {
                "id": nota.id,
                "autor": nota.autor,
                "contenido": nota.contenido,
                "es_importante": nota.es_importante,
                "created_at": nota.created_at.isoformat()
            }
            for nota in notas
        ]
    }

@router.post("/casos/{serial}/estado")
async def cambiar_estado(
    serial: str,
    cambio: CambioEstado,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """Cambia el estado de un caso y envía notificaciones via cola"""
    
    caso = db.query(Case).filter(Case.serial == serial).first()
    if not caso:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    
    estado_anterior = caso.estado.value
    nuevo_estado = cambio.estado
    
    try:
        EstadoCaso(nuevo_estado)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Estado inválido: {nuevo_estado}")
    
    caso.estado = EstadoCaso(nuevo_estado)
    
    if cambio.documentos:
        for doc_data in cambio.documentos:
            doc = db.query(CaseDocument).filter(
                CaseDocument.case_id == caso.id,
                CaseDocument.doc_tipo == doc_data.get("doc")
            ).first()
            
            if doc:
                doc.estado_doc = EstadoDocumento(doc_data.get("estado_doc", "PENDIENTE"))
                doc.observaciones = cambio.motivo
    
    registrar_evento(
        db, caso.id, "cambio_estado", 
        actor="Validador",
        estado_anterior=estado_anterior,
        estado_nuevo=nuevo_estado,
        motivo=cambio.motivo,
        metadata={"fecha_limite": cambio.fecha_limite} if cambio.fecha_limite else None
    )
    
    # ✅ CONTADORES: Rastrear intentos incompletos
    if nuevo_estado in ["INCOMPLETA", "ILEGIBLE", "INCOMPLETA_ILEGIBLE"]:
        caso.bloquea_nueva = True
        caso.intentos_incompletos = (caso.intentos_incompletos or 0) + 1
        caso.fecha_ultimo_incompleto = get_utc_now()
    
    if nuevo_estado == "COMPLETA":
        caso.bloquea_nueva = False
        # ✅ RESETEAR CONTADORES DE RECORDATORIOS
        caso.recordatorios_count = 0
        caso.recordatorio_enviado = False
        caso.fecha_recordatorio = None
    
    db.commit()
    
    # ✅ DRIVE: Mover archivos según estado
    if nuevo_estado == "COMPLETA":
        # COPIAR A HISTÓRICO + COMPLETAS + ELIMINAR DE INCOMPLETAS
        try:
            from app.drive_manager import IncompleteFileManager
            
            # 1️⃣ Copiar a Histórico (Incapacidades/{Empresa}/{Año}/{Quincena}/{Tipo}/)
            organizer = CaseFileOrganizer()
            link_historico = organizer.copiar_a_historico(caso)
            if link_historico:
                if not caso.metadata_form:
                    caso.metadata_form = {}
                caso.metadata_form['link_historico'] = link_historico
                print(f"✅ Caso {serial} copiado a Histórico")
            
            # 2️⃣ Copiar a Completas para respaldo rápido
            link_completes = completes_mgr.copiar_caso_a_completes(caso)
            if link_completes:
                if not caso.metadata_form:
                    caso.metadata_form = {}
                caso.metadata_form['link_completes'] = link_completes
                print(f"✅ Caso {serial} copiado a Completas")
            
            # 3️⃣ ELIMINAR DE INCOMPLETAS — Búsqueda robusta por serial
            print(f"🗑️ [{serial}] Buscando y eliminando de Incompletas...")
            incomplete_mgr = IncompleteFileManager()
            
            # Método A: Buscar por serial (elimina TODOS los archivos del serial en Incompletas)
            eliminados_count = incomplete_mgr.eliminar_de_incompletas_por_serial(serial)
            
            # Método B: Si no se encontró por serial, intentar por file_id del drive_link
            if eliminados_count == 0 and caso.drive_link:
                file_id = incomplete_mgr._extract_file_id(caso.drive_link)
                if file_id:
                    eliminado_por_id = incomplete_mgr.eliminar_de_incompletas_por_file_id(file_id)
                    if eliminado_por_id:
                        eliminados_count = 1
                        print(f"✅ Archivo eliminado de Incompletas por file_id: {serial}")
            
            if eliminados_count > 0:
                print(f"✅ [{serial}] {eliminados_count} archivo(s) eliminados de Incompletas")
            
            flag_modified(caso, 'metadata_form')
            db.commit()
            
        except Exception as e:
            print(f"⚠️ Error en manejo de archivos para COMPLETA: {e}")
            import traceback
            traceback.print_exc()
    
    elif nuevo_estado in ["INCOMPLETA", "ILEGIBLE", "INCOMPLETA_ILEGIBLE"]:
        # Mover a Incompletas/{Empresa}/{Motivo}/
        try:
            from app.drive_manager import IncompleteFileManager
            incomplete_mgr = IncompleteFileManager()
            motivo_cat = 'Ilegibles' if 'ILEGIBLE' in nuevo_estado else 'Faltan_Soportes'
            nuevo_link = incomplete_mgr.mover_a_incompletas(caso, motivo_cat)
            if nuevo_link:
                caso.drive_link = nuevo_link
                db.commit()
        except Exception as e:
            print(f"⚠️ Error moviendo a Incompletas: {e}")
    
    # ✅ NOTIFICACIONES VIA COLA (background, no bloquea la respuesta)
    # Obtener emails de directorio una sola vez
    emails_directorio = obtener_emails_empresa_directorio(
        caso.company_id, db
    ) if caso.company_id else []
    cc_directorio = ",".join(emails_directorio) if emails_directorio else None
    
    # Mapeo de estados a notificaciones
    notificaciones_estado = {
        "INCOMPLETA": {
            "tipo": "incompleta",
            "subject": f"📋 Incapacidad Incompleta - {serial}",
            "template": "incompleta"
        },
        "ILEGIBLE": {
            "tipo": "ilegible",
            "subject": f"📄 Documentos Ilegibles - {serial}",
            "template": "ilegible"
        },
        "INCOMPLETA_ILEGIBLE": {
            "tipo": "incompleta_ilegible",
            "subject": f"⚠️ Incapacidad Incompleta e Ilegible - {serial}",
            "template": "incompleta_ilegible"
        },
        "EPS_TRANSCRIPCION": {
            "tipo": "eps_transcripcion",
            "subject": f"🏥 Derivado a EPS - {serial}",
            "template": "eps_transcripcion"
        },
        "DERIVADO_TTHH": {
            "tipo": "derivado_tthh",
            "subject": f"👥 Derivado a Recursos Humanos - {serial}",
            "template": "derivado_tthh"
        },
        "CAUSA_EXTRA": {
            "tipo": "causa_extra",
            "subject": f"📌 Causa Extra Identificada - {serial}",
            "template": "causa_extra"
        },
        "COMPLETA": {
            "tipo": "completa",
            "subject": f"✅ Incapacidad Validada - {serial}",
            "template": "completa"
        },
        "EN_RADICACION": {
            "tipo": "en_radicacion",
            "subject": f"📤 En Radicación - {serial}",
            "template": "en_radicacion"
        }
    }
    
    notificacion_encolada = False
    
    if nuevo_estado in notificaciones_estado and caso.email_form:
        # ✅ Nombre del empleado con fallback robusto
        nombre_empleado = 'Colaborador/a'
        correo_bd_empleado = None
        if caso.empleado:
            nombre_empleado = caso.empleado.nombre or 'Colaborador/a'
            correo_bd_empleado = getattr(caso.empleado, 'correo', None)
        
        config = notificaciones_estado[nuevo_estado]
        
        # ✅ CAPTURAR datos del caso ANTES de salir del scope de DB
        _email = caso.email_form
        _telefono = caso.telefono_form
        _empresa = caso.empresa.nombre if caso.empresa else 'N/A'
        _tipo_inc = caso.tipo.value if caso.tipo else 'General'
        _drive_link = caso.drive_link
        _motivo = cambio.motivo
        
        if nuevo_estado == "COMPLETA":
            # ✅ ENCOLAR NOTIFICACIÓN COMPLETA (con WhatsApp especial)
            print(f"🔔 [{serial}] Encolando notificación COMPLETA → {_email}")
            
            def _enviar_completa():
                notification_queue.encolar_completa(
                    serial=serial,
                    email=_email,
                    nombre_empleado=nombre_empleado,
                    empresa=_empresa,
                    tipo_incapacidad=_tipo_inc,
                    telefono=_telefono,
                    drive_link=_drive_link,
                    cc_email=cc_directorio,
                    correo_bd=correo_bd_empleado,
                    motivo=_motivo
                )
            
            background_tasks.add_task(_enviar_completa)
            notificacion_encolada = True
        else:
            # ✅ ENCOLAR NOTIFICACIÓN GENÉRICA (incompleta, ilegible, etc.)
            print(f"🔔 [{serial}] Encolando notificación {nuevo_estado} → {_email}")
            
            def _enviar_estado():
                notification_queue.encolar_notificacion_estado(
                    serial=serial,
                    tipo=config["tipo"],
                    email=_email,
                    nombre_empleado=nombre_empleado,
                    empresa=_empresa,
                    tipo_incapacidad=_tipo_inc,
                    telefono=_telefono,
                    drive_link=_drive_link,
                    subject=config["subject"],
                    template=config["template"],
                    cc_email=cc_directorio,
                    correo_bd=correo_bd_empleado,
                    motivo=_motivo
                )
            
            background_tasks.add_task(_enviar_estado)
            notificacion_encolada = True
        
        print(f"   📧 Email TO: {_email}")
        print(f"   📱 WhatsApp: {_telefono or 'N/A'}")
        print(f"   📧 CC directorio: {cc_directorio or 'N/A'}")
        
    elif nuevo_estado in notificaciones_estado and not caso.email_form:
        print(f"⚠️ NOTIFICACIÓN OMITIDA para {serial}: No tiene email_form registrado")
    
    return {
        "status": "ok",
        "serial": serial,
        "estado_anterior": estado_anterior,
        "estado_nuevo": nuevo_estado,
        "mensaje": f"Estado actualizado a {nuevo_estado}",
        "emails_directorio": emails_directorio if emails_directorio else [],
        "cc_enviado": cc_directorio,
        "notificacion_encolada": notificacion_encolada,
        "email_destino": caso.email_form or None,
        "whatsapp_destino": caso.telefono_form or None,
        "intentos_incompletos": caso.intentos_incompletos or 0,
        "fecha_ultimo_incompleto": caso.fecha_ultimo_incompleto.isoformat() if caso.fecha_ultimo_incompleto else None
    }


# ==================== COLA DE NOTIFICACIONES ENDPOINTS ====================

@router.get("/notificaciones/estado")
async def estado_cola_notificaciones(
    _: bool = Depends(verificar_token_admin)
):
    """Retorna el estado actual de la cola de notificaciones"""
    return notification_queue.obtener_estado()


@router.get("/notificaciones/{serial}/historial")
async def historial_notificaciones(
    serial: str,
    _: bool = Depends(verificar_token_admin)
):
    """Retorna el historial de notificaciones de un serial"""
    return {
        "serial": serial,
        "historial": notification_queue.obtener_historial_serial(serial)
    }


@router.post("/casos/{serial}/marcar-procesado")
async def marcar_caso_procesado(
    serial: str,
    usuario: Optional[str] = None,
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    Marca un caso como procesado (para tracking en Excel exports).
    
    Útil cuando exportas casos a Excel, los procesas, y quieres marcar
    cuáles ya fueron manejados para no procesar duplicados.
    
    Parámetros:
    - serial: Serial del caso a marcar
    - usuario: Nombre del usuario que procesó (opcional)
    
    Retorna:
    {
        "serial": "INC-2026-001",
        "procesado": True,
        "fecha_procesado": "2026-03-04T15:30:45",
        "usuario": "Admin"
    }
    """
    caso = db.query(Case).filter(Case.serial == serial).first()
    if not caso:
        raise HTTPException(status_code=404, detail=f"Caso {serial} no encontrado")
    
    caso.procesado = True
    caso.fecha_procesado = datetime.now()
    caso.usuario_procesado = usuario or "Sistema"
    db.commit()
    
    return {
        "serial": caso.serial,
        "procesado": caso.procesado,
        "fecha_procesado": caso.fecha_procesado.isoformat() if caso.fecha_procesado else None,
        "usuario": caso.usuario_procesado
    }

@router.post("/casos/{serial}/desmarcar-procesado")
async def desmarcar_caso_procesado(
    serial: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """Desmarca un caso como procesado (revierte la marca)"""
    caso = db.query(Case).filter(Case.serial == serial).first()
    if not caso:
        raise HTTPException(status_code=404, detail=f"Caso {serial} no encontrado")
    
    caso.procesado = False
    caso.fecha_procesado = None
    caso.usuario_procesado = None
    db.commit()
    
    return {
        "serial": caso.serial,
        "procesado": caso.procesado,
        "mensaje": "Caso desmarcado como procesado"
    }

@router.get("/casos/sin-procesar")
async def listar_casos_sin_procesar(
    empresa: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    Lista SOLO casos que NO han sido procesados aún.
    Útil para saber cuáles faltan por procesar del Excel.
    """
    query = db.query(Case).filter(Case.procesado == False)
    
    if empresa and empresa != "all" and empresa != "undefined":
        company = db.query(Company).filter(Company.nombre == empresa).first()
        if company:
            query = query.filter(Case.company_id == company.id)
    
    total = query.count()
    offset = (page - 1) * page_size
    casos = query.order_by(Case.created_at.desc()).offset(offset).limit(page_size).all()
    
    return {
        "sin_procesar": total,
        "items": [
            {
                "serial": c.serial,
                "cedula": c.cedula,
                "estado": c.estado.value,
                "fecha_creacion": c.created_at.isoformat() if c.created_at else None
            }
            for c in casos
        ],
        "page": page,
        "total_pages": (total + page_size - 1) // page_size
    }

@router.post("/casos/{serial}/nota")
async def agregar_nota(
    serial: str,
    nota: NotaRapida,
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """Agrega una nota rápida al caso"""
    
    caso = db.query(Case).filter(Case.serial == serial).first()
    if not caso:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    
    nueva_nota = CaseNote(
        case_id=caso.id,
        autor="Validador",
        contenido=nota.contenido,
        es_importante=nota.es_importante
    )
    
    db.add(nueva_nota)
    db.commit()
    
    return {
        "status": "ok",
        "nota_id": nueva_nota.id,
        "mensaje": "Nota agregada exitosamente"
    }

@router.get("/stats")
async def obtener_estadisticas(
    empresa: Optional[str] = None,
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    Obtiene estadísticas para el dashboard
    
    ✅ FILTRO HISTÓRICO:
    - Solo cuenta casos actuales (es_historico=False)
    - Excluye los 20,686+ registros históricos sin PDF
    """
    
    query = db.query(Case).filter(Case.es_historico == False)  # ✅ Solo casos actuales
    
    if empresa and empresa != "all" and empresa != "undefined":
        company = db.query(Company).filter(Company.nombre == empresa).first()
        if company:
            query = query.filter(Case.company_id == company.id)
    
    stats = {
        "total_casos": query.count(),
        "incompletas": query.filter(Case.estado == EstadoCaso.INCOMPLETA).count(),
        "eps": query.filter(Case.estado == EstadoCaso.EPS_TRANSCRIPCION).count(),
        "tthh": query.filter(Case.estado == EstadoCaso.DERIVADO_TTHH).count(),
        "completas": query.filter(Case.estado == EstadoCaso.COMPLETA).count(),
        "nuevos": query.filter(Case.estado == EstadoCaso.NUEVO).count(),
        "causa_extra": query.filter(Case.estado == EstadoCaso.CAUSA_EXTRA).count(),
    }
    
    return stats

@router.get("/reglas/requisitos")
async def obtener_requisitos_documentos(
    tipo: str,
    dias: Optional[int] = None,
    vehiculo_fantasma: Optional[bool] = None,
    madre_trabaja: Optional[bool] = None,
    es_prorroga: bool = False,
    db: Session = Depends(get_db)
):
    """Motor de reglas dinámico: calcula documentos requeridos según contexto"""
    
    documentos_requeridos = []
    mensajes = []
    
    if tipo == "enfermedad_general":
        documentos_requeridos.append({"doc": "incapacidad_medica", "requerido": True, "aplica": True})
        
        if dias and dias >= 3:
            documentos_requeridos.append({"doc": "epicrisis_o_resumen_clinico", "requerido": True, "aplica": True})
            mensajes.append("Enfermedad general ≥3 días requiere epicrisis o resumen clínico")
        else:
            mensajes.append("1-2 días: solo incapacidad médica (salvo validación manual)")
    
    elif tipo == "enfermedad_laboral":
        documentos_requeridos.append({"doc": "incapacidad_medica", "requerido": True, "aplica": True})
        
        if dias and dias >= 3:
            documentos_requeridos.append({"doc": "epicrisis_o_resumen_clinico", "requerido": True, "aplica": True})
            mensajes.append("Enfermedad laboral ≥3 días requiere epicrisis o resumen clínico")
    
    elif tipo == "accidente_transito":
        documentos_requeridos.append({"doc": "incapacidad_medica", "requerido": True, "aplica": True})
        documentos_requeridos.append({"doc": "epicrisis_o_resumen_clinico", "requerido": True, "aplica": True})
        documentos_requeridos.append({"doc": "furips", "requerido": True, "aplica": True})
        
        if vehiculo_fantasma:
            documentos_requeridos.append({"doc": "soat", "requerido": False, "aplica": False})
            mensajes.append("Vehículo fantasma: no se requiere SOAT")
        else:
            documentos_requeridos.append({"doc": "soat", "requerido": True, "aplica": True})
            mensajes.append("Vehículo identificado: SOAT obligatorio")
    
    elif tipo == "especial":
        documentos_requeridos.append({"doc": "incapacidad_medica", "requerido": True, "aplica": True})
        documentos_requeridos.append({"doc": "epicrisis_o_resumen_clinico", "requerido": True, "aplica": True})
    
    elif tipo == "maternidad":
        documentos_requeridos.extend([
            {"doc": "licencia_o_incapacidad", "requerido": True, "aplica": True},
            {"doc": "epicrisis_o_resumen_clinico", "requerido": True, "aplica": True},
            {"doc": "nacido_vivo", "requerido": True, "aplica": True},
            {"doc": "registro_civil", "requerido": True, "aplica": True}
        ])
        mensajes.append("Maternidad: 4 documentos básicos obligatorios")
    
    elif tipo == "paternidad":
        documentos_requeridos.extend([
            {"doc": "epicrisis_o_resumen_clinico", "requerido": True, "aplica": True},
            {"doc": "cedula_padre", "requerido": True, "aplica": True},
            {"doc": "nacido_vivo", "requerido": True, "aplica": True},
            {"doc": "registro_civil", "requerido": True, "aplica": True}
        ])
        
        if madre_trabaja:
            documentos_requeridos.append({"doc": "licencia_maternidad", "requerido": True, "aplica": True})
            mensajes.append("Madre trabaja: licencia de maternidad obligatoria")
        else:
            documentos_requeridos.append({"doc": "licencia_maternidad", "requerido": False, "aplica": False})
            mensajes.append("Madre no trabaja: licencia de maternidad no requerida")
    
    return {
        "documentos": documentos_requeridos,
        "mensajes": mensajes
    }

@router.post("/busqueda-relacional")
async def busqueda_relacional(
    request: BusquedaRelacionalRequest,
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    Búsqueda relacional avanzada
    
    ✅ REGISTROS HISTÓRICOS:
    - INCLUYE registros históricos (es_historico=True) por defecto
    - Este es un endpoint de búsqueda manual explícita
    - Los usuarios deben poder encontrar casos antiguos sin PDF cuando buscan activamente
    """
    
    resultados = []
    filtros_globales = request.filtros_globales or {}
    
    for registro in request.registros:
        query = db.query(Case).join(Employee, Case.employee_id == Employee.id, isouter=True)
        
        if registro.cedula:
            query = query.filter(Case.cedula == registro.cedula)
        
        if registro.serial:
            query = query.filter(Case.serial == registro.serial)
        
        if registro.nombre:
            query = query.filter(Employee.nombre.ilike(f"%{registro.nombre}%"))
        
        if registro.tipo_incapacidad:
            query = query.filter(Case.tipo == registro.tipo_incapacidad)
        
        if registro.eps:
            query = query.filter(Case.eps.ilike(f"%{registro.eps}%"))
        
        if registro.fecha_inicio and registro.fecha_fin:
            fecha_inicio_dt = datetime.fromisoformat(registro.fecha_inicio)
            fecha_fin_dt = datetime.fromisoformat(registro.fecha_fin)
            query = query.filter(
                and_(
                    Case.fecha_inicio >= fecha_inicio_dt,
                    Case.fecha_fin <= fecha_fin_dt
                )
            )
        elif registro.fecha_inicio:
            fecha_inicio_dt = datetime.fromisoformat(registro.fecha_inicio)
            query = query.filter(Case.fecha_inicio >= fecha_inicio_dt)
        elif registro.fecha_fin:
            fecha_fin_dt = datetime.fromisoformat(registro.fecha_fin)
            query = query.filter(Case.fecha_fin <= fecha_fin_dt)
        
        if filtros_globales.get("empresa"):
            company = db.query(Company).filter(Company.nombre == filtros_globales["empresa"]).first()
            if company:
                query = query.filter(Case.company_id == company.id)
        
        if filtros_globales.get("tipo_documento"):
            tipos_docs = filtros_globales["tipo_documento"]
            query = query.join(CaseDocument).filter(CaseDocument.doc_tipo.in_(tipos_docs))
        
        casos = query.all()
        
        for caso in casos:
            empleado = caso.empleado
            empresa = caso.empresa
            documentos = db.query(CaseDocument).filter(CaseDocument.case_id == caso.id).all()
            
            resultados.append({
                "cedula": caso.cedula,
                "nombre": empleado.nombre if empleado else "No registrado",
                "serial": caso.serial,
                "tipo_incapacidad": caso.tipo.value if caso.tipo else None,
                "eps": caso.eps,
                "fecha_inicio": caso.fecha_inicio.isoformat() if caso.fecha_inicio else None,
                "fecha_fin": caso.fecha_fin.isoformat() if caso.fecha_fin else None,
                "empresa": empresa.nombre if empresa else None,
                "estado": caso.estado.value,
                "documentos": [
                    {
                        "doc_tipo": doc.doc_tipo,
                        "estado_doc": doc.estado_doc.value,
                        "drive_urls": doc.drive_urls
                    }
                    for doc in documentos
                ]
            })
    
    historial = SearchHistory(
        usuario="Validador",
        tipo_busqueda="relacional",
        parametros_json={
            "filtros_globales": filtros_globales,
            "total_registros": len(request.registros)
        },
        resultados_count=len(resultados)
    )
    db.add(historial)
    db.commit()
    
    return {
        "resultados": resultados,
        "total_encontrados": len(resultados),
        "registros_buscados": len(request.registros)
    }

@router.post("/busqueda-relacional/excel")
async def busqueda_relacional_desde_excel(
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """Búsqueda relacional desde Excel"""
    
    contents = await archivo.read()
    
    try:
        if archivo.filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(io.BytesIO(contents))
        elif archivo.filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(contents))
        else:
            raise HTTPException(status_code=400, detail="Formato de archivo no soportado. Use .xlsx, .xls o .csv")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error leyendo archivo: {str(e)}")
    
    columnas_map = {
        "cedula": ["cedula", "cc", "identificacion", "documento"],
        "serial": ["serial", "numero", "consecutivo", "id"],
        "nombre": ["nombre", "trabajador", "empleado", "persona"],
        "tipo_incapacidad": ["tipo", "tipo_incapacidad", "causa", "categoria"],
        "eps": ["eps", "entidad", "salud", "aseguradora"],
        "fecha_inicio": ["fecha_inicio", "fecha inicio", "inicio", "desde"],
        "fecha_fin": ["fecha_fin", "fecha fin", "fin", "hasta"]
    }
    
    columnas_detectadas = {}
    for col_objetivo, posibles_nombres in columnas_map.items():
        for col_df in df.columns:
            if col_df.lower().strip() in posibles_nombres:
                columnas_detectadas[col_objetivo] = col_df
                break
    
    registros = []
    for _, row in df.iterrows():
        registro = BusquedaRelacional()
        
        if "cedula" in columnas_detectadas:
            registro.cedula = str(row[columnas_detectadas["cedula"]]) if pd.notna(row[columnas_detectadas["cedula"]]) else None
        
        if "serial" in columnas_detectadas:
            registro.serial = str(row[columnas_detectadas["serial"]]) if pd.notna(row[columnas_detectadas["serial"]]) else None
        
        if "nombre" in columnas_detectadas:
            registro.nombre = str(row[columnas_detectadas["nombre"]]) if pd.notna(row[columnas_detectadas["nombre"]]) else None
        
        if "tipo_incapacidad" in columnas_detectadas:
            registro.tipo_incapacidad = str(row[columnas_detectadas["tipo_incapacidad"]]) if pd.notna(row[columnas_detectadas["tipo_incapacidad"]]) else None
        
        if "eps" in columnas_detectadas:
            registro.eps = str(row[columnas_detectadas["eps"]]) if pd.notna(row[columnas_detectadas["eps"]]) else None
        
        if "fecha_inicio" in columnas_detectadas:
            try:
                fecha = pd.to_datetime(row[columnas_detectadas["fecha_inicio"]])
                registro.fecha_inicio = fecha.strftime("%Y-%m-%d")
            except:
                registro.fecha_inicio = None
        
        if "fecha_fin" in columnas_detectadas:
            try:
                fecha = pd.to_datetime(row[columnas_detectadas["fecha_fin"]])
                registro.fecha_fin = fecha.strftime("%Y-%m-%d")
            except:
                registro.fecha_fin = None
        
        registros.append(registro)
    
    request = BusquedaRelacionalRequest(registros=registros)
    
    historial = SearchHistory(
        usuario="Validador",
        tipo_busqueda="relacional_excel",
        parametros_json={
            "archivo": archivo.filename,
            "columnas_detectadas": list(columnas_detectadas.keys()),
            "total_filas": len(registros)
        },
        resultados_count=0,
        archivo_nombre=archivo.filename
    )
    db.add(historial)
    db.commit()
    
    resultados_response = await busqueda_relacional(request, db, True)
    
    historial.resultados_count = resultados_response["total_encontrados"]
    db.commit()
    
    return {
        **resultados_response,
        "archivo_procesado": archivo.filename,
        "columnas_detectadas": columnas_detectadas,
        "filas_procesadas": len(registros)
    }

@router.get("/exportar/casos")
async def exportar_casos(
    formato: str = "xlsx",
    empresa: Optional[str] = None,
    estado: Optional[str] = None,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    q: Optional[str] = None,
    incluir_historicos: bool = False,
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    Exportar casos a Excel — respeta TODOS los filtros activos
    
    ✅ FILTRO HISTÓRICO:
    - Por defecto excluye registros históricos sin PDF (es_historico=False)
    - Usar incluir_historicos=true para exportar también históricos
    """
    
    query = db.query(Case).join(Employee, Case.employee_id == Employee.id, isouter=True)
    
    # Filtrar históricos por defecto
    if not incluir_historicos:
        query = query.filter(Case.es_historico == False)
    
    if empresa and empresa != "all":
        company = db.query(Company).filter(Company.nombre == empresa).first()
        if company:
            query = query.filter(Case.company_id == company.id)
    
    if estado and estado != "all":
        query = query.filter(Case.estado == estado)
    
    if q and q.strip():
        busqueda = f"%{q.strip()}%"
        query = query.filter(
            (Case.serial.ilike(busqueda)) |
            (Case.cedula.ilike(busqueda)) |
            (Employee.nombre.ilike(busqueda))
        )
    
    if desde:
        try:
            fecha_desde = datetime.fromisoformat(desde)
            query = query.filter(Case.created_at >= fecha_desde)
        except ValueError:
            pass
    
    if hasta:
        try:
            fecha_hasta = datetime.fromisoformat(hasta)
            query = query.filter(Case.created_at <= fecha_hasta)
        except ValueError:
            pass
    
    casos = query.all()
    
    data = []
    for caso in casos:
        empleado = caso.empleado
        empresa_obj = caso.empresa
        
        data.append({
            "Serial": caso.serial,
            "Cédula": caso.cedula,
            "Nombre": empleado.nombre if empleado else "No registrado",
            "Empresa": empresa_obj.nombre if empresa_obj else "Otra",
            "Tipo": caso.tipo.value if caso.tipo else None,
            "Días": caso.dias_incapacidad,
            "Estado": caso.estado.value,
            "EPS": caso.eps,
            "Fecha Inicio": caso.fecha_inicio.strftime("%Y-%m-%d") if caso.fecha_inicio else None,
            "Fecha Fin": caso.fecha_fin.strftime("%Y-%m-%d") if caso.fecha_fin else None,
            "Diagnóstico": caso.diagnostico,
            "Link Drive": caso.drive_link,
            "Fecha Registro": caso.created_at.strftime("%Y-%m-%d %H:%M"),
            "✅ Procesado": "SÍ" if caso.procesado else "NO",  # ✅ NUEVA COLUMNA para tracking
            "Fecha Procesado": caso.fecha_procesado.strftime("%Y-%m-%d %H:%M") if caso.fecha_procesado else None,
            "Usuario Procesado": caso.usuario_procesado
        })
    
    df = pd.DataFrame(data)
    
    output = io.BytesIO()
    
    if formato == "xlsx":
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Casos')
        
        output.seek(0)
        
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=casos_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"}
        )
    
    elif formato == "csv":
        df.to_csv(output, index=False)
        output.seek(0)
        
        return StreamingResponse(
            output,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=casos_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
        )
    
    else:
        raise HTTPException(status_code=400, detail="Formato no soportado. Use 'xlsx' o 'csv'")


# ═══════════════════════════════════════════════════════════
# EXPORTACIÓN MASIVA DE PDFs EN ZIP
# ═══════════════════════════════════════════════════════════

@router.post("/exportar/zip")
async def exportar_casos_zip(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    📦 Exporta PDFs de incapacidades como ZIP desde Google Drive.
    Soporta paginación por lotes de 500.
    
    Body JSON:
    {
      "filtro_fecha": "subida" | "incapacidad",
      "fecha_desde": "2026-01-01",
      "fecha_hasta": "2026-02-15",
      "empresa": "all" | "ELIOT",
      "tipo": "all" | "enfermedad_general",
      "cedulas": "1085043374,39017565",
      "lote": 1  // número de lote (1-indexed), cada lote = 500 PDFs
    }
    """
    import zipfile
    import math
    
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body JSON requerido")
    
    filtro_fecha = body.get("filtro_fecha", "subida")
    fecha_desde_str = body.get("fecha_desde")
    fecha_hasta_str = body.get("fecha_hasta")
    empresa_filtro = body.get("empresa", "all")
    tipo_filtro = body.get("tipo", "all")
    cedulas_raw = body.get("cedulas", "")
    lote = int(body.get("lote", 1))
    
    if lote < 1:
        lote = 1
    
    LOTE_SIZE = 500
    
    # Build query
    query = db.query(Case).join(Employee, Case.employee_id == Employee.id, isouter=True)
    
    # Filtro por empresa
    if empresa_filtro and empresa_filtro != "all":
        company = db.query(Company).filter(Company.nombre == empresa_filtro).first()
        if company:
            query = query.filter(Case.company_id == company.id)
    
    # Filtro por tipo
    if tipo_filtro and tipo_filtro != "all":
        query = query.filter(Case.tipo == tipo_filtro)
    
    # Filtro por cédulas específicas
    if cedulas_raw and cedulas_raw.strip():
        cedulas_list = [c.strip() for c in cedulas_raw.split(",") if c.strip()]
        if cedulas_list:
            query = query.filter(Case.cedula.in_(cedulas_list))
    
    # Filtro por fechas (obligatorio para exportación por lotes)
    if fecha_desde_str:
        try:
            fd = datetime.strptime(fecha_desde_str, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="fecha_desde inválida. Use YYYY-MM-DD")
        if filtro_fecha == "subida":
            query = query.filter(Case.created_at >= fd)
        elif filtro_fecha == "incapacidad":
            query = query.filter(Case.fecha_inicio >= fd)
    
    if fecha_hasta_str:
        try:
            fh = datetime.strptime(fecha_hasta_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        except ValueError:
            raise HTTPException(status_code=400, detail="fecha_hasta inválida. Use YYYY-MM-DD")
        if filtro_fecha == "subida":
            query = query.filter(Case.created_at <= fh)
        elif filtro_fecha == "incapacidad":
            query = query.filter(Case.fecha_inicio <= fh)
    
    # Solo contar los que tienen PDF para paginar correctamente
    query_con_pdf = query.filter(Case.drive_link.isnot(None), Case.drive_link != "")
    total_con_pdf = query_con_pdf.count()
    
    if total_con_pdf == 0:
        raise HTTPException(status_code=404, detail="No se encontraron casos con PDF para esos filtros")
    
    total_lotes = math.ceil(total_con_pdf / LOTE_SIZE)
    
    if lote > total_lotes:
        raise HTTPException(status_code=400, detail=f"Lote {lote} no existe. Total de lotes: {total_lotes}")
    
    # Paginar: offset y limit
    offset = (lote - 1) * LOTE_SIZE
    casos = query_con_pdf.order_by(Case.created_at.desc()).offset(offset).limit(LOTE_SIZE).all()
    
    print(f"📦 Exportación ZIP lote {lote}/{total_lotes}: {len(casos)} casos a descargar (total con PDF: {total_con_pdf})")
    
    # Crear ZIP en memoria
    zip_buffer = io.BytesIO()
    descargados = 0
    errores = 0
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for caso in casos:
            try:
                # Extraer file_id del link de Drive
                drive_id = None
                if "/file/d/" in caso.drive_link:
                    drive_id = caso.drive_link.split("/file/d/")[1].split("/")[0]
                elif "id=" in caso.drive_link:
                    drive_id = caso.drive_link.split("id=")[1].split("&")[0]
                
                if not drive_id:
                    errores += 1
                    continue
                
                # Descargar PDF de Drive
                download_url = f"https://drive.google.com/uc?export=download&id={drive_id}"
                response = requests.get(download_url, timeout=15)
                
                if response.status_code != 200 or len(response.content) < 100:
                    errores += 1
                    continue
                
                # Nombre del archivo: empresa/cedula fechaInicio fechaFin.pdf
                fecha_inicio_str = caso.fecha_inicio.strftime("%d %m %Y") if caso.fecha_inicio else "sin_inicio"
                fecha_fin_str = caso.fecha_fin.strftime("%d %m %Y") if caso.fecha_fin else "sin_fin"
                empresa_nombre = caso.empresa.nombre if caso.empresa else "otra"
                filename = f"{empresa_nombre}/{caso.cedula} {fecha_inicio_str} {fecha_fin_str}.pdf"
                
                zf.writestr(filename, response.content)
                descargados += 1
                
                if descargados % 10 == 0:
                    print(f"   📥 {descargados}/{len(casos)} descargados (lote {lote})...")
                
            except Exception as e:
                print(f"   ❌ Error descargando {caso.serial}: {e}")
                errores += 1
                continue
    
    zip_buffer.seek(0)
    
    print(f"✅ ZIP lote {lote}/{total_lotes} generado: {descargados} PDFs, {errores} errores")
    
    fecha_label = datetime.now().strftime("%Y%m%d_%H%M")
    
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=incapacidades_{fecha_label}_lote{lote}de{total_lotes}.zip",
            "X-Total-Casos": str(total_con_pdf),
            "X-Descargados": str(descargados),
            "X-Errores": str(errores),
            "X-Lote-Actual": str(lote),
            "X-Total-Lotes": str(total_lotes),
            "Access-Control-Expose-Headers": "X-Total-Casos, X-Descargados, X-Errores, X-Lote-Actual, X-Total-Lotes",
        }
    )


@router.post("/exportar/zip/preview")
async def preview_exportar_zip(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    👁️ Preview: muestra cuántos casos se descargarían con esos filtros, SIN descargar.
    Indica si usará ZIP directo (≤31 días, sin cédulas) o carpeta Drive temporal (>31 días o cédulas).
    Mismo body que /exportar/zip.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body JSON requerido")
    
    filtro_fecha = body.get("filtro_fecha", "subida")
    fecha_desde_str = body.get("fecha_desde")
    fecha_hasta_str = body.get("fecha_hasta")
    empresa_filtro = body.get("empresa", "all")
    tipo_filtro = body.get("tipo", "all")
    cedulas_raw = body.get("cedulas", "")
    
    # Calcular días del rango
    dias_rango = 0
    tiene_cedulas = bool(cedulas_raw and cedulas_raw.strip())
    
    if fecha_desde_str and fecha_hasta_str:
        try:
            fd = datetime.strptime(fecha_desde_str, "%Y-%m-%d")
            fh = datetime.strptime(fecha_hasta_str, "%Y-%m-%d")
            dias_rango = (fh - fd).days
        except ValueError:
            pass
    
    # Validar máximo 1 año
    if dias_rango > 365:
        raise HTTPException(status_code=400, detail=f"El rango máximo es 1 año (365 días). Seleccionaste {dias_rango} días.")
    
    # Determinar modo de exportación
    # ZIP: ≤31 días y sin cédulas específicas
    # Drive: >31 días O con cédulas específicas
    if tiene_cedulas or dias_rango > 31:
        modo_export = "drive"  # Carpeta temporal en Drive
    else:
        modo_export = "zip"  # Descarga directa en ZIP por lotes
    
    query = db.query(Case).join(Employee, Case.employee_id == Employee.id, isouter=True)
    
    if empresa_filtro and empresa_filtro != "all":
        company = db.query(Company).filter(Company.nombre == empresa_filtro).first()
        if company:
            query = query.filter(Case.company_id == company.id)
    
    if tipo_filtro and tipo_filtro != "all":
        query = query.filter(Case.tipo == tipo_filtro)
    
    if tiene_cedulas:
        cedulas_list = [c.strip() for c in cedulas_raw.split(",") if c.strip()]
        if cedulas_list:
            query = query.filter(Case.cedula.in_(cedulas_list))
    
    # Filtro por fechas
    if fecha_desde_str:
        try:
            fd = datetime.strptime(fecha_desde_str, "%Y-%m-%d")
        except ValueError:
            fd = None
        if fd:
            if filtro_fecha == "subida":
                query = query.filter(Case.created_at >= fd)
            elif filtro_fecha == "incapacidad":
                query = query.filter(Case.fecha_inicio >= fd)
    if fecha_hasta_str:
        try:
            fh = datetime.strptime(fecha_hasta_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        except ValueError:
            fh = None
        if fh:
            if filtro_fecha == "subida":
                query = query.filter(Case.created_at <= fh)
            elif filtro_fecha == "incapacidad":
                query = query.filter(Case.fecha_inicio <= fh)
    
    import math
    
    total = query.count()
    con_pdf = query.filter(Case.drive_link.isnot(None), Case.drive_link != "").count()
    
    LOTE_SIZE = 500
    total_lotes = max(1, math.ceil(con_pdf / LOTE_SIZE))
    
    # Muestra de los primeros 10
    muestra = query.order_by(Case.created_at.desc()).limit(10).all()
    preview = []
    for c in muestra:
        preview.append({
            "serial": c.serial,
            "cedula": c.cedula,
            "nombre": c.empleado.nombre if c.empleado else c.cedula,
            "empresa": c.empresa.nombre if c.empresa else "N/A",
            "tipo": c.tipo.value if c.tipo else None,
            "fecha_inicio": c.fecha_inicio.strftime("%Y-%m-%d") if c.fecha_inicio else None,
            "created_at": c.created_at.strftime("%Y-%m-%d") if c.created_at else None,
            "tiene_pdf": bool(c.drive_link),
        })
    
    return {
        "ok": True,
        "total_casos": total,
        "con_pdf": con_pdf,
        "sin_pdf": total - con_pdf,
        "lote_size": LOTE_SIZE,
        "total_lotes": total_lotes,
        "se_descargarian": con_pdf,
        "dias_rango": dias_rango,
        "modo_export": modo_export,  # "zip" o "drive"
        "modo_label": "📦 ZIP directo (lotes de 500)" if modo_export == "zip" else "📁 Carpeta temporal en Drive (se elimina en 24h)",
        "muestra": preview,
    }


@router.post("/exportar/historico")
async def exportar_historico_drive(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    📁 Histórico: devuelve links de carpetas de Google Drive
    donde ya están organizadas las incapacidades por año y quincena.
    
    Body JSON:
    {
      "year": 2026,
      "month": 2,        // opcional (1-12), null = todo el año
      "empresa": "all" | "ELIOT"
    }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body JSON requerido")
    
    year = body.get("year", datetime.now().year)
    month = body.get("month")  # None = todo el año, 1-12 = mes específico
    empresa_filtro = body.get("empresa", "all")
    
    # Mapping mes → nombres de quincena en Drive
    MESES_ES = {
        1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
        5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
        9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
    }
    
    try:
        from app.drive_uploader import get_authenticated_service, create_folder_if_not_exists
        service = get_authenticated_service()
        
        # Buscar la carpeta raíz de Incapacidades
        main_query = "name='Incapacidades' and mimeType='application/vnd.google-apps.folder' and 'root' in parents and trashed=false"
        main_results = service.files().list(q=main_query, spaces='drive', fields="files(id, name)").execute()
        main_folders = main_results.get('files', [])
        
        if not main_folders:
            raise HTTPException(status_code=404, detail="No se encontró la carpeta 'Incapacidades' en Google Drive")
        
        main_folder_id = main_folders[0]['id']
        
        # Obtener empresas
        if empresa_filtro and empresa_filtro != "all":
            empresas_buscar = [empresa_filtro]
        else:
            empresas_db = db.query(Company).filter(Company.activa == True).all()
            empresas_buscar = [e.nombre for e in empresas_db]
        
        carpetas = []
        total_archivos = 0
        
        for empresa_nombre in empresas_buscar:
            try:
                # Buscar carpeta de empresa
                emp_query = f"name='{empresa_nombre}' and mimeType='application/vnd.google-apps.folder' and '{main_folder_id}' in parents and trashed=false"
                emp_results = service.files().list(q=emp_query, spaces='drive', fields="files(id, name)").execute()
                emp_folders = emp_results.get('files', [])
                
                if not emp_folders:
                    continue
                
                emp_folder_id = emp_folders[0]['id']
                
                # Buscar carpeta del año
                year_query = f"name='{year}' and mimeType='application/vnd.google-apps.folder' and '{emp_folder_id}' in parents and trashed=false"
                year_results = service.files().list(q=year_query, spaces='drive', fields="files(id, name)").execute()
                year_folders = year_results.get('files', [])
                
                if not year_folders:
                    continue
                
                year_folder_id = year_folders[0]['id']
                
                if month and month in MESES_ES:
                    # ═══ MES ESPECÍFICO: buscar carpetas de quincena ═══
                    mes_nombre = MESES_ES[month]
                    quincenas = [f"Primera_Quincena_{mes_nombre}", f"Segunda_Quincena_{mes_nombre}"]
                    
                    for q_name in quincenas:
                        q_query = f"name='{q_name}' and mimeType='application/vnd.google-apps.folder' and '{year_folder_id}' in parents and trashed=false"
                        q_results = service.files().list(q=q_query, spaces='drive', fields="files(id, name)").execute()
                        q_folders = q_results.get('files', [])
                        
                        if q_folders:
                            q_folder_id = q_folders[0]['id']
                            # Contar items
                            count_query = f"'{q_folder_id}' in parents and trashed=false"
                            count_results = service.files().list(q=count_query, spaces='drive', fields="files(id)", pageSize=1000).execute()
                            num_items = len(count_results.get('files', []))
                            total_archivos += num_items
                            
                            folder_link = f"https://drive.google.com/drive/folders/{q_folder_id}"
                            label = q_name.replace("_", " ")
                            
                            carpetas.append({
                                "empresa": empresa_nombre,
                                "year": year,
                                "month": month,
                                "label": f"{empresa_nombre} — {label}",
                                "folder_id": q_folder_id,
                                "link": folder_link,
                                "items": num_items,
                            })
                else:
                    # ═══ AÑO COMPLETO: link a la carpeta del año ═══
                    count_query = f"'{year_folder_id}' in parents and trashed=false"
                    count_results = service.files().list(q=count_query, spaces='drive', fields="files(id)", pageSize=1000).execute()
                    num_items = len(count_results.get('files', []))
                    total_archivos += num_items
                    
                    folder_link = f"https://drive.google.com/drive/folders/{year_folder_id}"
                    
                    carpetas.append({
                        "empresa": empresa_nombre,
                        "year": year,
                        "month": None,
                        "label": f"{empresa_nombre} — {year}",
                        "folder_id": year_folder_id,
                        "link": folder_link,
                        "items": num_items,
                    })
                
            except Exception as e:
                print(f"   ⚠️ Error buscando carpeta de {empresa_nombre}/{year}: {e}")
                continue
        
        if not carpetas:
            mes_label = f" / {MESES_ES.get(month, month)}" if month else ""
            raise HTTPException(status_code=404, detail=f"No se encontraron carpetas para {year}{mes_label}")
        
        # Contar casos en BD para ese año/mes
        casos_bd = db.query(Case).filter(
            func.extract('year', Case.created_at) == year
        )
        if month:
            casos_bd = casos_bd.filter(func.extract('month', Case.created_at) == month)
        if empresa_filtro and empresa_filtro != "all":
            company = db.query(Company).filter(Company.nombre == empresa_filtro).first()
            if company:
                casos_bd = casos_bd.filter(Case.company_id == company.id)
        
        total_bd = casos_bd.count()
        con_pdf_bd = casos_bd.filter(Case.drive_link.isnot(None), Case.drive_link != "").count()
        
        return {
            "ok": True,
            "year": year,
            "month": month,
            "month_label": MESES_ES.get(month) if month else "Todo el año",
            "empresa": empresa_filtro,
            "carpetas": carpetas,
            "total_carpetas": len(carpetas),
            "total_items_drive": total_archivos,
            "total_casos_bd": total_bd,
            "con_pdf_bd": con_pdf_bd,
            "instrucciones": "Abre el enlace de Drive → Selecciona todos los archivos → Click derecho → Descargar. Google Drive los empaquetará en un ZIP automáticamente.",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error en exportar histórico: {e}")
        raise HTTPException(status_code=500, detail=f"Error accediendo a Google Drive: {str(e)}")


# ══════════════════════════════════════════════════════════════════
# EXPORTAR A CARPETA TEMPORAL DE DRIVE (COPIAS, 24h)
# Para rangos > 1 mes o búsquedas por cédulas
# ══════════════════════════════════════════════════════════════════

@router.post("/exportar/drive")
async def exportar_a_drive_temporal(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    📁 Crea una carpeta temporal en Drive con COPIAS de los PDFs que coinciden con los filtros.
    La carpeta se auto-elimina en 24 horas.
    Ideal para rangos > 1 mes o búsquedas por cédulas.
    
    Body JSON:
    {
      "filtro_fecha": "subida" | "incapacidad",
      "fecha_desde": "2025-06-01",
      "fecha_hasta": "2026-01-31",
      "empresa": "all" | "ELIOT",
      "tipo": "all" | "enfermedad_general",
      "cedulas": "1085043374,39017565"
    }
    
    Limites:
    - Máximo 1 año de rango (365 días)
    - Los archivos son COPIAS, los originales nunca se tocan
    - La carpeta temporal se borra automáticamente en 24 horas
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body JSON requerido")
    
    filtro_fecha = body.get("filtro_fecha", "subida")
    fecha_desde_str = body.get("fecha_desde")
    fecha_hasta_str = body.get("fecha_hasta")
    empresa_filtro = body.get("empresa", "all")
    tipo_filtro = body.get("tipo", "all")
    cedulas_raw = body.get("cedulas", "")
    
    # Validar rango máximo 1 año
    if fecha_desde_str and fecha_hasta_str:
        try:
            fd = datetime.strptime(fecha_desde_str, "%Y-%m-%d")
            fh = datetime.strptime(fecha_hasta_str, "%Y-%m-%d")
            dias_rango = (fh - fd).days
            if dias_rango > 365:
                raise HTTPException(status_code=400, detail=f"El rango máximo es 1 año (365 días). Seleccionaste {dias_rango} días.")
            if dias_rango < 0:
                raise HTTPException(status_code=400, detail="La fecha 'Hasta' debe ser posterior a 'Desde'")
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de fecha inválido. Use YYYY-MM-DD")
    
    # Build query
    query = db.query(Case).join(Employee, Case.employee_id == Employee.id, isouter=True)
    
    if empresa_filtro and empresa_filtro != "all":
        company = db.query(Company).filter(Company.nombre == empresa_filtro).first()
        if company:
            query = query.filter(Case.company_id == company.id)
    
    if tipo_filtro and tipo_filtro != "all":
        query = query.filter(Case.tipo == tipo_filtro)
    
    if cedulas_raw and cedulas_raw.strip():
        cedulas_list = [c.strip() for c in cedulas_raw.split(",") if c.strip()]
        if cedulas_list:
            query = query.filter(Case.cedula.in_(cedulas_list))
    
    if fecha_desde_str:
        fd = datetime.strptime(fecha_desde_str, "%Y-%m-%d")
        if filtro_fecha == "subida":
            query = query.filter(Case.created_at >= fd)
        elif filtro_fecha == "incapacidad":
            query = query.filter(Case.fecha_inicio >= fd)
    
    if fecha_hasta_str:
        fh = datetime.strptime(fecha_hasta_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        if filtro_fecha == "subida":
            query = query.filter(Case.created_at <= fh)
        elif filtro_fecha == "incapacidad":
            query = query.filter(Case.fecha_inicio <= fh)
    
    # Solo casos con PDF
    query_con_pdf = query.filter(Case.drive_link.isnot(None), Case.drive_link != "")
    total_con_pdf = query_con_pdf.count()
    
    if total_con_pdf == 0:
        raise HTTPException(status_code=404, detail="No se encontraron casos con PDF para esos filtros")
    
    casos = query_con_pdf.order_by(Case.created_at.desc()).all()
    
    print(f"📁 Exportación Drive temporal: {len(casos)} PDFs a copiar")
    
    try:
        from app.drive_uploader import get_authenticated_service, create_folder_if_not_exists
        service = get_authenticated_service()
        
        # Buscar o crear carpeta raíz "Exportaciones_Temporales"
        export_root_id = create_folder_if_not_exists(service, "Exportaciones_Temporales")
        
        # Crear carpeta de esta exportación con timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        rango_label = ""
        if fecha_desde_str and fecha_hasta_str:
            rango_label = f"_{fecha_desde_str}_a_{fecha_hasta_str}"
        elif cedulas_raw and cedulas_raw.strip():
            n_ced = len([c for c in cedulas_raw.split(",") if c.strip()])
            rango_label = f"_{n_ced}_cedulas"
        
        export_folder_name = f"export_{timestamp}{rango_label}"
        export_folder_id = create_folder_if_not_exists(service, export_folder_name, export_root_id)
        
        # Copiar cada PDF al folder temporal
        copiados = 0
        errores = 0
        
        for caso in casos:
            try:
                # Extraer file_id del link de Drive
                drive_id = None
                if "/file/d/" in caso.drive_link:
                    drive_id = caso.drive_link.split("/file/d/")[1].split("/")[0]
                elif "id=" in caso.drive_link:
                    drive_id = caso.drive_link.split("id=")[1].split("&")[0]
                
                if not drive_id:
                    errores += 1
                    continue
                
                # Nombre descriptivo para la copia: cedula fechaInicio fechaFin.pdf
                fecha_inicio_str = caso.fecha_inicio.strftime("%d %m %Y") if caso.fecha_inicio else "sin_inicio"
                fecha_fin_str = caso.fecha_fin.strftime("%d %m %Y") if caso.fecha_fin else "sin_fin"
                empresa_nombre = caso.empresa.nombre if caso.empresa else "otra"
                nuevo_nombre = f"{caso.cedula} {fecha_inicio_str} {fecha_fin_str}.pdf"
                
                # COPIAR archivo (no mover) al folder temporal
                copy_metadata = {
                    'name': nuevo_nombre,
                    'parents': [export_folder_id]
                }
                service.files().copy(
                    fileId=drive_id,
                    body=copy_metadata,
                    fields='id'
                ).execute()
                
                copiados += 1
                
                if copiados % 25 == 0:
                    print(f"   📋 {copiados}/{len(casos)} copiados...")
                
            except Exception as e:
                print(f"   ❌ Error copiando {caso.serial}: {e}")
                errores += 1
                continue
        
        export_link = f"https://drive.google.com/drive/folders/{export_folder_id}"
        
        print(f"✅ Carpeta temporal creada: {copiados} PDFs copiados, {errores} errores")
        print(f"   🔗 {export_link}")
        print(f"   ⏰ Se eliminará en 24 horas")
        
        return {
            "ok": True,
            "folder_link": export_link,
            "folder_id": export_folder_id,
            "folder_name": export_folder_name,
            "total_copiados": copiados,
            "total_errores": errores,
            "total_con_pdf": total_con_pdf,
            "expira_en": "24 horas",
            "instrucciones": "Abre el enlace → Selecciona todos (Ctrl+A) → Click derecho → Descargar. Drive genera el ZIP. La carpeta se eliminará automáticamente en 24 horas.",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error creando carpeta temporal: {e}")
        raise HTTPException(status_code=500, detail=f"Error creando carpeta en Drive: {str(e)}")


@router.post("/exportar/drive/limpiar")
async def limpiar_exportaciones_temporales(
    _: bool = Depends(verificar_token_admin)
):
    """
    🗑️ Elimina carpetas de exportación temporales que tengan más de 24 horas.
    Se ejecuta automáticamente, pero también puede llamarse manualmente.
    """
    try:
        from app.drive_uploader import get_authenticated_service
        service = get_authenticated_service()
        
        # Buscar carpeta Exportaciones_Temporales
        exp_query = "name='Exportaciones_Temporales' and mimeType='application/vnd.google-apps.folder' and 'root' in parents and trashed=false"
        exp_results = service.files().list(q=exp_query, spaces='drive', fields="files(id, name)").execute()
        exp_folders = exp_results.get('files', [])
        
        if not exp_folders:
            return {"ok": True, "message": "No existe carpeta Exportaciones_Temporales", "eliminadas": 0}
        
        export_root_id = exp_folders[0]['id']
        
        # Listar subcarpetas
        sub_query = f"'{export_root_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
        sub_results = service.files().list(q=sub_query, spaces='drive', fields="files(id, name, createdTime)", pageSize=100).execute()
        sub_folders = sub_results.get('files', [])
        
        eliminadas = 0
        ahora = datetime.utcnow()
        
        for folder in sub_folders:
            try:
                # Parsear fecha de creación
                created_str = folder.get('createdTime', '')
                if created_str:
                    created = datetime.fromisoformat(created_str.replace('Z', '+00:00')).replace(tzinfo=None)
                    edad_horas = (ahora - created).total_seconds() / 3600
                    
                    if edad_horas >= 24:
                        # Eliminar carpeta y todo su contenido
                        service.files().delete(fileId=folder['id']).execute()
                        eliminadas += 1
                        print(f"   🗑️ Eliminada carpeta temporal: {folder['name']} ({edad_horas:.1f}h)")
            except Exception as e:
                print(f"   ⚠️ Error eliminando {folder.get('name')}: {e}")
        
        return {
            "ok": True,
            "eliminadas": eliminadas,
            "total_revisadas": len(sub_folders),
            "message": f"{eliminadas} carpetas temporales eliminadas" if eliminadas > 0 else "No hay carpetas expiradas",
        }
    except Exception as e:
        print(f"❌ Error limpiando exportaciones: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


def limpiar_exportaciones_temporales_sync():
    """Versión síncrona para llamar desde scheduler"""
    try:
        from app.drive_uploader import get_authenticated_service
        service = get_authenticated_service()
        
        exp_query = "name='Exportaciones_Temporales' and mimeType='application/vnd.google-apps.folder' and 'root' in parents and trashed=false"
        exp_results = service.files().list(q=exp_query, spaces='drive', fields="files(id, name)").execute()
        exp_folders = exp_results.get('files', [])
        
        if not exp_folders:
            return
        
        export_root_id = exp_folders[0]['id']
        sub_query = f"'{export_root_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
        sub_results = service.files().list(q=sub_query, spaces='drive', fields="files(id, name, createdTime)", pageSize=100).execute()
        
        ahora = datetime.utcnow()
        eliminadas = 0
        
        for folder in sub_results.get('files', []):
            try:
                created_str = folder.get('createdTime', '')
                if created_str:
                    created = datetime.fromisoformat(created_str.replace('Z', '+00:00')).replace(tzinfo=None)
                    edad_horas = (ahora - created).total_seconds() / 3600
                    if edad_horas >= 24:
                        service.files().delete(fileId=folder['id']).execute()
                        eliminadas += 1
                        print(f"   🗑️ Eliminada exportación temporal: {folder['name']} ({edad_horas:.1f}h)")
            except Exception:
                pass
        
        if eliminadas > 0:
            print(f"✅ Limpieza exportaciones: {eliminadas} carpetas eliminadas")
    except Exception as e:
        print(f"⚠️ Error en limpieza exportaciones temporales: {e}")


@router.get("/casos/{serial}/pdf")
async def obtener_pdf_caso(
    serial: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """Devuelve el PDF del caso desde Google Drive"""
    
    caso = db.query(Case).filter(Case.serial == serial).first()
    if not caso:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    
    if not caso.drive_link:
        raise HTTPException(status_code=404, detail="Este caso no tiene PDF asociado")
    
    try:
        drive_id = None
        if "/file/d/" in caso.drive_link:
            drive_id = caso.drive_link.split("/file/d/")[1].split("/")[0]
        elif "id=" in caso.drive_link:
            drive_id = caso.drive_link.split("id=")[1].split("&")[0]
        
        if not drive_id:
            raise HTTPException(status_code=400, detail="Link de Drive inválido")
        
        download_url = f"https://drive.google.com/uc?export=download&id={drive_id}"
        
        response = requests.get(download_url, stream=True)
        
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail="Error descargando PDF desde Drive")
        
        return StreamingResponse(
            io.BytesIO(response.content),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename={serial}.pdf",
                "Access-Control-Allow-Origin": "*"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error obteniendo PDF para {serial}: {e}")
        raise HTTPException(status_code=500, detail=f"Error procesando PDF: {str(e)}")

@router.get("/casos/{serial}/pdf/stream")
async def obtener_pdf_stream(
    serial: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    ✅ STREAM DIRECTO DEL PDF DESDE DRIVE - OPTIMIZADO PARA RAILWAY
    - Carga instantánea (< 500ms)
    - Calidad original 100% preservada
    - Optimizado para Railway (timeout 25s)
    - Sin conversión, sin procesamiento
    
    Benchmarks esperados:
    - Fetch desde Drive: 200-400ms
    - Headers: 50ms
    - Respuesta cliente: < 500ms
    - TOTAL: < 1.2s ✅
    """
    
    print(f"📥 [PDF Stream] Iniciando descarga para {serial}...")
    
    caso = db.query(Case).filter(Case.serial == serial).first()
    if not caso or not caso.drive_link:
        print(f"❌ [PDF Stream] Caso no encontrado o sin PDF: {serial}")
        raise HTTPException(status_code=404, detail="Caso o PDF no encontrado")
    
    try:
        # ✅ PASO 1: Extraer file_id
        print(f"   1️⃣ Extrayendo file_id...")
        if '/file/d/' in caso.drive_link:
            file_id = caso.drive_link.split('/file/d/')[1].split('/')[0]
        elif 'id=' in caso.drive_link:
            file_id = caso.drive_link.split('id=')[1].split('&')[0]
        else:
            print(f"   ❌ Link inválido: {caso.drive_link}")
            raise HTTPException(status_code=400, detail="Link de Drive inválido")
        
        print(f"   ✅ File ID: {file_id}")
        
        # ✅ PASO 2: URL de descarga directa
        print(f"   2️⃣ Generando URL de descarga...")
        download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        
        # ✅ PASO 3: Descargar desde Drive con timeout para Railway
        print(f"   3️⃣ Descargando desde Drive (timeout 25s)...")
        
        try:
            # ⚠️ CRÍTICO: Railway timeout es 30s, usamos 25s para seguridad
            response = requests.get(
                download_url,
                stream=True,
                timeout=25  # ✅ IMPORTANTE para Railway
            )
            
            if response.status_code != 200:
                print(f"   ❌ Error HTTP {response.status_code}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Error descargando PDF (HTTP {response.status_code})"
                )
            
            content_type = response.headers.get('content-type', '')
            if 'pdf' not in content_type.lower():
                print(f"   ⚠️ Content-Type inesperado: {content_type}")
            
            print(f"   ✅ Descarga iniciada ({response.headers.get('content-length', 'unknown')} bytes)")
            
        except requests.Timeout:
            print(f"   ❌ TIMEOUT después de 25s - PDF muy grande")
            raise HTTPException(
                status_code=504,
                detail="PDF tardó más de 25s en descargar. Intenta de nuevo."
            )
        except requests.RequestException as e:
            print(f"   ❌ Error de conexión: {str(e)}")
            raise HTTPException(status_code=500, detail="Error conectando con Drive")
        
        # ✅ PASO 4: Retornar stream con headers optimizados
        print(f"   4️⃣ Retornando stream con headers optimizados...")
        
        return StreamingResponse(
            # ✅ IMPORTANTE: chunk_size 16KB para velocidad en Railway
            response.iter_content(chunk_size=16384),
            
            media_type="application/pdf",
            
            headers={
                # Headers básicos
                "Content-Disposition": f"inline; filename={serial}.pdf",
                
                # ✅ CRÍTICO para evitar bloqueos de CORS
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                
                # ✅ CRÍTICO para caché en cliente (evita re-descargas)
                "Cache-Control": "public, max-age=3600",  # 1 hora
                "ETag": f'"{file_id}"',  # Para validar caché
                
                # ✅ CRÍTICO para streaming eficiente
                "Accept-Ranges": "bytes",
                
                # Seguridad
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                
                # Performance
                "X-UA-Compatible": "IE=edge",
            }
        )
        
    except HTTPException:
        raise  # Re-lanzar excepciones HTTP
    
    except Exception as e:
        print(f"   ❌ Error inesperado: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/casos/{serial}/pdf/fast")
async def obtener_pdf_fast(
    serial: str,
    if_none_match: Optional[str] = Header(None),
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    ✅ ENDPOINT OPTIMIZADO 2026 - PDF con caché inteligente
    
    Mejoras vs /pdf/stream:
    - Usa API autenticada de Drive (no URL pública que falla)
    - Soporte ETag: si el cliente tiene caché válido, retorna 304 (0 bytes)
    - Descarga completa en memoria → respuesta sin streaming (más rápido para PDFs < 20MB)
    - Header X-PDF-Modified para invalidación de caché en frontend
    
    Tiempos esperados:
    - Con caché válido (304): <50ms
    - Sin caché (descarga): 1-3s
    - PDF muy grande (>10MB): 3-8s
    """
    
    caso = db.query(Case).filter(Case.serial == serial).first()
    if not caso or not caso.drive_link:
        raise HTTPException(status_code=404, detail="Caso o PDF no encontrado")
    
    try:
        # Extraer file_id
        if '/file/d/' in caso.drive_link:
            file_id = caso.drive_link.split('/file/d/')[1].split('/')[0]
        elif 'id=' in caso.drive_link:
            file_id = caso.drive_link.split('id=')[1].split('&')[0]
        else:
            raise HTTPException(status_code=400, detail="Link de Drive inválido")
        
        # Generar ETag basado en file_id + updated_at del caso
        updated_str = caso.updated_at.isoformat() if caso.updated_at else ""
        import hashlib
        etag_value = hashlib.md5(f"{file_id}:{updated_str}".encode()).hexdigest()
        etag_header = f'"{etag_value}"'
        
        # ✅ CACHÉ: Si cliente tiene la versión actual, retornar 304
        if if_none_match and if_none_match.strip('"') == etag_value:
            from fastapi.responses import Response
            return Response(
                status_code=304,
                headers={
                    "ETag": etag_header,
                    "Cache-Control": "private, max-age=3600",
                    "Access-Control-Allow-Origin": "*",
                }
            )
        
        # ✅ Descargar usando API autenticada (más rápida y confiable)
        try:
            from app.drive_uploader import get_authenticated_service
            service = get_authenticated_service()
            
            # Descargar contenido del archivo
            request_drive = service.files().get_media(fileId=file_id)
            
            pdf_content = io.BytesIO()
            from googleapiclient.http import MediaIoBaseDownload
            downloader = MediaIoBaseDownload(pdf_content, request_drive)
            
            done = False
            while not done:
                _, done = downloader.next_chunk()
            
            pdf_bytes = pdf_content.getvalue()
            print(f"✅ [PDF Fast] {serial}: {len(pdf_bytes)} bytes via API autenticada")
            
        except Exception as drive_api_error:
            # Fallback: URL pública si la API falla
            print(f"⚠️ [PDF Fast] API falló, usando URL pública: {drive_api_error}")
            download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
            response = requests.get(download_url, timeout=25)
            if response.status_code != 200:
                raise HTTPException(status_code=500, detail=f"Error descargando PDF")
            pdf_bytes = response.content
        
        # Retornar PDF completo con headers de caché
        from fastapi.responses import Response
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename={serial}.pdf",
                "Content-Length": str(len(pdf_bytes)),
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                "Access-Control-Expose-Headers": "ETag, X-PDF-Modified, Content-Length",
                "Cache-Control": "private, max-age=3600",
                "ETag": etag_header,
                "X-PDF-Modified": updated_str,
                "X-Content-Type-Options": "nosniff",
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [PDF Fast] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/casos/{serial}/pdf/meta")
async def obtener_pdf_meta(
    serial: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    ✅ Metadatos del PDF sin descargar (para validar caché)
    Retorna ETag y fecha de modificación para que el frontend
    decida si necesita descargar o usar caché local.
    """
    caso = db.query(Case).filter(Case.serial == serial).first()
    if not caso or not caso.drive_link:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    
    if '/file/d/' in caso.drive_link:
        file_id = caso.drive_link.split('/file/d/')[1].split('/')[0]
    elif 'id=' in caso.drive_link:
        file_id = caso.drive_link.split('id=')[1].split('&')[0]
    else:
        file_id = "unknown"
    
    updated_str = caso.updated_at.isoformat() if caso.updated_at else ""
    import hashlib
    etag_value = hashlib.md5(f"{file_id}:{updated_str}".encode()).hexdigest()
    
    return {
        "serial": serial,
        "etag": etag_value,
        "modified": updated_str,
        "has_pdf": bool(caso.drive_link)
    }


@router.post("/casos/{serial}/validar")
async def validar_caso_con_checks(
    serial: str,
    accion: str = Form(...),
    checks: List[str] = Form(default=[]),
    observaciones: str = Form(default=""),
    adjuntos: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    Endpoint unificado para validaciones con SISTEMA HÍBRIDO IA/PLANTILLAS
    Acciones: 'completa', 'incompleta', 'ilegible', 'eps', 'tthh', 'falsa'
    """
    caso = db.query(Case).filter(Case.serial == serial).first()
    if not caso:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    
    empleado = caso.empleado
    # ✅ MAPEAR ACCIÓN A ESTADO
    estado_map = {
        'completa': EstadoCaso.COMPLETA,
        'incompleta': EstadoCaso.INCOMPLETA,
        'ilegible': EstadoCaso.ILEGIBLE,
        'eps': EstadoCaso.EPS_TRANSCRIPCION,
        'tthh': EstadoCaso.DERIVADO_TTHH,
        'falsa': EstadoCaso.DERIVADO_TTHH
    }
    nuevo_estado = estado_map[accion]

    # ✅ INICIALIZAR VARIABLES
    es_reenvio = False
    casos_borrados = []

    # ✅ SI SE APRUEBA COMO COMPLETA Y ES UN REENVÍO
    if nuevo_estado == EstadoCaso.COMPLETA:
        es_reenvio = caso.metadata_form.get('es_reenvio', False) if caso.metadata_form else False
        
        if es_reenvio:
            # ✅ BUSCAR Y BORRAR VERSIONES ANTERIORES INCOMPLETAS
            casos_anteriores = db.query(Case).filter(
                Case.cedula == caso.cedula,
                Case.fecha_inicio == caso.fecha_inicio,
                Case.id != caso.id,  # No borrar el actual
                Case.estado.in_([
                    EstadoCaso.INCOMPLETA,
                    EstadoCaso.ILEGIBLE,
                    EstadoCaso.INCOMPLETA_ILEGIBLE
                ])
            ).all()
            
            for caso_anterior in casos_anteriores:
                print(f"🗑️ Borrando caso anterior incompleto: {caso_anterior.serial}")
                casos_borrados.append(caso_anterior.serial)
                
                # ✅ Intentar archivar en Drive (opcional)
                try:
                    organizer = CaseFileOrganizer()
                    organizer.archivar_caso(caso_anterior)
                    print(f"   ✅ Archivos movidos a carpeta de archivados")
                except Exception as e:
                    print(f"   ⚠️ No se pudieron archivar archivos: {e}")
                
                # ✅ Eliminar registro de BD
                db.delete(caso_anterior)
            
            print(f"✅ Eliminados {len(casos_borrados)} casos anteriores: {casos_borrados}")
        
            # ✅ LIMPIAR METADATA DE REENVÍO
            if caso.metadata_form:
                caso.metadata_form.pop('es_reenvio', None)
                caso.metadata_form.pop('total_reenvios', None)
                caso.metadata_form.pop('caso_original_id', None)
                caso.metadata_form.pop('caso_original_serial', None)
        
        # ✅ Cambiar estado y desbloquear
        caso.estado = EstadoCaso.COMPLETA
        caso.bloquea_nueva = False
        # ✅ RESETEAR CONTADORES DE RECORDATORIOS
        caso.recordatorios_count = 0
        caso.recordatorio_enviado = False
        caso.fecha_recordatorio = None
        
        # ✅ COPIAR A HISTÓRICO + COMPLETAS + ELIMINAR DE INCOMPLETAS
        try:
            from app.drive_manager import IncompleteFileManager
            organizer = CaseFileOrganizer()
            incomplete_mgr_validar = IncompleteFileManager()

            # 1️⃣ Copiar a Histórico (Incapacidades/{Empresa}/{Año}/{Quincena}/{Tipo}/)
            try:
                link_hist = organizer.copiar_a_historico(caso)
                if link_hist:
                    print(f"✅ [{serial}] Copiado a Histórico: {link_hist}")
            except Exception as e:
                print(f"⚠️ [{serial}] Error copiando a Histórico: {e}")

            # 2️⃣ Copiar a Completas
            print(f"📋 Copiando caso {serial} a carpeta Completes...")
            try:
                link_completes = completes_mgr.copiar_caso_a_completes(caso)
                if link_completes:
                    if not caso.metadata_form:
                        caso.metadata_form = {}
                    caso.metadata_form['link_completes'] = link_completes
                    flag_modified(caso, 'metadata_form')
                    print(f"✅ Caso {serial} disponible en Completes: {link_completes}")
            except Exception as e:
                print(f"⚠️ Error copiando a Completes: {e}")

            # 3️⃣ ELIMINAR DE INCOMPLETAS — Búsqueda robusta por serial
            print(f"🗑️ [{serial}] Buscando y eliminando de Incompletas...")
            eliminados_validar = incomplete_mgr_validar.eliminar_de_incompletas_por_serial(serial)
            if eliminados_validar > 0:
                print(f"✅ [{serial}] {eliminados_validar} archivo(s) eliminados de Incompletas")
            else:
                # Fallback por file_id
                if caso.drive_link:
                    import re as re_val
                    match_val = re_val.search(r'/d/([a-zA-Z0-9_-]+)', caso.drive_link)
                    if match_val:
                        fid_val = match_val.group(1)
                        eliminado_id = incomplete_mgr_validar.eliminar_de_incompletas_por_file_id(fid_val)
                        if eliminado_id:
                            print(f"✅ [{serial}] Eliminado de Incompletas por file_id")
                        else:
                            print(f"ℹ️ [{serial}] No estaba en Incompletas")
        except Exception as e:
            print(f"⚠️ Error en manejo de archivos COMPLETA en /validar: {e}")
            import traceback
            traceback.print_exc()
        
        # ✅ REGISTRAR EVENTO para COMPLETA desde /validar
        registrar_evento(
            db, caso.id,
            "validacion_completa",
            actor="Validador",
            estado_anterior="INCOMPLETA",
            estado_nuevo="COMPLETA",
            motivo="Validado como completa vía portal",
            metadata={"checks": checks, "es_reenvio": es_reenvio}
        )
        
        # ✅ ENVIAR NOTIFICACIÓN EMAIL/WHATSAPP para COMPLETA desde /validar
        try:
            nombre_emp = empleado.nombre if empleado else 'Colaborador/a'
            email_completa = get_email_template_universal(
                tipo_email='completa',
                nombre=nombre_emp,
                serial=serial,
                empresa=caso.empresa.nombre if caso.empresa else 'N/A',
                tipo_incapacidad=caso.tipo.value if caso.tipo else 'General',
                telefono=caso.telefono_form or 'N/A',
                email=caso.email_form or '',
                link_drive=caso.drive_link
            )
            
            # Construir mensaje WhatsApp
            wa_msg_completa = None
            if caso.telefono_form:
                try:
                    from app.ia_redactor import redactar_whatsapp_completa
                    wa_msg_completa = redactar_whatsapp_completa(nombre_emp, serial)
                except Exception:
                    wa_msg_completa = (
                        f"✅ *Incapacidad Validada*\n\n"
                        f"Hola {nombre_emp}, tu incapacidad {serial} ha sido validada exitosamente.\n"
                        f"_Automatico por Incapacidades_"
                    )
            
            # Obtener emails de directorio
            emails_dir = obtener_emails_empresa_directorio(
                caso.company_id, db
            ) if caso.company_id else []
            cc_dir = ",".join(emails_dir) if emails_dir else None
            correo_bd_emp = getattr(empleado, 'correo', None) if empleado else None
            
            fechas_str_c = f" ({caso.fecha_inicio.strftime('%d/%m/%Y')} al {caso.fecha_fin.strftime('%d/%m/%Y')})" if caso.fecha_inicio and caso.fecha_fin else ""
            asunto_completa = f"CC {caso.cedula} - {serial}{fechas_str_c} - Validada - {nombre_emp} - {caso.empresa.nombre if caso.empresa else 'N/A'}"
            
            if caso.email_form:
                from app.n8n_notifier import enviar_a_n8n
                enviar_a_n8n(
                    tipo_notificacion='completa',
                    email=caso.email_form,
                    serial=serial,
                    subject=asunto_completa,
                    html_content=email_completa,
                    cc_email=cc_dir,
                    correo_bd=correo_bd_emp,
                    whatsapp=caso.telefono_form,
                    whatsapp_message=wa_msg_completa,
                    drive_link=caso.drive_link
                )
                print(f"✅ [{serial}] Notificación COMPLETA enviada desde /validar → {caso.email_form}")
            else:
                print(f"⚠️ [{serial}] Sin email_form, no se envió notificación")
        except Exception as e:
            print(f"⚠️ [{serial}] Error enviando notificación COMPLETA desde /validar: {e}")
            import traceback
            traceback.print_exc()
        
        # ✅ SINCRONIZAR CON GOOGLE SHEETS para COMPLETA
        try:
            from app.google_sheets_tracker import actualizar_caso_en_sheet, registrar_cambio_estado_sheet
            actualizar_caso_en_sheet(caso, accion="actualizar")
            registrar_cambio_estado_sheet(
                caso,
                estado_anterior="INCOMPLETA",
                estado_nuevo="COMPLETA",
                validador="Sistema",
                observaciones="Validado como completa"
            )
            print(f"✅ [{serial}] Sincronizado con Google Sheets")
        except Exception as e:
            print(f"⚠️ [{serial}] Error sincronizando con Sheets: {e}")

    else:
        # ✅ Si es INCOMPLETA, ILEGIBLE, etc. → bloquea nuevas
        caso.estado = nuevo_estado
        caso.bloquea_nueva = True
        
        # ✅ GUARDAR CHECKS EN METADATA (para sistema de reenvío)
        if checks:
            if not caso.metadata_form:
                caso.metadata_form = {}
            caso.metadata_form['checks_seleccionados'] = checks
            flag_modified(caso, 'metadata_form')
        
        # ✅ BLOQUEAR si es incompleta/ilegible
        if accion in ['incompleta', 'ilegible']:
            caso.bloquea_nueva = True
            print(f"🔒 Caso {serial} BLOQUEADO - Empleado debe reenviar")
        
        db.commit()
        
        # ✅ Mover archivo en Drive según el estado
        if accion in ['incompleta', 'ilegible']:
            # Usar el nuevo gestor de incompletas
            from app.drive_manager import IncompleteFileManager
            incomplete_mgr = IncompleteFileManager()
            
            # Determinar categoría
            motivo_categoria = 'Ilegibles' if 'ilegible' in accion else 'Faltan_Soportes'
            
            if checks:
                checks_str = ' '.join(checks).lower()
                if 'ilegible' in checks_str or 'recortada' in checks_str or 'borrosa' in checks_str:
                    motivo_categoria = 'Ilegibles'
                elif 'eps' in checks_str or 'transcri' in checks_str:
                    motivo_categoria = 'EPS_No_Transcritas'
            
            nuevo_link = incomplete_mgr.mover_a_incompletas(caso, motivo_categoria)
            if nuevo_link:
                caso.drive_link = nuevo_link
                db.commit()
                print(f"✅ Archivo movido a Incompletas/{motivo_categoria}: {nuevo_link}")
        else:
            # Usar el gestor normal para otros estados
            organizer = CaseFileOrganizer()
            nuevo_link = organizer.mover_caso_segun_estado(caso, nuevo_estado.value, observaciones)
            if nuevo_link:
                caso.drive_link = nuevo_link
                db.commit()
                print(f"✅ Archivo movido en Drive: {nuevo_link}")
        
        # Procesar adjuntos si los hay
        adjuntos_paths = []
        if adjuntos:
            for i, adjunto in enumerate(adjuntos):
                temp_path = os.path.join(tempfile.gettempdir(), f"{serial}_adjunto_{i}_{adjunto.filename}")
                with open(temp_path, "wb") as f:
                    contenido = await adjunto.read()
                    f.write(contenido)
                adjuntos_paths.append(temp_path)
        
        # ✅ SISTEMA HÍBRIDO: IA vs Plantillas
        from app.ia_redactor import (
            redactar_email_incompleta, 
            redactar_email_ilegible, 
            redactar_alerta_tthh
        )
        
        contenido_ia = None
        
        # ========== LÓGICA HÍBRIDA ==========
        if accion in ['incompleta', 'ilegible']:
            # ✅ USAR IA para casos complejos
            print(f"🤖 Generando email con IA Claude Haiku para {serial}...")
            
            if accion == 'incompleta':
                contenido_ia = redactar_email_incompleta(
                    empleado.nombre if empleado else 'Colaborador/a',
                    serial,
                    checks,
                    caso.tipo.value if caso.tipo else 'General'
                )
            elif accion == 'ilegible':
                contenido_ia = redactar_email_ilegible(
                    empleado.nombre if empleado else 'Colaborador/a',
                    serial,
                    checks
                )
            
            # Insertar contenido IA en plantilla
            email_empleada = get_email_template_universal(
                tipo_email=accion,
                nombre=empleado.nombre if empleado else 'Colaborador/a',
                serial=serial,
                empresa=caso.empresa.nombre if caso.empresa else 'N/A',
                tipo_incapacidad=caso.tipo.value if caso.tipo else 'General',
                telefono=caso.telefono_form,
                email=caso.email_form,
                link_drive=caso.drive_link,
                checks_seleccionados=checks,
                contenido_ia=contenido_ia  # ✅ IA aquí
            )
            
            # Enviar con formato de asunto actualizado
            estado_label = 'Incompleta' if accion == 'incompleta' else 'Ilegible'
            fechas_str = f" ({caso.fecha_inicio.strftime('%d/%m/%Y')} al {caso.fecha_fin.strftime('%d/%m/%Y')})" if caso.fecha_inicio and caso.fecha_fin else ""
            asunto = f"CC {caso.cedula} - {serial}{fechas_str} - {estado_label} - {empleado.nombre if empleado else 'Colaborador'} - {caso.empresa.nombre if caso.empresa else 'N/A'}"
            # ✅ Construir mensaje WhatsApp con los checks directamente (sin parsear HTML)
            from app.checks_disponibles import CHECKS_DISPONIBLES
            from app.n8n_notifier import _parsear_serial_wa
            _cedula_wa, _fechas_wa = _parsear_serial_wa(serial)
            wa_lineas = []
            wa_emoji = '⚠️'
            wa_titulo = 'Documentacion Incompleta' if accion == 'incompleta' else 'Documento Ilegible'
            _fecha_texto_wa = f" {_fechas_wa}" if _fechas_wa else ""
            wa_lineas.append(f"{wa_emoji} *{wa_titulo}*")
            wa_lineas.append(f"Incapacidad{_fecha_texto_wa}")
            wa_lineas.append("")
            # Motivos desde checks
            motivos_wa = []
            for ck in checks:
                if ck in CHECKS_DISPONIBLES:
                    motivos_wa.append(CHECKS_DISPONIBLES[ck]['label'])
            if motivos_wa:
                wa_lineas.append("*Motivo:*")
                for m in motivos_wa[:5]:
                    wa_lineas.append(f"• {m}")
                wa_lineas.append("")
            # Soportes requeridos
            from app.ia_redactor import DOCUMENTOS_REQUERIDOS
            tipo_val = caso.tipo.value.lower().replace(' ', '_') if caso.tipo else 'enfermedad_general'
            soportes_wa = DOCUMENTOS_REQUERIDOS.get(tipo_val, [])
            if soportes_wa:
                wa_lineas.append("*Soportes requeridos:*")
                for s in soportes_wa[:5]:
                    wa_lineas.append(f"• {s}")
                wa_lineas.append("")
            wa_lineas.append("Enviar en *PDF escaneado*, completo y legible.")
            wa_lineas.append("")
            wa_lineas.append("Subir documentos: https://repogemin.vercel.app/")
            wa_lineas.append("")
            wa_lineas.append("_Automatico por Incapacidades_")
            wa_msg = "\n".join(wa_lineas)

            enviar_email_con_adjuntos(
                caso.email_form,
                asunto,
                email_empleada,
                adjuntos_paths,
                caso=caso,  # ✅ COPIA AUTOMÁTICA
                whatsapp_message=wa_msg
            )
        
        elif accion == 'tthh':
            # ✅ USAR IA para alerta a TTHH
            print(f"🚨 Generando alerta TTHH con IA para {serial}...")
            
            contenido_ia_tthh = redactar_alerta_tthh(
                empleado.nombre if empleado else 'Colaborador/a',
                serial,
                caso.empresa.nombre if caso.empresa else 'N/A',
                checks,
                observaciones
            )
            
            # Email al encargado de presunto fraude (múltiples destinatarios)
            emails_fraude = obtener_emails_presunto_fraude(caso.empresa.nombre if caso.empresa else 'Default', db=db)
            
            email_tthh = get_email_template_universal(
                tipo_email='tthh',
                nombre='Encargado de Presunto Fraude',
                serial=serial,
                empresa=caso.empresa.nombre if caso.empresa else 'N/A',
                tipo_incapacidad=caso.tipo.value if caso.tipo else 'General',
                telefono=caso.telefono_form,
                email=caso.email_form,
                link_drive=caso.drive_link,
                checks_seleccionados=checks,
                contenido_ia=contenido_ia_tthh,  # ✅ IA aquí
                empleado_nombre=empleado.nombre if empleado else 'Colaborador/a'
            )
            
            fechas_str_tthh = f" ({caso.fecha_inicio.strftime('%d/%m/%Y')} al {caso.fecha_fin.strftime('%d/%m/%Y')})" if caso.fecha_inicio and caso.fecha_fin else ""
            asunto_tthh = f"CC {caso.cedula} - {serial}{fechas_str_tthh} - PRESUNTO FRAUDE - {empleado.nombre if empleado else 'Colaborador'} - {caso.empresa.nombre if caso.empresa else 'N/A'}"
            
            # ✅ CORREO 1: Alerta a directorio presunto fraude — CON CC empresa
            import base64 as _b64_fraude
            adjuntos_b64_fraude = []
            for _path in adjuntos_paths:
                if os.path.exists(_path):
                    try:
                        with open(_path, 'rb') as _f:
                            _content = _b64_fraude.b64encode(_f.read()).decode('utf-8')
                            adjuntos_b64_fraude.append({
                                'filename': os.path.basename(_path),
                                'content': _content,
                                'mimetype': 'application/pdf'
                            })
                    except Exception as _e:
                        print(f"⚠️ Error procesando adjunto fraude {_path}: {_e}")
            
            # Obtener CC empresa del directorio
            cc_empresa_fraude = None
            if caso.company_id:
                emails_dir_fraude = obtener_emails_empresa_directorio(caso.company_id, db=db)
                if emails_dir_fraude:
                    cc_empresa_fraude = ",".join(emails_dir_fraude)
            
            for email_dest in emails_fraude:
                enviar_a_n8n(
                    tipo_notificacion='tthh',
                    email=email_dest,
                    serial=serial,
                    subject=asunto_tthh,
                    html_content=email_tthh,
                    cc_email=cc_empresa_fraude,  # ✅ CC empresa (en TODOS va)
                    correo_bd=None,      # ✅ SIN CC empleado
                    whatsapp=None,       # ✅ SIN WhatsApp
                    whatsapp_message=None,
                    adjuntos_base64=adjuntos_b64_fraude,
                    drive_link=caso.drive_link
                )
                print(f"🚨 Presunto fraude enviado a: {email_dest} (CC empresa: {cc_empresa_fraude or 'N/A'})")
            
            # ✅ CORREO 2: Confirmación NORMAL al empleado — CON CC empresa (como cualquier otro correo)
            email_empleada_falsa = get_email_template_universal(
                tipo_email='falsa',
                nombre=empleado.nombre if empleado else 'Colaborador/a',
                serial=serial,
                empresa=caso.empresa.nombre if caso.empresa else 'N/A',
                tipo_incapacidad=caso.tipo.value if caso.tipo else 'General',
                telefono=caso.telefono_form,
                email=caso.email_form,
                link_drive=caso.drive_link
            )
            
            fechas_str_conf = f" ({caso.fecha_inicio.strftime('%d/%m/%Y')} al {caso.fecha_fin.strftime('%d/%m/%Y')})" if caso.fecha_inicio and caso.fecha_fin else ""
            asunto_confirmacion = f"CC {caso.cedula} - {serial}{fechas_str_conf} - Confirmación - {empleado.nombre if empleado else 'Colaborador'} - {caso.empresa.nombre if caso.empresa else 'N/A'}"
            send_html_email(
                caso.email_form,
                asunto_confirmacion,
                email_empleada_falsa,
                caso=caso  # ✅ CC empresa va aquí (normal como cualquier correo)
            )
        
        elif accion in ['completa', 'eps', 'falsa']:
            # ✅ PLANTILLAS ESTÁTICAS (Gratis)
            print(f"📄 Usando plantilla estática para {accion}...")
            
            email_empleada = get_email_template_universal(
                tipo_email=accion,
                nombre=empleado.nombre if empleado else 'Colaborador/a',
                serial=serial,
                empresa=caso.empresa.nombre if caso.empresa else 'N/A',
                tipo_incapacidad=caso.tipo.value if caso.tipo else 'General',
                telefono=caso.telefono_form,
                email=caso.email_form,
                link_drive=caso.drive_link
            )
            
            estado_map_asunto = {
                'completa': 'Validada',
                'eps': 'EPS',
                'falsa': 'Confirmación'
            }
            estado_label = estado_map_asunto.get(accion, 'Actualización')
            fechas_str = f" ({caso.fecha_inicio.strftime('%d/%m/%Y')} al {caso.fecha_fin.strftime('%d/%m/%Y')})" if caso.fecha_inicio and caso.fecha_fin else ""
            asunto = f"CC {caso.cedula} - {serial}{fechas_str} - {estado_label} - {empleado.nombre if empleado else 'Colaborador'} - {caso.empresa.nombre if caso.empresa else 'N/A'}"
            send_html_email(
                caso.email_form,
                asunto,
                email_empleada,
                caso=caso  # ✅ COPIA AUTOMÁTICA
            )
        
        # Limpiar adjuntos temporales
        for temp_file in adjuntos_paths:
            try:
                os.remove(temp_file)
            except:
                pass
        
        # Registrar evento
        registrar_evento(
            db, caso.id, 
            "validacion_con_ia" if contenido_ia else "validacion_estatica",
            actor="Validador",
            estado_anterior=caso.estado.value,
            estado_nuevo=nuevo_estado.value,
            motivo=observaciones,
            metadata={"checks": checks, "usa_ia": bool(contenido_ia)}
        )
        
        # ✅ SINCRONIZAR CON GOOGLE SHEETS
        try:
            from app.google_sheets_tracker import actualizar_caso_en_sheet, registrar_cambio_estado_sheet
            actualizar_caso_en_sheet(caso, accion="actualizar")
            registrar_cambio_estado_sheet(
                caso, 
                estado_anterior=caso.estado.value,
                estado_nuevo=nuevo_estado.value,
                validador="Sistema",
                observaciones=observaciones
            )
            print(f"✅ Caso {serial} sincronizado con Google Sheets")
        except Exception as e:
            print(f"⚠️ Error sincronizando con Sheets: {e}")
    
    # ✅ GUARDAR TODOS LOS CAMBIOS EN BD
    db.commit()
    
    return {
        "status": "ok",
        "serial": serial,
        "accion": accion,
        "checks": checks,
        "nuevo_link": caso.drive_link,
        "usa_ia": bool(contenido_ia),
        "es_reenvio": es_reenvio if nuevo_estado == EstadoCaso.COMPLETA else False,
        "casos_borrados": len(casos_borrados) if nuevo_estado == EstadoCaso.COMPLETA and es_reenvio else 0,
        "mensaje": f"Caso {accion} correctamente"
    }


# ✅ NUEVO: Endpoint para notificación libre con IA
@router.post("/casos/{serial}/notificar-libre")
async def notificar_libre_con_ia(
    serial: str,
    mensaje_personalizado: str = Form(...),
    adjuntos: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    Endpoint para el botón "Extra" - Notificación libre con IA
    El validador escribe un mensaje informal y la IA lo convierte en profesional
    """
    caso = db.query(Case).filter(Case.serial == serial).first()
    if not caso:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    
    empleado = caso.empleado
    
    # ✅ Redactar con IA
    from app.ia_redactor import redactar_mensaje_personalizado
    
    print(f"🤖 Redactando mensaje personalizado con IA para {serial}...")
    
    contenido_ia = redactar_mensaje_personalizado(
        empleado.nombre if empleado else 'Colaborador/a',
        serial,
        mensaje_personalizado
    )
    
    # Procesar adjuntos
    adjuntos_paths = []
    if adjuntos:
        for i, adjunto in enumerate(adjuntos):
            temp_path = os.path.join(tempfile.gettempdir(), f"{serial}_extra_{i}_{adjunto.filename}")
            with open(temp_path, "wb") as f:
                contenido = await adjunto.read()
                f.write(contenido)
            adjuntos_paths.append(temp_path)
    
    # Insertar en plantilla
    email_personalizado = get_email_template_universal(
        tipo_email='extra',
        nombre=empleado.nombre if empleado else 'Colaborador/a',
        serial=serial,
        empresa=caso.empresa.nombre if caso.empresa else 'N/A',
        tipo_incapacidad=caso.tipo.value if caso.tipo else 'General',
        telefono=caso.telefono_form,
        email=caso.email_form,
        link_drive=caso.drive_link,
        contenido_ia=contenido_ia
    )
    
    # Enviar con formato de asunto actualizado
    fechas_str = f" ({caso.fecha_inicio.strftime('%d/%m/%Y')} al {caso.fecha_fin.strftime('%d/%m/%Y')})" if caso.fecha_inicio and caso.fecha_fin else ""
    asunto = f"CC {caso.cedula} - {serial}{fechas_str} - Extra - {empleado.nombre if empleado else 'Colaborador'} - {caso.empresa.nombre if caso.empresa else 'N/A'}"
    enviar_email_con_adjuntos(
        caso.email_form,
        asunto,
        email_personalizado,
        adjuntos_paths,
        caso=caso  # ✅ COPIA AUTOMÁTICA
    )
    
    # Limpiar adjuntos
    for temp_file in adjuntos_paths:
        try:
            os.remove(temp_file)
        except:
            pass
    
    # Registrar evento
    registrar_evento(
        db, caso.id, 
        "notificacion_libre_ia",
        actor="Validador",
        motivo=mensaje_personalizado[:200],  # Primeros 200 caracteres
        metadata={"mensaje_original": mensaje_personalizado}
    )
    
    return {
        "status": "ok",
        "serial": serial,
        "mensaje": "Notificación enviada correctamente"
    }

@router.get("/checks-disponibles/{tipo_incapacidad}")
async def obtener_checks_disponibles_endpoint(
    tipo_incapacidad: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """Endpoint para obtener los checks disponibles según tipo de incapacidad"""
    checks = obtener_checks_por_tipo(tipo_incapacidad)
    
    return {
        "tipo_incapacidad": tipo_incapacidad,
        "checks": checks
    }
# ==================== AGREGAR AL FINAL DE app/validador.py ====================

@router.post("/casos/{serial}/editar-pdf")
async def editar_pdf_caso(
    serial: str,
    request: Request,
    token: str = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db)
):
    """
    ✨ Edita el PDF de un caso con múltiples operaciones
    VERSIÓN OPTIMIZADA - Operaciones rápidas primero
    """
    verificar_token_admin(token)
    
    try:
        datos = await request.json()
        operaciones = datos.get('operaciones', {})
        print(f"📝 Operaciones: {list(operaciones.keys())}")
    except:
        raise HTTPException(status_code=400, detail="Datos inválidos")
    
    caso = db.query(Case).filter(Case.serial == serial).first()
    if not caso or not caso.drive_link:
        raise HTTPException(status_code=404, detail="Caso o PDF no encontrado")
    
    # Extraer file_id de Drive
    if '/file/d/' in caso.drive_link:
        file_id = caso.drive_link.split('/file/d/')[1].split('/')[0]
    elif 'id=' in caso.drive_link:
        file_id = caso.drive_link.split('id=')[1].split('&')[0]
    else:
        raise HTTPException(status_code=400, detail="Link de Drive inválido")
    
    download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    
    import time
    start_time = time.time()
    
    # Descargar PDF
    response = requests.get(download_url, timeout=15)
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Error descargando PDF")
    
    temp_input = os.path.join(tempfile.gettempdir(), f"{serial}_original.pdf")
    temp_output = os.path.join(tempfile.gettempdir(), f"{serial}_edited.pdf")
    
    with open(temp_input, 'wb') as f:
        f.write(response.content)
    
    download_time = time.time() - start_time
    print(f"⬇️ Descarga: {download_time:.2f}s")
    
    try:
        # Usar PyMuPDF directo para operaciones simples (RÁPIDO)
        import fitz
        doc = fitz.open(temp_input)
        modificaciones = []
        
        process_start = time.time()
        
        # PROCESAR OPERACIONES
        for op_type, op_data in operaciones.items():
            
            if op_type == 'rotate':
                # Rotación simple (INSTANTÁNEA con PyMuPDF)
                for item in op_data:
                    page_num = item['page_num']
                    angle = item['angle']
                    page = doc[page_num]
                    current = page.rotation
                    page.set_rotation((current + angle) % 360)
                    modificaciones.append(f"Rotated page {page_num} by {angle}°")
            
            elif op_type == 'delete_pages':
                # Eliminar páginas (RÁPIDO)
                for page_num in sorted(op_data, reverse=True):
                    doc.delete_page(page_num)
                    modificaciones.append(f"Deleted page {page_num}")
            
            elif op_type == 'enhance_quality' or op_type == 'aplicar_filtro' or op_type == 'crop_auto' or op_type == 'deskew':
                # Operaciones PESADAS - usar PDFEditor completo
                doc.close()
                from app.pdf_editor import PDFEditor
                editor = PDFEditor(temp_input)
                
                if op_type == 'enhance_quality':
                    pages = op_data.get('pages', [])
                    scale = op_data.get('scale', 2.5)
                    for page_num in pages:
                        editor.enhance_page_quality(page_num, scale)
                
                elif op_type == 'aplicar_filtro':
                    page_num = op_data.get('page_num', 0)
                    filtro = op_data.get('filtro', 'grayscale')
                    editor.aplicar_filtro_imagen(page_num, filtro)
                
                elif op_type == 'crop_auto':
                    for item in op_data:
                        page_num = item['page_num']
                        margin = item.get('margin', 10)
                        editor.auto_crop_page(page_num, margin)
                
                elif op_type == 'deskew':
                    page_num = op_data.get('page_num', 0)
                    editor.enhance_page_quality(page_num, scale=2.0)
                
                editor.save_changes(temp_output)
                modificaciones = editor.get_modifications_log()
                break  # Salir del loop si usamos PDFEditor
        
        # Si usamos PyMuPDF directo, guardar
        if doc.is_closed == False:
            doc.save(temp_output, garbage=4, deflate=True)
            doc.close()
        
        process_time = time.time() - process_start
        print(f"⚙️ Procesamiento: {process_time:.2f}s")
        
        # Subir a Drive
        upload_start = time.time()
        from app.drive_manager import CaseFileOrganizer
        organizer = CaseFileOrganizer()
        nuevo_link = organizer.actualizar_pdf_editado(caso, temp_output)
        
        upload_time = time.time() - upload_start
        print(f"⬆️ Subida: {upload_time:.2f}s")
        
        if nuevo_link:
            caso.drive_link = nuevo_link
            db.commit()
        
        # Limpiar
        if os.path.exists(temp_input):
            os.remove(temp_input)
        if os.path.exists(temp_output):
            os.remove(temp_output)
        
        total_time = time.time() - start_time
        print(f"✅ Total: {total_time:.2f}s")
        
        return {
            "status": "ok",
            "serial": serial,
            "nuevo_link": nuevo_link,
            "modificaciones": modificaciones,
            "tiempos": {
                "descarga": f"{download_time:.2f}s",
                "procesamiento": f"{process_time:.2f}s",
                "subida": f"{upload_time:.2f}s",
                "total": f"{total_time:.2f}s"
            },
            "mensaje": "PDF editado correctamente"
        }
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
        # Limpiar
        if os.path.exists(temp_input):
            os.remove(temp_input)
        if os.path.exists(temp_output):
            os.remove(temp_output)
        
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    else:
        raise HTTPException(status_code=400, detail="Link de Drive inválido")
    
    download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    response = requests.get(download_url)
    
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Error descargando PDF")
    
    temp_input = os.path.join(tempfile.gettempdir(), f"{serial}_original.pdf")
    temp_output = os.path.join(tempfile.gettempdir(), f"{serial}_edited.pdf")
    
    with open(temp_input, 'wb') as f:
        f.write(response.content)
    
    try:
        editor = PDFEditor(temp_input)
        
        # ✅ PROCESAR OPERACIONES
        for op_type, op_data in operaciones.items():
            if op_type == 'enhance_quality':
                for page_num in op_data.get('pages', []):
                    editor.enhance_page_quality(page_num)
            
            elif op_type == 'rotate':
                for item in op_data:
                    editor.rotate_page(item['page_num'], item['angle'])
            
            elif op_type == 'aplicar_filtro':
                editor.aplicar_filtro_imagen(op_data['page_num'], op_data['filtro'])
            
            elif op_type == 'crop_auto':
                for item in op_data:
                    editor.auto_crop_page(item['page_num'], item.get('margin', 10))
            
            elif op_type == 'deskew':
                page_num = op_data.get('page_num', 0)
                page = editor.doc[page_num]
                mat = fitz.Matrix(2.0, 2.0)
                pix = page.get_pixmap(matrix=mat)
                img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                
                deskewed = editor.auto_deskew(img_array)
                
                from PIL import Image
                img_pil = Image.fromarray(deskewed)
                img_bytes = io.BytesIO()
                img_pil.save(img_bytes, format='PNG')
                img_bytes.seek(0)
                
                rect = page.rect
                page.clean_contents()
                page.insert_image(rect, stream=img_bytes.getvalue())
        
        editor.save_changes(temp_output)
        
        # Subir a Drive
        from app.drive_manager import CaseFileOrganizer
        organizer = CaseFileOrganizer()
        nuevo_link = organizer.actualizar_pdf_editado(caso, temp_output)
        
        if nuevo_link:
            caso.drive_link = nuevo_link
            db.commit()
        
        os.remove(temp_input)
        os.remove(temp_output)
        
        return {
            "status": "ok",
            "serial": serial,
            "nuevo_link": nuevo_link,
            "modificaciones": editor.get_modifications_log(),
            "mensaje": "PDF editado y actualizado en Drive"
        }
    
    except Exception as e:
        if os.path.exists(temp_input):
            os.remove(temp_input)
        if os.path.exists(temp_output):
            os.remove(temp_output)
        raise HTTPException(status_code=500, detail=f"Error editando PDF: {str(e)}")
    """
    Edita el PDF de un caso con múltiples operaciones
    
    Operaciones soportadas:
    - enhance_quality: {page_num: int}
    - rotate: {page_num: int, angle: int}
    - crop_auto: {page_num: int, margin: int}
    - crop_custom: {page_num: int, x: int, y: int, width: int, height: int}
    - reorder: {new_order: [1, 0, 2, ...]}
    - annotate: {page_num: int, type: str, coords: [x1,y1,x2,y2], text: str, color: [r,g,b]}
    - delete_page: {pages: [0, 2, 5]}
    """
    from app.pdf_editor import PDFEditor
    
    caso = db.query(Case).filter(Case.serial == serial).first()
    if not caso or not caso.drive_link:
        raise HTTPException(status_code=404, detail="Caso o PDF no encontrado")
    
    # Extraer file_id y descargar PDF
    if '/file/d/' in caso.drive_link:
        file_id = caso.drive_link.split('/file/d/')[1].split('/')[0]
    elif 'id=' in caso.drive_link:
        file_id = caso.drive_link.split('id=')[1].split('&')[0]
    else:
        raise HTTPException(status_code=400, detail="Link de Drive inválido")
    
    download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    response = requests.get(download_url)
    
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Error descargando PDF")
    
    temp_input = os.path.join(tempfile.gettempdir(), f"{serial}_original.pdf")
    temp_output = os.path.join(tempfile.gettempdir(), f"{serial}_edited.pdf")
    
    with open(temp_input, 'wb') as f:
        f.write(response.content)
    
    try:
        editor = PDFEditor(temp_input)
        
        for op_type, op_data in operaciones.items():
            if op_type == 'enhance_quality':
                for page_num in op_data.get('pages', []):
                    editor.enhance_page_quality(page_num)
            
            elif op_type == 'rotate':
                for item in op_data:
                    editor.rotate_page(item['page_num'], item['angle'])
            
            elif op_type == 'crop_auto':
                for item in op_data:
                    editor.auto_crop_page(item['page_num'], item.get('margin', 10))
            
            elif op_type == 'crop_custom':
                for item in op_data:
                    editor.crop_page_custom(
                        item['page_num'],
                        item['x'], item['y'],
                        item['width'], item['height']
                    )
            
            elif op_type == 'reorder':
                editor.reorder_pages(op_data['new_order'])
            
            elif op_type == 'annotate':
                for item in op_data:
                    color_tuple = tuple(item.get('color', [1, 0, 0]))
                    editor.add_annotation(
                        item['page_num'],
                        item['type'],
                        tuple(item['coords']),
                        item.get('text', ''),
                        color_tuple
                    )
            
            elif op_type == 'delete_page':
                for page_num in sorted(op_data['pages'], reverse=True):
                    editor.delete_page(page_num)
        
        editor.save_changes(temp_output)
        
        # Subir a Drive
        organizer = CaseFileOrganizer()
        nuevo_link = organizer.actualizar_pdf_editado(caso, temp_output)
        
        if nuevo_link:
            caso.drive_link = nuevo_link
            db.commit()
        
        os.remove(temp_input)
        os.remove(temp_output)
        
        return {
            "status": "ok",
            "serial": serial,
            "nuevo_link": nuevo_link,
            "modificaciones": editor.get_modifications_log(),
            "mensaje": "PDF editado y actualizado en Drive"
        }
    
    except Exception as e:
        if os.path.exists(temp_input):
            os.remove(temp_input)
        if os.path.exists(temp_output):
            os.remove(temp_output)
        raise HTTPException(status_code=500, detail=f"Error editando PDF: {str(e)}")

@router.post("/casos/{serial}/crear-adjunto")
async def crear_adjunto_desde_pdf(
    serial: str,
    page_num: int,
    coords: List[int],
    tipo: str = "highlight",
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    Crea una imagen recortada del PDF para adjuntar al email
    Tipos: "highlight" o "preview"
    """
    from app.pdf_editor import PDFAttachmentManager
    
    caso = db.query(Case).filter(Case.serial == serial).first()
    if not caso or not caso.drive_link:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    
    if '/file/d/' in caso.drive_link:
        file_id = caso.drive_link.split('/file/d/')[1].split('/')[0]
    else:
        raise HTTPException(status_code=400, detail="Link inválido")
    
    download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    response = requests.get(download_url)
    
    temp_pdf = os.path.join(tempfile.gettempdir(), f"{serial}_temp.pdf")
    temp_img = os.path.join(tempfile.gettempdir(), f"{serial}_adjunto_{page_num}.png")
    
    with open(temp_pdf, 'wb') as f:
        f.write(response.content)
    
    try:
        manager = PDFAttachmentManager()
        
        if tipo == "highlight":
            manager.create_highlight_image(temp_pdf, page_num, coords, temp_img)
        else:
            manager.create_page_preview(temp_pdf, page_num, temp_img, [coords])
        
        with open(temp_img, 'rb') as f:
            img_data = f.read()
        
        os.remove(temp_pdf)
        os.remove(temp_img)
        
        return StreamingResponse(
            io.BytesIO(img_data),
            media_type="image/png",
            headers={"Content-Disposition": f"attachment; filename={serial}_adjunto.png"}
        )
    
    except Exception as e:
        if os.path.exists(temp_pdf):
            os.remove(temp_pdf)
        if os.path.exists(temp_img):
            os.remove(temp_img)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# ==================== ENDPOINTS PARA MANEJO DE REENVÍOS ====================

@router.get("/casos/{serial}/comparar-versiones")
async def comparar_versiones_reenvio(
    serial: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    Muestra al validador ambas versiones para comparar:
    - Versión incompleta anterior
    - Versión reenviada nueva
    """
    
    caso = db.query(Case).filter(Case.serial == serial).first()
    
    if not caso:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    
    # Verificar si hay reenvíos
    if not caso.metadata_form or 'reenvios' not in caso.metadata_form:
        raise HTTPException(status_code=404, detail="No hay reenvíos para este caso")
    
    reenvios = caso.metadata_form['reenvios']
    ultimo_reenvio = reenvios[-1]
    
    return {
        "serial": serial,
        "empleado": caso.empleado.nombre if caso.empleado else "N/A",
        "empresa": caso.empresa.nombre if caso.empresa else "N/A",
        "cedula": caso.cedula,
        "tipo": caso.tipo.value if caso.tipo else "N/A",
        "version_anterior": {
            "link": caso.drive_link,
            "estado": "INCOMPLETA",
            "fecha": caso.updated_at.isoformat()
        },
        "version_nueva": {
            "link": ultimo_reenvio['link'],
            "estado": ultimo_reenvio['estado'],
            "fecha": ultimo_reenvio['fecha'],
            "archivos": ultimo_reenvio['archivos']
        },
        "total_reenvios": len(reenvios),
        "historial_reenvios": reenvios
    }


@router.post("/casos/{serial}/aprobar-reenvio")
async def aprobar_reenvio(
    serial: str,
    decision: str = Form(...),  # 'aprobar' o 'rechazar'
    motivo: str = Form(default=""),
    checks: List[str] = Form(default=[]),
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    Validador decide si el reenvío es válido:
    - 'aprobar' → Borra incompleta, mueve nueva a Validadas, desbloquea
    - 'rechazar' → Nueva también va a Incompletas, sigue bloqueado
    """
    
    caso = db.query(Case).filter(Case.serial == serial).first()
    
    if not caso:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    
    if not caso.metadata_form or 'reenvios' not in caso.metadata_form:
        raise HTTPException(status_code=400, detail="No hay reenvíos pendientes")
    
    reenvios = caso.metadata_form['reenvios']
    ultimo_reenvio = reenvios[-1]
    
    if decision == 'aprobar':
        # ✅ APROBAR REENVÍO
        
        print(f"✅ Aprobando reenvío de {serial}...")
        
        # 1. Buscar y eliminar versión incompleta de Drive (método robusto)
        from app.drive_manager import IncompleteFileManager
        incomplete_mgr_drive = IncompleteFileManager()
        
        # Método robusto: busca por serial y recorre árbol de carpetas hasta 5 niveles
        eliminados_aprobar = incomplete_mgr_drive.eliminar_de_incompletas_por_serial(serial)
        if eliminados_aprobar > 0:
            print(f"   🗑️ Eliminados {eliminados_aprobar} archivo(s) de Incompletas para {serial}")
        else:
            # Fallback: intentar por file_id del drive_link actual
            if caso.drive_link:
                import re as re_drive
                match_fid = re_drive.search(r'/d/([a-zA-Z0-9_-]+)', caso.drive_link)
                if match_fid:
                    fid = match_fid.group(1)
                    if incomplete_mgr_drive.eliminar_de_incompletas_por_file_id(fid):
                        print(f"   🗑️ Eliminado de Incompletas por file_id: {fid}")
                    else:
                        print(f"   ℹ️ Archivo {fid} no estaba en Incompletas (ya movido o no existe)")
            else:
                print(f"   ℹ️ No se encontró archivo de {serial} en Incompletas")
        
        # 2. Actualizar caso con nueva versión
        caso.drive_link = ultimo_reenvio['link']
        caso.estado = EstadoCaso.COMPLETA
        caso.bloquea_nueva = False  # ✅ DESBLOQUEAR
        # ✅ RESETEAR CONTADORES DE RECORDATORIOS
        caso.recordatorios_count = 0
        caso.recordatorio_enviado = False
        caso.fecha_recordatorio = None
        
        # 3. Actualizar metadata
        ultimo_reenvio['estado'] = 'APROBADO'
        ultimo_reenvio['fecha_aprobacion'] = datetime.now().isoformat()
        ultimo_reenvio['validador_decision'] = 'APROBAR'
        ultimo_reenvio['motivo'] = motivo or "Documentos correctos"
        caso.metadata_form['reenvios'][-1] = ultimo_reenvio
        flag_modified(caso, 'metadata_form')
        
        # 4. Copiar archivo a Completes/{Empresa}/ y a Historico
        from app.drive_manager import CaseFileOrganizer
        organizer = CaseFileOrganizer()
        
        # 4a. Copiar a Completes (carpeta operativa)
        try:
            link_completes = completes_mgr.copiar_caso_a_completes(caso)
            if link_completes:
                if not caso.metadata_form:
                    caso.metadata_form = {}
                caso.metadata_form['link_completes'] = link_completes
                flag_modified(caso, 'metadata_form')
                print(f"   ✅ Archivo copiado a Completes: {link_completes}")
        except Exception as e:
            print(f"   ⚠️ Error copiando a Completes: {e}")
        
        # 4b. Copiar a Historico (Incapacidades/{Empresa}/{Año}/{Quincena}/{Tipo}/)
        try:
            link_historico = organizer.copiar_a_historico(caso)
            if link_historico:
                print(f"   ✅ Archivo copiado a Historico: {link_historico}")
        except Exception as e:
            print(f"   ⚠️ Error copiando a Historico: {e}")
        
        # 5. Registrar evento
        registrar_evento(
            db, caso.id,
            "reenvio_aprobado",
            actor="Validador",
            estado_anterior="INCOMPLETA",
            estado_nuevo="COMPLETA",
            motivo=motivo or "Reenvío aprobado - documentos correctos"
        )
        
        db.commit()
        
        # 6. Enviar email al empleado
        try:
            from app.email_templates import get_email_template_universal
            
            email_aprobacion = get_email_template_universal(
                tipo_email='completa',
                nombre=caso.empleado.nombre if caso.empleado else 'Colaborador/a',
                serial=serial,
                empresa=caso.empresa.nombre if caso.empresa else 'N/A',
                tipo_incapacidad=caso.tipo.value if caso.tipo else 'General',
                telefono=caso.telefono_form,
                email=caso.email_form,
                link_drive=caso.drive_link
            )
            
            asunto = f"✅ Incapacidad Validada - {serial} - {caso.empleado.nombre if caso.empleado else 'N/A'} - {caso.empresa.nombre if caso.empresa else 'N/A'}"
            
            if caso.email_form:
                send_html_email(
                    caso.email_form,
                    asunto,
                    email_aprobacion,
                    caso=caso
                )
                print(f"✅ [{serial}] Notificación reenvío APROBADO enviada → {caso.email_form}")
            else:
                print(f"⚠️ [{serial}] Sin email_form, no se envió notificación de aprobación")
        except Exception as e:
            print(f"⚠️ [{serial}] Error enviando notificación de aprobación: {e}")
            import traceback
            traceback.print_exc()
        
        print(f"✅ Reenvío APROBADO: {serial} - Caso desbloqueado y validado")
        
        # 7. Sincronizar con Sheets
        try:
            from app.google_sheets_tracker import actualizar_caso_en_sheet, registrar_cambio_estado_sheet
            actualizar_caso_en_sheet(caso, accion="actualizar")
            registrar_cambio_estado_sheet(
                caso,
                estado_anterior="INCOMPLETA",
                estado_nuevo="COMPLETA",
                validador="Sistema",
                observaciones="Reenvío aprobado"
            )
        except Exception as e:
            print(f"⚠️ Error sincronizando con Sheets: {e}")
        
        return {
            "success": True,
            "decision": "aprobado",
            "serial": serial,
            "nuevo_estado": "COMPLETA",
            "desbloqueado": True,
            "nuevo_link": caso.drive_link,
            "mensaje": "Reenvío aprobado. Caso validado y desbloqueado."
        }
    
    elif decision == 'rechazar':
        # ❌ RECHAZAR REENVÍO
        
        print(f"❌ Rechazando reenvío de {serial}...")
        
        # 1. Determinar categoría para Incompletas
        motivo_categoria = 'Faltan_Soportes'  # Default
        
        if checks:
            # Determinar categoría según los checks seleccionados
            checks_str = ' '.join(checks).lower()
            if 'ilegible' in checks_str or 'recortada' in checks_str or 'borrosa' in checks_str:
                motivo_categoria = 'Ilegibles'
            elif 'eps' in checks_str or 'transcri' in checks_str:
                motivo_categoria = 'EPS_No_Transcritas'
        elif motivo:
            # Determinar por el motivo escrito
            if 'ilegible' in motivo.lower():
                motivo_categoria = 'Ilegibles'
            elif 'eps' in motivo.lower():
                motivo_categoria = 'EPS_No_Transcritas'
        
        # 2. Mover nueva versión TAMBIÉN a Incompletas
        from app.drive_manager import IncompleteFileManager
        incomplete_mgr = IncompleteFileManager()
        
        # Crear caso temporal con el nuevo link para moverlo
        caso_temp = caso
        caso_temp.drive_link = ultimo_reenvio['link']
        
        nuevo_link_incompleta = incomplete_mgr.mover_a_incompletas(caso_temp, motivo_categoria)
        
        if nuevo_link_incompleta:
            print(f"   📁 Nueva versión movida a Incompletas/{motivo_categoria}")
        
        # 3. Actualizar metadata
        ultimo_reenvio['estado'] = 'RECHAZADO'
        ultimo_reenvio['fecha_rechazo'] = datetime.now().isoformat()
        ultimo_reenvio['validador_decision'] = 'RECHAZAR'
        ultimo_reenvio['motivo_rechazo'] = motivo
        ultimo_reenvio['checks_faltantes'] = checks
        caso.metadata_form['reenvios'][-1] = ultimo_reenvio
        flag_modified(caso, 'metadata_form')
        
        # 4. Mantener bloqueo y estado incompleto
        caso.estado = EstadoCaso.INCOMPLETA
        caso.bloquea_nueva = True  # ✅ SIGUE BLOQUEADO
        
        # 5. Guardar checks en metadata para próximo intento
        if checks:
            caso.metadata_form['checks_seleccionados'] = checks
            flag_modified(caso, 'metadata_form')
        
        # 6. Registrar evento
        registrar_evento(
            db, caso.id,
            "reenvio_rechazado",
            actor="Validador",
            estado_anterior="NUEVO",
            estado_nuevo="INCOMPLETA",
            motivo=motivo or "Reenvío rechazado - documentos aún incompletos",
            metadata={'checks': checks, 'categoria': motivo_categoria}
        )
        
        db.commit()
        
        # 7. Enviar email al empleado con IA
        try:
            from app.email_templates import get_email_template_universal
            from app.ia_redactor import redactar_email_incompleta
            
            print(f"   🤖 Generando email con IA para notificar rechazo...")
            
            contenido_ia = redactar_email_incompleta(
                caso.empleado.nombre if caso.empleado else 'Colaborador/a',
                serial,
                checks,
                caso.tipo.value if caso.tipo else 'General'
            )
            
            email_rechazo = get_email_template_universal(
                tipo_email='incompleta',
                nombre=caso.empleado.nombre if caso.empleado else 'Colaborador/a',
                serial=serial,
                empresa=caso.empresa.nombre if caso.empresa else 'N/A',
                tipo_incapacidad=caso.tipo.value if caso.tipo else 'General',
                telefono=caso.telefono_form,
                email=caso.email_form,
                link_drive=caso.drive_link,
                checks_seleccionados=checks,
                contenido_ia=contenido_ia
            )
            
            asunto = f"❌ Documentos Aún Incompletos - {serial} - {caso.empleado.nombre if caso.empleado else 'N/A'} - {caso.empresa.nombre if caso.empresa else 'N/A'}"
            
            if caso.email_form:
                send_html_email(
                    caso.email_form,
                    asunto,
                    email_rechazo,
                    caso=caso
                )
                print(f"✅ [{serial}] Notificación reenvío RECHAZADO enviada → {caso.email_form}")
            else:
                print(f"⚠️ [{serial}] Sin email_form, no se envió notificación de rechazo")
        except Exception as e:
            print(f"⚠️ [{serial}] Error enviando notificación de rechazo: {e}")
            import traceback
            traceback.print_exc()
        
        print(f"❌ Reenvío RECHAZADO: {serial} - Caso sigue bloqueado")
        
        # 8. Sincronizar con Sheets
        try:
            from app.google_sheets_tracker import actualizar_caso_en_sheet, registrar_cambio_estado_sheet
            actualizar_caso_en_sheet(caso, accion="actualizar")
            registrar_cambio_estado_sheet(
                caso,
                estado_anterior="NUEVO",
                estado_nuevo="INCOMPLETA",
                validador="Sistema",
                observaciones=f"Reenvío rechazado - {motivo_categoria}"
            )
        except Exception as e:
            print(f"⚠️ Error sincronizando con Sheets: {e}")
        
        return {
            "success": True,
            "decision": "rechazado",
            "serial": serial,
            "nuevo_estado": "INCOMPLETA",
            "desbloqueado": False,
            "checks_faltantes": checks,
            "categoria": motivo_categoria,
            "mensaje": "Reenvío rechazado. Documentos aún incompletos. Empleado debe volver a enviar."
        }
    
    else:
        raise HTTPException(status_code=400, detail="Decisión inválida. Use 'aprobar' o 'rechazar'")


@router.get("/casos/{serial}/historial-reenvios")
async def obtener_historial_reenvios(
    serial: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    Obtiene el historial completo de reenvíos de un caso
    """
    
    caso = db.query(Case).filter(Case.serial == serial).first()
    
    if not caso:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    
    if not caso.metadata_form or 'reenvios' not in caso.metadata_form:
        return {
            "serial": serial,
            "tiene_reenvios": False,
            "total_reenvios": 0,
            "historial": []
        }
    
    reenvios = caso.metadata_form['reenvios']
    
    return {
        "serial": serial,
        "tiene_reenvios": True,
        "total_reenvios": len(reenvios),
        "estado_actual": caso.estado.value,
        "bloqueado": caso.bloquea_nueva,
        "historial": reenvios
    }

@router.post("/casos/{serial}/toggle-bloqueo")
async def toggle_bloqueo(
    serial: str,
    accion: str = Form(...),
    motivo: str = Form(default=""),
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    Permite al validador bloquear o desbloquear un caso.
    - accion: 'bloquear' o 'desbloquear'
    - motivo: razón del bloqueo/desbloqueo (opcional)
    """
    
    try:
        print(f"\n🔄 Toggle bloqueo - Serial: {serial}, Acción: {accion}")
        
        caso = db.query(Case).filter(Case.serial == serial).first()
        
        if not caso:
            print(f"❌ Caso no encontrado: {serial}")
            raise HTTPException(status_code=404, detail=f"Caso {serial} no encontrado")
        
        print(f"   Caso actual - Bloqueado: {caso.bloquea_nueva}, Estado: {caso.estado.value if caso.estado else 'N/A'}")
        
        estado_actual = caso.estado.value if caso.estado else 'DESCONOCIDO'
        
        if accion == 'bloquear':
            caso.bloquea_nueva = True
            print(f"   🔒 Bloqueando caso...")
        elif accion == 'desbloquear':
            caso.bloquea_nueva = False
            print(f"   🔓 Desbloqueando caso...")
        else:
            print(f"❌ Acción inválida: {accion}")
            raise HTTPException(status_code=400, detail=f"Acción inválida. Use 'bloquear' o 'desbloquear'. Recibido: {accion}")
        
        # Registrar evento
        try:
            registrar_evento(
                db, caso.id,
                accion=f"{accion}_manual",
                actor="Validador",
                estado_anterior=estado_actual,
                estado_nuevo=estado_actual,
                motivo=motivo or f"Cambio manual de bloqueo"
            )
            print(f"   ✅ Evento registrado")
        except Exception as e:
            print(f"   ⚠️ Error registrando evento: {e}")
        
        # Guardar cambios
        db.commit()
        print(f"   ✅ Cambios guardados en BD")
        
        emoji = '🔒' if accion == 'bloquear' else '🔓'
        print(f"\n{emoji} Caso {serial} {accion}do exitosamente")
        
        return {
            "success": True,
            "serial": serial,
            "mensaje": f"Caso {accion}do exitosamente. Motivo: {motivo or 'Manual'}",
            "bloquea_nueva": caso.bloquea_nueva,
            "estado": caso.estado.value if caso.estado else 'DESCONOCIDO',
            "accion": accion
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error en toggle_bloqueo: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error al procesar bloqueo: {str(e)}")

@router.post("/casos/{serial}/desbloquear")
async def desbloquear_caso_manual(
    serial: str,
    motivo: str = Form(...),
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    Permite al validador desbloquear manualmente un caso
    sin cambiar su estado
    """
    
    caso = db.query(Case).filter(Case.serial == serial).first()
    
    if not caso:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    
    estado_actual = caso.estado.value
    
    # Desbloquear
    caso.bloquea_nueva = False
    
    # Registrar evento
    registrar_evento(
        db, caso.id,
        accion="desbloqueo_manual",
        actor="Validador",
        estado_anterior=estado_actual,
        estado_nuevo=estado_actual,  # Sin cambio de estado
        motivo=motivo
    )
    
    db.commit()
    
    print(f"🔓 Caso {serial} desbloqueado manualmente por validador")
    
    return {
        "success": True,
        "serial": serial,
        "mensaje": f"Caso desbloqueado exitosamente. Motivo: {motivo}"
    }

@router.post("/casos/{serial}/guardar-pdf-editado")
async def guardar_pdf_editado(
    serial: str,
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """
    Guarda un PDF editado en Drive reemplazando el original
    """
    import shutil
    
    caso = db.query(Case).filter(Case.serial == serial).first()
    if not caso:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    
    temp_path = os.path.join(tempfile.gettempdir(), f"{serial}_edited.pdf")
    
    try:
        with open(temp_path, 'wb') as f:
            shutil.copyfileobj(archivo.file, f)
        
        organizer = CaseFileOrganizer()
        nuevo_link = organizer.actualizar_pdf_editado(caso, temp_path)
        
        if nuevo_link:
            caso.drive_link = nuevo_link
            db.commit()
            
            registrar_evento(
                db, caso.id,
                "pdf_editado",
                actor="Validador",
                motivo="PDF editado con herramientas de anotación"
            )
            
            os.remove(temp_path)
            
            return {
                "status": "ok",
                "serial": serial,
                "nuevo_link": nuevo_link,
                "mensaje": "PDF actualizado exitosamente en Drive"
            }
        else:
            raise HTTPException(status_code=500, detail="Error actualizando PDF en Drive")
    
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")



    """
    Endpoint para validar casos: COMPLETA, INCOMPLETA, ILEGIBLE, etc.
    Si es un reenvío que se aprueba como COMPLETA, borra versiones anteriores.
    """
    # ✅ Verificar token admin
    verificar_token_admin(token)
    
    # ✅ Buscar caso
    caso = db.query(Case).filter(Case.serial == serial).first()
    if not caso:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    
    # ✅ Validar acción
    acciones_validas = ['completa', 'incompleta', 'ilegible', 'incompleta_ilegible']
    if accion.lower() not in acciones_validas:
        raise HTTPException(status_code=400, detail=f"Acción inválida. Usa: {', '.join(acciones_validas)}")
    
    # ✅ MAPEAR ACCIÓN A ESTADO
    estado_map = {
        'completa': EstadoCaso.COMPLETA,
        'incompleta': EstadoCaso.INCOMPLETA,
        'ilegible': EstadoCaso.ILEGIBLE,
        'incompleta_ilegible': EstadoCaso.INCOMPLETA_ILEGIBLE
    }
    nuevo_estado = estado_map[accion.lower()]
    
    # ✅ INICIALIZAR VARIABLES
    es_reenvio = False
    casos_borrados = []
    
    # ✅ SI SE APRUEBA COMO COMPLETA Y ES UN REENVÍO
    if nuevo_estado == EstadoCaso.COMPLETA:
        es_reenvio = caso.metadata_form.get('es_reenvio', False) if caso.metadata_form else False
        
        if es_reenvio:
            # ✅ BUSCAR Y BORRAR VERSIONES ANTERIORES INCOMPLETAS
            casos_anteriores = db.query(Case).filter(
                Case.cedula == caso.cedula,
                Case.fecha_inicio == caso.fecha_inicio,
                Case.id != caso.id,  # No borrar el actual
                Case.estado.in_([
                    EstadoCaso.INCOMPLETA,
                    EstadoCaso.ILEGIBLE,
                    EstadoCaso.INCOMPLETA_ILEGIBLE
                ])
            ).all()
            
            for caso_anterior in casos_anteriores:
                print(f"🗑️ Borrando caso anterior incompleto: {caso_anterior.serial}")
                casos_borrados.append(caso_anterior.serial)
                
                # ✅ Intentar archivar en Drive (opcional)
                try:
                    organizer = CaseFileOrganizer()
                    organizer.archivar_caso(caso_anterior)
                    print(f"   ✅ Archivos movidos a carpeta de archivados")
                except Exception as e:
                    print(f"   ⚠️ No se pudieron archivar archivos: {e}")
                
                # ✅ Eliminar registro de BD
                db.delete(caso_anterior)
            
            print(f"✅ Eliminados {len(casos_borrados)} casos anteriores: {casos_borrados}")
        
        # ✅ LIMPIAR METADATA DE REENVÍO
        if caso.metadata_form:
            caso.metadata_form.pop('es_reenvio', None)
            caso.metadata_form.pop('total_reenvios', None)
            caso.metadata_form.pop('caso_original_id', None)
            caso.metadata_form.pop('caso_original_serial', None)
        
        # ✅ Cambiar estado y desbloquear
        caso.estado = EstadoCaso.COMPLETA
        caso.bloquea_nueva = False
    
    else:
        # ✅ Si es INCOMPLETA, ILEGIBLE, etc. → bloquea nuevas
        caso.estado = nuevo_estado
        caso.bloquea_nueva = True
    
    # ✅ GUARDAR MOTIVO SI SE PROPORCIONA
    if motivo:
        if not caso.metadata_form:
            caso.metadata_form = {}
        caso.metadata_form['motivo_validacion'] = motivo
        flag_modified(caso, 'metadata_form')
    
    # ✅ GUARDAR EN BD
    db.commit()
    db.refresh(caso)
    
    # ✅ REGISTRAR EVENTO
    try:
        registrar_evento(
            db, caso.id,
            f"validacion_{accion.lower()}",
            actor="Sistema",
            estado_anterior=None,
            estado_nuevo=nuevo_estado.value,
            motivo=motivo or f"Validado como {accion}",
            metadata={'es_reenvio': es_reenvio if nuevo_estado == EstadoCaso.COMPLETA else None}
        )
    except Exception as e:
        print(f"⚠️ Error registrando evento: {e}")
    
    # ✅ RESPUESTA
    return {
        "status": "ok",
        "serial": serial,
        "estado_nuevo": nuevo_estado.value,
        "es_reenvio": es_reenvio if nuevo_estado == EstadoCaso.COMPLETA else False,
        "casos_borrados": len(casos_borrados) if nuevo_estado == EstadoCaso.COMPLETA and es_reenvio else 0,
        "mensaje": f"Caso {serial} validado como {accion}"
    }

# ========================================
# ??? ELIMINAR INCAPACIDAD COMPLETAMENTE
# ========================================

@router.delete("/casos/{serial}")
async def eliminar_caso_completo(
    serial: str,
    x_admin_token: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Elimina una incapacidad del sistema completamente:
    - Base de datos (caso, documentos, eventos, notas)
    - Google Drive (TODOS los archivos asociados)
    
    Solo para administradores.
    """
    # Validar token de administrador
    admin_token = os.environ.get("ADMIN_TOKEN")
    if not admin_token:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN no configurado en el servidor")
    if not x_admin_token or x_admin_token != admin_token:
        raise HTTPException(status_code=403, detail="Token de administrador requerido")
    
    # Buscar caso en BD
    caso = db.query(Case).filter(Case.serial == serial).first()
    
    if not caso:
        raise HTTPException(status_code=404, detail=f"Caso {serial} no encontrado")
    
    archivos_eliminados = []
    errores = []
    drive_service = None
    
    # Obtener servicio de Drive una sola vez
    try:
        from app.drive_uploader import get_drive_service
        drive_service = get_drive_service()
        print(f"🗑️ Iniciando eliminación completa del caso {serial}")
    except Exception as e:
        errores.append(f"No se pudo conectar a Drive: {str(e)}")
        print(f"⚠️ Error conectando a Drive: {e}")
    
    # Función auxiliar para eliminar archivo de Drive
    def eliminar_archivo_drive(url_or_id):
        if not drive_service or not url_or_id:
            return False
        try:
            # Extraer file_id del link si es URL completa
            if 'drive.google.com' in str(url_or_id):
                file_id_match = re.search(r'/d/([a-zA-Z0-9_-]+)', url_or_id)
                if file_id_match:
                    file_id = file_id_match.group(1)
                else:
                    return False
            else:
                file_id = url_or_id
            
            drive_service.files().delete(fileId=file_id).execute()
            archivos_eliminados.append(file_id)
            print(f"   ✅ Archivo eliminado de Drive: {file_id}")
            return True
        except Exception as e:
            error_msg = f"Error eliminando {url_or_id}: {str(e)}"
            if "File not found" not in str(e):  # Ignorar si ya no existe
                errores.append(error_msg)
            print(f"   ⚠️ {error_msg}")
            return False
    
    try:
        # 1. Eliminar archivo principal de Drive (drive_link del caso)
        if caso.drive_link:
            print(f"   📁 Eliminando archivo principal: {caso.drive_link}")
            eliminar_archivo_drive(caso.drive_link)
        
        # 2. Eliminar todos los documentos asociados de case_documents
        from app.database import CaseDocument
        documentos = db.query(CaseDocument).filter(CaseDocument.case_id == caso.id).all()
        
        for doc in documentos:
            if doc.drive_urls:
                # drive_urls puede ser un JSON con lista de URLs
                urls = doc.drive_urls if isinstance(doc.drive_urls, list) else [doc.drive_urls]
                for url in urls:
                    if url:
                        print(f"   📄 Eliminando documento {doc.doc_tipo}: {url}")
                        eliminar_archivo_drive(url)
        
        # 3. Eliminar archivos de carpeta Incompletas en Drive (si los hay)
        try:
            from app.drive_manager import IncompleteFileManager
            incomplete_mgr = IncompleteFileManager()
            eliminados_inc = incomplete_mgr.eliminar_de_incompletas_por_serial(serial)
            if eliminados_inc > 0:
                print(f"   ✅ {eliminados_inc} archivo(s) eliminados de Incompletas")
        except Exception as e:
            print(f"   ⚠️ Error limpiando Incompletas: {e}")
        
        # 5. Guardar info del caso antes de eliminar (para el response)
        caso_info = {
            "serial": caso.serial,
            "cedula": caso.cedula,
            "tipo": str(caso.tipo.value) if caso.tipo else None,
            "estado": str(caso.estado.value) if caso.estado else None,
            "fecha_inicio": caso.fecha_inicio.isoformat() if caso.fecha_inicio else None,
            "fecha_fin": caso.fecha_fin.isoformat() if caso.fecha_fin else None,
        }
        
        # 6. Eliminar de la base de datos (cascade eliminará documentos, eventos, notas)
        db.delete(caso)
        db.commit()
        print(f"   ✅ Caso {serial} eliminado de BD")
        
        return {
            "status": "ok",
            "mensaje": f"Incapacidad {serial} eliminada completamente del sistema y Drive",
            "caso": caso_info,
            "archivos_eliminados_drive": len(archivos_eliminados),
            "archivos_ids": archivos_eliminados,
            "errores": errores if errores else None
        }
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error eliminando caso {serial}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error al eliminar la incapacidad: {str(e)}"
        )


# ========================================
# 🧹 LIMPIAR TODO EL SISTEMA (ADMIN)
# Elimina TODOS los registros EXCEPTO Employee y Company
# ========================================

@router.delete("/casos-limpiar-todos")
async def limpiar_todos_los_casos(
    contraseña: str = Query(...),
    db: Session = Depends(get_db)
):
    """
    🧹 Elimina TODO el sistema como si nunca se hubiera enviado ninguna incapacidad.
    
    SE ELIMINA:
    - Cases (incapacidades)
    - CaseDocument (documentos adjuntos)
    - CaseEvent (eventos/historial)
    - CaseNote (notas)
    - SearchHistory (historial de búsquedas)
    - CorreoNotificacion (correos adicionales)
    - AlertaEmail (alertas de email)
    - Alerta180Log (logs de alertas 180 días)
    - Archivos en Google Drive
    
    NO SE ELIMINA:
    - Employee (empleados — vienen de Hoja 1 del Excel)
    - Company (empresas — del directorio)
    
    Requiere contraseña correcta. Operación irreversible.
    """
    CONTRASEÑA_MAESTRO = "1085043374"
    
    if contraseña != CONTRASEÑA_MAESTRO:
        raise HTTPException(status_code=403, detail="Contraseña incorrecta")
    
    try:
        resumen = {}
        errores_lista = []
        archivos_eliminados = 0
        
        # 1. Obtener todos los casos para eliminar archivos de Drive
        todos_los_casos = db.query(Case).all()
        total_casos = len(todos_los_casos)
        
        for caso in todos_los_casos:
            try:
                if caso.drive_link:
                    try:
                        file_id_match = re.search(r'/d/([a-zA-Z0-9_-]+)', caso.drive_link)
                        if file_id_match:
                            file_id = file_id_match.group(1)
                            from app.drive_uploader import get_drive_service
                            service = get_drive_service()
                            service.files().delete(fileId=file_id).execute()
                            archivos_eliminados += 1
                    except Exception as e:
                        errores_lista.append(f"Error Drive ({caso.serial}): {str(e)}")
            except Exception as e:
                errores_lista.append(f"Error procesando caso: {str(e)}")
        
        # 2. Eliminar TODAS las tablas relacionadas (orden por dependencias FK)
        #    EXCEPTO Employee y Company que son datos maestros del Excel
        
        # Tablas hijas de Case
        n_docs = db.query(CaseDocument).delete()
        resumen["documentos"] = n_docs
        
        n_events = db.query(CaseEvent).delete()
        resumen["eventos"] = n_events
        
        n_notes = db.query(CaseNote).delete()
        resumen["notas"] = n_notes
        
        # Tablas independientes
        n_search = db.query(SearchHistory).delete()
        resumen["historial_busquedas"] = n_search
        
        try:
            n_correos = db.query(CorreoNotificacion).delete()
            resumen["correos_notificacion"] = n_correos
        except Exception as e:
            errores_lista.append(f"Error CorreoNotificacion: {str(e)}")
            db.rollback()
        
        try:
            n_alertas = db.query(AlertaEmail).delete()
            resumen["alertas_email"] = n_alertas
        except Exception as e:
            errores_lista.append(f"Error AlertaEmail: {str(e)}")
            db.rollback()
        
        try:
            n_logs180 = db.query(Alerta180Log).delete()
            resumen["alertas_180_log"] = n_logs180
        except Exception as e:
            errores_lista.append(f"Error Alerta180Log: {str(e)}")
            db.rollback()
        
        # Tabla principal
        n_cases = db.query(Case).delete()
        resumen["casos"] = n_cases
        
        # 3. Commit todo
        db.commit()
        
        total_eliminados = sum(resumen.values())
        
        print(f"🧹 LIMPIEZA TOTAL completada:")
        for tabla, cantidad in resumen.items():
            print(f"   • {tabla}: {cantidad} registros eliminados")
        print(f"   • Archivos Drive: {archivos_eliminados}")
        
        return {
            "status": "ok",
            "mensaje": f"🧹 Sistema limpiado completamente: {total_eliminados} registros eliminados",
            "detalle": resumen,
            "archivos_drive_eliminados": archivos_eliminados,
            "tablas_preservadas": ["Employee (empleados)", "Company (empresas)"],
            "errores": errores_lista
        }
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error limpiando sistema: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error al limpiar el sistema: {str(e)}"
        )
