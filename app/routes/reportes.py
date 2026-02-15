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
from app.services.prorroga_detector import auto_detectar_prorroga_caso, analizar_historial_empleado
from app.services.cie10_service import buscar_codigo, validar_dias

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
def _calcular_fechas_periodo(periodo: str, fecha_desde: str = None, fecha_hasta: str = None):
    """Calcula fechas inicio/fin según período"""
    import calendar
    hoy = datetime.now()
    if periodo == "personalizado" and fecha_desde and fecha_hasta:
        try:
            inicio = datetime.strptime(fecha_desde, "%Y-%m-%d")
            fin = datetime.strptime(fecha_hasta, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            return inicio, fin
        except ValueError:
            return datetime(hoy.year, hoy.month, 1), hoy
    elif periodo == "mes_actual":
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
    elif periodo == "todo":
        return datetime(2020, 1, 1), hoy
    else:
        return datetime(hoy.year, hoy.month, 1), hoy


@router.get("/dashboard-completo")
async def get_dashboard_completo(
    empresa: str = Query("all"),
    periodo: str = Query("mes_actual"),
    fecha_desde: str = Query(None, description="Fecha inicio YYYY-MM-DD (solo si periodo=personalizado)"),
    fecha_hasta: str = Query(None, description="Fecha fin YYYY-MM-DD (solo si periodo=personalizado)"),
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
        fecha_inicio, fecha_fin = _calcular_fechas_periodo(periodo, fecha_desde, fecha_hasta)
        
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
            
            # ⭐ Auto-detectar prórroga por CIE-10
            prorroga_auto = {"es_prorroga": False}
            try:
                prorroga_auto = auto_detectar_prorroga_caso(db, c)
            except Exception:
                pass
            
            # ⭐ Validar CIE-10 y días
            cie10_info = None
            dias_validacion = None
            if c.codigo_cie10:
                cie10_info = buscar_codigo(c.codigo_cie10)
                if c.dias_incapacidad:
                    dias_validacion = validar_dias(c.codigo_cie10, c.dias_incapacidad)
            
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
                "cie10_descripcion": cie10_info.get("descripcion") if cie10_info else None,
                "cie10_grupo": cie10_info.get("grupo") if cie10_info else None,
                "dias_incapacidad": c.dias_incapacidad,
                "dias_kactus": c.dias_kactus,
                "dias_kactus_empleado": emp_dias_kactus,
                "dias_validacion": dias_validacion,
                "es_prorroga": prorroga_auto.get("es_prorroga", c.es_prorroga),
                "es_prorroga_db": c.es_prorroga,
                "prorroga_confianza": prorroga_auto.get("confianza"),
                "prorroga_explicacion": prorroga_auto.get("explicacion"),
                "prorroga_caso_original": prorroga_auto.get("caso_original_serial"),
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
            
            # ⭐ Análisis CIE-10 de historial completo
            analisis_cie10 = None
            alertas_180 = []
            try:
                analisis_cie10 = analizar_historial_empleado(db, cedula)
                alertas_180 = analisis_cie10.get("alertas_180", [])
                # Usar prórrogas detectadas por CIE-10 si son más que las de BD
                prorrogas_auto = sum(
                    len(c.get("prorrogas", []))
                    for c in analisis_cie10.get("cadenas_prorroga", [])
                )
                if prorrogas_auto > prorrogas:
                    prorrogas = prorrogas_auto
            except Exception:
                pass
            
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
                # ⭐ Campos nuevos CIE-10
                "alertas_180": alertas_180,
                "tiene_alerta_180": len(alertas_180) > 0,
                "max_cadena_dias": analisis_cie10["resumen"]["cadena_mas_larga_dias"] if analisis_cie10 else 0,
                "dias_prorroga": analisis_cie10.get("dias_prorroga", analisis_cie10["resumen"].get("dias_prorroga", 0)) if analisis_cie10 else 0,
                "cadenas_prorroga": analisis_cie10["resumen"]["cadenas_con_prorroga"] if analisis_cie10 else 0,
                "cerca_limite_180": analisis_cie10["resumen"].get("cerca_limite_180", False) if analisis_cie10 else False,
                "supero_180": analisis_cie10["resumen"].get("supero_180", False) if analisis_cie10 else False,
                # ⭐ Huecos (prórrogas cortadas)
                "huecos_detectados": len(analisis_cie10.get("huecos_detectados", [])) if analisis_cie10 else 0,
                "tiene_huecos": len(analisis_cie10.get("huecos_detectados", [])) > 0 if analisis_cie10 else False,
                "huecos_info": analisis_cie10["resumen"].get("huecos_info", []) if analisis_cie10 else [],
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
        
        # ═══ 6. ALERTAS 180 DÍAS GLOBALES ═══
        alertas_180_global = []
        for f in frecuencia:
            if f.get("alertas_180"):
                alertas_180_global.extend(f["alertas_180"])
        alertas_180_global.sort(key=lambda x: {"critica": 0, "alta": 1, "media": 2}.get(x.get("severidad", ""), 3))
        
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
            "alertas_180": alertas_180_global,
        }
    
    except Exception as e:
        logger.error(f"Error dashboard completo: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 6️⃣ ENDPOINT: POWER BI — ANÁLISIS PERSONA (timeline + gaps)
# ============================================================
@router.get("/powerbi/persona/{cedula}")
async def powerbi_analisis_persona(
    cedula: str,
    db: Session = Depends(get_db)
):
    """
    📊 POWER BI — Análisis completo de una persona.
    Devuelve todas las incapacidades con timeline, gaps, cadenas de prórroga,
    y periodos descubiertos para visualización estilo Power BI.
    """
    try:
        from datetime import date as date_type
        
        # Datos del empleado
        empleado = db.query(Employee).filter(Employee.cedula == cedula).first()
        if not empleado:
            # Buscar en casos directamente
            caso_sample = db.query(Case).filter(Case.cedula == cedula).first()
            if not caso_sample:
                raise HTTPException(status_code=404, detail=f"No se encontró empleado con cédula {cedula}")
        
        # Todas las incapacidades ordenadas por fecha
        casos = db.query(Case).filter(
            Case.cedula == cedula
        ).order_by(Case.fecha_inicio.asc()).all()
        
        if not casos:
            raise HTTPException(status_code=404, detail="Sin incapacidades registradas")
        
        # Análisis de prórrogas completo
        analisis = analizar_historial_empleado(db, cedula)
        
        # Construir timeline de incapacidades
        timeline = []
        for c in casos:
            cie_info = buscar_codigo(c.codigo_cie10) if c.codigo_cie10 else None
            empresa_obj = db.query(Company).filter(Company.id == c.company_id).first() if c.company_id else None
            
            fi = c.fecha_inicio
            ff = c.fecha_fin or c.fecha_inicio
            
            timeline.append({
                "serial": c.serial,
                "fecha_inicio": fi.strftime("%Y-%m-%d") if fi else None,
                "fecha_fin": ff.strftime("%Y-%m-%d") if ff else None,
                "dias": c.dias_incapacidad or 0,
                "tipo": c.tipo.value if c.tipo else "",
                "estado": c.estado.value if c.estado else "",
                "diagnostico": c.diagnostico or "",
                "codigo_cie10": c.codigo_cie10 or "",
                "cie10_descripcion": cie_info["descripcion"] if cie_info and cie_info.get("encontrado") else "",
                "cie10_grupo": cie_info["grupo"] if cie_info and cie_info.get("encontrado") else "",
                "empresa": empresa_obj.nombre if empresa_obj else "",
                "eps": c.eps or "",
                "es_prorroga": c.es_prorroga or False,
                "numero_incapacidad": c.numero_incapacidad or "",
                "medico_tratante": c.medico_tratante or "",
                "institucion_origen": c.institucion_origen or "",
                "drive_link": c.drive_link or "",
                "created_at": c.created_at.strftime("%Y-%m-%d") if c.created_at else "",
            })
        
        # Detectar TODOS los gaps (huecos) entre incapacidades consecutivas
        gaps = []
        for i in range(len(casos) - 1):
            caso_a = casos[i]
            caso_b = casos[i + 1]
            
            fin_a = caso_a.fecha_fin or caso_a.fecha_inicio
            inicio_b = caso_b.fecha_inicio
            
            if fin_a and inicio_b:
                brecha = (inicio_b.date() if hasattr(inicio_b, 'date') else inicio_b) - \
                         (fin_a.date() if hasattr(fin_a, 'date') else fin_a)
                dias_gap = brecha.days
                
                if dias_gap > 1:  # Hay un hueco (más de 1 día entre fin e inicio)
                    fecha_gap_inicio = fin_a.date() if hasattr(fin_a, 'date') else fin_a
                    fecha_gap_fin = inicio_b.date() if hasattr(inicio_b, 'date') else inicio_b
                    
                    # Determinar severidad del gap
                    corta_prorroga = dias_gap > 30
                    
                    gaps.append({
                        "fecha_inicio": str(fecha_gap_inicio + timedelta(days=1)),
                        "fecha_fin": str(fecha_gap_fin - timedelta(days=1)),
                        "dias": dias_gap - 1,
                        "entre_serial_a": caso_a.serial,
                        "entre_serial_b": caso_b.serial,
                        "corta_prorroga": corta_prorroga,
                        "severidad": "critica" if corta_prorroga else "advertencia",
                        "mensaje": f"{'🔴 CORTA PRÓRROGA' if corta_prorroga else '🟡 Hueco'}: {dias_gap - 1} días sin cobertura" +
                                   (f" (>{30}d, reinicia conteo)" if corta_prorroga else ""),
                    })
        
        # Resumen KPIs por tipo
        por_tipo = {}
        for c in casos:
            t = c.tipo.value if c.tipo else "sin_tipo"
            if t not in por_tipo:
                por_tipo[t] = {"cantidad": 0, "dias": 0}
            por_tipo[t]["cantidad"] += 1
            por_tipo[t]["dias"] += c.dias_incapacidad or 0
        
        # Resumen KPIs por año
        por_anio = {}
        for c in casos:
            anio = c.fecha_inicio.year if c.fecha_inicio else 0
            if anio not in por_anio:
                por_anio[anio] = {"cantidad": 0, "dias": 0}
            por_anio[anio]["cantidad"] += 1
            por_anio[anio]["dias"] += c.dias_incapacidad or 0
        
        # Resumen mensual para gráfico de barras
        por_mes = {}
        for c in casos:
            if c.fecha_inicio:
                mes_key = c.fecha_inicio.strftime("%Y-%m")
                if mes_key not in por_mes:
                    por_mes[mes_key] = {"mes": mes_key, "cantidad": 0, "dias": 0}
                por_mes[mes_key]["cantidad"] += 1
                por_mes[mes_key]["dias"] += c.dias_incapacidad or 0
        
        # CIE-10 frecuencia
        cie10_freq = {}
        for c in casos:
            if c.codigo_cie10:
                cod = c.codigo_cie10.strip().upper()
                if cod not in cie10_freq:
                    info = buscar_codigo(cod)
                    cie10_freq[cod] = {
                        "codigo": cod,
                        "descripcion": info["descripcion"] if info and info.get("encontrado") else c.diagnostico or cod,
                        "cantidad": 0,
                        "dias_total": 0,
                    }
                cie10_freq[cod]["cantidad"] += 1
                cie10_freq[cod]["dias_total"] += c.dias_incapacidad or 0
        
        # Datos del empleado
        emp_data = {}
        if empleado:
            emp_data = {
                "nombre": empleado.nombre or "",
                "cedula": empleado.cedula,
                "empresa": "",
                "area": empleado.area_trabajo or "",
                "cargo": empleado.cargo or "",
                "eps": empleado.eps or "",
                "centro_costo": empleado.centro_costo or "",
                "ciudad": empleado.ciudad or "",
                "fecha_ingreso": empleado.fecha_ingreso.strftime("%Y-%m-%d") if empleado.fecha_ingreso else "",
                "tipo_contrato": empleado.tipo_contrato or "",
            }
            if empleado.company_id:
                comp = db.query(Company).filter(Company.id == empleado.company_id).first()
                emp_data["empresa"] = comp.nombre if comp else ""
        else:
            # Reconstruir desde casos
            emp_data = {
                "nombre": "",
                "cedula": cedula,
                "empresa": timeline[0]["empresa"] if timeline else "",
                "area": "", "cargo": "", "eps": timeline[0].get("eps", "") if timeline else "",
                "centro_costo": "", "ciudad": "", "fecha_ingreso": "", "tipo_contrato": "",
            }
        
        total_dias = sum(c.dias_incapacidad or 0 for c in casos)
        total_gaps = sum(g["dias"] for g in gaps)
        gaps_criticos = [g for g in gaps if g["corta_prorroga"]]
        
        return {
            "ok": True,
            "empleado": emp_data,
            "kpis": {
                "total_incapacidades": len(casos),
                "total_dias_incapacidad": total_dias,
                "total_gaps": len(gaps),
                "total_dias_gap": total_gaps,
                "gaps_criticos": len(gaps_criticos),
                "cadenas_prorroga": len([c for c in analisis.get("cadenas_prorroga", []) if c.get("es_cadena_prorroga")]),
                "dias_prorroga_max": analisis.get("dias_prorroga", 0),
                "promedio_dias": round(total_dias / len(casos), 1) if casos else 0,
            },
            "timeline": timeline,
            "gaps": gaps,
            "cadenas": analisis.get("cadenas_prorroga", []),
            "huecos_prorroga": analisis.get("huecos_detectados", []),
            "alertas_180": analisis.get("alertas_180", []),
            "por_tipo": por_tipo,
            "por_anio": {str(k): v for k, v in sorted(por_anio.items())},
            "por_mes": sorted(por_mes.values(), key=lambda x: x["mes"]),
            "cie10_frecuencia": sorted(cie10_freq.values(), key=lambda x: -x["cantidad"]),
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error PowerBI persona {cedula}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 7️⃣ ENDPOINT: POWER BI — BÚSQUEDA DE EMPLEADOS
# ============================================================
@router.get("/powerbi/buscar")
async def powerbi_buscar_empleados(
    q: str = Query("", description="Búsqueda por cédula o nombre"),
    empresa: str = Query("all", description="Filtrar por empresa"),
    db: Session = Depends(get_db)
):
    """
    🔍 Busca empleados para el Power BI dashboard.
    Retorna lista de empleados con resumen rápido.
    """
    try:
        query = db.query(
            Case.cedula,
            func.count(Case.id).label("total"),
            func.sum(Case.dias_incapacidad).label("dias"),
            func.min(Case.fecha_inicio).label("primera"),
            func.max(Case.fecha_inicio).label("ultima"),
        ).group_by(Case.cedula)
        
        if q:
            # Buscar por cédula o nombre
            empleado_ids = db.query(Employee.cedula).filter(
                (Employee.cedula.ilike(f"%{q}%")) | 
                (Employee.nombre.ilike(f"%{q}%"))
            ).all()
            cedulas_match = [e[0] for e in empleado_ids]
            
            # También buscar directamente en casos por cédula
            query = query.filter(
                (Case.cedula.ilike(f"%{q}%")) |
                (Case.cedula.in_(cedulas_match) if cedulas_match else False)
            )
        
        if empresa != "all":
            company = db.query(Company).filter(Company.nombre == empresa).first()
            if company:
                query = query.filter(Case.company_id == company.id)
        
        resultados = query.order_by(func.count(Case.id).desc()).limit(50).all()
        
        # Enriquecer con nombres
        empleados = []
        for r in resultados:
            emp = db.query(Employee).filter(Employee.cedula == r.cedula).first()
            comp = None
            if emp and emp.company_id:
                comp = db.query(Company).filter(Company.id == emp.company_id).first()
            
            empleados.append({
                "cedula": r.cedula,
                "nombre": emp.nombre if emp else r.cedula,
                "empresa": comp.nombre if comp else "",
                "area": emp.area_trabajo if emp else "",
                "cargo": emp.cargo if emp else "",
                "eps": emp.eps if emp else "",
                "total_incapacidades": r.total,
                "total_dias": r.dias or 0,
                "primera_fecha": r.primera.strftime("%Y-%m-%d") if r.primera else "",
                "ultima_fecha": r.ultima.strftime("%Y-%m-%d") if r.ultima else "",
            })
        
        return {"ok": True, "resultados": empleados, "total": len(empleados)}
    
    except Exception as e:
        logger.error(f"Error PowerBI buscar: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 8️⃣ ENDPOINT: POWER BI — VISTA GLOBAL (todas las personas)
# ============================================================
@router.get("/powerbi/global")
async def powerbi_global(
    empresa: str = Query("all", description="Filtrar por empresa"),
    cedulas: str = Query("", description="Cédulas separadas por coma"),
    db: Session = Depends(get_db)
):
    """
    📊 POWER BI GLOBAL — Vista de TODAS las personas con su estado de prórroga,
    180 días, gaps, etc. Para visualización masiva.
    """
    try:
        from datetime import date as date_type

        # Base query: agrupar por cédula
        base_q = db.query(Case.cedula).distinct()

        if cedulas and cedulas.strip():
            lista_ced = [c.strip() for c in cedulas.split(",") if c.strip()]
            if lista_ced:
                base_q = base_q.filter(Case.cedula.in_(lista_ced))

        if empresa != "all":
            company = db.query(Company).filter(Company.nombre == empresa).first()
            if company:
                base_q = base_q.filter(Case.company_id == company.id)

        cedulas_unicas = [r[0] for r in base_q.limit(200).all()]

        # Analizar cada persona
        personas = []
        categorias = {
            "superan_180": [],
            "cerca_180": [],
            "con_gaps_criticos": [],
            "prorrogas_activas": [],
            "sin_prorroga": [],
        }
        
        resumen_global = {
            "total_personas": len(cedulas_unicas),
            "total_incapacidades": 0,
            "total_dias": 0,
            "total_prorrogas": 0,
            "total_gaps_criticos": 0,
        }

        for ced in cedulas_unicas:
            casos = db.query(Case).filter(Case.cedula == ced).order_by(Case.fecha_inicio.asc()).all()
            if not casos:
                continue

            emp = db.query(Employee).filter(Employee.cedula == ced).first()
            comp = None
            if emp and emp.company_id:
                comp = db.query(Company).filter(Company.id == emp.company_id).first()

            analisis = analizar_historial_empleado(db, ced)
            
            total_dias = sum(c.dias_incapacidad or 0 for c in casos)
            cadenas_activas = [c for c in analisis.get("cadenas_prorroga", []) if c.get("es_cadena_prorroga")]
            max_cadena = max((c["dias_acumulados"] for c in cadenas_activas), default=0)
            
            # Detectar gaps
            gaps_criticos = 0
            total_gaps = 0
            for i in range(len(casos) - 1):
                fin_a = casos[i].fecha_fin or casos[i].fecha_inicio
                inicio_b = casos[i + 1].fecha_inicio
                if fin_a and inicio_b:
                    brecha = ((inicio_b.date() if hasattr(inicio_b, 'date') else inicio_b) -
                              (fin_a.date() if hasattr(fin_a, 'date') else fin_a)).days
                    if brecha > 1:
                        total_gaps += 1
                        if brecha > 30:
                            gaps_criticos += 1

            persona = {
                "cedula": ced,
                "nombre": emp.nombre if emp else ced,
                "empresa": comp.nombre if comp else "",
                "area": emp.area_trabajo if emp else "",
                "cargo": emp.cargo if emp else "",
                "eps": emp.eps if emp else "",
                "total_incapacidades": len(casos),
                "total_dias": total_dias,
                "cadenas_prorroga": len(cadenas_activas),
                "max_cadena_dias": max_cadena,
                "gaps_criticos": gaps_criticos,
                "total_gaps": total_gaps,
                "tiene_prorroga": len(cadenas_activas) > 0,
                "supera_180": max_cadena >= 180,
                "cerca_180": 150 <= max_cadena < 180,
                "alertas_count": len(analisis.get("alertas_180", [])),
                "huecos_count": len(analisis.get("huecos_detectados", [])),
                "primera_fecha": casos[0].fecha_inicio.strftime("%Y-%m-%d") if casos[0].fecha_inicio else "",
                "ultima_fecha": casos[-1].fecha_inicio.strftime("%Y-%m-%d") if casos[-1].fecha_inicio else "",
                "pct_180": round(min(max_cadena / 180 * 100, 100), 1) if max_cadena > 0 else 0,
            }
            personas.append(persona)

            # Categorizar
            resumen_global["total_incapacidades"] += len(casos)
            resumen_global["total_dias"] += total_dias
            resumen_global["total_prorrogas"] += len(cadenas_activas)
            resumen_global["total_gaps_criticos"] += gaps_criticos

            if max_cadena >= 180:
                categorias["superan_180"].append(persona)
            elif max_cadena >= 150:
                categorias["cerca_180"].append(persona)
            elif gaps_criticos > 0:
                categorias["con_gaps_criticos"].append(persona)
            elif len(cadenas_activas) > 0:
                categorias["prorrogas_activas"].append(persona)
            else:
                categorias["sin_prorroga"].append(persona)

        # Ordenar cada categoría por días desc
        for cat in categorias.values():
            cat.sort(key=lambda x: -x["max_cadena_dias"])

        # Top 10 por días acumulados
        top_dias = sorted(personas, key=lambda x: -x["total_dias"])[:10]
        # Top 10 por más incapacidades
        top_frecuencia = sorted(personas, key=lambda x: -x["total_incapacidades"])[:10]

        # Distribución por empresa
        por_empresa = {}
        for p in personas:
            emp_key = p["empresa"] or "Sin empresa"
            if emp_key not in por_empresa:
                por_empresa[emp_key] = {"empresa": emp_key, "personas": 0, "incapacidades": 0, "dias": 0, "prorrogas": 0, "gaps_criticos": 0}
            por_empresa[emp_key]["personas"] += 1
            por_empresa[emp_key]["incapacidades"] += p["total_incapacidades"]
            por_empresa[emp_key]["dias"] += p["total_dias"]
            por_empresa[emp_key]["prorrogas"] += p["cadenas_prorroga"]
            por_empresa[emp_key]["gaps_criticos"] += p["gaps_criticos"]

        return {
            "ok": True,
            "resumen": resumen_global,
            "categorias": {
                "superan_180": {"label": "Superan 180 días", "color": "#ef4444", "personas": categorias["superan_180"]},
                "cerca_180": {"label": "Cerca de 180 días (150-179)", "color": "#f97316", "personas": categorias["cerca_180"]},
                "con_gaps_criticos": {"label": "Con gaps que cortan prórroga", "color": "#eab308", "personas": categorias["con_gaps_criticos"]},
                "prorrogas_activas": {"label": "Prórrogas activas (<150d)", "color": "#3b82f6", "personas": categorias["prorrogas_activas"]},
                "sin_prorroga": {"label": "Sin cadena de prórroga", "color": "#10b981", "personas": categorias["sin_prorroga"]},
            },
            "top_dias": top_dias,
            "top_frecuencia": top_frecuencia,
            "por_empresa": sorted(por_empresa.values(), key=lambda x: -x["dias"]),
            "personas": personas,
        }

    except Exception as e:
        logger.error(f"Error PowerBI global: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 🔄 ENDPOINT: ESTADO DE SINCRONIZACIÓN BD ↔ EXCEL
# ============================================================

@router.get("/sync/estado")
async def get_estado_sync():
    """
    📊 Estado en tiempo real de la sincronización BD ↔ Excel Kactus
    - Casos con/sin datos Kactus
    - Casos con/sin diagnóstico y CIE-10
    - Traslapos detectados
    - Última sincronización
    """
    from app.sync_excel import obtener_estado_sync
    return obtener_estado_sync()


@router.get("/sync/traslapos")
async def get_traslapos(
    empresa: str = Query("all"),
    db: Session = Depends(get_db)
):
    """
    🔀 Listado de todas las incapacidades con traslapo de fechas detectado
    """
    try:
        query = db.query(Case).filter(Case.dias_traslapo > 0)
        
        if empresa != "all":
            company = db.query(Company).filter(Company.nombre == empresa).first()
            if company:
                query = query.filter(Case.company_id == company.id)
        
        traslapos = query.order_by(Case.fecha_inicio.desc()).all()
        
        resultado = []
        for caso in traslapos:
            emp = db.query(Employee).filter(Employee.cedula == caso.cedula).first()
            comp = db.query(Company).filter(Company.id == caso.company_id).first() if caso.company_id else None
            
            resultado.append({
                "serial": caso.serial,
                "cedula": caso.cedula,
                "nombre": emp.nombre if emp else "?",
                "empresa": comp.nombre if comp else "?",
                "tipo": caso.tipo.value if caso.tipo else None,
                "fecha_inicio_original": str(caso.fecha_inicio.date()) if caso.fecha_inicio else None,
                "fecha_fin_original": str(caso.fecha_fin.date()) if caso.fecha_fin else None,
                "fecha_inicio_kactus": str(caso.fecha_inicio_kactus.date()) if caso.fecha_inicio_kactus else None,
                "fecha_fin_kactus": str(caso.fecha_fin_kactus.date()) if caso.fecha_fin_kactus else None,
                "dias_incapacidad_original": caso.dias_incapacidad,
                "dias_kactus": caso.dias_kactus,
                "dias_traslapo": caso.dias_traslapo,
                "traslapo_con_serial": caso.traslapo_con_serial,
                "diagnostico": caso.diagnostico,
                "codigo_cie10": caso.codigo_cie10,
                "diagnostico_kactus": caso.diagnostico_kactus,
                "estado": caso.estado.value if caso.estado else None,
                "kactus_sync_at": str(caso.kactus_sync_at) if caso.kactus_sync_at else None,
            })
        
        return {
            "ok": True,
            "total": len(resultado),
            "traslapos": resultado
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/vaciar-kactus")
async def vaciar_kactus_manual():
    """
    🗑️ Vaciar manualmente la Hoja 3 (Cases_Kactus) del Excel.
    Solo funciona si todos los datos ya están sincronizados en BD.
    """
    try:
        from app.sync_excel import vaciar_hoja_kactus_quincenal
        vaciar_hoja_kactus_quincenal()
        return {"ok": True, "mensaje": "Vaciado ejecutado — verificar logs"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

