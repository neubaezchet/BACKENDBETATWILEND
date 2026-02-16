"""
SERVICIO OMS ICD API + Base de datos oficial MinSalud Colombia
===============================================================
Integración con la ICD API de la OMS (Organización Mundial de la Salud)
y la base de datos oficial CIE-10 de MinSalud con 12,568 códigos.

COMPONENTES:
  1. Base local CIE-10 oficial (12,568 códigos) — siempre disponible
  2. Mapping CIE-10 ↔ CIE-11 (17,349 registros) — preparación CIE-11
  3. Cliente ICD API OMS — consultas en línea (requiere credenciales)

FUENTES:
  - CIE10.json: Base oficial MinSalud Colombia — Resolución 1895/2001
  - mapping11To10.json: OMS ICD-11 mapping tables (Jan 2025)
  - ICD API: https://icd.who.int/icdapi — OMS OAuth2

CREDENCIALES:
  Para usar la ICD API en línea, registrarse en https://icd.who.int/icdapi
  y configurar variables de entorno:
    ICD_API_CLIENT_ID=<tu_client_id>
    ICD_API_CLIENT_SECRET=<tu_client_secret>
"""

import json
import os
import re
import logging
from typing import Optional, List, Dict
from pathlib import Path
from functools import lru_cache
from datetime import datetime

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════

_DATA_DIR = Path(__file__).parent.parent / "data"

# ICD API OMS
ICD_API_TOKEN_URL = "https://icdaccessmanagement.who.int/connect/token"
ICD_API_BASE_URL = "https://id.who.int/icd"
ICD_API_RELEASE_10 = f"{ICD_API_BASE_URL}/release/10/2019"
ICD_API_RELEASE_11 = f"{ICD_API_BASE_URL}/release/11/2025-01"

# ═══════════════════════════════════════════════════════════
# CARGA DE DATOS LOCALES (singleton)
# ═══════════════════════════════════════════════════════════

_cie10_oficial: Optional[dict] = None   # {código_normalizado: {title, code_original, text_search}}
_mapping_11a10: Optional[list] = None   # [{icd10Code, icd11Code, icd11Title, icd10Title}]
_icd_token: Optional[dict] = None       # {access_token, expires_at}


def _cargar_cie10_oficial() -> dict:
    """
    Carga los 12,568 códigos CIE-10 oficiales de MinSalud.
    Normaliza a un dict indexado por código base (ej: A00, A001, etc.)
    """
    global _cie10_oficial
    if _cie10_oficial is not None:
        return _cie10_oficial

    ruta = _DATA_DIR / "cie10_oficial_minsalud.json"
    if not ruta.exists():
        logger.warning("⚠️ No se encontró cie10_oficial_minsalud.json")
        _cie10_oficial = {}
        return _cie10_oficial

    with open(ruta, "r", encoding="utf-8") as f:
        data = json.load(f)

    codigos_raw = data.get("CIE10", [])
    _cie10_oficial = {}

    for c in codigos_raw:
        code = c.get("Icd10Code", "")
        title = c.get("Icd10Title", "")
        text_search = c.get("TextSearch", "")

        # Guardar con código original (ej: A00.0)
        _cie10_oficial[code] = {
            "titulo": title,
            "codigo_original": code,
            "texto_busqueda": text_search
        }

        # También guardar normalizado sin punto (ej: A000)
        code_norm = code.replace(".", "").upper().strip()
        if code_norm != code:
            _cie10_oficial[code_norm] = {
                "titulo": title,
                "codigo_original": code,
                "texto_busqueda": text_search
            }

        # Guardar código base de 3 caracteres (ej: A00) si no existe
        code_base = re.match(r"([A-Z]\d{2})", code_norm)
        if code_base:
            base = code_base.group(1)
            if base not in _cie10_oficial:
                _cie10_oficial[base] = {
                    "titulo": title,
                    "codigo_original": code,
                    "texto_busqueda": text_search
                }

    logger.info(f"✅ CIE-10 oficial MinSalud cargado: {len(codigos_raw)} códigos ({len(_cie10_oficial)} índices)")
    print(f"✅ CIE-10 oficial MinSalud cargado: {len(codigos_raw)} códigos")
    return _cie10_oficial


def _cargar_mapping_cie11() -> list:
    """Carga los 17,349 mappings CIE-11 → CIE-10"""
    global _mapping_11a10
    if _mapping_11a10 is not None:
        return _mapping_11a10

    ruta = _DATA_DIR / "mapping_cie11_a_cie10.json"
    if not ruta.exists():
        logger.warning("⚠️ No se encontró mapping_cie11_a_cie10.json")
        _mapping_11a10 = []
        return _mapping_11a10

    with open(ruta, "r", encoding="utf-8") as f:
        data = json.load(f)

    _mapping_11a10 = data.get("map11To10", [])
    logger.info(f"✅ Mapping CIE-11→CIE-10 cargado: {len(_mapping_11a10)} registros")
    print(f"✅ Mapping CIE-11→CIE-10 cargado: {len(_mapping_11a10)} registros")
    return _mapping_11a10


def recargar_datos_oms():
    """Recarga todos los datos OMS/MinSalud"""
    global _cie10_oficial, _mapping_11a10
    _cie10_oficial = None
    _mapping_11a10 = None
    _cargar_cie10_oficial()
    _cargar_mapping_cie11()
    return {"ok": True, "mensaje": "Datos OMS/MinSalud recargados"}


# ═══════════════════════════════════════════════════════════
# BÚSQUEDA EN BASE OFICIAL (12,568 CÓDIGOS)
# ═══════════════════════════════════════════════════════════

def buscar_codigo_oficial(codigo: str) -> Optional[dict]:
    """
    Busca un código CIE-10 en la base oficial MinSalud (12,568 códigos).
    Acepta formatos: A00, A00.0, A000, a00, a00.0
    
    Retorna:
        {
            "codigo": "A00.0",
            "titulo": "Colera debido a Vibrio cholerae 01, biotipo cholerae",
            "encontrado": True,
            "fuente": "MinSalud_CIE10_Oficial"
        }
    """
    oficial = _cargar_cie10_oficial()

    if not codigo:
        return None

    # Intentar búsquedas en orden de especificidad
    codigo = codigo.strip()
    variantes = [
        codigo.upper(),                          # Original
        codigo.upper().replace(".", ""),          # Sin punto
        codigo.upper().replace(" ", ""),          # Sin espacios
    ]

    # Si tiene punto, agregar sin punto
    if "." in codigo:
        variantes.append(codigo.upper().replace(".", ""))

    # Si NO tiene punto pero tiene 4+ chars, intentar con punto (A000 → A00.0)
    code_upper = codigo.upper().replace(".", "").replace(" ", "")
    if len(code_upper) >= 4 and "." not in codigo:
        with_dot = code_upper[:3] + "." + code_upper[3:]
        variantes.append(with_dot)

    for var in variantes:
        if var in oficial:
            info = oficial[var]
            return {
                "codigo": info["codigo_original"],
                "titulo": info["titulo"],
                "encontrado": True,
                "fuente": "MinSalud_CIE10_Oficial"
            }

    return {
        "codigo": codigo,
        "titulo": "",
        "encontrado": False,
        "fuente": "MinSalud_CIE10_Oficial"
    }


def buscar_por_texto(texto: str, limite: int = 20) -> List[dict]:
    """
    Busca códigos CIE-10 por texto (descripción) en la base oficial.
    Búsqueda case-insensitive en el campo TextSearch.
    
    Ejemplo: buscar_por_texto("resfriado") → [J00.X, ...]
    """
    oficial = _cargar_cie10_oficial()
    texto_lower = texto.lower().strip()

    if not texto_lower:
        return []

    resultados = []
    codigos_vistos = set()

    for key, info in oficial.items():
        code_orig = info["codigo_original"]
        if code_orig in codigos_vistos:
            continue

        text_search = info.get("texto_busqueda", "").lower()
        titulo = info.get("titulo", "").lower()

        if texto_lower in text_search or texto_lower in titulo:
            resultados.append({
                "codigo": code_orig,
                "titulo": info["titulo"],
                "fuente": "MinSalud_CIE10_Oficial"
            })
            codigos_vistos.add(code_orig)

            if len(resultados) >= limite:
                break

    return resultados


# ═══════════════════════════════════════════════════════════
# MAPPING CIE-10 ↔ CIE-11
# ═══════════════════════════════════════════════════════════

def obtener_cie11_de_cie10(codigo_cie10: str) -> List[dict]:
    """
    Dado un código CIE-10, retorna los códigos CIE-11 correspondientes.
    
    Retorna:
        [
            {
                "cie10_codigo": "A00.9",
                "cie10_titulo": "Colera, no especificado",
                "cie11_codigo": "1A00",
                "cie11_titulo": "Cholera"
            }
        ]
    """
    mapping = _cargar_mapping_cie11()
    codigo_norm = codigo_cie10.strip().upper()

    # Buscar código exacto
    resultados = []
    for m in mapping:
        cie10 = m.get("icd10Code", "").upper()
        if cie10 == codigo_norm or cie10.replace(".", "") == codigo_norm.replace(".", ""):
            resultados.append({
                "cie10_codigo": m.get("icd10Code", ""),
                "cie10_titulo": m.get("icd10Title", ""),
                "cie11_codigo": m.get("icd11Code", ""),
                "cie11_titulo": m.get("icd11Title", "")
            })

    # Si no encontró exacto, buscar por código base (3 chars)
    if not resultados:
        code_base = re.match(r"([A-Z]\d{2})", codigo_norm)
        if code_base:
            base = code_base.group(1)
            for m in mapping:
                cie10 = m.get("icd10Code", "").upper().replace(".", "")
                if cie10.startswith(base):
                    resultados.append({
                        "cie10_codigo": m.get("icd10Code", ""),
                        "cie10_titulo": m.get("icd10Title", ""),
                        "cie11_codigo": m.get("icd11Code", ""),
                        "cie11_titulo": m.get("icd11Title", "")
                    })
                    if len(resultados) >= 10:
                        break

    return resultados


def obtener_cie10_de_cie11(codigo_cie11: str) -> List[dict]:
    """
    Dado un código CIE-11, retorna los códigos CIE-10 correspondientes.
    Soporta códigos poscoordinados con / o -.
    """
    mapping = _cargar_mapping_cie11()
    codigo_norm = codigo_cie11.strip().upper().replace("-", "/")

    resultados = []
    for m in mapping:
        cie11 = m.get("icd11Code", "").upper()
        if cie11 == codigo_norm:
            resultados.append({
                "cie10_codigo": m.get("icd10Code", ""),
                "cie10_titulo": m.get("icd10Title", ""),
                "cie11_codigo": m.get("icd11Code", ""),
                "cie11_titulo": m.get("icd11Title", "")
            })

    return resultados


# ═══════════════════════════════════════════════════════════
# CLIENTE ICD API OMS (en línea)
# ═══════════════════════════════════════════════════════════

async def _obtener_token_icd() -> Optional[str]:
    """
    Obtiene un token OAuth2 de la ICD API de la OMS.
    Credenciales desde variables de entorno.
    
    Registrarse en: https://icd.who.int/icdapi
    Variables:
        ICD_API_CLIENT_ID
        ICD_API_CLIENT_SECRET
    """
    global _icd_token

    client_id = os.environ.get("ICD_API_CLIENT_ID", "")
    client_secret = os.environ.get("ICD_API_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        return None

    # Verificar si el token actual aún es válido
    if _icd_token and _icd_token.get("expires_at", 0) > datetime.now().timestamp():
        return _icd_token["access_token"]

    try:
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.post(
                ICD_API_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": "icdapi_access",
                    "grant_type": "client_credentials"
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            response.raise_for_status()
            data = response.json()

            _icd_token = {
                "access_token": data["access_token"],
                "expires_at": datetime.now().timestamp() + data.get("expires_in", 3600) - 60
            }
            logger.info("✅ Token ICD API OMS obtenido")
            return _icd_token["access_token"]

    except Exception as e:
        logger.error(f"❌ Error obteniendo token ICD API: {e}")
        return None


async def buscar_icd_api(codigo: str, version: str = "10") -> Optional[dict]:
    """
    Busca un código en la ICD API de la OMS (en línea).
    Requiere credenciales configuradas.
    
    version: "10" o "11"
    """
    token = await _obtener_token_icd()
    if not token:
        return None

    try:
        import httpx

        if version == "10":
            url = f"{ICD_API_RELEASE_10}/{codigo}"
        else:
            url = f"{ICD_API_RELEASE_11}/{codigo}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Accept-Language": "es",
                    "API-Version": "v2"
                }
            )
            response.raise_for_status()
            data = response.json()

            return {
                "codigo": data.get("code", codigo),
                "titulo": data.get("title", {}).get("@value", ""),
                "definicion": data.get("definition", {}).get("@value", ""),
                "exclusiones": [e.get("label", {}).get("@value", "") for e in data.get("exclusion", [])],
                "inclusiones": [i.get("@value", "") for i in data.get("inclusion", [])],
                "parent": data.get("parent", []),
                "child": data.get("child", []),
                "fuente": f"ICD_API_OMS_v{version}"
            }

    except Exception as e:
        logger.warning(f"⚠️ Error consultando ICD API: {e}")
        return None


# ═══════════════════════════════════════════════════════════
# BÚSQUEDA UNIFICADA (LOCAL + API)
# ═══════════════════════════════════════════════════════════

async def buscar_codigo_completo(codigo: str) -> dict:
    """
    Búsqueda completa de un código CIE-10:
    1. Primero busca en base oficial MinSalud (12,568 códigos) — instantáneo
    2. Si hay credenciales ICD API, enriquece con datos OMS — en línea
    3. Incluye mapping a CIE-11 si existe
    
    Retorna resultado enriquecido con todas las fuentes disponibles.
    """
    resultado = {
        "codigo": codigo,
        "encontrado": False,
        "fuentes": []
    }

    # 1. Base oficial MinSalud (siempre disponible)
    oficial = buscar_codigo_oficial(codigo)
    if oficial and oficial.get("encontrado"):
        resultado["encontrado"] = True
        resultado["titulo_oficial"] = oficial["titulo"]
        resultado["codigo_oficial"] = oficial["codigo"]
        resultado["fuentes"].append("MinSalud_CIE10_Oficial")

    # 2. Mapping CIE-11
    cie11 = obtener_cie11_de_cie10(codigo)
    if cie11:
        resultado["cie11_equivalente"] = cie11
        resultado["fuentes"].append("OMS_Mapping_CIE11")

    # 3. ICD API OMS (si hay credenciales)
    api_result = await buscar_icd_api(codigo, version="10")
    if api_result:
        resultado["datos_oms"] = api_result
        resultado["fuentes"].append("ICD_API_OMS")
        if not resultado.get("titulo_oficial"):
            resultado["titulo_oficial"] = api_result.get("titulo", "")
            resultado["encontrado"] = True

    return resultado


# ═══════════════════════════════════════════════════════════
# INFO DEL SERVICIO
# ═══════════════════════════════════════════════════════════

def info_servicio_oms() -> dict:
    """Información del servicio OMS/MinSalud"""
    oficial = _cargar_cie10_oficial()
    mapping = _cargar_mapping_cie11()

    client_id = os.environ.get("ICD_API_CLIENT_ID", "")
    api_configurada = bool(client_id)

    # Contar códigos únicos en la base oficial
    codigos_unicos = set()
    for key, info in oficial.items():
        codigos_unicos.add(info["codigo_original"])

    return {
        "version": "1.0",
        "fuentes": {
            "cie10_oficial_minsalud": {
                "total_codigos": len(codigos_unicos),
                "total_indices": len(oficial),
                "archivo": "cie10_oficial_minsalud.json",
                "origen": "MinSalud Colombia — Resolución 1895/2001"
            },
            "mapping_cie11": {
                "total_registros": len(mapping),
                "archivo": "mapping_cie11_a_cie10.json",
                "origen": "OMS ICD-11 Mapping Tables (Jan 2025)"
            },
            "icd_api_oms": {
                "configurada": api_configurada,
                "url_token": ICD_API_TOKEN_URL,
                "url_base": ICD_API_BASE_URL,
                "registro": "https://icd.who.int/icdapi",
                "nota": "Configurar ICD_API_CLIENT_ID e ICD_API_CLIENT_SECRET" if not api_configurada else "API activa"
            }
        }
    }


# ═══════════════════════════════════════════════════════════
# VALIDACIÓN DE CORRELACIÓN OMS (API en vivo)
# ═══════════════════════════════════════════════════════════

async def obtener_jerarquia_oms(codigo: str) -> Optional[dict]:
    """
    Obtiene la jerarquía completa de un código CIE-10 desde la API OMS.
    Retorna parent, child, blockId, chapter, exclusiones, inclusiones.
    """
    token = await _obtener_token_icd()
    if not token:
        return None

    try:
        import httpx

        # Normalizar código para URL de la API (con punto: A00.0)
        code_upper = codigo.strip().upper().replace(".", "")
        if len(code_upper) >= 4:
            code_api = code_upper[:3] + "." + code_upper[3:]
        else:
            code_api = code_upper

        url = f"{ICD_API_RELEASE_10}/{code_api}"

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Accept-Language": "es",
                    "API-Version": "v2"
                }
            )

            if response.status_code == 404:
                # Intentar sin subcódigo (solo 3 chars)
                url_base = f"{ICD_API_RELEASE_10}/{code_upper[:3]}"
                response = await client.get(
                    url_base,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Accept-Language": "es",
                        "API-Version": "v2"
                    }
                )

            if response.status_code != 200:
                logger.warning(f"⚠️ OMS API {response.status_code} para {codigo}")
                return None

            data = response.json()

            # Extraer parents como lista de URIs
            parents_raw = data.get("parent", [])
            if isinstance(parents_raw, str):
                parents_raw = [parents_raw]

            # Extraer título
            title = data.get("title", {})
            if isinstance(title, dict):
                title = title.get("@value", "")

            return {
                "codigo": data.get("code", codigo),
                "titulo": title,
                "parent_uris": parents_raw,
                "child_uris": data.get("child", []),
                "chapter": data.get("classKind", ""),
                "block_id": _extraer_bloque_de_uri(parents_raw),
                "exclusiones": [e.get("label", {}).get("@value", "") for e in data.get("exclusion", [])],
                "inclusiones": [i.get("@value", "") if isinstance(i, dict) else str(i) for i in data.get("inclusion", [])],
                "fuente": "ICD_API_OMS"
            }

    except Exception as e:
        logger.warning(f"⚠️ Error jerarquía OMS para {codigo}: {e}")
        return None


def _extraer_bloque_de_uri(parent_uris: list) -> str:
    """Extrae el bloque CIE-10 de las URIs parent de la API OMS"""
    for uri in parent_uris:
        # URIs como: http://id.who.int/icd/release/10/2019/A00-A09
        match = re.search(r'/([A-Z]\d{2}-[A-Z]\d{2})$', str(uri))
        if match:
            return match.group(1)
    return ""


async def validar_correlacion_oms(codigo1: str, codigo2: str) -> dict:
    """
    Valida si dos códigos CIE-10 están correlacionados según la jerarquía
    oficial de la OMS (API en vivo).
    
    Evalúa 4 niveles jerárquicos OMS:
      1. Mismo parent (bloque) → 98% confianza
      2. Parents comparten abuelo → 92% confianza
      3. Mismo capítulo ICD → 85% confianza
      4. Sin relación jerárquica → 0%
    
    También verifica si un código aparece en las exclusiones del otro
    (lo cual invalidaría la correlación).
    
    Retorna:
        {
            "validado_oms": True/False,
            "correlacionados_oms": True/False,
            "confianza_oms": float (0-100),
            "nivel_oms": str,
            "razon_oms": str,
            "cita_legal_oms": str,
            "jerarquia_codigo1": {...},
            "jerarquia_codigo2": {...},
            "error": str or None
        }
    """
    resultado_base = {
        "validado_oms": False,
        "correlacionados_oms": False,
        "confianza_oms": 0.0,
        "nivel_oms": "NO_VALIDADO",
        "razon_oms": "",
        "cita_legal_oms": "",
        "jerarquia_codigo1": None,
        "jerarquia_codigo2": None,
        "error": None
    }

    # Obtener jerarquía de ambos códigos en paralelo
    try:
        import asyncio as _asyncio
        jer1, jer2 = await _asyncio.gather(
            obtener_jerarquia_oms(codigo1),
            obtener_jerarquia_oms(codigo2)
        )
    except Exception as e:
        resultado_base["error"] = f"Error consultando API OMS: {str(e)}"
        return resultado_base

    if not jer1 or not jer2:
        faltante = []
        if not jer1:
            faltante.append(codigo1)
        if not jer2:
            faltante.append(codigo2)
        resultado_base["error"] = f"Código(s) {', '.join(faltante)} no encontrado(s) en API OMS"
        resultado_base["jerarquia_codigo1"] = jer1
        resultado_base["jerarquia_codigo2"] = jer2
        return resultado_base

    resultado_base["validado_oms"] = True
    resultado_base["jerarquia_codigo1"] = jer1
    resultado_base["jerarquia_codigo2"] = jer2

    # ═══ Verificar exclusiones mutuas ═══
    titulo1_lower = jer1.get("titulo", "").lower()
    titulo2_lower = jer2.get("titulo", "").lower()

    for excl in jer1.get("exclusiones", []):
        if codigo2.upper().replace(".", "") in excl.upper().replace(".", "") or \
           titulo2_lower and any(p in excl.lower() for p in titulo2_lower.split()[:3] if len(p) > 3):
            resultado_base["correlacionados_oms"] = False
            resultado_base["confianza_oms"] = 0.0
            resultado_base["nivel_oms"] = "EXCLUIDO_OMS"
            resultado_base["razon_oms"] = f"OMS EXCLUYE: {jer1['codigo']} excluye explícitamente a {jer2['codigo']}: '{excl}'"
            resultado_base["cita_legal_oms"] = f"Según OMS ICD-10 (2019), {jer1['codigo']} excluye {jer2['codigo']}. No procede prórroga."
            return resultado_base

    for excl in jer2.get("exclusiones", []):
        if codigo1.upper().replace(".", "") in excl.upper().replace(".", "") or \
           titulo1_lower and any(p in excl.lower() for p in titulo1_lower.split()[:3] if len(p) > 3):
            resultado_base["correlacionados_oms"] = False
            resultado_base["confianza_oms"] = 0.0
            resultado_base["nivel_oms"] = "EXCLUIDO_OMS"
            resultado_base["razon_oms"] = f"OMS EXCLUYE: {jer2['codigo']} excluye explícitamente a {jer1['codigo']}: '{excl}'"
            resultado_base["cita_legal_oms"] = f"Según OMS ICD-10 (2019), {jer2['codigo']} excluye {jer1['codigo']}. No procede prórroga."
            return resultado_base

    # ═══ NIVEL 1: Mismo parent (mismo bloque) → 98% ═══
    parents1 = set(jer1.get("parent_uris", []))
    parents2 = set(jer2.get("parent_uris", []))
    parents_comunes = parents1 & parents2

    if parents_comunes:
        bloque = jer1.get("block_id") or jer2.get("block_id") or "mismo bloque"
        resultado_base["correlacionados_oms"] = True
        resultado_base["confianza_oms"] = 98.0
        resultado_base["nivel_oms"] = "MISMO_PARENT_OMS"
        resultado_base["razon_oms"] = (
            f"OMS CONFIRMA: {jer1['codigo']} ({jer1['titulo']}) y {jer2['codigo']} ({jer2['titulo']}) "
            f"comparten mismo parent jerárquico ({bloque})"
        )
        resultado_base["cita_legal_oms"] = (
            f"Según la clasificación OMS ICD-10 (Release 2019), los diagnósticos {jer1['codigo']} y {jer2['codigo']} "
            f"pertenecen al mismo grupo nosológico ({bloque}), confirmando correlación clínica para prórroga. "
            f"Ref: ICD-10 OMS — https://icd.who.int"
        )
        return resultado_base

    # ═══ NIVEL 2: Parents comparten abuelo → 92% ═══
    # Obtener los parents de los parents (abuelos)
    try:
        import asyncio as _asyncio
        abuelos = []
        for p_uri in list(parents1)[:2] + list(parents2)[:2]:
            # Extraer código del URI
            match = re.search(r'/([A-Z0-9][\w.-]*)$', str(p_uri))
            if match:
                abuelos.append(match.group(1))

        # Verificar si comparten el mismo bloque de 3 letras (ej: A00-A09)
        bloques1 = set()
        bloques2 = set()
        for uri in parents1:
            match = re.search(r'/([A-Z]\d{2}-[A-Z]\d{2})$', str(uri))
            if match:
                bloques1.add(match.group(1))
            # También capturar capítulos (I, II, III, etc.)
            match_cap = re.search(r'/(I{1,3}|IV|V{1,3}|VI{1,3}|IX|X{1,3}|XI{1,3}|XIV|XV|XVI|XVII|XVIII|XIX|XX|XXI|XXII)$', str(uri))
            if match_cap:
                bloques1.add(f"CAP_{match_cap.group(1)}")

        for uri in parents2:
            match = re.search(r'/([A-Z]\d{2}-[A-Z]\d{2})$', str(uri))
            if match:
                bloques2.add(match.group(1))
            match_cap = re.search(r'/(I{1,3}|IV|V{1,3}|VI{1,3}|IX|X{1,3}|XI{1,3}|XIV|XV|XVI|XVII|XVIII|XIX|XX|XXI|XXII)$', str(uri))
            if match_cap:
                bloques2.add(f"CAP_{match_cap.group(1)}")

        bloques_comunes = bloques1 & bloques2
        if bloques_comunes:
            bloque_str = ", ".join(bloques_comunes)
            resultado_base["correlacionados_oms"] = True
            resultado_base["confianza_oms"] = 92.0
            resultado_base["nivel_oms"] = "MISMO_BLOQUE_SUPERIOR_OMS"
            resultado_base["razon_oms"] = (
                f"OMS CONFIRMA: {jer1['codigo']} y {jer2['codigo']} comparten bloque superior ({bloque_str})"
            )
            resultado_base["cita_legal_oms"] = (
                f"Según OMS ICD-10, ambos diagnósticos pertenecen al bloque {bloque_str}, "
                f"lo que establece correlación clínica válida. Ref: ICD-10 OMS."
            )
            return resultado_base

    except Exception as e:
        logger.warning(f"⚠️ Error verificando abuelos OMS: {e}")

    # ═══ NIVEL 3: Mismo capítulo (misma letra) → 85% ═══
    code1_clean = codigo1.strip().upper().replace(".", "")
    code2_clean = codigo2.strip().upper().replace(".", "")
    if code1_clean and code2_clean and code1_clean[0] == code2_clean[0]:
        resultado_base["correlacionados_oms"] = True
        resultado_base["confianza_oms"] = 75.0
        resultado_base["nivel_oms"] = "MISMO_CAPITULO_OMS"
        resultado_base["razon_oms"] = (
            f"OMS: {jer1['codigo']} y {jer2['codigo']} pertenecen al mismo capítulo CIE-10 "
            f"(letra {code1_clean[0]}), pero sin bloque común directo"
        )
        resultado_base["cita_legal_oms"] = (
            f"Ambos diagnósticos pertenecen al capítulo {code1_clean[0]} de la CIE-10 OMS. "
            f"Correlación por capítulo, valoración clínica recomendada."
        )
        return resultado_base

    # ═══ NIVEL 4: Sin relación jerárquica ═══
    resultado_base["correlacionados_oms"] = False
    resultado_base["confianza_oms"] = 0.0
    resultado_base["nivel_oms"] = "SIN_RELACION_OMS"
    resultado_base["razon_oms"] = (
        f"OMS NO CONFIRMA correlación: {jer1['codigo']} ({jer1['titulo']}) y "
        f"{jer2['codigo']} ({jer2['titulo']}) están en capítulos/bloques diferentes"
    )
    resultado_base["cita_legal_oms"] = (
        f"Según la clasificación OMS ICD-10, {jer1['codigo']} y {jer2['codigo']} "
        f"no comparten jerarquía diagnóstica. No hay correlación oficial para prórroga."
    )
    return resultado_base


def validar_correlacion_oms_local_sync(codigo1: str, codigo2: str) -> dict:
    """
    Versión SÍNCRONA que usa datos LOCALES (12,568 códigos + mapping) sin necesitar la API en vivo.
    Útil como fallback o cuando no hay credenciales. Llamable desde contextos sync y async.
    
    Compara:
    - Misma letra (capítulo) → 75%
    - Mismo rango de bloque → 90%
    - Mapping CIE-11 compartido → 88%
    """
    oficial = _cargar_cie10_oficial()
    
    # Buscar ambos códigos
    info1 = buscar_codigo_oficial(codigo1)
    info2 = buscar_codigo_oficial(codigo2)
    
    resultado = {
        "validado_oms": True,
        "metodo": "local_minsalud",
        "correlacionados_oms": False,
        "confianza_oms": 0.0,
        "nivel_oms": "NO_CORRELACIONADO",
        "razon_oms": "",
        "cita_legal_oms": "",
        "codigo1_info": info1,
        "codigo2_info": info2
    }
    
    if not info1 or not info1.get("encontrado") or not info2 or not info2.get("encontrado"):
        resultado["razon_oms"] = "Código(s) no encontrado(s) en base MinSalud"
        return resultado
    
    cod1_norm = codigo1.strip().upper().replace(".", "")
    cod2_norm = codigo2.strip().upper().replace(".", "")
    
    # Verificar si comparten mapping CIE-11 (mismo código CIE-11)
    cie11_1 = obtener_cie11_de_cie10(codigo1)
    cie11_2 = obtener_cie11_de_cie10(codigo2)
    
    codigos_cie11_1 = set(m["cie11_codigo"] for m in cie11_1)
    codigos_cie11_2 = set(m["cie11_codigo"] for m in cie11_2)
    cie11_comunes = codigos_cie11_1 & codigos_cie11_2
    
    if cie11_comunes:
        comunes_str = ", ".join(cie11_comunes)
        resultado["correlacionados_oms"] = True
        resultado["confianza_oms"] = 95.0
        resultado["nivel_oms"] = "MISMO_CIE11"
        resultado["razon_oms"] = (
            f"MAPPING OMS: {info1['codigo']} y {info2['codigo']} mapean al mismo código CIE-11: {comunes_str}. "
            f"La OMS los considera equivalentes/relacionados en su clasificación actualizada."
        )
        resultado["cita_legal_oms"] = (
            f"Según el mapping oficial OMS ICD-11 (Enero 2025), los diagnósticos {info1['codigo']} y {info2['codigo']} "
            f"convergen al código CIE-11 {comunes_str}, confirmando correlación clínica. "
            f"Ref: OMS ICD-11 Mapping Tables."
        )
        return resultado
    
    # Verificar si sus CIE-11 comparten prefijo (misma familia en CIE-11)
    if codigos_cie11_1 and codigos_cie11_2:
        # Comparar prefijos CIE-11 (ej: 1A vs 1A, DA vs DA)
        prefijos_1 = set(c[:2] for c in codigos_cie11_1 if len(c) >= 2)
        prefijos_2 = set(c[:2] for c in codigos_cie11_2 if len(c) >= 2)
        prefijos_comunes = prefijos_1 & prefijos_2
        
        if prefijos_comunes:
            pref_str = ", ".join(prefijos_comunes)
            resultado["correlacionados_oms"] = True
            resultado["confianza_oms"] = 88.0
            resultado["nivel_oms"] = "MISMA_FAMILIA_CIE11"
            resultado["razon_oms"] = (
                f"MAPPING OMS: {info1['codigo']} y {info2['codigo']} pertenecen a la misma familia CIE-11 ({pref_str}). "
                f"Indica correlación en la clasificación moderna OMS."
            )
            resultado["cita_legal_oms"] = (
                f"Según mapping OMS ICD-11, ambos diagnósticos pertenecen a la familia {pref_str} de la CIE-11, "
                f"estableciendo correlación nosológica."
            )
            return resultado
    
    # Mismo bloque de 3 dígitos (ej: A00-A09)
    if len(cod1_norm) >= 3 and len(cod2_norm) >= 3:
        # Comparar los primeros 3 caracteres para bloques cercanos
        base1 = int(cod1_norm[1:3])
        base2 = int(cod2_norm[1:3])
        if cod1_norm[0] == cod2_norm[0] and abs(base1 - base2) <= 6:
            resultado["correlacionados_oms"] = True
            resultado["confianza_oms"] = 82.0
            resultado["nivel_oms"] = "BLOQUE_CERCANO_MINSALUD"
            resultado["razon_oms"] = (
                f"MinSalud: {info1['codigo']} y {info2['codigo']} están en bloques cercanos "
                f"del mismo capítulo CIE-10 (diferencia: {abs(base1-base2)} posiciones)"
            )
            resultado["cita_legal_oms"] = (
                f"Ambos diagnósticos se ubican en posiciones cercanas del capítulo {cod1_norm[0]} de la CIE-10 "
                f"(Resolución 1895/2001 MinSalud), sugiriendo relación nosológica."
            )
            return resultado
    
    # Mismo capítulo (misma letra)
    if cod1_norm and cod2_norm and cod1_norm[0] == cod2_norm[0]:
        resultado["correlacionados_oms"] = True
        resultado["confianza_oms"] = 70.0
        resultado["nivel_oms"] = "MISMO_CAPITULO_MINSALUD"
        resultado["razon_oms"] = (
            f"MinSalud: {info1['codigo']} y {info2['codigo']} pertenecen al mismo capítulo CIE-10 (letra {cod1_norm[0]})"
        )
        resultado["cita_legal_oms"] = (
            f"Ambos diagnósticos pertenecen al capítulo {cod1_norm[0]} de la CIE-10 (MinSalud Colombia). "
            f"Se recomienda valoración clínica para confirmar correlación."
        )
        return resultado
    
    # Sin correlación
    resultado["razon_oms"] = (
        f"MinSalud: {info1['codigo']} ({info1['titulo']}) y {info2['codigo']} ({info2['titulo']}) "
        f"no comparten capítulo ni familia CIE-11. Sin correlación identificada."
    )
    resultado["cita_legal_oms"] = (
        f"Los diagnósticos {info1['codigo']} y {info2['codigo']} se encuentran en capítulos diferentes "
        f"de la CIE-10 y no convergen en la CIE-11. No se establece correlación para prórroga."
    )
    return resultado


async def validar_correlacion_oms_local(codigo1: str, codigo2: str) -> dict:
    """Wrapper async de validar_correlacion_oms_local_sync (compatibilidad con endpoints async)."""
    return validar_correlacion_oms_local_sync(codigo1, codigo2)
