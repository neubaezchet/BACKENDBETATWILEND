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
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List

from app.database import get_db, DemoRequest, Company, TenantInvitation, TenantConfig, DemoSession, asignar_slug
from app.routes.admin import get_current_user, require_role, create_access_token, pwd_context
from app.services.portal_links import links_de_company

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
    cantidad_empleados: Optional[str] = Field(None, max_length=20)  # "1-10" | "11-50" | "51-200" | "200+"
    captcha_token: Optional[str] = Field(None, max_length=2048)     # token de Cloudflare Turnstile


class RechazarLeadBody(BaseModel):
    notas_internas: Optional[str] = None


class AprobarLeadBody(BaseModel):
    notas_internas: Optional[str] = None


# ═══════════════════════════════════════════════════════════
# SEGURIDAD — rate-limit por IP + captcha (Cloudflare Turnstile)
# ═══════════════════════════════════════════════════════════

# Rate-limit in-process: máximo N solicitudes por IP por ventana.
# Suficiente para un solo proceso (Railway); si algún día hay réplicas, migrar a Redis.
_RATE_VENTANA_SEG = 3600      # 1 hora
_RATE_MAX_POR_IP = 3          # 3 demos/hora por IP
_rate_hits = defaultdict(deque)  # ip -> deque de timestamps


def _client_ip(request: Request) -> str:
    """IP real del cliente (Railway pone la original en X-Forwarded-For)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "desconocida"


def _rate_limit_ok(ip: str) -> bool:
    """True si la IP aún tiene cupo en la ventana. Registra el hit si pasa."""
    ahora = time.monotonic()
    hits = _rate_hits[ip]
    while hits and ahora - hits[0] > _RATE_VENTANA_SEG:
        hits.popleft()
    if len(hits) >= _RATE_MAX_POR_IP:
        return False
    hits.append(ahora)
    # Evitar crecimiento sin límite del dict (IPs viejas sin hits vigentes)
    if len(_rate_hits) > 10000:
        for k in [k for k, v in _rate_hits.items() if not v]:
            _rate_hits.pop(k, None)
    return True


def _verificar_turnstile(token: str, ip: str) -> bool:
    """
    Valida el captcha de Cloudflare Turnstile.
    Si TURNSTILE_SECRET_KEY no está configurada, se omite (retorna True) para
    poder lanzar sin captcha y activarlo después solo con la variable de entorno.
    """
    secret = os.environ.get("TURNSTILE_SECRET_KEY")
    if not secret:
        return True
    if not token:
        return False
    try:
        import requests as _requests
        resp = _requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": secret, "response": token, "remoteip": ip},
            timeout=10,
        )
        return bool(resp.json().get("success"))
    except Exception as e:
        logger.warning(f"⚠️ Turnstile no verificable ({e}) — rechazando por seguridad")
        return False


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════

def _serializar_lead(lead: DemoRequest, db: Session = None) -> dict:
    # Slug + links de los 3 portales (si el lead tiene empresa asociada)
    slug = None
    demo_estado = None
    if db is not None and lead.company_id:
        company = db.query(Company).filter(Company.id == lead.company_id).first()
        if company:
            slug = company.slug
            sesion = db.query(DemoSession).filter(DemoSession.company_id == company.id).first()
            if sesion:
                if sesion.activa and sesion.expires_at > datetime.utcnow():
                    demo_estado = "demo_activo"
                else:
                    demo_estado = "demo_expirado"  # desactivado, aún recuperable con Activar
            else:
                demo_estado = "empresa_activa" if company.activa else "desactivada"
        else:
            demo_estado = "eliminada"  # el demo se purgó; Activar la recrea
    return {
        "slug": slug,
        "links": links_de_company(slug) if slug else None,
        "demo_estado": demo_estado,
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


def _enviar_email_demo_aprobado(
    contacto_email: str, contacto_nombre: str, empresa_nombre: str,
    link_registro: str, horas: int, links: dict = None,
):
    """Email especial para aprobación de demo: incluye link de registro + los 3 portales."""
    try:
        from app.email_service import enviar_email_simple
        links = links or links_de_company(None)
        asunto = f"🎯 Tu demo de NeuroBareza está listo — {empresa_nombre}"
        cuerpo = f"""
Hola {contacto_nombre},

¡Buenas noticias! Tu solicitud de demo para **{empresa_nombre}** ha sido aprobada.

Tienes **{horas} horas** para explorar el sistema completo desde que completes el registro.

━━━━━━━━━━━━━━━━━━━━━━━━
PASO 1 — Completa tu registro:
{link_registro}

⚠️ Este enlace expira en 24 horas.
━━━━━━━━━━━━━━━━━━━━━━━━

Una vez registrado, tendrás acceso a los 3 portales EXCLUSIVOS de tu empresa
(se abren con tus colores y tu logo):

🔵 Portal Administración (configuración, usuarios, reportes)
   {links['admin']}

🟢 Portal Validación (revisión de incapacidades)
   {links['portal']}

🟡 Recepción de incapacidades (compártelo con tus empleados)
   {links['repogemin']}

━━━━━━━━━━━━━━━━━━━━━━━━
Puedes enviar una incapacidad de prueba, ver cómo se procesa y cómo aparece en el validador.
Al finalizar el demo, todos los datos se eliminarán automáticamente.

¿Quieres contratar después del demo? Escríbenos a gestiondeincapacidades@incapacidade.com

Saludos,
El equipo de NeuroBareza
        """.strip()

        enviar_email_simple(
            destinatario=contacto_email,
            asunto=asunto,
            cuerpo_texto=cuerpo,
        )
        logger.info(f"✅ Email de demo enviado a {contacto_email}")
    except Exception as e:
        logger.warning(f"⚠️ No se pudo enviar email de demo a {contacto_email}: {e}")


def _enviar_email_empresa_activada(
    contacto_email: str, contacto_nombre: str, empresa_nombre: str,
    links: dict, paleta_id: str = None,
):
    """Email de bienvenida al activar la empresa como cliente: incluye los links de SUS 3 portales."""
    try:
        from app.email_service import enviar_email_simple
        asunto = f"🎉 ¡Bienvenido a NeuroBareza, {empresa_nombre}!"
        paleta_linea = f"\nTu portal conserva la personalización que elegiste (paleta: {paleta_id}).\n" if paleta_id else "\n"
        cuerpo = f"""
Hola {contacto_nombre},

¡Excelentes noticias! **{empresa_nombre}** ya es cliente activo de NeuroBareza.

Toda la configuración, usuarios y datos que creaste durante el demo se conservan.
{paleta_linea}
Estos son los accesos exclusivos de tu empresa (guárdalos en favoritos):

🔵 Portal Administración (configuración, usuarios, reportes)
   {links['admin']}

🟢 Portal Validación (revisión de incapacidades)
   {links['portal']}

🟡 Recepción de incapacidades (compártelo con tus empleados)
   {links['repogemin']}

Al abrir estos links, verás tu logo y tus colores desde el inicio de sesión.

Si tienes alguna pregunta, escríbenos a gestiondeincapacidades@incapacidade.com

Saludos,
El equipo de NeuroBareza
        """.strip()

        enviar_email_simple(
            destinatario=contacto_email,
            asunto=asunto,
            cuerpo_texto=cuerpo,
        )
        logger.info(f"✅ Email de activación enviado a {contacto_email}")
    except Exception as e:
        logger.warning(f"⚠️ No se pudo enviar email de activación a {contacto_email}: {e}")


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

@demo_router.post("/solicitar-auto")
async def solicitar_demo_auto(
    body: SolicitarDemoBody,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Demo auto-servicio: sin aprobación manual del admin.
    - Rate-limit por IP + captcha Turnstile (si TURNSTILE_SECRET_KEY está configurada)
    - Crea DemoRequest visible en el panel de Solicitudes
    - Crea Company + TenantInvitation (24h) + DemoSession (3h)
    - El link de registro se envía SOLO POR EMAIL (verifica propiedad del correo,
      no se expone en la respuesta)
    - Solo permite un demo por email
    """
    # ── SEGURIDAD 1: rate-limit por IP
    ip = _client_ip(request)
    if not _rate_limit_ok(ip):
        logger.warning(f"🛑 Rate-limit demo auto-servicio: IP {ip}")
        raise HTTPException(
            status_code=429,
            detail="Demasiadas solicitudes desde esta conexión. Intenta de nuevo en una hora.",
        )

    # ── SEGURIDAD 2: captcha (activo solo si TURNSTILE_SECRET_KEY está configurada)
    if not _verificar_turnstile(body.captcha_token, ip):
        raise HTTPException(status_code=400, detail="Verificación de seguridad fallida. Recarga la página e intenta de nuevo.")

    # Bloquear solo si hay un demo VIGENTE para ese email (pendiente o aprobado con
    # empresa viva). Los expirados/rechazados no bloquean: pueden pedir otro demo.
    existente = db.query(DemoRequest).filter(
        DemoRequest.contacto_email == body.contacto_email,
        DemoRequest.estado.in_(["pendiente", "aprobado"]),
    ).first()
    if existente:
        return {
            "ok": False,
            "ya_existe": True,
            "mensaje": "Ya existe una solicitud de demo para este correo.",
        }

    # 1. Crear DemoRequest (visible en Leads del admin como "aprobado")
    lead = DemoRequest(
        empresa_nombre=body.empresa_nombre,
        nit=body.nit,
        contacto_nombre=body.contacto_nombre,
        contacto_email=body.contacto_email,
        contacto_telefono=body.contacto_telefono,
        como_conocio=body.como_conocio,
        mensaje=body.cantidad_empleados or body.mensaje,
        estado="aprobado",
        aprobado_por="auto-servicio",
    )
    db.add(lead)
    db.flush()

    # 2. Crear Company
    company = db.query(Company).filter(Company.nombre == body.empresa_nombre).first()
    if not company:
        company = Company(
            nombre=body.empresa_nombre,
            nit=body.nit,
            contacto_email=body.contacto_email,
            contacto_telefono=body.contacto_telefono,
            activa=True,
        )
        db.add(company)
        db.flush()
    if not company.slug:
        asignar_slug(db, company)
    company.activa = True  # por si estaba desactivada de un demo expirado anterior

    lead.company_id = company.id

    # 3. TenantInvitation: 24h para completar el registro
    HORAS_DEMO = 3
    token = secrets.token_urlsafe(64)
    inv_expires = datetime.utcnow() + timedelta(hours=24)

    invitacion = TenantInvitation(
        token=token,
        company_id=company.id,
        creado_por="auto-servicio",
        expires_at=inv_expires,
        demo_request_id=lead.id,
    )
    db.add(invitacion)

    # 4. DemoSession: timer empieza cuando completan el wizard "Hola"
    # (company_id es UNIQUE: si quedó una sesión expirada en periodo de gracia, se reutiliza)
    demo_session = db.query(DemoSession).filter(DemoSession.company_id == company.id).first()
    if demo_session:
        demo_session.demo_request_id = lead.id
        demo_session.horas = HORAS_DEMO
        demo_session.expires_at = datetime.utcnow() + timedelta(hours=HORAS_DEMO + 1)
        demo_session.activa = True
        demo_session.cantidad_empleados = body.cantidad_empleados
    else:
        demo_session = DemoSession(
            company_id=company.id,
            demo_request_id=lead.id,
            horas=HORAS_DEMO,
            expires_at=datetime.utcnow() + timedelta(hours=HORAS_DEMO + 1),
            activa=True,
            cantidad_empleados=body.cantidad_empleados,
        )
        db.add(demo_session)

    db.commit()

    # ── SEGURIDAD 3: el link va SOLO por correo — verifica que el email sea suyo.
    # (Antes se devolvía en la respuesta: cualquier bot obtenía acceso sin email real.)
    link_registro = f"{ADMIN_ORIGIN}/onboarding?token={token}&demo=1&horas={HORAS_DEMO}"
    background_tasks.add_task(
        _enviar_email_demo_aprobado,
        body.contacto_email,
        body.contacto_nombre,
        body.empresa_nombre,
        link_registro,
        HORAS_DEMO,
        links_de_company(company.slug),
    )

    logger.info(f"🎯 Demo auto-servicio: {body.empresa_nombre} ({body.contacto_email}) → company_id={company.id} | link enviado por email")

    return {
        "ok": True,
        "email_enviado": True,
        "horas": HORAS_DEMO,
        "empresa_nombre": body.empresa_nombre,
        "mensaje": f"Te enviamos el enlace de registro a {body.contacto_email}. Revisa tu bandeja (y spam). Expira en 24 horas.",
    }


@demo_router.post("/solicitar")
async def solicitar_demo(
    body: SolicitarDemoBody,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Endpoint público: registra una solicitud de demo.
    No requiere autenticación. Queda en estado 'pendiente'.
    """
    # Rate-limit por IP (mismo límite que el auto-servicio)
    ip = _client_ip(request)
    if not _rate_limit_ok(ip):
        raise HTTPException(
            status_code=429,
            detail="Demasiadas solicitudes desde esta conexión. Intenta de nuevo en una hora.",
        )
    if not _verificar_turnstile(body.captcha_token, ip):
        raise HTTPException(status_code=400, detail="Verificación de seguridad fallida. Recarga la página e intenta de nuevo.")

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
        mensaje=body.cantidad_empleados or body.mensaje,  # cantidad_empleados tiene prioridad
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
        "leads": [_serializar_lead(l, db) for l in leads],
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
    return {"ok": True, "lead": _serializar_lead(lead, db)}


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
    if not company.slug:
        asignar_slug(db, company)

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
    link_registro = f"{ADMIN_ORIGIN}/onboarding?token={token}"

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
    contacto_email: Optional[str] = Field(None, max_length=300)
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
    asignar_slug(db, company)

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

    link_registro = f"{ADMIN_ORIGIN}/onboarding?token={token}"

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


# ═══════════════════════════════════════════════════════════
# ENDPOINT ADMIN: POST /admin/leads/{id}/aprobar-demo
# Aprueba como DEMO temporal (horas limitadas, auto-destruye datos)
# ═══════════════════════════════════════════════════════════

class AprobarDemoBody(BaseModel):
    horas: int = Field(4, ge=1, le=24, description="Duración del demo en horas (1-24)")
    notas_internas: Optional[str] = None


@leads_router.post("/{lead_id}/aprobar-demo")
async def aprobar_lead_como_demo(
    lead_id: int,
    body: AprobarDemoBody,
    background_tasks: BackgroundTasks,
    user=Depends(require_role("superadmin", "admin")),
    db: Session = Depends(get_db),
):
    """
    Aprueba un lead como demo temporal:
    - Crea Company + TenantInvitation (24h para registrarse)
    - Crea DemoSession con timer (horas indicadas desde que completen el registro)
    - El link de registro es diferente: /registro?token=XXX&demo=1
    - Al vencer, los datos se eliminan automáticamente
    """
    lead = db.query(DemoRequest).filter(DemoRequest.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if lead.estado != "pendiente":
        raise HTTPException(status_code=400, detail=f"Esta solicitud ya fue procesada (estado: {lead.estado})")

    # Crear la Company
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
        db.flush()
    if not company.slug:
        asignar_slug(db, company)
    company.activa = True  # por si estaba desactivada de un demo expirado anterior

    # TenantInvitation con 24h para registrarse (demo empieza al completar registro)
    token = secrets.token_urlsafe(64)
    inv_expires = datetime.utcnow() + timedelta(hours=24)

    invitacion = TenantInvitation(
        token=token,
        company_id=company.id,
        creado_por=user.username,
        expires_at=inv_expires,
        demo_request_id=lead.id,
    )
    db.add(invitacion)

    # DemoSession — el timer empieza cuando completan el registro
    # (company_id es UNIQUE: si quedó una sesión expirada en periodo de gracia, se reutiliza)
    demo_expires = datetime.utcnow() + timedelta(hours=body.horas + 1)  # +1 por tiempo de registro
    demo_session = db.query(DemoSession).filter(DemoSession.company_id == company.id).first()
    if demo_session:
        demo_session.demo_request_id = lead.id
        demo_session.horas = body.horas
        demo_session.expires_at = demo_expires
        demo_session.activa = True
        demo_session.cantidad_empleados = lead.mensaje
    else:
        demo_session = DemoSession(
            company_id=company.id,
            demo_request_id=lead.id,
            horas=body.horas,
            expires_at=demo_expires,
            activa=True,
            cantidad_empleados=lead.mensaje,  # reutilizamos mensaje para cantidad_empleados si viene
        )
        db.add(demo_session)

    lead.estado = "aprobado"
    lead.aprobado_por = user.username
    lead.company_id = company.id
    if body.notas_internas:
        lead.notas_internas = body.notas_internas

    db.commit()

    link_registro = f"{ADMIN_ORIGIN}/onboarding?token={token}&demo=1&horas={body.horas}"

    background_tasks.add_task(
        _enviar_email_demo_aprobado,
        lead.contacto_email,
        lead.contacto_nombre,
        lead.empresa_nombre,
        link_registro,
        body.horas,
        links_de_company(company.slug),
    )

    logger.info(f"🎯 Lead aprobado como DEMO ({body.horas}h): {lead.empresa_nombre} → company_id={company.id}")

    return {
        "ok": True,
        "es_demo": True,
        "horas": body.horas,
        "company_id": company.id,
        "link_registro": link_registro,
        "expires_label": demo_expires.strftime("%d %b %Y a las %H:%M UTC"),
    }


# ═══════════════════════════════════════════════════════════
# ENDPOINT PÚBLICO: GET /demo/status/{company_id}
# Verifica si el demo está activo y cuánto tiempo queda
# ═══════════════════════════════════════════════════════════

@demo_router.get("/status/{company_id}")
async def demo_status(company_id: int, db: Session = Depends(get_db)):
    """
    ENDPOINT PÚBLICO. Verifica si una empresa tiene demo activo.
    Retorna tiempo restante en segundos.
    """
    # OJO: no filtrar por activa — un demo expirado en periodo de gracia sigue
    # existiendo (desactivado) y el portal debe seguir mostrándolo como expirado.
    session = db.query(DemoSession).filter(
        DemoSession.company_id == company_id,
    ).first()

    if not session:
        return {"es_demo": False, "activo": False}

    ahora = datetime.utcnow()
    if session.expires_at <= ahora or not session.activa:
        if session.activa:
            session.activa = False
            db.commit()
        return {"es_demo": True, "activo": False, "expirado": True}

    segundos_restantes = int((session.expires_at - ahora).total_seconds())
    return {
        "es_demo": True,
        "activo": True,
        "segundos_restantes": segundos_restantes,
        "horas_totales": session.horas,
        "expires_at": session.expires_at.isoformat(),
    }


# ═══════════════════════════════════════════════════════════
# ENDPOINT PÚBLICO: POST /demo/feedback
# Envía feedback al finalizar el demo
# ═══════════════════════════════════════════════════════════

class DemoFeedbackBody(BaseModel):
    company_id: int
    calificacion: int = Field(..., ge=1, le=5)
    mejoras: Optional[str] = Field(None, max_length=2000)
    quiere_contratar: Optional[str] = Field(None, pattern="^(si|no|despues)$")


@demo_router.post("/feedback")
async def enviar_demo_feedback(body: DemoFeedbackBody, db: Session = Depends(get_db)):
    """
    ENDPOINT PÚBLICO. Guarda el feedback del demo.
    """
    session = db.query(DemoSession).filter(
        DemoSession.company_id == body.company_id,
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Sesión de demo no encontrada")

    session.feedback_calificacion = body.calificacion
    session.feedback_mejoras = body.mejoras
    session.feedback_quiere_contratar = body.quiere_contratar
    session.feedback_enviado_at = datetime.utcnow()
    db.commit()

    logger.info(f"📝 Feedback demo recibido: company_id={body.company_id} ⭐{body.calificacion}")
    return {"ok": True, "mensaje": "¡Gracias por tu retroalimentación!"}


# ═══════════════════════════════════════════════════════════
# ENDPOINT ADMIN: DELETE /admin/demos/limpiar
# Elimina datos de demos expirados (llamar manualmente o via cron)
# ═══════════════════════════════════════════════════════════

GRACIA_DIAS_DEMO = 7  # días que un demo expirado queda desactivado antes de la purga total


def limpiar_demos_expirados_core() -> dict:
    """
    Ciclo de vida del demo expirado, en DOS FASES:

    FASE 1 (al expirar): DESACTIVA la empresa — portales bloqueados, el sync la
      ignora, no gasta ciclos de servidor. Los datos y la configuración se
      CONSERVAN para que el admin todavía pueda oprimir "Activar empresa" si el
      cliente decidió contratar después del demo. El lead pasa a "expirado"
      (conserva historial y libera el email).

    FASE 2 (a los GRACIA_DIAS_DEMO días de expirado): purga total — empresa,
      empleados, casos, TenantConfig y Sheet en Drive. Solo queda el lead como
      historial; si el admin activa después, se recrea desde cero con una nueva
      invitación.

    Reutilizable: la invocan el endpoint de admin y el job automático del scheduler.
    Abre y cierra su propia sesión de BD.
    """
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        ahora = datetime.utcnow()
        limite_purga = ahora - timedelta(days=GRACIA_DIAS_DEMO)

        sessions_expiradas = db.query(DemoSession).filter(
            DemoSession.expires_at <= ahora,
        ).all()

        if not sessions_expiradas:
            return {"ok": True, "demos_desactivados": 0, "demos_eliminados": 0, "sheets_borrados": 0}

        desactivados = 0
        eliminados = 0
        sheets_a_borrar = []
        for s in sessions_expiradas:
            company = db.query(Company).filter(Company.id == s.company_id).first()

            # Lead asociado: conserva el historial en el panel de Solicitudes
            # y libera el email para que puedan pedir otro demo.
            lead = None
            if s.demo_request_id:
                lead = db.query(DemoRequest).filter(DemoRequest.id == s.demo_request_id).first()
            if not lead and s.company_id:
                lead = db.query(DemoRequest).filter(DemoRequest.company_id == s.company_id).first()
            if lead and lead.estado == "aprobado":
                lead.estado = "expirado"

            if s.expires_at > limite_purga:
                # ── FASE 1: expiró pero está en periodo de gracia → desactivar, NO borrar
                s.activa = False
                if company and company.activa:
                    company.activa = False
                    desactivados += 1
                    logger.info(f"⏸️ Demo expirado — empresa desactivada (gracia {GRACIA_DIAS_DEMO} días): '{company.nombre}' (id={company.id})")
                continue

            # ── FASE 2: gracia vencida → purga total
            if company:
                # Capturar el Sheet del tenant ANTES del cascade (TenantConfig se borra con la Company)
                config = db.query(TenantConfig).filter(TenantConfig.company_id == company.id).first()
                if config and config.google_sheets_id:
                    sheets_a_borrar.append(config.google_sheets_id)
                db.delete(company)  # CASCADE borra empleados, casos, etc.
                eliminados += 1

            db.delete(s)

        db.commit()

        # Borrar los Sheets de Drive (best-effort: un fallo aquí no debe revertir la limpieza en BD)
        sheets_borrados = 0
        if sheets_a_borrar:
            try:
                from app.services.tenant_provisioning import _get_drive_service
                drive = _get_drive_service()
                for sheet_id in sheets_a_borrar:
                    try:
                        drive.files().delete(fileId=sheet_id, supportsAllDrives=True).execute()
                        sheets_borrados += 1
                    except Exception as e:
                        logger.warning(f"⚠️ No se pudo borrar Sheet {sheet_id} de demo expirado: {e}")
            except Exception as e:
                logger.warning(f"⚠️ Sin servicio Drive para borrar Sheets de demos: {e}")

        logger.info(
            f"🗑️ Limpieza de demos: {desactivados} desactivados (gracia), "
            f"{eliminados} purgados, {sheets_borrados} Sheets borrados de Drive"
        )
        return {
            "ok": True,
            "demos_desactivados": desactivados,
            "demos_eliminados": eliminados,
            "sheets_borrados": sheets_borrados,
        }
    finally:
        db.close()


@leads_router.delete("/demos/limpiar")
async def limpiar_demos_expirados(
    user=Depends(require_role("superadmin")),
):
    """Elimina todos los datos de demos expirados (companies, empleados, casos, etc.)."""
    return limpiar_demos_expirados_core()


# ═══════════════════════════════════════════════════════════
# ENDPOINT ADMIN: POST /admin/leads/{id}/activar-empresa
# Convierte empresa demo en empresa real SIN doble registro
# ═══════════════════════════════════════════════════════════

@leads_router.post("/{lead_id}/activar-empresa")
async def activar_empresa_desde_demo(
    lead_id: int,
    background_tasks: BackgroundTasks,
    user=Depends(require_role("superadmin", "admin")),
    db: Session = Depends(get_db),
):
    """
    Convierte una empresa demo en empresa real permanente.
    - Elimina la DemoSession (quita el timer)
    - REACTIVA la empresa si el demo ya había expirado (periodo de gracia)
    - Conserva TODA la configuración, empleados, y portal ya creados
    - Si el demo fue purgado (gracia vencida): recrea la empresa y envía una
      nueva invitación de registro al contacto
    - Envía email al contacto con los links de sus 3 portales
    """
    lead = db.query(DemoRequest).filter(DemoRequest.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    company = None
    if lead.company_id:
        company = db.query(Company).filter(Company.id == lead.company_id).first()

    # ── Caso purga: el demo expiró y sus datos ya fueron eliminados → recrear desde cero
    if not company:
        company = Company(
            nombre=lead.empresa_nombre,
            nit=lead.nit,
            contacto_email=lead.contacto_email,
            contacto_telefono=lead.contacto_telefono,
            activa=True,
        )
        db.add(company)
        db.flush()
        asignar_slug(db, company)

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
        lead.company_id = company.id
        lead.estado = "aprobado"
        lead.aprobado_por = user.username
        db.commit()

        link_registro = f"{ADMIN_ORIGIN}/onboarding?token={token}"
        background_tasks.add_task(
            _enviar_email_aprobacion,
            lead.contacto_email,
            lead.contacto_nombre,
            company.nombre,
            link_registro,
        )
        logger.info(
            f"♻️ Demo purgado reactivado como empresa real: '{company.nombre}' "
            f"(id={company.id}) — nueva invitación enviada, por {user.username}"
        )
        return {
            "ok": True,
            "recreada": True,
            "company_id": company.id,
            "empresa_nombre": company.nombre,
            "link_registro": link_registro,
            "mensaje": (
                f"El demo de '{company.nombre}' ya había sido eliminado. "
                f"Se creó la empresa de nuevo y se envió una invitación de registro a {lead.contacto_email}."
            ),
        }

    # ── Caso normal: la empresa existe (demo vigente o expirado en gracia)
    demo_session = db.query(DemoSession).filter(
        DemoSession.company_id == lead.company_id,
    ).first()

    reactivada = not company.activa
    company.activa = True  # reactiva si estaba desactivada por expiración
    if lead.estado == "expirado":
        lead.estado = "aprobado"

    feedback = None
    if demo_session:
        feedback = {
            "calificacion": demo_session.feedback_calificacion,
            "mejoras": demo_session.feedback_mejoras,
            "quiere_contratar": demo_session.feedback_quiere_contratar,
        }
        db.delete(demo_session)  # quita el timer → empresa permanente
    db.commit()

    # Email al contacto con los links de sus 3 portales + su personalización
    config = db.query(TenantConfig).filter(TenantConfig.company_id == company.id).first()
    paleta_id = config.paleta_id if config else None

    # ♻️ AUTOCURACIÓN: si el aprovisionamiento quedó incompleto durante el demo,
    # reintentarlo automáticamente al activar la empresa (Sheet solo si no existe;
    # estructura Drive es idempotente).
    if config:
        try:
            from app.routes.tenants import _provisionar_sheet_background, _crear_estructura_drive_background
            if not config.google_sheets_id:
                config.sheet_status = "pendiente"
                db.commit()
                background_tasks.add_task(
                    _provisionar_sheet_background,
                    company_id=company.id,
                    company_nombre=company.nombre,
                    contacto_email=config.contacto_email or company.contacto_email or "",
                    tipo_estructura=config.tipo_estructura or "unica",
                    sub_empresas=config.sub_empresas or [],
                )
                logger.info(f"♻️ Activación: Sheet faltante para '{company.nombre}' — reaprovisionando")
            if config.google_workspace_drive_id:
                background_tasks.add_task(
                    _crear_estructura_drive_background,
                    company_id=company.id,
                    company_nombre=company.nombre,
                    tipo_estructura=config.tipo_estructura or "unica",
                    sub_empresas=config.sub_empresas or [],
                )
        except Exception as _e:
            logger.warning(f"⚠️ Autocuración de aprovisionamiento al activar falló: {_e}")
    email_destino = company.contacto_email or lead.contacto_email
    if email_destino:
        background_tasks.add_task(
            _enviar_email_empresa_activada,
            email_destino,
            lead.contacto_nombre,
            company.nombre,
            links_de_company(company.slug),
            paleta_id,
        )

    logger.info(
        f"✅ Empresa demo activada como real: '{company.nombre}' (id={company.id}) "
        f"por {user.username} | reactivada={reactivada} | Feedback: {feedback}"
    )

    return {
        "ok": True,
        "ya_activa": demo_session is None and not reactivada,
        "reactivada": reactivada,
        "company_id": company.id,
        "empresa_nombre": company.nombre,
        "slug": company.slug,
        "links": links_de_company(company.slug),
        "mensaje": f"¡Empresa '{company.nombre}' activada exitosamente! Ya es una empresa real.",
        "feedback": feedback,
    }
