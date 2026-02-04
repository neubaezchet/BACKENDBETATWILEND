"""
RUTAS DE REPORTES
Endpoints principales para tabla viva y exportaciones
"""

from fastapi import APIRouter, Depends, Query, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
import io
import logging
from datetime import datetime
from typing import Optional

from app.database import get_db, Case
from app.schemas.reporte import (
    FiltrosExportacion, 
    TablaVivaResponse,
    PreviewExportResponse,
    RegenerarTablaResponse
)
from app.services.reporte_service import ReporteService
from app.utils.excel_formatter import ExcelFormatter

logger = logging.getLogger(__name__)

# Crear router
router = APIRouter(prefix="/validador/casos", tags=["Reportes"])

# ============================================================
# 1️⃣ ENDPOINT: TABLA VIVA (Auto-refresh cada 30s)
# ============================================================
@router.get("/tabla-viva", response_model=TablaVivaResponse)
async def get_tabla_viva(
    empresa: str = Query("all", description="Nombre de empresa o 'all'"),
    periodo: str = Query("mes_actual", description="Tipo de período"),
    db: Session = Depends(get_db)
):
    """
    📊 TABLA VIVA EN TIEMPO REAL
    
    - Se actualiza automáticamente cada 30 segundos desde el frontend
    - Muestra estadísticas por estado
    - Incluye últimos 20 casos
    
    Parámetros:
    - empresa: "all" o nombre específico
    - periodo: mes_actual, mes_anterior, quincena_1, quincena_2, año_actual
    
    Ejemplo:
    GET /validador/casos/tabla-viva?empresa=all&periodo=mes_actual
    """
    try:
        datos = ReporteService.obtener_tabla_viva(db, empresa, periodo, Case)
        return datos
    except Exception as e:
        logger.error(f"Error tabla viva: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# 2️⃣ ENDPOINT: PREVIEW EXPORTACIÓN (20 registros)
# ============================================================
@router.get("/preview-exportacion", response_model=PreviewExportResponse)
async def get_preview_exportacion(
    empresa: str = Query("all"),
    fecha_inicio: Optional[str] = Query(None, description="YYYY-MM-DD"),
    fecha_fin: Optional[str] = Query(None, description="YYYY-MM-DD"),
    estados: Optional[str] = Query(None, description="estado1,estado2,..."),
    tipos: Optional[str] = Query(None, description="tipo1,tipo2,..."),
    db: Session = Depends(get_db)
):
    """
    👁️ PREVIEW DE EXPORTACIÓN
    
    - Muestra máximo 20 registros
    - No descarga, solo visualización
    - Usado antes de hacer export final
    
    Parámetros:
    - empresa: "all" o nombre
    - fecha_inicio/fin: formato YYYY-MM-DD
    - estados: separado por comas
    - tipos: separado por comas
    
    Ejemplo:
    GET /validador/casos/preview-exportacion?empresa=all&estados=COMPLETA,NUEVA
    """
    try:
        filtros = {
            "empresa": empresa,
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
            "estados": estados,
            "tipos": tipos,
        }
        
        preview = ReporteService.obtener_preview(db, filtros, Case)
        return {
            **preview,
            "periodo": "custom",
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
        }
    except Exception as e:
        logger.error(f"Error preview: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# 3️⃣ ENDPOINT: EXPORTAR AVANZADO (XLSX/CSV/JSON)
# ============================================================
@router.get("/exportar-avanzado")
async def exportar_avanzado(
    empresa: str = Query("all"),
    fecha_inicio: Optional[str] = Query(None, description="YYYY-MM-DD"),
    fecha_fin: Optional[str] = Query(None, description="YYYY-MM-DD"),
    estados: Optional[str] = Query(None, description="estado1,estado2,..."),
    tipos: Optional[str] = Query(None, description="tipo1,tipo2,..."),
    incluir_historial: bool = Query(False),
    formato: str = Query("xlsx", description="xlsx, csv o json"),
    db: Session = Depends(get_db)
):
    """
    📥 EXPORTAR DATOS AVANZADO
    
    - Descarga archivo en 3 formatos: XLSX, CSV, JSON
    - Aplica todos los filtros
    - Excel con formato profesional
    
    Parámetros:
    - formato: "xlsx", "csv", "json"
    - incluir_historial: True/False
    
    Ejemplo:
    GET /validador/casos/exportar-avanzado?formato=xlsx&empresa=all&estados=COMPLETA
    """
    try:
        filtros = {
            "empresa": empresa,
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
            "estados": estados,
            "tipos": tipos,
        }
        
        # Obtener datos
        df = ReporteService.obtener_datos_exportacion(
            db, filtros, incluir_historial, Case
        )
        
        # Generar nombre del archivo
        fecha_export = datetime.now().strftime("%Y-%m-%d")
        empresa_nombre = empresa.lower().replace(" ", "_") if empresa != "all" else "todas-empresas"
        
        if formato == "xlsx":
            archivo = ExcelFormatter.crear_excel(df, titulo="Reporte Incapacidades")
            nombre = f"reporte_incapacidades_{empresa_nombre}_{fecha_export}.xlsx"
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        
        elif formato == "csv":
            archivo = ExcelFormatter.crear_csv(df)
            nombre = f"reporte_incapacidades_{empresa_nombre}_{fecha_export}.csv"
            media_type = "text/csv"
        
        elif formato == "json":
            archivo = ExcelFormatter.crear_json(df)
            nombre = f"reporte_incapacidades_{empresa_nombre}_{fecha_export}.json"
            media_type = "application/json"
        
        else:
            raise ValueError("Formato no soportado")
        
        return Response(
            content=archivo,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={nombre}"}
        )
    
    except Exception as e:
        logger.error(f"Error exportando: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# 4️⃣ ENDPOINT: REGENERAR TABLA VIVA (Admin)
# ============================================================
@router.post("/regenerar-tabla-viva", response_model=RegenerarTablaResponse)
async def regenerar_tabla_viva(db: Session = Depends(get_db)):
    """
    🔄 REGENERAR TABLA VIVA (Archiva mes anterior)
    
    - ⚠️ Uso ADMINISTRATIVO
    - Archiva datos del mes anterior
    - Limpia tabla para nuevo período
    - Se ejecuta automáticamente cada 1° del mes a las 00:01
    
    Uso manual: POST /validador/casos/regenerar-tabla-viva
    """
    try:
        resultado = ReporteService.regenerar_tabla_viva(db, Case)
        logger.info(f"✅ Tabla regenerada: {resultado}")
        return resultado
    except Exception as e:
        logger.error(f"Error regenerando: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# ENDPOINT ADICIONAL: HEALTH CHECK
# ============================================================
@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """
    ✅ Verificar estado de la API
    
    Retorna:
    - status: "ok"
    - scheduler: "running" o "stopped"
    - database: "connected"
    """
    try:
        # Verificar base de datos
        db.query(Case).limit(1).all()
        
        return {
            "status": "ok",
            "scheduler": "running",
            "database": "connected",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error health check: {str(e)}")
        return {
            "status": "error",
            "scheduler": "unknown",
            "database": "disconnected",
            "error": str(e)
        }
