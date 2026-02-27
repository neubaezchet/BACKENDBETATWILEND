"""
DETECTOR DE PRÓRROGAS v3 — Motor con detección de huecos temporales
=====================================================================
Analiza el historial de incapacidades de un empleado,
detecta prórrogas automáticamente por correlación CIE-10,
cuenta días acumulados, detecta huecos en cadenas de prórroga,
y alerta al acercarse a 180 días.

REGLA DE CORTE 30 DÍAS:
- Si pasan 30+ días sin nueva incapacidad → la cadena de prórroga se CORTA
- El sistema registra el hueco y alerta a Talento Humano
- Si el empleado envía después un certificado que llena el hueco → llenado retroactivo
- Se calcula "días en incapacidad" (total) vs "días en prórroga" (cadena activa)

REGLA DE HUECOS TEMPORALES (<30 DÍAS): ⭐ NUEVO v3
- Si aparece un diagnóstico NO CORRELACIONADO que dura <30 días
  ENTRE dos diagnósticos SÍ correlacionados, la cadena NO se rompe.
- Los días del diagnóstico no correlacionado NO se cuentan en la cadena.
- Ejemplo: A09(60d) → J00(10d) → A09(20d) = cadena de 80d (J00 ignorado)
- Si el diagnóstico no correlacionado dura ≥30 días → SÍ rompe la cadena.

Normativa colombiana aplicable:
- Ley 776/2002 Art. 3: Incapacidad temporal hasta 180 días calendario
- Decreto 1427/2022: Procedimiento de incapacidades
- Art. 142 Decreto 019/2012: Prórroga y reconocimiento
- Los primeros 2 días los paga el empleador (incapacidad ≤ 2 días)
- Del día 3 al 180: EPS paga 66.67% del salario
- Del día 181 al 540: Fondo de Pensiones paga 50% del salario (con concepto favorable)
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.database import Case, Employee
from app.services.cie10_service import (
    son_correlacionados,
    buscar_codigo,
    _normalizar_codigo,
    validar_conteo_dias,
    _cargar_correlaciones,
)
import json
from pathlib import Path

# ═══════════════════════════════════════════════════════════
# CONSTANTES NORMATIVA COLOMBIANA
# ═══════════════════════════════════════════════════════════

LIMITE_DIAS_EPS = 180           # Límite EPS (Ley 776/2002)
LIMITE_DIAS_PENSION = 540       # Límite máximo con concepto favorable
ALERTA_TEMPRANA_DIAS = 150      # Alertar a los 150 días
ALERTA_CRITICA_DIAS = 170      # Alerta crítica a los 170 días

# Ventana de corte: >30 días sin incapacidad CORTA la cadena de prórroga
VENTANA_CORTE_PRORROGA = 30    # Máximo días de brecha para mantener cadena activa


# ═══════════════════════════════════════════════════════════
# VALIDACIÓN RUPTURA DE PRÓRROGA: OMS + REGLAS LOCALES
# ═══════════════════════════════════════════════════════════

def _validar_ruptura_prorroga(codigo_a: str, codigo_b: str, dias_entre: int) -> dict:
    """
    Valida si dos códigos CIE-10 ROMPEN la prórroga según:
    1. API OMS (primaria) - Exclusiones mutuas, sin relación jerárquica
    2. Reglas locales (complementaria) - exclusiones_cie10.json
    
    Retorna:
        {
            "puede_ser_prorroga": bool,
            "razon_ruptura": str,
            "fuente": "OMS" | "LOCAL" | "AMBAS" | "NINGUNA" (puede ser prórroga),
            "confianza_oms": float | None,
            "asertividad_local": float | None,
            "cita_legal": str | None
        }
    """
    resultado = {
        "puede_ser_prorroga": True,  # Por defecto, permite prórroga
        "razon_ruptura": "",
        "fuente": "NINGUNA",
        "confianza_oms": None,
        "asertividad_local": None,
        "cita_legal": None
    }
    
    if not codigo_a or not codigo_b:
        return resultado  # Sin códigos, sin ruptura detectada
    
    # ═══ 1. VALIDAR CON API OMS (primaria) ═══
    try:
        from app.services.oms_icd_service import validar_correlacion_oms_local_sync
        
        validacion_oms = validar_correlacion_oms_local_sync(codigo_a, codigo_b)
        
        if validacion_oms.get("validado_oms"):
            resultado["confianza_oms"] = validacion_oms.get("confianza_oms", 0)
            nivel_oms = validacion_oms.get("nivel_oms", "")
            
            # ⭐ OMS dice que ROMPE prórroga
            if nivel_oms == "EXCLUIDO_OMS" or validacion_oms.get("confianza_oms", 0) == 0:
                resultado["puede_ser_prorroga"] = False
                resultado["razon_ruptura"] = (
                    f"OMS RECHAZA PRÓRROGA: {validacion_oms.get('razon_oms', '')}. "
                    f"{validacion_oms.get('cita_legal_oms', '')}"
                )
                resultado["fuente"] = "OMS"
                resultado["cita_legal"] = validacion_oms.get("cita_legal_oms", "")
                return resultado
            
            # OMS dice que SÍ correlaciona (98%, 92%, 85%, 75%, etc.)
            # Continuar a validación local como confirmación
    
    except Exception as e:
        pass  # Si OMS falla, continuar con reglas locales
    
    # ═══ 2. VALIDAR CON REGLAS LOCALES (complementaria) ═══
    try:
        data_dir = Path(__file__).parent.parent / "data"
        excl_file = data_dir / "exclusiones_cie10.json"
        
        if excl_file.exists():
            with open(excl_file, "r", encoding="utf-8") as f:
                excl_data = json.load(f)
            
            codigo_a_norm = codigo_a.strip().upper().replace(".", "")
            codigo_b_norm = codigo_b.strip().upper().replace(".", "")
            
            for excl in excl_data.get("exclusiones", []):
                cod_a_local = excl.get("codigo_a", "").strip().upper().replace(".", "")
                cod_b_local = excl.get("codigo_b", "").strip().upper().replace(".", "")
                
                # Encontrar si el par existe (cualquier dirección)
                if (cod_a_local == codigo_a_norm and cod_b_local == codigo_b_norm) or \
                   (cod_a_local == codigo_b_norm and cod_b_local == codigo_a_norm):
                    
                    bloquear = excl.get("bloquear", False)
                    asertividad_reducida = excl.get("asertividad_reducida", 0)
                    
                    resultado["asertividad_local"] = asertividad_reducida
                    
                    # Si bloquear = true, la exclusión ROMPE la prórroga
                    if bloquear:
                        resultado["puede_ser_prorroga"] = False
                        resultado["razon_ruptura"] = (
                            f"REGLA LOCAL BLOQUEA: {excl.get('razon', '')}. "
                            f"Evidencia: {excl.get('evidencia', '')}"
                        )
                        resultado["fuente"] = "LOCAL"
                        resultado["cita_legal"] = f"Resolución MinSalud — {excl.get('evidencia', '')}"
                        return resultado
                    
                    # Si bloquear = false, reduce asertividad pero no rompe
                    # La correlación local decide
    
    except Exception as e:
        pass
    
    return resultado


# ═════════════════════════════════════════════════════════════


def analizar_historial_empleado(db: Session, cedula: str) -> dict:
    """
    Analiza TODAS las incapacidades de un empleado y detecta cadenas de prórrogas.
    
    Retorna:
        {
            "cedula": str,
            "nombre": str,
            "total_incapacidades": int,
            "cadenas_prorroga": [...],      # Grupos de incapacidades relacionadas
            "dias_acumulados_total": int,
            "alertas_180": [...],
            "resumen": {...}
        }
    """
    # Obtener todas las incapacidades del empleado ordenadas por fecha
    casos = db.query(Case).filter(
        Case.cedula == cedula
    ).order_by(Case.fecha_inicio.asc()).all()
    
    if not casos:
        return {
            "cedula": cedula,
            "total_incapacidades": 0,
            "cadenas_prorroga": [],
            "dias_acumulados_total": 0,
            "alertas_180": [],
            "resumen": {"mensaje": "Sin historial de incapacidades"}
        }
    
    # Obtener nombre del empleado
    empleado = db.query(Employee).filter(Employee.cedula == cedula).first()
    nombre = empleado.nombre if empleado else cedula
    
    # Detectar cadenas de prórroga
    cadenas = _detectar_cadenas_prorroga(casos)
    
    # Detectar huecos entre cadenas (prórrogas cortadas por >30d sin incapacidad)
    huecos = _detectar_huecos_entre_cadenas(cadenas, casos)
    
    # Generar alertas (incluye huecos/prórrogas cortadas)
    alertas = _generar_alertas_180(cadenas, cedula, nombre, huecos)
    
    # Calcular totales — restar días traslapados para no contar doble
    dias_total = sum(c.dias_incapacidad or 0 for c in casos) - sum(c.dias_traslapo or 0 for c in casos)
    
    # Días en prórroga = cadena activa más larga (solo cadenas con prórrogas)
    dias_prorroga = max(
        (c["dias_acumulados"] for c in cadenas if c["es_cadena_prorroga"]),
        default=0
    )
    
    return {
        "cedula": cedula,
        "nombre": nombre,
        "total_incapacidades": len(casos),
        "cadenas_prorroga": cadenas,
        "dias_acumulados_total": dias_total,
        "dias_prorroga": dias_prorroga,
        "huecos_detectados": huecos,
        "alertas_180": alertas,
        "resumen": _generar_resumen(cadenas, alertas, dias_total, huecos)
    }


def _detectar_cadenas_prorroga(casos: List[Case]) -> List[dict]:
    """
    Detecta cadenas de prórrogas: secuencias de incapacidades correlacionadas.
    
    Algoritmo v3 con detección de huecos temporales:
    1. Toma cada caso como posible inicio de cadena
    2. Para cada caso posterior, verifica:
       a. Proximidad temporal (brecha ≤ 30 días)
       b. Correlación de códigos CIE-10
    3. Si ambos se cumplen → prórroga directa
    4. Si NO correlacionado pero <30 días → hueco temporal (no rompe cadena)
    5. Si la brecha > 30 días PERO hay huecos <30d que la explican → cadena continúa
    """
    if not casos:
        return []
    
    # Marcar qué casos ya están en una cadena
    asignados = set()
    cadenas = []
    
    for i, caso_inicial in enumerate(casos):
        if i in asignados:
            continue
        
        cadena = {
            "id_cadena": len(cadenas) + 1,
            "caso_inicial": _caso_a_dict(caso_inicial),
            "prorrogas": [],
            "codigos_cie10": set(),
            "dias_acumulados": caso_inicial.dias_incapacidad or 0,
            "fecha_inicio_cadena": caso_inicial.fecha_inicio,
            "fecha_fin_cadena": caso_inicial.fecha_fin or caso_inicial.fecha_inicio,
            "huecos_ignorados": [],  # v3: huecos temporales <30d
        }
        
        # Agregar código del caso inicial
        if caso_inicial.codigo_cie10:
            cadena["codigos_cie10"].add(_normalizar_codigo(caso_inicial.codigo_cie10))
        if caso_inicial.diagnostico:
            cadena["diagnostico_base"] = caso_inicial.diagnostico
        
        asignados.add(i)
        ultimo_caso = caso_inicial
        huecos_pendientes = []  # v3: track potential temporal gaps
        
        # Buscar prórrogas
        for j in range(i + 1, len(casos)):
            if j in asignados:
                continue
            
            caso_siguiente = casos[j]
            resultado = _es_prorroga_de(ultimo_caso, caso_siguiente)
            
            if resultado["es_prorroga"]:
                # ─── v3: Finalizar huecos pendientes como ignorados ───
                for hp in huecos_pendientes:
                    cadena["huecos_ignorados"].append(hp["info"])
                    asignados.add(hp["index"])
                huecos_pendientes = []
                
                # Días de traslapo a descontar (si hay solapamiento)
                dias_traslapo_desc = resultado.get("dias_traslapo", 0)
                # También verificar el campo dias_traslapo del caso en BD
                if not dias_traslapo_desc and caso_siguiente.dias_traslapo:
                    dias_traslapo_desc = caso_siguiente.dias_traslapo
                
                cadena["prorrogas"].append({
                    **_caso_a_dict(caso_siguiente),
                    "tipo_deteccion": resultado["tipo"],
                    "confianza": resultado["confianza"],
                    "asertividad": resultado.get("asertividad", 0.0),
                    "brecha_dias": resultado["brecha_dias"],
                    "dias_traslapo": dias_traslapo_desc,
                    "explicacion": resultado["explicacion"],
                    "requiere_validacion_medica": resultado.get("requiere_validacion_medica", False),
                })
                # Sumar días REALES: días de la incapacidad MENOS los días traslapados
                dias_efectivos = (caso_siguiente.dias_incapacidad or 0) - dias_traslapo_desc
                cadena["dias_acumulados"] += max(dias_efectivos, 0)
                cadena["fecha_fin_cadena"] = caso_siguiente.fecha_fin or caso_siguiente.fecha_inicio
                
                if caso_siguiente.codigo_cie10:
                    cadena["codigos_cie10"].add(_normalizar_codigo(caso_siguiente.codigo_cie10))
                
                asignados.add(j)
                ultimo_caso = caso_siguiente
            else:
                # ─── v3: DETECTOR DE HUECOS TEMPORALES ───
                brecha = resultado.get("brecha_dias")
                dias_caso_sig = caso_siguiente.dias_incapacidad or 0
                codigo_sig = _normalizar_codigo(caso_siguiente.codigo_cie10 or "")
                codigo_ult = _normalizar_codigo(ultimo_caso.codigo_cie10 or "")
                
                # CASO A: Brecha > 30 días PERO hay huecos pendientes que pueden explicar el gap
                if (brecha is not None and brecha > VENTANA_CORTE_PRORROGA
                        and huecos_pendientes and codigo_ult and codigo_sig):
                    
                    # Calcular brecha efectiva descontando días cubiertos por huecos
                    dias_cubiertos_huecos = sum(
                        hp["caso"].dias_incapacidad or 0 for hp in huecos_pendientes
                    )
                    brecha_efectiva = brecha - dias_cubiertos_huecos
                    
                    if brecha_efectiva <= VENTANA_CORTE_PRORROGA:
                        # Re-evaluar correlación (porque _es_prorroga_de cortó por brecha > 30)
                        corr = son_correlacionados(
                            codigo_ult, codigo_sig,
                            dias_entre=max(0, int(brecha_efectiva)),
                            codigo_anterior=codigo_ult
                        )
                        
                        if corr["correlacionados"]:
                            # ✅ Huecos explican el gap → cadena continúa
                            for hp in huecos_pendientes:
                                hp["info"]["razon"] = (
                                    f"Hueco temporal <30d ({hp['caso'].dias_incapacidad}d con "
                                    f"{hp['caso'].codigo_cie10 or 'sin código'}). "
                                    f"No rompe cadena de {codigo_ult}."
                                )
                                cadena["huecos_ignorados"].append(hp["info"])
                                asignados.add(hp["index"])
                            huecos_pendientes = []
                            
                            # Agregar a la cadena como prórroga con hueco
                            dias_traslapo_desc = caso_siguiente.dias_traslapo or 0
                            cadena["prorrogas"].append({
                                **_caso_a_dict(caso_siguiente),
                                "tipo_deteccion": "prorroga_con_hueco_temporal",
                                "confianza": corr.get("confianza", "MEDIA"),
                                "asertividad": corr.get("asertividad", 0.0),
                                "brecha_dias": brecha,
                                "brecha_efectiva": int(brecha_efectiva),
                                "dias_traslapo": dias_traslapo_desc,
                                "explicacion": (
                                    f"Prórroga con hueco temporal: {codigo_ult}→{codigo_sig}. "
                                    f"Brecha real {brecha}d pero efectiva {int(brecha_efectiva)}d "
                                    f"(descontados {dias_cubiertos_huecos}d de diagnósticos no relacionados <30d)."
                                ),
                                "requiere_validacion_medica": corr.get("requiere_validacion_medica", False),
                            })
                            dias_efectivos = (caso_siguiente.dias_incapacidad or 0) - dias_traslapo_desc
                            cadena["dias_acumulados"] += max(dias_efectivos, 0)
                            cadena["fecha_fin_cadena"] = caso_siguiente.fecha_fin or caso_siguiente.fecha_inicio
                            
                            if codigo_sig:
                                cadena["codigos_cie10"].add(codigo_sig)
                            
                            asignados.add(j)
                            ultimo_caso = caso_siguiente
                            continue
                    
                    # Extensión no funcionó — verificar si este caso es un nuevo hueco
                    if codigo_ult and codigo_sig:
                        # Verificar si este caso NO es correlacionado y es <30d → nuevo hueco
                        corr_check = son_correlacionados(codigo_ult, codigo_sig)
                        if not corr_check["correlacionados"] and dias_caso_sig < 30:
                            huecos_pendientes.append({
                                "index": j,
                                "caso": caso_siguiente,
                                "info": {
                                    "serial": caso_siguiente.serial,
                                    "codigo_cie10": caso_siguiente.codigo_cie10,
                                    "diagnostico": caso_siguiente.diagnostico,
                                    "dias": dias_caso_sig,
                                    "fecha_inicio": caso_siguiente.fecha_inicio.isoformat() if caso_siguiente.fecha_inicio else None,
                                    "fecha_fin": caso_siguiente.fecha_fin.isoformat() if caso_siguiente.fecha_fin else None,
                                    "razon": f"Posible hueco temporal <30d entre diagnósticos correlacionados"
                                }
                            })
                        else:
                            huecos_pendientes = []
                    else:
                        huecos_pendientes = []
                
                # CASO B: Brecha ≤ 30 pero no correlacionado → posible hueco temporal
                elif (brecha is not None and 0 <= brecha <= VENTANA_CORTE_PRORROGA
                      and dias_caso_sig < 30):
                    huecos_pendientes.append({
                        "index": j,
                        "caso": caso_siguiente,
                        "info": {
                            "serial": caso_siguiente.serial,
                            "codigo_cie10": caso_siguiente.codigo_cie10,
                            "diagnostico": caso_siguiente.diagnostico,
                            "dias": dias_caso_sig,
                            "fecha_inicio": caso_siguiente.fecha_inicio.isoformat() if caso_siguiente.fecha_inicio else None,
                            "fecha_fin": caso_siguiente.fecha_fin.isoformat() if caso_siguiente.fecha_fin else None,
                            "razon": f"Posible hueco temporal <30d entre diagnósticos correlacionados"
                        }
                    })
                
                # CASO C: ≥30 días no correlacionado o brecha indefinida → reset
                else:
                    huecos_pendientes = []
        
        # Al final del inner loop, descartar huecos pendientes no finalizados
        huecos_pendientes = []
        
        # Convertir set a lista para serialización
        cadena["codigos_cie10"] = sorted(cadena["codigos_cie10"])
        cadena["total_incapacidades_cadena"] = 1 + len(cadena["prorrogas"])
        cadena["es_cadena_prorroga"] = len(cadena["prorrogas"]) > 0
        cadena["total_huecos_ignorados"] = len(cadena["huecos_ignorados"])
        
        # Serializar fechas
        cadena["fecha_inicio_cadena"] = cadena["fecha_inicio_cadena"].isoformat() if cadena["fecha_inicio_cadena"] else None
        cadena["fecha_fin_cadena"] = cadena["fecha_fin_cadena"].isoformat() if cadena["fecha_fin_cadena"] else None
        
        cadenas.append(cadena)
    
    return cadenas


def _es_prorroga_de(caso_anterior: Case, caso_nuevo: Case) -> dict:
    """
    Determina si caso_nuevo es prórroga de caso_anterior.
    
    Criterios (deben cumplirse AMBOS):
    1. TEMPORAL: caso_nuevo.fecha_inicio está dentro de la ventana temporal
       después de caso_anterior.fecha_fin
    2. DIAGNÓSTICO: Los códigos CIE-10 están correlacionados (asertividad ≥ 40%)
    
    Retorna asertividad numérica (%) del motor CIE-10 v2.
    Umbral de prórroga: ≥ 60% = prórroga, ≥ 40% = posible prórroga
    """
    resultado_base = {
        "es_prorroga": False,
        "tipo": "ninguno",
        "confianza": "NINGUNA",
        "asertividad": 0.0,
        "brecha_dias": None,
        "explicacion": ""
    }
    
    # Verificar fechas
    fecha_fin_anterior = caso_anterior.fecha_fin or caso_anterior.fecha_inicio
    fecha_inicio_nuevo = caso_nuevo.fecha_inicio
    
    if not fecha_fin_anterior or not fecha_inicio_nuevo:
        resultado_base["explicacion"] = "Fechas incompletas para determinar prórroga"
        return resultado_base
    
    # Calcular brecha entre fin anterior e inicio nuevo
    brecha = (fecha_inicio_nuevo.date() - fecha_fin_anterior.date()).days
    resultado_base["brecha_dias"] = brecha
    
    # Si la brecha es negativa = TRASLAPO (superposición de fechas)
    # Traslapos SÍ son parte de la cadena, solo se descuentan los días superpuestos
    if brecha < 0:
        dias_traslapo_calc = abs(brecha)
        return {
            "es_prorroga": True,
            "tipo": "traslapo",
            "confianza": "MUY_ALTA",
            "asertividad": 98.0,
            "brecha_dias": brecha,
            "dias_traslapo": dias_traslapo_calc,
            "explicacion": f"Incapacidades traslapadas ({dias_traslapo_calc} días de solapamiento). Los días traslapados se cuentan UNA sola vez."
        }
    
    if brecha > VENTANA_CORTE_PRORROGA:
        resultado_base["explicacion"] = f"Brecha de {brecha} días — CADENA CORTADA (regla >30d sin incapacidad)"
        return resultado_base
    
    # Verificar correlación de diagnósticos con motor v2 (asertividad numérica)
    codigo_anterior = caso_anterior.codigo_cie10 or ""
    codigo_nuevo = caso_nuevo.codigo_cie10 or ""
    
    # ⭐ v4: CAMBIO CRÍTICO — Sin CIE-10, NO es prórroga
    # Las prorrogas REQUIEREN correlación diagnóstica (código_cie10 relacionado)
    # No se permiten "prorrogas por solo temporalidad" sin validación clínica
    if not codigo_anterior and not codigo_nuevo:
        # Sin códigos CIE-10 = no hay correlación diagnóstica = no es prórroga
        resultado_base["explicacion"] = (
            f"SIN CORRELACIÓN DIAGNÓSTICA: Ambas incapacidades sin código CIE-10. "
            f"No se puede determinar prórroga sin diagnósticos. Brecha: {brecha}d. "
            f"⚠️ Esperar confirmación de Kactus con códigos CIE-10."
        )
        return resultado_base
    
    # Correlación CIE-10 con motor v2
    if codigo_anterior and codigo_nuevo:
        # ⭐ PRIMERO: Validar si OMS + reglas locales ROMPEN la prórroga
        validacion_ruptura = _validar_ruptura_prorroga(codigo_anterior, codigo_nuevo, brecha)
        
        if not validacion_ruptura["puede_ser_prorroga"]:
            # OMS o reglas locales detecten incompatibilidad
            resultado_base["explicacion"] = validacion_ruptura["razon_ruptura"]
            resultado_base["validacion_oms"] = {
                "rechazada_por": validacion_ruptura["fuente"],
                "confianza_oms": validacion_ruptura["confianza_oms"],
                "cita_legal": validacion_ruptura["cita_legal"]
            }
            return resultado_base
        
        # SEGUNDO: Si OMS+LOCAL no rechazan, evaluar con motor local
        # Llamar al motor v2 con días_entre y dirección
        correlacion = son_correlacionados(
            codigo_anterior,
            codigo_nuevo,
            dias_entre=brecha,
            codigo_anterior=codigo_anterior
        )
        
        asertividad = correlacion.get("asertividad", 0.0)
        confianza = correlacion.get("confianza", "NINGUNA")
        
        if correlacion["correlacionados"]:
            # Determinar tipo según asertividad
            if asertividad >= 60:
                tipo = "correlacion_cie10"
            else:
                tipo = "correlacion_cie10_baja"
            
            resultado_response = {
                "es_prorroga": True,
                "tipo": tipo,
                "confianza": confianza,
                "asertividad": asertividad,
                "brecha_dias": brecha,
                "grupos_correlacion": correlacion.get("grupos_comunes", []),
                "explicacion": correlacion["explicacion"],
                "detalles_calculo": correlacion.get("detalles_calculo", {}),
                "requiere_validacion_medica": correlacion.get("requiere_validacion_medica", False),
                "evidencia": correlacion.get("evidencia", ""),
                "validacion_oms": {
                    "permitida_por": validacion_ruptura["fuente"],
                    "confianza_oms": validacion_ruptura["confianza_oms"]
                }
            }
            return resultado_response
        else:
            # v3: No correlacionados → NO es prórroga (independiente de la brecha)
            # El detector de huecos temporales en _detectar_cadenas_prorroga
            # se encarga de no romper la cadena si este caso dura <30 días
            resultado_base["explicacion"] = (
                f"Códigos {codigo_anterior}→{codigo_nuevo} NO correlacionados "
                f"(asertividad {asertividad}%). Brecha {brecha}d. "
                f"No se considera prórroga."
            )
    elif codigo_anterior or codigo_nuevo:
        # ⭐ v4: Solo uno tiene código = NO es prórroga, es INCOMPLETO
        # Requiere que AMBOS tengan código CIE-10 para detectar prórroga
        resultado_base["explicacion"] = (
            f"SIN CORRELACIÓN COMPLETA: Solo {'primera' if codigo_anterior else 'segunda'} incapacidad tiene código CIE-10. "
            f"Necesita que ambas tengan diagnóstico para detectar prórroga. Brecha: {brecha}d. "
            f"⚠️ Marcar segunda como INCOMPLETA si falta el código."
        )
    
    return resultado_base


def _combinar_confianzas(temporal: str, diagnostica: str) -> str:
    """Combina la confianza temporal y diagnóstica — compatibilidad v1"""
    niveles = {"MUY_ALTA": 4, "ALTA": 3, "MEDIA": 2, "BAJA": 1, "NINGUNA": 0,
               "alta": 3, "media": 2, "baja": 1, "ninguna": 0}
    promedio = (niveles.get(temporal, 0) + niveles.get(diagnostica, 0)) / 2
    if promedio >= 3.0:
        return "MUY_ALTA"
    elif promedio >= 2.0:
        return "ALTA"
    elif promedio >= 1.0:
        return "MEDIA"
    elif promedio >= 0.5:
        return "BAJA"
    return "NINGUNA"


def _detectar_huecos_entre_cadenas(cadenas: List[dict], casos: List[Case]) -> List[dict]:
    """
    Detecta huecos entre cadenas de prórroga con diagnósticos correlacionados.
    
    Un hueco ocurre cuando:
    - Dos cadenas tienen diagnósticos correlacionados (CIE-10)
    - Pero la brecha entre ellas es > 30 días
    - Esto indica que la prórroga se cortó y TH debe investigar
    
    LLENADO RETROACTIVO: Si un empleado envía después un certificado
    que cubre el hueco, al re-analizar las cadenas se reconectan
    automáticamente (el hueco desaparece).
    """
    if len(cadenas) < 2:
        return []
    
    huecos = []
    
    # Ordenar cadenas por fecha de inicio
    cadenas_ordenadas = sorted(
        [c for c in cadenas if c.get("fecha_inicio_cadena")],
        key=lambda c: c["fecha_inicio_cadena"]
    )
    
    for i in range(len(cadenas_ordenadas) - 1):
        cadena_a = cadenas_ordenadas[i]
        cadena_b = cadenas_ordenadas[i + 1]
        
        # Parsear fechas
        try:
            fin_a_str = cadena_a.get("fecha_fin_cadena")
            inicio_b_str = cadena_b.get("fecha_inicio_cadena")
            if not fin_a_str or not inicio_b_str:
                continue
            fin_a = datetime.fromisoformat(fin_a_str).date() if isinstance(fin_a_str, str) else fin_a_str
            inicio_b = datetime.fromisoformat(inicio_b_str).date() if isinstance(inicio_b_str, str) else inicio_b_str
        except (ValueError, TypeError):
            continue
        
        brecha = (inicio_b - fin_a).days
        
        # Solo nos interesa si la brecha es > 30 días
        if brecha <= VENTANA_CORTE_PRORROGA:
            continue
        
        # Verificar si los diagnósticos están correlacionados
        codigos_a = set(cadena_a.get("codigos_cie10", []))
        codigos_b = set(cadena_b.get("codigos_cie10", []))
        
        hay_correlacion = False
        explicacion_correlacion = ""
        
        # Mismo código = correlación directa
        if codigos_a & codigos_b:
            hay_correlacion = True
            codigos_comunes = codigos_a & codigos_b
            explicacion_correlacion = f"Mismo código CIE-10: {', '.join(codigos_comunes)}"
        else:
            # Verificar correlación cruzada
            for cod_a in codigos_a:
                for cod_b in codigos_b:
                    if cod_a and cod_b:
                        resultado = son_correlacionados(cod_a, cod_b)
                        if resultado["correlacionados"]:
                            hay_correlacion = True
                            explicacion_correlacion = resultado["explicacion"]
                            break
                if hay_correlacion:
                    break
        
        if hay_correlacion:
            # Calcular días acumulados si se juntaran ambas cadenas
            dias_potenciales = cadena_a["dias_acumulados"] + cadena_b["dias_acumulados"]
            
            huecos.append({
                "cadena_antes_id": cadena_a["id_cadena"],
                "cadena_despues_id": cadena_b["id_cadena"],
                "fecha_fin_cadena_antes": str(fin_a),
                "fecha_inicio_cadena_despues": str(inicio_b),
                "dias_hueco": brecha,
                "codigos_antes": sorted(codigos_a),
                "codigos_despues": sorted(codigos_b),
                "correlacion": explicacion_correlacion,
                "dias_cadena_antes": cadena_a["dias_acumulados"],
                "dias_cadena_despues": cadena_b["dias_acumulados"],
                "dias_potenciales_sin_corte": dias_potenciales,
                "mensaje": (
                    f"⚠️ Prórroga CORTADA: {brecha} días sin incapacidad entre cadenas "
                    f"correlacionadas ({', '.join(codigos_a)} → {', '.join(codigos_b)}). "
                    f"Si se juntaran serían {dias_potenciales}d. Verificar por qué se interrumpió."
                ),
            })
    
    return huecos


def _generar_alertas_180(cadenas: List[dict], cedula: str, nombre: str, huecos: List[dict] = None) -> List[dict]:
    """Genera alertas cuando las cadenas se acercan a 180 días o se detectan huecos"""
    alertas = []
    
    for cadena in cadenas:
        if not cadena["es_cadena_prorroga"]:
            continue
        
        dias = cadena["dias_acumulados"]
        
        if dias >= LIMITE_DIAS_EPS:
            alertas.append({
                "tipo": "LIMITE_180_SUPERADO",
                "severidad": "critica",
                "cadena_id": cadena["id_cadena"],
                "dias_acumulados": dias,
                "dias_excedidos": dias - LIMITE_DIAS_EPS,
                "mensaje": f"⛔ {nombre} ({cedula}): {dias} días acumulados. SUPERÓ el límite de {LIMITE_DIAS_EPS} días de la EPS. Debe pasar a Fondo de Pensiones.",
                "normativa": "Ley 776/2002 Art. 3 — Después de 180 días, el Fondo de Pensiones asume al 50%",
                "codigos_involucrados": cadena["codigos_cie10"],
            })
        elif dias >= ALERTA_CRITICA_DIAS:
            alertas.append({
                "tipo": "ALERTA_CRITICA",
                "severidad": "alta",
                "cadena_id": cadena["id_cadena"],
                "dias_acumulados": dias,
                "dias_restantes": LIMITE_DIAS_EPS - dias,
                "mensaje": f"🔴 {nombre} ({cedula}): {dias} días acumulados. Quedan {LIMITE_DIAS_EPS - dias} días para el límite de 180. Preparar trámite ante Fondo de Pensiones.",
                "codigos_involucrados": cadena["codigos_cie10"],
            })
        elif dias >= ALERTA_TEMPRANA_DIAS:
            alertas.append({
                "tipo": "ALERTA_TEMPRANA",
                "severidad": "media",
                "cadena_id": cadena["id_cadena"],
                "dias_acumulados": dias,
                "dias_restantes": LIMITE_DIAS_EPS - dias,
                "mensaje": f"🟡 {nombre} ({cedula}): {dias} días acumulados. Se acerca al límite de 180 días ({LIMITE_DIAS_EPS - dias} restantes).",
                "codigos_involucrados": cadena["codigos_cie10"],
            })
    
    # ⭐ Alertas de prórroga cortada por huecos (>30 días sin incapacidad)
    if huecos:
        for hueco in huecos:
            alertas.append({
                "tipo": "PRORROGA_CORTADA",
                "severidad": "alta",
                "dias_acumulados": hueco["dias_potenciales_sin_corte"],
                "dias_hueco": hueco["dias_hueco"],
                "fecha_corte": hueco["fecha_fin_cadena_antes"],
                "mensaje": (
                    f"⚠️ {nombre} ({cedula}): Prórroga CORTADA — {hueco['dias_hueco']} días sin incapacidad. "
                    f"Cadena anterior: {hueco['dias_cadena_antes']}d, cadena nueva: {hueco['dias_cadena_despues']}d. "
                    f"Si se juntaran serían {hueco['dias_potenciales_sin_corte']}d. "
                    f"TH debe verificar por qué se interrumpió la cadena."
                ),
                "normativa": "Prórroga se interrumpe tras 30+ días sin incapacidad — Verificar si el empleado tiene certificados pendientes por radicar",
                "codigos_involucrados": hueco["codigos_antes"] + hueco["codigos_despues"],
            })
    
    return alertas


def _generar_resumen(cadenas: List[dict], alertas: List[dict], dias_total: int, huecos: List[dict] = None) -> dict:
    """Genera resumen del análisis incluyendo huecos detectados"""
    cadenas_con_prorroga = [c for c in cadenas if c["es_cadena_prorroga"]]
    max_cadena = max((c["dias_acumulados"] for c in cadenas), default=0)
    huecos = huecos or []
    
    return {
        "total_cadenas": len(cadenas),
        "cadenas_con_prorroga": len(cadenas_con_prorroga),
        "incapacidades_aisladas": len([c for c in cadenas if not c["es_cadena_prorroga"]]),
        "dias_totales": dias_total,
        "dias_prorroga": max_cadena,
        "cadena_mas_larga_dias": max_cadena,
        "tiene_alertas": len(alertas) > 0,
        "alertas_criticas": len([a for a in alertas if a["severidad"] == "critica"]),
        "alertas_altas": len([a for a in alertas if a["severidad"] == "alta"]),
        "alertas_medias": len([a for a in alertas if a["severidad"] == "media"]),
        "cerca_limite_180": max_cadena >= ALERTA_TEMPRANA_DIAS,
        "supero_180": max_cadena >= LIMITE_DIAS_EPS,
        # Huecos (prórrogas cortadas)
        "total_huecos": len(huecos),
        "tiene_huecos": len(huecos) > 0,
        "huecos_info": [
            {
                "dias_hueco": h["dias_hueco"],
                "dias_potenciales": h["dias_potenciales_sin_corte"],
                "fecha_corte": h["fecha_fin_cadena_antes"],
                "fecha_desde": h["fecha_fin_cadena_antes"],
                "fecha_hasta": h["fecha_inicio_cadena_despues"],
            }
            for h in huecos
        ],
    }


# ═══════════════════════════════════════════════════════════
# AUTO-DETECCIÓN PARA DASHBOARD
# ═══════════════════════════════════════════════════════════

def auto_detectar_prorroga_caso(db: Session, caso: Case) -> dict:
    """
    Para un caso dado, determina si es prórroga de alguno anterior.
    Se usa en el dashboard para auto-rellenar es_prorroga.
    """
    if not caso.cedula or not caso.fecha_inicio:
        return {"es_prorroga": False, "explicacion": "Datos insuficientes"}
    
    # Buscar incapacidades previas del mismo empleado
    anteriores = db.query(Case).filter(
        Case.cedula == caso.cedula,
        Case.id != caso.id,
        Case.fecha_inicio < caso.fecha_inicio,
    ).order_by(Case.fecha_inicio.desc()).limit(10).all()
    
    for anterior in anteriores:
        resultado = _es_prorroga_de(anterior, caso)
        if resultado["es_prorroga"]:
            return {
                "es_prorroga": True,
                "caso_original_serial": anterior.serial,
                "caso_original_diagnostico": anterior.diagnostico,
                "caso_original_cie10": anterior.codigo_cie10,
                **resultado,
            }
    
    return {"es_prorroga": False, "explicacion": "No se encontró incapacidad previa correlacionada"}


def analisis_masivo_prorrogas(db: Session, empresa: str = "all") -> dict:
    """
    Analiza TODAS las cédulas con incapacidades y detecta prórrogas.
    Usado para el dashboard general.
    """
    # Obtener todas las cédulas únicas con incapacidades
    query = db.query(Case.cedula).distinct()
    
    if empresa != "all":
        from app.database import Company
        query = query.join(Company, Case.company_id == Company.id).filter(Company.nombre == empresa)
    
    cedulas = [row[0] for row in query.all() if row[0]]
    
    resultados = []
    alertas_globales = []
    
    for cedula in cedulas:
        analisis = analizar_historial_empleado(db, cedula)
        
        if analisis["total_incapacidades"] >= 2:
            resultados.append({
                "cedula": cedula,
                "nombre": analisis.get("nombre", cedula),
                "total_incapacidades": analisis["total_incapacidades"],
                "dias_acumulados": analisis["dias_acumulados_total"],
                "dias_prorroga": analisis.get("dias_prorroga", 0),
                "cadenas_prorroga": len([c for c in analisis["cadenas_prorroga"] if c["es_cadena_prorroga"]]),
                "max_cadena_dias": max((c["dias_acumulados"] for c in analisis["cadenas_prorroga"]), default=0),
                "tiene_alertas": len(analisis["alertas_180"]) > 0,
                "huecos_detectados": len(analisis.get("huecos_detectados", [])),
                "tiene_huecos": len(analisis.get("huecos_detectados", [])) > 0,
                "resumen": analisis["resumen"],
            })
        
        alertas_globales.extend(analisis["alertas_180"])
    
    # Ordenar por cadena más larga
    resultados.sort(key=lambda x: x["max_cadena_dias"], reverse=True)
    alertas_globales.sort(key=lambda x: {"critica": 0, "alta": 1, "media": 2}.get(x["severidad"], 3))
    
    return {
        "total_empleados_analizados": len(cedulas),
        "empleados_con_historial": len(resultados),
        "total_alertas": len(alertas_globales),
        "alertas_criticas": len([a for a in alertas_globales if a["severidad"] == "critica"]),
        "alertas": alertas_globales[:50],  # Top 50 alertas
        "empleados": resultados[:100],      # Top 100 empleados
    }


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════

def _caso_a_dict(caso: Case) -> dict:
    """Convierte un Case de SQLAlchemy a diccionario"""
    return {
        "id": caso.id,
        "serial": caso.serial,
        "cedula": caso.cedula,
        "diagnostico": caso.diagnostico,
        "codigo_cie10": caso.codigo_cie10,
        "dias_incapacidad": caso.dias_incapacidad,
        "fecha_inicio": caso.fecha_inicio.isoformat() if caso.fecha_inicio else None,
        "fecha_fin": caso.fecha_fin.isoformat() if caso.fecha_fin else None,
        "estado": caso.estado.value if caso.estado else None,
        "tipo": caso.tipo.value if caso.tipo else None,
        "es_prorroga_db": caso.es_prorroga,
        "numero_incapacidad": caso.numero_incapacidad,
    }
