import os
import base64
import httpx
from pathlib import Path


# ──────────────────────────────────────────────
#  CONFIGURACIÓN  (API key en Railway: GLM_API_KEY)
# ──────────────────────────────────────────────
GLM_API_URL = "https://api.z.ai/api/paas/v4/layout_parsing"
GLM_API_KEY = os.getenv("GLM_API_KEY", "")  # nunca pongas la key en el código


# ──────────────────────────────────────────────
#  FUNCIÓN PRINCIPAL
#  Recibe: ruta al PDF  →  devuelve: texto plano
# ──────────────────────────────────────────────
def extraer_texto_pdf(ruta_pdf: str) -> dict:
    """
    Envía un PDF a GLM-OCR y devuelve el texto extraído.

    Retorna un dict con:
        - exito    (bool)
        - texto    (str)  → texto plano listo para radicación
        - error    (str)  → mensaje si algo falla
        - paginas  (int)  → número de páginas procesadas
    """

    if not GLM_API_KEY:
        return {
            "exito": False,
            "texto": "",
            "error": "GLM_API_KEY no configurada en las variables de entorno",
            "paginas": 0,
        }

    ruta = Path(ruta_pdf)
    if not ruta.exists():
        return {
            "exito": False,
            "texto": "",
            "error": f"Archivo no encontrado: {ruta_pdf}",
            "paginas": 0,
        }

    # Convierte el PDF a base64 para enviarlo a la API
    with open(ruta, "rb") as f:
        pdf_bytes = f.read()

    pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
    data_uri = f"data:application/pdf;base64,{pdf_base64}"

    headers = {
        "Authorization": f"Bearer {GLM_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "glm-ocr",
        "file": data_uri,
    }

    try:
        # Timeout de 60 segundos (suficiente para 2-3 páginas)
        with httpx.Client(timeout=60.0) as client:
            response = client.post(GLM_API_URL, headers=headers, json=payload)
            response.raise_for_status()

        resultado = response.json()

        # Extrae el texto del response de GLM-OCR
        texto = _parsear_respuesta(resultado)
        paginas = resultado.get("usage", {}).get("pages", 0)

        return {
            "exito": True,
            "texto": texto,
            "error": "",
            "paginas": paginas,
        }

    except httpx.TimeoutException:
        return {
            "exito": False,
            "texto": "",
            "error": "Timeout: el servidor GLM-OCR tardó demasiado",
            "paginas": 0,
        }
    except httpx.HTTPStatusError as e:
        return {
            "exito": False,
            "texto": "",
            "error": f"Error HTTP {e.response.status_code}: {e.response.text}",
            "paginas": 0,
        }
    except Exception as e:
        return {
            "exito": False,
            "texto": "",
            "error": f"Error inesperado: {str(e)}",
            "paginas": 0,
        }


def _parsear_respuesta(resultado: dict) -> str:
    """
    Extrae el texto plano del JSON que devuelve GLM-OCR.
    El modelo devuelve markdown estructurado; aquí lo convertimos a texto limpio.
    """
    contenido = resultado.get("choices", [{}])[0].get("message", {}).get("content", "")

    if not contenido:
        # Fallback: intenta otros campos del response
        contenido = resultado.get("content", "") or resultado.get("text", "")

    # Limpieza básica: quita marcadores markdown para texto plano
    lineas = contenido.split("\n")
    lineas_limpias = []
    for linea in lineas:
        linea = linea.strip()
        # Quita encabezados markdown (#, ##, ###)
        if linea.startswith("#"):
            linea = linea.lstrip("#").strip()
        # Quita guiones de tabla markdown
        if set(linea) <= {"|", "-", " "}:
            continue
        if linea:
            lineas_limpias.append(linea)

    return "\n".join(lineas_limpias)
