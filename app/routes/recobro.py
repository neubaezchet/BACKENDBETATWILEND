"""
RUTAS DE RECOBRO — cruce de lo radicado contra lo que la EPS pagó.
==================================================================
Usadas por:
  - Admin panel → ver el cruce, la cobertura y disparar la descarga de reportes
  - Portal      → histórico de incapacidades de una persona

La lógica vive en app/services/recobro_service.py; aquí solo hay transporte.
Autenticación: el mismo JWT admin del resto de radicación (get_current_user).
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db, AdminUser, RecobroFila, RecobroSync
from app.routes.radicacion import get_current_user
from app.services import recobro_service as recobro

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/recobro", tags=["Recobro"])

# Tope duro de página: el cruce de una empresa grande son miles de filas y
# devolverlas todas de un golpe tumba el navegador y el worker.
MAX_LIMITE = 500


def _a_fecha(valor: Optional[str], campo: str) -> Optional[date]:
    if not valor:
        return None
    try:
        return datetime.strptime(valor[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, f"'{campo}' debe tener formato YYYY-MM-DD, llegó '{valor}'")


# ─── GET /admin/recobro/cruce ────────────────────────────────────────────────

@router.get("/cruce", summary="Cruce radicado vs pagado")
async def obtener_cruce(
    empresa: str = Query(..., description="Nombre de la empresa"),
    eps: Optional[str] = Query(None, description="eps_key; vacío = todas"),
    desde: Optional[str] = Query(None, description="YYYY-MM-DD"),
    hasta: Optional[str] = Query(None, description="YYYY-MM-DD"),
    limite: int = Query(200, ge=1, le=MAX_LIMITE),
    offset: int = Query(0, ge=0),
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Cada incapacidad radicada con su situación real ante la EPS:
    pagada / rechazada / en_tramite / sin_respuesta / no_radicada.

    `cobertura` dice hasta qué fecha están descargados los reportes: sin eso,
    un "sin_respuesta" podría ser solo un reporte que no se ha bajado.
    """
    return {"ok": True, **recobro.cruce(
        db, empresa=empresa, eps_key=eps,
        desde=_a_fecha(desde, "desde"), hasta=_a_fecha(hasta, "hasta"),
        limite=limite, offset=offset,
    )}


# ─── GET /admin/recobro/historico/{cedula} ───────────────────────────────────

@router.get("/historico/{cedula}", summary="Histórico de incapacidades de una persona")
async def historico(
    cedula: str,
    empresa: str = Query(..., description="Nombre de la empresa"),
    eps: Optional[str] = Query(None),
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Trazabilidad completa de un trabajador, con los huecos entre una
    incapacidad y la siguiente (0 = prórroga continua, negativo = traslape).
    Se responde desde la base: no gasta un run de navegador.
    """
    return {"ok": True, **recobro.historico_persona(db, empresa, cedula, eps)}


# ─── GET /admin/recobro/cobertura ────────────────────────────────────────────

@router.get("/cobertura", summary="Hasta qué fecha está descargado cada reporte")
async def cobertura(
    empresa: Optional[str] = Query(None),
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(RecobroSync)
    if empresa:
        q = q.filter(RecobroSync.empresa == empresa)
    filas = q.order_by(RecobroSync.empresa, RecobroSync.eps_key, RecobroSync.origen).all()
    return {"ok": True, "total": len(filas), "items": [{
        "empresa": s.empresa, "eps": s.eps_key, "origen": s.origen,
        "cubierto_desde": s.cubierto_desde.isoformat() if s.cubierto_desde else None,
        "cubierto_hasta": s.cubierto_hasta.isoformat() if s.cubierto_hasta else None,
        "estado": s.ultimo_estado, "error": s.ultimo_error,
        "filas_totales": s.filas_totales,
        "ultimo_run_id": s.ultimo_run_id,
        "ultimo_sync": s.ultimo_sync_en.isoformat() if s.ultimo_sync_en else None,
    } for s in filas]}


# ─── POST /admin/recobro/descargar ───────────────────────────────────────────

class DescargaReporte(BaseModel):
    empresa: str
    eps: str
    origen: str = Field("radicadas", description="radicadas | pagadas")
    desde: Optional[str] = Field(None, description="YYYY-MM-DD; vacío = incremental")
    hasta: Optional[str] = Field(None, description="YYYY-MM-DD; vacío = hoy")


@router.post("/descargar", summary="Pedirle al portal un reporte (lanza el bot)")
async def descargar_reporte(
    data: DescargaReporte,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Lanza el run que descarga el reporte. NO espera: el ciclo del scheduler
    recoge el archivo cuando el run termina, lo parsea y lo ingesta.

    Sin `desde`/`hasta` pide solo lo nuevo desde lo ya cubierto (con solape),
    que es el modo normal: bajar mes por mes desde cero desgasta el bot y
    cuesta plata cuando la base ya tiene ese histórico.
    """
    if data.origen not in recobro.ORIGENES:
        raise HTTPException(400, f"origen debe ser uno de {recobro.ORIGENES}")

    resultado = await recobro.lanzar_reporte(
        db, empresa=data.empresa, eps_key=data.eps, origen=data.origen,
        desde=_a_fecha(data.desde, "desde"), hasta=_a_fecha(data.hasta, "hasta"),
    )
    if not resultado.get("ok"):
        raise HTTPException(400, resultado.get("error", "No se pudo lanzar el reporte"))
    return resultado


# ─── POST /admin/recobro/sincronizar ─────────────────────────────────────────

@router.post("/sincronizar", summary="Recoger e ingestar los reportes ya descargados")
async def sincronizar(
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fuerza un ciclo de ingesta sin esperar al scheduler."""
    return {"ok": True, **await recobro.sincronizar_reportes(db)}


# ─── GET /admin/recobro/filas ────────────────────────────────────────────────

@router.get("/filas", summary="Filas crudas del reporte (auditoría)")
async def listar_filas(
    empresa: str = Query(...),
    eps: Optional[str] = Query(None),
    origen: Optional[str] = Query(None),
    cedula: Optional[str] = Query(None),
    limite: int = Query(100, ge=1, le=MAX_LIMITE),
    offset: int = Query(0, ge=0),
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lo que dijo el portal, tal cual, para auditar una diferencia."""
    q = db.query(RecobroFila).filter(RecobroFila.empresa == empresa)
    if eps:
        q = q.filter(RecobroFila.eps_key == eps)
    if origen:
        q = q.filter(RecobroFila.origen == origen)
    if cedula:
        q = q.filter(RecobroFila.cedula == "".join(c for c in cedula if c.isdigit()))

    total = q.count()
    filas = (q.order_by(RecobroFila.fecha_inicio.desc().nullslast())
             .limit(limite).offset(offset).all())
    return {"ok": True, "total": total, "limite": limite, "offset": offset, "items": [{
        "id": f.id, "eps": f.eps_key, "origen": f.origen,
        "radicado": f.radicado, "numero_incapacidad": f.numero_incapacidad,
        "cedula": f.cedula, "nombre": f.nombre_trabajador,
        "fecha_inicio": f.fecha_inicio.isoformat() if f.fecha_inicio else None,
        "fecha_fin": f.fecha_fin.isoformat() if f.fecha_fin else None,
        "dias": f.dias, "diagnostico": f.diagnostico, "motivo": f.motivo,
        "estado_portal": f.estado_portal, "motivo_rechazo": f.motivo_rechazo,
        "valor_reconocido": f.valor_reconocido, "valor_pagado": f.valor_pagado,
        "fecha_pago": f.fecha_pago.isoformat() if f.fecha_pago else None,
        "cola_id": f.cola_id, "case_id": f.case_id,
        "datos_crudos": f.datos_crudos or {},
    } for f in filas]}
