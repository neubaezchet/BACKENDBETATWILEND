"""
✅ Dispatcher de radicación — Browserbase
Reemplaza el ciclo que hacía browser-use:

  RadicacionCola (pendiente) ──despachar──▶ run en Browserbase (agente cloud)
  run terminado ──sincronizar──▶ RadicacionSesion + RadicacionCola (backoff) + RadicacionSkill

Corre automáticamente desde el scheduler (cada minuto) y también se puede
disparar manualmente vía POST /api/browserbase/cola/procesar.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.database import (
    SessionLocal, RadicacionCola, RadicacionSesion, RadicacionSkill, EmpresaBotConfig,
)
from app.services import browserbase_service as bb
from app.services.browserbase_service import BrowserbaseError

logger = logging.getLogger(__name__)

# Máximo de runs lanzados por ciclo (control de costos y de carga)
MAX_RUNS_POR_CICLO = 3
_MAX_INTENTOS = 12

# Resultado estándar que exige el agente
RESULT_SCHEMA_RADICACION = {
    "type": "object",
    "properties": {
        "exito": {"type": "boolean"},
        "numero_radicado": {"type": "string"},
        "fecha_radicacion": {"type": "string"},
        "estado_portal": {"type": "string", "description": "Estado textual que mostró el portal (ej. 'Radicación Exitosa', 'Rechazada', 'En validación')"},
        "observacion": {"type": "string", "description": "Observación completa del portal tras radicar (éxito o rechazo)"},
        "motivo_rechazo": {"type": "string", "description": "SOLO si el portal RECHAZÓ la radicación: motivo textual exacto (duplicada, datos inválidos, peso excedido...)"},
        "peso_maximo_pdf_mb": {"type": "number", "description": "SOLO si el portal mostró o exigió un límite de peso del PDF en MB (ej. rechazo por archivo muy pesado)"},
        "mensaje": {"type": "string"},
        "paso_fallido": {"type": "string"},
    },
    "required": ["exito", "mensaje"],
}


def _calcular_proximo_intento(intentos: int) -> datetime:
    """Backoff escalado (mismo esquema documentado en RadicacionCola)."""
    ahora = datetime.utcnow()
    if intentos <= 2:
        return ahora + timedelta(minutes=5)
    if intentos <= 4:
        return ahora + timedelta(minutes=20)
    if intentos <= 6:
        return ahora + timedelta(hours=1)
    if intentos <= 8:
        return ahora + timedelta(hours=4)
    # 9+ → mañana 8 am Colombia (UTC-5 → 13:00 UTC)
    manana = (ahora + timedelta(days=1)).replace(hour=13, minute=0, second=0, microsecond=0)
    return manana


def _agregar_historial(item: RadicacionCola, error: Optional[str], ts: datetime):
    historial = list(item.historial_errores or [])
    historial.append({"intento": item.intentos, "error": (error or "")[:500], "ts": ts.isoformat()})
    item.historial_errores = historial[-20:]  # conservar los últimos 20


def _buscar_bot(db: Session, empresa: str, eps_key: str) -> Optional[EmpresaBotConfig]:
    return db.query(EmpresaBotConfig).filter(
        EmpresaBotConfig.nombre_empresa == empresa,
        EmpresaBotConfig.bot_nombre == eps_key,
    ).first()


# ──────────────────────────────────────────────
#  AUTO-ENCOLADO desde repogemin (subir-incapacidad)
# ──────────────────────────────────────────────

def _mapear_eps_a_bot(db: Session, empresa: str, eps_texto: str) -> Optional[EmpresaBotConfig]:
    """
    Mapea el texto libre de EPS del empleado (ej. 'COMPENSAR E.P.S.', 'EPS SURA')
    al bot configurado de esa empresa (bot_nombre: compensar, sura_eps, ...).
    """
    if not eps_texto:
        return None
    eps_norm = eps_texto.lower().replace(".", "").replace("-", " ")
    bots = db.query(EmpresaBotConfig).filter(
        EmpresaBotConfig.nombre_empresa == empresa,
        EmpresaBotConfig.estado.in_(["activo", "configuracion"]),
    ).all()
    for bot in bots:
        # 'sura_eps' → raíces ['sura', 'eps']; con que la raíz principal esté en el texto basta
        raiz = bot.bot_nombre.split("_")[0]
        if raiz and raiz in eps_norm:
            return bot
    return None


def encolar_caso(db: Session, caso) -> Optional[int]:
    """
    Encola automáticamente la radicación de un caso recién creado desde repogemin.
    Solo encola si la empresa tiene un bot configurado para la EPS del empleado.
    Devuelve el id del ítem de cola, o None si no aplica.
    Nunca lanza excepción (no debe romper el flujo de recepción).
    """
    try:
        empresa_nombre = caso.empresa.nombre if getattr(caso, "empresa", None) else None
        if not empresa_nombre or not caso.drive_link:
            return None

        # Prioridad de EPS: 1) la que indica la incapacidad (OCR/Gemini)  2) la de la BD del empleado.
        # (El documento manda: es la EPS donde el médico emitió la incapacidad.)
        meta_pre = caso.metadata_form or {}
        eps_ocr = ((meta_pre.get("plano") or {}).get("eps") or "").strip()
        eps_bd = (caso.eps or "").strip()

        bot = None
        eps_usada, fuente_eps = None, None
        if eps_ocr:
            bot = _mapear_eps_a_bot(db, empresa_nombre, eps_ocr)
            if bot:
                eps_usada, fuente_eps = eps_ocr, "ocr"
        if not bot and eps_bd:
            bot = _mapear_eps_a_bot(db, empresa_nombre, eps_bd)
            if bot:
                eps_usada, fuente_eps = eps_bd, "base_datos"
        if not bot:
            logger.info(
                f"[Encolar] Caso {caso.serial}: sin bot para EPS "
                f"(OCR: '{eps_ocr or '—'}' / BD: '{eps_bd or '—'}') en '{empresa_nombre}' — flujo manual"
            )
            return None
        logger.info(f"[Encolar] Caso {caso.serial}: EPS '{eps_usada}' (fuente: {fuente_eps}) → bot '{bot.bot_nombre}'")

        # Evitar duplicados: no encolar si ya hay ítem activo para este caso
        existente = db.query(RadicacionCola).filter(
            RadicacionCola.case_id == caso.id,
            RadicacionCola.estado.in_(["pendiente", "procesando", "fallo_temporal"]),
        ).first()
        if existente:
            return existente.id

        meta = caso.metadata_form or {}
        plano = meta.get("plano") or {}
        datos_ocr = {
            "cedula": caso.cedula,
            "tipo_doc_trabajador": plano.get("tipo_doc") or "CC",
            "fecha_inicio": (meta.get("fecha_inicio_incapacidad") or "")[:10],
            "dias": meta.get("dias_incapacidad") or plano.get("dias_incapacidad") or plano.get("dias") or "",
            "motivo": (caso.tipo.value if hasattr(caso.tipo, "value") else str(caso.tipo or "")),
            "diagnostico": caso.diagnostico or plano.get("diagnostico") or "",
            "cie10": caso.codigo_cie10 or plano.get("cie10") or "",
            "eps_detectada": eps_usada,
            "eps_fuente": fuente_eps,
        }

        item = RadicacionCola(
            serial_caso=caso.serial,
            case_id=caso.id,
            empresa=empresa_nombre,
            eps_key=bot.bot_nombre,
            tipo_incapacidad=datos_ocr["motivo"] or "enfermedad_general",
            pdf_drive_url=caso.drive_link,
            datos_ocr=datos_ocr,
            estado="pendiente",
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        logger.info(f"[Encolar] ✅ Caso {caso.serial} → cola #{item.id} ({empresa_nombre}/{bot.bot_nombre})")
        return item.id
    except Exception as e:
        logger.error(f"[Encolar] Error encolando caso: {e}")
        db.rollback()
        return None


# ──────────────────────────────────────────────
#  OPTIMIZACIÓN DE PESO DEL PDF (pre-radicación)
# ──────────────────────────────────────────────

def _limite_pdf_mb(db: Session, eps_key: str) -> float:
    """Límite vigente: el detectado en vivo por el bot (skill) > manifest > 5 MB."""
    skill = db.query(RadicacionSkill).filter(RadicacionSkill.eps_key == eps_key).first()
    if skill and skill.max_pdf_mb:
        return float(skill.max_pdf_mb)
    from app.routes.radicacion import MANIFESTS
    return float(MANIFESTS.get(eps_key, {}).get("max_pdf_mb", 5.0))


async def _optimizar_pdf_si_excede(db: Session, item: RadicacionCola) -> None:
    """
    Descarga el PDF del caso, y si supera el límite de la EPS lo comprime
    (sin perder soportes requeridos) y lo re-sube a Drive, actualizando la URL.
    Si algo falla, se continúa con el PDF original (el rechazo del portal
    quedará registrado y alimentará el límite para el siguiente intento).
    """
    import tempfile
    from pathlib import Path

    if not item.pdf_drive_url:
        return
    try:
        max_mb = _limite_pdf_mb(db, item.eps_key)
        import httpx
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            resp = await client.get(item.pdf_drive_url if "uc?" in item.pdf_drive_url
                                    else _url_descarga_drive(item.pdf_drive_url))
            resp.raise_for_status()
            contenido = resp.content

        peso_mb = len(contenido) / 1024 / 1024
        if peso_mb <= max_mb:
            return  # dentro del límite — nada que hacer

        logger.info(f"[PDF] Cola #{item.id}: {peso_mb:.2f} MB > límite {max_mb} MB de '{item.eps_key}' — comprimiendo…")
        from app.pdf_compressor import comprimir_pdf
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(contenido)
            tmp_path = Path(tmp.name)
        try:
            comprimido = comprimir_pdf(tmp_path, max_mb, item.tipo_incapacidad or "enfermedad_general")
        finally:
            tmp_path.unlink(missing_ok=True)

        # Re-subir a Drive el PDF optimizado
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp2:
            tmp2.write(comprimido)
            tmp2_path = Path(tmp2.name)
        try:
            from app.drive_uploader import upload_to_drive_v3
            datos = {**(item.datos_ocr or {}), **(item.datos_manuales or {})}
            link = upload_to_drive_v3(
                str(tmp2_path), item.empresa, datos.get("cedula") or "sin_cedula",
                item.tipo_incapacidad or "enfermedad_general",
                f"{item.serial_caso or item.id}_optimizado",
            )
            if isinstance(link, dict):
                link = link.get("link") or link.get("webViewLink") or link.get("url")
            if link:
                datos_man = dict(item.datos_manuales or {})
                datos_man["pdf_original_url"] = item.pdf_drive_url
                datos_man["pdf_comprimido"] = True
                datos_man["pdf_peso_original_mb"] = round(peso_mb, 2)
                datos_man["pdf_peso_final_mb"] = round(len(comprimido) / 1024 / 1024, 2)
                item.datos_manuales = datos_man
                item.pdf_drive_url = link
                db.commit()
                logger.info(f"[PDF] Cola #{item.id}: optimizado {peso_mb:.2f} → {len(comprimido)/1024/1024:.2f} MB ✅")
        finally:
            tmp2_path.unlink(missing_ok=True)
    except Exception as e:
        logger.warning(f"[PDF] Cola #{item.id}: no se pudo optimizar ({e}) — se usa el PDF original")


def _url_descarga_drive(url: str) -> str:
    """Convierte un link de vista de Drive en link de descarga directa."""
    import re
    m = re.search(r"/d/([\w-]+)|id=([\w-]+)", url or "")
    file_id = (m.group(1) or m.group(2)) if m else None
    return f"https://drive.google.com/uc?id={file_id}&export=download" if file_id else url


def _construir_task_y_variables(item: RadicacionCola, bot: EmpresaBotConfig) -> tuple:
    """
    Arma la instrucción corta del run y las variables (datos y credenciales).
    El paso a paso vive en el system prompt del agente reutilizable (AGENTES_POR_BOT).
    """
    datos = {**(item.datos_ocr or {}), **(item.datos_manuales or {})}

    # Soportes: PDF de la incapacidad + soporte fijo del bot (ej. certificado bancario)
    soportes = []
    if item.pdf_drive_url:
        cedula = datos.get("cedula") or datos.get("documento") or item.serial_caso or "incapacidad"
        soportes.append({"url": item.pdf_drive_url, "nombre": f"{cedula}_incapacidad.pdf"})
    if bot.soporte_drive_url:
        soportes.append({"url": bot.soporte_drive_url, "nombre": bot.soporte_nombre or "soporte_empresa.pdf"})

    variables: dict = {}

    # Credenciales del bot → variables seguras (%usuario%, %clave%, …)
    for key, value in (bot.credenciales or {}).items():
        if value:
            variables[key] = {
                "value": str(value),
                "description": f"Credencial '{key}' del portal — usar solo en el login oficial",
            }

    # Datos del caso
    mapa_datos = {
        "cedula": datos.get("cedula") or datos.get("documento") or "",
        "tipo_doc_trabajador": datos.get("tipo_doc_trabajador") or datos.get("tipo_doc") or "CC",
        "motivo": datos.get("motivo") or item.tipo_incapacidad.replace("_", " ").title(),
        "fecha_inicio": datos.get("fecha_inicio") or "",
        "dias": str(datos.get("dias") or ""),
        "soportes": json.dumps(soportes, ensure_ascii=False),
    }
    for key, value in mapa_datos.items():
        variables[key] = {"value": str(value)}

    task = (
        f"Radica la incapacidad del trabajador con documento %cedula% "
        f"(motivo: %motivo%, fecha inicio: %fecha_inicio%, días: %dias%) "
        f"siguiendo exactamente los pasos de tus instrucciones. "
        f"Soportes a adjuntar (JSON): %soportes%"
    )
    return task, variables


def _upsert_skill(db: Session, eps_key: str, bot: EmpresaBotConfig, exito: Optional[bool] = None):
    """Mantiene viva la tabla de skills que alimenta el portal admin (campos por EPS)."""
    skill = db.query(RadicacionSkill).filter(RadicacionSkill.eps_key == eps_key).first()
    if not skill:
        skill = RadicacionSkill(eps_key=eps_key, estado="activa")
        db.add(skill)
    if not skill.campos_credenciales and bot.credenciales:
        # Registrar qué campos usa este bot para que el portal los pida
        skill.campos_credenciales = [
            {"key": k, "label": k.replace("_", " ").title(), "tipo": "password" if "clave" in k or "pass" in k else "text"}
            for k in bot.credenciales.keys()
        ]
    if exito is True:
        skill.estado = "activa"
        skill.usos_totales = (skill.usos_totales or 0) + 1
        skill.ultimo_uso_at = datetime.utcnow()
        if not skill.primer_run_at:
            skill.primer_run_at = datetime.utcnow()
    elif exito is False:
        skill.estado = "fallo"


async def despachar_pendientes(db: Session) -> dict:
    """Toma ítems pendientes de la cola y lanza un run de Browserbase por cada uno."""
    from app.routes.browserbase import AGENTES_POR_BOT  # import tardío para evitar ciclo

    ahora = datetime.utcnow()
    items = (
        db.query(RadicacionCola)
        .filter(RadicacionCola.estado == "pendiente",
                RadicacionCola.proximo_intento <= ahora)
        .order_by(RadicacionCola.creado_en)
        .limit(MAX_RUNS_POR_CICLO)
        .all()
    )

    lanzados, errores = [], []
    for item in items:
        bot = _buscar_bot(db, item.empresa, item.eps_key)
        if not bot:
            item.estado = "fallo_temporal"
            item.intentos = (item.intentos or 0) + 1
            item.ultimo_error = f"No hay bot configurado para {item.empresa}/{item.eps_key}"
            item.proximo_intento = _calcular_proximo_intento(item.intentos)
            _agregar_historial(item, item.ultimo_error, ahora)
            errores.append({"item": item.id, "error": item.ultimo_error})
            continue

        agent_id = AGENTES_POR_BOT.get(item.eps_key)
        if not agent_id:
            # Sin agente entrenado aún — el ítem espera (no cuenta como intento fallido)
            logger.info(f"[Dispatcher] Item #{item.id}: sin agente para '{item.eps_key}' — en espera")
            continue

        # Optimizar peso del PDF si supera el límite conocido de la EPS
        await _optimizar_pdf_si_excede(db, item)

        task, variables = _construir_task_y_variables(item, bot)

        browser_settings: dict = {"proxies": True}
        if bot.browserbase_context_id:
            browser_settings["context"] = {"id": bot.browserbase_context_id, "persist": True}

        try:
            run = await bb.create_run(
                task=task,
                agent_id=agent_id,
                variables=variables,
                result_schema=RESULT_SCHEMA_RADICACION,
                browser_settings=browser_settings,
            )
        except BrowserbaseError as e:
            item.estado = "fallo_temporal"
            item.intentos = (item.intentos or 0) + 1
            item.ultimo_error = f"Error lanzando run: {e.detail}"
            item.proximo_intento = _calcular_proximo_intento(item.intentos)
            _agregar_historial(item, item.ultimo_error, ahora)
            errores.append({"item": item.id, "error": str(e.detail)[:200]})
            continue

        run_id = run.get("runId")
        item.estado = "procesando"
        item.sesion_id = run_id
        item.actualizado_en = ahora

        datos = {**(item.datos_ocr or {}), **(item.datos_manuales or {})}
        db.add(RadicacionSesion(
            sesion_id=run_id,
            empresa=item.empresa,
            eps=item.eps_key,
            medio=bot.bot_tipo_medio or "portal",
            documento=str(datos.get("cedula") or datos.get("documento") or ""),
            estado="en_curso",
            cached=bool(bot.browserbase_context_id),  # con sesión guardada = entra logueado
            logs=["Run lanzado en Browserbase", f"Agente: {agent_id[:8]}…"],
        ))
        _upsert_skill(db, item.eps_key, bot)
        lanzados.append({"item": item.id, "run_id": run_id, "empresa": item.empresa, "eps": item.eps_key})
        logger.info(f"[Dispatcher] Item #{item.id} → run {run_id} ({item.empresa}/{item.eps_key})")

    db.commit()
    return {"lanzados": lanzados, "errores": errores}


async def sincronizar_activas(db: Session) -> dict:
    """Consulta los runs activos y vuelca los resultados en sesiones + cola."""
    sesiones = db.query(RadicacionSesion).filter(RadicacionSesion.estado == "en_curso").all()
    finalizadas, aun_activas = [], 0
    ahora = datetime.utcnow()

    for sesion in sesiones:
        try:
            run = await bb.get_run(sesion.sesion_id)
        except BrowserbaseError as e:
            if e.status_code == 404:
                sesion.estado = "error"
                sesion.error_msg = "Run no encontrado en Browserbase"
                sesion.finalizado_en = ahora
            continue

        status = run.get("status")
        if status in ("PENDING", "RUNNING"):
            aun_activas += 1
            continue

        resultado = run.get("result") or {}
        # El resultado puede venir como summary JSON string (formato del agente)
        if isinstance(resultado.get("summary"), str):
            try:
                resultado = {**resultado, **json.loads(resultado["summary"])}
            except (ValueError, TypeError):
                pass

        exito = bool(resultado.get("exito")) and status == "COMPLETED"
        radicado = resultado.get("numero_radicado") or ""
        mensaje = resultado.get("mensaje") or (run.get("cause") or {}).get("message") or status
        paso_fallido = resultado.get("paso_fallido") or ""
        estado_portal = resultado.get("estado_portal") or ""
        observacion = resultado.get("observacion") or mensaje
        motivo_rechazo = resultado.get("motivo_rechazo") or ""
        peso_maximo = resultado.get("peso_maximo_pdf_mb")

        # 1. Actualizar sesión (monitoreo)
        sesion.estado = "exitosa" if exito else "fallida"
        sesion.radicado = radicado or None
        sesion.error_msg = None if exito else f"{paso_fallido + ': ' if paso_fallido else ''}{motivo_rechazo or mensaje}"
        sesion.progreso = 100
        sesion.finalizado_en = ahora

        # 2. Actualizar ítem de cola (reintentos con backoff) → alimenta la tabla
        #    de reportes "Estado de Radicación" en portal-neurobaeza
        item = db.query(RadicacionCola).filter(RadicacionCola.sesion_id == sesion.sesion_id).first()
        if item:
            obs_completa = " · ".join(x for x in [estado_portal, observacion] if x)
            item.observacion = obs_completa or mensaje
            if exito:
                item.estado = "exitosa"
                item.radicado = radicado
                item.procesado_en = ahora
            elif motivo_rechazo:
                # Rechazo del portal (duplicada, datos inválidos, peso…):
                # reintentar no lo arregla → fallo definitivo con el motivo exacto
                item.estado = "fallo_definitivo"
                item.fallo_motivo = f"RECHAZADA por el portal: {motivo_rechazo}"
                item.ultimo_error = item.fallo_motivo
                item.procesado_en = ahora
                _agregar_historial(item, item.fallo_motivo, ahora)
            else:
                item.intentos = (item.intentos or 0) + 1
                item.ultimo_error = sesion.error_msg
                _agregar_historial(item, sesion.error_msg, ahora)
                horas = (ahora - item.creado_en).total_seconds() / 3600 if item.creado_en else 0
                if item.intentos >= _MAX_INTENTOS or horas >= 48:
                    item.estado = "fallo_definitivo"
                    item.fallo_motivo = f"Agotados {item.intentos} intentos. Último error: {sesion.error_msg}"
                    item.procesado_en = ahora
                else:
                    item.estado = "fallo_temporal"
                    item.proximo_intento = _calcular_proximo_intento(item.intentos)
            item.actualizado_en = ahora

        # 3. Actualizar skill (+ límite de peso del PDF si el portal lo reveló)
        bot = _buscar_bot(db, sesion.empresa, sesion.eps)
        if bot:
            _upsert_skill(db, sesion.eps, bot, exito=exito)
        if peso_maximo:
            try:
                skill = db.query(RadicacionSkill).filter(RadicacionSkill.eps_key == sesion.eps).first()
                if skill and float(peso_maximo) > 0:
                    skill.max_pdf_mb = float(peso_maximo)
                    logger.info(f"[Skill] '{sesion.eps}': límite de PDF detectado en vivo → {peso_maximo} MB")
            except (ValueError, TypeError):
                pass

        finalizadas.append({
            "run_id": sesion.sesion_id, "empresa": sesion.empresa, "eps": sesion.eps,
            "exito": exito, "radicado": radicado, "error": sesion.error_msg,
        })
        logger.info(f"[Dispatcher] Run {sesion.sesion_id} → {'✅ ' + radicado if exito else '❌ ' + str(sesion.error_msg)[:100]}")

    db.commit()
    return {"finalizadas": finalizadas, "aun_activas": aun_activas}


async def ciclo_dispatcher() -> dict:
    """Un ciclo completo: sincronizar runs activos + despachar pendientes."""
    db = SessionLocal()
    try:
        sync = await sincronizar_activas(db)
        despacho = await despachar_pendientes(db)
        return {"sincronizacion": sync, "despacho": despacho}
    finally:
        db.close()


def ciclo_dispatcher_sync():
    """Wrapper síncrono para APScheduler."""
    import asyncio
    try:
        resultado = asyncio.run(ciclo_dispatcher())
        lanzados = len(resultado["despacho"]["lanzados"])
        finalizadas = len(resultado["sincronizacion"]["finalizadas"])
        if lanzados or finalizadas:
            logger.info(f"[Dispatcher] Ciclo: {lanzados} lanzado(s), {finalizadas} finalizada(s)")
    except Exception as e:
        logger.error(f"❌ Error en ciclo dispatcher Browserbase: {e}")
