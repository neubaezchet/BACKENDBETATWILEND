"""
RUTAS DEMO — Solicitudes de acceso al sistema
===============================================
Prefijo: /demo (públicas) + /admin/leads (protegidas)

Endpoints públicos:
  POST /demo/solicitar  → Empresa llena formulario, queda como lead pendiente

Endpoints de admin (superadmin / admin):
  GET  /admin/leads                  → Lista solicitudes con filtros
  GET  /admin/leads/{id}             → Detalle de una solicitud
  POST /admin/leads/{id}/aprobar     → Aprueba, crea Company + token, envía email
  POST /admin/leads/{id}/rechazar    → Rechaza con motivo opcional
"""

import secrets
import logging
import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List

from app.database import get_db, DemoRequest, Company, TenantInvitation, TenantConfig
from app.routes.admin import get_current_user, require_role

logger = logging.getLogger(__name__)

# Dos routers: uno público y uno protegido
demo_router = APIRouter(prefix="/demo", tags=["Demo Requests"])
leads_router = APIRouter(prefix="/admin/leads", tags=["Leads Admin"])

ADMIN_ORIGIN = os.environ.get("ADMIN_ORIGIN", "https://admin-neurobaeza.vercel.app")


# ═══════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════

class SolicitarDemoBody(BaseModel):
    empresa_nombre: str = Field(..., min_length=2, max_length=200)
    nit: Optional[str] = Field(None, max_length=50)
    contacto_nombre: str = Field(..., min_length=2, max_length=200)
    contacto_email: str = Field(..., max_length=300)
    contacto_telefono: Optional[str] = Field(None, max_length=50)
    como_conocio: Optional[str] = Field(None, max_length=200)
    mensaje: Optional[str] = Field(None, max_length=1000)


class RechazarLeadBody(BaseModel):
    notas_internas: Optional[str] = None


class AprobarLeadBody(BaseModel):
    notas_internas: Optional[str] = None


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════

def _serializar_lead(lead: DemoRequest) -> dict:
    return {
        "id": lead.id,
        "empresa_nombre": lead.empresa_nombre,
        "nit": lead.nit,
        "contacto_nombre": lead.contacto_nombre,
        "contacto_email": lead.contacto_email,
        "contacto_telefono": lead.contacto_telefono,
        "como_conocio": lead.como_conocio,
        "mensaje": lead.mensaje,
        "estado": lead.estado,
        "notas_internas": lead.notas_internas,
        "aprobado_por": lead.aprobado_por,
        "company_id": lead.company_id,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
    }


def _enviar_email_aprobacion(contacto_email: str, contacto_nombre: str, empresa_nombre: str, link: str):
    """Envía email de aprobación con el link de registro al representante de la empresa."""
    try:
        from app.email_service import enviar_email_simple
        asunto = f"¡Tu acceso a NeuroBareza está listo, {contacto_nombre}!"
        cuerpo = f"""
Hola {contacto_nombre},

Nos complace informarte que tu solicitud de acceso para **{empresa_nombre}** ha sido aprobada.

Puedes completar el registro de tu empresa haciendo clic en el siguiente enlace:

{link}

**Importante:** Este enlace es de un solo uso y expirará en 7 días.

Si tienes alguna pregunta, no dudes en contactarnos.

Saludos,
El equipo de NeuroBareza
        """.strip()

        enviar_email_simple(
            destinatario=contacto_email,
            asunto=asunto,
            cuerpo_texto=cuerpo,
        )
        logger.info(f"✅ Email de aprobación enviado a {contacto_email}")
    except Exception as e:
        logger.warning(f"⚠️ No se pudo enviar email de aprobación a {contacto_email}: {e}")


def _enviar_email_rechazo(contacto_email: str, contacto_nombre: str, empresa_nombre: str, notas: str):
    """Notifica al solicitante que su solicitud fue rechazada."""
    try:
        from app.email_service import enviar_email_simple
        asunto = f"Actualización sobre tu solicitud — {empresa_nombre}"
        cuerpo = f"""
Hola {contacto_nombre},

Hemos revisado tu solicitud de acceso para **{empresa_nombre}**.

Lamentablemente, en este momento no podemos aprobar el acceso.
{f'Motivo: {notas}' if notas else ''}

Si crees que esto es un error o tienes más información, puedes volver a contactarnos.

Saludos,
El equipo de NeuroBareza
        """.strip()

        enviar_email_simple(
            destinatario=contacto_email,
            asunto=asunto,
            cuerpo_texto=cuerpo,
        )
    except Exception as e:
        logger.warning(f"⚠️ No se pudo enviar email de rechazo a {contacto_email}: {e}")


# ═══════════════════════════════════════════════════════════
# ENDPOINT PÚBLICO: POST /demo/solicitar
# ═══════════════════════════════════════════════════════════

@demo_router.post("/solicitar")
async def solicitar_demo(
    body: SolicitarDemoBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Endpoint público: registra una solicitud de demo.
    No requiere autenticación. Queda en estado 'pendiente'.
    """
    # Verificar si ya existe una solicitud pendiente del mismo email
    existente = db.query(DemoRequest).filter(
        DemoRequest.contacto_email == body.contacto_email,
        DemoRequest.estado == "pendiente",
    ).first()

    if existente:
        return {
            "ok": True,
            "mensaje": "Ya tenemos una solicitud tuya en revisión. Te contactaremos pronto.",
            "id": existente.id,
        }

    lead = DemoRequest(
        empresa_nombre=body.empresa_nombre,
        nit=body.nit,
        contacto_nombre=body.contacto_nombre,
        contacto_email=body.contacto_email,
        contacto_telefono=body.contacto_telefono,
        como_conocio=body.como_conocio,
        mensaje=body.mensaje,
        estado="pendiente",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    logger.info(f"📝 Nueva solicitud de demo: {body.empresa_nombre} ({body.contacto_email})")

    return {
        "ok": True,
        "mensaje": "¡Solicitud recibida! Revisaremos tu información y te contactaremos en las próximas 24 horas.",
        "id": lead.id,
    }


# ═══════════════════════════════════════════════════════════
# ENDPOINT ADMIN: GET /admin/leads
# ═══════════════════════════════════════════════════════════

@leads_router.get("/")
async def listar_leads(
    estado: Optional[str] = Query(None, description="pendiente | aprobado | rechazado"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    user=Depends(require_role("superadmin", "admin")),
    db: Session = Depends(get_db),
):
    """Lista todas las solicitudes de demo con filtros opcionales."""
    query = db.query(DemoRequest)
    if estado:
        query = query.filter(DemoRequest.estado == estado)
    query = query.order_by(DemoRequest.created_at.desc())

    total = query.count()
    leads = query.offset(offset).limit(limit).all()

    # Conteos por estado
    pendientes = db.query(DemoRequest).filter(DemoRequest.estado == "pendiente").count()
    aprobados = db.query(DemoRequest).filter(DemoRequest.estado == "aprobado").count()
    rechazados = db.query(DemoRequest).filter(DemoRequest.estado == "rechazado").count()

    return {
        "ok": True,
        "total": total,
        "stats": {"pendientes": pendientes, "aprobados": aprobados, "rechazados": rechazados},
        "leads": [_serializar_lead(l) for l in leads],
    }


# ═══════════════════════════════════════════════════════════
# ENDPOINT ADMIN: GET /admin/leads/{id}
# ═══════════════════════════════════════════════════════════

@leads_router.get("/{lead_id}")
async def detalle_lead(
    lead_id: int,
    user=Depends(require_role("superadmin", "admin")),
    db: Session = Depends(get_db),
):
    lead = db.query(DemoRequest).filter(DemoRequest.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    return {"ok": True, "lead": _serializar_lead(lead)}


# ═══════════════════════════════════════════════════════════
# ENDPOINT ADMIN: POST /admin/leads/{id}/aprobar
# ═══════════════════════════════════════════════════════════

@leads_router.post("/{lead_id}/aprobar")
async def aprobar_lead(
    lead_id: int,
    body: AprobarLeadBody,
    background_tasks: BackgroundTasks,
    user=Depends(require_role("superadmin", "admin")),
    db: Session = Depends(get_db),
):
    """
    Aprueba una solicitud de demo:
    1. Crea la Company en BD
    2. Crea TenantInvitation con token de 7 días
    3. Envía email con el link de registro al contacto
    """
    lead = db.query(DemoRequest).filter(DemoRequest.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    if lead.estado != "pendiente":
        raise HTTPException(
            status_code=400,
            detail=f"Esta solicitud ya fue procesada (estado: {lead.estado})"
        )

    # 1. Crear o recuperar la Company
    company = db.query(Company).filter(Company.nombre == lead.empresa_nombre).first()
    if not company:
        company = Company(
            nombre=lead.empresa_nombre,
            nit=lead.nit,
            contacto_email=lead.contacto_email,
            contacto_telefono=lead.contacto_telefono,
            activa=True,
        )
        db.add(company)
        db.flush()  # Para obtener el ID antes del commit

    # 2. Crear token de invitación (7 días)
    token = secrets.token_urlsafe(64)
    expires_at = datetime.utcnow() + timedelta(days=7)

    invitacion = TenantInvitation(
        token=token,
        company_id=company.id,
        creado_por=user.username,
        expires_at=expires_at,
        demo_request_id=lead.id,
    )
    db.add(invitacion)

    # 3. Actualizar el lead
    lead.estado = "aprobado"
    lead.aprobado_por = user.username
    lead.company_id = company.id
    if body.notas_internas:
        lead.notas_internas = body.notas_internas

    db.commit()

    # Link de registro self-service
    link_registro = f"{ADMIN_ORIGIN}/registro?token={token}"

    # 4. Enviar email en background
    background_tasks.add_task(
        _enviar_email_aprobacion,
        lead.contacto_email,
        lead.contacto_nombre,
        lead.empresa_nombre,
        link_registro,
    )

    logger.info(
        f"✅ Lead aprobado: {lead.empresa_nombre} → company_id={company.id} "
        f"| token generado | aprobado por {user.username}"
    )

    return {
        "ok": True,
        "mensaje": f"Empresa '{lead.empresa_nombre}' aprobada. Email enviado a {lead.contacto_email}.",
        "company_id": company.id,
        "link_registro": link_registro,
        "token": token,
        "expires_at": expires_at.isoformat(),
        "expires_label": expires_at.strftime("%d %b %Y a las %H:%M UTC"),
    }


# ═══════════════════════════════════════════════════════════
# ENDPOINT ADMIN: POST /admin/leads/{id}/rechazar
# ═══════════════════════════════════════════════════════════

@leads_router.post("/{lead_id}/rechazar")
async def rechazar_lead(
    lead_id: int,
    body: RechazarLeadBody,
    background_tasks: BackgroundTasks,
    user=Depends(require_role("superadmin", "admin")),
    db: Session = Depends(get_db),
):
    """Rechaza una solicitud de demo con motivo opcional."""
    lead = db.query(DemoRequest).filter(DemoRequest.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    if lead.estado != "pendiente":
        raise HTTPException(
            status_code=400,
            detail=f"Esta solicitud ya fue procesada (estado: {lead.estado})"
        )

    lead.estado = "rechazado"
    lead.aprobado_por = user.username
    if body.notas_internas:
        lead.notas_internas = body.notas_internas

    db.commit()

    # Email de notificación en background
    background_tasks.add_task(
        _enviar_email_rechazo,
        lead.contacto_email,
        lead.contacto_nombre,
        lead.empresa_nombre,
        body.notas_internas or "",
    )

    logger.info(f"❌ Lead rechazado: {lead.empresa_nombre} | por {user.username}")

    return {
        "ok": True,
        "mensaje": f"Solicitud de '{lead.empresa_nombre}' rechazada.",
    }


# ═══════════════════════════════════════════════════════════
# ENDPOINT ADMIN: POST /admin/leads/crear-empresa
# Crea empresa + invitación directamente sin pasar por lead
# ═══════════════════════════════════════════════════════════

class CrearEmpresaDirectaBody(BaseModel):
    empresa_nombre: str = Field(..., min_length=2, max_length=200)
    nit: Optional[str] = Field(None, max_length=50)
    contacto_email: str = Field(..., max_length=300)
    contacto_telefono: Optional[str] = Field(None, max_length=50)


@leads_router.post("/crear-empresa")
async def crear_empresa_directa(
    body: CrearEmpresaDirectaBody,
    user=Depends(require_role("superadmin", "admin")),
    db: Session = Depends(get_db),
):
    """
    Crea una empresa + token de invitación directamente (sin lead previo).
    Útil para agregar clientes manualmente desde el admin.
    """
    # Evitar duplicados por nombre
    existente = db.query(Company).filter(Company.nombre == body.empresa_nombre).first()
    if existente:
        raise HTTPException(
            status_code=400,
            detail=f"Ya existe una empresa con el nombre '{body.empresa_nombre}' (id={existente.id})"
        )

    # Crear la empresa
    company = Company(
        nombre=body.empresa_nombre,
        nit=body.nit,
        contacto_email=body.contacto_email,
        contacto_telefono=body.contacto_telefono,
        activa=True,
    )
    db.add(company)
    db.flush()

    # Crear token de invitación (7 días)
    token = secrets.token_urlsafe(64)
    expires_at = datetime.utcnow() + timedelta(days=7)

    invitacion = TenantInvitation(
        token=token,
        company_id=company.id,
        creado_por=user.username,
        expires_at=expires_at,
    )
    db.add(invitacion)
    db.commit()

    link_registro = f"{ADMIN_ORIGIN}/registro?token={token}"

    logger.info(
        f"✅ Empresa creada directamente: '{body.empresa_nombre}' "
        f"(id={company.id}) por {user.username}"
    )

    return {
        "ok": True,
        "company_id": company.id,
        "empresa_nombre": company.nombre,
        "link_registro": link_registro,
        "token": token,
        "expires_at": expires_at.isoformat(),
        "expires_label": expires_at.strftime("%d %b %Y a las %H:%M UTC"),
    }
