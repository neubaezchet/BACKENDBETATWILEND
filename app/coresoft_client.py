# -*- coding: utf-8 -*-
"""
✅ Cliente CoreSoft — consultas oficiales sobre datos colombianos (ADRES/BDUA,
créditos de la cuenta, etc.)

Usado para la verificación mensual de EPS de empleados activos.
Ver app/tasks/scheduler_tasks.py → tarea_actualizar_eps_mensual.

Docs: https://coresoft.solutions/docs — auth por header X-API-Key, todas las
peticiones son GET con parámetros en la URL (no POST, no JSON body).

Fail-safe: ninguna función de este módulo lanza excepción por errores de red,
HTTP o de negocio (401/404/429/500) — siempre devuelve None y registra el
motivo, para que un fallo puntual de CoreSoft nunca interrumpa el ciclo mensual.
"""

import os
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

CORESOFT_BASE_URL = os.getenv("CORESOFT_BASE_URL", "https://coresoft.solutions/api")
CORESOFT_API_KEY = os.getenv("CORESOFT_API_KEY", "")

# Límite documentado por CoreSoft (plan actual): 30 consultas/minuto
CORESOFT_CONSULTAS_POR_MINUTO = 30


def _headers() -> Optional[dict]:
    if not CORESOFT_API_KEY:
        logger.error("❌ CORESOFT_API_KEY no está configurada en las variables de entorno")
        return None
    return {"X-API-Key": CORESOFT_API_KEY}


def consultar_creditos() -> Optional[dict]:
    """
    GET /api/cuenta — gratis, no descuenta créditos ni cuenta contra el límite
    por minuto. Devuelve el dict 'creditos' o None si la consulta falla.
    """
    headers = _headers()
    if headers is None:
        return None
    try:
        with httpx.Client(base_url=CORESOFT_BASE_URL, timeout=20.0) as client:
            resp = client.get("/cuenta", headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data.get("creditos")
    except Exception as e:
        logger.warning(f"⚠️ CoreSoft /cuenta falló: {e}")
        return None


def consultar_eps(documento: str, tipo_doc: str = "CC") -> Optional[dict]:
    """
    GET /api/adres — afiliación EPS/BDUA de una persona por documento.
    Devuelve el dict 'resultado' de la respuesta (afiliado, eps, regimen,
    estado, tipo_afiliado, fecha_afiliacion, ...) o None si no se pudo
    resolver (documento no encontrado, sin créditos, rate limit, timeout, etc.)
    Costo: 2 créditos por consulta exitosa.
    """
    headers = _headers()
    if headers is None:
        return None

    try:
        with httpx.Client(base_url=CORESOFT_BASE_URL, timeout=30.0) as client:
            resp = client.get(
                "/adres",
                headers=headers,
                params={"documento": documento, "tipoDoc": tipo_doc},
            )
    except httpx.TimeoutException:
        logger.warning(f"⚠️ CoreSoft: timeout consultando documento {documento}")
        return None
    except Exception as e:
        logger.warning(f"⚠️ CoreSoft: error de red consultando {documento}: {e}")
        return None

    if resp.status_code == 401:
        logger.error("❌ CoreSoft: API Key inválida o sin créditos disponibles (401)")
        return None
    if resp.status_code == 429:
        logger.warning(f"⚠️ CoreSoft: límite de consultas/min alcanzado (429) en documento {documento}")
        return None
    if resp.status_code == 404:
        logger.info(f"ℹ️ CoreSoft: documento {documento} no encontrado (404)")
        return None
    if resp.status_code != 200:
        logger.warning(f"⚠️ CoreSoft: respuesta {resp.status_code} consultando {documento}: {resp.text[:300]}")
        return None

    try:
        data = resp.json()
    except Exception as e:
        logger.warning(f"⚠️ CoreSoft: respuesta no-JSON para {documento}: {e}")
        return None

    if not data.get("success"):
        logger.warning(f"⚠️ CoreSoft: success=false para {documento}: {data}")
        return None

    return data.get("resultado")
