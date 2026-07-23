"""
✅ Validación automática de soportes con IA
Conecta el validador IA (Gemini/Claude) con los casos:
- Toma el texto OCR (Mistral) guardado en metadata_form del caso
- Valida contra las reglas (reglas_validacion.json)
- Persiste ResultadoValidacion ligado al caso
- Guarda un resumen con semáforo en metadata_form['validacion_ia']
  para que el portal del validador lo muestre como pre-análisis.

Semáforo:
    verde    → ACEPTAR   (documento completo)
    amarillo → REVISAR   (requiere revisión humana)
    rojo     → RECHAZAR  (incompleto / ilegible / inconsistente)
    gris     → sin OCR o error de la IA (pendiente)
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

logger = logging.getLogger(__name__)

SEMAFORO_POR_DECISION = {
    "ACEPTAR": "verde",
    "REVISAR": "amarillo",
    "RECHAZAR": "rojo",
}


def _contexto_formulario_de_caso(caso) -> Dict:
    """Datos declarados en el formulario, para reglas de concordancia (R02, R09)."""
    meta = caso.metadata_form or {}
    return {
        "cedula": caso.cedula,
        "tipo": caso.tipo.value if caso.tipo else None,
        "subtipo": caso.subtipo,
        "fecha_inicio": caso.fecha_inicio.isoformat() if caso.fecha_inicio else None,
        "fecha_fin": caso.fecha_fin.isoformat() if caso.fecha_fin else None,
        "dias_incapacidad": caso.dias_incapacidad or meta.get("dias_incapacidad"),
    }


def _guardar_resumen_en_caso(db: Session, caso, resumen: Dict) -> None:
    meta = dict(caso.metadata_form or {})
    meta["validacion_ia"] = resumen
    caso.metadata_form = meta
    flag_modified(caso, "metadata_form")
    db.commit()


def validar_caso_con_ia(db: Session, caso, forzar: bool = False) -> Dict:
    """
    Ejecuta la validación IA sobre un caso ya creado.

    Args:
        db: Sesión de BD
        caso: Instancia de Case (con metadata_form['texto_ocr_mistral'])
        forzar: Si True, re-valida aunque ya exista un resultado previo

    Returns:
        El resumen guardado en metadata_form['validacion_ia']
    """
    from app.database import ResultadoValidacion, DecisionValidacion
    from app.validators import validador_ia

    meta = caso.metadata_form or {}

    if not forzar and meta.get("validacion_ia", {}).get("exito"):
        return meta["validacion_ia"]

    ahora = datetime.now(timezone.utc).isoformat()
    texto_ocr = meta.get("texto_ocr_mistral") or meta.get("texto_ocr_glm")

    if not texto_ocr:
        resumen = {
            "exito": False,
            "decision": None,
            "semaforo": "gris",
            "motivo": "Sin texto OCR disponible para analizar (Mistral OCR falló o no está configurado)",
            "reglas_fallidas": [],
            "reglas_procesadas": 0,
            "datos_extraidos": {},
            "modelo": None,
            "fecha": ahora,
        }
        _guardar_resumen_en_caso(db, caso, resumen)
        return resumen

    if validador_ia is None:
        resumen = {
            "exito": False,
            "decision": None,
            "semaforo": "gris",
            "motivo": "Validador IA no disponible (configura GEMINI_API_KEY o CLAUDE_API_KEY)",
            "reglas_fallidas": [],
            "reglas_procesadas": 0,
            "datos_extraidos": {},
            "modelo": None,
            "fecha": ahora,
        }
        _guardar_resumen_en_caso(db, caso, resumen)
        return resumen

    contexto = _contexto_formulario_de_caso(caso)
    resultado = validador_ia.validar(texto_ocr, contexto_formulario=contexto)

    decision = resultado.get("decision") or "REVISAR"
    semaforo = SEMAFORO_POR_DECISION.get(decision, "gris") if resultado.get("exito") else "gris"

    # Persistir resultado completo ligado al caso
    try:
        registro = ResultadoValidacion(
            cedula=caso.cedula,
            caso_id=caso.id,
            decision=DecisionValidacion(decision) if resultado.get("exito") else DecisionValidacion.REVISAR,
            motivo=resultado.get("motivo", ""),
            reglas_fallidas=resultado.get("reglas_fallidas", []),
            reglas_procesadas=resultado.get("reglas_procesadas", 0),
            datos_extraidos=resultado.get("datos_extraidos", {}),
            modelo_ia=resultado.get("modelo", ""),
            validado_exitosamente=bool(resultado.get("exito")),
            error_validacion=(resultado.get("error") or "")[:500] or None,
        )
        db.add(registro)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error guardando ResultadoValidacion para {caso.serial}: {e}")

    resumen = {
        "exito": bool(resultado.get("exito")),
        "decision": decision if resultado.get("exito") else None,
        "semaforo": semaforo,
        "motivo": resultado.get("motivo", ""),
        "reglas_fallidas": resultado.get("reglas_fallidas", []),
        "reglas_procesadas": resultado.get("reglas_procesadas", 0),
        "datos_extraidos": resultado.get("datos_extraidos", {}),
        "modelo": resultado.get("modelo"),
        "fecha": ahora,
    }
    _guardar_resumen_en_caso(db, caso, resumen)

    logger.info(
        f"🤖 Validación IA {caso.serial}: {decision} (semáforo={semaforo}, "
        f"reglas fallidas={resumen['reglas_fallidas']})"
    )
    return resumen
