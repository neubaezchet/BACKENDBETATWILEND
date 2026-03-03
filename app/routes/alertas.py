"""
RUTAS ALERTAS 180 DÍAS - CRUD emails + disparo automático
==========================================================
Gestión de correos de Talento Humano y alertas automáticas
cuando un empleado se acerca o supera los 180 días (Ley 776/2002).
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, desc
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timedelta
import logging

from app.database import get_db, AlertaEmail, Alerta180Log, Company, Employee, CorreoNotificacion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/alertas-180", tags=["Alertas 180 Días"])


# ═══════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════

class EmailAlertaCreate(BaseModel):
    email: str = Field(..., description="Correo electrónico")
    nombre_contacto: Optional[str] = Field(None, description="Nombre del contacto")
    company_id: Optional[int] = Field(None, description="ID empresa (null = global)")
    tipo: str = Field("talento_humano", description="talento_humano | adicional | admin")

class EmailAlertaUpdate(BaseModel):
    email: Optional[str] = None
    nombre_contacto: Optional[str] = None
    activo: Optional[bool] = None
    tipo: Optional[str] = None


# ═══════════════════════════════════════════════════════════
# 1. CRUD EMAILS DE ALERTA
# ═══════════════════════════════════════════════════════════

@router.get("/emails")
async def listar_emails_alerta(
    empresa: str = Query("all"),
    db: Session = Depends(get_db)
):
    """📧 Lista todos los correos configurados para alertas 180 días"""
    try:
        query = db.query(AlertaEmail)
        
        if empresa != "all":
            company = db.query(Company).filter(Company.nombre == empresa).first()
            if company:
                # Emails de esa empresa + emails globales (company_id IS NULL)
                query = query.filter(
                    (AlertaEmail.company_id == company.id) | (AlertaEmail.company_id.is_(None))
                )
        
        emails = query.order_by(AlertaEmail.created_at.desc()).all()
        
        resultado = []
        for e in emails:
            resultado.append({
                "id": e.id,
                "email": e.email,
                "nombre_contacto": e.nombre_contacto,
                "tipo": e.tipo,
                "activo": e.activo,
                "company_id": e.company_id,
                "empresa": e.empresa.nombre if e.empresa else "Todas (Global)",
                "created_at": e.created_at.isoformat() if e.created_at else None,
            })
        
        return {"ok": True, "total": len(resultado), "emails": resultado}
    except Exception as e:
        logger.error(f"Error listar emails: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/emails")
async def crear_email_alerta(
    data: EmailAlertaCreate,
    db: Session = Depends(get_db)
):
    """➕ Agrega un correo para recibir alertas de 180 días"""
    try:
        # Validar que no exista duplicado
        existente = db.query(AlertaEmail).filter(
            AlertaEmail.email == data.email,
            AlertaEmail.company_id == data.company_id
        ).first()
        
        if existente:
            raise HTTPException(status_code=400, detail=f"El email {data.email} ya está registrado para esta empresa")
        
        # Validar company_id si se proporcionó
        if data.company_id:
            company = db.query(Company).filter(Company.id == data.company_id).first()
            if not company:
                raise HTTPException(status_code=404, detail=f"Empresa con ID {data.company_id} no encontrada")
        
        nuevo = AlertaEmail(
            email=data.email,
            nombre_contacto=data.nombre_contacto,
            company_id=data.company_id,
            tipo=data.tipo,
            activo=True,
        )
        db.add(nuevo)
        db.commit()
        db.refresh(nuevo)
        
        return {
            "ok": True,
            "mensaje": f"Email {data.email} agregado para alertas 180 días",
            "id": nuevo.id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error crear email alerta: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/emails/{email_id}")
async def actualizar_email_alerta(
    email_id: int,
    data: EmailAlertaUpdate,
    db: Session = Depends(get_db)
):
    """✏️ Actualiza un correo de alerta"""
    try:
        registro = db.query(AlertaEmail).filter(AlertaEmail.id == email_id).first()
        if not registro:
            raise HTTPException(status_code=404, detail="Email no encontrado")
        
        if data.email is not None:
            registro.email = data.email
        if data.nombre_contacto is not None:
            registro.nombre_contacto = data.nombre_contacto
        if data.activo is not None:
            registro.activo = data.activo
        if data.tipo is not None:
            registro.tipo = data.tipo
        
        db.commit()
        return {"ok": True, "mensaje": f"Email {registro.email} actualizado"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/emails/{email_id}")
async def eliminar_email_alerta(
    email_id: int,
    db: Session = Depends(get_db)
):
    """🗑️ Elimina un correo de alerta"""
    try:
        registro = db.query(AlertaEmail).filter(AlertaEmail.id == email_id).first()
        if not registro:
            raise HTTPException(status_code=404, detail="Email no encontrado")
        
        email = registro.email
        db.delete(registro)
        db.commit()
        return {"ok": True, "mensaje": f"Email {email} eliminado"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════
# 2. HISTORIAL DE ALERTAS ENVIADAS
# ═══════════════════════════════════════════════════════════

@router.get("/historial")
async def historial_alertas(
    cedula: Optional[str] = None,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db)
):
    """📜 Historial de alertas 180 días enviadas"""
    try:
        query = db.query(Alerta180Log).order_by(desc(Alerta180Log.created_at))
        
        if cedula:
            query = query.filter(Alerta180Log.cedula == cedula)
        
        logs = query.limit(limit).all()
        
        resultado = [{
            "id": l.id,
            "cedula": l.cedula,
            "tipo_alerta": l.tipo_alerta,
            "dias_acumulados": l.dias_acumulados,
            "codigos_cie10": l.cadena_codigos_cie10,
            "emails_enviados": l.emails_enviados,
            "enviado_ok": l.enviado_ok,
            "fecha": l.created_at.isoformat() if l.created_at else None,
        } for l in logs]
        
        return {"ok": True, "total": len(resultado), "historial": resultado}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════
# 3. DISPARO MANUAL DE REVISIÓN DE ALERTAS
# ═══════════════════════════════════════════════════════════

@router.post("/revisar")
async def revisar_alertas_ahora(
    empresa: str = Query("all"),
    db: Session = Depends(get_db)
):
    """
    🔍 Ejecuta revisión manual de alertas 180 días.
    Analiza todos los empleados, detecta los que están cerca de 150/170/180 días
    y envía correos a los destinatarios configurados.
    """
    try:
        from app.services.alerta_180_service import ejecutar_revision_alertas
        resultado = ejecutar_revision_alertas(db, empresa)
        return {"ok": True, **resultado}
    except Exception as e:
        logger.error(f"Error revisión alertas: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════
# 4. EMPRESAS DISPONIBLES (para el dropdown del frontend)
# ═══════════════════════════════════════════════════════════

@router.get("/empresas")
async def listar_empresas(db: Session = Depends(get_db)):
    """📋 Lista empresas disponibles con su cantidad de emails configurados"""
    try:
        empresas = db.query(Company).filter(Company.activa == True).all()
        resultado = []
        for emp in empresas:
            emails_count = db.query(AlertaEmail).filter(
                AlertaEmail.company_id == emp.id,
                AlertaEmail.activo == True
            ).count()
            resultado.append({
                "id": emp.id,
                "nombre": emp.nombre,
                "contacto_email": emp.contacto_email,
                "emails_alerta_configurados": emails_count,
            })
        return {"ok": True, "empresas": resultado}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════
# CORREOS DE NOTIFICACIÓN (Gestión manual/API)
# ═══════════════════════════════════════════════════════════

@router.get("/correos-notificacion")
async def listar_correos_notificacion(
    area: str = Query("all"),
    empresa: str = Query("all"),
    db: Session = Depends(get_db)
):
    """📧 Lista correos de notificación adicionales por área"""
    try:
        query = db.query(CorreoNotificacion)
        
        if area != "all":
            query = query.filter(CorreoNotificacion.area == area)
        
        if empresa != "all":
            company = db.query(Company).filter(Company.nombre == empresa).first()
            if company:
                query = query.filter(
                    (CorreoNotificacion.company_id == company.id) |
                    (CorreoNotificacion.company_id.is_(None))
                )
        
        correos = query.order_by(CorreoNotificacion.area, CorreoNotificacion.nombre_contacto).all()
        
        resultado = []
        for c in correos:
            resultado.append({
                "id": c.id,
                "area": c.area,
                "nombre_contacto": c.nombre_contacto,
                "email": c.email,
                "empresa": c.empresa.nombre if c.empresa else "Todas (Global)",
                "company_id": c.company_id,
                "activo": c.activo,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            })
        
        # Resumen por área
        areas_resumen = {}
        for c in resultado:
            a = c["area"]
            if a not in areas_resumen:
                areas_resumen[a] = {"total": 0, "activos": 0}
            areas_resumen[a]["total"] += 1
            if c["activo"]:
                areas_resumen[a]["activos"] += 1
        
        return {
            "ok": True,
            "total": len(resultado),
            "por_area": areas_resumen,
            "correos": resultado,
            "nota": "Correos adicionales por área. Los CC de empresa están en el directorio (companies.email_copia)"
        }
    except Exception as e:
        logger.error(f"Error listar correos notificación: {e}")
        raise HTTPException(status_code=500, detail=str(e))
