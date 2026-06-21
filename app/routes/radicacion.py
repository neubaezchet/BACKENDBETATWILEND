"""
RUTAS DE RADICACIÓN — Monitoreo en vivo + Skills + Manifests
=============================================================
Usadas por:
  - Admin panel  → leer estado de sesiones y skills (GET)
  - Browser-use  → registrar skills y reportar sesiones (POST/PUT)

Autenticación: Bearer JWT del admin (mismo que el portal).
Browser-use debe configurar NEUROBAEZA_BACKEND_TOKEN con un JWT válido.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
import logging
import os

from jose import jwt, JWTError

from app.database import get_db, AdminUser, EmpresaBotConfig, RadicacionSkill, RadicacionSesion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/radicacion", tags=["Radicación"])

SECRET_KEY    = os.environ.get("ADMIN_JWT_SECRET", "neurobaeza-admin-secret-2026-change-in-prod")
ALGORITHM     = "HS256"
SERVICE_TOKEN = os.environ.get("NEUROBAEZA_SERVICE_TOKEN", "")
security      = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> AdminUser:
    if not credentials:
        raise HTTPException(status_code=401, detail="Token requerido")

    # Token de servicio permanente (browser-use / bots internos)
    if SERVICE_TOKEN and credentials.credentials == SERVICE_TOKEN:
        user = db.query(AdminUser).filter(
            AdminUser.rol == "superadmin", AdminUser.activo == True
        ).first()
        if user:
            return user

    try:
        payload  = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Token inválido")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token expirado o inválido")
    user = db.query(AdminUser).filter(AdminUser.username == username, AdminUser.activo == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")
    return user


# ─── Schemas ──────────────────────────────────────────────────────────────────

class SkillUpdate(BaseModel):
    estado: str                     # activa | fallo | pendiente
    cache_key: Optional[str] = None
    script_path: Optional[str] = None
    tokens: Optional[int] = 0
    campos_credenciales: Optional[List[dict]] = None  # Schema dinámico del formulario de login

class SesionCreate(BaseModel):
    sesion_id: str
    empresa: str
    eps: str
    medio: str = "portal"
    documento: Optional[str] = None

class SesionUpdate(BaseModel):
    estado: str                         # en_curso | exitosa | fallida | enviado | error
    radicado: Optional[str] = None
    error: Optional[str] = None
    progreso: Optional[int] = None
    logs: Optional[List[str]] = None
    cached: Optional[bool] = None


# ─── Manifests (datos estáticos del catálogo) ─────────────────────────────────

MANIFESTS = {
    "compensar":    {"nombre":"Compensar","tipo":"EPS","medio":"portal","skill":"activa","ocr":["N° documento","Tipo doc","Fecha inicio","Días","Diagnóstico CIE-10","Tipo incapacidad"],"manual":["PDF adjunto"],"cred":["NIT empresa","Contraseña"]},
    "nueva_eps":    {"nombre":"Nueva EPS","tipo":"EPS","medio":"portal","skill":"activa","ocr":["N° documento","Tipo doc","Fecha inicio","Días","Diagnóstico CIE-10"],"manual":["PDF adjunto","Tipo incapacidad"],"cred":["Usuario","Contraseña"]},
    "salud_total":  {"nombre":"Salud Total","tipo":"EPS","medio":"email","skill":"activa","ocr":["N° documento","Nombre trabajador","Fecha inicio","Días","Diagnóstico CIE-10"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "famisanar":    {"nombre":"Famisanar","tipo":"EPS","medio":"email","skill":"activa","ocr":["N° documento","Nombre trabajador","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "sura_eps":     {"nombre":"EPS SURA","tipo":"EPS","medio":"portal","skill":"pendiente","ocr":["N° documento","Tipo doc","Fecha inicio","Días","Diagnóstico CIE-10","Nombre trabajador"],"manual":["PDF adjunto"],"cred":["N° doc empresa","Tipo doc empresa","Clave"]},
    "sanitas":      {"nombre":"EPS Sanitas","tipo":"EPS","medio":"portal","skill":"pendiente","ocr":["N° documento","Tipo doc","Fecha inicio","Días"],"manual":["PDF adjunto","Diagnóstico CIE-10"],"cred":["Usuario","Contraseña"]},
    "medimas":      {"nombre":"Medimás","tipo":"EPS","medio":"portal","skill":"pendiente","ocr":["N° documento","Tipo doc","Fecha inicio","Días","Diagnóstico CIE-10","Tipo incapacidad"],"manual":["PDF adjunto","Municipio atención"],"cred":["Usuario","Contraseña"]},
    "coosalud":     {"nombre":"Coosalud","tipo":"EPS","medio":"email","skill":"pendiente","ocr":["N° documento","Nombre trabajador","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "colsanitas":   {"nombre":"Colsanitas","tipo":"EPS","medio":"portal","skill":"pendiente","ocr":["N° documento","Tipo doc","Fecha inicio","Días","Diagnóstico CIE-10"],"manual":["PDF adjunto"],"cred":["Usuario","Contraseña"]},
    "aliansalud":   {"nombre":"Aliansalud","tipo":"EPS","medio":"email","skill":"pendiente","ocr":["N° documento","Nombre trabajador","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "cruz_blanca":  {"nombre":"Cruz Blanca / Emssanar","tipo":"EPS","medio":"email","skill":"pendiente","ocr":["N° documento","Nombre trabajador","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "mutual_ser":   {"nombre":"Mutual Ser","tipo":"EPS","medio":"email","skill":"pendiente","ocr":["N° documento","Nombre trabajador","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "cafe_salud":   {"nombre":"Café Salud","tipo":"EPS","medio":"email","skill":"pendiente","ocr":["N° documento","Nombre trabajador","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "coomeva":      {"nombre":"Coomeva EPS","tipo":"EPS","medio":"portal","skill":"pendiente","ocr":["N° documento","Tipo doc","Fecha inicio","Días","Diagnóstico CIE-10"],"manual":["PDF adjunto"],"cred":["Usuario","Contraseña"]},
    "arl_sura":     {"nombre":"ARL SURA","tipo":"ARL","medio":"portal","skill":"pendiente","ocr":["N° documento","Tipo doc","Fecha inicio","Días","Diagnóstico CIE-10","Tipo accidente"],"manual":["PDF adjunto","N° caso ARL"],"cred":["Usuario","Contraseña"]},
    "positiva":     {"nombre":"ARL Positiva","tipo":"ARL","medio":"portal","skill":"pendiente","ocr":["N° documento","Tipo doc","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Usuario","Contraseña"]},
    "colmena":      {"nombre":"Colmena Seguros ARL","tipo":"ARL","medio":"portal","skill":"pendiente","ocr":["N° documento","Tipo doc","Fecha inicio","Días","Diagnóstico CIE-10"],"manual":["PDF adjunto"],"cred":["Usuario","Contraseña"]},
    "liberty":      {"nombre":"Liberty Seguros ARL","tipo":"ARL","medio":"email","skill":"pendiente","ocr":["N° documento","Nombre trabajador","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "bolivar":      {"nombre":"Seguros Bolívar ARL","tipo":"ARL","medio":"email","skill":"pendiente","ocr":["N° documento","Nombre trabajador","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "mapfre":       {"nombre":"Mapfre ARL","tipo":"ARL","medio":"email","skill":"pendiente","ocr":["N° documento","Nombre trabajador","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "equidad":      {"nombre":"La Equidad Seguros ARL","tipo":"ARL","medio":"email","skill":"pendiente","ocr":["N° documento","Nombre trabajador","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "axa_colpatria":{"nombre":"AXA Colpatria ARL","tipo":"ARL","medio":"portal","skill":"pendiente","ocr":["N° documento","Tipo doc","Fecha inicio","Días","Diagnóstico CIE-10"],"manual":["PDF adjunto"],"cred":["Usuario","Contraseña"]},
}


# ─── GET /admin/bots/manifests ────────────────────────────────────────────────
# Este endpoint vive en admin_router pero lo ponemos aquí como alternativa

@router.get("/manifests", summary="Manifests de campos por EPS (GET)")
async def listar_manifests(user: AdminUser = Depends(get_current_user)):
    """Devuelve el manifest completo de campos OCR/manuales/credenciales por EPS"""
    return {
        "ok": True,
        "total": len(MANIFESTS),
        "manifests": MANIFESTS,
    }


# ─── GET /admin/radicacion/stats ──────────────────────────────────────────────

@router.get("/stats", summary="Estadísticas del lote actual")
async def stats_radicacion(
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Métricas globales de radicación (últimas 24 h)"""
    cutoff = datetime.utcnow() - timedelta(hours=24)
    sesiones = db.query(RadicacionSesion).filter(
        RadicacionSesion.iniciado_en >= cutoff
    ).all()

    total     = len(sesiones)
    exitosas  = sum(1 for s in sesiones if s.estado in ('exitosa', 'enviado'))
    en_curso  = sum(1 for s in sesiones if s.estado in ('en_curso', 'esperando'))
    fallidas  = sum(1 for s in sesiones if s.estado in ('fallida', 'error'))

    return {
        "ok": True,
        "total": total,
        "exitosas": exitosas,
        "en_curso": en_curso,
        "fallidas": fallidas,
        "periodo": "últimas 24 horas",
    }


# ─── GET /admin/radicacion/sesiones ───────────────────────────────────────────

@router.get("/sesiones", summary="Sesiones activas y recientes")
async def listar_sesiones(
    limit: int = 20,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lista sesiones de radicación ordenadas por más reciente"""
    sesiones = (
        db.query(RadicacionSesion)
        .order_by(desc(RadicacionSesion.iniciado_en))
        .limit(limit)
        .all()
    )
    return {
        "ok": True,
        "total": len(sesiones),
        "sesiones": [_fmt_sesion(s) for s in sesiones],
    }


# ─── GET /admin/radicacion/cola ───────────────────────────────────────────────

@router.get("/cola", summary="Cola de radicaciones pendientes")
async def cola_radicacion(
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Items en estado 'esperando'"""
    items = db.query(RadicacionSesion).filter(
        RadicacionSesion.estado == "esperando"
    ).order_by(RadicacionSesion.iniciado_en).all()

    return {
        "ok": True,
        "total": len(items),
        "items": [{"eps": s.eps, "empresa": s.empresa, "documento": s.documento, "sesion_id": s.sesion_id} for s in items],
    }


# ─── GET /admin/radicacion/skills ─────────────────────────────────────────────

@router.get("/skills", summary="Estado de skills por EPS")
async def listar_skills(
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lista el estado de cada skill registrada por browser-use"""
    skills_db = db.query(RadicacionSkill).order_by(RadicacionSkill.eps_key).all()
    skills_map = {s.eps_key: s for s in skills_db}

    resultado = []
    for key, manifest in MANIFESTS.items():
        s = skills_map.get(key)
        if s:
            estado = s.estado
            costo  = "$0" if s.cached_runs_free() else f"~${round(s.primer_run_tokens * 0.000003, 3)}"
        else:
            estado = "pendiente"
            costo  = "—"
        resultado.append({
            "key":    key,
            "nombre": manifest["nombre"],
            "estado": estado,
            "costo":  costo if s else "—",
            "usos":   s.usos_totales if s else 0,
            "ultimo_uso": s.ultimo_uso_at.isoformat() if s and s.ultimo_uso_at else None,
            "campos_credenciales": s.campos_credenciales if s else None,
        })

    return {"ok": True, "skills": resultado}


# ─── PUT /admin/radicacion/skills/{eps_key} ───────────────────────────────────
# Browser-use llama aquí después de generar o actualizar una skill.

@router.put("/skills/{eps_key}", summary="Registrar/actualizar skill desde browser-use")
async def registrar_skill(
    eps_key: str,
    data: SkillUpdate,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Browser-use llama esto después de generar un Playwright script cacheado"""
    skill = db.query(RadicacionSkill).filter(RadicacionSkill.eps_key == eps_key).first()

    if skill:
        skill.estado         = data.estado
        if data.cache_key:    skill.cache_key      = data.cache_key
        if data.script_path:  skill.script_path    = data.script_path
        if data.tokens:       skill.primer_run_tokens = data.tokens
        if data.campos_credenciales: skill.campos_credenciales = data.campos_credenciales
        skill.ultimo_uso_at  = datetime.utcnow()
        skill.usos_totales   = (skill.usos_totales or 0) + 1
        skill.actualizado_en = datetime.utcnow()
    else:
        skill = RadicacionSkill(
            eps_key             = eps_key,
            estado              = data.estado,
            cache_key           = data.cache_key,
            script_path         = data.script_path,
            primer_run_tokens   = data.tokens or 0,
            campos_credenciales = data.campos_credenciales,
            primer_run_at       = datetime.utcnow(),
            ultimo_uso_at       = datetime.utcnow(),
            usos_totales        = 1,
        )
        db.add(skill)

    db.commit()
    return {"ok": True, "eps_key": eps_key, "estado": data.estado}


# ─── POST /admin/radicacion/sesiones ──────────────────────────────────────────

@router.post("/sesiones", summary="Crear sesión de radicación (browser-use)")
async def crear_sesion(
    data: SesionCreate,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Browser-use llama esto al iniciar una radicación"""
    # Evitar duplicados
    existente = db.query(RadicacionSesion).filter(
        RadicacionSesion.sesion_id == data.sesion_id
    ).first()
    if existente:
        return {"ok": True, "id": existente.id, "sesion_id": existente.sesion_id}

    sesion = RadicacionSesion(
        sesion_id  = data.sesion_id,
        empresa    = data.empresa,
        eps        = data.eps,
        medio      = data.medio,
        documento  = data.documento,
        estado     = "en_curso",
        logs       = [],
    )
    db.add(sesion)
    db.commit()
    db.refresh(sesion)
    logger.info(f"Sesión creada: {data.sesion_id} | {data.empresa} | {data.eps}")
    return {"ok": True, "id": sesion.id, "sesion_id": sesion.sesion_id}


# ─── PUT /admin/radicacion/sesiones/{sesion_id} ───────────────────────────────

@router.put("/sesiones/{sesion_id}", summary="Actualizar sesión (browser-use)")
async def actualizar_sesion(
    sesion_id: str,
    data: SesionUpdate,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Browser-use actualiza el progreso de una sesión"""
    sesion = db.query(RadicacionSesion).filter(
        RadicacionSesion.sesion_id == sesion_id
    ).first()
    if not sesion:
        raise HTTPException(status_code=404, detail=f"Sesión '{sesion_id}' no encontrada")

    sesion.estado        = data.estado
    if data.radicado is not None:  sesion.radicado   = data.radicado
    if data.error is not None:     sesion.error_msg  = data.error
    if data.progreso is not None:  sesion.progreso   = data.progreso
    if data.cached is not None:    sesion.cached     = data.cached
    if data.logs is not None:      sesion.logs       = data.logs
    if data.estado in ('exitosa', 'fallida', 'enviado', 'error'):
        sesion.finalizado_en = datetime.utcnow()
    sesion.actualizado_en = datetime.utcnow()

    db.commit()
    return {"ok": True, "sesion_id": sesion_id, "estado": data.estado}


# ─── Helper ───────────────────────────────────────────────────────────────────

def _fmt_sesion(s: RadicacionSesion) -> dict:
    return {
        "sesion_id":   s.sesion_id,
        "empresa":     s.empresa,
        "eps":         s.eps,
        "medio":       s.medio,
        "documento":   s.documento,
        "estado":      s.estado,
        "radicado":    s.radicado,
        "error":       s.error_msg,
        "cached":      s.cached,
        "progreso":    s.progreso,
        "logs":        s.logs or [],
        "iniciado_en": s.iniciado_en.isoformat() if s.iniciado_en else None,
        "finalizado_en": s.finalizado_en.isoformat() if s.finalizado_en else None,
    }


# Parche para el método que usamos en GET skills
def _cached_runs_free(self):
    return self.usos_totales > 1 and self.estado == 'activa'

RadicacionSkill.cached_runs_free = _cached_runs_free
