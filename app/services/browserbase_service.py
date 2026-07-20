"""
✅ Servicio de integración con Browserbase Agents API
Ejecuta agentes de navegador autónomos en la nube de Browserbase.

Flujo:
  1. create_run(task) → Browserbase lanza un navegador cloud y un agente que ejecuta la tarea
  2. get_run(run_id)  → polling hasta estado terminal (COMPLETED/FAILED/STOPPED/TIMED_OUT)
  3. run["result"]    → resultado estructurado (según result_schema si se definió)
  4. get_live_view_urls(session_id) → URL embebible (iframe) para ver el navegador en vivo

Docs locales: browserbase-docs/ (spec OpenAPI + páginas markdown)
API: https://api.browserbase.com — auth por header X-BB-API-Key
"""

import os
import logging
from typing import Optional, Any

import httpx

logger = logging.getLogger(__name__)

BROWSERBASE_API_URL = "https://api.browserbase.com"
BROWSERBASE_API_KEY = os.getenv("BROWSERBASE_API_KEY", "")
BROWSERBASE_PROJECT_ID = os.getenv("BROWSERBASE_PROJECT_ID", "")

# Estados terminales de un run
TERMINAL_STATUSES = {"COMPLETED", "FAILED", "STOPPED", "TIMED_OUT"}


class BrowserbaseError(Exception):
    """Error devuelto por la API de Browserbase."""

    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Browserbase API error {status_code}: {detail}")


def _headers(with_body: bool) -> dict:
    if not BROWSERBASE_API_KEY:
        raise BrowserbaseError(500, "BROWSERBASE_API_KEY no está configurada en las variables de entorno")
    headers = {"X-BB-API-Key": BROWSERBASE_API_KEY}
    if with_body:
        headers["Content-Type"] = "application/json"
    return headers


async def _request(method: str, path: str, json: Optional[dict] = None, params: Optional[dict] = None) -> dict:
    async with httpx.AsyncClient(base_url=BROWSERBASE_API_URL, timeout=60.0) as client:
        resp = await client.request(method, path, headers=_headers(json is not None), json=json, params=params)
    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        logger.error(f"❌ Browserbase {method} {path} → {resp.status_code}: {detail}")
        raise BrowserbaseError(resp.status_code, detail)
    if not resp.content:
        return {}
    return resp.json()


# ──────────────────────────────────────────────
#  AGENTS (configuración reutilizable)
# ──────────────────────────────────────────────

async def create_agent(name: str, system_prompt: Optional[str] = None,
                       result_schema: Optional[dict] = None) -> dict:
    """Crea un agente reutilizable con system prompt y schema de resultado."""
    body: dict = {"name": name}
    if system_prompt:
        body["systemPrompt"] = system_prompt
    if result_schema:
        body["resultSchema"] = result_schema
    return await _request("POST", "/v1/agents", json=body)


async def list_agents(limit: int = 20, cursor: Optional[str] = None) -> dict:
    params: dict = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    return await _request("GET", "/v1/agents", params=params)


async def get_agent(agent_id: str) -> dict:
    return await _request("GET", f"/v1/agents/{agent_id}")


async def delete_agent(agent_id: str) -> dict:
    return await _request("DELETE", f"/v1/agents/{agent_id}")


# ──────────────────────────────────────────────
#  RUNS (ejecuciones de tareas)
# ──────────────────────────────────────────────

async def create_run(task: str,
                     agent_id: Optional[str] = None,
                     variables: Optional[dict] = None,
                     result_schema: Optional[dict] = None,
                     browser_settings: Optional[dict] = None) -> dict:
    """
    Lanza un run asíncrono. Devuelve {"agentId": ..., "runId": ..., "status": "PENDING", ...}.
    - task: instrucción en lenguaje natural (soporta placeholders %variable%)
    - variables: {"nombre": {"value": "...", "description": "..."}}
    - browser_settings: ej. {"proxies": True, "solveCaptchas": True, "context": {"id": "...", "persist": True}}
    """
    body: dict = {"task": task}
    if agent_id:
        body["agentId"] = agent_id
    if variables:
        body["variables"] = variables
    if result_schema:
        body["resultSchema"] = result_schema
    if browser_settings:
        body["browserSettings"] = browser_settings
    logger.info(f"🚀 Browserbase: creando run — task: {task[:80]}...")
    return await _request("POST", "/v1/agents/runs", json=body)


async def get_run(run_id: str) -> dict:
    """Estado actual del run. Incluye sessionId, result (si terminó) y cause (si falló)."""
    return await _request("GET", f"/v1/agents/runs/{run_id}")


async def list_runs(agent_id: Optional[str] = None, status: Optional[str] = None,
                    limit: int = 20, cursor: Optional[str] = None) -> dict:
    params: dict = {"limit": limit}
    if agent_id:
        params["agentId"] = agent_id
    if status:
        params["status"] = status
    if cursor:
        params["cursor"] = cursor
    return await _request("GET", "/v1/agents/runs", params=params)


async def list_run_messages(run_id: str, since: Optional[str] = None, limit: int = 100) -> dict:
    """Transcript paso a paso del agente. Usa nextSince → since para paginación incremental."""
    params: dict = {"limit": limit}
    if since:
        params["since"] = since
    return await _request("GET", f"/v1/agents/runs/{run_id}/messages", params=params)


async def stop_run(run_id: str) -> dict:
    return await _request("POST", f"/v1/agents/runs/{run_id}/stop")


# ──────────────────────────────────────────────
#  CONTEXTS (persistencia de sesión/credenciales)
#  Un context guarda cookies, tokens y localStorage entre sesiones.
#  Best practice Browserbase: un context por sitio + login.
# ──────────────────────────────────────────────

async def create_context() -> dict:
    """Crea un context vacío. Devuelve {'id': ...}. El project se infiere de la API key."""
    body = {"projectId": BROWSERBASE_PROJECT_ID} if BROWSERBASE_PROJECT_ID else {}
    return await _request("POST", "/v1/contexts", json=body)


async def get_context(context_id: str) -> dict:
    return await _request("GET", f"/v1/contexts/{context_id}")


async def delete_context(context_id: str) -> dict:
    """Elimina un context permanentemente (borra la sesión/login guardado)."""
    return await _request("DELETE", f"/v1/contexts/{context_id}")


# ──────────────────────────────────────────────
#  SESIONES (navegador directo — para login manual y observabilidad)
# ──────────────────────────────────────────────

async def create_session(context_id: Optional[str] = None,
                         persist: bool = True,
                         keep_alive: bool = True,
                         timeout: int = 900,
                         proxies: Optional[Any] = None,
                         user_metadata: Optional[dict] = None,
                         browser_settings_extra: Optional[dict] = None) -> dict:
    """
    Crea una sesión de navegador (sin agente). Se usa para el flujo de
    login manual: el admin abre el live view, inicia sesión en el portal
    de la EPS y el context guarda las cookies al cerrar.
    """
    browser_settings: dict = {"solveCaptchas": True, "blockAds": True}
    if context_id:
        browser_settings["context"] = {"id": context_id, "persist": persist}
    if browser_settings_extra:
        browser_settings.update(browser_settings_extra)

    body: dict = {
        "browserSettings": browser_settings,
        "keepAlive": keep_alive,
        "timeout": timeout,
    }
    if BROWSERBASE_PROJECT_ID:
        body["projectId"] = BROWSERBASE_PROJECT_ID
    if proxies is not None:
        body["proxies"] = proxies
    if user_metadata:
        body["userMetadata"] = user_metadata
    return await _request("POST", "/v1/sessions", json=body)


async def release_session(session_id: str) -> dict:
    """
    Cierra la sesión de forma limpia (REQUEST_RELEASE). Importante:
    dispara la persistencia del context y evita cobrar minutos de más.
    """
    return await _request("POST", f"/v1/sessions/{session_id}",
                          json={"status": "REQUEST_RELEASE"})


async def get_live_view_urls(session_id: str) -> dict:
    """
    URLs para ver el navegador en tiempo real.
    debuggerFullscreenUrl se puede embeber en un <iframe> del frontend.
    """
    return await _request("GET", f"/v1/sessions/{session_id}/debug")


async def get_session(session_id: str) -> dict:
    return await _request("GET", f"/v1/sessions/{session_id}")


# ──────────────────────────────────────────────
#  HELPERS DE RADICACIÓN
# ──────────────────────────────────────────────

# Proxy Browserbase con geolocalización Colombia — consistencia de ubicación
# para que los portales EPS no invaliden la sesión guardada del context.
PROXY_COLOMBIA = [{"type": "browserbase", "geolocation": {"country": "CO"}}]
