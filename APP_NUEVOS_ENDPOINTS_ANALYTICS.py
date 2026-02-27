"""
ENDPOINT: Analytics CIE-10 — 4 Sistemas NO Explotados
Agregados al final de reportes.py
"""

# Este archivo contiene los endpoints nuevos que deben agregarse al final de:
# c:\Users\Administrador\Documents\GitHub\BACKENDBETATWILEND\app\routes\reportes.py

# ═══════════════════════════════════════════════════════════════
# 🧪 ENDPOINT: ANALYTICS CIE-10 GENERAL
# ═══════════════════════════════════════════════════════════════

@router.get("/analytics/cie10")
async def get_analytics_cie10(db: Session = Depends(get_db)):
    """
    🎯 ANALYTICS CIE-10 — Análisis de cuán confiables son las correlaciones

    Retorna 4 sistemas NO explotados activados:
    1. APRENDIZAJE: Precisión histórica, pares más validados
    2. EXCLUSIONES: Reglas de pares que NO correlacionan
    3. DEGRADACIÓN TEMPORAL: Cómo cae la confianza con el tiempo
    4. CONFIABILIDAD GENERAL: Indicadores de madurez del sistema

    Endpoints relacionados:
    - GET /validador/casos/analytics/cie10/patrones
    - GET /validador/casos/analytics/cie10/anomalias
    """
    try:
        # 1. SISTEMA DE APRENDIZAJE
        precision = obtener_precision_correlaciones()
        aprendizo = obtener_correlaciones_aprendidas()

        # 2. REGLAS DE EXCLUSIÓN
        exclusiones = obtener_reglas_exclusion()

        # 3. INDICADORES DE CONFIABILIDAD
        confiabilidad = generar_indicadores_confiabilidad()

        return {
            "ok": True,
            "timestamp": datetime.now().isoformat(),
            "resumen": {
                "sistemas_activados": 4,
                "confiabilidad_general": confiabilidad["confiabilidad_general"],
                "color": confiabilidad["color"],
                "nivel_madurez": confiabilidad["nivel_madurez"],
                "precision_historica_%": precision["precision_historica_%"],
                "total_validaciones": precision["total_validaciones"],
            },
            "1_sistema_aprendizaje": {
                "titulo": "📚 Sistema de Aprendizaje",
                "descripcion": "Correlaciones aprendidas de validaciones manuales",
                "precision": precision,
                "top_pares_aprendidos": aprendizo["top_15_pares_aprendidos"],
            },
            "2_reglas_exclusion": {
                "titulo": "⛔ Reglas de Exclusión",
                "descripcion": "Pares de diagnósticos que NO pueden correlacionar",
                "total_activas": exclusiones["total_exclusiones_activas"],
                "primeras_5": exclusiones["excluidas"][:5],
                "interpretacion": exclusiones["interpretacion"],
            },
            "3_degradacion_temporal": {
                "titulo": "⏰ Degradación Temporal",
                "descripcion": "Cómo caen los umbrales de confianza con el tiempo",
                "ejemplo": calcular_asertividad_con_degradacion("A09", "K21", 30),
                "nota": "A mayor número de días entre incapacidades, menor confianza.",
            },
            "4_confiabilidad_general": {
                "titulo": "🎯 Indicadores de Confiabilidad",
                "descripcion": "Estado general de precisión y madurez del sistema",
                "datos": confiabilidad,
            },
        }

    except Exception as e:
        logger.error(f"Error analytics CIE-10: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# 🏢 ENDPOINT: ANALYTICS CIE-10 POR DEPARTAMENTO
# ═══════════════════════════════════════════════════════════════

@router.get("/analytics/cie10/departamentos")
async def get_analytics_departamentos(db: Session = Depends(get_db)):
    """
    🏢 ANALYTICS POR DEPARTAMENTO
    Detecta patrones anómalos:
    - Departamento X tiene 3x más prórrogas que media
    - Concentración de diagnóstico singular (>30% del área)
    - Duración promedio atípica

    Retorna:
    - Análisis por empresa y área
    - Anomalías detectadas con severidad
    - Recomendaciones de acción
    """
    try:
        patrones = analizar_patrones_por_departamento(db)

        return {
            "ok": True,
            "timestamp": datetime.now().isoformat(),
            "promedios_globales": patrones["promedios_globales"],
            "resumen_ejecutivo": {
                "total_empresas": len(patrones["analisis_por_empresa"]),
                "total_areas": sum(
                    len(areas) for areas in patrones["analisis_por_empresa"].values()
                ),
                "anomalias_detectadas": len(patrones["anomalias_detectadas"]),
                "severidad_critica": len([a for a in patrones["anomalias_detectadas"] if a["severidad"] == "critica"]),
                "severidad_media": len([a for a in patrones["anomalias_detectadas"] if a["severidad"] == "media"]),
            },
            "analisis_por_empresa": patrones["analisis_por_empresa"],
            "anomalias": patrones["anomalias_detectadas"],
            "recomendaciones": _generar_recomendaciones_por_departamento(patrones),
        }

    except Exception as e:
        logger.error(f"Error analytics departamentos: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _generar_recomendaciones_por_departamento(patrones: dict) -> List[str]:
    """Genera recomendaciones específicas según anomalías detectadas"""
    recs = []
    anomalias = patrones.get("anomalias_detectadas", [])

    prorrogas_altas = [a for a in anomalias if a["tipo"] == "PRORROGAS_ALTAS"]
    duracion_larga = [a for a in anomalias if a["tipo"] == "DURACION_LARGA"]
    diag_concentrado = [a for a in anomalias if a["tipo"] == "DIAGNOSTICO_CONCENTRADO"]

    if prorrogas_altas:
        recs.append(
            f"🔴 CRÍTICO: {len(prorrogas_altas)} área(s) con >2x tasa de prorrogas. "
            "Revisar historiales de empleados, validar diagnósticos con ARL/EPS."
        )

    if duracion_larga:
        recs.append(
            f"🟡 REFERENCIA: {len(duracion_larga)} área(s) con duración >15d promedio. "
            "Evaluar si hay diagnósticos más severos o retrasos en autorización."
        )

    if diag_concentrado:
        recs.append(
            f"🟡 OCUPACIONAL: {len(diag_concentrado)} área(s) con diagnóstico concentrado. "
            "Posible factor ocupacional común - Evaluación ergonómica recomendada."
        )

    if not recs:
        recs.append("✅ Sistema dentro de parámetros normales. Sin anomalías críticas detectadas.")

    return recs


# ═══════════════════════════════════════════════════════════════
# 🚨 ENDPOINT: ALERT

AS ANOMALÍAS EN CORRELACIONES
# ═══════════════════════════════════════════════════════════════

@router.get("/analytics/cie10/anomalias")
async def get_analytics_anomalias(db: Session = Depends(get_db)):
    """
    🚨 DETECCIÓN DE ANOMALÍAS EN CORRELACIONES
    Identifica pares de diagnósticos que se comportan de manera inconsistente
    - Correlación detectada N veces
    - Pero rechazada también N veces
    - Indica problema en la regla de correlación

    Ejemplo: A09 → K21 marcado como prórroga 5 veces, pero rechazado 7 veces
    → Aumentar umbral de asertividad o revisar exclusión
    """
    try:
        anomalias = detectar_anomalias_correlacion(db)

        return {
            "ok": True,
            "timestamp": datetime.now().isoformat(),
            "resumen": {
                "total_anomalias": anomalias["total_anomalias"],
                "pares_problematicos": len(anomalias["anomalias"]),
                "interpretacion": anomalias["interpretacion"],
            },
            "anomalias_detectadas": sorted(
                anomalias["anomalias"],
                key=lambda x: -x["tasa_rechazo_%"]
            ),
            "recomendaciones": [
                "🔍 Revisar cada par problemático",
                "📊 Aumentar umbral de asertividad para pares con >50% rechazo",
                "⚖️ Evaluar si necesita regla de exclusión bidireccional",
                "📚 Registrar decisión en validaciones_historicas.json para aprendizaje",
            ],
        }

    except Exception as e:
        logger.error(f"Error analytics anomalías: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

