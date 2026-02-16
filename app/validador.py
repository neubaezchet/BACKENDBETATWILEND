"""
Router del Portal de Validadores - IncaNeurobaeza
Endpoints para gestión, validación y búsqueda de casos
"""

from fastapi import APIRouter, Depends, HTTPException, Header, UploadFile, File, Form, Request, Query
from fastapi.responses import StreamingResponse, FileResponse
import requests
import io
import os
import tempfile
import base64
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from pydantic import BaseModel
import pandas as pd

from app.database import (
    get_db, Case, CaseDocument, CaseEvent, CaseNote, Employee, 
    Company, SearchHistory, EstadoCaso, EstadoDocumento, TipoIncapacidad,
    CorreoNotificacion, AlertaEmail, Alerta180Log
)
from app.checks_disponibles import CHECKS_DISPONIBLES, obtener_checks_por_tipo
from app.email_templates import get_email_template_universal
from app.drive_manager import CaseFileOrganizer
from app.n8n_notifier import enviar_a_n8n  # ✅ NUEVO
from app.completes_manager import completes_mgr  # ✅ NUEVO - Sincronización Completes

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

def enviar_email_con_adjuntos(to_email, subject, html_body, adjuntos_paths=[], caso=None, db=None):
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
    cc_empresa = None
    correo_bd = None
    whatsapp = None
    
    if caso:
        if hasattr(caso, 'empresa') and caso.empresa:
            if hasattr(caso.empresa, 'email_copia') and caso.empresa.email_copia:
                cc_empresa = caso.empresa.email_copia
                print(f"📧 CC empresa: {cc_empresa}")
        
        if hasattr(caso, 'empleado') and caso.empleado:
            if hasattr(caso.empleado, 'correo') and caso.empleado.correo:
                correo_bd = caso.empleado.correo
                print(f"📧 CC empleado BD: {correo_bd}")
        
        if hasattr(caso, 'telefono_form') and caso.telefono_form:
            whatsapp = caso.telefono_form
            print(f"📱 WhatsApp: {whatsapp}")
    
    # ✅ El mensaje WhatsApp se genera automáticamente
    whatsapp_message = None
    
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
        whatsapp_message=whatsapp_message,  # ✅ ACTUALIZADO: Enviar mensaje de WhatsApp
        adjuntos_base64=adjuntos_base64
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
    cc_empresa = None
    correo_bd = None
    whatsapp = None
    
    if caso:
        if hasattr(caso, 'empresa') and caso.empresa:
            if hasattr(caso.empresa, 'email_copia') and caso.empresa.email_copia:
                cc_empresa = caso.empresa.email_copia
                print(f"📧 CC empresa: {cc_empresa}")
        
        if hasattr(caso, 'empleado') and caso.empleado:
            if hasattr(caso.empleado, 'correo') and caso.empleado.correo:
                correo_bd = caso.empleado.correo
                print(f"📧 CC empleado BD: {correo_bd}")
        
        if hasattr(caso, 'telefono_form') and caso.telefono_form:
            whatsapp = caso.telefono_form
            print(f"📱 WhatsApp: {whatsapp}")
    
    # ✅ El mensaje WhatsApp se genera automáticamente
    whatsapp_message = None
    
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
        whatsapp_message=whatsapp_message,  # ✅ ACTUALIZADO: Enviar mensaje de WhatsApp
        adjuntos_base64=adjuntos_base64
    )
    
    if resultado:
        print(f"✅ Email enviado: TO={to_email}, CC_EMPRESA={cc_empresa or 'N/A'}, CC_BD={correo_bd or 'N/A'}")
    else:
        print(f"❌ Error enviando email")
    
    return resultado


def obtener_email_tthh(empresa_nombre):
    """Retorna el email de TTHH según la empresa"""
    emails_tthh = {
        'ABC Corp': 'tthh.abc@example.com',
        'XYZ S.A.S': 'tthh.xyz@example.com',
    }
    return emails_tthh.get(empresa_nombre, 'xoblaxbaezaospino@gmail.com')


# ==================== ENDPOINTS ====================

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
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """Lista casos con filtros avanzados"""
    
    query = db.query(Case)
    
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
        
        items.append({
            "id": caso.id,
            "serial": caso.serial,
            "cedula": caso.cedula,
            "nombre": empleado.nombre if empleado else "No registrado",
            "empresa": empresa_obj.nombre if empresa_obj else "Otra empresa",
            "tipo": caso.tipo.value if caso.tipo else None,
            "estado": caso.estado.value,
            "created_at": caso.created_at.isoformat(),
            "bloquea_nueva": caso.bloquea_nueva
        })
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
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
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """Cambia el estado de un caso y envía notificaciones"""
    
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
    
    if nuevo_estado in ["INCOMPLETA", "ILEGIBLE", "INCOMPLETA_ILEGIBLE"]:
        caso.bloquea_nueva = True
    
    db.commit()
    
    return {
        "status": "ok",
        "serial": serial,
        "estado_anterior": estado_anterior,
        "estado_nuevo": nuevo_estado,
        "mensaje": f"Estado actualizado a {nuevo_estado}"
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
    """Obtiene estadísticas para el dashboard"""
    
    query = db.query(Case)
    
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
    """Búsqueda relacional avanzada"""
    
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
    db: Session = Depends(get_db),
    _: bool = Depends(verificar_token_admin)
):
    """Exportar casos a Excel — respeta TODOS los filtros activos"""
    
    query = db.query(Case).join(Employee, Case.employee_id == Employee.id, isouter=True)
    
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
            "Fecha Registro": caso.created_at.strftime("%Y-%m-%d %H:%M")
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
    
    Body JSON:
    {
      "filtro_fecha": "subida" | "incapacidad" | "historico",
      "fecha_desde": "2026-01-01",    // opcional si historico
      "fecha_hasta": "2026-02-15",    // opcional si historico
      "empresa": "all" | "ELIOT",
      "tipo": "all" | "enfermedad_general",
      "cedulas": "1085043374,39017565"  // opcional, separadas por comas
    }
    """
    import zipfile
    
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body JSON requerido")
    
    filtro_fecha = body.get("filtro_fecha", "historico")
    fecha_desde_str = body.get("fecha_desde")
    fecha_hasta_str = body.get("fecha_hasta")
    empresa_filtro = body.get("empresa", "all")
    tipo_filtro = body.get("tipo", "all")
    cedulas_raw = body.get("cedulas", "")
    
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
    
    # Filtro por fechas
    if filtro_fecha != "historico":
        if fecha_desde_str:
            try:
                fd = datetime.strptime(fecha_desde_str, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(status_code=400, detail="fecha_desde inválida. Use YYYY-MM-DD")
        else:
            fd = None
        
        if fecha_hasta_str:
            try:
                fh = datetime.strptime(fecha_hasta_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            except ValueError:
                raise HTTPException(status_code=400, detail="fecha_hasta inválida. Use YYYY-MM-DD")
        else:
            fh = None
        
        if filtro_fecha == "subida":
            if fd:
                query = query.filter(Case.created_at >= fd)
            if fh:
                query = query.filter(Case.created_at <= fh)
        elif filtro_fecha == "incapacidad":
            if fd:
                query = query.filter(Case.fecha_inicio >= fd)
            if fh:
                query = query.filter(Case.fecha_inicio <= fh)
    
    casos = query.order_by(Case.created_at.desc()).all()
    
    if not casos:
        raise HTTPException(status_code=404, detail="No se encontraron casos con esos filtros")
    
    # Limitar a 500 para no sobrecargar
    if len(casos) > 500:
        casos = casos[:500]
    
    print(f"📦 Exportación ZIP: {len(casos)} casos a descargar")
    
    # Crear ZIP en memoria
    zip_buffer = io.BytesIO()
    descargados = 0
    errores = 0
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for caso in casos:
            if not caso.drive_link:
                errores += 1
                continue
            
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
                
                # Nombre del archivo: cedula_serial_fecha.pdf
                emp_nombre = caso.empleado.nombre.replace(" ", "_") if caso.empleado else caso.cedula
                fecha_str = caso.created_at.strftime("%Y%m%d") if caso.created_at else "sin_fecha"
                empresa_nombre = caso.empresa.nombre if caso.empresa else "otra"
                filename = f"{empresa_nombre}/{caso.cedula}_{emp_nombre}_{fecha_str}.pdf"
                
                zf.writestr(filename, response.content)
                descargados += 1
                
                if descargados % 10 == 0:
                    print(f"   📥 {descargados}/{len(casos)} descargados...")
                
            except Exception as e:
                print(f"   ❌ Error descargando {caso.serial}: {e}")
                errores += 1
                continue
    
    zip_buffer.seek(0)
    
    print(f"✅ ZIP generado: {descargados} PDFs, {errores} errores")
    
    fecha_label = datetime.now().strftime("%Y%m%d_%H%M")
    
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=incapacidades_{fecha_label}_{descargados}pdfs.zip",
            "X-Total-Casos": str(len(casos)),
            "X-Descargados": str(descargados),
            "X-Errores": str(errores),
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
    Mismo body que /exportar/zip.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body JSON requerido")
    
    filtro_fecha = body.get("filtro_fecha", "historico")
    fecha_desde_str = body.get("fecha_desde")
    fecha_hasta_str = body.get("fecha_hasta")
    empresa_filtro = body.get("empresa", "all")
    tipo_filtro = body.get("tipo", "all")
    cedulas_raw = body.get("cedulas", "")
    
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
    
    if filtro_fecha != "historico":
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
    
    total = query.count()
    con_pdf = query.filter(Case.drive_link.isnot(None), Case.drive_link != "").count()
    
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
        "limite_maximo": 500,
        "se_descargarian": min(con_pdf, 500),
        "muestra": preview,
    }


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
        
        # ✅ NUEVO: Copiar a carpeta operativa Completes/
        print(f"📋 Copiando caso {serial} a carpeta Completes...")
        try:
            link_completes = completes_mgr.copiar_caso_a_completes(caso)
            if link_completes:
                # Guardar referencia en metadata
                if not caso.metadata_form:
                    caso.metadata_form = {}
                caso.metadata_form['link_completes'] = link_completes
                print(f"✅ Caso {serial} disponible en Completes: {link_completes}")
        except Exception as e:
            print(f"⚠️ Error copiando a Completes: {e}")

    else:
        # ✅ Si es INCOMPLETA, ILEGIBLE, etc. → bloquea nuevas
        caso.estado = nuevo_estado
        caso.bloquea_nueva = True
        
        # ✅ GUARDAR CHECKS EN METADATA (para sistema de reenvío)
        if checks:
            if not caso.metadata_form:
                caso.metadata_form = {}
            caso.metadata_form['checks_seleccionados'] = checks
        
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
            asunto = f"CC {caso.cedula} - {serial} - {estado_label} - {empleado.nombre if empleado else 'Colaborador'} - {caso.empresa.nombre if caso.empresa else 'N/A'}"
            enviar_email_con_adjuntos(
                caso.email_form,
                asunto,
                email_empleada,
                adjuntos_paths,
                caso=caso  # ✅ COPIA AUTOMÁTICA
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
            
            # Email al jefe/TTHH
            email_tthh_destinatario = obtener_email_tthh(caso.empresa.nombre if caso.empresa else 'Default')
            
            email_tthh = get_email_template_universal(
                tipo_email='tthh',
                nombre='Equipo de Talento Humano',
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
            
            asunto_tthh = f"CC {caso.cedula} - {serial} - TTHH - {empleado.nombre if empleado else 'Colaborador'} - {caso.empresa.nombre if caso.empresa else 'N/A'}"
            enviar_email_con_adjuntos(
                email_tthh_destinatario,
                asunto_tthh,
                email_tthh,
                adjuntos_paths
            )
            
            # Email confirmación a la empleada (plantilla estática)
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
            
            asunto_confirmacion = f"CC {caso.cedula} - {serial} - Confirmación - {empleado.nombre if empleado else 'Colaborador'} - {caso.empresa.nombre if caso.empresa else 'N/A'}"
            send_html_email(
                caso.email_form,
                asunto_confirmacion,
                email_empleada_falsa,
                caso=caso  # ✅ COPIA AUTOMÁTICA
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
            asunto = f"CC {caso.cedula} - {serial} - {estado_label} - {empleado.nombre if empleado else 'Colaborador'} - {caso.empresa.nombre if caso.empresa else 'N/A'}"
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
    asunto = f"CC {caso.cedula} - {serial} - Extra - {empleado.nombre if empleado else 'Colaborador'} - {caso.empresa.nombre if caso.empresa else 'N/A'}"
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
        
        # 1. Buscar y eliminar versión incompleta de Drive
        from app.drive_manager import IncompleteFileManager
        incomplete_mgr = IncompleteFileManager()
        
        version_incompleta = incomplete_mgr.buscar_version_incompleta(serial)
        if version_incompleta:
            print(f"   🗑️ Eliminando versión incompleta: {version_incompleta['filename']}")
            incomplete_mgr.eliminar_version_incompleta(version_incompleta['file_id'])
        
        # 2. Actualizar caso con nueva versión
        caso.drive_link = ultimo_reenvio['link']
        caso.estado = EstadoCaso.COMPLETA
        caso.bloquea_nueva = False  # ✅ DESBLOQUEAR
        
        # 3. Actualizar metadata
        ultimo_reenvio['estado'] = 'APROBADO'
        ultimo_reenvio['fecha_aprobacion'] = datetime.now().isoformat()
        ultimo_reenvio['validador_decision'] = 'APROBAR'
        ultimo_reenvio['motivo'] = motivo or "Documentos correctos"
        caso.metadata_form['reenvios'][-1] = ultimo_reenvio
        
        # 4. Mover archivo en Drive a Validadas
        from app.drive_manager import CaseFileOrganizer
        organizer = CaseFileOrganizer()
        nuevo_link = organizer.mover_caso_segun_estado(caso, 'COMPLETA')
        if nuevo_link:
            caso.drive_link = nuevo_link
            print(f"   ✅ Archivo movido a Validadas: {nuevo_link}")
        
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
        
        send_html_email(
            caso.email_form,
            asunto,
            email_aprobacion,
            caso=caso
        )
        
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
        
        # 4. Mantener bloqueo y estado incompleto
        caso.estado = EstadoCaso.INCOMPLETA
        caso.bloquea_nueva = True  # ✅ SIGUE BLOQUEADO
        
        # 5. Guardar checks en metadata para próximo intento
        if checks:
            caso.metadata_form['checks_seleccionados'] = checks
        
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
        
        send_html_email(
            caso.email_form,
            asunto,
            email_rechazo,
            caso=caso
        )
        
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
    - Base de datos
    - Google Drive (todos los archivos con ese serial)
    
    Solo para administradores.
    """
    # Validar token de administrador
    if not x_admin_token or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Token de administrador requerido")
    
    # Buscar caso en BD
    caso = db.query(Case).filter(Case.serial == serial).first()
    
    if not caso:
        raise HTTPException(status_code=404, detail=f"Caso {serial} no encontrado")
    
    archivos_eliminados = []
    errores = []
    
    try:
        # 1. Eliminar archivo de Drive (si existe drive_link)
        if caso.drive_link:
            try:
                # Extraer file_id del link
                file_id_match = re.search(r'/d/([a-zA-Z0-9_-]+)', caso.drive_link)
                if file_id_match:
                    file_id = file_id_match.group(1)
                    
                    from app.drive_uploader import get_drive_service
                    service = get_drive_service()
                    
                    # Eliminar archivo
                    service.files().delete(fileId=file_id).execute()
                    archivos_eliminados.append(file_id)
                    print(f"Archivo eliminado de Drive: {file_id}")
            except Exception as e:
                error_msg = f"Error eliminando archivo de Drive: {str(e)}"
                errores.append(error_msg)
                print(f"Error: {error_msg}")
        
        # 2. Eliminar de la base de datos
        db.delete(caso)
        db.commit()
        print(f"Caso {serial} eliminado de BD")
        
        return {
            "status": "ok",
            "mensaje": f"Incapacidad {serial} eliminada completamente",
            "caso": {
                "serial": caso.serial,
                "cedula": caso.cedula,
                "nombre": caso.nombre,
                "empresa": caso.empresa,
                "tipo": caso.tipo
            },
            "archivos_eliminados": len(archivos_eliminados),
            "errores": errores
        }
        
    except Exception as e:
        db.rollback()
        print(f"Error eliminando caso {serial}: {str(e)}")
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
    - CorreoNotificacion (correos configurados en Hoja 4)
    - AlertaEmail (alertas de email)
    - Alerta180Log (logs de alertas 180 días)
    - Archivos en Google Drive
    
    NO SE ELIMINA:
    - Employee (empleados — vienen de Hoja 1)
    - Company (empresas — vienen de Hoja 2)
    
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
