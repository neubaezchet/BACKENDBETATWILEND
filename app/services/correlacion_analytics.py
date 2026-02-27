"""
ANALYTICS DE CORRELACIONES CIE-10 — 4 Sistemas NO Explotados Activados
========================================================================

1. APRENDIZAJE: Registra correcciones manuales para reentrenamiento
2. EXCLUSIONES: Valida constantemente pares que NO correlacionan  
3. DEGRADACIÓN TEMPORAL: Reduce confianza con el tiempo
4. ANÁLISIS INTER-EMPLEADOS: Detecta patrones anómalos por departamento

Normativa: Ley 776/2002, Decreto 1427/2022, GPC MinSalud
"""

import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from app.database import Case, Employee
from app.services.cie10_service import (
    _normalizar_codigo,
    _cargar_validaciones,
    _buscar_exclusion,
    _obtener_factor_temporal,
    registrar_validacion,
    recargar_datos,
    son_correlacionados,
)

_DATA_DIR = Path(__file__).parent.parent / "data"


# ═══════════════════════════════════════════════════════════
# 1. SISTEMA DE APRENDIZAJE — Usar validaciones para reentrenar
# ═══════════════════════════════════════════════════════════

def obtener_precision_correlaciones() -> dict:
    """Retorna estadísticas de precisión del sistema de correlaciones históricamente"""
    validaciones = _cargar_validaciones()
    stats = validaciones.get("estadisticas", {})
    
    total = stats.get("total_validaciones", 0)
    confirmados = stats.get("correlaciones_confirmadas", 0)
    rechazados = stats.get("correlaciones_rechazadas", 0)
    
    return {
        "total_validaciones": total,
        "confirmadas": confirmados,
        "rechazadas": rechazados,
        "precision_historica_%": stats.get("precision_historica", 0),
        "ultima_actualizacion": stats.get("ultima_actualizacion", None),
        "interprettacion": (
            f"El sistema ha validado {total} pares de códigos. "
            f"{confirmados} resultaron como prórroga real, "
            f"{rechazados} fueron falsas correlaciones."
        ),
        "ajustes_aprendidos": len(validaciones.get("ajustes_aprendidos", {}))
    }


def obtener_correlaciones_aprendidas() -> dict:
    """Retorna los ajustes aprendidos de mayor impacto en precisión"""
    validaciones = _cargar_validaciones()
    ajustes = validaciones.get("ajustes_aprendidos", {})
    
    # Ordenar por total_casos (más datos = más confiable)
    mejores = sorted(
        [
            {
                "par": clave,
                "casos": aj.get("total_casos", 0),
                "confirmados": aj.get("confirmados", 0),
                "rechazados": aj.get("rechazados", 0),
                "asertividad_ajustada": aj.get("asertividad_ajustada", 0),
                "cod1": clave.split("_")[0],
                "cod2": clave.split("_")[1],
            }
            for clave, aj in ajustes.items()
        ],
        key=lambda x: x["casos"],
        reverse=True
    )[:15]  # Top 15
    
    return {
        "total_ajustes": len(ajustes),
        "top_15_pares_aprendidos": mejores,
        "interpretacion": (
            "Estos pares han sido validados múltiples veces. "
            "Los confirmados indican prórroga real; los rechazados evitan falsas detecciones."
        )
    }


# ═══════════════════════════════════════════════════════════
# 2. REGLAS DE EXCLUSIÓN — Validar constantemente
# ═══════════════════════════════════════════════════════════

def validar_exclusion_par(codigo1: str, codigo2: str) -> dict:
    """
    Valida si un par de códigos tiene una regla de exclusión ACTIVA.
    Retorna advertencia si el par es incompatible.
    """
    cod1 = _normalizar_codigo(codigo1)
    cod2 = _normalizar_codigo(codigo2)
    
    excl = _buscar_exclusion(cod1, cod2)
    
    if excl:
        return {
            "excluida": True,
            "razon": excl.get("razon", ""),
            "evidencia": excl.get("evidencia", ""),
            "normativa": excl.get("normativa", ""),
            "mensaje": (
                f"⚠️  EXCLUSIÓN ACTIVA: {cod1} y {cod2} NO pueden correlacionar. "
                f"Razón: {excl.get('razon', 'No especificada')}"
            ),
            "tipo_excluida": excl.get("tipo", "incompatible")
        }
    
    return {
        "excluida": False,
        "mensaje": f"{cod1} y {cod2} pueden correlacionar (sin exclusión)",
        "tipo_excluida": None
    }


def obtener_reglas_exclusion() -> dict:
    """Retorna todas las exclusiones activas"""
    validaciones = _cargar_validaciones()
    from app.services.cie10_service import _cargar_exclusiones
    
    exclusiones = _cargar_exclusiones()
    
    reglas = []
    for excl in exclusiones.get("exclusiones", []):
        reglas.append({
            "codigo_a": excl.get("codigo_a", ""),
            "codigo_b": excl.get("codigo_b", ""),
            "razon": excl.get("razon", ""),
            "tipo": excl.get("tipo", "incompatible"),
            "vigente": excl.get("vigente", True)
        })
    
    return {
        "total_exclusiones_activas": len([r for r in reglas if r["vigente"]]),
        "excluidas": reglas,
        "interpretacion": "Estos pares de diagnósticos NO pueden ser prórroga uno del otro (incompatibles clínicamente)"
    }


# ═══════════════════════════════════════════════════════════
# 3. DEGRADACIÓN TEMPORAL — Reducir confianza con días
# ═══════════════════════════════════════════════════════════

def calcular_asertividad_con_degradacion(
    codigo1: str,
    codigo2: str,
    dias_entre: int,
    grupo_correlacion: str = "DEFAULT"
) -> dict:
    """
    Calcula asertividad CON degradación temporal.
    A mayor número de días entre incapacidades, menor confianza en prórroga.
    """
    cod1 = _normalizar_codigo(codigo1)
    cod2 = _normalizar_codigo(codigo2)
    
    # Obtener asertividad base (sin degradación)
    corr_base = son_correlacionados(cod1, cod2)
    asertividad_base = corr_base.get("asertividad", 0.0)
    
    # Obtener factor temporal (degradación)
    factor_temp = _obtener_factor_temporal(grupo_correlacion, dias_entre)
    factor = factor_temp.get("factor", 1.0)
    
    # Aplicar degradación
    asertividad_degradada = asertividad_base * factor
    
    # Determinar confianza resultante
    if asertividad_degradada >= 80:
        confianza = "MUY_ALTA"
    elif asertividad_degradada >= 60:
        confianza = "ALTA"
    elif asertividad_degradada >= 40:
        confianza = "MEDIA"
    elif asertividad_degradada >= 20:
        confianza = "BAJA"
    else:
        confianza = "NINGUNA"
    
    return {
        "codigo1": cod1,
        "codigo2": cod2,
        "dias_entre": dias_entre,
        "asertividad_base": round(asertividad_base, 1),
        "factor_temporal": round(factor, 2),
        "asertividad_degradada": round(asertividad_degradada, 1),
        "confianza": confianza,
        "mensaje_temporal": factor_temp.get("nota", ""),
        "interpretacion": (
            f"Base {asertividad_base}% × {factor} (factor temporal) = "
            f"{asertividad_degradada}% ({confianza}). "
            f"Con {dias_entre} días entre incapacidades, la confianza se reduce."
        ),
        "recomendacion": (
            "Prórroga probable" if asertividad_degradada >= 60
            else "Prórroga posible — requiere validación médica" if asertividad_degradada >= 40
            else "NO es prórroga — validación negativa"
        )
    }


# ═══════════════════════════════════════════════════════════
# 4. ANÁLISIS INTER-EMPLEADOS — Patrones por departamento
# ═══════════════════════════════════════════════════════════

def analizar_patrones_por_departamento(db: Session) -> dict:
    """
    Analiza patrones de prórrogas y diagnósticos por departamento.
    Detecta anomalías: "Dpto X tiene 3x más códigos respiratorios que media"
    """
    
    # Obtener todos los casos agrupados por empresa
    casos = db.query(Case).filter(Case.estado != "DESECHADO").all()
    empleados = db.query(Employee).filter(Employee.activo == True).all()
    
    # Mapeo: cedula → empresa
    cedula_a_empresa = {}
    cedula_a_area = {}
    for emp in empleados:
        cedula_a_empresa[emp.cedula] = emp.company.nombre if emp.company else "SIN_EMPRESA"
        cedula_a_area[emp.cedula] = emp.area_trabajo or "SIN_AREA"
    
    # Agrupar casos por empresa y área
    patrones = {}
    
    for caso in casos:
        empresa = cedula_a_empresa.get(caso.cedula, "DESCONOCIDA")
        area = cedula_a_area.get(caso.cedula, "DESCONOCIDA")
        
        if empresa not in patrones:
            patrones[empresa] = {}
        
        if area not in patrones[empresa]:
            patrones[empresa][area] = {
                "total_incapacidades": 0,
                "total_empleados_unicos": set(),
                "total_dias": 0,
                "codigo_cie10_frecuencia": {},
                "sistema_anatomico_frecuencia": {},
                "prorrogas_detectadas": 0,
                "cerca_180_dias": 0,
                "supero_180_dias": 0,
            }
        
        area_stats = patrones[empresa][area]
        area_stats["total_incapacidades"] += 1
        area_stats["total_empleados_unicos"].add(caso.cedula)
        area_stats["total_dias"] += caso.dias_incapacidad or 0
        
        if caso.codigo_cie10:
            codigo = _normalizar_codigo(caso.codigo_cie10)
            area_stats["codigo_cie10_frecuencia"][codigo] = \
                area_stats["codigo_cie10_frecuencia"].get(codigo, 0) + 1
        
        if caso.es_prorroga:
            area_stats["prorrogas_detectadas"] += 1
    
    # Calcular promedios globales para comparación
    total_empresas = len([p for empresa, areas in patrones.items() for area, s in areas.items()])
    promedio_dias_por_incap = 0
    promedio_prorroga_pct = 0
    
    if total_empresas > 0:
        todas_incaps = sum(
            s["total_incapacidades"]
            for empresa, areas in patrones.items()
            for s in areas.values()
        )
        todos_dias = sum(
            s["total_dias"]
            for empresa, areas in patrones.items()
            for s in areas.values()
        )
        todas_prorrogas = sum(
            s["prorrogas_detectadas"]
            for empresa, areas in patrones.items()
            for s in areas.values()
        )
        
        promedio_dias_por_incap = todos_dias / todas_incaps if todas_incaps > 0 else 0
        promedio_prorroga_pct = (todas_prorrogas / todas_incaps * 100) if todas_incaps > 0 else 0
    
    # Procesar resultados y detectar anomalías
    resultados = {
        "analisis_por_empresa": {},
        "anomalias_detectadas": [],
        "promedios_globales": {
            "dias_promedio_por_incapacidad": round(promedio_dias_por_incap, 1),
            "porcentaje_prorrogas": round(promedio_prorroga_pct, 1),
        }
    }
    
    for empresa, areas in patrones.items():
        resultados["analisis_por_empresa"][empresa] = {}
        
        for area, stats in areas.items():
            num_empleados = len(stats["total_empleados_unicos"])
            pct_prorrogas = (stats["prorrogas_detectadas"] / stats["total_incapacidades"] * 100) \
                if stats["total_incapacidades"] > 0 else 0
            dias_promedio = (stats["total_dias"] / stats["total_incapacidades"]) \
                if stats["total_incapacidades"] > 0 else 0
            
            # Top 3 códigos más frecuentes en esta área
            top_codigos = sorted(
                stats["codigo_cie10_frecuencia"].items(),
                key=lambda x: x[1],
                reverse=True
            )[:3]
            
            area_info = {
                "total_incapacidades": stats["total_incapacidades"],
                "empleados_unicos": num_empleados,
                "dias_acumulados": stats["total_dias"],
                "dias_promedio_por_incap": round(dias_promedio, 1),
                "prorrogas_porcentaje": round(pct_prorrogas, 1),
                "cerca_180_dias": stats["cerca_180_dias"],
                "supero_180_dias": stats["supero_180_dias"],
                "codigos_top_3": top_codigos,
            }
            
            resultados["analisis_por_empresa"][empresa][area] = area_info
            
            # Detectar anomalías
            # Anomalía 1: % de prorrogas > 2x el promedio
            if pct_prorrogas > (promedio_prorroga_pct * 2):
                resultados["anomalias_detectadas"].append({
                    "tipo": "PRORROGAS_ALTAS",
                    "severidad": "alta",
                    "empresa": empresa,
                    "area": area,
                    "valor": round(pct_prorrogas, 1),
                    "promedio_sistema": round(promedio_prorroga_pct, 1),
                    "multiplicador": round(pct_prorrogas / (promedio_prorroga_pct or 1), 1),
                    "mensaje": (
                        f"⚠️  {empresa} - {area}: "
                        f"{pct_prorrogas}% de prorrogas (sistema: {promedio_prorroga_pct}%). "
                        f"Investigar si hay problemas de retorno al trabajo."
                    ),
                    "acciones": "Revisar historiales, validar diagnósticos con ARL"
                })
            
            # Anomalía 2: Días promedio muy alto (>15 días)
            if dias_promedio > 15:
                resultados["anomalias_detectadas"].append({
                    "tipo": "DURACION_LARGA",
                    "severidad": "media",
                    "empresa": empresa,
                    "area": area,
                    "valor": round(dias_promedio, 1),
                    "promedio_sistema": round(promedio_dias_por_incap, 1),
                    "mensaje": (
                        f"🔷 {empresa} - {area}: "
                        f"Promedio {dias_promedio}d por incapacidad (sistema: {promedio_dias_por_incap}d). "
                        f"Puede indicar diagnósticos más severos."
                    ),
                    "acciones": "Valorar si se requiere intervención de salud ocupacional"
                })
            
            # Anomalía 3: Concentración de un diagnóstico (>30% del área)
            if top_codigos:
                top_codigo, frecuencia = top_codigos[0]
                pct_top = (frecuencia / stats["total_incapacidades"] * 100) if stats["total_incapacidades"] > 0 else 0
                if pct_top > 30:
                    resultados["anomalias_detectadas"].append({
                        "tipo": "DIAGNOSTICO_CONCENTRADO",
                        "severidad": "media",
                        "empresa": empresa,
                        "area": area,
                        "codigo_cie10": top_codigo,
                        "porcentaje": round(pct_top, 1),
                        "casos": frecuencia,
                        "mensaje": (
                            f"🔷 {empresa} - {area}: "
                            f"{pct_top}% de incapacidades son {top_codigo} ({frecuencia} casos). "
                            f"Posible factor ocupacional común."
                        ),
                        "acciones": "Evaluación ocupacional, ergonomía, condiciones de trabajo"
                    })
    
    return resultados


def generar_indicadores_confiabilidad() -> dict:
    """
    Genera indicadores de cuán confiables son las correlaciones detectadas.
    Basado en: Historial de validaciones, exclusiones aplicadas, patrones.
    """
    
    # Obtener historial
    historial = obtener_precision_correlaciones()
    aprendidas = obtener_correlaciones_aprendidas()
    exclusiones = obtener_reglas_exclusion()
    
    precision_pct = historial["precision_historica_%"]
    total_validaciones = historial["total_validaciones"]
    
    # Calcular confiabilidad general
    if total_validaciones >= 100:
        nivel_madurez = "MADURO"
        descripcion = "Sistema entrenado con 100+ validaciones"
    elif total_validaciones >= 30:
        nivel_madurez = "DESARROLLANDO"
        descripcion = "Sistema en desarrollo (30+ validaciones)"
    else:
        nivel_madurez = "INICIAL"
        descripcion = "Sistema inicial con pocas validaciones"
    
    # Indicador de confiabilidad global
    if precision_pct >= 85 and total_validaciones >= 50:
        confiabilidad_general = "ALTA"
        color = "🟢"
    elif precision_pct >= 70 or total_validaciones >= 20:
        confiabilidad_general = "MEDIA"
        color = "🟡"
    else:
        confiabilidad_general = "BAJA"
        color = "🔴"
    
    return {
        "confiabilidad_general": confiabilidad_general,
        "color": color,
        "nivel_madurez": nivel_madurez,
        "descripcion": descripcion,
        "precision_historica_%": round(precision_pct, 1),
        "total_validaciones_realizadas": total_validaciones,
        "pares_aprendidos": aprendidas["total_ajustes"],
        "reglas_exclusion_activas": exclusiones["total_exclusiones_activas"],
        "recomendaciones": _generar_recomendaciones(precision_pct, total_validaciones),
        "interpretacion": (
            f"El sistema ha validado {total_validaciones} pares de diagnósticos "
            f"con {precision_pct}% de precisión. "
            f"{aprendidas['total_ajustes']} pares han sido ajustados por el aprendizaje histórico. "
            f"Confiabilidad: {confiabilidad_general} 🎯"
        )
    }


def _generar_recomendaciones(precision: float, validaciones: int) -> List[str]:
    """Genera recomendaciones según el estado del sistema"""
    recomendaciones = []
    
    if validaciones < 20:
        recomendaciones.append("⭐ Realizar más validaciones manuales para entrenar el sistema")
    
    if precision < 70:
        recomendaciones.append("⚠️  Precisión baja (<70%) — revisar exclusiones y reglas direccionales")
    
    if precision >= 85:
        recomendaciones.append("✅ Precisión alta — el sistema está aprendiendo correctamente")
    
    return recomendaciones


def detectar_anomalias_correlacion(db: Session) -> dict:
    """
    Detecta anomalías en correlaciones:
    - Pares que se marcan como prórroga pero luego se rechazan
    - Casesentre empleados con mismo diagnóstico pero resultados diferentes
    """
    validaciones = _cargar_validaciones()
    
    hist = validaciones.get("validaciones", [])
    
    # Agrupar por par de códigos
    pares_analisis = {}
    
    for reg in hist:
        par = f"{reg.get('codigo_a')}_{reg.get('codigo_b')}"
        if par not in pares_analisis:
            pares_analisis[par] = {"confirmados": 0, "rechazados": 0}
        
        if reg.get("resultado") == "CONFIRMADO":
            pares_analisis[par]["confirmados"] += 1
        else:
            pares_analisis[par]["rechazados"] += 1
    
    anomalias = []
    
    for par, conteos in pares_analisis.items():
        total = conteos["confirmados"] + conteos["rechazados"]
        
        # Si se rechaza >50% del tiempo, algo está mal
        if total >= 3 and conteos["rechazados"] > conteos["confirmados"]:
            cod1, cod2 = par.split("_")
            anomalias.append({
                "tipo": "FALSO_POSITIVO_FRECUENTE",
                "par": f"{cod1} → {cod2}",
                "casos_confirmados": conteos["confirmados"],
                "casos_rechazados": conteos["rechazados"],
                "tasa_rechazo_%": round((conteos["rechazados"] / total * 100), 1),
                "mensaje": (
                    f"⚠️  Par {cod1}→{cod2} se marca como prórroga pero "
                    f"{conteos['rechazados']}x fue rechazado vs {conteos['confirmados']}x confirmado. "
                    f"Revisar regla de correlación."
                ),
                "accion": "Aumentar umbral de asertividad o revisar exclusión"
            })
    
    return {
        "total_anomalias": len(anomalias),
        "anomalias": anomalias,
        "interpretacion": (
            "Estos pares de diagnósticos se comportan de manera inconsistente. "
            "Pueden indicar problemas en las reglas de correlación."
        )
    }
