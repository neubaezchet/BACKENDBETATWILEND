"""
RUTAS DE APELACIONES — seguimiento de negaciones apelables y de casos
incompletos ya completados que hay que volver a radicar.
======================================================================
La lógica vive en app/services/apelacion_service.py; aquí solo hay transporte.
Autenticación: el mismo JWT admin del resto de radicación (get_current_user).
"""

from typing import Any, Dict, Optional
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db, AdminUser
from app.routes.radicacion import get_current_user
from app.services import apelacion_service as apelaciones

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/apelaciones", tags=["Apelaciones"])

MAX_LIMITE = 500


class CrearApelacion(BaseModel):
    cedula: str
    empresa: str
    eps_key: str
    tipo: str = Field(..., description="negacion_apelable | incompleta_completada")
    case_id: Optional[int] = None
    recobro_fila_id: Optional[int] = None
    radicacion_cola_id: Optional[int] = None
    motivo_codigo: Optional[str] = None
    motivo_original: Optional[str] = None
    justificacion: Optional[str] = None
    datos_corregidos: Optional[Dict[str, Any]] = None


@router.post("", summary="Registrar una apelación o un reintento de radicación")
async def crear(
    data: CrearApelacion,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return {"ok": True, **apelaciones.crear_apelacion(
            db, creado_por=user.username, **data.model_dump(),
        )}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("", summary="Listar apelaciones")
async def listar(
    empresa: Optional[str] = Query(None),
    estado: Optional[str] = Query(None),
    cedula: Optional[str] = Query(None),
    limite: int = Query(200, ge=1, le=MAX_LIMITE),
    offset: int = Query(0, ge=0),
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"ok": True, **apelaciones.listar_apelaciones(
        db, empresa=empresa, estado=estado, cedula=cedula, limite=limite, offset=offset,
    )}


class MarcarRadicada(BaseModel):
    radicacion_cola_id: int


@router.patch("/{apelacion_id}/radicada", summary="Enlazar la apelación con el reenvío al portal")
async def marcar_radicada(
    apelacion_id: int,
    data: MarcarRadicada,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return {"ok": True, "apelacion": apelaciones.marcar_radicada(db, apelacion_id, data.radicacion_cola_id)}
    except ValueError as e:
        raise HTTPException(404, str(e))


class ResolverApelacion(BaseModel):
    resultado: str
    estado: str = "resuelta"


@router.patch("/{apelacion_id}/resolver", summary="Registrar la respuesta de la EPS a la apelación")
async def resolver(
    apelacion_id: int,
    data: ResolverApelacion,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return {"ok": True, "apelacion": apelaciones.resolver_apelacion(db, apelacion_id, data.resultado, data.estado)}
    except ValueError as e:
        raise HTTPException(400, str(e))
