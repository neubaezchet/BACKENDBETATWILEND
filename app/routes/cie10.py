"""
RUTAS CIE-10 - Endpoints de diagnóstico y detección de prórrogas
================================================================
Expone el motor CIE-10 y el detector de prórrogas vía REST API.
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, List
import logging

from app.database import get_db, AdminUser
from app.routes.radicacion import get_current_user
from app.services.linea_tiempo import linea_de_tiempo
from app.services.cie10_service import (
    buscar_codigo,
    son_correlacionados,
    son_correlacionados_auditoria,
    obtener_todos_correlacionados,
    validar_dias,
    validar_dias_coherencia,
    validar_conteo_dias,
    recargar_datos,
    info_sistema,
)
from app.services.prorroga_detector import (
    analizar_historial_empleado,
    analisis_masivo_prorrogas,
)
from app.services.oms_icd_service import (
    buscar_codigo_oficial,
    buscar_por_texto,
    obtener_cie11_de_cie10,
    obtener_cie10_de_cie11,
    buscar_codigo_completo,
    info_servicio_oms,
    recargar_datos_oms,
    validar_correlacion_oms,
    validar_correlacion_oms_local,
    validar_correlacion_oms_local_sync,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cie10", tags=["CIE-10 Diagnósticos"])


# ═══════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════

class ValidarDiagnosticoRequest(BaseModel):
    codigo: str = Field(..., description="Código CIE-10 (ej: A09, M54, K21)")

class CorrelacionRequest(BaseModel):
    codigo1: str = Field(..., description="Primer código CIE-10")
    codigo2: str = Field(..., description="Segundo código CIE-10")

class ValidarDiasRequest(BaseModel):
    codigo: str = Field(..., description="Código CIE-10")
    dias: int = Field(..., description="Días de incapacidad")

class ValidarConteoRequest(BaseModel):
    fecha_inicio: str = Field(..., description="Fecha inicio (YYYY-MM-DD)")
    fecha_fin: str = Field(..., description="Fecha fin (YYYY-MM-DD)")
    dias: int = Field(..., description="Días reportados")

class ValidarCoherenciaRequest(BaseModel):
    codigo: str = Field(..., description="Código CIE-10 (ej: J00, M54, I21)")
    dias: int = Field(..., description="Días de incapacidad solicitados")

class CorrelacionAuditoriaRequest(BaseModel):
    codigo1: str = Field(..., description="Primer código CIE-10")
    codigo2: str = Field(..., description="Segundo código CIE-10")
    dias_entre: Optional[int] = Field(None, description="Días entre fin inc.1 e inicio inc.2")


# ═══════════════════════════════════════════════════════════
# 1. CONSULTA DE CÓDIGO CIE-10
# ═══════════════════════════════════════════════════════════

@router.post("/validar-diagnostico")
async def validar_diagnostico(req: ValidarDiagnosticoRequest):
    """
    🔍 Busca un código CIE-10 en la base de datos
    Retorna: descripción, bloque, grupo, días típicos
    """
    try:
        resultado = buscar_codigo(req.codigo)
        if not resultado:
            return {
                "ok": False,
                "codigo": req.codigo,
                "mensaje": f"Código {req.codigo} no encontrado en la base CIE-10 2026",
                "sugerencia": "Verifique el código o agregue al JSON cie10_2026.json"
            }
        return {"ok": True, **resultado}
    except Exception as e:
        logger.error(f"Error validar diagnóstico: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/buscar/{codigo}")
async def buscar_cie10(codigo: str):
    """
    🔍 Busca un código CIE-10 (endpoint GET alternativo)
    """
    resultado = buscar_codigo(codigo)
    if not resultado:
        return {"ok": False, "codigo": codigo, "mensaje": "Código no encontrado"}
    return {"ok": True, **resultado}


# ═══════════════════════════════════════════════════════════
# 2. CORRELACIÓN ENTRE CÓDIGOS
# ═══════════════════════════════════════════════════════════

@router.post("/correlacion")
async def verificar_correlacion(req: CorrelacionRequest):
    """
    🔗 Verifica si dos códigos CIE-10 están correlacionados
    (pertenecen al mismo grupo de enfermedad)
    
    Ejemplo: A09 y K52 → correlacionados (GASTROINTESTINAL_INFECCIOSO)
    """
    try:
        resultado = son_correlacionados(req.codigo1, req.codigo2)
        return {"ok": True, **resultado}
    except Exception as e:
        logger.error(f"Error correlación: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/correlaciones/{codigo}")
async def obtener_correlaciones(codigo: str):
    """
    📋 Obtiene TODOS los códigos correlacionados a uno dado
    Útil para ver qué diagnósticos podrían ser prórroga
    """
    try:
        resultado = obtener_todos_correlacionados(codigo)
        return {"ok": True, "codigo": codigo, **resultado}
    except Exception as e:
        logger.error(f"Error obtener correlaciones: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════
# 3. VALIDACIÓN DE DÍAS
# ═══════════════════════════════════════════════════════════

@router.post("/validar-dias")
async def validar_dias_incapacidad(req: ValidarDiasRequest):
    """
    📅 Valida si los días de incapacidad son coherentes con el diagnóstico
    Compara contra los días típicos para ese código CIE-10
    """
    try:
        resultado = validar_dias(req.codigo, req.dias)
        return {"ok": True, **resultado}
    except Exception as e:
        logger.error(f"Error validar días: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/validar-conteo")
async def validar_conteo_dias_ep(req: ValidarConteoRequest):
    """
    🧮 Valida que fecha_inicio + días = fecha_fin (ambos días cuentan)
    Normativa colombiana: se cuentan día inicio y día fin
    """
    try:
        resultado = validar_conteo_dias(req.fecha_inicio, req.fecha_fin, req.dias)
        return {"ok": True, **resultado}
    except Exception as e:
        logger.error(f"Error validar conteo: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/validar-coherencia-dias")
async def validar_coherencia_dias_endpoint(req: ValidarCoherenciaRequest):
    """
    🔍 Valida si los días solicitados son coherentes con el diagnóstico CIE-10
    
    Detecta:
    - Posible FRAUDE: ej. 60 días por resfriado común (J00)
    - Error MÉDICO: ej. 5 días por infarto (I21) = alta prematura
    - COHERENCIA: ej. 14 días por dorsalgia (M54) = OK
    
    Niveles de alerta:
    - OK: Días coherentes con diagnóstico
    - ADVERTENCIA: Revisar justificación médica
    - ALTA: Solicitar concepto de especialista
    - CRITICA: Bloquear y derivar a investigación
    """
    try:
        resultado = validar_dias_coherencia(req.codigo, req.dias)
        return {"ok": True, **resultado}
    except Exception as e:
        logger.error(f"Error validando coherencia días: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════
# 4. ANÁLISIS DE PRÓRROGAS POR EMPLEADO
# ═══════════════════════════════════════════════════════════

@router.get("/historial/{cedula}")
async def historial_empleado(
    cedula: str,
    db: Session = Depends(get_db)
):
    """
    📊 Análisis completo del historial de incapacidades de un empleado
    - Detecta cadenas de prórrogas automáticamente
    - Cuenta días acumulados por cadena
    - Genera alertas al acercarse a 180 días
    """
    try:
        resultado = analizar_historial_empleado(db, cedula)
        return {"ok": True, **resultado}
    except Exception as e:
        logger.error(f"Error historial {cedula}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/alerta-180/{cedula}")
async def alerta_180_dias(
    cedula: str,
    db: Session = Depends(get_db)
):
    """
    ⚠️ Verificación rápida de alerta 180 días para un empleado
    Retorna solo las alertas (más ligero que historial completo)
    """
    try:
        analisis = analizar_historial_empleado(db, cedula)
        return {
            "ok": True,
            "cedula": cedula,
            "nombre": analisis.get("nombre"),
            "dias_acumulados_total": analisis["dias_acumulados_total"],
            "alertas": analisis["alertas_180"],
            "resumen": analisis["resumen"],
        }
    except Exception as e:
        logger.error(f"Error alerta 180 {cedula}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/linea-tiempo/{cedula}")
async def linea_tiempo_empleado(
    cedula: str,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """
    📊 Línea de tiempo del empleado: **una barra por cadena**.

    Por qué no es un solo contador: una persona puede tener dos o tres cadenas
    abiertas al mismo tiempo por patologías distintas, y cada una corre contra
    su propio cronograma y su propio pagador. Sumarlas dispara alertas de 180
    días a quien no las ha causado y esconde a quien sí.

    Cada barra trae lo que el frontend necesita para dibujarla:

    - `etiqueta`: lo que va **encima** de la barra — `"180 GENERAL"`,
      `"180 LABORAL"` o `"LICENCIA"`.
    - `origen` / `origen_mixto` / `confianza_origen` / `nota_origen`: de esto
      depende a quién se le radica. Si la confianza no es `"alta"`, la cadena
      aparece además en `requiere_revision_origen` y hay que confirmarla a mano.
    - `escala_dias` (540 en común, 360 en laboral) y `avance_pct`.
    - `tramos`: quién paga en cada segmento, con `inicio_pct`/`ancho_pct` para
      pintarlos y `activo` en el tramo de hoy.
    - `hitos`: 120 / 150 / 180 / 540 / 541 en origen común y 180 / 360 en
      laboral, cada uno con `estado` (`cumplido` | `proximo` | `pendiente`),
      la fecha (exacta si ya se cruzó, `proyectada: true` si se estimó) y su
      `posicion_pct` sobre la barra.
    - `responsable_actual`: quién debe estar pagando hoy esta cadena.

    Todo se arma con el OCR de los propios soportes (`Case`): no depende de que
    nadie suba el reporte de nómina.
    """
    try:
        analisis = analizar_historial_empleado(db, cedula)
        return {"ok": True, **linea_de_tiempo(analisis)}
    except Exception as e:
        logger.error(f"Error línea de tiempo {cedula}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════
# 5. ANÁLISIS MASIVO (DASHBOARD)
# ═══════════════════════════════════════════════════════════

@router.get("/analisis-masivo")
async def analisis_masivo(
    empresa: str = Query("all"),
    db: Session = Depends(get_db)
):
    """
    📊 Análisis masivo de prórrogas para TODOS los empleados
    Usado para el dashboard general de alertas 180 días
    """
    try:
        resultado = analisis_masivo_prorrogas(db, empresa)
        return {"ok": True, **resultado}
    except Exception as e:
        logger.error(f"Error análisis masivo: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════
# 6. ADMINISTRACIÓN
# ═══════════════════════════════════════════════════════════

@router.post("/recargar")
async def recargar_cie10():
    """
    🔄 Recarga los JSON de CIE-10 sin reiniciar el servidor
    Útil después de actualizar cie10_2026.json o correlaciones_cie10.json
    """
    try:
        resultado = recargar_datos()
        return {"ok": True, **resultado}
    except Exception as e:
        logger.error(f"Error recargar: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/info")
async def info_cie10():
    """
    ℹ️ Información del sistema CIE-10
    Versión, cantidad de códigos, grupos de correlación
    """
    try:
        info = info_sistema()
        return {"ok": True, **info}
    except Exception as e:
        logger.error(f"Error info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════
# 7. OMS / MINSALUD — BASE OFICIAL 12,568 CÓDIGOS
# ═══════════════════════════════════════════════════════════

@router.get("/oficial/{codigo}")
async def buscar_oficial(codigo: str):
    """
    🔍 Busca un código CIE-10 en la base oficial MinSalud (12,568 códigos)
    
    Acepta: A00, A00.0, A000, a00.0
    """
    try:
        resultado = buscar_codigo_oficial(codigo)
        return {"ok": True, **(resultado or {})}
    except Exception as e:
        logger.error(f"Error buscar oficial: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/oficial/buscar/texto")
async def buscar_texto_oficial(
    q: str = Query(..., description="Texto a buscar (ej: resfriado, diabetes, lumbar)"),
    limite: int = Query(20, ge=1, le=100, description="Máximo resultados")
):
    """
    🔎 Búsqueda por texto en la base oficial MinSalud
    
    Busca en títulos y descripciones de los 12,568 códigos oficiales.
    Ejemplo: /oficial/buscar/texto?q=resfriado
    """
    try:
        resultados = buscar_por_texto(q, limite)
        return {
            "ok": True,
            "query": q,
            "total": len(resultados),
            "resultados": resultados
        }
    except Exception as e:
        logger.error(f"Error buscar texto: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cie11/{codigo_cie10}")
async def mapear_a_cie11(codigo_cie10: str):
    """
    🔄 Obtiene los códigos CIE-11 equivalentes a un código CIE-10
    
    Basado en las tablas oficiales de mapping OMS (17,349 registros).
    Preparación para la transición a CIE-11.
    """
    try:
        resultados = obtener_cie11_de_cie10(codigo_cie10)
        return {
            "ok": True,
            "codigo_cie10": codigo_cie10,
            "total_equivalencias": len(resultados),
            "cie11": resultados
        }
    except Exception as e:
        logger.error(f"Error mapear CIE-11: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cie10-desde-cie11/{codigo_cie11}")
async def mapear_desde_cie11(codigo_cie11: str):
    """
    🔄 Obtiene los códigos CIE-10 correspondientes a un código CIE-11
    
    Soporta códigos poscoordinados (usar - en lugar de /).
    """
    try:
        resultados = obtener_cie10_de_cie11(codigo_cie11)
        return {
            "ok": True,
            "codigo_cie11": codigo_cie11,
            "total_equivalencias": len(resultados),
            "cie10": resultados
        }
    except Exception as e:
        logger.error(f"Error mapear desde CIE-11: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/completo/{codigo}")
async def buscar_completo(codigo: str):
    """
    🔍 Búsqueda completa de un código CIE-10 con todas las fuentes:
    
    1. Base oficial MinSalud (12,568 códigos) — instantáneo
    2. Mapping CIE-10 ↔ CIE-11 (17,349 registros) — instantáneo
    3. ICD API OMS (si hay credenciales) — en línea
    """
    try:
        resultado = await buscar_codigo_completo(codigo)
        return {"ok": True, **resultado}
    except Exception as e:
        logger.error(f"Error búsqueda completa: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/oms/info")
async def info_oms():
    """
    ℹ️ Información del servicio OMS / MinSalud
    
    Muestra fuentes disponibles, cantidad de códigos, estado de la ICD API.
    """
    try:
        info = info_servicio_oms()
        return {"ok": True, **info}
    except Exception as e:
        logger.error(f"Error info OMS: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/oms/recargar")
async def recargar_oms():
    """
    🔄 Recarga los datos OMS/MinSalud sin reiniciar el servidor
    """
    try:
        resultado = recargar_datos_oms()
        return {"ok": True, **resultado}
    except Exception as e:
        logger.error(f"Error recargar OMS: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════
# 8. VALIDACIÓN CON OMS — AUDITORÍA Y CORRELACIÓN 100%
# ═══════════════════════════════════════════════════════════

@router.post("/correlacion-auditoria")
async def correlacion_auditoria(req: CorrelacionAuditoriaRequest):
    """
    🔒 Validación de correlación con respaldo OMS para AUDITORÍA.
    
    Flujo:
      1. Motor local CIE-10 v3 (6 niveles jerárquicos) → resultado instantáneo
      2. API OMS en vivo / datos locales MinSalud (12,568 códigos + CIE-11) → cross-validación
      3. Si ambos coinciden → 100% confianza con cita legal OMS
      4. Si difieren → marca conflicto para revisión clínica
    
    Ideal para: casos de 180 días, auditorías EPS, defensa ante Fondo de Pensiones.
    
    Ejemplo:
      POST {"codigo1": "A09", "codigo2": "K52.9", "dias_entre": 5}
      → {"correlacionados": true, "asertividad": 95.0, "fuente": "LOCAL+OMS_CONFIRMADO",
         "cita_legal_oms": "Según OMS ICD-10..."}
    """
    try:
        resultado = await son_correlacionados_auditoria(
            req.codigo1, req.codigo2, dias_entre=req.dias_entre
        )
        return {"ok": True, **resultado}
    except Exception as e:
        logger.error(f"Error correlación auditoría: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/correlacion-oms")
async def correlacion_oms_directa(req: CorrelacionRequest):
    """
    🌐 Validación de correlación DIRECTA contra API OMS en vivo.
    
    No usa el motor local — consulta directamente la jerarquía OMS.
    Requiere credenciales ICD API configuradas (ICD_API_CLIENT_ID, ICD_API_CLIENT_SECRET).
    Si no hay credenciales, usa datos locales MinSalud (12,568 códigos + mapping CIE-11).
    
    Retorna: parent compartido, exclusiones, cita legal OMS.
    """
    try:
        import os
        if os.environ.get("ICD_API_CLIENT_ID"):
            resultado = await validar_correlacion_oms(req.codigo1, req.codigo2)
        else:
            resultado = await validar_correlacion_oms_local(req.codigo1, req.codigo2)
        return {"ok": True, **resultado}
    except Exception as e:
        logger.error(f"Error correlación OMS: {e}")
        raise HTTPException(status_code=500, detail=str(e))
