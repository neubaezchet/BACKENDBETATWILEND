"""
✅ Rutas para Browserbase Agents API
El frontend llama a estos endpoints; el backend guarda la API key y hace proxy
hacia https://api.browserbase.com. Así la key nunca se expone en el navegador.

Flujo típico desde la web:
  1. POST /api/browserbase/runs            → lanza la tarea, devuelve run_id
  2. GET  /api/browserbase/runs/{run_id}   → polling cada 2-3s hasta estado terminal
  3. GET  /api/browserbase/runs/{run_id}/live → URL para <iframe> con el navegador en vivo
  4. run.result → resultado estructurado cuando status == COMPLETED
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
import logging

from app.services import browserbase_service as bb
from app.services.browserbase_service import BrowserbaseError, TERMINAL_STATUSES
from app.routes.admin import get_current_user  # 🔒 mismo JWT del portal admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/browserbase", tags=["Browserbase"],
                   dependencies=[Depends(get_current_user)])


# ──────────────────────────────────────────────
#  MODELOS PYDANTIC
# ──────────────────────────────────────────────

class CrearAgenteRequest(BaseModel):
    name: str
    system_prompt: Optional[str] = None
    result_schema: Optional[dict] = None


class CrearRunRequest(BaseModel):
    task: str
    agent_id: Optional[str] = None
    variables: Optional[dict] = None
    result_schema: Optional[dict] = None
    browser_settings: Optional[dict] = None


def _http_error(e: BrowserbaseError) -> HTTPException:
    return HTTPException(status_code=e.status_code if 400 <= e.status_code < 600 else 502,
                         detail=e.detail)


# ──────────────────────────────────────────────
#  AGENTES
# ──────────────────────────────────────────────

@router.post("/agents")
async def crear_agente(req: CrearAgenteRequest):
    """Crea un agente reutilizable (system prompt + schema de resultado)."""
    try:
        return await bb.create_agent(req.name, req.system_prompt, req.result_schema)
    except BrowserbaseError as e:
        raise _http_error(e)


@router.get("/agents")
async def listar_agentes(limit: int = Query(20, le=100), cursor: Optional[str] = None):
    try:
        return await bb.list_agents(limit=limit, cursor=cursor)
    except BrowserbaseError as e:
        raise _http_error(e)


# ──────────────────────────────────────────────
#  RUNS
# ──────────────────────────────────────────────

@router.post("/runs")
async def crear_run(req: CrearRunRequest):
    """
    Lanza una tarea en un navegador cloud de Browserbase.
    Respuesta inmediata con runId (el run es asíncrono — hacer polling con GET /runs/{run_id}).
    """
    try:
        return await bb.create_run(
            task=req.task,
            agent_id=req.agent_id,
            variables=req.variables,
            result_schema=req.result_schema,
            browser_settings=req.browser_settings,
        )
    except BrowserbaseError as e:
        raise _http_error(e)


@router.get("/runs")
async def listar_runs(agent_id: Optional[str] = None,
                      status: Optional[str] = None,
                      limit: int = Query(20, le=100),
                      cursor: Optional[str] = None):
    try:
        return await bb.list_runs(agent_id=agent_id, status=status, limit=limit, cursor=cursor)
    except BrowserbaseError as e:
        raise _http_error(e)


@router.get("/runs/{run_id}")
async def obtener_run(run_id: str):
    """Estado del run. Cuando status ∈ {COMPLETED, FAILED, STOPPED, TIMED_OUT} incluye result/cause."""
    try:
        run = await bb.get_run(run_id)
        run["is_terminal"] = run.get("status") in TERMINAL_STATUSES
        return run
    except BrowserbaseError as e:
        raise _http_error(e)


@router.get("/runs/{run_id}/messages")
async def mensajes_run(run_id: str, since: Optional[str] = None, limit: int = Query(100, le=200)):
    """Transcript paso a paso (lo que el agente va haciendo). Pasar nextSince como since para incrementales."""
    try:
        return await bb.list_run_messages(run_id, since=since, limit=limit)
    except BrowserbaseError as e:
        raise _http_error(e)


@router.post("/runs/{run_id}/stop")
async def detener_run(run_id: str):
    try:
        return await bb.stop_run(run_id)
    except BrowserbaseError as e:
        raise _http_error(e)


@router.get("/runs/{run_id}/live")
async def live_view_run(run_id: str):
    """
    Devuelve la URL del navegador en vivo para embeber en un <iframe> del frontend.
    Solo disponible mientras el run está activo y ya tiene sesión asignada.
    """
    try:
        run = await bb.get_run(run_id)
        session_id = run.get("sessionId")
        if not session_id:
            raise HTTPException(status_code=404, detail="El run aún no tiene sesión de navegador asignada")
        urls = await bb.get_live_view_urls(session_id)
        return {
            "sessionId": session_id,
            "status": run.get("status"),
            "liveViewUrl": urls.get("debuggerFullscreenUrl"),
            "pages": urls.get("pages", []),
            "replayUrl": f"https://browserbase.com/sessions/{session_id}",
        }
    except BrowserbaseError as e:
        raise _http_error(e)
