"""
Servicio Gemini Flash — Estructuración de Plano de Incapacidades
Recibe el texto OCR de Mistral y extrae los campos del plano en JSON limpio.

SDK: google-genai >= 2.4.0  (from google import genai)
Modelo principal: configurable via GEMINI_PLANO_MODEL en Railway.
  - Por defecto: gemini-3.5-flash (estable mayo 2026, óptimo)
  - Fallback automático si el modelo principal falla con 404.
"""

import os
import re
import json
import logging
from datetime import date, timedelta
from typing import Any, Dict, Optional

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ── Modelo principal ──────────────────────────────────────────────────────────
# Configura GEMINI_PLANO_MODEL en las variables de entorno de Railway para
# cambiar el modelo sin necesidad de hacer deploy.
# Ejemplo: GEMINI_PLANO_MODEL=gemini-3.5-flash
GEMINI_PLANO_MODEL = os.getenv("GEMINI_PLANO_MODEL", "gemini-2.5-flash")

# ── Lista de fallback (se intenta en orden si el principal da 404) ─────────────
_FALLBACK_EXTRA = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
]
# El modelo principal siempre va primero; el resto son respaldo sin duplicados
GEMINI_MODELS_FALLBACK = [GEMINI_PLANO_MODEL] + [
    m for m in _FALLBACK_EXTRA if m != GEMINI_PLANO_MODEL
]

PROMPT_TEMPLATE = """Eres un experto en documentos médicos colombianos (incapacidades, epicrisis, certificados).
Tu única tarea es extraer campos específicos del texto OCR que te doy y devolver un JSON válido.

CAMPOS A EXTRAER:
- tipo_documento: tipo de documento de identidad (CC, TI, CE, PA, RC, NIT). Si no aparece, usa "CC".
- numero_documento: número de cédula o documento. Solo dígitos, sin puntos ni comas.
- numero_incapacidad: número del certificado/incapacidad que asignó la IPS o la EPS (aparece como "No. Incapacidad", "Certificado No.", "Consecutivo", "No. de certificado", "Orden N°"). Solo dígitos. NO es la cédula ni el radicado. Vacío si no aparece.
- empresa: nombre de la empresa empleadora. Vacío si no aparece.
- eps: nombre de la EPS o aseguradora. Vacío si no aparece.
- dias_incapacidad: número entero de días. 0 si no aparece.
- fecha_inicio: fecha de inicio en formato YYYY-MM-DD. Vacío si no aparece.
- fecha_fin: fecha de fin en formato YYYY-MM-DD. Vacío si no aparece.
  ORDEN PARA HALLARLAS (respétalo):
  1) Si el documento trae dos campos separados ("Fecha inicio" / "Fecha fin",
     "Fecha inicial" / "Fecha final"), usa esos.
  2) Si NO encuentras los dos campos por separado, busca un RANGO en un solo
     campo: muchas IPS lo escriben así. Etiquetas típicas: "Vigencia",
     "Válida del ... al ...", "Período", "Desde ... Hasta ...", "Del ... al ...".
     Ejemplo real: "Vigencia: 18/09/2026 - 25/09/2026"  →  fecha_inicio
     2026-09-18, fecha_fin 2026-09-25. La PRIMERA fecha del rango es
     fecha_inicio y la SEGUNDA es fecha_fin.
  3) Si solo aparece la fecha de inicio ("Fecha desde", "A partir del"), eso está
     bien: llena fecha_inicio y deja fecha_fin vacío. NO inventes la fecha fin ni
     la deduzcas tú: el sistema la calcula con los días. Un soporte con solo
     fecha de inicio es válido.
  No confundas ninguna de estas fechas con la fecha de impresión, de atención, de
  registro, de ingreso ni de nacimiento, que suelen estar en el mismo documento.
- medico: nombre completo del médico que firma. Vacío si no aparece.
- registro_medico: número de registro médico o tarjeta profesional. Vacío si no aparece.
- lugar_atencion: nombre de la clínica, hospital o IPS. Vacío si no aparece.
- nit_lugar_atencion: NIT de la institución. Solo dígitos. Vacío si no aparece.
- diagnostico: descripción del diagnóstico en texto. Vacío si no aparece.
- codigo_cie10: código CIE-10 del diagnóstico (ej: A09, S299). Vacío si no aparece.
- origen: clasifica el origen. Solo puede ser uno de: "Común", "Laboral", "Accidente de Tránsito", "Maternidad", "Paternidad". Usa contexto del texto.
- tipo_incapacidad: tipo descriptivo (Enfermedad General, Accidente Laboral, Maternidad, etc.)

REGLAS ESTRICTAS:
1. Devuelve SOLO el JSON, sin explicaciones, sin markdown, sin texto adicional.
2. Si un campo no está en el texto, devuelve cadena vacía "" o 0 para números.
3. Las fechas SIEMPRE en formato YYYY-MM-DD.
4. numero_documento: solo dígitos, sin espacios ni separadores.
5. dias_incapacidad: número entero, no texto.

TEXTO OCR:
---
{texto_ocr}
---

JSON:"""


# ══════════════════════════════════════════════════════════════════════════════
#  RANGO DE VIGENCIA — verificación determinística sobre el texto OCR
# ══════════════════════════════════════════════════════════════════════════════
# Muchas IPS no imprimen "fecha inicio" y "fecha fin", sino un rango en un solo
# campo ("Vigencia: 18/09/2026 - 25/09/2026"). En la misma hoja suele haber
# cuatro o cinco fechas más (impresión, atención, registro, ingreso, nacimiento),
# así que pedirle al modelo que "no se confunda" no es garantía de nada: cuando
# el OCR llega sucio vuelve a agarrar la de arriba, y radicar con la fecha
# equivocada es un rechazo seguro que nadie nota hasta el recobro.
#
# Por eso el rango se busca también con expresiones regulares sobre el texto
# crudo: cero tokens, cero alucinación, mismo resultado siempre. El modelo
# explora, esto congela.
#
# El rango NO pisa a ciegas lo que trajo el modelo: si el documento tiene sus dos
# campos de fecha por separado, esos mandan (una etiqueta "Vigencia" también
# puede ser la de la afiliación o la del carné). El rango entra cuando falta
# alguna de las dos, y cuando las dos versiones se contradicen desempatan los
# días que el propio documento declara. Ver _consolidar_fechas.

_MESES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

# Un solo grupo de captura por fecha, para poder usarlo dos veces en un rango.
_FECHA = (
    r"((?:\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})"
    r"|(?:\d{4}-\d{1,2}-\d{1,2})"
    r"|(?:\d{1,2}\s+de\s+[a-zñ]+\s+de\s+\d{4}))"
)
_SEP = r"\s*(?:-|–|—|a|al|hasta|y)\s*"

# Rangos con etiqueta explícita: los más confiables, se buscan primero.
_PATRONES_ETIQUETADOS = [
    ("vigencia",  re.compile(r"vigenc\w*\s*:?\s*" + _FECHA + _SEP + _FECHA)),
    ("validez",   re.compile(r"v[aá]lid\w*\s*(?:desde|del|de)?\s*:?\s*" + _FECHA + _SEP + _FECHA)),
    ("periodo",   re.compile(r"per[ií]odo\s*:?\s*" + _FECHA + _SEP + _FECHA)),
    ("desde_hasta", re.compile(r"desde\s*:?\s*" + _FECHA + r"[^0-9]{0,20}hasta\s*:?\s*" + _FECHA)),
]
# Sin etiqueta: solo si ninguno de los anteriores encontró nada, porque una
# epicrisis puede traer "control del X al Y" que no es la incapacidad.
_PATRON_DEL_AL = re.compile(r"\bde\s?l\s+" + _FECHA + r"\s*(?:al|hasta|a)\s+" + _FECHA)


def _quitar_tildes(texto: str) -> str:
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def _parsear_fecha(bruto: str) -> Optional[date]:
    """Convierte una fecha suelta del documento a date. None si no es válida."""
    if not bruto:
        return None
    s = _quitar_tildes(bruto.strip().lower())

    m = re.match(r"^(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(\d{4})$", s)
    if m:
        mes = _MESES_ES.get(m.group(2))
        if not mes:
            return None
        try:
            return date(int(m.group(3)), mes, int(m.group(1)))
        except ValueError:
            return None

    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$", s)
    if m:
        # En Colombia el formato es dd/mm/aaaa. Nunca se invierte a mm/dd:
        # "05/09" significa 5 de septiembre, y adivinar aquí sería peor que fallar.
        dia, mes, anio = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if anio < 100:
            anio += 2000
        try:
            return date(anio, mes, dia)
        except ValueError:
            return None

    return None


def extraer_rango_vigencia(texto_ocr: str) -> Optional[Dict[str, Any]]:
    """
    Busca en el texto OCR el rango de vigencia de la incapacidad.

    Devuelve {"fecha_inicio", "fecha_fin", "dias", "etiqueta"} o None si el
    documento no trae un rango explícito (que es un resultado válido: muchas
    incapacidades sí traen los dos campos por separado).

    Nunca lanza excepción: si el texto viene raro, devuelve None y el flujo
    sigue con lo que haya extraído el modelo.
    """
    try:
        if not texto_ocr:
            return None
        plano_txt = _quitar_tildes(re.sub(r"\s+", " ", texto_ocr)).lower()

        candidatos = list(_PATRONES_ETIQUETADOS)
        encontrado = None
        for etiqueta, patron in candidatos:
            m = patron.search(plano_txt)
            if m:
                encontrado = (etiqueta, m)
                break
        if not encontrado:
            m = _PATRON_DEL_AL.search(plano_txt)
            if m:
                encontrado = ("del_al", m)
        if not encontrado:
            return None

        etiqueta, m = encontrado
        inicio, fin = _parsear_fecha(m.group(1)), _parsear_fecha(m.group(2))
        if not inicio or not fin:
            return None
        if fin < inicio:
            # Rango al revés: casi siempre es OCR que partió mal los dígitos.
            # Se descarta en vez de radicar fechas invertidas.
            logger.warning(f"⚠️ Rango de vigencia invertido ({inicio} → {fin}), se descarta")
            return None
        if (fin - inicio).days > 545:
            # Ninguna incapacidad dura año y medio: es otra cosa (un tratamiento,
            # una afiliación) que se coló con la etiqueta.
            return None

        return {
            "fecha_inicio": inicio.isoformat(),
            "fecha_fin": fin.isoformat(),
            "dias": (fin - inicio).days + 1,  # inclusivo: del 18 al 25 son 8 días
            "etiqueta": etiqueta,
        }
    except Exception as e:
        logger.warning(f"⚠️ No se pudo extraer rango de vigencia: {e}")
        return None


# Los días son un dato que el documento declara por su cuenta, aparte de las
# fechas. Por eso sirven de árbitro independiente cuando el modelo y el rango
# impreso no coinciden: gana el par de fechas cuyos días cuadren con el papel.
_PATRONES_DIAS = (
    # "Días de incapacidad: 8", "Días licencia 8", "Días autorizados: 8"
    re.compile(r"\bd[ií]as?\b[^0-9\n]{0,25}?(?:incapacidad|licencia|autorizad\w*|"
               r"otorgad\w*|reconocid\w*)\b\s*:?\s*(\d{1,3})\b"),
    # "Total de días: 8", "Número de días 8", "Cantidad de días: 8"
    re.compile(r"\b(?:total|n[uú]mero|cantidad|nro\.?)\s+(?:de\s+)?d[ií]as?\b\s*:?\s*(\d{1,3})\b"),
    # "8 días de incapacidad"
    re.compile(r"\b(\d{1,3})\s+d[ií]as?\s+(?:de\s+)?(?:incapacidad|licencia)\b"),
)


def _extraer_dias_declarados(texto_ocr: str) -> Optional[int]:
    """Días que el documento dice en letra, sin pasar por el modelo. None si no los trae."""
    try:
        if not texto_ocr:
            return None
        plano_txt = _quitar_tildes(re.sub(r"\s+", " ", texto_ocr)).lower()
        for patron in _PATRONES_DIAS:
            m = patron.search(plano_txt)
            if m:
                dias = int(m.group(1))
                # Fuera de este rango no es un conteo de días de incapacidad.
                if 1 <= dias <= 365:
                    return dias
        return None
    except Exception:
        return None


def _parsear_iso(valor: Any) -> Optional[date]:
    """'2026-09-18' → date. None si viene vacío o ilegible."""
    try:
        texto = str(valor or "").strip()[:10]
        return date.fromisoformat(texto) if len(texto) == 10 else None
    except (ValueError, TypeError):
        return None


def _consolidar_fechas(plano: dict, texto_ocr: str) -> dict:
    """
    Deja el plano con las mejores fechas posibles y el rastro de cómo se
    decidieron. Orden fijado por el negocio:

      1. Si el documento trae fecha_inicio Y fecha_fin como campos aparte, esas
         mandan: son el dato propio, no una interpretación.
      2. Si falta alguna de las dos, la rellena el rango explícito impreso
         ("Vigencia: 18/09/2026 - 25/09/2026"). Este es el caso de los formatos
         tipo Virrey Solís / Salud Total, que no traen los campos sueltos.
      3. Si las dos existen pero contradicen al rango, desempata el árbitro
         independiente: los días que el propio documento declara.
      4. Si al final falta la fecha fin pero hay inicio y días, se calcula
         (inicio + días - 1): eso es aritmética, no adivinanza. Un soporte con
         solo fecha de inicio es válido; lo que nunca se hace es inventarle un
         fin sin días que lo respalden.

    Campos que agrega: fechas_fuente, vigencia_etiqueta, dias_segun_fechas,
    fecha_fin_calculada, alerta_fechas. Nunca lanza excepción.
    """
    try:
        rango = extraer_rango_vigencia(texto_ocr)
        dias_doc = _extraer_dias_declarados(texto_ocr)
        alertas = []
        fuente = "modelo"

        inicio_ia = (plano.get("fecha_inicio") or "").strip()[:10]
        fin_ia = (plano.get("fecha_fin") or "").strip()[:10]

        if rango:
            plano["vigencia_etiqueta"] = rango["etiqueta"]

            if not inicio_ia or not fin_ia:
                # Regla 2 — el rango impreso rellena el hueco.
                if inicio_ia and inicio_ia != rango["fecha_inicio"]:
                    alertas.append(
                        f"fecha_inicio: el modelo dijo {inicio_ia} y la vigencia "
                        f"impresa dice {rango['fecha_inicio']}"
                    )
                if fin_ia and fin_ia != rango["fecha_fin"]:
                    alertas.append(
                        f"fecha_fin: el modelo dijo {fin_ia} y la vigencia "
                        f"impresa dice {rango['fecha_fin']}"
                    )
                plano["fecha_inicio"] = rango["fecha_inicio"]
                plano["fecha_fin"] = rango["fecha_fin"]
                fuente = "vigencia_documento"

            elif (inicio_ia, fin_ia) == (rango["fecha_inicio"], rango["fecha_fin"]):
                # Los dos caminos dieron lo mismo: confianza alta.
                fuente = "vigencia_confirmada"

            else:
                # Regla 3 — hay dos versiones completas y distintas. Se decide
                # por los días declarados, no por corazonada.
                ini_ia_d, fin_ia_d = _parsear_iso(inicio_ia), _parsear_iso(fin_ia)
                dias_ia = (fin_ia_d - ini_ia_d).days + 1 if ini_ia_d and fin_ia_d else None
                cuadra_rango = dias_doc is not None and dias_doc == rango["dias"]
                cuadra_ia = dias_doc is not None and dias_doc == dias_ia
                detalle = (
                    f"los campos sueltos dicen {inicio_ia}→{fin_ia} y la vigencia "
                    f"impresa {rango['fecha_inicio']}→{rango['fecha_fin']}"
                )
                if cuadra_rango and not cuadra_ia:
                    plano["fecha_inicio"] = rango["fecha_inicio"]
                    plano["fecha_fin"] = rango["fecha_fin"]
                    fuente = "vigencia_documento"
                    alertas.append(f"{detalle}; gana la vigencia porque el documento declara {dias_doc} días")
                elif cuadra_ia and not cuadra_rango:
                    alertas.append(f"{detalle}; se conservan los campos sueltos porque cuadran con los {dias_doc} días declarados")
                else:
                    alertas.append(f"{detalle}; sin días declarados que desempaten quedan los campos sueltos — revisar a mano")

        # ── Días ──────────────────────────────────────────────────────────────
        try:
            dias = int(plano.get("dias_incapacidad") or 0)
        except (TypeError, ValueError):
            dias = 0

        ini = _parsear_iso(plano.get("fecha_inicio"))
        fin = _parsear_iso(plano.get("fecha_fin"))

        if dias <= 0 and dias_doc:
            dias = dias_doc
            plano["dias_incapacidad"] = dias
        if dias <= 0 and ini and fin:
            dias = (fin - ini).days + 1
            plano["dias_incapacidad"] = dias

        # Regla 4 — falta el fin, pero inicio + días lo determinan sin ambigüedad.
        if ini and not fin and dias > 0:
            fin = ini + timedelta(days=dias - 1)
            plano["fecha_fin"] = fin.isoformat()
            plano["fecha_fin_calculada"] = True
            logger.info(f"📅 fecha_fin calculada como {fin} ({ini} + {dias} días)")

        # El documento se contradice a sí mismo: se reporta, no se resuelve solo.
        if dias > 0 and ini and fin:
            dias_reales = (fin - ini).days + 1
            if dias_reales != dias:
                alertas.append(
                    f"dias: el documento declara {dias} y {ini.isoformat()}→"
                    f"{fin.isoformat()} da {dias_reales}"
                )
                plano["dias_segun_fechas"] = dias_reales

        plano["fechas_fuente"] = fuente
        if alertas:
            plano["alerta_fechas"] = " | ".join(alertas)
            logger.warning(f"⚠️ Discrepancia de fechas en el plano: {plano['alerta_fechas']}")
        return plano

    except Exception as e:
        # Fail-safe: si algo sale mal aquí, el plano del modelo sigue de largo.
        logger.warning(f"⚠️ No se pudieron consolidar las fechas: {e}")
        plano.setdefault("fechas_fuente", "modelo")
        return plano


class GeminiPlanoService:
    """Extrae campos del Plano de Incapacidades a partir de texto OCR de Mistral.
    Usa fallback automático de modelos si el principal no está disponible.
    """

    def __init__(self):
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY no configurada en variables de entorno")
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        # Detectar qué modelo está disponible al iniciar
        self.model = self._detectar_modelo_disponible()

    def _detectar_modelo_disponible(self) -> str:
        """Prueba los modelos en orden y retorna el primero disponible."""
        for modelo in GEMINI_MODELS_FALLBACK:
            try:
                self.client.models.generate_content(
                    model=modelo,
                    contents="test",
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        max_output_tokens=1,
                    ),
                )
                logger.info(f"✅ GeminiPlanoService: modelo '{modelo}' seleccionado")
                return modelo
            except Exception as e:
                err_str = str(e)
                if "404" in err_str or "NOT_FOUND" in err_str or "no longer available" in err_str:
                    logger.warning(f"⚠️ Modelo '{modelo}' no disponible (404), probando siguiente...")
                    continue
                else:
                    logger.warning(f"⚠️ Modelo '{modelo}' error: {e}, probando siguiente...")
                    continue
        logger.error("❌ Ningún modelo Gemini disponible.")
        return GEMINI_MODELS_FALLBACK[0]

    def estructurar_plano(self, texto_ocr: str) -> dict:
        """
        Toma el texto markdown devuelto por Mistral OCR y pide a Gemini
        que extraiga los campos del plano de incapacidades en JSON.

        Returns:
            {
                "exito": bool,
                "plano": { tipo_documento, numero_documento, numero_incapacidad,
                           empresa, eps,
                           dias_incapacidad, fecha_inicio, fecha_fin,
                           medico, registro_medico, lugar_atencion,
                           nit_lugar_atencion, diagnostico, codigo_cie10,
                           origen, tipo_incapacidad },
                "modelo": str,
                "error": str
            }
        """
        if not texto_ocr or not texto_ocr.strip():
            return {
                "exito": False,
                "plano": {},
                "modelo": self.model,
                "error": "Texto OCR vacío — no hay nada que estructurar",
            }

        prompt = PROMPT_TEMPLATE.format(texto_ocr=texto_ocr[:12000])

        # Intentar con el modelo activo y hacer fallback si da 404
        modelos_a_intentar = [self.model] + [m for m in GEMINI_MODELS_FALLBACK if m != self.model]

        for modelo in modelos_a_intentar:
            raw = ""
            try:
                response = self.client.models.generate_content(
                    model=modelo,
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=0.0),
                )

                raw = response.text.strip() if response.text else ""

                # Limpiar markdown si Gemini lo envuelve
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                    raw = raw.strip()
                raw = raw.rstrip("`").strip()

                plano = json.loads(raw)

                try:
                    plano["dias_incapacidad"] = int(plano.get("dias_incapacidad") or 0)
                except (ValueError, TypeError):
                    plano["dias_incapacidad"] = 0

                # Verificación determinística del rango de vigencia sobre el
                # texto crudo (ver _consolidar_fechas): el modelo propone, el
                # documento decide.
                plano = _consolidar_fechas(plano, texto_ocr)

                if modelo != self.model:
                    logger.info(f"✅ Fallback exitoso: nuevo modelo activo = '{modelo}'")
                    self.model = modelo

                logger.info(
                    f"✅ Gemini plano OK [{modelo}]: "
                    f"origen={plano.get('origen')}, dias={plano.get('dias_incapacidad')}"
                )

                return {"exito": True, "plano": plano, "modelo": modelo, "error": ""}

            except json.JSONDecodeError as e:
                logger.error(f"⚠️ Gemini [{modelo}] JSON inválido: {e} | raw={raw[:300]}")
                return {
                    "exito": False,
                    "plano": {},
                    "modelo": modelo,
                    "error": f"JSON inválido de Gemini: {str(e)}",
                }
            except Exception as e:
                err_str = str(e)
                if "404" in err_str or "NOT_FOUND" in err_str or "no longer available" in err_str:
                    logger.warning(f"⚠️ Modelo '{modelo}' no disponible, probando siguiente...")
                    continue
                else:
                    logger.error(f"❌ Error Gemini [{modelo}]: {e}")
                    return {"exito": False, "plano": {}, "modelo": modelo, "error": str(e)}

        return {
            "exito": False,
            "plano": {},
            "modelo": "none",
            "error": f"Ningún modelo Gemini disponible. Intentados: {modelos_a_intentar}",
        }


# ── Instancia global ──────────────────────────────────────────────────────────
try:
    gemini_plano = GeminiPlanoService()
    logger.info(f"✅ GeminiPlanoService listo. Modelo activo: {gemini_plano.model}")
except Exception as e:
    logger.warning(f"⚠️ GeminiPlanoService no disponible: {e}")
    gemini_plano = None
