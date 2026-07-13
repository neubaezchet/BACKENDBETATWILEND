"""
RUTAS TENANT — Sistema Multi-Tenant Neurobaeza
===============================================
Prefijo: /tenants

Endpoints públicos (sin JWT):
  GET  /tenants/registro/validar-token          → Valida token de invitación
  POST /tenants/registro/completar              → Registro self-service de la empresa

Endpoints protegidos (JWT requerido):
  GET  /tenants/{company_id}                    → Datos del tenant (Company + TenantConfig)
  GET  /tenants/{company_id}/onboarding         → Progreso del wizard
  POST /tenants/{company_id}/onboarding/step    → Guardar paso del wizard
  POST /tenants/{company_id}/onboarding/complete → Completar onboarding (flujo viejo)
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

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional

from app.database import (
    get_db, AdminUser, Company, TenantConfig, TenantInvitation, DemoSession,
)
from app.routes.admin import get_current_user, require_role, pwd_context, create_access_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants", tags=["Multi-Tenant"])

ADMIN_ORIGIN = os.environ.get("ADMIN_ORIGIN", "https://admin-neurobaeza.vercel.app")


# ═════════════════════════════════════════════════════════
# ENDPOINT PÚBLICO: GET /tenants/registro/validar-token
# ═════════════════════════════════════════════════════════

@router.get("/registro/validar-token")
async def validar_token_registro(
    token: str = Query(..., description="Token de invitación recibido por email"),
    db: Session = Depends(get_db),
):
    """
    ENDPOINT PÚBLICO (sin JWT).
    Valida que el token de invitación sea válido, no expirado y no usado.
    Retorna datos pre-llenados de la empresa para el wizard.
    """
    invitacion = db.query(TenantInvitation).filter(
        TenantInvitation.token == token
    ).first()

    if not invitacion:
        raise HTTPException(status_code=404, detail="Token de invitación no válido.")
    if invitacion.usado:
        raise HTTPException(status_code=400, detail="Este enlace ya fue utilizado. Solicita uno nuevo.")
    if invitacion.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Este enlace ha expirado. Solicita uno nuevo.")

    company = db.query(Company).filter(Company.id == invitacion.company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Empresa no encontrada.")

    config = db.query(TenantConfig).filter(TenantConfig.company_id == company.id).first()

    return {
        "ok": True,
        "token_valido": True,
        "expires_at": invitacion.expires_at.isoformat(),
        "company": {
            "id": company.id,
            "nombre": company.nombre,
            "nit": company.nit,
            "contacto_email": company.contacto_email,
        },
        "onboarding_completado": config.onboarding_completado if config else False,
    }


# ═════════════════════════════════════════════════════════
# ENDPOINT PÚBLICO: GET /tenants/service-account-email
# ═════════════════════════════════════════════════════════

@router.get("/service-account-email")
async def get_service_account_email_public():
    """
    ENDPOINT PÚBLICO (sin JWT).
    Retorna el email de la Service Account de Google para que la empresa
    sepa con quién compartir su carpeta de Drive.
    """
    try:
        import json as _json
        creds_json = (
            os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
            or os.environ.get("GOOGLE_CREDENTIALS_JSON")
            or os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
        )
        if creds_json:
            creds = _json.loads(creds_json)
            email = creds.get("client_email", "")
            if email:
                return {"ok": True, "email": email}
    except Exception:
        pass
    return {"ok": False, "email": None, "mensaje": "Credenciales no configuradas"}


# ═════════════════════════════════════════════════════════
# TEMA VISUAL DEL TENANT
# GET /tenants/me/theme  |  GET /tenants/{company_id}/theme
# (el hook useTenantTheme del frontend consume estos endpoints)
# ═════════════════════════════════════════════════════════

PORTALES_VALIDOS = ("admin", "portal", "repogemin")


def _theme_de_company(db: Session, company_id: int, portal: str = None) -> dict:
    """
    Tema visual de una empresa. Si `portal` viene ('admin' | 'portal' | 'repogemin')
    y la empresa definió una paleta específica para ese portal, esa paleta gana;
    si no, se usa la paleta general elegida en el wizard.
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    config = db.query(TenantConfig).filter(TenantConfig.company_id == company_id).first()

    paleta_id = config.paleta_id if config else None
    paleta_colores = (config.paleta_colores if config else None) or {}
    overrides = (config.paletas_portales if config else None) or {}
    if portal in PORTALES_VALIDOS and isinstance(overrides.get(portal), dict):
        ov = overrides[portal]
        paleta_id = ov.get("paleta_id") or paleta_id
        paleta_colores = ov.get("colores") or paleta_colores

    from app.services.portal_links import links_de_company
    return {
        "ok": True,
        "company_id": company.id,
        "empresa": company.nombre,
        "slug": company.slug,
        "activa": company.activa,
        "links": links_de_company(company.slug),
        "paleta_id": paleta_id,
        "paleta_colores": paleta_colores,
        "paletas_portales": overrides,
        "estilo_ui": config.estilo_ui if config else "default",
        "logo_url": config.logo_url if config else None,
        "tipo_estructura": (config.tipo_estructura if config else None) or "unica",
        "sub_empresas": (config.sub_empresas if config else None) or [],
        "ciclo_reporte": (config.ciclo_reporte if config else None) or "mensual",
    }


@router.get("/me/theme")
async def get_mi_theme(
    portal: str = Query(None, description="admin | portal | repogemin"),
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Tema visual de la empresa del usuario autenticado."""
    if not user.company_id:
        return {"ok": False, "mensaje": "Usuario sin empresa asociada (admin global)"}
    return _theme_de_company(db, user.company_id, portal)


class ActualizarThemeBody(BaseModel):
    paleta_id: Optional[str] = None
    paleta_colores: Optional[dict] = None   # {primary, secondary, accent}
    estilo_ui: Optional[str] = None
    portal: Optional[str] = None            # admin | portal | repogemin | None/"todos" = general


@router.put("/me/theme")
async def actualizar_mi_theme(
    body: ActualizarThemeBody,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Actualiza la paleta de la empresa del usuario autenticado (tuerquita ⚙️).
    - portal = None o "todos" → cambia la paleta GENERAL y borra las paletas por
      portal (los 3 frontends quedan iguales).
    - portal = "admin" | "portal" | "repogemin" → guarda una paleta SOLO para ese
      portal; los demás siguen con la general.
    """
    if not user.company_id:
        raise HTTPException(status_code=403, detail="Usuario sin empresa asociada")

    config = db.query(TenantConfig).filter(TenantConfig.company_id == user.company_id).first()
    if not config:
        config = TenantConfig(company_id=user.company_id)
        db.add(config)

    portal = (body.portal or "todos").lower()
    if portal not in PORTALES_VALIDOS and portal != "todos":
        raise HTTPException(status_code=400, detail=f"Portal inválido: {body.portal}")

    if portal == "todos":
        if body.paleta_id is not None:
            config.paleta_id = body.paleta_id
        if body.paleta_colores is not None:
            config.paleta_colores = body.paleta_colores
        if body.estilo_ui is not None:
            config.estilo_ui = body.estilo_ui
        config.paletas_portales = {}  # los 3 portales vuelven a la paleta general
    else:
        overrides = dict(config.paletas_portales or {})
        overrides[portal] = {
            "paleta_id": body.paleta_id,
            "colores": body.paleta_colores or {},
        }
        config.paletas_portales = overrides

    db.commit()
    logger.info(f"🎨 Paleta actualizada por {user.username} (company_id={user.company_id}, portal={portal})")
    return _theme_de_company(db, user.company_id, None if portal == "todos" else portal)


@router.get("/{company_id}/theme")
async def get_theme_de_empresa(
    company_id: int,
    portal: str = Query(None, description="admin | portal | repogemin"),
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Tema visual de una empresa específica (para previews desde el admin global)."""
    return _theme_de_company(db, company_id, portal)


# ═════════════════════════════════════════════════════════
# ENDPOINT PÚBLICO: GET /public/portal/{slug}
# Branding pre-login: los frontends lo usan para pintarse con
# los colores/logo de la empresa ANTES de autenticar.
# ═════════════════════════════════════════════════════════

public_router = APIRouter(prefix="/public", tags=["Public Branding"])


@public_router.get("/portal/{slug}")
async def branding_publico(
    slug: str,
    portal: str = Query(None, description="admin | portal | repogemin"),
    db: Session = Depends(get_db),
):
    """
    ENDPOINT PÚBLICO (sin auth). Devuelve SOLO el branding de la empresa por su
    slug: nombre, logo, paleta y estado. No expone datos operativos.
    """
    company = db.query(Company).filter(Company.slug == slug.strip().lower()).first()
    if not company:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    tema = _theme_de_company(db, company.id, portal)
    # Filtrar a lo estrictamente público
    return {
        "ok": True,
        "company_id": tema["company_id"],
        "empresa": tema["empresa"],
        "slug": tema["slug"],
        "activa": tema["activa"],
        "paleta_id": tema["paleta_id"],
        "paleta_colores": tema["paleta_colores"],
        "estilo_ui": tema["estilo_ui"],
        "logo_url": tema["logo_url"],
    }


# ═════════════════════════════════════════════════════════
# ENDPOINT PÚBLICO: POST /tenants/registro/completar
# ═════════════════════════════════════════════════════════

class RegistroCompletoBody(BaseModel):
    token: str
    # Datos de la empresa
    nit: Optional[str] = None
    nombre: Optional[str] = None
    tipo_estructura: str = "unica"  # unica | holding
    sub_empresas: list = []
    ciclo_reporte: str = "mensual"  # quincenal | mensual
    zona_horaria: str = "America/Bogota"
    # Contacto
    contacto_email: Optional[str] = None
    correo_drive: Optional[str] = None
    # Credenciales del admin (elegidas por la empresa)
    admin_password: str = Field(..., min_length=8)
    # Personalización visual
    paleta_id: str = "ocean"
    paleta_colores: dict = {}
    estilo_ui: str = "default"
    logo_url: Optional[str] = None
    # Drive (opcional — se puede configurar después)
    google_workspace_drive_id: Optional[str] = None


@router.post("/registro/completar")
async def completar_registro(
    body: RegistroCompletoBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    ENDPOINT PÚBLICO (sin JWT). Usa el token de invitación como autenticación.

    Completa el registro self-service de la empresa:
    1. Valida el token
    2. Actualiza Company con los datos finales
    3. Crea/actualiza TenantConfig
    4. Provisiona el Google Sheet (en background)
    5. Crea AdminUser con las credenciales elegidas por la empresa
    6. Invalida el token
    """
    # 1. Validar token
    invitacion = db.query(TenantInvitation).filter(
        TenantInvitation.token == body.token
    ).first()

    if not invitacion:
        raise HTTPException(status_code=404, detail="Token de invitación no válido.")
    if invitacion.usado:
        raise HTTPException(status_code=400, detail="Este enlace ya fue utilizado.")
    if invitacion.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Este enlace ha expirado.")

    company_id = invitacion.company_id
    company = db.query(Company).filter(Company.id == company_id, Company.activa == True).first()
    if not company:
        raise HTTPException(status_code=404, detail="Empresa no encontrada.")

    # Verificar que no haya sido completado antes
    config_existente = db.query(TenantConfig).filter(TenantConfig.company_id == company_id).first()
    if config_existente and config_existente.onboarding_completado:
        raise HTTPException(
            status_code=400,
            detail="Esta empresa ya completó su registro. Usa tus credenciales para ingresar."
        )

    # 2. Actualizar Company
    if body.nit:
        company.nit = body.nit
    if body.nombre:
        company.nombre = body.nombre
    if body.contacto_email:
        company.contacto_email = body.contacto_email

    # 3. Crear o actualizar TenantConfig
    config = config_existente or TenantConfig(company_id=company_id)
    if not config_existente:
        db.add(config)

    config.nit = body.nit or company.nit
    if body.contacto_email:
        config.contacto_email = body.contacto_email
    config.correo_drive = body.correo_drive or body.contacto_email or ""
    config.zona_horaria = body.zona_horaria
    config.tipo_estructura = body.tipo_estructura
    config.sub_empresas = body.sub_empresas
    config.ciclo_reporte = body.ciclo_reporte
    config.paleta_id = body.paleta_id
    config.paleta_colores = body.paleta_colores
    config.estilo_ui = body.estilo_ui
    if body.logo_url:
        config.logo_url = body.logo_url
    if body.google_workspace_drive_id:
        config.google_workspace_drive_id = body.google_workspace_drive_id
    config.onboarding_completado = True
    config.onboarding_step = 6

    db.flush()

    # 4. Crear AdminUser con las credenciales elegidas por la empresa
    # Generar username desde el email
    email_parte = body.contacto_email.split("@")[0].replace(".", "_").replace("+", "_")[:30]
    base_username = f"{email_parte}_{company_id}"
    username = base_username
    counter = 0
    while db.query(AdminUser).filter(AdminUser.username == username).first():
        counter += 1
        username = f"{base_username}_{counter}"

    tenant_admin = AdminUser(
        username=username,
        password_hash=pwd_context.hash(body.admin_password),
        nombre=f"Administrador — {company.nombre}",
        email=body.contacto_email,
        rol="admin",
        company_id=company_id,
        es_tenant_admin=True,
        activo=True,
        tenant_permisos={
            "tabla_viva": True,
            "reportes": True,
            "powerbi": False,
            "exportaciones": False,
        },
        permisos={
            "bots": True,       # Puede gestionar bots de SU empresa
            "correos": True,    # Directorio de correos de su empresa
            "usuarios": True,   # Gestionar sus sub-admins
            "validador": False,
            "reportes": False,
            "powerbi": False,
            "exportaciones": False,
            "consola": False,
        },
    )
    db.add(tenant_admin)

    # 5. Invalidar token
    invitacion.usado = True

    db.commit()
    db.refresh(tenant_admin)
    db.refresh(config)

    # 5b. Si es demo, iniciar el timer ahora (desde que completan el registro)
    demo_session = db.query(DemoSession).filter(
        DemoSession.company_id == company_id,
        DemoSession.activa == True,
    ).first()
    if demo_session:
        demo_session.expires_at = datetime.utcnow() + timedelta(hours=demo_session.horas)
        db.commit()

    # 6. Tareas background: Sheet + estructura de carpetas en Drive del cliente
    email_para_bg = body.contacto_email or company.contacto_email or ""
    background_tasks.add_task(
        _provisionar_sheet_background,
        company_id=company_id,
        company_nombre=company.nombre,
        contacto_email=email_para_bg,
        tipo_estructura=body.tipo_estructura,
        sub_empresas=body.sub_empresas,
    )
    background_tasks.add_task(
        _crear_estructura_drive_background,
        company_id=company_id,
        company_nombre=company.nombre,
        tipo_estructura=body.tipo_estructura,
        sub_empresas=body.sub_empresas,
    )

    # 7. Generar JWT para auto-login inmediato
    es_tenant_admin = True
    access_token = create_access_token(data={
        "sub": tenant_admin.username,
        "rol": tenant_admin.rol,
        "es_tenant_admin": es_tenant_admin,
        "company_id": company_id,
    })

    logger.info(
        f"✅ Registro completado: empresa='{company.nombre}' "
        f"company_id={company_id} admin_username={username}"
    )

    return {
        "ok": True,
        "mensaje": f"¡Empresa '{company.nombre}' registrada exitosamente!",
        "company": {
            "id": company.id,
            "nombre": company.nombre,
            "nit": config.nit,
        },
        "admin_username": username,
        "ciclo_reporte": config.ciclo_reporte,
        # Para auto-login en el frontend
        "token": access_token,
        "user": {
            "id": tenant_admin.id,
            "username": tenant_admin.username,
            "nombre": tenant_admin.nombre,
            "email": tenant_admin.email,
            "rol": tenant_admin.rol,
            "company_id": company_id,
            "empresa": company.nombre,
            "permisos": tenant_admin.permisos or {},
            "es_tenant_admin": es_tenant_admin,
            "tenant_permisos": tenant_admin.tenant_permisos or {},
        },
    }


async def _provisionar_sheet_background(
    company_id: int,
    company_nombre: str,
    contacto_email: str,
    tipo_estructura: str = "unica",
    sub_empresas: list = None,
):
    """
    Tarea en background: crea el Sheet (con pestañas para holdings) y guarda el ID en TenantConfig.
    Registra el resultado en sheet_status ('ok' | 'error') para que el admin lo vea y pueda reintentar.
    """
    from app.database import SessionLocal

    def _marcar(status: str, error: str = None):
        db = SessionLocal()
        try:
            config = db.query(TenantConfig).filter(TenantConfig.company_id == company_id).first()
            if config:
                config.sheet_status = status
                if error is not None:
                    config.provision_error = error[:2000]
                elif status == "ok":
                    config.provision_error = None
                db.commit()
        finally:
            db.close()

    try:
        from app.services.tenant_provisioning import provisionar_tenant_completo

        resultado = provisionar_tenant_completo(
            company_nombre,
            company_id,
            contacto_email,
            tipo_estructura=tipo_estructura,
            sub_empresas=sub_empresas or [],
        )

        if resultado.get("google_sheets_id"):
            db = SessionLocal()
            try:
                config = db.query(TenantConfig).filter(TenantConfig.company_id == company_id).first()
                if config:
                    config.google_sheets_id = resultado["google_sheets_id"]
                    config.google_sheets_url = resultado["google_sheets_url"]
                    config.sheet_status = "ok"
                    config.provision_error = None
                    db.commit()
                    logger.info(f"✅ Sheet guardado en TenantConfig para company_id={company_id}")
            finally:
                db.close()
        else:
            _marcar("error", "El aprovisionamiento no devolvió un Sheet (revisa credenciales/carpeta de Drive)")
            logger.error(f"❌ Provisionamiento sin Sheet para company_id={company_id}")
    except Exception as e:
        _marcar("error", str(e))
        logger.error(f"❌ Error en provisionamiento background para company_id={company_id}: {e}")


async def _crear_estructura_drive_background(
    company_id: int,
    company_nombre: str,
    tipo_estructura: str = "unica",
    sub_empresas: list = None,
):
    """
    Crea la estructura inicial de carpetas en el Drive del cliente.
    Se ejecuta en background tras completar_registro.

    Estructura creada:
      [client_drive_id]
        └── EmpresaX/           ← o una carpeta por sub-empresa en holdings
              └── 2026/
                    └── <quincena actual>/
    """
    from app.database import SessionLocal, TenantConfig
    from datetime import datetime

    db = SessionLocal()
    try:
        config = db.query(TenantConfig).filter(TenantConfig.company_id == company_id).first()
        if not config or not config.google_workspace_drive_id:
            if config:
                config.drive_status = "sin_drive"
                db.commit()
            logger.warning(
                f"⚠️ Sin carpeta Drive configurada para company_id={company_id} — estructura omitida"
            )
            return

        client_drive_id = config.google_workspace_drive_id

        from app.drive_uploader import get_authenticated_service, create_folder_if_not_exists, get_periodo_folder_name

        service = get_authenticated_service()
        año_actual = str(datetime.now().year)
        # Respeta el ciclo elegido en el onboarding: mensual → 'Julio', quincenal → 'Primera_Quincena_Julio'
        quinzena_nombre = get_periodo_folder_name(config.ciclo_reporte)

        # Para holdings crear una subcarpeta por sub-empresa; para individuales usar el nombre de la empresa
        empresas = sub_empresas if (tipo_estructura == "holding" and sub_empresas) else [company_nombre]

        for emp in empresas:
            emp_nombre = emp.strip()
            emp_folder_id = create_folder_if_not_exists(
                service,
                emp_nombre.encode(),
                client_drive_id,
            )
            year_folder_id = create_folder_if_not_exists(
                service,
                año_actual.encode(),
                emp_folder_id,
            )
            create_folder_if_not_exists(
                service,
                quinzena_nombre.encode(),
                year_folder_id,
            )
            logger.info(f"✅ Carpeta Drive creada: {emp_nombre}/{año_actual}/{quinzena_nombre}")

        config.drive_status = "ok"
        db.commit()
        logger.info(f"✅ Estructura Drive lista para '{company_nombre}' (company_id={company_id})")

    except Exception as e:
        try:
            if config:
                config.drive_status = "error"
                config.provision_error = str(e)[:2000]
                db.commit()
        except Exception:
            db.rollback()
        logger.error(f"❌ Error creando estructura Drive para company_id={company_id}: {e}")
    finally:
        db.close()


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
        from app.drive_uploader import get_authenticated_service
        service = get_authenticated_service()
        meta = service.files().get(
            fileId=drive_folder_id,
            fields="name,id",
            supportsAllDrives=True,
        ).execute()
        carpeta_nombre = meta.get("name", drive_folder_id)

        result = service.files().list(
            q=f"'{drive_folder_id}' in parents and trashed=false",
            fields="files(id,name,mimeType)",
            pageSize=20,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()

        archivos = result.get("files", [])
        estructura = [{"name": f["name"], "nuevo": False} for f in archivos]

        return {
            "acceso": True,
            "carpeta_nombre": carpeta_nombre,
            "estructura": estructura,
            "error": None,
        }
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
            "google_sheets_id": config.google_sheets_id,
            "google_sheets_url": config.google_sheets_url,
            "sheet_status": config.sheet_status or "pendiente",
            "drive_status": config.drive_status or "pendiente",
            "provision_error": config.provision_error,
        }

    from app.services.portal_links import links_de_company
    return {
        "ok": True,
        "id": company.id,
        "nombre": company.nombre,
        "nit": company.nit or (config.nit if config else None),
        "contacto_email": company.contacto_email,
        "activa": company.activa,
        "slug": company.slug,
        "links": links_de_company(company.slug),
        "tenant_config": config_data,
    }


# ═══════════════════════════════════════════════════════════
# ENDPOINT: POST /tenants/{company_id}/reprovisionar
# Reintenta el aprovisionamiento (Sheet y/o estructura Drive)
# cuando las tareas background fallaron.
# ═══════════════════════════════════════════════════════════

@router.post("/{company_id}/reprovisionar")
async def reprovisionar_tenant(
    company_id: int,
    background_tasks: BackgroundTasks,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Re-lanza el aprovisionamiento en background:
    - Sheet: SOLO si aún no existe (evita duplicados en Drive).
    - Estructura Drive: siempre (create_folder_if_not_exists es idempotente).
    Permitido para admins globales y para el tenant admin de ESA empresa.
    """
    if user.company_id and user.company_id != company_id:
        raise HTTPException(status_code=403, detail="No puedes reaprovisionar otra empresa")
    if not user.company_id and user.rol not in ("superadmin", "admin"):
        raise HTTPException(status_code=403, detail="Sin permisos")

    company = _get_or_404(db, company_id)
    config = db.query(TenantConfig).filter(TenantConfig.company_id == company_id).first()
    if not config:
        raise HTTPException(status_code=400, detail="La empresa aún no tiene configuración (onboarding sin iniciar)")

    acciones = []

    # Sheet: solo si no existe todavía
    if not config.google_sheets_id:
        config.sheet_status = "pendiente"
        config.provision_error = None
        db.commit()
        background_tasks.add_task(
            _provisionar_sheet_background,
            company_id=company_id,
            company_nombre=company.nombre,
            contacto_email=config.contacto_email or company.contacto_email or "",
            tipo_estructura=config.tipo_estructura or "unica",
            sub_empresas=config.sub_empresas or [],
        )
        acciones.append("sheet")

    # Estructura Drive: siempre que haya carpeta del cliente (idempotente)
    if config.google_workspace_drive_id:
        config.drive_status = "pendiente"
        db.commit()
        background_tasks.add_task(
            _crear_estructura_drive_background,
            company_id=company_id,
            company_nombre=company.nombre,
            tipo_estructura=config.tipo_estructura or "unica",
            sub_empresas=config.sub_empresas or [],
        )
        acciones.append("drive")

    if not acciones:
        return {
            "ok": True,
            "acciones": [],
            "mensaje": "Nada que reaprovisionar: el Sheet ya existe y no hay carpeta Drive configurada.",
        }

    logger.info(f"♻️ Reaprovisionamiento de company_id={company_id} por {user.username}: {acciones}")
    return {
        "ok": True,
        "acciones": acciones,
        "mensaje": f"Reaprovisionamiento en marcha ({' + '.join(acciones)}). Revisa el estado en unos segundos.",
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
    background_tasks: BackgroundTasks,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Verifica que la Service Account tenga acceso a la carpeta de Drive especificada.
    Si tiene acceso, marca drive_verificado=True en TenantConfig y crea la
    estructura de carpetas (Empresa/Año/Quincena) si aún no existe.
    """
    company = _get_or_404(db, company_id)

    resultado = _verificar_acceso_drive(body.drive_folder_id)

    if resultado["acceso"]:
        config = _get_or_create_config(db, company_id)
        config.google_workspace_drive_id = body.drive_folder_id
        config.drive_verificado = True
        if body.correo_drive:
            config.correo_drive = body.correo_drive
        db.commit()

        # La estructura solo se crea en el registro si la carpeta ya estaba
        # configurada; si el cliente la conecta después, este es el único
        # punto donde podemos crearla. create_folder_if_not_exists es
        # idempotente, así que repetir la verificación no duplica carpetas.
        background_tasks.add_task(
            _crear_estructura_drive_background,
            company_id=company_id,
            company_nombre=company.nombre,
            tipo_estructura=config.tipo_estructura or "unica",
            sub_empresas=config.sub_empresas or [],
        )

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
