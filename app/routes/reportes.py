"""
RUTAS DE REPORTES
Endpoints principales para tabla viva y exportaciones
"""

from fastapi import APIRouter, Depends, Query, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, case as sql_case, distinct
import io
import logging
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict

from app.database import get_db, Case, Company, Employee, CaseDocument, CaseEvent, CaseNote
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


# ============================================================
# 5️⃣ ENDPOINT: DASHBOARD COMPLETO 2026
# ============================================================
def _calcular_fechas_periodo(periodo: str):
    """Calcula fechas inicio/fin según período"""
    import calendar
    hoy = datetime.now()
    if periodo == "mes_actual":
        return datetime(hoy.year, hoy.month, 1), hoy
    elif periodo == "mes_anterior":
        primer_dia = datetime(hoy.year, hoy.month, 1)
        fin = primer_dia - timedelta(days=1)
        return datetime(fin.year, fin.month, 1), fin
    elif periodo == "quincena_1":
        return datetime(hoy.year, hoy.month, 1), datetime(hoy.year, hoy.month, 15, 23, 59, 59)
    elif periodo == "quincena_2":
        ultimo = calendar.monthrange(hoy.year, hoy.month)[1]
        return datetime(hoy.year, hoy.month, 16), datetime(hoy.year, hoy.month, ultimo, 23, 59, 59)
    elif periodo == "año_actual":
        return datetime(hoy.year, 1, 1), hoy
    elif periodo == "ultimos_90":
        return hoy - timedelta(days=90), hoy
    else:
        return datetime(hoy.year, hoy.month, 1), hoy


@router.get("/dashboard-completo")
async def get_dashboard_completo(
    empresa: str = Query("all"),
    periodo: str = Query("mes_actual"),
    db: Session = Depends(get_db)
):
    """
    📊 DASHBOARD COMPLETO 2026
    Retorna TODOS los datos necesarios para el panel de reportes:
    - KPIs generales
    - Tabla principal con TODOS los campos
    - Documentos incompletos con motivos
    - Frecuencia por empleado (reincidencia)
    - Indicadores por estado
    - Días en portal de validación
    """
    try:
        fecha_inicio, fecha_fin = _calcular_fechas_periodo(periodo)
        
        # Query base con joins
        query = db.query(Case).options(
            joinedload(Case.empresa),
            joinedload(Case.empleado),
            joinedload(Case.documentos),
            joinedload(Case.eventos),
        ).filter(
            Case.created_at >= fecha_inicio,
            Case.created_at <= fecha_fin
        )
        
        if empresa != "all":
            query = query.join(Company, Case.company_id == Company.id).filter(Company.nombre == empresa)
        
        casos = query.order_by(Case.created_at.desc()).all()
        ahora = datetime.now()
        
        # ═══ 1. KPIs ═══
        total = len(casos)
        por_estado = defaultdict(int)
        total_dias_incapacidad = 0
        
        for c in casos:
            est = c.estado.value if c.estado else "NUEVO"
            por_estado[est] += 1
            if c.dias_incapacidad:
                total_dias_incapacidad += c.dias_incapacidad
        
        kpis = {
            "total_casos": total,
            "total_dias_incapacidad": total_dias_incapacidad,
            "promedio_dias": round(total_dias_incapacidad / total, 1) if total > 0 else 0,
            "por_estado": dict(por_estado),
            "completas": por_estado.get("COMPLETA", 0),
            "incompletas": por_estado.get("INCOMPLETA", 0) + por_estado.get("ILEGIBLE", 0) + por_estado.get("INCOMPLETA_ILEGIBLE", 0),
            "en_proceso": por_estado.get("NUEVO", 0) + por_estado.get("EN_REVISION", 0),
            "eps_transcripcion": por_estado.get("EPS_TRANSCRIPCION", 0),
            "derivado_tthh": por_estado.get("DERIVADO_TTHH", 0),
        }
        
        # ═══ 2. TABLA PRINCIPAL ═══
        tabla_principal = []
        for c in casos:
            emp = c.empleado
            emp_nombre = emp.nombre if emp else c.cedula or "N/A"
            emp_area = emp.area_trabajo if emp else None
            emp_eps = emp.eps if emp else c.eps
            empresa_nombre = c.empresa.nombre if c.empresa else "N/A"
            
            # Campos Kactus del empleado
            emp_cargo = emp.cargo if emp else None
            emp_centro_costo = emp.centro_costo if emp else None
            emp_fecha_ingreso = emp.fecha_ingreso.isoformat() if emp and emp.fecha_ingreso else None
            emp_tipo_contrato = emp.tipo_contrato if emp else None
            emp_dias_kactus = emp.dias_kactus if emp else None
            emp_ciudad = emp.ciudad if emp else None
            
            # Calcular días en portal (desde creación hasta ahora o hasta estado final)
            dias_en_portal = (ahora - c.created_at).days if c.created_at else 0
            
            # Obtener último motivo/observación de eventos
            ultimo_motivo = None
            if c.eventos:
                evt_con_motivo = [e for e in c.eventos if e.motivo]
                if evt_con_motivo:
                    ultimo_evt = sorted(evt_con_motivo, key=lambda e: e.created_at or datetime.min, reverse=True)[0]
                    ultimo_motivo = ultimo_evt.motivo
            
            # Documentos faltantes
            docs_faltantes = []
            docs_ilegibles = []
            if c.documentos:
                for d in c.documentos:
                    est_doc = d.estado_doc.value if d.estado_doc else "PENDIENTE"
                    if est_doc in ("PENDIENTE", "INCOMPLETO"):
                        docs_faltantes.append(d.doc_tipo)
                    elif est_doc == "ILEGIBLE":
                        docs_ilegibles.append(d.doc_tipo)
            
            tabla_principal.append({
                "serial": c.serial,
                "cedula": c.cedula,
                "nombre": emp_nombre,
                "empresa": empresa_nombre,
                "area": emp_area,
                "cargo": emp_cargo,
                "centro_costo": emp_centro_costo,
                "ciudad": emp_ciudad,
                "tipo_contrato": emp_tipo_contrato,
                "fecha_ingreso": emp_fecha_ingreso,
                "eps": emp_eps or c.eps,
                "tipo": c.tipo.value if c.tipo else "N/A",
                "subtipo": c.subtipo,
                "estado": c.estado.value if c.estado else "NUEVO",
                "diagnostico": c.diagnostico,
                "codigo_cie10": c.codigo_cie10,
                "dias_incapacidad": c.dias_incapacidad,
                "dias_kactus": c.dias_kactus,
                "dias_kactus_empleado": emp_dias_kactus,
                "es_prorroga": c.es_prorroga,
                "numero_incapacidad": c.numero_incapacidad,
                "medico_tratante": c.medico_tratante,
                "institucion_origen": c.institucion_origen,
                "fecha_inicio": c.fecha_inicio.isoformat() if c.fecha_inicio else None,
                "fecha_fin": c.fecha_fin.isoformat() if c.fecha_fin else None,
                "fecha_radicacion": c.created_at.isoformat() if c.created_at else None,
                "dias_en_portal": dias_en_portal,
                "observacion": ultimo_motivo,
                "docs_faltantes": docs_faltantes,
                "docs_ilegibles": docs_ilegibles,
                "drive_link": c.drive_link,
            })
        
        # ═══ 3. INCOMPLETAS / OBSERVACIÓN ═══
        incompletas = []
        for row in tabla_principal:
            if row["estado"] in ("INCOMPLETA", "ILEGIBLE", "INCOMPLETA_ILEGIBLE"):
                incompletas.append({
                    "serial": row["serial"],
                    "cedula": row["cedula"],
                    "nombre": row["nombre"],
                    "empresa": row["empresa"],
                    "area": row.get("area"),
                    "cargo": row.get("cargo"),
                    "tipo": row["tipo"],
                    "estado": row["estado"],
                    "observacion": row["observacion"],
                    "docs_faltantes": row["docs_faltantes"],
                    "docs_ilegibles": row["docs_ilegibles"],
                    "dias_en_portal": row["dias_en_portal"],
                    "fecha_radicacion": row["fecha_radicacion"],
                    "diagnostico": row.get("diagnostico"),
                    "codigo_cie10": row.get("codigo_cie10"),
                })
        
        # ═══ 4. FRECUENCIA POR EMPLEADO (reincidencia) ═══
        # Agrupar por cédula para detectar personas con múltiples incapacidades
        freq_query = db.query(Case).filter(
            Case.created_at >= datetime(ahora.year, 1, 1)  # Año actual completo
        )
        if empresa != "all":
            freq_query = freq_query.join(Company, Case.company_id == Company.id).filter(Company.nombre == empresa)
        
        todos_casos_año = freq_query.options(joinedload(Case.empleado), joinedload(Case.empresa)).all()
        
        por_cedula = defaultdict(list)
        for c in todos_casos_año:
            if c.cedula:
                por_cedula[c.cedula].append(c)
        
        frecuencia = []
        for cedula, casos_persona in por_cedula.items():
            if len(casos_persona) == 0:
                continue
            primer_caso = casos_persona[0]
            emp = primer_caso.empleado
            nombre = emp.nombre if emp else cedula
            empresa_n = primer_caso.empresa.nombre if primer_caso.empresa else "N/A"
            
            total_dias_persona = sum(c.dias_incapacidad or 0 for c in casos_persona)
            total_dias_kactus = sum(c.dias_kactus or 0 for c in casos_persona)
            diagnosticos = list(set(c.diagnostico for c in casos_persona if c.diagnostico))
            codigos_cie10 = list(set(c.codigo_cie10 for c in casos_persona if c.codigo_cie10))
            prorrogas = sum(1 for c in casos_persona if c.es_prorroga)
            
            # Desglose por mes
            por_mes = defaultdict(int)
            for c in casos_persona:
                if c.created_at:
                    mes_key = c.created_at.strftime("%Y-%m")
                    por_mes[mes_key] += 1
            
            frecuencia.append({
                "cedula": cedula,
                "nombre": nombre,
                "empresa": empresa_n,
                "area": emp.area_trabajo if emp else None,
                "cargo": emp.cargo if emp else None,
                "ciudad": emp.ciudad if emp else None,
                "total_incapacidades": len(casos_persona),
                "total_dias_portal": total_dias_persona,
                "total_dias_kactus": total_dias_kactus,
                "prorrogas": prorrogas,
                "diagnosticos": diagnosticos,
                "codigos_cie10": codigos_cie10,
                "desglose_mensual": dict(por_mes),
                "es_reincidente": len(casos_persona) >= 3,
                "primera_fecha": min(c.created_at for c in casos_persona if c.created_at).isoformat() if any(c.created_at for c in casos_persona) else None,
                "ultima_fecha": max(c.created_at for c in casos_persona if c.created_at).isoformat() if any(c.created_at for c in casos_persona) else None,
            })
        
        # Ordenar por más incapacidades primero
        frecuencia.sort(key=lambda x: x["total_incapacidades"], reverse=True)
        
        # ═══ 5. INDICADORES POR ESTADO ═══
        indicadores = []
        for estado, cantidad in sorted(por_estado.items(), key=lambda x: x[1], reverse=True):
            casos_estado = [r for r in tabla_principal if r["estado"] == estado]
            dias_promedio = 0
            if casos_estado:
                dias_vals = [r["dias_incapacidad"] or 0 for r in casos_estado]
                dias_promedio = round(sum(dias_vals) / len(dias_vals), 1) if dias_vals else 0
            
            indicadores.append({
                "estado": estado,
                "cantidad": cantidad,
                "porcentaje": round(cantidad / total * 100, 1) if total > 0 else 0,
                "dias_promedio_incapacidad": dias_promedio,
                "dias_promedio_portal": round(sum(r["dias_en_portal"] for r in casos_estado) / len(casos_estado), 1) if casos_estado else 0,
            })
        
        return {
            "ok": True,
            "periodo": periodo,
            "empresa": empresa,
            "fecha_inicio": fecha_inicio.isoformat(),
            "fecha_fin": fecha_fin.isoformat(),
            "fecha_consulta": ahora.isoformat(),
            "kpis": kpis,
            "tabla_principal": tabla_principal,
            "incompletas": incompletas,
            "frecuencia": frecuencia,
            "indicadores": indicadores,
        }
    
    except Exception as e:
        logger.error(f"Error dashboard completo: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
