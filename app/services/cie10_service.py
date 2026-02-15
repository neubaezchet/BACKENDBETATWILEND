"""
SERVICIO CIE-10 - Motor de búsqueda y correlación de diagnósticos
=================================================================
Carga los JSONs de CIE-10 y correlaciones una sola vez en memoria.
Provee funciones de búsqueda, validación y correlación.

Para actualizar a CIE-11: solo reemplace los archivos JSON en app/data/
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
    """Fuerza recarga de los JSONs (para actualizaciones en caliente)"""
    global _cie10_data, _correlaciones_data, _codigo_a_grupos
    _cie10_data = None
    _correlaciones_data = None
    _codigo_a_grupos = None
    _cargar_cie10()
    _cargar_correlaciones()
    _construir_indice_invertido()
    return {"ok": True, "mensaje": "Datos CIE-10 y correlaciones recargados"}


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
    """Busca un código CIE-10 y retorna su información completa"""
    cie10 = _cargar_cie10()
    cod_norm = _normalizar_codigo(codigo)
    info = cie10.get("codigos", {}).get(cod_norm)
    if info:
        return {
            "codigo": cod_norm,
            "codigo_original": codigo,
            "descripcion": info.get("desc", ""),
            "bloque": info.get("bloque", ""),
            "grupo": info.get("grupo", ""),
            "dias_tipicos": info.get("dias_tipicos", []),
            "encontrado": True,
        }
    # No encontrado exacto, pero podemos dar info del capítulo
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
# CORRELACIÓN DE DIAGNÓSTICOS
# ═══════════════════════════════════════════════════════════

def son_correlacionados(codigo1: str, codigo2: str) -> dict:
    """
    Determina si dos códigos CIE-10 están correlacionados.
    
    Retorna:
        {
            "correlacionados": bool,
            "confianza": "alta" | "media" | "baja" | "ninguna",
            "grupos_comunes": [...],
            "explicacion": str
        }
    """
    cod1 = _normalizar_codigo(codigo1)
    cod2 = _normalizar_codigo(codigo2)
    
    if not cod1 or not cod2:
        return {
            "correlacionados": False,
            "confianza": "ninguna",
            "grupos_comunes": [],
            "explicacion": "Código(s) inválido(s)"
        }
    
    # Caso trivial: mismo código
    if cod1 == cod2:
        return {
            "correlacionados": True,
            "confianza": "alta",
            "grupos_comunes": ["MISMO_CODIGO"],
            "explicacion": f"{cod1} = {cod2}: mismo diagnóstico, prórroga directa"
        }
    
    # Mismo bloque CIE-10 (ej: A00-A09)
    mismo_bloque = _mismo_bloque(cod1, cod2)
    
    # Buscar en correlaciones
    indice = _construir_indice_invertido()
    grupos_cod1 = set(indice.get(cod1, []))
    grupos_cod2 = set(indice.get(cod2, []))
    grupos_comunes = grupos_cod1 & grupos_cod2
    
    if grupos_comunes:
        # Obtener la confianza más alta entre los grupos comunes
        corr = _cargar_correlaciones()
        confianzas = []
        explicaciones = []
        for g in grupos_comunes:
            grupo_data = corr["grupos_correlacion"].get(g, {})
            confianzas.append(grupo_data.get("confianza", "media"))
            explicaciones.append(grupo_data.get("logica", ""))
        
        mejor_confianza = "alta" if "alta" in confianzas else ("media" if "media" in confianzas else "baja")
        
        return {
            "correlacionados": True,
            "confianza": mejor_confianza,
            "grupos_comunes": list(grupos_comunes),
            "mismo_bloque": mismo_bloque,
            "explicacion": f"{cod1} ↔ {cod2}: diagnósticos relacionados en {', '.join(grupos_comunes)}. {explicaciones[0] if explicaciones else ''}"
        }
    
    # Mismo bloque pero no en correlaciones explícitas
    if mismo_bloque:
        return {
            "correlacionados": True,
            "confianza": "media",
            "grupos_comunes": ["MISMO_BLOQUE"],
            "mismo_bloque": True,
            "explicacion": f"{cod1} y {cod2} pertenecen al mismo bloque CIE-10, probable relación clínica"
        }
    
    # Misma letra (mismo capítulo general)
    if cod1[0] == cod2[0]:
        return {
            "correlacionados": False,
            "confianza": "baja",
            "grupos_comunes": [],
            "mismo_capitulo": True,
            "explicacion": f"{cod1} y {cod2} están en el mismo capítulo pero sin correlación clínica definida"
        }
    
    return {
        "correlacionados": False,
        "confianza": "ninguna",
        "grupos_comunes": [],
        "explicacion": f"{cod1} y {cod2} no tienen correlación diagnóstica identificada"
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
# INFO GENERAL
# ═══════════════════════════════════════════════════════════

def info_sistema() -> dict:
    """Información del sistema CIE-10 cargado"""
    cie10 = _cargar_cie10()
    corr = _cargar_correlaciones()
    indice = _construir_indice_invertido()
    
    return {
        "version_cie10": cie10.get("version"),
        "total_codigos": len(cie10.get("codigos", {})),
        "total_capitulos": len(cie10.get("capitulos", {})),
        "version_correlaciones": corr.get("version"),
        "total_grupos_correlacion": len(corr.get("grupos_correlacion", {})),
        "total_codigos_indexados": len(indice),
        "ventana_prorroga_dias": corr.get("reglas_temporales", {}).get("ventana_prorroga_dias", 30),
        "ventana_prorroga_maxima": corr.get("reglas_temporales", {}).get("ventana_prorroga_maxima_dias", 90),
        "ultima_actualizacion": cie10.get("ultima_actualizacion"),
    }
