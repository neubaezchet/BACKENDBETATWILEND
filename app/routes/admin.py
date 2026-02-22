"""
RUTAS ADMIN - Portal Administrativo NeuroBarranquilla
======================================================
- Auth JWT (login, me)
- CRUD Correos de Notificación
- CRUD Usuarios Admin
- Health / Stats del sistema
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, text
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timedelta
import logging
import os

from jose import jwt, JWTError
from passlib.context import CryptContext

from app.database import (
    get_db, AdminUser, Company, CorreoNotificacion, AlertaEmail,
    Case, Employee, Alerta180Log, CaseEvent, EstadoCaso
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin Portal"])

# ═══════════════════════════════════════════════════════════
# AUTH CONFIG
# ═══════════════════════════════════════════════════════════

SECRET_KEY = os.environ.get("ADMIN_JWT_SECRET", "neurobaeza-admin-secret-2026-change-in-prod")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> AdminUser:
    """Valida JWT y retorna el usuario admin"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Token requerido")
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Token inválido")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token expirado o inválido")

    user = db.query(AdminUser).filter(AdminUser.username == username, AdminUser.activo == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="Usuario no encontrado o inactivo")
    return user


def require_role(*roles):
    """Dependency factory: requiere uno de los roles indicados"""
    def checker(user: AdminUser = Depends(get_current_user)):
        if user.rol not in roles:
            raise HTTPException(status_code=403, detail=f"Rol '{user.rol}' sin permisos. Se requiere: {', '.join(roles)}")
        return user
    return checker


# ═══════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    username: str
    password: str

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=6)

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)
    nombre: Optional[str] = None
    email: Optional[str] = None
    rol: str = Field("viewer", description="superadmin | admin | th | sst | nomina | viewer")
    company_id: Optional[int] = None
    permisos: Optional[dict] = None

class UserUpdate(BaseModel):
    nombre: Optional[str] = None
    email: Optional[str] = None
    rol: Optional[str] = None
    company_id: Optional[int] = None
    permisos: Optional[dict] = None
    activo: Optional[bool] = None
    password: Optional[str] = None

class CorreoCreate(BaseModel):
    area: str = Field(..., description="alerta_180 | presunto_fraude | empresas")
    nombre_contacto: Optional[str] = None
    email: str
    company_id: Optional[int] = None

class CorreoUpdate(BaseModel):
    area: Optional[str] = None
    nombre_contacto: Optional[str] = None
    email: Optional[str] = None
    activo: Optional[bool] = None


# ═══════════════════════════════════════════════════════════
# 1. AUTH
# ═══════════════════════════════════════════════════════════

@router.post("/login")
async def login(data: LoginRequest, db: Session = Depends(get_db)):
    """🔐 Login - retorna JWT token"""
    user = db.query(AdminUser).filter(
        AdminUser.username == data.username,
        AdminUser.activo == True
    ).first()

    if not user or not pwd_context.verify(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")

    # Actualizar ultimo_login
    user.ultimo_login = datetime.now()
    db.commit()

    token = create_access_token({"sub": user.username, "rol": user.rol})
    return {
        "ok": True,
        "token": token,
        "user": {
            "id": user.id,
            "username": user.username,
            "nombre": user.nombre,
            "email": user.email,
            "rol": user.rol,
            "company_id": user.company_id,
            "empresa": user.empresa.nombre if user.empresa else None,
            "permisos": user.permisos or {},
        }
    }


@router.get("/me")
async def whoami(user: AdminUser = Depends(get_current_user)):
    """👤 Retorna datos del usuario autenticado"""
    return {
        "ok": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "nombre": user.nombre,
            "email": user.email,
            "rol": user.rol,
            "company_id": user.company_id,
            "empresa": user.empresa.nombre if user.empresa else None,
            "permisos": user.permisos or {},
        }
    }


@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """🔑 Envía correo de recuperación de contraseña"""
    user = db.query(AdminUser).filter(
        AdminUser.email == data.email,
        AdminUser.activo == True
    ).first()

    if not user:
        # No revelar si el email existe o no (seguridad)
        return {"ok": True, "mensaje": "Si el correo existe, recibirás un enlace de recuperación"}

    # Crear token de reset (15 min de vida)
    reset_token = jwt.encode(
        {"sub": user.username, "purpose": "reset", "exp": datetime.utcnow() + timedelta(minutes=15)},
        SECRET_KEY,
        algorithm=ALGORITHM
    )

    # Enviar email de recuperación
    try:
        from app.n8n_notifier import enviar_a_n8n

        portal_url = os.environ.get("PORTAL_URL", "https://repogemin.vercel.app")
        reset_link = f"{portal_url}?reset_token={reset_token}"

        html_recovery = f"""
        <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 500px; margin: 0 auto; padding: 30px; background: #f8fafc; border-radius: 12px;">
            <div style="text-align: center; margin-bottom: 24px;">
                <h2 style="color: #1e293b; margin: 0;">🔐 Recuperación de Contraseña</h2>
                <p style="color: #64748b; font-size: 14px;">Portal Incapacidades</p>
            </div>
            <div style="background: white; padding: 24px; border-radius: 8px; border: 1px solid #e2e8f0;">
                <p style="color: #334155;">Hola <strong>{user.nombre or user.username}</strong>,</p>
                <p style="color: #334155;">Recibimos una solicitud para restablecer tu contraseña.</p>
                <div style="text-align: center; margin: 24px 0;">
                    <a href="{reset_link}" style="display: inline-block; background: #2563eb; color: white; padding: 12px 32px; border-radius: 8px; text-decoration: none; font-weight: 600;">Restablecer Contraseña</a>
                </div>
                <p style="color: #94a3b8; font-size: 12px;">Este enlace expira en 15 minutos. Si no solicitaste esto, ignora este correo.</p>
            </div>
        </div>
        """

        enviar_a_n8n(
            tipo_notificacion="recuperacion",
            email=user.email,
            serial="RECOVERY",
            subject="🔐 Recuperación de contraseña - Portal Incapacidades",
            html_content=html_recovery,
        )
        logger.info(f"📧 Recovery email sent to {user.email} for user {user.username}")
    except Exception as e:
        logger.error(f"Error enviando email recovery: {e}")

    return {"ok": True, "mensaje": "Si el correo existe, recibirás un enlace de recuperación"}


@router.post("/reset-password")
async def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    """🔑 Restablece la contraseña usando el token de recuperación"""
    try:
        payload = jwt.decode(data.token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("purpose") != "reset":
            raise HTTPException(status_code=400, detail="Token inválido")
        username = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=400, detail="Token expirado o inválido")

    user = db.query(AdminUser).filter(AdminUser.username == username, AdminUser.activo == True).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    user.password_hash = pwd_context.hash(data.new_password)
    db.commit()

    logger.info(f"🔑 Password reset for user {username}")
    return {"ok": True, "mensaje": "Contraseña actualizada exitosamente"}


@router.post("/setup-superadmin")
async def setup_superadmin(data: LoginRequest, db: Session = Depends(get_db)):
    """
    🔧 Crea el primer superadmin (SOLO funciona si no existe NINGÚN AdminUser).
    Después de crear el primero, este endpoint se desactiva automáticamente.
    """
    existing = db.query(AdminUser).first()
    if existing:
        raise HTTPException(status_code=403, detail="Ya existe al menos un usuario admin. Usa /admin/users para crear más.")

    superadmin = AdminUser(
        username=data.username,
        password_hash=pwd_context.hash(data.password),
        nombre="Super Administrador",
        rol="superadmin",
        permisos={"validador": True, "reportes": True, "powerbi": True, "directorio": True, "consola": True},
        activo=True,
    )
    db.add(superadmin)
    db.commit()
    db.refresh(superadmin)

    token = create_access_token({"sub": superadmin.username, "rol": "superadmin"})
    return {
        "ok": True,
        "mensaje": f"Superadmin '{data.username}' creado exitosamente",
        "token": token,
    }


# ═══════════════════════════════════════════════════════════
# 2. CRUD USUARIOS
# ═══════════════════════════════════════════════════════════

@router.get("/users")
async def listar_usuarios(
    user: AdminUser = Depends(require_role("superadmin", "admin")),
    db: Session = Depends(get_db)
):
    """👥 Lista todos los usuarios admin"""
    users = db.query(AdminUser).order_by(AdminUser.created_at.desc()).all()
    return {
        "ok": True,
        "total": len(users),
        "users": [{
            "id": u.id,
            "username": u.username,
            "nombre": u.nombre,
            "email": u.email,
            "rol": u.rol,
            "company_id": u.company_id,
            "empresa": u.empresa.nombre if u.empresa else None,
            "permisos": u.permisos or {},
            "activo": u.activo,
            "ultimo_login": u.ultimo_login.isoformat() if u.ultimo_login else None,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        } for u in users]
    }


@router.post("/users")
async def crear_usuario(
    data: UserCreate,
    user: AdminUser = Depends(require_role("superadmin", "admin")),
    db: Session = Depends(get_db)
):
    """➕ Crea un nuevo usuario admin"""
    existente = db.query(AdminUser).filter(AdminUser.username == data.username).first()
    if existente:
        raise HTTPException(status_code=400, detail=f"Username '{data.username}' ya existe")

    if data.company_id:
        company = db.query(Company).filter(Company.id == data.company_id).first()
        if not company:
            raise HTTPException(status_code=404, detail="Empresa no encontrada")

    nuevo = AdminUser(
        username=data.username,
        password_hash=pwd_context.hash(data.password),
        nombre=data.nombre,
        email=data.email,
        rol=data.rol,
        company_id=data.company_id,
        permisos=data.permisos or {},
        activo=True,
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)

    return {"ok": True, "mensaje": f"Usuario '{data.username}' creado", "id": nuevo.id}


@router.put("/users/{user_id}")
async def actualizar_usuario(
    user_id: int,
    data: UserUpdate,
    user: AdminUser = Depends(require_role("superadmin", "admin")),
    db: Session = Depends(get_db)
):
    """✏️ Actualiza un usuario admin"""
    target = db.query(AdminUser).filter(AdminUser.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # Solo superadmin puede modificar otros superadmin
    if target.rol == "superadmin" and user.rol != "superadmin":
        raise HTTPException(status_code=403, detail="Solo superadmin puede modificar a otro superadmin")

    if data.nombre is not None:
        target.nombre = data.nombre
    if data.email is not None:
        target.email = data.email
    if data.rol is not None:
        target.rol = data.rol
    if data.company_id is not None:
        target.company_id = data.company_id if data.company_id != 0 else None
    if data.permisos is not None:
        target.permisos = data.permisos
    if data.activo is not None:
        target.activo = data.activo
    if data.password:
        target.password_hash = pwd_context.hash(data.password)

    db.commit()
    return {"ok": True, "mensaje": f"Usuario '{target.username}' actualizado"}


@router.delete("/users/{user_id}")
async def eliminar_usuario(
    user_id: int,
    user: AdminUser = Depends(require_role("superadmin")),
    db: Session = Depends(get_db)
):
    """🗑️ Elimina un usuario admin (solo superadmin)"""
    target = db.query(AdminUser).filter(AdminUser.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="No puedes eliminarte a ti mismo")

    username = target.username
    db.delete(target)
    db.commit()
    return {"ok": True, "mensaje": f"Usuario '{username}' eliminado"}


# ═══════════════════════════════════════════════════════════
# 3. CRUD CORREOS DE NOTIFICACIÓN
# ═══════════════════════════════════════════════════════════

@router.get("/correos")
async def listar_correos(
    area: str = Query("all"),
    empresa: str = Query("all"),
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """📧 Lista todos los correos de notificación con filtros"""
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

    resultado = [{
        "id": c.id,
        "area": c.area,
        "nombre_contacto": c.nombre_contacto,
        "email": c.email,
        "company_id": c.company_id,
        "empresa": c.empresa.nombre if c.empresa else "Global",
        "activo": c.activo,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    } for c in correos]

    # Resumen
    areas = {}
    for c in resultado:
        a = c["area"]
        if a not in areas:
            areas[a] = {"total": 0, "activos": 0}
        areas[a]["total"] += 1
        if c["activo"]:
            areas[a]["activos"] += 1

    return {"ok": True, "total": len(resultado), "por_area": areas, "correos": resultado}


@router.post("/correos")
async def crear_correo(
    data: CorreoCreate,
    user: AdminUser = Depends(require_role("superadmin", "admin")),
    db: Session = Depends(get_db)
):
    """➕ Crea un correo de notificación"""
    # Validar duplicado
    existente = db.query(CorreoNotificacion).filter(
        CorreoNotificacion.email == data.email,
        CorreoNotificacion.area == data.area,
        CorreoNotificacion.company_id == data.company_id,
    ).first()
    if existente:
        raise HTTPException(status_code=400, detail=f"'{data.email}' ya existe para área '{data.area}'")

    if data.company_id:
        company = db.query(Company).filter(Company.id == data.company_id).first()
        if not company:
            raise HTTPException(status_code=404, detail="Empresa no encontrada")

    nuevo = CorreoNotificacion(
        area=data.area,
        nombre_contacto=data.nombre_contacto,
        email=data.email,
        company_id=data.company_id,
        activo=True,
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)

    return {"ok": True, "mensaje": f"Correo '{data.email}' agregado a '{data.area}'", "id": nuevo.id}


@router.put("/correos/{correo_id}")
async def actualizar_correo(
    correo_id: int,
    data: CorreoUpdate,
    user: AdminUser = Depends(require_role("superadmin", "admin")),
    db: Session = Depends(get_db)
):
    """✏️ Actualiza un correo de notificación"""
    registro = db.query(CorreoNotificacion).filter(CorreoNotificacion.id == correo_id).first()
    if not registro:
        raise HTTPException(status_code=404, detail="Correo no encontrado")

    if data.area is not None:
        registro.area = data.area
    if data.nombre_contacto is not None:
        registro.nombre_contacto = data.nombre_contacto
    if data.email is not None:
        registro.email = data.email
    if data.activo is not None:
        registro.activo = data.activo

    db.commit()
    return {"ok": True, "mensaje": f"Correo actualizado"}


@router.delete("/correos/{correo_id}")
async def eliminar_correo(
    correo_id: int,
    user: AdminUser = Depends(require_role("superadmin", "admin")),
    db: Session = Depends(get_db)
):
    """🗑️ Elimina un correo de notificación"""
    registro = db.query(CorreoNotificacion).filter(CorreoNotificacion.id == correo_id).first()
    if not registro:
        raise HTTPException(status_code=404, detail="Correo no encontrado")

    email = registro.email
    db.delete(registro)
    db.commit()
    return {"ok": True, "mensaje": f"Correo '{email}' eliminado"}


# ═══════════════════════════════════════════════════════════
# 4. EMPRESAS (lectura para dropdowns)
# ═══════════════════════════════════════════════════════════

@router.get("/empresas")
async def listar_empresas(
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """📋 Lista empresas para dropdowns del admin"""
    empresas = db.query(Company).filter(Company.activa == True).order_by(Company.nombre).all()
    return {
        "ok": True,
        "empresas": [{
            "id": e.id,
            "nombre": e.nombre,
            "nit": e.nit,
            "contacto_email": e.contacto_email,
            "email_copia": e.email_copia,
        } for e in empresas]
    }


# ═══════════════════════════════════════════════════════════
# 5. CONSOLA DEL SISTEMA (stats / health)
# ═══════════════════════════════════════════════════════════

@router.get("/stats")
async def system_stats(
    user: AdminUser = Depends(require_role("superadmin", "admin")),
    db: Session = Depends(get_db)
):
    """📊 Estadísticas generales del sistema"""
    try:
        total_casos = db.query(func.count(Case.id)).scalar() or 0
        total_empleados = db.query(func.count(Employee.id)).scalar() or 0
        total_empresas = db.query(func.count(Company.id)).filter(Company.activa == True).scalar() or 0

        # Casos por estado
        estados = db.query(
            Case.estado, func.count(Case.id)
        ).group_by(Case.estado).all()
        por_estado = {str(e): c for e, c in estados}

        # Casos hoy
        hoy = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        casos_hoy = db.query(func.count(Case.id)).filter(Case.created_at >= hoy).scalar() or 0

        # Últimos eventos
        ultimos_eventos = db.query(CaseEvent).order_by(desc(CaseEvent.created_at)).limit(20).all()
        eventos = [{
            "id": ev.id,
            "case_id": ev.case_id,
            "tipo": ev.tipo,
            "detalle": ev.detalle,
            "fecha": ev.created_at.isoformat() if ev.created_at else None,
        } for ev in ultimos_eventos]

        # Alertas 180 recientes
        alertas_recientes = db.query(func.count(Alerta180Log.id)).filter(
            Alerta180Log.created_at >= hoy - timedelta(days=7)
        ).scalar() or 0

        return {
            "ok": True,
            "stats": {
                "total_casos": total_casos,
                "total_empleados": total_empleados,
                "total_empresas": total_empresas,
                "casos_hoy": casos_hoy,
                "por_estado": por_estado,
                "alertas_180_7d": alertas_recientes,
            },
            "ultimos_eventos": eventos,
        }
    except Exception as e:
        logger.error(f"Error stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def system_health(db: Session = Depends(get_db)):
    """🏥 Health check del sistema (público)"""
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    import platform
    return {
        "ok": db_ok,
        "database": "connected" if db_ok else "disconnected",
        "python": platform.python_version(),
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/activity")
async def recent_activity(
    limit: int = Query(50, le=200),
    user: AdminUser = Depends(require_role("superadmin", "admin")),
    db: Session = Depends(get_db)
):
    """📜 Actividad reciente del sistema"""
    try:
        eventos = db.query(CaseEvent).order_by(desc(CaseEvent.created_at)).limit(limit).all()
        return {
            "ok": True,
            "total": len(eventos),
            "actividad": [{
                "id": ev.id,
                "case_id": ev.case_id,
                "tipo": ev.tipo,
                "detalle": ev.detalle,
                "fecha": ev.created_at.isoformat() if ev.created_at else None,
            } for ev in eventos]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
