"""
RUTAS TENANT — Sistema Multi-Tenant Neurobaeza
===============================================
Prefijo: /tenants

Endpoints:
  GET  /tenants/{company_id}                    → Datos del tenant (Company + TenantConfig)
  GET  /tenants/{company_id}/onboarding         → Progreso del wizard
  POST /tenants/{company_id}/onboarding/step    → Guardar paso del wizard
  POST /tenants/{company_id}/onboarding/complete → Completar onboarding
  POST /tenants/{company_id}/invite             → Generar link de invitación
  POST /tenants/{company_id}/drive/verify       → Verificar acceso a Google Drive
  GET  /tenants/{company_id}/users              → Usuarios del tenant
"""

import uuid
import secrets
import string
import logging
import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional

from app.database import (
    get_db, AdminUser, Company, TenantConfig, TenantInvitation,
)
from app.routes.admin import get_current_user, require_role, pwd_context, create_access_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants", tags=["Multi-Tenant"])

ADMIN_ORIGIN = os.environ.get("ADMIN_ORIGIN", "https://admin-neurobaeza.vercel.app")


# ═══════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════

class OnboardingStepData(BaseModel):
    step: int
    data: dict = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════

def _get_or_404(db: Session, company_id: int) -> Company:
    company = db.query(Company).filter(
        Company.id == company_id,
        Company.activa == True
    ).first()
    if not company:
        raise HTTPException(status_code=404, detail=f"Empresa con id={company_id} no encontrada")
    return company


def _get_or_create_config(db: Session, company_id: int) -> TenantConfig:
    config = db.query(TenantConfig).filter(TenantConfig.company_id == company_id).first()
    if not config:
        config = TenantConfig(company_id=company_id, onboarding_data_json={})
        db.add(config)
        db.flush()
    return config


def _generar_password_temporal(length: int = 10) -> str:
    """Genera contraseña segura: letras + números, sin ambiguos."""
    alphabet = string.ascii_letters + string.digits
    # Al menos 1 mayúscula, 1 minúscula, 1 dígito
    while True:
        pwd = ''.join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.isupper() for c in pwd)
                and any(c.islower() for c in pwd)
                and any(c.isdigit() for c in pwd)):
            return pwd


def _verificar_acceso_drive(drive_folder_id: str) -> dict:
    """
    Intenta listar archivos en la carpeta de Drive usando la Service Account del sistema.
    Retorna {acceso: bool, carpeta_nombre, estructura: [{name, nuevo}], error}.
    """
    try:
        from app.drive_uploader import get_drive_service
        service = get_drive_service()
        meta = service.files().get(fileId=drive_folder_id, fields="name,id").execute()
        carpeta_nombre = meta.get("name", drive_folder_id)

        result = service.files().list(
            q=f"'{drive_folder_id}' in parents and trashed=false",
            fields="files(id,name,mimeType)",
            pageSize=20,
        ).execute()

        archivos = result.get("files", [])
        estructura = [{"name": f["name"], "nuevo": False} for f in archivos]

        return {
            "acceso": True,
            "carpeta_nombre": carpeta_nombre,
            "estructura": estructura,
            "error": None,
        }
    except ImportError:
        return {"acceso": False, "carpeta_nombre": None, "estructura": [],
                "error": "Módulo drive_uploader no disponible"}
    except Exception as e:
        err = str(e)
        if "notFound" in err or "404" in err:
            return {"acceso": False, "carpeta_nombre": None, "estructura": [],
                    "error": "Carpeta no encontrada. Verifica el ID y que esté compartida con la cuenta de servicio."}
        if "403" in err or "forbidden" in err.lower():
            return {"acceso": False, "carpeta_nombre": None, "estructura": [],
                    "error": "Sin permisos en la carpeta. Compártela con la cuenta de servicio del sistema."}
        return {"acceso": False, "carpeta_nombre": None, "estructura": [], "error": err[:300]}


# ═══════════════════════════════════════════════════════════
# ENDPOINT: GET /tenants/{company_id}
# ═══════════════════════════════════════════════════════════

@router.get("/{company_id}")
async def get_tenant(
    company_id: int,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retorna datos de la empresa + TenantConfig (o null si aún no existe)."""
    company = _get_or_404(db, company_id)

    config = db.query(TenantConfig).filter(TenantConfig.company_id == company_id).first()
    config_data = None
    if config:
        config_data = {
            "id": config.id,
            "nit": config.nit,
            "logo_url": config.logo_url,
            "paleta_id": config.paleta_id,
            "paleta_colores": config.paleta_colores,
            "estilo_ui": config.estilo_ui,
            "tipo_estructura": config.tipo_estructura,
            "sub_empresas": config.sub_empresas,
            "ciclo_reporte": config.ciclo_reporte,
            "contacto_email": config.contacto_email,
            "correo_drive": config.correo_drive,
            "zona_horaria": config.zona_horaria,
            "google_workspace_drive_id": config.google_workspace_drive_id,
            "drive_verificado": config.drive_verificado,
            "onboarding_completado": config.onboarding_completado,
            "onboarding_step": config.onboarding_step,
        }

    return {
        "ok": True,
        "id": company.id,
        "nombre": company.nombre,
        "nit": company.nit or (config.nit if config else None),
        "contacto_email": company.contacto_email,
        "activa": company.activa,
        "tenant_config": config_data,
    }


# ═══════════════════════════════════════════════════════════
# ENDPOINT: GET /tenants/{company_id}/onboarding
# ═══════════════════════════════════════════════════════════

@router.get("/{company_id}/onboarding")
async def get_onboarding_progress(
    company_id: int,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retorna el progreso acumulado del wizard de onboarding."""
    _get_or_404(db, company_id)
    config = db.query(TenantConfig).filter(TenantConfig.company_id == company_id).first()

    if not config:
        return {
            "ok": True,
            "step_actual": 1,
            "data_acumulada": {},
            "completado": False,
            "tenant_config": None,
        }

    return {
        "ok": True,
        "step_actual": config.onboarding_step or 1,
        "data_acumulada": config.onboarding_data_json or {},
        "completado": config.onboarding_completado,
        "tenant_config": {
            "paleta_id": config.paleta_id,
            "paleta_colores": config.paleta_colores,
            "estilo_ui": config.estilo_ui,
            "ciclo_reporte": config.ciclo_reporte,
        },
    }


# ═══════════════════════════════════════════════════════════
# ENDPOINT: POST /tenants/{company_id}/onboarding/step
# ═══════════════════════════════════════════════════════════

@router.post("/{company_id}/onboarding/step")
async def save_onboarding_step(
    company_id: int,
    body: OnboardingStepData,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Guarda/fusiona datos de un paso del wizard sin completarlo."""
    _get_or_404(db, company_id)
    config = _get_or_create_config(db, company_id)

    # Merge incremental del JSON acumulado
    acumulado = config.onboarding_data_json or {}
    acumulado.update(body.data or {})
    config.onboarding_data_json = acumulado

    # El step solo avanza, nunca retrocede
    config.onboarding_step = max(config.onboarding_step or 1, body.step)

    db.commit()
    logger.info(f"Tenant {company_id}: guardado paso {body.step} por {user.username}")

    return {
        "ok": True,
        "step_guardado": body.step,
        "data_acumulada": acumulado,
    }


# ═══════════════════════════════════════════════════════════
# ENDPOINT: POST /tenants/{company_id}/onboarding/complete
# ═══════════════════════════════════════════════════════════

@router.post("/{company_id}/onboarding/complete")
async def complete_onboarding(
    company_id: int,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Completa el onboarding:
    1. Aplica datos acumulados al TenantConfig
    2. Crea AdminUser con rol=admin, es_tenant_admin=True
    3. Retorna credenciales temporales (SOLO UNA VEZ)
    """
    company = _get_or_404(db, company_id)
    config = _get_or_create_config(db, company_id)

    if config.onboarding_completado:
        raise HTTPException(
            status_code=400,
            detail="El onboarding de esta empresa ya fue completado anteriormente."
        )

    datos = config.onboarding_data_json or {}

    # ── Aplicar datos al modelo ──
    if datos.get("nit"):
        config.nit = datos["nit"]
        company.nit = datos["nit"]
    if datos.get("contacto_email"):
        config.contacto_email = datos["contacto_email"]
        company.contacto_email = datos["contacto_email"]
    if datos.get("correo_drive"):
        config.correo_drive = datos["correo_drive"]
    if datos.get("zona_horaria"):
        config.zona_horaria = datos["zona_horaria"]
    if datos.get("paleta_id"):
        config.paleta_id = datos["paleta_id"]
    if datos.get("paleta_colores"):
        config.paleta_colores = datos["paleta_colores"]
    if datos.get("estilo_ui"):
        config.estilo_ui = datos["estilo_ui"]
    if datos.get("tipo_estructura"):
        config.tipo_estructura = datos["tipo_estructura"]
    if datos.get("sub_empresas"):
        config.sub_empresas = datos["sub_empresas"]
    if datos.get("ciclo_reporte"):
        config.ciclo_reporte = datos["ciclo_reporte"]
    if datos.get("google_workspace_drive_id"):
        config.google_workspace_drive_id = datos["google_workspace_drive_id"]
    if datos.get("logo_url"):
        config.logo_url = datos["logo_url"]

    config.onboarding_completado = True
    config.onboarding_step = 7

    # ── Crear TenantAdmin ──
    nit_clean = (config.nit or str(company_id)).replace("-", "").replace(".", "")[:12]
    base_username = f"admin_{nit_clean}"

    # Evitar colisión de username
    username = base_username
    counter = 0
    while db.query(AdminUser).filter(AdminUser.username == username).first():
        counter += 1
        username = f"{base_username}_{counter}"

    password_temporal = _generar_password_temporal(10)

    tenant_admin = AdminUser(
        username=username,
        password_hash=pwd_context.hash(password_temporal),
        nombre=f"Administrador — {company.nombre}",
        email=config.contacto_email,
        rol="admin",
        company_id=company_id,
        es_tenant_admin=True,
        tenant_permisos={
            "tabla_viva": True,
            "reportes": True,
            "powerbi": False,
            "exportaciones": False,
            "plano": False,
            "pendientes": False,
        },
        permisos={
            "validador": True,
            "reportes": True,
            "exportaciones": False,
            "powerbi": False,
            "directorio": False,
            "consola": False,
        },
        invited_by=user.id,
        activo=True,
    )
    db.add(tenant_admin)
    db.commit()
    db.refresh(tenant_admin)

    logger.info(
        f"Onboarding completado — empresa={company.nombre} "
        f"tenant_admin={username} — por {user.username}"
    )

    return {
        "ok": True,
        "mensaje": f"Empresa '{company.nombre}' activada. Guarda estas credenciales.",
        "tenant_admin_username": username,
        "tenant_admin_password_temporal": password_temporal,
        "company": {"id": company.id, "nombre": company.nombre, "nit": config.nit},
    }


# ═══════════════════════════════════════════════════════════
# ENDPOINT: POST /tenants/{company_id}/invite
# ═══════════════════════════════════════════════════════════

@router.post("/{company_id}/invite")
async def generar_invitacion(
    company_id: int,
    user: AdminUser = Depends(require_role("superadmin", "admin")),
    db: Session = Depends(get_db),
):
    """
    Genera un token de invitación de un solo uso (expira en 7 días).
    El link apunta al wizard de onboarding del admin.
    """
    _get_or_404(db, company_id)

    token = secrets.token_urlsafe(64)
    expires_at = datetime.utcnow() + timedelta(days=7)

    inv = TenantInvitation(
        token=token,
        company_id=company_id,
        creado_por=user.username,
        expires_at=expires_at,
    )
    db.add(inv)
    db.commit()

    link_onboarding = f"{ADMIN_ORIGIN}/tenants/{company_id}/onboarding?token={token}"

    return {
        "ok": True,
        "token": token,
        "link_onboarding": link_onboarding,
        "expires_at": expires_at.isoformat(),
        "expires_label": expires_at.strftime("%d %b %Y a las %H:%M"),
        "advertencia": "Este link es de un solo uso y expira en 7 días.",
    }


# ═══════════════════════════════════════════════════════════
# ENDPOINT: POST /tenants/{company_id}/drive/verify
# ═══════════════════════════════════════════════════════════

class DriveVerifyBody(BaseModel):
    drive_folder_id: str
    correo_drive: Optional[str] = None


@router.post("/{company_id}/drive/verify")
async def verificar_drive(
    company_id: int,
    body: DriveVerifyBody,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Verifica que la Service Account tenga acceso a la carpeta de Drive especificada.
    Si tiene acceso, marca drive_verificado=True en TenantConfig.
    """
    _get_or_404(db, company_id)

    resultado = _verificar_acceso_drive(body.drive_folder_id)

    if resultado["acceso"]:
        config = _get_or_create_config(db, company_id)
        config.google_workspace_drive_id = body.drive_folder_id
        config.drive_verificado = True
        if body.correo_drive:
            config.correo_drive = body.correo_drive
        db.commit()

    return resultado


# ═══════════════════════════════════════════════════════════
# ENDPOINT: GET /tenants/{company_id}/users
# ═══════════════════════════════════════════════════════════

@router.get("/{company_id}/users")
async def listar_usuarios_tenant(
    company_id: int,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Lista los usuarios AdminUser de un tenant.
    Solo accesible por el TenantAdmin de esa empresa, o por superadmin/admin global.
    """
    _get_or_404(db, company_id)

    # Control de acceso
    es_tenant_admin = getattr(user, 'es_tenant_admin', False)
    if es_tenant_admin and user.company_id != company_id:
        raise HTTPException(status_code=403, detail="Solo puedes ver usuarios de tu empresa.")
    if not es_tenant_admin and user.rol not in ("superadmin", "admin"):
        raise HTTPException(status_code=403, detail="Sin permisos suficientes.")

    usuarios = db.query(AdminUser).filter(
        AdminUser.company_id == company_id,
        AdminUser.activo == True,
    ).order_by(AdminUser.created_at).all()

    return {
        "ok": True,
        "company_id": company_id,
        "total": len(usuarios),
        "usuarios": [
            {
                "id": u.id,
                "username": u.username,
                "nombre": u.nombre,
                "email": u.email,
                "rol": u.rol,
                "es_tenant_admin": getattr(u, 'es_tenant_admin', False),
                "tenant_permisos": getattr(u, 'tenant_permisos', {}) or {},
                "permisos": u.permisos or {},
                "ultimo_login": u.ultimo_login.isoformat() if u.ultimo_login else None,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in usuarios
        ],
    }
