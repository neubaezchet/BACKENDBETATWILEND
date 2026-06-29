"""
Compresor de PDF en cascada para radicación de incapacidades.

Estrategia en 4 etapas para reducir el tamaño al límite de la EPS sin
perder los soportes requeridos.

Etapa 1 — Compresión básica (sin pérdida):
    PyMuPDF garbage=4, deflate, clean.

Etapa 2 — Re-render a 96 DPI (pérdida mínima):
    Documentos médicos siguen perfectamente legibles.

Etapa 3 — Eliminación de páginas no esenciales (reglas + IA opcional):
    Se clasifican las páginas y se eliminan en este orden:
      a) Páginas en blanco / duplicadas
      b) Resultados de exámenes
      c) Instrucciones de egreso
      d) Indicaciones médicas / Recomendaciones médicas
      e) Órdenes médicas

Etapa 4 — Limpiar resúmenes de atención extras:
    Mantiene solo el resumen principal (el que dice qué se hizo ese día
    y tiene firma del médico). Los demás se eliminan.

Los soportes requeridos por tipo de incapacidad NUNCA se eliminan.
"""

import io
import logging
import os
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

logger = logging.getLogger(__name__)


# ── Soportes requeridos (no se eliminan nunca) ────────────────────────────────

SOPORTES_REQUERIDOS: dict[str, list[str]] = {
    "enfermedad_general":  ["incapacidad", "resumen_atencion"],
    "enfermedad_laboral":  ["incapacidad", "resumen_atencion"],
    "accidente_transito":  ["incapacidad", "resumen_atencion", "soat", "furips"],
    "maternidad":          ["incapacidad", "resumen_atencion", "registro_civil", "nacido_vivo"],
    "paternidad":          ["incapacidad", "licencia_maternidad", "registro_civil", "nacido_vivo", "cedula_padre"],
    "especial":            ["incapacidad", "resumen_atencion"],
    "prelicencia":         ["incapacidad", "resumen_atencion"],
    "certificado":         ["incapacidad"],
    "other":               ["incapacidad", "resumen_atencion"],
}

# Orden de eliminación (primero = se elimina antes porque es menos importante)
ORDEN_ELIMINACION = [
    "blanco",
    "duplicado",
    "examenes",
    "instrucciones_egreso",
    "indicaciones_medicas",
    "recomendaciones_medicas",
    "orden_medica",
    "resumen_atencion_extra",  # especial: conserva el primero, elimina los demás
]

# ── Palabras clave para clasificación basada en texto ────────────────────────

_KW: dict[str, list[str]] = {
    "examenes": [
        "resultado", "laboratorio", "muestra", "valores de referencia", "hemograma",
        "parcial de orina", "creatinina", "glucosa", "hematocrito", "leucocitos",
        "plaquetas", "bilirrubina", "enzimas", "radiografía", "ecografía",
        "tomografía", "resonancia", "rx ", "eco ", "uroanálisis",
    ],
    "instrucciones_egreso": [
        "instrucciones de egreso", "instrucciones al egreso", "alta médica",
        "se da de alta", "indicaciones de egreso", "alta hospitalaria",
    ],
    "indicaciones_medicas": [
        "indicaciones médicas", "indicaciones generales", "indicaciones para el paciente",
        "se indica", "se recomienda", "indicaciones:", "indicaciones post",
    ],
    "recomendaciones_medicas": [
        "recomendaciones médicas", "recomendaciones generales", "cuidados en casa",
        "cuidados en el hogar", "recomendaciones al paciente", "recomendaciones:",
    ],
    "orden_medica": [
        "orden médica", "fórmula médica", "se ordena", "se formula", "se prescribe",
        "medicamento", "dosis:", "vía de administración", "dispensar",
        "orden de", "solicitar", "rx:", "paraclínicos:",
    ],
    "soat": [
        "soat", "seguro obligatorio", "fasecolda", "accidente de tránsito",
        "placa del vehículo", "póliza soat",
    ],
    "furips": [
        "furips", "formato único", "reporte de accidente", "furat",
    ],
    "registro_civil": [
        "registro civil", "nacimiento", "notaría", "registraduría",
    ],
    "nacido_vivo": [
        "nacido vivo", "certificado de nacido", "recién nacido",
    ],
    "licencia_maternidad": [
        "licencia de maternidad", "licencia maternidad", "semanas de gestación",
    ],
    "incapacidad": [
        "incapacidad laboral", "incapacidad médica", "días de incapacidad",
        "incapacitado por", "certificado de incapacidad",
    ],
    "resumen_atencion": [
        "resumen de atención", "epicrisis", "historia clínica", "motivo de consulta",
        "antecedentes", "diagnóstico", "plan de manejo", "evolución",
        "médico tratante", "firma", "registro médico",
    ],
}

PROMPT_CLASIFICAR_GEMINI = """Analiza esta imagen de una página de un expediente médico colombiano.
Clasifícala en UNO de los siguientes tipos. Responde SOLO el tipo, sin texto adicional.

incapacidad              → certificado/soporte de incapacidad
resumen_atencion         → resumen de atención, epicrisis o historia clínica del día principal (tiene motivo + lo que se hizo + firma)
resumen_atencion_extra   → resumen de atención de visita diferente (seguimiento, control)
examenes                 → resultados de laboratorio, imágenes diagnósticas
instrucciones_egreso     → instrucciones de egreso o alta médica
indicaciones_medicas     → indicaciones médicas post-consulta
recomendaciones_medicas  → recomendaciones de salud o cuidados en casa
orden_medica             → orden de medicamentos, exámenes o procedimientos
soat                     → póliza SOAT
furips                   → formato FURIPS
registro_civil           → registro civil de nacimiento
nacido_vivo              → certificado de nacido vivo
licencia_maternidad      → licencia de maternidad EPS
cedula_padre             → cédula del padre
blanco                   → página en blanco o casi vacía
duplicado                → copia idéntica a otra página
otro                     → cualquier otro tipo

Tipo:"""


# ── Clasificación basada en texto extraído ────────────────────────────────────

def _clasificar_por_texto(texto: str) -> str:
    """Clasifica una página según palabras clave en su texto extraído."""
    t = texto.lower()
    if len(t.strip()) < 60:
        return "blanco"
    for tipo, kws in _KW.items():
        for kw in kws:
            if kw in t:
                return tipo
    return "otro"


def _clasificar_paginas_reglas(doc: fitz.Document) -> list[str]:
    """
    Clasifica páginas usando extracción de texto (funciona sin red).
    Para páginas escaneadas sin texto extraíble, se asigna 'otro'.
    """
    hashes_vistos: dict[str, int] = {}
    clasificaciones: list[str] = []

    for i, page in enumerate(doc):
        texto = page.get_text("text") or ""
        clase = _clasificar_por_texto(texto)

        # Detectar duplicados por hash del texto
        if clase not in ("blanco",):
            h = str(hash(texto.strip()))
            if h in hashes_vistos:
                clase = "duplicado"
            else:
                hashes_vistos[h] = i

        clasificaciones.append(clase)
        logger.debug(f"  Página {i + 1}: texto={len(texto)} chars → '{clase}'")

    return clasificaciones


def _clasificar_paginas_gemini(doc: fitz.Document) -> list[str] | None:
    """
    Clasifica páginas con Gemini Vision. Retorna None si no está disponible.
    """
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None

    model = os.getenv("GEMINI_PLANO_MODEL", "gemini-2.5-flash")
    client = genai.Client(api_key=api_key)

    tipos_validos = set(ORDEN_ELIMINACION) | {
        "incapacidad", "resumen_atencion", "soat", "furips",
        "registro_civil", "nacido_vivo", "licencia_maternidad", "cedula_padre", "otro",
    }
    clasificaciones: list[str] = []

    for i, page in enumerate(doc):
        try:
            scale = 72 / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
            img = Image.frombytes(
                "RGBA" if pix.alpha else "RGB",
                (pix.width, pix.height),
                pix.samples,
            ).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=50)
            jpeg_bytes = buf.getvalue()

            response = client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg"),
                    PROMPT_CLASIFICAR_GEMINI,
                ],
                config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=20),
            )
            raw = (response.text or "otro").strip().lower().split()[0].rstrip(".")
            clase = raw if raw in tipos_validos else "otro"
            clasificaciones.append(clase)
            logger.info(f"  [Gemini] Página {i + 1}/{len(doc)}: '{clase}'")
        except Exception as e:
            logger.warning(f"  [Gemini] Página {i + 1}: error ({e})")
            clasificaciones.append("otro")

    return clasificaciones


# ── Compresión por etapas ─────────────────────────────────────────────────────

def _basic_compress(pdf_path: Path) -> bytes:
    doc = fitz.open(str(pdf_path))
    buf = io.BytesIO()
    doc.save(buf, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True)
    doc.close()
    return buf.getvalue()


def _rerender(pdf_path: Path, dpi: int = 96) -> bytes:
    doc_orig = fitz.open(str(pdf_path))
    doc_out = fitz.open()
    scale = dpi / 72.0

    for page in doc_orig:
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        img = Image.frombytes(
            "RGBA" if pix.alpha else "RGB",
            (pix.width, pix.height),
            pix.samples,
        ).convert("RGB")
        buf_img = io.BytesIO()
        img.save(buf_img, format="JPEG", quality=80)
        buf_img.seek(0)
        new_page = doc_out.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, stream=buf_img.read())

    buf = io.BytesIO()
    doc_out.save(buf, garbage=4, deflate=True, clean=True)
    doc_out.close()
    doc_orig.close()
    return buf.getvalue()


def _keep_pages(pdf_bytes: bytes, indices: list[int]) -> bytes:
    """Reconstruye el PDF conservando solo los índices indicados."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    doc_out = fitz.open()
    for i in indices:
        if i < len(doc):
            doc_out.insert_pdf(doc, from_page=i, to_page=i)
    buf = io.BytesIO()
    doc_out.save(buf, garbage=4, deflate=True, clean=True)
    doc_out.close()
    doc.close()
    return buf.getvalue()


# ── Función principal pública ─────────────────────────────────────────────────

def comprimir_pdf(
    pdf_path: Path,
    max_mb: float,
    tipo_incapacidad: str = "enfermedad_general",
) -> bytes:
    """
    Comprime el PDF al límite `max_mb` MB usando estrategia en cascada.

    Prioridad de compresión:
      1. Compresión técnica sin pérdida (deflate, garbage)
      2. Re-render de páginas a 96 DPI (calidad visual conservada)
      3. Eliminación de páginas no esenciales (por reglas de texto)
      4. Si Gemini está disponible, reclasificación y segunda pasada

    Los soportes requeridos por `tipo_incapacidad` NUNCA se eliminan.

    Returns:
        Bytes del PDF resultante. Si no se alcanzó el objetivo, retorna
        el resultado más pequeño posible sin perder soportes requeridos.
    """
    max_bytes = int(max_mb * 1024 * 1024)
    original_size = pdf_path.stat().st_size

    logger.info(
        f"[pdf_compressor] '{pdf_path.name}' "
        f"({original_size / 1024 / 1024:.2f} MB) → objetivo ≤ {max_mb} MB"
    )

    if original_size <= max_bytes:
        logger.info("[pdf_compressor] Ya dentro del límite.")
        return pdf_path.read_bytes()

    soportes = SOPORTES_REQUERIDOS.get(
        tipo_incapacidad, SOPORTES_REQUERIDOS["enfermedad_general"]
    )

    # ── Etapa 1 ───────────────────────────────────────────────────────────
    logger.info("[pdf_compressor] Etapa 1: compresión básica...")
    e1 = _basic_compress(pdf_path)
    logger.info(f"[pdf_compressor]   → {len(e1) / 1024 / 1024:.2f} MB")
    if len(e1) <= max_bytes:
        return e1

    # ── Etapa 2 ───────────────────────────────────────────────────────────
    logger.info("[pdf_compressor] Etapa 2: re-render a 96 DPI...")
    e2 = _rerender(pdf_path, dpi=96)
    logger.info(f"[pdf_compressor]   → {len(e2) / 1024 / 1024:.2f} MB")
    if len(e2) <= max_bytes:
        return e2

    # ── Etapas 3/4: clasificar y eliminar páginas ─────────────────────────
    logger.info("[pdf_compressor] Etapa 3: clasificando páginas por texto...")
    doc_orig = fitz.open(str(pdf_path))
    n_total = len(doc_orig)

    # Intentar primero con Gemini; si falla, usar reglas de texto
    gemini_result = _clasificar_paginas_gemini(doc_orig)
    if gemini_result is not None:
        clasificaciones = gemini_result
        logger.info("[pdf_compressor]   Usando clasificación Gemini Vision.")
    else:
        clasificaciones = _clasificar_paginas_reglas(doc_orig)
        logger.info("[pdf_compressor]   Usando clasificación por texto (sin IA).")
    doc_orig.close()

    excluidos: set[int] = set()
    resultado_actual = e2

    for tipo_elim in ORDEN_ELIMINACION:
        if len(resultado_actual) <= max_bytes:
            break

        nuevos: set[int] = set()

        if tipo_elim == "resumen_atencion_extra":
            # Conservar el PRIMER resumen_atencion; los restantes son eliminables
            primer_visto = False
            for idx, clase in enumerate(clasificaciones):
                if idx in excluidos:
                    continue
                if clase == "resumen_atencion":
                    if not primer_visto:
                        primer_visto = True
                    else:
                        nuevos.add(idx)
        else:
            for idx, clase in enumerate(clasificaciones):
                if idx not in excluidos and clase == tipo_elim and tipo_elim not in soportes:
                    nuevos.add(idx)

        if not nuevos:
            continue

        excluidos |= nuevos
        indices_mantener = [i for i in range(n_total) if i not in excluidos]
        candidato = _keep_pages(e2, indices_mantener)

        logger.info(
            f"[pdf_compressor]   Eliminadas {len(nuevos)} pág. tipo '{tipo_elim}' "
            f"→ {len(candidato) / 1024 / 1024:.2f} MB "
            f"(quedan {len(indices_mantener)}/{n_total})"
        )
        resultado_actual = candidato

    mb_final = len(resultado_actual) / 1024 / 1024
    if len(resultado_actual) <= max_bytes:
        logger.info(f"[pdf_compressor] ✅ {mb_final:.2f} MB — dentro del límite.")
    else:
        logger.warning(
            f"[pdf_compressor] ⚠️ Objetivo {max_mb} MB no alcanzado. "
            f"Mejor resultado: {mb_final:.2f} MB"
        )

    return resultado_actual
