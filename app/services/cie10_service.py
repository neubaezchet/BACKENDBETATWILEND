"""
SERVICIO CIE-10 v3 — Motor de correlación jerárquica con asertividad explícita
================================================================================
Sistema de correlación de diagnósticos CIE-10 con porcentaje de asertividad
calculado a partir de múltiples factores y jerarquía de 6 niveles:

  JERARQUÍA DE CORRELACIÓN (de mayor a menor asertividad):
    Nivel 1 — Mismo código:           100%
    Nivel 2 — Mismo bloque CIE-10:     90%  (ej: J00-J06 = vías resp. superiores)
    Nivel 3 — Grupo de correlación:    var%  (definido en correlaciones_cie10.json)
    Nivel 4 — Mismo sistema anatómico:  70%  (ej: RESPIRATORIO↔RESPIRATORIO)
    Nivel 5 — Inter-sistema vinculado:  65-80% (ej: ENDOCRINO→VISUAL por diabetes)
    Nivel 6 — Mismo capítulo CIE-10:   55%  (misma letra pero sin vínculo clínico)
    Sin correlación:                     0%

  MODIFICADORES (aplicados sobre la asertividad base):
    A. Exclusiones: pares que NO deben correlacionarse
    B. Correlaciones direccionales: A→B vs B→A
    C. Umbrales temporales: degradación por días transcurridos
    D. Historial de validaciones: aprendizaje continuo

  CAMPOS DERIVADOS POR CÓDIGO:
    - sistema_anatomico: derivado de la letra del código
    - gravedad_estimada: derivada de dias_tipicos (LEVE/MODERADA/GRAVE/MUY_GRAVE)
    - causa_externa: true para códigos S,T,V,W,X,Y
    - permite_prorroga: true excepto códigos Z (factores de salud)

Normativa colombiana 2026:
  - Ley 776/2002 Art. 3
  - Decreto 1427/2022
  - CIE-10 OMS/OPS vigente — Resolución 1895/2001 MinSalud
  - GPC MinSalud Colombia
  - GATISO Resolución 2844/2007

Para actualizar: edite los archivos JSON en app/data/
"""

import json
import os
import re
from typing import Optional, List, Dict, Tuple
from pathlib import Path
from functools import lru_cache

# ═══════════════════════════════════════════════════════════
# CARGA DE DATOS (singleton, se carga una vez)
# ═══════════════════════════════════════════════════════════

_DATA_DIR = Path(__file__).parent.parent / "data"
_cie10_data: Optional[dict] = None
_correlaciones_data: Optional[dict] = None
_exclusiones_data: Optional[dict] = None
_direccionales_data: Optional[dict] = None
_umbrales_data: Optional[dict] = None
_validaciones_data: Optional[dict] = None
_dias_tipicos_data: Optional[dict] = None
_codigo_a_grupos: Optional[dict] = None  # índice invertido: código → lista de grupos


def _cargar_cie10() -> dict:
    global _cie10_data
    if _cie10_data is None:
        ruta = _DATA_DIR / "cie10_2026.json"
        with open(ruta, "r", encoding="utf-8") as f:
            _cie10_data = json.load(f)
        print(f"✅ CIE-10 cargado: {len(_cie10_data.get('codigos', {}))} códigos ({_cie10_data.get('version', '?')})")
    return _cie10_data


def _cargar_correlaciones() -> dict:
    global _correlaciones_data
    if _correlaciones_data is None:
        ruta = _DATA_DIR / "correlaciones_cie10.json"
        with open(ruta, "r", encoding="utf-8") as f:
            _correlaciones_data = json.load(f)
        print(f"✅ Correlaciones CIE-10 cargadas: {len(_correlaciones_data.get('grupos_correlacion', {}))} grupos")
    return _correlaciones_data


def _cargar_exclusiones() -> dict:
    global _exclusiones_data
    if _exclusiones_data is None:
        ruta = _DATA_DIR / "exclusiones_cie10.json"
        if ruta.exists():
            with open(ruta, "r", encoding="utf-8") as f:
                _exclusiones_data = json.load(f)
            print(f"✅ Exclusiones CIE-10 cargadas: {len(_exclusiones_data.get('exclusiones', []))} reglas")
        else:
            _exclusiones_data = {"exclusiones": []}
    return _exclusiones_data


def _cargar_direccionales() -> dict:
    global _direccionales_data
    if _direccionales_data is None:
        ruta = _DATA_DIR / "direccionales_cie10.json"
        if ruta.exists():
            with open(ruta, "r", encoding="utf-8") as f:
                _direccionales_data = json.load(f)
            print(f"✅ Direccionales CIE-10 cargadas: {len(_direccionales_data.get('direccionales', []))} reglas")
        else:
            _direccionales_data = {"direccionales": []}
    return _direccionales_data


def _cargar_umbrales() -> dict:
    global _umbrales_data
    if _umbrales_data is None:
        ruta = _DATA_DIR / "umbrales_temporales_cie10.json"
        if ruta.exists():
            with open(ruta, "r", encoding="utf-8") as f:
                _umbrales_data = json.load(f)
            print(f"✅ Umbrales temporales CIE-10 cargados: {len(_umbrales_data.get('umbrales_por_grupo', {}))} grupos")
        else:
            _umbrales_data = {"umbrales_por_grupo": {}, "reglas_aplicacion": {}}
    return _umbrales_data


def _cargar_validaciones() -> dict:
    global _validaciones_data
    if _validaciones_data is None:
        ruta = _DATA_DIR / "validaciones_historicas.json"
        if ruta.exists():
            with open(ruta, "r", encoding="utf-8") as f:
                _validaciones_data = json.load(f)
        else:
            _validaciones_data = {"ajustes_aprendidos": {}, "estadisticas": {"total_validaciones": 0}}
    return _validaciones_data


def _cargar_dias_tipicos() -> dict:
    """Carga las reglas de validación de coherencia clínica por código"""
    global _dias_tipicos_data
    if _dias_tipicos_data is None:
        ruta = _DATA_DIR / "dias_tipicos_cie10.json"
        if ruta.exists():
            with open(ruta, "r", encoding="utf-8") as f:
                _dias_tipicos_data = json.load(f)
            print(f"✅ Validaciones de coherencia clínica cargadas: {len(_dias_tipicos_data.get('validaciones_especificas', {}))} códigos específicos")
        else:
            _dias_tipicos_data = {"reglas_por_defecto": {}, "validaciones_especificas": {}}
    return _dias_tipicos_data


def _construir_indice_invertido() -> dict:
    """Construye un índice: código → [lista de grupos donde aparece]"""
    global _codigo_a_grupos
    if _codigo_a_grupos is None:
        corr = _cargar_correlaciones()
        _codigo_a_grupos = {}
        for grupo_id, grupo_data in corr.get("grupos_correlacion", {}).items():
            for codigo in grupo_data.get("codigos", []):
                cod_norm = _normalizar_codigo(codigo)
                if cod_norm not in _codigo_a_grupos:
                    _codigo_a_grupos[cod_norm] = []
                _codigo_a_grupos[cod_norm].append(grupo_id)
    return _codigo_a_grupos


def recargar_datos():
    """Fuerza recarga de TODOS los JSONs (para actualizaciones en caliente)"""
    global _cie10_data, _correlaciones_data, _codigo_a_grupos
    global _exclusiones_data, _direccionales_data, _umbrales_data, _validaciones_data, _dias_tipicos_data
    _cie10_data = None
    _correlaciones_data = None
    _codigo_a_grupos = None
    _exclusiones_data = None
    _direccionales_data = None
    _umbrales_data = None
    _validaciones_data = None
    _dias_tipicos_data = None
    _cargar_cie10()
    _cargar_correlaciones()
    _construir_indice_invertido()
    _cargar_exclusiones()
    _cargar_direccionales()
    _cargar_umbrales()
    _cargar_validaciones()
    _cargar_dias_tipicos()
    return {"ok": True, "mensaje": "Datos CIE-10 v3 completos recargados (correlaciones, exclusiones, direccionales, umbrales, historial, coherencia días)"}


# ═══════════════════════════════════════════════════════════
# NORMALIZACIÓN DE CÓDIGOS
# ═══════════════════════════════════════════════════════════

def _normalizar_codigo(codigo: str) -> str:
    """
    Normaliza un código CIE-10 para búsqueda:
    - Quita espacios y puntos
    - Mayúsculas
    - Toma solo la parte principal (ej: M54.5 → M54, A09.0 → A09)
    """
    if not codigo:
        return ""
    codigo = codigo.strip().upper().replace(".", "").replace(" ", "")
    # Extraer código base (letra + 2 dígitos)
    match = re.match(r"([A-Z]\d{2})", codigo)
    if match:
        return match.group(1)
    return codigo


# ═══════════════════════════════════════════════════════════
# BÚSQUEDA DE CÓDIGO
# ═══════════════════════════════════════════════════════════

def buscar_codigo(codigo: str) -> Optional[dict]:
    """Busca un código CIE-10 y retorna su información completa con jerarquía"""
    cie10 = _cargar_cie10()
    cod_norm = _normalizar_codigo(codigo)
    info = cie10.get("codigos", {}).get(cod_norm)
    if info:
        capitulo = _identificar_capitulo(cod_norm)
        return {
            "codigo": cod_norm,
            "codigo_original": codigo,
            "descripcion": info.get("desc", ""),
            "bloque": info.get("bloque", ""),
            "grupo": info.get("grupo", ""),
            "dias_tipicos": info.get("dias_tipicos", []),
            "encontrado": True,
            # ─── Campos jerárquicos v3 ───
            "sistema_anatomico": _obtener_sistema_anatomico(cod_norm),
            "gravedad_estimada": _obtener_gravedad_estimada(cod_norm),
            "causa_externa": _es_causa_externa(cod_norm),
            "permite_prorroga": _permite_prorroga(cod_norm),
            "capitulo": capitulo,
        }
    # No encontrado en nuestra base de 259 códigos
    # ─── Fallback a base oficial MinSalud (12,568 códigos) ───
    try:
        from app.services.oms_icd_service import buscar_codigo_oficial
        oficial = buscar_codigo_oficial(cod_norm)
        if oficial and oficial.get("encontrado"):
            capitulo = _identificar_capitulo(cod_norm)
            return {
                "codigo": cod_norm,
                "codigo_original": codigo,
                "descripcion": oficial["titulo"],
                "bloque": "",
                "grupo": "",
                "capitulo": capitulo,
                "dias_tipicos": [],
                "encontrado": True,
                "fuente": "MinSalud_CIE10_Oficial",
                # ─── Campos jerárquicos v3 ───
                "sistema_anatomico": _obtener_sistema_anatomico(cod_norm),
                "gravedad_estimada": "INDETERMINADA",
                "causa_externa": _es_causa_externa(cod_norm),
                "permite_prorroga": _permite_prorroga(cod_norm),
            }
    except ImportError:
        pass

    # No encontrado en ninguna base
    capitulo = _identificar_capitulo(cod_norm)
    return {
        "codigo": cod_norm,
        "codigo_original": codigo,
        "descripcion": f"Código {cod_norm} no está en la base de datos detallada",
        "bloque": "",
        "grupo": "",
        "capitulo": capitulo,
        "dias_tipicos": [],
        "encontrado": False,
        # ─── Campos jerárquicos v3 ───
        "sistema_anatomico": _obtener_sistema_anatomico(cod_norm),
        "gravedad_estimada": "INDETERMINADA",
        "causa_externa": _es_causa_externa(cod_norm),
        "permite_prorroga": _permite_prorroga(cod_norm),
    }


def _identificar_capitulo(codigo: str) -> Optional[dict]:
    """Identifica el capítulo CIE-10 por la letra del código"""
    cie10 = _cargar_cie10()
    for cap_id, cap_data in cie10.get("capitulos", {}).items():
        rango = cap_data.get("rango", "")
        if "-" in rango:
            inicio, fin = rango.split("-")
            if inicio <= codigo <= fin + "Z":
                return {"capitulo": cap_id, "rango": rango, "titulo": cap_data.get("titulo", "")}
    return None


# ═══════════════════════════════════════════════════════════
# JERARQUÍA CIE-10: SISTEMA ANATÓMICO + GRAVEDAD + INDICADORES
# ═══════════════════════════════════════════════════════════

def _obtener_sistema_anatomico(codigo: str) -> str:
    """
    Obtiene el sistema anatómico de un código CIE-10.
    Basado en la clasificación OMS/OPS:
      - Letra del código → sistema principal
      - Refinamiento para capítulo H (VISUAL vs AUDITIVO)
    """
    if not codigo or len(codigo) < 1:
        return "DESCONOCIDO"
    
    cie10 = _cargar_cie10()
    sistemas = cie10.get("sistemas_anatomicos", {})
    
    letra = codigo[0].upper()
    
    # Caso especial: H se divide en VISUAL (H00-H59) y AUDITIVO (H60-H95)
    if letra == "H" and len(codigo) >= 3:
        try:
            num = int(codigo[1:3])
            if num <= 59:
                return "VISUAL"
            else:
                return "AUDITIVO"
        except ValueError:
            pass
    
    mapeo = sistemas.get("mapeo_por_letra", {})
    return mapeo.get(letra, "DESCONOCIDO")


def _obtener_gravedad_estimada(codigo: str) -> str:
    """
    Estima la gravedad de un código CIE-10 a partir de sus días típicos máximos.
    Basado en reglas_gravedad del JSON.
    """
    cie10 = _cargar_cie10()
    info = cie10.get("codigos", {}).get(codigo, {})
    dias_tipicos = info.get("dias_tipicos", [])
    
    if not dias_tipicos or len(dias_tipicos) < 2:
        return "INDETERMINADA"
    
    max_dias = dias_tipicos[1]
    
    reglas = cie10.get("reglas_gravedad", {}).get("rangos", [])
    for regla in reglas:
        if max_dias <= regla.get("max_dias", 9999):
            return regla.get("gravedad", "INDETERMINADA")
    
    return "INDETERMINADA"


def _es_causa_externa(codigo: str) -> bool:
    """Determina si un código CIE-10 es de causa externa (traumático)"""
    if not codigo:
        return False
    cie10 = _cargar_cie10()
    prefijos = cie10.get("indicadores_por_prefijo", {}).get("causa_externa", ["S", "T", "V", "W", "X", "Y"])
    return codigo[0].upper() in prefijos


def _permite_prorroga(codigo: str) -> bool:
    """Determina si un código permite prórroga directa (excluye factores Z)"""
    if not codigo:
        return True
    cie10 = _cargar_cie10()
    no_prorroga = cie10.get("indicadores_por_prefijo", {}).get("no_permite_prorroga_directa", ["Z"])
    return codigo[0].upper() not in no_prorroga


def _buscar_correlacion_inter_sistema(sistema1: str, sistema2: str) -> Optional[dict]:
    """
    Busca si existe una correlación inter-sistema definida.
    Las correlaciones inter-sistema son bidireccionales.
    
    Retorna: {"asertividad": float, "ejemplo": str, "evidencia": str} o None
    """
    cie10 = _cargar_cie10()
    inter = cie10.get("correlaciones_inter_sistema", {})
    
    for par in inter.get("pares", []):
        sa = par.get("sistema_a", "")
        sb = par.get("sistema_b", "")
        if (sistema1 == sa and sistema2 == sb) or (sistema1 == sb and sistema2 == sa):
            return {
                "asertividad": par.get("asertividad", 65),
                "ejemplo": par.get("ejemplo", ""),
                "evidencia": par.get("evidencia", "")
            }
    return None


# ═══════════════════════════════════════════════════════════
# MOTOR DE EXCLUSIONES
# ═══════════════════════════════════════════════════════════

def _buscar_exclusion(cod1: str, cod2: str) -> Optional[dict]:
    """
    Busca si existe una exclusión definida para el par de códigos.
    Las exclusiones son bidireccionales por defecto.
    Retorna la regla de exclusión o None.
    """
    exclusiones = _cargar_exclusiones()
    for excl in exclusiones.get("exclusiones", []):
        a = _normalizar_codigo(excl.get("codigo_a", ""))
        b = _normalizar_codigo(excl.get("codigo_b", ""))
        if (cod1 == a and cod2 == b) or (cod1 == b and cod2 == a):
            return excl
    return None


# ═══════════════════════════════════════════════════════════
# MOTOR DE CORRELACIONES DIRECCIONALES
# ═══════════════════════════════════════════════════════════

def _buscar_direccional(cod_anterior: str, cod_nuevo: str) -> Optional[dict]:
    """
    Busca si existe una regla direccional para el par de códigos.
    cod_anterior = diagnóstico de la incapacidad previa
    cod_nuevo = diagnóstico de la incapacidad nueva
    
    Retorna la regla direccional con la asertividad correspondiente a la dirección,
    o None si no hay regla.
    """
    direccionales = _cargar_direccionales()
    for direc in direccionales.get("direccionales", []):
        origen = _normalizar_codigo(direc.get("codigo_origen", ""))
        destino = _normalizar_codigo(direc.get("codigo_destino", ""))
        
        if cod_anterior == origen and cod_nuevo == destino:
            # Dirección de ida (origen → destino): usar asertividad_ida
            return {
                "encontrado": True,
                "asertividad_direccional": direc.get("asertividad_ida", 80),
                "direccion": "ida",
                "razon": direc.get("razon", ""),
                "evidencia": direc.get("evidencia", "")
            }
        elif cod_anterior == destino and cod_nuevo == origen:
            # Dirección de vuelta (destino → origen): usar asertividad_vuelta
            return {
                "encontrado": True,
                "asertividad_direccional": direc.get("asertividad_vuelta", 40),
                "direccion": "vuelta",
                "razon": direc.get("razon", ""),
                "evidencia": direc.get("evidencia", "")
            }
    return None


# ═══════════════════════════════════════════════════════════
# MOTOR DE UMBRALES TEMPORALES
# ═══════════════════════════════════════════════════════════

def _obtener_factor_temporal(grupo: str, dias_entre: int) -> dict:
    """
    Obtiene el factor de degradación temporal para un grupo y un número de días.
    
    Retorna:
        {
            "factor": float (0.05 - 1.00),
            "nota": str,
            "grupo_umbral": str (grupo usado, puede ser DEFAULT)
        }
    """
    umbrales = _cargar_umbrales()
    umbrales_grupo = umbrales.get("umbrales_por_grupo", {})
    
    # Buscar umbral específico del grupo, o usar DEFAULT
    rangos = None
    grupo_usado = grupo
    if grupo in umbrales_grupo:
        rangos = umbrales_grupo[grupo].get("rangos", [])
    
    if not rangos:
        rangos = umbrales_grupo.get("DEFAULT", {}).get("rangos", [])
        grupo_usado = "DEFAULT"
    
    if not rangos:
        # Sin umbrales configurados, usar factor por defecto basado en 30 días
        if dias_entre <= 7:
            return {"factor": 1.00, "nota": "Sin umbrales — prórroga inmediata", "grupo_umbral": "NONE"}
        elif dias_entre <= 30:
            return {"factor": 0.85, "nota": "Sin umbrales — ventana legal", "grupo_umbral": "NONE"}
        elif dias_entre <= 90:
            return {"factor": 0.45, "nota": "Sin umbrales — fuera de ventana", "grupo_umbral": "NONE"}
        else:
            return {"factor": 0.10, "nota": "Sin umbrales — muy improbable", "grupo_umbral": "NONE"}
    
    # Buscar el rango temporal correspondiente
    for rango in rangos:
        if rango["min_dias"] <= dias_entre <= rango["max_dias"]:
            return {
                "factor": rango["factor"],
                "nota": rango.get("nota", ""),
                "grupo_umbral": grupo_usado
            }
    
    # Fuera de todos los rangos (no debería pasar si el último rango cubre hasta 9999)
    return {"factor": 0.05, "nota": "Fuera de todos los rangos temporales", "grupo_umbral": grupo_usado}


# ═══════════════════════════════════════════════════════════
# MOTOR DE HISTORIAL DE APRENDIZAJE
# ═══════════════════════════════════════════════════════════

def _obtener_ajuste_historico(cod1: str, cod2: str) -> Optional[float]:
    """
    Busca si hay un ajuste aprendido para el par de códigos.
    Retorna la asertividad ajustada o None si no hay historial suficiente.
    """
    validaciones = _cargar_validaciones()
    ajustes = validaciones.get("ajustes_aprendidos", {})
    
    # Buscar en ambas direcciones
    clave1 = f"{cod1}_{cod2}"
    clave2 = f"{cod2}_{cod1}"
    
    ajuste = ajustes.get(clave1) or ajustes.get(clave2)
    
    if ajuste and ajuste.get("total_casos", 0) >= 3:  # Mínimo 3 casos para considerar
        return ajuste.get("asertividad_ajustada")
    
    return None


def registrar_validacion(codigo_a: str, codigo_b: str, grupo: str,
                          asertividad_calculada: float, dias_entre: int,
                          resultado: str, cedula: str = "",
                          razon_rechazo: str = "", validado_por: str = "sistema") -> dict:
    """
    Registra una validación en el historial para aprendizaje continuo.
    resultado: "CONFIRMADO" | "RECHAZADO"
    """
    from datetime import datetime
    
    validaciones = _cargar_validaciones()
    
    cod_a = _normalizar_codigo(codigo_a)
    cod_b = _normalizar_codigo(codigo_b)
    
    # Registrar validación
    nueva = {
        "id": validaciones["estadisticas"].get("total_validaciones", 0) + 1,
        "fecha": datetime.now().isoformat(),
        "codigo_a": cod_a,
        "codigo_b": cod_b,
        "grupo_detectado": grupo,
        "asertividad_calculada": asertividad_calculada,
        "dias_entre": dias_entre,
        "resultado": resultado,
        "razon_rechazo": razon_rechazo,
        "validado_por": validado_por,
        "cedula_empleado": cedula
    }
    validaciones.setdefault("validaciones", []).append(nueva)
    
    # Actualizar estadísticas
    stats = validaciones["estadisticas"]
    stats["total_validaciones"] = stats.get("total_validaciones", 0) + 1
    if resultado == "CONFIRMADO":
        stats["correlaciones_confirmadas"] = stats.get("correlaciones_confirmadas", 0) + 1
    elif resultado == "RECHAZADO":
        stats["correlaciones_rechazadas"] = stats.get("correlaciones_rechazadas", 0) + 1
    stats["ultima_actualizacion"] = datetime.now().isoformat()
    
    # Actualizar ajuste aprendido
    clave = f"{cod_a}_{cod_b}"
    ajustes = validaciones.setdefault("ajustes_aprendidos", {})
    if clave not in ajustes:
        ajustes[clave] = {"total_casos": 0, "confirmados": 0, "rechazados": 0}
    
    aj = ajustes[clave]
    aj["total_casos"] += 1
    if resultado == "CONFIRMADO":
        aj["confirmados"] += 1
    elif resultado == "RECHAZADO":
        aj["rechazados"] += 1
    
    if aj["total_casos"] > 0:
        aj["asertividad_ajustada"] = round((aj["confirmados"] / aj["total_casos"]) * 100, 1)
    aj["ultima_actualizacion"] = datetime.now().isoformat()
    
    # Calcular precisión histórica global
    total = stats.get("total_validaciones", 0)
    confirmados = stats.get("correlaciones_confirmadas", 0)
    if total > 0:
        stats["precision_historica"] = round((confirmados / total) * 100, 1)
    
    # Guardar al archivo
    try:
        ruta = _DATA_DIR / "validaciones_historicas.json"
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(validaciones, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Error guardando validaciones: {e}")
    
    return {"ok": True, "validacion_id": nueva["id"], "ajuste": aj}


# ═══════════════════════════════════════════════════════════
# CORRELACIÓN DE DIAGNÓSTICOS — MOTOR PRINCIPAL v2
# ═══════════════════════════════════════════════════════════

def son_correlacionados(codigo1: str, codigo2: str, dias_entre: Optional[int] = None,
                         codigo_anterior: Optional[str] = None) -> dict:
    """
    Determina si dos códigos CIE-10 están correlacionados con asertividad explícita.
    
    Parámetros:
        codigo1: Primer código CIE-10
        codigo2: Segundo código CIE-10
        dias_entre: Días entre fin de incapacidad 1 e inicio de incapacidad 2 (opcional)
        codigo_anterior: Indica cuál es el código ANTERIOR temporalmente (para direccional)
                         Si es None, se asume codigo1 es el anterior.
    
    Retorna:
        {
            "correlacionados": bool,
            "asertividad": float (0-100),           # NUEVO: % explícito
            "confianza": "MUY_ALTA"|"ALTA"|"MEDIA"|"BAJA"|"NINGUNA",
            "grupos_comunes": [...],
            "explicacion": str,
            "detalles_calculo": {                    # NUEVO: transparencia del cálculo
                "asertividad_base_grupo": float,
                "ajuste_exclusion": float | null,
                "ajuste_direccional": float | null,
                "factor_temporal": float | null,
                "ajuste_historico": float | null,
                "formula": str
            },
            "requiere_validacion_medica": bool,       # NUEVO
            "evidencia": str                           # NUEVO
        }
    """
    cod1 = _normalizar_codigo(codigo1)
    cod2 = _normalizar_codigo(codigo2)
    
    # Base result
    resultado_base = {
        "correlacionados": False,
        "asertividad": 0.0,
        "confianza": "NINGUNA",
        "grupos_comunes": [],
        "explicacion": "",
        "detalles_calculo": {},
        "requiere_validacion_medica": False,
        "evidencia": ""
    }
    
    if not cod1 or not cod2:
        resultado_base["explicacion"] = "Código(s) inválido(s)"
        return resultado_base
    
    # Caso trivial: mismo código
    if cod1 == cod2:
        return {
            "correlacionados": True,
            "asertividad": 100.0,
            "confianza": "MUY_ALTA",
            "grupos_comunes": ["MISMO_CODIGO"],
            "explicacion": f"{cod1} = {cod2}: mismo diagnóstico, prórroga directa",
            "detalles_calculo": {
                "asertividad_base_grupo": 100.0,
                "ajuste_exclusion": None,
                "ajuste_direccional": None,
                "factor_temporal": None,
                "ajuste_historico": None,
                "formula": "Mismo código = 100%"
            },
            "requiere_validacion_medica": False,
            "evidencia": "CIE-10: Mismo diagnóstico"
        }
    
    # ═══ PASO 1: Buscar en grupos de correlación ═══
    mismo_bloque = _mismo_bloque(cod1, cod2)
    indice = _construir_indice_invertido()
    grupos_cod1 = set(indice.get(cod1, []))
    grupos_cod2 = set(indice.get(cod2, []))
    grupos_comunes = grupos_cod1 & grupos_cod2
    
    # ─── Determinar sistemas anatómicos (v3) ───
    sistema1 = _obtener_sistema_anatomico(cod1)
    sistema2 = _obtener_sistema_anatomico(cod2)
    mismo_sistema = (sistema1 == sistema2 and sistema1 != "DESCONOCIDO")
    inter_sistema = _buscar_correlacion_inter_sistema(sistema1, sistema2) if not mismo_sistema else None
    
    # ═══ JERARQUÍA DE 6 NIVELES ═══
    # Nivel 2: Mismo bloque (90%) — sube de 65% a 90% porque clínicamente
    # los códigos del mismo bloque CIE-10 son de la misma entidad diagnóstica
    # Ej: J00-J06 son todas infecciones agudas de vías resp. superiores
    if grupos_comunes:
        # Nivel 3: Grupo de correlación (usa asertividad del grupo)
        pass  # Se procesan abajo
    elif mismo_bloque:
        # Nivel 2: Mismo bloque CIE-10 → 90%
        pass  # Se procesan abajo
    elif mismo_sistema:
        # Nivel 4: Mismo sistema anatómico → 70%
        if cod1[0] == cod2[0]:
            # Mismo capítulo (misma letra) + mismo sistema = 70%
            pass
        else:
            # Diferente capítulo pero mismo sistema (ej: S y T = TRAUMATICO) = 70%
            pass
    elif inter_sistema:
        # Nivel 5: Inter-sistema vinculado → 65-80%
        pass
    elif cod1[0] == cod2[0]:
        # Nivel 6: Mismo capítulo sin vínculo clínico → 55%
        pass
    else:
        # Sin correlación
        resultado_base["explicacion"] = f"{cod1} y {cod2} no tienen correlación diagnóstica identificada (sistemas: {sistema1} ↔ {sistema2})"
        return resultado_base
    
    # ═══ PASO 2: Obtener asertividad base según nivel jerárquico ═══
    corr = _cargar_correlaciones()
    mejor_asertividad = 0.0
    mejor_grupo = ""
    mejor_evidencia = ""
    req_validacion = False
    explicaciones = []
    nivel_jerarquico = ""
    
    if grupos_comunes:
        # NIVEL 3: Grupo de correlación
        nivel_jerarquico = "GRUPO_CORRELACION"
        for g in grupos_comunes:
            grupo_data = corr["grupos_correlacion"].get(g, {})
            asert = grupo_data.get("asertividad", 80)
            if asert > mejor_asertividad:
                mejor_asertividad = asert
                mejor_grupo = g
                mejor_evidencia = grupo_data.get("evidencia", "")
            if grupo_data.get("requiere_validacion_medica", False):
                req_validacion = True
            explicaciones.append(grupo_data.get("logica", ""))
    elif mismo_bloque:
        # NIVEL 2: Mismo bloque CIE-10 → 90%
        nivel_jerarquico = "MISMO_BLOQUE"
        mejor_asertividad = 90.0
        mejor_grupo = "MISMO_BLOQUE"
        mejor_evidencia = "CIE-10 OMS: Mismo bloque diagnóstico — entidades clínicas estrechamente relacionadas"
        explicaciones.append(f"{cod1} y {cod2} pertenecen al mismo bloque CIE-10 (alta afinidad clínica)")
    elif mismo_sistema:
        # NIVEL 4: Mismo sistema anatómico → 70%
        nivel_jerarquico = "MISMO_SISTEMA"
        mejor_asertividad = 70.0
        mejor_grupo = f"SISTEMA_{sistema1}"
        mejor_evidencia = f"CIE-10 OMS: Mismo sistema anatómico ({sistema1})"
        explicaciones.append(f"{cod1} y {cod2} afectan el mismo sistema ({sistema1})")
        req_validacion = True
    elif inter_sistema:
        # NIVEL 5: Inter-sistema vinculado → asertividad del par
        nivel_jerarquico = "INTER_SISTEMA"
        mejor_asertividad = inter_sistema["asertividad"]
        mejor_grupo = f"INTER_{sistema1}_{sistema2}"
        mejor_evidencia = inter_sistema["evidencia"]
        explicaciones.append(f"Correlación inter-sistema {sistema1}↔{sistema2}: {inter_sistema['ejemplo']}")
        req_validacion = True
    elif cod1[0] == cod2[0]:
        # NIVEL 6: Mismo capítulo sin vínculo clínico → 55%
        nivel_jerarquico = "MISMO_CAPITULO"
        mejor_asertividad = 55.0
        mejor_grupo = "MISMO_CAPITULO"
        mejor_evidencia = "CIE-10 OMS: Mismo capítulo diagnóstico"
        explicaciones.append(f"{cod1} y {cod2} mismo capítulo CIE-10 sin correlación clínica definida")
        req_validacion = True
    
    asertividad_base = mejor_asertividad
    
    # ═══ PASO 3: Verificar EXCLUSIONES ═══
    ajuste_exclusion = None
    exclusion = _buscar_exclusion(cod1, cod2)
    if exclusion:
        if exclusion.get("bloquear", False):
            return {
                "correlacionados": False,
                "asertividad": 0.0,
                "confianza": "NINGUNA",
                "grupos_comunes": list(grupos_comunes),
                "explicacion": f"EXCLUSIÓN: {cod1} ↔ {cod2} — {exclusion.get('razon', 'Diagnósticos incompatibles para prórroga')}",
                "detalles_calculo": {
                    "asertividad_base_grupo": asertividad_base,
                    "ajuste_exclusion": 0.0,
                    "formula": "Exclusión bloqueante = 0%"
                },
                "requiere_validacion_medica": False,
                "evidencia": exclusion.get("evidencia", "")
            }
        else:
            # Exclusión no bloqueante: reducir asertividad
            ajuste_exclusion = exclusion.get("asertividad_reducida", 30)
            asertividad_base = min(asertividad_base, ajuste_exclusion)
            req_validacion = True
    
    # ═══ PASO 4: Verificar CORRELACIÓN DIRECCIONAL ═══
    ajuste_direccional = None
    cod_ant = _normalizar_codigo(codigo_anterior) if codigo_anterior else cod1
    cod_nvo = cod2 if cod_ant == cod1 else cod1
    
    direccional = _buscar_direccional(cod_ant, cod_nvo)
    if direccional and direccional.get("encontrado"):
        ajuste_direccional = direccional["asertividad_direccional"]
        # La asertividad direccional puede incrementar o reducir la base
        # Tomamos el promedio ponderado (70% grupo + 30% direccional)
        asertividad_pre_temporal = (asertividad_base * 0.7) + (ajuste_direccional * 0.3)
        explicaciones.append(f"Dirección {direccional['direccion']}: {direccional['razon']}")
    else:
        asertividad_pre_temporal = asertividad_base
    
    # ═══ PASO 5: Aplicar UMBRAL TEMPORAL ═══
    factor_temporal = None
    nota_temporal = ""
    if dias_entre is not None and dias_entre >= 0:
        temporal = _obtener_factor_temporal(mejor_grupo, dias_entre)
        factor_temporal = temporal["factor"]
        nota_temporal = temporal["nota"]
        asertividad_con_temporal = asertividad_pre_temporal * factor_temporal
    else:
        asertividad_con_temporal = asertividad_pre_temporal
    
    # ═══ PASO 6: Ajuste por HISTORIAL DE APRENDIZAJE ═══
    ajuste_historico = _obtener_ajuste_historico(cod1, cod2)
    if ajuste_historico is not None:
        # Promedio ponderado: 80% cálculo actual + 20% historial
        asertividad_final = (asertividad_con_temporal * 0.8) + (ajuste_historico * 0.2)
    else:
        asertividad_final = asertividad_con_temporal
    
    # ═══ PASO 7: Clampear y determinar confianza ═══
    asertividad_final = max(5.0, min(100.0, round(asertividad_final, 1)))
    
    # Determinar nivel de confianza a partir de la asertividad
    if asertividad_final >= 90:
        confianza = "MUY_ALTA"
    elif asertividad_final >= 75:
        confianza = "ALTA"
    elif asertividad_final >= 55:
        confianza = "MEDIA"
    elif asertividad_final >= 30:
        confianza = "BAJA"
    else:
        confianza = "NINGUNA"
    
    # Umbral de correlación
    umbrales_config = _cargar_umbrales().get("reglas_aplicacion", {})
    umbral_prorroga = umbrales_config.get("umbral_prorroga", 60)
    umbral_posible = umbrales_config.get("umbral_posible_prorroga", 40)
    
    correlacionados = asertividad_final >= umbral_posible
    
    # ═══ Construir explicación final ═══
    explicacion_parts = [f"{cod1} ↔ {cod2}"]
    if grupos_comunes:
        explicacion_parts.append(f"Grupo(s): {', '.join(grupos_comunes)}")
    if explicaciones:
        explicacion_parts.append(explicaciones[0])
    if nota_temporal:
        explicacion_parts.append(f"Temporal: {nota_temporal}")
    if exclusion and not exclusion.get("bloquear"):
        explicacion_parts.append(f"⚠️ Exclusión parcial: {exclusion.get('razon', '')}")
    
    explicacion_final = ". ".join(explicacion_parts)
    
    return {
        "correlacionados": correlacionados,
        "asertividad": asertividad_final,
        "confianza": confianza,
        "grupos_comunes": list(grupos_comunes) if grupos_comunes else ([mejor_grupo] if mejor_grupo else []),
        "mismo_bloque": mismo_bloque,
        "nivel_jerarquico": nivel_jerarquico,
        "sistemas_anatomicos": {"codigo1": sistema1, "codigo2": sistema2, "mismo_sistema": mismo_sistema},
        "explicacion": explicacion_final,
        "detalles_calculo": {
            "asertividad_base_grupo": round(mejor_asertividad, 1),
            "grupo_principal": mejor_grupo,
            "nivel_jerarquico": nivel_jerarquico,
            "ajuste_exclusion": ajuste_exclusion,
            "ajuste_direccional": ajuste_direccional,
            "factor_temporal": factor_temporal,
            "dias_entre": dias_entre,
            "nota_temporal": nota_temporal,
            "ajuste_historico": ajuste_historico,
            "asertividad_pre_temporal": round(asertividad_pre_temporal, 1),
            "asertividad_final": asertividad_final,
            "umbral_prorroga": umbral_prorroga,
            "umbral_posible_prorroga": umbral_posible,
            "formula": f"base({round(mejor_asertividad,1)}) → exclusion({ajuste_exclusion}) → direccional({ajuste_direccional}) → temporal(×{factor_temporal}) → historico({ajuste_historico}) = {asertividad_final}%"
        },
        "requiere_validacion_medica": req_validacion,
        "evidencia": mejor_evidencia
    }


def _mismo_bloque(cod1: str, cod2: str) -> bool:
    """Verifica si dos códigos están en el mismo bloque CIE-10"""
    cie10 = _cargar_cie10()
    codigos = cie10.get("codigos", {})
    bloque1 = codigos.get(cod1, {}).get("bloque", "")
    bloque2 = codigos.get(cod2, {}).get("bloque", "")
    if bloque1 and bloque2 and bloque1 == bloque2:
        return True
    return False


def obtener_todos_correlacionados(codigo: str) -> List[str]:
    """Retorna todos los códigos que se correlacionan con el dado"""
    cod_norm = _normalizar_codigo(codigo)
    indice = _construir_indice_invertido()
    grupos = indice.get(cod_norm, [])
    
    codigos_relacionados = set()
    corr = _cargar_correlaciones()
    for grupo_id in grupos:
        grupo_data = corr["grupos_correlacion"].get(grupo_id, {})
        for c in grupo_data.get("codigos", []):
            codigos_relacionados.add(_normalizar_codigo(c))
    
    codigos_relacionados.discard(cod_norm)
    return sorted(codigos_relacionados)


def validar_dias(codigo: str, dias_solicitados: int) -> dict:
    """
    Valida si los días de incapacidad están dentro del rango típico.
    NO es vinculante, es orientativo.
    """
    info = buscar_codigo(codigo)
    dias_tipicos = info.get("dias_tipicos", [])
    
    if not dias_tipicos or len(dias_tipicos) < 2:
        return {
            "codigo": codigo,
            "dias_solicitados": dias_solicitados,
            "dentro_rango": None,
            "mensaje": "Sin datos de rango típico para este código"
        }
    
    dia_min, dia_max = dias_tipicos[0], dias_tipicos[1]
    dentro = dia_min <= dias_solicitados <= dia_max
    
    return {
        "codigo": info["codigo"],
        "descripcion": info["descripcion"],
        "dias_solicitados": dias_solicitados,
        "rango_tipico": dias_tipicos,
        "dentro_rango": dentro,
        "mensaje": (
            f"✅ Dentro del rango típico ({dia_min}-{dia_max} días)" if dentro
            else f"⚠️ Fuera del rango típico ({dia_min}-{dia_max} días). Puede requerir revisión."
        )
    }


def validar_conteo_dias(fecha_inicio, fecha_fin, dias_incapacidad: int) -> dict:
    """
    Valida que el conteo de días sea correcto:
    fecha_fin - fecha_inicio + 1 == dias_incapacidad
    (porque el día de inicio cuenta)
    """
    from datetime import datetime
    
    if isinstance(fecha_inicio, str):
        fecha_inicio = datetime.fromisoformat(fecha_inicio.replace("Z", "+00:00")).replace(tzinfo=None)
    if isinstance(fecha_fin, str):
        fecha_fin = datetime.fromisoformat(fecha_fin.replace("Z", "+00:00")).replace(tzinfo=None)
    
    dias_calculados = (fecha_fin.date() - fecha_inicio.date()).days + 1  # +1 porque ambos días cuentan
    
    correcto = dias_calculados == dias_incapacidad
    
    return {
        "fecha_inicio": fecha_inicio.isoformat(),
        "fecha_fin": fecha_fin.isoformat(),
        "dias_declarados": dias_incapacidad,
        "dias_calculados": dias_calculados,
        "correcto": correcto,
        "mensaje": (
            f"✅ Conteo correcto: {dias_calculados} días ({fecha_inicio.date()} al {fecha_fin.date()})"
            if correcto else
            f"❌ Discrepancia: declarados {dias_incapacidad} pero calculados {dias_calculados} días ({fecha_inicio.date()} al {fecha_fin.date()})"
        )
    }


# ═══════════════════════════════════════════════════════════
# VALIDACIÓN DE COHERENCIA CLÍNICA (DÍAS vs DIAGNÓSTICO)
# ═══════════════════════════════════════════════════════════

def validar_dias_coherencia(codigo: str, dias_solicitados: int) -> dict:
    """
    Valida si los días de incapacidad son coherentes con el diagnóstico CIE-10.
    Detecta posible fraude (exceso de días) o error médico (déficit de días).
    
    LÓGICA:
    1. Buscar regla específica para el código en dias_tipicos_cie10.json
    2. Si no hay regla específica, calcular desde dias_tipicos del cie10_2026.json
       usando factores multiplicadores (×2 advertencia, ×3.5 alto, ×5 crítico)
    3. Verificar alertas por rango de días
    
    Retorna:
        {
            "valido": bool,
            "codigo": str,
            "diagnostico": str,
            "dias_solicitados": int,
            "dias_tipicos": [min, max],
            "dias_maximos_recomendados": int,
            "nivel_alerta": "OK"|"ADVERTENCIA"|"ALTA"|"CRITICA",
            "alertas": [...],
            "requiere_revision_medica": bool
        }
    """
    cod_norm = _normalizar_codigo(codigo)
    info = buscar_codigo(codigo)
    dias_tipicos_cfg = _cargar_dias_tipicos()
    reglas_defecto = dias_tipicos_cfg.get("reglas_por_defecto", {})
    validaciones = dias_tipicos_cfg.get("validaciones_especificas", {})
    
    # Buscar regla específica
    regla = validaciones.get(cod_norm)
    
    nombre = ""
    dias_min = 1
    dias_tipicos_val = 0
    dias_max_sin_alerta = 0
    dias_max_absolutos = 0
    alertas_config = []
    
    if regla:
        # Regla específica encontrada
        nombre = regla.get("nombre", info.get("descripcion", ""))
        dias_min = regla.get("dias_minimos", 1)
        dias_tipicos_val = regla.get("dias_tipicos", 0)
        dias_max_sin_alerta = regla.get("dias_maximos_sin_alerta", 0)
        dias_max_absolutos = regla.get("dias_maximos_absolutos", 9999)
        alertas_config = regla.get("alertas", [])
    elif info.get("dias_tipicos") and len(info["dias_tipicos"]) >= 2:
        # Regla por defecto calculada desde dias_tipicos
        nombre = info.get("descripcion", "")
        dia_min_t, dia_max_t = info["dias_tipicos"][0], info["dias_tipicos"][1]
        dias_min = dia_min_t
        dias_tipicos_val = dia_max_t
        factor_adv = reglas_defecto.get("factor_advertencia", 2.0)
        factor_alt = reglas_defecto.get("factor_alto", 3.5)
        factor_crit = reglas_defecto.get("factor_critico", 5.0)
        dias_max_sin_alerta = int(dia_max_t * factor_adv)
        dias_max_alto = int(dia_max_t * factor_alt)
        dias_max_absolutos = int(dia_max_t * factor_crit)
        
        # Generar alertas automáticas
        alertas_config = [
            {
                "min_dias": dias_max_sin_alerta + 1,
                "max_dias": dias_max_alto,
                "nivel": "ADVERTENCIA",
                "mensaje": reglas_defecto.get("mensaje_exceso_advertencia", "Días por encima del rango típico.")
            },
            {
                "min_dias": dias_max_alto + 1,
                "max_dias": dias_max_absolutos,
                "nivel": "ALTA",
                "mensaje": reglas_defecto.get("mensaje_exceso_alto", "Días significativamente por encima del rango.")
            },
            {
                "min_dias": dias_max_absolutos + 1,
                "max_dias": 9999,
                "nivel": "CRITICA",
                "mensaje": reglas_defecto.get("mensaje_exceso_critico", "ALERTA: Días excesivos para este diagnóstico.")
            },
        ]
    else:
        # Sin datos de días típicos
        return {
            "valido": True,
            "codigo": cod_norm,
            "diagnostico": info.get("descripcion", ""),
            "dias_solicitados": dias_solicitados,
            "dias_tipicos": [],
            "dias_maximos_recomendados": None,
            "nivel_alerta": "OK",
            "alertas": [],
            "requiere_revision_medica": False,
            "nota": "Código sin datos de días típicos para validación"
        }
    
    # ─── Evaluar alertas ───
    alertas = []
    nivel_max = "OK"
    prioridades = {"OK": 0, "ADVERTENCIA": 1, "ALTA": 2, "CRITICA": 3}
    
    # Verificar déficit (días por debajo del mínimo)
    if dias_solicitados < dias_min:
        alerta_deficit = {
            "nivel": "ADVERTENCIA",
            "tipo": "DEFICIT",
            "mensaje": f"Días solicitados ({dias_solicitados}) por debajo del mínimo típico ({dias_min}d) para {nombre}. Verificar alta médica prematura."
        }
        alertas.append(alerta_deficit)
        if prioridades.get("ADVERTENCIA", 0) > prioridades.get(nivel_max, 0):
            nivel_max = "ADVERTENCIA"
    
    # Verificar exceso — buscar alerta por rango
    for alerta_cfg in alertas_config:
        min_d = alerta_cfg.get("min_dias", 0)
        max_d = alerta_cfg.get("max_dias", 9999)
        if min_d <= dias_solicitados <= max_d:
            nivel_alerta = alerta_cfg.get("nivel", "ADVERTENCIA")
            alertas.append({
                "nivel": nivel_alerta,
                "tipo": "EXCESO" if dias_solicitados > dias_max_sin_alerta else "DEFICIT",
                "mensaje": alerta_cfg.get("mensaje", "")
            })
            if prioridades.get(nivel_alerta, 0) > prioridades.get(nivel_max, 0):
                nivel_max = nivel_alerta
    
    return {
        "valido": nivel_max != "CRITICA",
        "codigo": cod_norm,
        "diagnostico": nombre,
        "dias_solicitados": dias_solicitados,
        "dias_tipicos": info.get("dias_tipicos", [dias_min, dias_tipicos_val]),
        "dias_maximos_recomendados": dias_max_sin_alerta,
        "dias_maximos_absolutos": dias_max_absolutos,
        "nivel_alerta": nivel_max,
        "alertas": alertas,
        "requiere_revision_medica": nivel_max in ["ALTA", "CRITICA"],
        "accion_recomendada": dias_tipicos_cfg.get("niveles_alerta", {}).get(nivel_max, {}).get("accion", "")
    }


# ═══════════════════════════════════════════════════════════
# INFO GENERAL
# ═══════════════════════════════════════════════════════════

def info_sistema() -> dict:
    """Información del sistema CIE-10 v2 cargado"""
    cie10 = _cargar_cie10()
    corr = _cargar_correlaciones()
    indice = _construir_indice_invertido()
    excl = _cargar_exclusiones()
    direc = _cargar_direccionales()
    umbr = _cargar_umbrales()
    valid = _cargar_validaciones()
    
    return {
        "version_motor": "3.0",
        "version_cie10": cie10.get("version"),
        "total_codigos": len(cie10.get("codigos", {})),
        "total_capitulos": len(cie10.get("capitulos", {})),
        "total_sistemas_anatomicos": len(cie10.get("sistemas_anatomicos", {}).get("sistemas_lista", [])),
        "total_correlaciones_inter_sistema": len(cie10.get("correlaciones_inter_sistema", {}).get("pares", [])),
        "version_correlaciones": corr.get("version"),
        "total_grupos_correlacion": len(corr.get("grupos_correlacion", {})),
        "total_codigos_indexados": len(indice),
        "total_exclusiones": len(excl.get("exclusiones", [])),
        "total_direccionales": len(direc.get("direccionales", [])),
        "total_grupos_temporales": len(umbr.get("umbrales_por_grupo", {})),
        "total_validaciones_historicas": valid.get("estadisticas", {}).get("total_validaciones", 0),
        "total_codigos_coherencia_dias": len(_cargar_dias_tipicos().get("validaciones_especificas", {})),
        "precision_historica": valid.get("estadisticas", {}).get("precision_historica"),
        "jerarquia_niveles": [
            "Nivel 1: Mismo código (100%)",
            "Nivel 2: Mismo bloque (90%)",
            "Nivel 3: Grupo correlación (variable)",
            "Nivel 4: Mismo sistema anatómico (70%)",
            "Nivel 5: Inter-sistema vinculado (65-80%)",
            "Nivel 6: Mismo capítulo (55%)"
        ],
        "ventana_prorroga_dias": corr.get("reglas_temporales", {}).get("ventana_prorroga_dias", 30),
        "ventana_prorroga_maxima": corr.get("reglas_temporales", {}).get("ventana_prorroga_maxima_dias", 90),
        "umbral_prorroga": umbr.get("reglas_aplicacion", {}).get("umbral_prorroga", 60),
        "umbral_posible_prorroga": umbr.get("reglas_aplicacion", {}).get("umbral_posible_prorroga", 40),
        "normativa": corr.get("normativa", {}),
        "ultima_actualizacion": cie10.get("ultima_actualizacion"),
    }
