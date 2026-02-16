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
