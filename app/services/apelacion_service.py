"""
APELACIONES — seguimiento de negaciones apelables y de casos incompletos que
ya se completaron y necesitan volver a radicarse.
=============================================================================

Qué problema cierra este módulo
--------------------------------
`recobro_service.cruce()` ya sabe distinguir una negación `apelable` de una
`en_firme` (vía `motivos.clasificar_negacion`, que resuelve el artículo que la
sustenta). Y `Case.EstadoCaso` ya sabe cuándo un caso quedó `INCOMPLETA`. Lo
que no existía era un lugar donde quedara **la decisión y el seguimiento**:
quién decidió apelar, con qué justificación, qué cambió, y si el reenvío al
portal ya se hizo y qué respondió la EPS.

Este servicio no reclasifica nada — reusa lo que ya existe — solo abre y
cierra el ciclo de una apelación:

    1. crear_apelacion()     — el validador decide apelar o reintentar
    2. listar_apelaciones()  — seguimiento por empresa/estado
    3. marcar_radicada()     — se generó el reenvío (queda el enlace a
                                radicacion_cola, el reenvío real lo hace el
                                flujo de radicación normal, no este módulo)
    4. resolver_apelacion()  — la EPS ya respondió al reenvío

Nada aquí dispara un bot ni toca el portal: es puro seguimiento en BD, así
que no hay nada que revertir si algo sale mal.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.database import Apelacion, Case, RadicacionCola, RecobroFila

logger = logging.getLogger(__name__)

MAX_LIMITE = 500
TIPOS_VALIDOS = {"negacion_apelable", "incompleta_completada"}
ESTADOS_VALIDOS = {"pendiente", "radicada", "resuelta", "descartada"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def crear_apelacion(
    db: Session,
    *,
    cedula: str,
    empresa: str,
    eps_key: str,
    tipo: str,
    creado_por: Optional[str] = None,
    case_id: Optional[int] = None,
    recobro_fila_id: Optional[int] = None,
    radicacion_cola_id: Optional[int] = None,
    motivo_codigo: Optional[str] = None,
    motivo_original: Optional[str] = None,
    justificacion: Optional[str] = None,
    datos_corregidos: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Registra la decisión de apelar una negación o reintentar un caso
    completado. No valida contra el portal ni dispara nada — es la bitácora.
    """
    if tipo not in TIPOS_VALIDOS:
        raise ValueError(f"tipo debe ser uno de {TIPOS_VALIDOS}, llegó '{tipo}'")

    # Evita duplicar: si ya hay una apelación pendiente/radicada para la misma
    # fila de recobro o el mismo caso, no se abre una segunda en paralelo.
    dup_q = db.query(Apelacion).filter(
        Apelacion.estado.in_(["pendiente", "radicada"]),
        Apelacion.tipo == tipo,
    )
    if recobro_fila_id is not None:
        dup_q = dup_q.filter(Apelacion.recobro_fila_id == recobro_fila_id)
    elif case_id is not None:
        dup_q = dup_q.filter(Apelacion.case_id == case_id)
    else:
        dup_q = dup_q.filter(Apelacion.cedula == cedula, Apelacion.empresa == empresa)
    existente = dup_q.first()
    if existente:
        return {"creada": False, "motivo": "Ya existe una apelación abierta para este caso",
                "apelacion": _serializar(existente)}

    fila = Apelacion(
        cedula=cedula, empresa=empresa, eps_key=eps_key, tipo=tipo,
        case_id=case_id, recobro_fila_id=recobro_fila_id, radicacion_cola_id=radicacion_cola_id,
        motivo_codigo=motivo_codigo, motivo_original=motivo_original,
        justificacion=justificacion, datos_corregidos=datos_corregidos or {},
        creado_por=creado_por, estado="pendiente",
    )
    db.add(fila)
    db.commit()
    db.refresh(fila)
    logger.info(f"Apelación #{fila.id} creada ({tipo}) para cédula {cedula} — {empresa}/{eps_key}")
    return {"creada": True, "apelacion": _serializar(fila)}


def listar_apelaciones(
    db: Session,
    empresa: Optional[str] = None,
    estado: Optional[str] = None,
    cedula: Optional[str] = None,
    limite: int = 200,
    offset: int = 0,
) -> Dict[str, Any]:
    limite = min(max(limite, 1), MAX_LIMITE)
    q = db.query(Apelacion)
    if empresa:
        q = q.filter(Apelacion.empresa == empresa)
    if estado:
        q = q.filter(Apelacion.estado == estado)
    if cedula:
        q = q.filter(Apelacion.cedula == cedula)
    total = q.count()
    filas = q.order_by(Apelacion.creado_en.desc()).limit(limite).offset(offset).all()
    return {"total": total, "limite": limite, "offset": offset,
            "items": [_serializar(f) for f in filas]}


def marcar_radicada(db: Session, apelacion_id: int, radicacion_cola_id: int) -> Dict[str, Any]:
    """Enlaza la apelación con el item de radicacion_cola que la reenvió al portal."""
    fila = db.query(Apelacion).get(apelacion_id)
    if not fila:
        raise ValueError(f"Apelación {apelacion_id} no existe")
    fila.radicacion_cola_id = radicacion_cola_id
    fila.estado = "radicada"
    db.commit()
    db.refresh(fila)
    return _serializar(fila)


def resolver_apelacion(db: Session, apelacion_id: int, resultado: str, estado: str = "resuelta") -> Dict[str, Any]:
    if estado not in ESTADOS_VALIDOS:
        raise ValueError(f"estado debe ser uno de {ESTADOS_VALIDOS}, llegó '{estado}'")
    fila = db.query(Apelacion).get(apelacion_id)
    if not fila:
        raise ValueError(f"Apelación {apelacion_id} no existe")
    fila.estado = estado
    fila.resultado = resultado
    fila.resuelto_en = _utc_now()
    db.commit()
    db.refresh(fila)
    return _serializar(fila)


def _serializar(f: Apelacion) -> Dict[str, Any]:
    return {
        "id": f.id, "cedula": f.cedula, "empresa": f.empresa, "eps_key": f.eps_key,
        "tipo": f.tipo, "case_id": f.case_id, "recobro_fila_id": f.recobro_fila_id,
        "radicacion_cola_id": f.radicacion_cola_id,
        "motivo_codigo": f.motivo_codigo, "motivo_original": f.motivo_original,
        "justificacion": f.justificacion, "datos_corregidos": f.datos_corregidos or {},
        "estado": f.estado, "resultado": f.resultado, "creado_por": f.creado_por,
        "creado_en": f.creado_en.isoformat() if f.creado_en else None,
        "resuelto_en": f.resuelto_en.isoformat() if f.resuelto_en else None,
    }
