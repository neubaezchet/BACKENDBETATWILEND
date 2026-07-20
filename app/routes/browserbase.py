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
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
import logging

from app.services import browserbase_service as bb
from app.services.browserbase_service import (
    BrowserbaseError, TERMINAL_STATUSES, PROXY_COLOMBIA,
)
from app.database import get_db, EmpresaBotConfig
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


# ──────────────────────────────────────────────
#  SESIÓN GUARDADA POR BOT (contexts por EPS/empresa)
#  Flujo: login → el admin inicia sesión en el portal desde el live view →
#  finalizar → las cookies quedan guardadas y todos los runs futuros entran logueados.
# ──────────────────────────────────────────────

def _get_bot(db: Session, bot_id: int) -> EmpresaBotConfig:
    bot = db.query(EmpresaBotConfig).filter(EmpresaBotConfig.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail=f"Bot config {bot_id} no encontrado")
    return bot


@router.get("/bots/{bot_id}/sesion")
async def estado_sesion_bot(bot_id: int, db: Session = Depends(get_db)):
    """Estado de la sesión guardada (context) de un bot: si existe, último login, login en curso."""
    bot = _get_bot(db, bot_id)
    login_activo = None
    if bot.context_login_session:
        try:
            ses = await bb.get_session(bot.context_login_session)
            if ses.get("status") == "RUNNING":
                urls = await bb.get_live_view_urls(bot.context_login_session)
                login_activo = {
                    "sessionId": bot.context_login_session,
                    "liveViewUrl": urls.get("debuggerFullscreenUrl"),
                }
            else:
                bot.context_login_session = None
                db.commit()
        except BrowserbaseError:
            bot.context_login_session = None
            db.commit()
    return {
        "bot_id": bot.id,
        "empresa": bot.nombre_empresa,
        "bot_nombre": bot.bot_nombre,
        "tiene_sesion_guardada": bool(bot.browserbase_context_id),
        "context_id": bot.browserbase_context_id,
        "ultimo_login": bot.context_ultimo_login.isoformat() if bot.context_ultimo_login else None,
        "login_en_curso": login_activo,
    }


@router.post("/bots/{bot_id}/sesion/login")
async def iniciar_login_bot(bot_id: int, db: Session = Depends(get_db)):
    """
    Abre un navegador cloud con el context del bot para hacer login manual.
    Devuelve liveViewUrl para embeber en iframe. Si ya hay un login en curso,
    devuelve esa misma sesión (evita logins simultáneos que invalidan cookies).
    """
    bot = _get_bot(db, bot_id)
    try:
        # Reusar sesión de login abierta si sigue viva
        if bot.context_login_session:
            try:
                ses = await bb.get_session(bot.context_login_session)
                if ses.get("status") == "RUNNING":
                    urls = await bb.get_live_view_urls(bot.context_login_session)
                    return {
                        "sessionId": bot.context_login_session,
                        "liveViewUrl": urls.get("debuggerFullscreenUrl"),
                        "reusada": True,
                    }
            except BrowserbaseError:
                pass  # sesión vieja muerta — crear una nueva

        # Crear context si el bot aún no tiene
        if not bot.browserbase_context_id:
            ctx = await bb.create_context()
            bot.browserbase_context_id = ctx["id"]
            db.commit()
            logger.info(f"🔑 Context creado para bot {bot.nombre_empresa}/{bot.bot_nombre}: {ctx['id']}")

        # Sesión de login: keep_alive para que sobreviva mientras el admin escribe,
        # timeout 15 min como tope de seguridad, proxy Colombia para geolocalización consistente
        ses = await bb.create_session(
            context_id=bot.browserbase_context_id,
            persist=True,
            keep_alive=True,
            timeout=900,
            proxies=PROXY_COLOMBIA,
            user_metadata={"tipo": "login-manual", "empresa": bot.nombre_empresa, "bot": bot.bot_nombre},
        )
        bot.context_login_session = ses["id"]
        db.commit()

        urls = await bb.get_live_view_urls(ses["id"])
        return {
            "sessionId": ses["id"],
            "liveViewUrl": urls.get("debuggerFullscreenUrl"),
            "reusada": False,
        }
    except BrowserbaseError as e:
        raise _http_error(e)


@router.post("/bots/{bot_id}/sesion/login/finalizar")
async def finalizar_login_bot(bot_id: int, db: Session = Depends(get_db)):
    """
    Cierra la sesión de login. Al cerrarse, Browserbase persiste las cookies
    en el context — desde este momento los bots entran ya logueados.
    """
    bot = _get_bot(db, bot_id)
    if not bot.context_login_session:
        raise HTTPException(status_code=400, detail="No hay sesión de login en curso para este bot")
    try:
        await bb.release_session(bot.context_login_session)
    except BrowserbaseError as e:
        # Si ya estaba cerrada seguimos — lo importante es registrar el login
        logger.warning(f"release_session: {e}")
    bot.context_login_session = None
    bot.context_ultimo_login = datetime.utcnow()
    db.commit()
    return {
        "ok": True,
        "mensaje": "Sesión guardada. Los próximos bots entrarán logueados automáticamente.",
        "ultimo_login": bot.context_ultimo_login.isoformat(),
    }


@router.delete("/bots/{bot_id}/sesion")
async def eliminar_sesion_bot(bot_id: int, db: Session = Depends(get_db)):
    """Elimina la sesión guardada (context) del bot — borra cookies/login almacenados."""
    bot = _get_bot(db, bot_id)
    if not bot.browserbase_context_id:
        raise HTTPException(status_code=400, detail="Este bot no tiene sesión guardada")
    try:
        await bb.delete_context(bot.browserbase_context_id)
    except BrowserbaseError as e:
        if e.status_code != 404:  # si ya no existe en Browserbase, solo limpiamos la referencia
            raise _http_error(e)
    bot.browserbase_context_id = None
    bot.context_ultimo_login = None
    bot.context_login_session = None
    db.commit()
    return {"ok": True, "mensaje": "Sesión guardada eliminada"}


# ──────────────────────────────────────────────
#  RADICACIÓN — run enriquecido y robusto para uso masivo
# ──────────────────────────────────────────────

# Resultado estándar de una radicación (el agente SIEMPRE responde este JSON)
RESULT_SCHEMA_RADICACION = {
    "type": "object",
    "properties": {
        "exito": {"type": "boolean", "description": "true si la radicación se completó"},
        "numero_radicado": {"type": "string", "description": "Número o serial de radicado devuelto por el portal, vacío si no aplica"},
        "mensaje": {"type": "string", "description": "Resumen corto de lo ocurrido o del error encontrado"},
        "paso_fallido": {"type": "string", "description": "Si falló: en qué paso exacto se detuvo (ej. 'login', 'formulario', 'adjuntar PDF')"},
    },
    "required": ["exito", "mensaje"],
}


# Agentes reutilizables por bot (system prompt probado + result schema fijos en Browserbase).
# Si el request no trae agent_id, se usa el del bot correspondiente.
AGENTES_POR_BOT = {
    "compensar": "82ccb16d-1776-4ee2-8e7b-227cb033a0db",  # Compensar - Radicación de Incapacidades
}


class RadicarRequest(BaseModel):
    bot_id: int                                # empresa_bot_config.id — de ahí salen context y credenciales
    task: str                                  # instrucción; puede usar %usuario%, %clave%, etc.
    variables: Optional[dict] = None           # variables adicionales (cedula, fechas, urls de PDFs…)
    result_schema: Optional[dict] = None       # override del schema de resultado
    agent_id: Optional[str] = None             # agente reutilizable (system prompt fijo)
    timeout_extra: Optional[dict] = None       # reservado para ajustes futuros


@router.post("/radicar")
async def radicar(req: RadicarRequest, db: Session = Depends(get_db)):
    """
    Lanza un run de radicación con la configuración robusta completa:
    - Context del bot (entra logueado si ya se guardó sesión)
    - Credenciales del bot inyectadas como variables %usuario%, %clave%… (nunca inline en el prompt)
    - Proxy activado + CAPTCHAs y grabación (defaults del runner de Browserbase)
    - Schema de resultado estándar: exito / numero_radicado / mensaje / paso_fallido
    """
    bot = _get_bot(db, req.bot_id)
    if bot.estado not in ("activo", "configuracion"):
        raise HTTPException(status_code=400, detail=f"El bot está '{bot.estado}' — no se puede radicar")

    # Credenciales del bot → variables del run (el valor no aparece en el prompt)
    variables: dict = {}
    for key, value in (bot.credenciales or {}).items():
        if value:
            variables[key] = {
                "value": str(value),
                "description": f"Credencial '{key}' del portal {bot.bot_nombre} — usar cuando el sitio la pida",
            }
    if req.variables:
        for key, value in req.variables.items():
            variables[key] = value if isinstance(value, dict) else {"value": str(value)}

    # Nota: en runs de agente browserSettings SOLO acepta context, proxies (bool) y verified.
    # CAPTCHAs, grabación y demás los aplica el runner por defecto.
    browser_settings: dict = {"proxies": True}
    if bot.browserbase_context_id:
        browser_settings["context"] = {"id": bot.browserbase_context_id, "persist": True}

    try:
        run = await bb.create_run(
            task=req.task,
            agent_id=req.agent_id or AGENTES_POR_BOT.get(bot.bot_nombre),
            variables=variables or None,
            result_schema=req.result_schema or RESULT_SCHEMA_RADICACION,
            browser_settings=browser_settings,
        )
        logger.info(f"🚀 Radicación lanzada — bot {bot.nombre_empresa}/{bot.bot_nombre} → run {run.get('runId')}")
        return {
            **run,
            "bot_id": bot.id,
            "empresa": bot.nombre_empresa,
            "bot_nombre": bot.bot_nombre,
            "con_sesion_guardada": bool(bot.browserbase_context_id),
        }
    except BrowserbaseError as e:
        raise _http_error(e)


# ──────────────────────────────────────────────
#  COLA — disparo manual del dispatcher (útil para pruebas)
# ──────────────────────────────────────────────

@router.post("/cola/procesar")
async def procesar_cola_manual():
    """
    Ejecuta un ciclo del dispatcher inmediatamente:
    sincroniza runs activos y lanza los ítems pendientes de la cola.
    (El scheduler lo hace automáticamente cada minuto.)
    """
    from app.services.radicacion_dispatcher import ciclo_dispatcher
    return await ciclo_dispatcher()


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
