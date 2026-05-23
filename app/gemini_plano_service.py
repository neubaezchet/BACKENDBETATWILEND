"""
Servicio Gemini Flash — Estructuración de Plano de Incapacidades
Recibe el texto OCR de Mistral y extrae los campos del plano en JSON limpio.

SDK: google-genai >= 2.4.0  (from google import genai)
Modelos (con fallback automático):
  1. gemini-1.5-flash          (estable, amplio soporte)
  2. gemini-2.5-flash-preview-05-20  (más nuevo)
  3. gemini-1.5-pro            (fallback pro)
"""

import os
import json
import logging
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Lista de modelos a intentar en orden. Si el primero falla con 404, se prueba el siguiente.
GEMINI_MODELS_FALLBACK = [
    "gemini-1.5-flash",
    "gemini-2.5-flash-preview-05-20",
    "gemini-1.5-pro",
]

PROMPT_TEMPLATE = """Eres un experto en documentos médicos colombianos (incapacidades, epicrisis, certificados).
Tu única tarea es extraer campos específicos del texto OCR que te doy y devolver un JSON válido.

CAMPOS A EXTRAER:
- tipo_documento: tipo de documento de identidad (CC, TI, CE, PA, RC, NIT). Si no aparece, usa "CC".
- numero_documento: número de cédula o documento. Solo dígitos, sin puntos ni comas.
- empresa: nombre de la empresa empleadora. Vacío si no aparece.
- eps: nombre de la EPS o aseguradora. Vacío si no aparece.
- dias_incapacidad: número entero de días. 0 si no aparece.
- fecha_inicio: fecha de inicio en formato YYYY-MM-DD. Vacío si no aparece.
- fecha_fin: fecha de fin en formato YYYY-MM-DD. Vacío si no aparece.
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
                # Prueba mínima: generar 1 token para verificar disponibilidad
                self.client.models.generate_content(
                    model=modelo,
                    contents="test",
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        max_output_tokens=1,
                    ),
                )
                logger.info(f"✅ GeminiPlanoService: modelo '{modelo}' disponible y seleccionado")
                return modelo
            except Exception as e:
                err_str = str(e)
                if "404" in err_str or "NOT_FOUND" in err_str or "no longer available" in err_str:
                    logger.warning(f"⚠️ Modelo '{modelo}' no disponible (404), probando siguiente...")
                    continue
                else:
                    # Error de red u otro — igual intentar siguiente
                    logger.warning(f"⚠️ Modelo '{modelo}' error inesperado: {e}, probando siguiente...")
                    continue
        # Si ninguno funcionó, usar el primero de la lista (fallará en runtime con mensaje claro)
        logger.error("❌ Ningún modelo Gemini disponible. Usando gemini-1.5-flash como último recurso.")
        return GEMINI_MODELS_FALLBACK[0]

    def estructurar_plano(self, texto_ocr: str) -> dict:
        """
        Toma el texto markdown devuelto por Mistral OCR y pide a Gemini Flash
        que extraiga los campos del plano de incapacidades en JSON.

        Returns:
            {
                "exito": bool,
                "plano": {
                    "tipo_documento", "numero_documento", "empresa", "eps",
                    "dias_incapacidad", "fecha_inicio", "fecha_fin",
                    "medico", "registro_medico", "lugar_atencion",
                    "nit_lugar_atencion", "diagnostico", "codigo_cie10",
                    "origen", "tipo_incapacidad"
                },
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

        prompt = PROMPT_TEMPLATE.format(texto_ocr=texto_ocr[:12000])  # límite seguro de tokens

        # Intentar con el modelo activo, y hacer fallback si da 404
        modelos_a_intentar = [self.model] + [m for m in GEMINI_MODELS_FALLBACK if m != self.model]

        for modelo in modelos_a_intentar:
            try:
                response = self.client.models.generate_content(
                    model=modelo,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                    ),
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

                # Asegurar tipo correcto en dias_incapacidad
                try:
                    plano["dias_incapacidad"] = int(plano.get("dias_incapacidad") or 0)
                except (ValueError, TypeError):
                    plano["dias_incapacidad"] = 0

                # Si cambió de modelo, actualizar el activo para próximas llamadas
                if modelo != self.model:
                    logger.info(f"✅ Fallback exitoso: cambiando modelo activo a '{modelo}'")
                    self.model = modelo

                logger.info(f"✅ Gemini plano OK [{modelo}]: origen={plano.get('origen')}, dias={plano.get('dias_incapacidad')}")

                return {
                    "exito": True,
                    "plano": plano,
                    "modelo": modelo,
                    "error": "",
                }

            except json.JSONDecodeError as e:
                logger.error(f"⚠️ Gemini [{modelo}] devolvió JSON inválido: {e} | raw={raw[:300]}")
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
                    logger.error(f"❌ Error Gemini plano [{modelo}]: {e}")
                    return {
                        "exito": False,
                        "plano": {},
                        "modelo": modelo,
                        "error": str(e),
                    }

        # Si llegamos aquí, todos los modelos fallaron
        return {
            "exito": False,
            "plano": {},
            "modelo": "none",
            "error": f"Ningún modelo Gemini disponible. Modelos intentados: {modelos_a_intentar}",
        }


# Instancia global — None si falta la key
try:
    gemini_plano = GeminiPlanoService()
    logger.info(f"✅ GeminiPlanoService listo: modelo activo = {gemini_plano.model}")
except Exception as e:
    logger.warning(f"⚠️ GeminiPlanoService no disponible: {e}")
    gemini_plano = None
