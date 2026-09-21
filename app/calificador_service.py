"""
Calificador IA de soportes — semáforo informativo (ACEPTAR/REVISAR/RECHAZAR)
sobre incapacidades recién radicadas desde repogemin.

Arquitectura de 3 capas por costo (más barato primero):
  Capa 1 (gratis, código puro): R13 formato transcrito conocido (substring match),
          cálculo de documentos requeridos (misma fuente que /reglas/requisitos),
          y chequeos aritméticos/de campo sobre el "plano" ya extraído por Gemini
          (R02 cédula, R06 campos mínimos, R09 límite de días).
  Capa 2 (LLM barato, Gemini Flash): lee el texto OCR completo para determinar
          qué documentos requeridos están realmente presentes (resumen, FURIPS,
          SOAT...), concordancia de origen, semanas de gestación indicadas, y
          posibles incapacidades duplicadas en un mismo archivo (R01).
  Capa 3 (visión, solo si hiciera falta): calidad/legibilidad de imagen — NO
          implementada todavía (fuera de alcance de esta primera versión).

Regla de negocio confirmada: el resultado es SIEMPRE informativo. Nunca bloquea
ni decide el estado del caso — todo soporte se radica, completo o incompleto.
Este servicio solo escribe en ResultadoValidacion; nunca toca Case.estado.

Fail-safe: evaluar_caso() nunca lanza — cualquier error se captura y se
persiste como registro con validado_exitosamente=False, para no afectar jamás
el flujo principal de recepción/radicación en main.py.
"""

import os
import json
import logging
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.database import (
    Case,
    ResultadoValidacion,
    ReglaValidacionIA,
    DecisionValidacion,
)
from app.reglas_requisitos import calcular_documentos_requeridos, detectar_formato_transcrito
from app.checks_disponibles import CHECKS_DISPONIBLES

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:  # pragma: no cover - el SDK ya es dependencia del proyecto
    genai = None
    genai_types = None

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_CALIFICADOR_MODEL = os.getenv("GEMINI_CALIFICADOR_MODEL", "gemini-2.5-flash")
CALIFICADOR_VERSION = "1.0-layers12"

# Mapeo doc requerido (reglas_requisitos) → check faltante (checks_disponibles.py)
DOC_A_CHECK_FALTANTE = {
    "incapacidad_medica": "incapacidad_faltante",
    "licencia_o_incapacidad": "incapacidad_faltante",
    "epicrisis_o_resumen_clinico": "epicrisis_faltante",
    "furips": "furips_faltante",
    "soat": "soat_faltante",
    "nacido_vivo": "nacido_vivo_faltante",
    "registro_civil": "registro_civil_faltante",
    "cedula_padre": "cedula_padre_faltante",
    "licencia_maternidad": "licencia_maternidad_faltante",
}

_RANK_DECISION = {"ACEPTAR": 0, "REVISAR": 1, "RECHAZAR": 2}

_PROMPT_LAYER2 = """Eres un auditor experto en soportes de incapacidad laboral en Colombia.
Analiza el texto OCR de un soporte ya radicado y determina, con base en las reglas dadas,
si el paquete de documentos está completo y coherente. Tu respuesta es SOLO informativa
(no bloquea nada), así que sé preciso y justifica brevemente.

TIPO DE INCAPACIDAD: {tipo}
DÍAS DE INCAPACIDAD: {dias}

DATOS YA EXTRAÍDOS DEL DOCUMENTO PRINCIPAL (plano):
{plano_json}

DOCUMENTOS QUE EL SISTEMA CALCULA COMO REQUERIDOS PARA ESTE CASO:
{documentos_requeridos_json}

HALLAZGOS PREVIOS DE VALIDACIÓN AUTOMÁTICA (capa de código, ya evaluados, no los repitas):
{hallazgos_previos}

REGLAS DE VALIDACIÓN VIGENTES (evalúalas sobre el texto OCR):
{reglas_texto}

TEXTO OCR COMPLETO DEL SOPORTE (puede incluir varios documentos fusionados en un solo PDF):
---
{texto_ocr}
---

Responde SOLO con un JSON válido (sin markdown, sin explicaciones fuera del JSON) con esta forma exacta:
{{
  "decision": "ACEPTAR" | "REVISAR" | "RECHAZAR",
  "motivo": "explicación breve en español, clara para un validador humano",
  "reglas_fallidas": ["R04", "R10", ...],
  "documentos_detectados": {{"<doc>": true|false, ...}},
  "entidad_formato_transcrito": "nombre de entidad o null si no aplica",
  "semanas_gestacion_detectadas": true|false,
  "posible_incapacidad_duplicada": true|false
}}

"documentos_detectados" debe traer una entrada por cada documento de la lista de requeridos,
indicando si tu lectura del texto OCR confirma que ese documento SÍ está presente en el soporte."""


def _extraer_texto_ocr(metadata: dict) -> str:
    texto = metadata.get("texto_ocr_mistral") or ""
    if not texto:
        ocr_mistral = metadata.get("ocr_mistral") or {}
        texto = ocr_mistral.get("texto") or ""
    return texto or ""


def _extraer_plano(metadata: dict) -> dict:
    plano_data = metadata.get("plano_incapacidad") or {}
    if plano_data.get("exito"):
        return plano_data.get("plano") or {}
    return {}


def _es_verdadero(valor) -> bool:
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str):
        return valor.strip().lower() in ("true", "sí", "si", "1", "yes")
    return bool(valor)


def _cargar_reglas_activas(db: Session, company_id: Optional[int]) -> list:
    """Reglas activas globales o de la empresa. Con solo ~13 reglas hoy, se
    envían todas al prompt sin necesidad de narrowing por RAG/vectores — el
    pgvector de ReglaValidacionIA/PrecedenteValidacion queda listo para cuando
    el volumen de reglas o precedentes crezca lo suficiente para justificarlo."""
    try:
        reglas = db.query(ReglaValidacionIA).filter(
            ReglaValidacionIA.activa == True,  # noqa: E712
            or_(ReglaValidacionIA.company_id.is_(None), ReglaValidacionIA.company_id == company_id),
        ).all()
        if reglas:
            return [
                {"codigo": r.codigo, "nombre": r.nombre, "descripcion": r.descripcion}
                for r in reglas
            ]
    except Exception as e:
        logger.warning(f"⚠️ No se pudieron leer reglas_validacion_ia, usando fallback JSON: {e}")

    try:
        ruta_json = os.path.join(os.path.dirname(__file__), "data", "reglas_validacion.json")
        with open(ruta_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [
            {"codigo": r["id"], "nombre": r.get("nombre", r["id"]), "descripcion": r.get("descripcion", "")}
            for r in data.get("reglas", [])
        ]
    except Exception as e:
        logger.error(f"❌ Fallback de reglas también falló: {e}")
        return []


def _evaluar_layer1(caso: Case, metadata: dict, plano: dict, texto_ocr: str) -> dict:
    """Capa gratis: código puro, sin llamadas a LLM."""
    reglas_fallidas = []
    motivos = []

    # R13 — formato oficial transcrito: si aplica, anula todo lo demás.
    entidad_transcrita = detectar_formato_transcrito(texto_ocr)

    # R02 — concordancia de cédula (plano vs. formulario)
    numero_plano = str(plano.get("numero_documento") or "").strip()
    cedula_caso = str(caso.cedula or "").strip()
    if numero_plano and cedula_caso and numero_plano != cedula_caso:
        reglas_fallidas.append("R02")
        motivos.append(f"El número de documento del soporte ({numero_plano}) no coincide con el registrado ({cedula_caso}).")

    # R06 — campos mínimos de la incapacidad ya extraídos en el plano
    if plano:
        campos_faltantes = []
        if not plano.get("fecha_inicio"):
            campos_faltantes.append("fecha de inicio")
        if not (plano.get("medico") or plano.get("registro_medico")):
            campos_faltantes.append("identificación del médico")
        if not plano.get("codigo_cie10"):
            campos_faltantes.append("diagnóstico CIE-10")
        if campos_faltantes:
            reglas_fallidas.append("R06")
            motivos.append(f"Campos mínimos no identificados en la incapacidad: {', '.join(campos_faltantes)}.")

    # R09 — límite de días
    dias = caso.dias_incapacidad or plano.get("dias_incapacidad") or 0
    try:
        dias_int = int(dias)
        if dias_int > 30:
            reglas_fallidas.append("R09")
            motivos.append(f"La incapacidad reporta {dias_int} días, supera el límite de 30.")
    except (ValueError, TypeError):
        pass

    documentos_requeridos = calcular_documentos_requeridos(
        tipo=caso.tipo.value if caso.tipo else "",
        dias=caso.dias_incapacidad,
        vehiculo_fantasma=_es_verdadero(metadata.get("vehiculo_fantasma")),
        madre_trabaja=_es_verdadero(metadata.get("madre_trabaja")),
        semanas_gestacion_indicadas=False,  # se confirma/corrige en capa 2 (lectura semántica del OCR)
        es_prorroga=bool(caso.es_prorroga) if hasattr(caso, "es_prorroga") else False,
    )["documentos"]

    return {
        "entidad_formato_transcrito": entidad_transcrita,
        "documentos_requeridos": documentos_requeridos,
        "reglas_fallidas": reglas_fallidas,
        "motivos": motivos,
    }


def _evaluar_layer2(caso: Case, plano: dict, texto_ocr: str, layer1: dict, db: Session) -> Optional[dict]:
    """Capa LLM: lee el OCR completo para presencia de documentos y coherencia
    semántica. Retorna None si no se pudo ejecutar (sin API key, sin OCR, error)."""
    if not GEMINI_API_KEY or genai is None:
        logger.warning("⚠️ Calificador capa 2 omitida: GEMINI_API_KEY no configurada o SDK no disponible")
        return None
    if not texto_ocr or not texto_ocr.strip():
        logger.warning("⚠️ Calificador capa 2 omitida: sin texto OCR disponible")
        return None

    documentos_requeridos = [d for d in layer1["documentos_requeridos"] if d.get("requerido")]
    if not documentos_requeridos:
        return None

    reglas = _cargar_reglas_activas(db, caso.company_id)
    reglas_texto = "\n".join(f"- {r['codigo']} ({r['nombre']}): {r['descripcion']}" for r in reglas) or "(sin reglas configuradas)"

    prompt = _PROMPT_LAYER2.format(
        tipo=caso.tipo.value if caso.tipo else "desconocido",
        dias=caso.dias_incapacidad or "desconocido",
        plano_json=json.dumps(plano, ensure_ascii=False, indent=2),
        documentos_requeridos_json=json.dumps(documentos_requeridos, ensure_ascii=False, indent=2),
        hallazgos_previos="\n".join(layer1["motivos"]) or "(ninguno)",
        reglas_texto=reglas_texto,
        texto_ocr=texto_ocr[:20000],
    )

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_CALIFICADOR_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(temperature=0.0),
        )
        raw = (response.text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        raw = raw.rstrip("`").strip()
        resultado = json.loads(raw)
        resultado["_modelo"] = GEMINI_CALIFICADOR_MODEL
        return resultado
    except Exception as e:
        logger.error(f"❌ Calificador capa 2 (Gemini) falló: {e}")
        return None


def evaluar_caso(caso_id: int, db: Session) -> dict:
    """Punto de entrada. Evalúa un caso ya guardado y persiste el resultado en
    ResultadoValidacion (upsert por caso_id — idempotente si se reintenta).
    Nunca lanza excepciones."""
    resultado_dict = {"exito": False, "decision": None, "error": None}
    try:
        caso = db.query(Case).filter(Case.id == caso_id).first()
        if not caso:
            resultado_dict["error"] = f"Caso {caso_id} no encontrado"
            return resultado_dict

        metadata = caso.metadata_form or {}
        texto_ocr = _extraer_texto_ocr(metadata)
        plano = _extraer_plano(metadata)

        layer1 = _evaluar_layer1(caso, metadata, plano, texto_ocr)
        capas_ejecutadas = ["layer1"]

        if layer1["entidad_formato_transcrito"]:
            decision = "ACEPTAR"
            motivo = (
                f"El soporte corresponde a un certificado oficial transcrito por "
                f"{layer1['entidad_formato_transcrito']}, que ya contiene todos los datos "
                f"requeridos. No se exigen soportes adicionales (regla R13)."
            )
            reglas_fallidas = []
            checks_fallidos = []
            documentos_detectados = {d["doc"]: True for d in layer1["documentos_requeridos"]}
            modelo_ia = "layer1-only"
        else:
            layer2 = _evaluar_layer2(caso, plano, texto_ocr, layer1, db)
            reglas_fallidas = list(layer1["reglas_fallidas"])
            documentos_detectados = {}
            checks_fallidos = []

            if layer2:
                capas_ejecutadas.append("layer2")
                decision = layer2.get("decision") if layer2.get("decision") in _RANK_DECISION else "REVISAR"
                motivo = layer2.get("motivo") or "Evaluado por IA sin motivo explícito."
                reglas_fallidas.extend([r for r in layer2.get("reglas_fallidas", []) if r not in reglas_fallidas])
                documentos_detectados = layer2.get("documentos_detectados") or {}
                modelo_ia = layer2.get("_modelo", GEMINI_CALIFICADOR_MODEL)
                if layer2.get("posible_incapacidad_duplicada"):
                    if "R01" not in reglas_fallidas:
                        reglas_fallidas.append("R01")
                    decision = "RECHAZAR"
            else:
                decision = "REVISAR" if layer1["reglas_fallidas"] else "ACEPTAR"
                motivo = " ".join(layer1["motivos"]) or "Sin observaciones automáticas (solo capa de código, IA de lectura no disponible)."
                modelo_ia = "layer1-only"

            # Red de seguridad determinística: si falta algún doc requerido
            # según lo que la IA detectó, nunca dejar la decisión en ACEPTAR.
            for doc in layer1["documentos_requeridos"]:
                if not doc.get("requerido"):
                    continue
                detectado = documentos_detectados.get(doc["doc"])
                if detectado is False:
                    check = DOC_A_CHECK_FALTANTE.get(doc["doc"])
                    if check and check not in checks_fallidos:
                        checks_fallidos.append(check)
                    if _RANK_DECISION.get(decision, 0) < _RANK_DECISION["REVISAR"]:
                        decision = "REVISAR"

        datos_extraidos = {
            "plano": plano,
            "documentos_requeridos": layer1["documentos_requeridos"],
            "documentos_detectados": documentos_detectados,
            "checks_fallidos": checks_fallidos,
            "entidad_formato_transcrito": layer1["entidad_formato_transcrito"],
            "capas_ejecutadas": capas_ejecutadas,
        }

        existente = db.query(ResultadoValidacion).filter(ResultadoValidacion.caso_id == caso.id).first()
        if existente:
            existente.decision = DecisionValidacion(decision)
            existente.motivo = motivo
            existente.reglas_fallidas = reglas_fallidas
            existente.reglas_procesadas = len(reglas_fallidas)
            existente.datos_extraidos = datos_extraidos
            existente.modelo_ia = modelo_ia
            existente.version_reglas = CALIFICADOR_VERSION
            existente.validado_exitosamente = True
            existente.error_validacion = None
        else:
            db.add(ResultadoValidacion(
                cedula=caso.cedula,
                caso_id=caso.id,
                decision=DecisionValidacion(decision),
                motivo=motivo,
                reglas_fallidas=reglas_fallidas,
                reglas_procesadas=len(reglas_fallidas),
                datos_extraidos=datos_extraidos,
                modelo_ia=modelo_ia,
                version_reglas=CALIFICADOR_VERSION,
                validado_exitosamente=True,
            ))
        db.commit()

        logger.info(f"✅ Calificador IA: caso {caso.serial} → {decision} ({', '.join(capas_ejecutadas)})")
        resultado_dict.update({"exito": True, "decision": decision})
        return resultado_dict

    except Exception as e:
        logger.error(f"❌ Error en calificador_service.evaluar_caso({caso_id}): {e}")
        try:
            db.rollback()
            caso = db.query(Case).filter(Case.id == caso_id).first()
            if caso:
                existente = db.query(ResultadoValidacion).filter(ResultadoValidacion.caso_id == caso.id).first()
                if not existente:
                    db.add(ResultadoValidacion(
                        cedula=caso.cedula,
                        caso_id=caso.id,
                        decision=DecisionValidacion.REVISAR,
                        motivo="El calificador IA no pudo completar la evaluación automática. Requiere validación manual.",
                        reglas_fallidas=[],
                        reglas_procesadas=0,
                        datos_extraidos={},
                        modelo_ia="error",
                        version_reglas=CALIFICADOR_VERSION,
                        validado_exitosamente=False,
                        error_validacion=str(e)[:500],
                    ))
                    db.commit()
        except Exception as e2:
            logger.error(f"❌ Calificador: también falló el registro de error: {e2}")
            db.rollback()
        resultado_dict["error"] = str(e)
        return resultado_dict
