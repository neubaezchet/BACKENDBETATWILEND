"""
✅ Validador de Incapacidades con IA (Gemini/Claude)
Lee reglas desde JSON y valida texto OCR
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
import google.generativeai as genai
import anthropic

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  CONFIGURACIÓN
# ──────────────────────────────────────────────
VALIDATOR_MODEL = os.getenv("VALIDATOR", "gemini")  # "gemini" | "claude"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")

# Cargar reglas desde JSON
REGLAS_PATH = Path(__file__).parent.parent / "data" / "reglas_validacion.json"

def cargar_reglas() -> Dict:
    """Carga las reglas de validación desde el archivo JSON"""
    try:
        with open(REGLAS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"❌ Archivo de reglas no encontrado: {REGLAS_PATH}")
        return {"reglas": []}
    except json.JSONDecodeError as e:
        logger.error(f"❌ Error al parsear JSON de reglas: {e}")
        return {"reglas": []}

REGLAS_VALIDACION = cargar_reglas()

# ──────────────────────────────────────────────
#  PROMPT DE VALIDACIÓN
# ──────────────────────────────────────────────

def construir_prompt_validacion(texto_ocr: str, reglas: Dict, contexto_formulario: Optional[Dict] = None) -> str:
    """Construye el prompt para validar el OCR contra las reglas"""

    # Formatear las reglas de forma clara
    reglas_texto = ""
    for regla in reglas.get("reglas", []):
        reglas_texto += f"""
**{regla['id']}: {regla['nombre']}**
- Descripción: {regla['descripcion']}
- Tipo: {regla.get('tipo', 'general')}
- Decisión si falla: {regla['decision']}
"""

    contexto_texto = ""
    if contexto_formulario:
        campos = {
            "cedula": "Cédula registrada en el formulario",
            "tipo": "Tipo de incapacidad declarado",
            "subtipo": "Subtipo declarado",
            "fecha_inicio": "Fecha de inicio declarada",
            "fecha_fin": "Fecha de fin declarada",
            "dias_incapacidad": "Días de incapacidad declarados",
        }
        lineas = [
            f"- {label}: {contexto_formulario[key]}"
            for key, label in campos.items()
            if contexto_formulario.get(key) not in (None, "")
        ]
        if lineas:
            contexto_texto = f"""
DATOS DECLARADOS EN EL FORMULARIO (compáralos contra el documento — reglas de concordancia como R02 y R09):
{chr(10).join(lineas)}
"""

    prompt = f"""
Eres un validador EXPERTO de incapacidades médicas colombianas.
Tu tarea es analizar el texto extraído de un documento y validarlo contra las siguientes REGLAS ESTRICTAS:

{reglas_texto}
{contexto_texto}

INSTRUCCIONES:
1. Analiza el texto OCR línea por línea
2. Para CADA regla, determina si PASA o FALLA
3. Identifica CLARAMENTE qué información hay o falta
4. Extrae los DATOS CLAVE del documento
5. Proporciona un MOTIVO detallado

TEXTO DEL DOCUMENTO (extraído por OCR):
---
{texto_ocr}
---

RESPONDE SOLO EN JSON VÁLIDO, sin texto adicional. Ejemplo estructura:
{{
  "decision": "ACEPTAR" | "RECHAZAR" | "REVISAR",
  "motivo": "Explicación clara en español",
  "reglas_fallidas": ["R01", "R03"],
  "reglas_procesadas": 11,
  "datos_extraidos": {{
    "nombre_paciente": "",
    "cedula": "",
    "fecha_inicio": "",
    "fecha_fin": "",
    "dias": 0,
    "diagnostico_cie10": "",
    "medico": "",
    "registro_medico": "",
    "entidad": "",
    "origen": "EPS | ARL | SOAT | OTRO"
  }}
}}

REGLAS DE DECISIÓN:
- ACEPTAR: El documento está completo, legible y cumple TODAS las reglas
- RECHAZAR: Hay reglas críticas fallidas (R01, R07, R04, R06)
- REVISAR: Hay reglas menores fallidas pero el documento es evaluable
"""
    return prompt

# ──────────────────────────────────────────────
#  VALIDADOR CON IA
# ──────────────────────────────────────────────

class ValidadorIncapacidadIA:
    """Validador de incapacidades usando Gemini o Claude"""
    
    def __init__(self, modelo: str = None):
        self.modelo = modelo or VALIDATOR_MODEL
        self.reglas = REGLAS_VALIDACION
        
        if self.modelo == "gemini":
            if not GEMINI_API_KEY:
                raise ValueError("❌ GEMINI_API_KEY no está configurada")
            genai.configure(api_key=GEMINI_API_KEY)
        elif self.modelo == "claude":
            if not CLAUDE_API_KEY:
                raise ValueError("❌ CLAUDE_API_KEY no está configurada")
        else:
            raise ValueError(f"❌ Modelo no soportado: {self.modelo}")
    
    def validar(self, texto_ocr: str, contexto_formulario: Optional[Dict] = None) -> Dict:
        """
        Valida un texto OCR contra las reglas

        Args:
            texto_ocr: Texto extraído por OCR (Mistral)
            contexto_formulario: Datos declarados en el formulario (cédula, tipo,
                fechas, días) para las reglas de concordancia

        Returns:
            {
                "exito": bool,
                "decision": "ACEPTAR" | "RECHAZAR" | "REVISAR",
                "motivo": str,
                "reglas_fallidas": List[str],
                "reglas_procesadas": int,
                "datos_extraidos": Dict,
                "modelo": str,
                "error": str
            }
        """
        try:
            prompt = construir_prompt_validacion(texto_ocr, self.reglas, contexto_formulario)
            
            if self.modelo == "gemini":
                respuesta = self._validar_con_gemini(prompt)
            else:
                respuesta = self._validar_con_claude(prompt)
            
            # Parsear respuesta
            try:
                resultado_ia = json.loads(respuesta)
            except json.JSONDecodeError:
                # Intentar extraer JSON de entre comillas o markdown
                respuesta_limpia = respuesta.strip()
                if respuesta_limpia.startswith("```json"):
                    respuesta_limpia = respuesta_limpia[7:]
                if respuesta_limpia.endswith("```"):
                    respuesta_limpia = respuesta_limpia[:-3]
                resultado_ia = json.loads(respuesta_limpia.strip())
            
            return {
                "exito": True,
                "decision": resultado_ia.get("decision", "REVISAR"),
                "motivo": resultado_ia.get("motivo", ""),
                "reglas_fallidas": resultado_ia.get("reglas_fallidas", []),
                "reglas_procesadas": resultado_ia.get("reglas_procesadas", len(self.reglas.get("reglas", []))),
                "datos_extraidos": resultado_ia.get("datos_extraidos", {}),
                "modelo": self.modelo,
                "error": ""
            }
        
        except Exception as e:
            logger.error(f"❌ Error validando: {str(e)}")
            return {
                "exito": False,
                "decision": "REVISAR",
                "motivo": f"Error al validar: {str(e)}",
                "reglas_fallidas": [],
                "reglas_procesadas": 0,
                "datos_extraidos": {},
                "modelo": self.modelo,
                "error": str(e)
            }
    
    def _validar_con_gemini(self, prompt: str) -> str:
        """Valida usando Gemini 2.0 Flash"""
        model = genai.GenerativeModel("gemini-3.5-flash")
        response = model.generate_content(prompt, timeout=30)
        return response.text.strip()
    
    def _validar_con_claude(self, prompt: str) -> str:
        """Valida usando Claude Haiku"""
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()


# ──────────────────────────────────────────────
#  INSTANCIA GLOBAL
# ──────────────────────────────────────────────

try:
    validador_ia = ValidadorIncapacidadIA()
    logger.info(f"✅ Validador IA inicializado: {VALIDATOR_MODEL}")
except Exception as e:
    logger.error(f"❌ Error inicializando validador: {e}")
    validador_ia = None


# ──────────────────────────────────────────────
#  TEST RÁPIDO
# ──────────────────────────────────────────────

if __name__ == "__main__":
    texto_prueba = """
    INCAPACIDAD LABORAL
    
    Paciente: JOSE LUIS VALENCIA
    Cédula: CC 79535936
    Diagnóstico: S299 - TRAUMATISMO DEL TORAX
    Fecha inicio: 08-05-2026
    Fecha fin: 10-05-2026
    Días: 3
    Médico: EDISON JAVIER RODRIGUEZ SERRANO
    Registro: 1032429873
    Origen: LABORAL
    Entidad: COLSUBSIDIO
    
    Resumen: Se otorga incapacidad por traumatismo de tórax por accidente laboral.
    Se solicita reposo.
    """
    
    if validador_ia:
        resultado = validador_ia.validar(texto_prueba)
        print(json.dumps(resultado, indent=2, ensure_ascii=False))
