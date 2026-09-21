"""
RUTAS — Centro de Costos (servicios y suscripciones pagas)
============================================================
Panel único para ver TODOS los servicios/APIs que se deben pagar
(Google Workspace, Anthropic, Gemini, Mistral, GLM, Replicate, Browserbase,
CoreSoft, Railway, WhatsApp Business, OneDrive...), sus costos, próximas
fechas de cobro, estadísticas y alertas — sin exponer esta información a
usuarios tenant (solo superadmin/admin, es información financiera interna).
"""

import logging
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import Optional, List

from app.database import get_db, AdminUser, ServicioPago, ServicioPagoHistorial, ServicioPagoAlertaLog
from app.routes.admin import require_role
from app.services.servicios_pago import registrar_historial_si_cambio, verificar_alertas_servicios

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/servicios-pago",
    tags=["Centro de Costos"],
    dependencies=[Depends(require_role("superadmin", "admin"))],
)


# ═══════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════

class ServicioPagoCreate(BaseModel):
    nombre: str
    proveedor: Optional[str] = None
    categoria: str = "otros"
    costo_mensual: Optional[float] = None
    moneda: str = "COP"
    ciclo_facturacion: str = "mensual"
    fecha_proximo_cobro: Optional[date] = None
    dia_cobro: Optional[int] = None
    metodo_pago: Optional[str] = None
    url_panel: Optional[str] = None
    estado: str = "activo"
    tipo_verificacion: str = "ninguna"
    umbral_alerta_dias: int = 5
    umbral_alerta_credito_pct: int = 15
    email_alertas: Optional[str] = None
    whatsapp_alertas: Optional[str] = None
    notas: Optional[str] = None


class ServicioPagoUpdate(BaseModel):
    nombre: Optional[str] = None
    proveedor: Optional[str] = None
    categoria: Optional[str] = None
    costo_mensual: Optional[float] = None
    moneda: Optional[str] = None
    ciclo_facturacion: Optional[str] = None
    fecha_proximo_cobro: Optional[date] = None
    dia_cobro: Optional[int] = None
    metodo_pago: Optional[str] = None
    url_panel: Optional[str] = None
    estado: Optional[str] = None
    tipo_verificacion: Optional[str] = None
    umbral_alerta_dias: Optional[int] = None
    umbral_alerta_credito_pct: Optional[int] = None
    email_alertas: Optional[str] = None
    whatsapp_alertas: Optional[str] = None
    notas: Optional[str] = None
    activo: Optional[bool] = None


def _serializar(s: ServicioPago) -> dict:
    return {
        "id": s.id,
        "nombre": s.nombre,
        "proveedor": s.proveedor,
        "categoria": s.categoria,
        "costo_mensual": s.costo_mensual,
        "moneda": s.moneda,
        "ciclo_facturacion": s.ciclo_facturacion,
        "fecha_proximo_cobro": s.fecha_proximo_cobro.isoformat() if s.fecha_proximo_cobro else None,
        "dia_cobro": s.dia_cobro,
        "metodo_pago": s.metodo_pago,
        "url_panel": s.url_panel,
        "estado": s.estado,
        "tipo_verificacion": s.tipo_verificacion,
        "umbral_alerta_dias": s.umbral_alerta_dias,
        "umbral_alerta_credito_pct": s.umbral_alerta_credito_pct,
        "email_alertas": s.email_alertas,
        "whatsapp_alertas": s.whatsapp_alertas,
        "notas": s.notas,
        "activo": s.activo,
        "creado_en": s.creado_en.isoformat() if s.creado_en else None,
        "actualizado_en": s.actualizado_en.isoformat() if s.actualizado_en else None,
    }


# ═══════════════════════════════════════════════════════════
# LISTAR + ESTADÍSTICAS
# ═══════════════════════════════════════════════════════════

@router.get("")
def listar_servicios(
    incluir_archivados: bool = False,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(require_role("superadmin", "admin")),
):
    query = db.query(ServicioPago)
    if not incluir_archivados:
        query = query.filter(ServicioPago.activo == True)  # noqa: E712
    servicios = query.order_by(ServicioPago.categoria, ServicioPago.nombre).all()

    hoy = date.today()
    activos = [s for s in servicios if s.activo and s.estado != "pendiente"]

    # Costo mensual total: normaliza anual → /12, ignora servicios sin costo cargado
    gasto_mensual_total = 0.0
    for s in activos:
        if not s.costo_mensual:
            continue
        gasto_mensual_total += s.costo_mensual / 12 if s.ciclo_facturacion == "anual" else s.costo_mensual

    proximas_renovaciones = sorted(
        [s for s in activos if s.fecha_proximo_cobro and (s.fecha_proximo_cobro - hoy).days <= 15],
        key=lambda s: s.fecha_proximo_cobro,
    )

    alertas_activas = db.query(func.count(ServicioPagoAlertaLog.id)).filter(
        ServicioPagoAlertaLog.referencia_ciclo == hoy.strftime("%Y-%m")
    ).scalar() or 0

    return {
        "servicios": [_serializar(s) for s in servicios],
        "estadisticas": {
            "total_servicios": len(servicios),
            "servicios_activos": len(activos),
            "servicios_pendientes": len([s for s in servicios if s.estado == "pendiente"]),
            "servicios_en_riesgo": len([s for s in servicios if s.estado == "en_riesgo"]),
            "gasto_mensual_total_cop": round(gasto_mensual_total, 2),
            "proximas_renovaciones": [_serializar(s) for s in proximas_renovaciones],
            "alertas_este_mes": alertas_activas,
        },
    }


@router.get("/{servicio_id}/historial")
def historial_servicio(
    servicio_id: int,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(require_role("superadmin", "admin")),
):
    servicio = db.query(ServicioPago).filter(ServicioPago.id == servicio_id).first()
    if not servicio:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    historial = db.query(ServicioPagoHistorial).filter(
        ServicioPagoHistorial.servicio_id == servicio_id
    ).order_by(ServicioPagoHistorial.registrado_en.desc()).all()
    return [
        {
            "campo": h.campo,
            "valor_anterior": h.valor_anterior,
            "valor_nuevo": h.valor_nuevo,
            "registrado_en": h.registrado_en.isoformat() if h.registrado_en else None,
        }
        for h in historial
    ]


# ═══════════════════════════════════════════════════════════
# CRUD
# ═══════════════════════════════════════════════════════════

@router.post("")
def crear_servicio(
    payload: ServicioPagoCreate,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(require_role("superadmin", "admin")),
):
    servicio = ServicioPago(**payload.dict())
    db.add(servicio)
    db.commit()
    db.refresh(servicio)
    return _serializar(servicio)


@router.put("/{servicio_id}")
def actualizar_servicio(
    servicio_id: int,
    payload: ServicioPagoUpdate,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(require_role("superadmin", "admin")),
):
    servicio = db.query(ServicioPago).filter(ServicioPago.id == servicio_id).first()
    if not servicio:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")

    datos = payload.dict(exclude_unset=True)

    # Registrar historial antes de sobrescribir (para "si suben de precio")
    if "costo_mensual" in datos:
        registrar_historial_si_cambio(db, servicio, "costo_mensual", servicio.costo_mensual, datos["costo_mensual"])
    if "estado" in datos:
        registrar_historial_si_cambio(db, servicio, "estado", servicio.estado, datos["estado"])

    for campo, valor in datos.items():
        setattr(servicio, campo, valor)

    db.commit()
    db.refresh(servicio)
    return _serializar(servicio)


@router.delete("/{servicio_id}")
def archivar_servicio(
    servicio_id: int,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(require_role("superadmin", "admin")),
):
    """Archiva (no borra) — conserva el historial de un servicio que ya no se usa."""
    servicio = db.query(ServicioPago).filter(ServicioPago.id == servicio_id).first()
    if not servicio:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    servicio.activo = False
    db.commit()
    return {"ok": True, "mensaje": f"'{servicio.nombre}' archivado"}


@router.post("/verificar-ahora")
def verificar_ahora(
    user: AdminUser = Depends(require_role("superadmin", "admin")),
):
    """Dispara manualmente la revisión de alertas (misma lógica de la tarea diaria)."""
    resumen = verificar_alertas_servicios()
    return {"ok": True, **resumen}
