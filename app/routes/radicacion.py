"""
RUTAS DE RADICACIÓN — Monitoreo en vivo + Skills + Manifests
=============================================================
Usadas por:
  - Admin panel  → leer estado de sesiones y skills (GET)
  - Browser-use  → registrar skills y reportar sesiones (POST/PUT)

Autenticación: Bearer JWT del admin (mismo que el portal).
Browser-use debe configurar NEUROBAEZA_BACKEND_TOKEN con un JWT válido.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, and_
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import logging
import os
import tempfile
from pathlib import Path

from jose import jwt, JWTError

from app.database import get_db, AdminUser, EmpresaBotConfig, RadicacionSkill, RadicacionSesion, RadicacionCola

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
    max_pdf_mb: Optional[float] = None               # Límite de peso del PDF en el portal

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
    # max_pdf_mb: límite de peso del archivo PDF para ese portal/email.
    # Portales web: típicamente 5 MB. Email: 10 MB (generosos).
    # El bot comprimirá el PDF ANTES de subir si supera este límite.
    "compensar":    {"nombre":"Compensar","tipo":"EPS","medio":"portal","skill":"activa","max_pdf_mb":5.0,"ocr":["N° documento","Tipo doc","Fecha inicio","Días","Diagnóstico CIE-10","Tipo incapacidad"],"manual":["PDF adjunto"],"cred":["NIT empresa","Contraseña"]},
    "nueva_eps":    {"nombre":"Nueva EPS","tipo":"EPS","medio":"portal","skill":"activa","max_pdf_mb":5.0,"ocr":["N° documento","Tipo doc","Fecha inicio","Días","Diagnóstico CIE-10"],"manual":["PDF adjunto","Tipo incapacidad"],"cred":["Usuario","Contraseña"]},
    "salud_total":  {"nombre":"Salud Total","tipo":"EPS","medio":"email","skill":"activa","max_pdf_mb":10.0,"ocr":["N° documento","Nombre trabajador","Fecha inicio","Días","Diagnóstico CIE-10"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "famisanar":    {"nombre":"Famisanar","tipo":"EPS","medio":"email","skill":"activa","max_pdf_mb":10.0,"ocr":["N° documento","Nombre trabajador","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "sura_eps":     {"nombre":"EPS SURA","tipo":"EPS","medio":"portal","skill":"pendiente","max_pdf_mb":5.0,"ocr":["N° documento","Tipo doc","Fecha inicio","Días","Diagnóstico CIE-10","Nombre trabajador"],"manual":["PDF adjunto"],"cred":["N° doc empresa","Tipo doc empresa","Clave"]},
    "sanitas":      {"nombre":"EPS Sanitas","tipo":"EPS","medio":"portal","skill":"pendiente","max_pdf_mb":5.0,"ocr":["N° documento","Tipo doc","Fecha inicio","Días"],"manual":["PDF adjunto","Diagnóstico CIE-10"],"cred":["Usuario","Contraseña"]},
    "medimas":      {"nombre":"Medimás","tipo":"EPS","medio":"portal","skill":"pendiente","max_pdf_mb":5.0,"ocr":["N° documento","Tipo doc","Fecha inicio","Días","Diagnóstico CIE-10","Tipo incapacidad"],"manual":["PDF adjunto","Municipio atención"],"cred":["Usuario","Contraseña"]},
    "coosalud":     {"nombre":"Coosalud","tipo":"EPS","medio":"email","skill":"pendiente","max_pdf_mb":10.0,"ocr":["N° documento","Nombre trabajador","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "colsanitas":   {"nombre":"Colsanitas","tipo":"EPS","medio":"portal","skill":"pendiente","max_pdf_mb":5.0,"ocr":["N° documento","Tipo doc","Fecha inicio","Días","Diagnóstico CIE-10"],"manual":["PDF adjunto"],"cred":["Usuario","Contraseña"]},
    "aliansalud":   {"nombre":"Aliansalud","tipo":"EPS","medio":"email","skill":"pendiente","max_pdf_mb":10.0,"ocr":["N° documento","Nombre trabajador","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "cruz_blanca":  {"nombre":"Cruz Blanca / Emssanar","tipo":"EPS","medio":"email","skill":"pendiente","max_pdf_mb":10.0,"ocr":["N° documento","Nombre trabajador","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "mutual_ser":   {"nombre":"Mutual Ser","tipo":"EPS","medio":"email","skill":"pendiente","max_pdf_mb":10.0,"ocr":["N° documento","Nombre trabajador","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "cafe_salud":   {"nombre":"Café Salud","tipo":"EPS","medio":"email","skill":"pendiente","max_pdf_mb":10.0,"ocr":["N° documento","Nombre trabajador","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "coomeva":      {"nombre":"Coomeva EPS","tipo":"EPS","medio":"portal","skill":"pendiente","max_pdf_mb":5.0,"ocr":["N° documento","Tipo doc","Fecha inicio","Días","Diagnóstico CIE-10"],"manual":["PDF adjunto"],"cred":["Usuario","Contraseña"]},
    "arl_sura":     {"nombre":"ARL SURA","tipo":"ARL","medio":"portal","skill":"pendiente","max_pdf_mb":5.0,"ocr":["N° documento","Tipo doc","Fecha inicio","Días","Diagnóstico CIE-10","Tipo accidente"],"manual":["PDF adjunto","N° caso ARL"],"cred":["Usuario","Contraseña"]},
    "positiva":     {"nombre":"ARL Positiva","tipo":"ARL","medio":"portal","skill":"pendiente","max_pdf_mb":5.0,"ocr":["N° documento","Tipo doc","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Usuario","Contraseña"]},
    "colmena":      {"nombre":"Colmena Seguros ARL","tipo":"ARL","medio":"portal","skill":"pendiente","max_pdf_mb":5.0,"ocr":["N° documento","Tipo doc","Fecha inicio","Días","Diagnóstico CIE-10"],"manual":["PDF adjunto"],"cred":["Usuario","Contraseña"]},
    "liberty":      {"nombre":"Liberty Seguros ARL","tipo":"ARL","medio":"email","skill":"pendiente","max_pdf_mb":10.0,"ocr":["N° documento","Nombre trabajador","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "bolivar":      {"nombre":"Seguros Bolívar ARL","tipo":"ARL","medio":"email","skill":"pendiente","max_pdf_mb":10.0,"ocr":["N° documento","Nombre trabajador","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "mapfre":       {"nombre":"Mapfre ARL","tipo":"ARL","medio":"email","skill":"pendiente","max_pdf_mb":10.0,"ocr":["N° documento","Nombre trabajador","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "equidad":      {"nombre":"La Equidad Seguros ARL","tipo":"ARL","medio":"email","skill":"pendiente","max_pdf_mb":10.0,"ocr":["N° documento","Nombre trabajador","Fecha inicio","Días"],"manual":["PDF adjunto"],"cred":["Correo destino"]},
    "axa_colpatria":{"nombre":"AXA Colpatria ARL","tipo":"ARL","medio":"portal","skill":"pendiente","max_pdf_mb":5.0,"ocr":["N° documento","Tipo doc","Fecha inicio","Días","Diagnóstico CIE-10"],"manual":["PDF adjunto"],"cred":["Usuario","Contraseña"]},
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

@router.get("/sesiones-cola", summary="Sesiones en espera (sistema legado)")
async def cola_sesiones_legado(
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Sesiones RadicacionSesion en estado 'esperando' (sistema anterior a la cola)."""
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
        if data.max_pdf_mb is not None: skill.max_pdf_mb = data.max_pdf_mb
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
            max_pdf_mb          = data.max_pdf_mb,
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


# ─── POST /admin/radicacion/comprimir-pdf ─────────────────────────────────────

@router.post("/comprimir-pdf", summary="Comprimir PDF antes de radicar (browser-use)")
async def comprimir_pdf_endpoint(
    archivo: UploadFile = File(...),
    eps_key: str = Form(...),
    tipo_incapacidad: str = Form("enfermedad_general"),
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Recibe un PDF y lo comprime al límite permitido por el portal de la EPS.

    El límite se obtiene de RadicacionSkill.max_pdf_mb (si ya fue guardado por el bot)
    o del valor por defecto en MANIFESTS. Aplica estrategia en cascada:
    1. Compresión técnica  →  2. Re-render 96 DPI  →  3. Eliminación de páginas
    no esenciales  →  4. Eliminar resúmenes extras.

    Los soportes requeridos según tipo_incapacidad nunca se eliminan.
    Devuelve el PDF comprimido con cabeceras indicando tamaños original y final.
    """
    from app.pdf_compressor import comprimir_pdf

    # Determinar límite: skill en BD > manifest > fallback 5 MB
    skill = db.query(RadicacionSkill).filter(RadicacionSkill.eps_key == eps_key).first()
    if skill and skill.max_pdf_mb:
        max_mb = skill.max_pdf_mb
    else:
        max_mb = MANIFESTS.get(eps_key, {}).get("max_pdf_mb", 5.0)

    content = await archivo.read()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        compressed = comprimir_pdf(tmp_path, max_mb, tipo_incapacidad)
    finally:
        tmp_path.unlink(missing_ok=True)

    filename = archivo.filename or "documento.pdf"
    return Response(
        content=compressed,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="comprimido_{filename}"',
            "X-Original-Size-Bytes": str(len(content)),
            "X-Compressed-Size-Bytes": str(len(compressed)),
            "X-Max-MB": str(max_mb),
            "X-EPS-Key": eps_key,
        },
    )


# ─── GET /admin/radicacion/manifests/{eps_key}/pdf-limit ──────────────────────

@router.get("/manifests/{eps_key}/pdf-limit", summary="Límite de PDF para una EPS")
async def get_pdf_limit(
    eps_key: str,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retorna el límite de peso de PDF vigente para la EPS.
    Primero consulta la BD (en caso de que el bot haya detectado un límite real),
    si no existe usa el valor por defecto del MANIFEST.
    """
    manifest = MANIFESTS.get(eps_key)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"EPS '{eps_key}' no encontrada en manifests")

    skill = db.query(RadicacionSkill).filter(RadicacionSkill.eps_key == eps_key).first()
    max_mb = (skill.max_pdf_mb if skill and skill.max_pdf_mb else None) or manifest.get("max_pdf_mb", 5.0)

    return {
        "ok": True,
        "eps_key": eps_key,
        "nombre": manifest["nombre"],
        "max_pdf_mb": max_mb,
        "fuente": "skill_bd" if (skill and skill.max_pdf_mb) else "manifest_default",
    }


# ══════════════════════════════════════════════════════════════════════════════
# COLA DE RADICACIÓN — Reintentos automáticos + Batch processing
# ══════════════════════════════════════════════════════════════════════════════

# Backoff escalado (índice = intentos completados hasta ahora)
_BACKOFF_MINUTOS = [5, 5, 20, 20, 60, 60, 240, 240, 480, 480]
_MAX_INTENTOS    = 12   # ~2 días de intentos antes de fallo definitivo

def _calcular_proximo_intento(intentos: int) -> datetime:
    """Retorna el datetime UTC del próximo intento según backoff escalado."""
    if intentos < len(_BACKOFF_MINUTOS):
        return datetime.utcnow() + timedelta(minutes=_BACKOFF_MINUTOS[intentos])
    # Intentos 10+ → próximo día a las 8 am Colombia (UTC-5 = 13:00 UTC)
    manana = (datetime.utcnow() + timedelta(days=1)).replace(
        hour=13, minute=0, second=0, microsecond=0
    )
    return manana


# ─── Schemas de cola ─────────────────────────────────────────────────────────

class ColaItemCreate(BaseModel):
    eps_key:          str
    empresa:          str
    tipo_incapacidad: str                    = "enfermedad_general"
    pdf_path:         Optional[str]          = None
    pdf_drive_url:    Optional[str]          = None
    datos_ocr:        Optional[Dict[str, Any]] = None
    datos_manuales:   Optional[Dict[str, Any]] = None
    serial_caso:      Optional[str]          = None
    case_id:          Optional[int]          = None

class ColaItemResult(BaseModel):
    """Browser-use llama PUT /cola/{item_id} con este body al terminar (bien o mal)."""
    estado:    str                    # exitosa | fallo_temporal | fallo_definitivo
    radicado:  Optional[str]  = None
    error:     Optional[str]  = None
    sesion_id: Optional[str]  = None


# ─── POST /admin/radicacion/cola ─────────────────────────────────────────────

@router.post("/cola", summary="Encolar radicación")
async def crear_item_cola(
    data: ColaItemCreate,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Agrega una radicación a la cola. El scheduler y browser-use la procesan
    automáticamente respetando el backoff de reintentos.
    """
    if data.eps_key not in MANIFESTS:
        raise HTTPException(status_code=400, detail=f"EPS '{data.eps_key}' no reconocida")

    item = RadicacionCola(
        serial_caso      = data.serial_caso,
        case_id          = data.case_id,
        empresa          = data.empresa,
        eps_key          = data.eps_key,
        tipo_incapacidad = data.tipo_incapacidad,
        pdf_path         = data.pdf_path,
        pdf_drive_url    = data.pdf_drive_url,
        datos_ocr        = data.datos_ocr or {},
        datos_manuales   = data.datos_manuales or {},
        estado           = "pendiente",
        intentos         = 0,
        proximo_intento  = datetime.utcnow(),   # disponible de inmediato
        historial_errores= [],
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    logger.info(f"Cola: nuevo item #{item.id} | {data.empresa} | {data.eps_key}")
    return {"ok": True, "id": item.id, "eps_key": data.eps_key}


# ─── GET /admin/radicacion/cola/siguiente ────────────────────────────────────

@router.get("/cola/siguiente", summary="Siguiente lote de radicaciones (browser-use)")
async def siguiente_lote(
    eps_key:    str,
    batch_size: int = 10,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Devuelve los próximos `batch_size` ítems pendientes para la EPS indicada.
    Browser-use los procesa en una sola sesión del portal (sin re-login).
    Marca los ítems como 'procesando' para evitar que otro worker los tome.
    """
    ahora = datetime.utcnow()
    items = (
        db.query(RadicacionCola)
        .filter(
            RadicacionCola.eps_key == eps_key,
            RadicacionCola.estado.in_(["pendiente", "fallo_temporal"]),
            RadicacionCola.proximo_intento <= ahora,
        )
        .order_by(RadicacionCola.creado_en)
        .limit(batch_size)
        .all()
    )

    if not items:
        return {"ok": True, "total": 0, "items": []}

    # Marcar como 'procesando'
    for item in items:
        item.estado = "procesando"
        item.actualizado_en = ahora
    db.commit()

    return {
        "ok": True,
        "total": len(items),
        "items": [_fmt_cola_item(i) for i in items],
    }


# ─── PUT /admin/radicacion/cola/{item_id} ────────────────────────────────────

@router.put("/cola/{item_id}", summary="Reportar resultado de radicación (browser-use)")
async def actualizar_item_cola(
    item_id: int,
    data: ColaItemResult,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Browser-use llama aquí al terminar cada radicación del lote.
    - exitosa         → guarda radicado, cierra el ítem
    - fallo_temporal  → incrementa intentos, calcula próximo reintento con backoff
    - fallo_definitivo→ ítem marcado como fallido definitivamente
    """
    item = db.query(RadicacionCola).filter(RadicacionCola.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Item #{item_id} no encontrado")

    ahora = datetime.utcnow()

    if data.sesion_id:
        item.sesion_id = data.sesion_id

    if data.estado == "exitosa":
        item.estado      = "exitosa"
        item.radicado    = data.radicado
        item.procesado_en = ahora

    elif data.estado == "fallo_definitivo":
        item.estado         = "fallo_definitivo"
        item.fallo_motivo   = data.error or "Fallo definitivo reportado por browser-use"
        item.ultimo_error   = data.error
        item.procesado_en   = ahora
        _agregar_historial(item, data.error, ahora)

    else:  # fallo_temporal
        item.intentos = (item.intentos or 0) + 1
        item.ultimo_error = data.error
        _agregar_historial(item, data.error, ahora)

        # ¿Se superó el límite de intentos o han pasado más de 48 h?
        horas_transcurridas = (ahora - item.creado_en).total_seconds() / 3600
        if item.intentos >= _MAX_INTENTOS or horas_transcurridas >= 48:
            item.estado = "fallo_definitivo"
            item.fallo_motivo = (
                f"Agotados {item.intentos} intentos en {horas_transcurridas:.1f} h. "
                f"Último error: {data.error}"
            )
            item.procesado_en = ahora
            logger.warning(f"Cola: item #{item_id} → fallo_definitivo tras {item.intentos} intentos")
        else:
            item.estado          = "fallo_temporal"
            item.proximo_intento = _calcular_proximo_intento(item.intentos)
            mins = int((item.proximo_intento - ahora).total_seconds() / 60)
            logger.info(
                f"Cola: item #{item_id} → reintento #{item.intentos} en {mins} min "
                f"({item.proximo_intento.strftime('%H:%M')} UTC)"
            )

    item.actualizado_en = ahora
    db.commit()
    return {"ok": True, "id": item_id, "estado": item.estado}


# ─── GET /admin/radicacion/cola ──────────────────────────────────────────────

@router.get("/cola", summary="Listar cola de radicaciones (admin)")
async def listar_cola(
    estado:   Optional[str] = None,   # filtro por estado
    eps_key:  Optional[str] = None,
    limit:    int = 50,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lista la cola para el panel admin. Soporta filtros por estado y EPS."""
    q = db.query(RadicacionCola)
    if estado:
        q = q.filter(RadicacionCola.estado == estado)
    if eps_key:
        q = q.filter(RadicacionCola.eps_key == eps_key)
    items = q.order_by(desc(RadicacionCola.creado_en)).limit(limit).all()
    return {"ok": True, "total": len(items), "items": [_fmt_cola_item(i) for i in items]}


# ─── GET /admin/radicacion/cola/stats ────────────────────────────────────────

@router.get("/cola/stats", summary="Estadísticas de la cola")
async def stats_cola(
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Conteo de ítems de la cola por estado y por EPS."""
    from sqlalchemy import case as sql_case

    totales = db.query(
        RadicacionCola.estado,
        func.count(RadicacionCola.id).label("cantidad"),
    ).group_by(RadicacionCola.estado).all()

    por_eps = db.query(
        RadicacionCola.eps_key,
        RadicacionCola.estado,
        func.count(RadicacionCola.id).label("cantidad"),
    ).group_by(RadicacionCola.eps_key, RadicacionCola.estado).all()

    proximos = (
        db.query(RadicacionCola)
        .filter(
            RadicacionCola.estado.in_(["pendiente", "fallo_temporal"]),
            RadicacionCola.proximo_intento <= datetime.utcnow() + timedelta(minutes=30),
        )
        .count()
    )

    return {
        "ok": True,
        "por_estado": {e: c for e, c in totales},
        "por_eps": [
            {"eps_key": eps, "estado": est, "cantidad": c}
            for eps, est, c in por_eps
        ],
        "listos_en_30min": proximos,
    }


# ─── DELETE /admin/radicacion/cola/{item_id} ─────────────────────────────────

@router.delete("/cola/{item_id}", summary="Eliminar ítem de la cola (admin)")
async def eliminar_item_cola(
    item_id: int,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Elimina un ítem de la cola (solo admin). Útil para cancelar radicaciones."""
    item = db.query(RadicacionCola).filter(RadicacionCola.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Item #{item_id} no encontrado")
    db.delete(item)
    db.commit()
    return {"ok": True, "id": item_id, "eliminado": True}


# ─── POST /admin/radicacion/cola/{item_id}/reintentar ────────────────────────

@router.post("/cola/{item_id}/reintentar", summary="Forzar reintento inmediato (admin)")
async def reintentar_item_cola(
    item_id: int,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Fuerza que un ítem fallo_definitivo o fallo_temporal vuelva a pendiente
    de inmediato. Útil cuando el admin sabe que el portal ya está disponible.
    """
    item = db.query(RadicacionCola).filter(RadicacionCola.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Item #{item_id} no encontrado")
    item.estado          = "pendiente"
    item.proximo_intento = datetime.utcnow()
    item.actualizado_en  = datetime.utcnow()
    db.commit()
    return {"ok": True, "id": item_id, "estado": "pendiente"}


# ─── Helpers de cola ─────────────────────────────────────────────────────────

def _agregar_historial(item: RadicacionCola, error: Optional[str], ts: datetime):
    """Appends an error entry to item.historial_errores (JSON list)."""
    historial = list(item.historial_errores or [])
    historial.append({
        "intento": item.intentos,
        "error":   (error or "")[:500],
        "ts":      ts.isoformat(),
    })
    item.historial_errores = historial


def _fmt_cola_item(i: RadicacionCola) -> dict:
    return {
        "id":               i.id,
        "serial_caso":      i.serial_caso,
        "empresa":          i.empresa,
        "eps_key":          i.eps_key,
        "tipo_incapacidad": i.tipo_incapacidad,
        # Archivos y datos del formulario — necesarios para que browser-use construya el task
        "pdf_path":         i.pdf_path,
        "pdf_drive_url":    i.pdf_drive_url,
        "datos_ocr":        i.datos_ocr or {},
        "datos_manuales":   i.datos_manuales or {},
        "estado":           i.estado,
        "intentos":         i.intentos,
        "proximo_intento":  i.proximo_intento.isoformat() if i.proximo_intento else None,
        "radicado":         i.radicado,
        "ultimo_error":     i.ultimo_error,
        "fallo_motivo":     i.fallo_motivo,
        "historial_errores":i.historial_errores or [],
        "sesion_id":        i.sesion_id,
        "creado_en":        i.creado_en.isoformat() if i.creado_en else None,
        "procesado_en":     i.procesado_en.isoformat() if i.procesado_en else None,
    }


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
