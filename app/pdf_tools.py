"""
Herramientas de edición de PDF para operaciones básicas usadas por el validador.
Soporta rotación, mejora de calidad, filtros simples, recorte automático y deskew.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional

import io
import numpy as np
import fitz  # PyMuPDF
from PIL import Image
import cv2


def _page_to_numpy(page, scale: float = 2.0) -> np.ndarray:
    """Renderiza una página a un numpy array (BGR)."""
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat)
    n_channels = 4 if pix.alpha else 3
    arr = np.frombuffer(pix.samples, dtype=np.uint8)
    arr = arr.reshape(pix.height, pix.width, n_channels)
    # Convertir RGBA/RGB a BGR
    if n_channels == 4:
        arr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
    else:
        arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    return arr


def _numpy_to_png_bytes(img: np.ndarray) -> bytes:
    """Convierte numpy (BGR) a PNG bytes."""
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb)
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def enhance_image_quality(img: np.ndarray) -> np.ndarray:
    """Mejora básica de calidad para documentos (desruido, contraste, nitidez)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    denoised = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(denoised)
    kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
    sharpened = cv2.filter2D(enhanced, -1, kernel)
    return cv2.cvtColor(sharpened, cv2.COLOR_GRAY2BGR)


def auto_deskew(img: np.ndarray) -> np.ndarray:
    """Corrige inclinación aproximada mediante HoughLines."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, np.pi / 180.0, 200)
    if lines is None:
        return img
    angles = []
    for l in lines:
        rho, theta = l[0]
        angles.append(np.degrees(theta) - 90)
    if not angles:
        return img
    median_angle = float(np.median(angles))
    if abs(median_angle) < 0.5:
        return img
    (h, w) = gray.shape
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    rotated = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return rotated


def smart_crop(img: np.ndarray, margin: int = 10) -> np.ndarray:
    """Recorte automático eliminando bordes vacíos."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return img
    cnt = np.concatenate(contours)
    x, y, w, h = cv2.boundingRect(cnt)
    x = max(0, x - margin)
    y = max(0, y - margin)
    w = min(img.shape[1] - x, w + 2 * margin)
    h = min(img.shape[0] - y, h + 2 * margin)
    return img[y : y + h, x : x + w]


def apply_filter(img: np.ndarray, filtro: str) -> np.ndarray:
    """Aplica filtros básicos: grayscale, contrast, brightness, sharpen."""
    filtro = (filtro or "").lower()
    if filtro == "grayscale":
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    if filtro == "contrast":
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        merged = cv2.merge([l, a, b])
        return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
    if filtro == "brightness":
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)
        v = cv2.add(v, 30)
        merged = cv2.merge([h, s, v])
        return cv2.cvtColor(merged, cv2.COLOR_HSV2BGR)
    if filtro == "sharpen":
        kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
        return cv2.filter2D(img, -1, kernel)
    return img


def edit_pdf(pdf_in: Path, operaciones: Dict[str, Any], pdf_out: Optional[Path] = None) -> Path:
    """
    Aplica operaciones al PDF.
    - operaciones puede contener:
      - rotate: List[{"page_num": int, "angle": int}]
      - enhance_quality: {"pages": List[int]}
      - aplicar_filtro: {"page_num": int, "filtro": str}
      - crop_auto: List[{"page_num": int, "margin": int}]
      - deskew: {"page_num": int}
    """
    pdf_in = Path(pdf_in)
    pdf_out = Path(pdf_out) if pdf_out else pdf_in.parent / f"{pdf_in.stem}_editado.pdf"

    doc = fitz.open(str(pdf_in))

    # Rotación
    for rot in (operaciones.get("rotate") or []):
        try:
            page = doc[int(rot.get("page_num", 0))]
            angle = int(rot.get("angle", 0)) % 360
            page.set_rotation(angle)
        except Exception:
            continue

    # Mejora de calidad
    eq = operaciones.get("enhance_quality") or {}
    for p in (eq.get("pages") or []):
        try:
            page = doc[int(p)]
            img = _page_to_numpy(page, scale=3.0)
            img = enhance_image_quality(img)
            img = auto_deskew(img)
            png = _numpy_to_png_bytes(img)
            rect = page.rect
            page.clean_contents()
            page.insert_image(rect, stream=png)
        except Exception:
            continue

    # Filtros
    af = operaciones.get("aplicar_filtro") or {}
    if af:
        try:
            page = doc[int(af.get("page_num", 0))]
            img = _page_to_numpy(page, scale=3.0)
            img = apply_filter(img, str(af.get("filtro", "")))
            png = _numpy_to_png_bytes(img)
            rect = page.rect
            page.clean_contents()
            page.insert_image(rect, stream=png)
        except Exception:
            pass

    # Recorte automático
    for ca in (operaciones.get("crop_auto") or []):
        try:
            page = doc[int(ca.get("page_num", 0))]
            img = _page_to_numpy(page, scale=2.0)
            cropped = smart_crop(img, margin=int(ca.get("margin", 10)))
            png = _numpy_to_png_bytes(cropped)
            rect = page.rect
            page.clean_contents()
            page.insert_image(rect, stream=png)
        except Exception:
            continue

    # Deskew individual
    ds = operaciones.get("deskew") or {}
    if ds:
        try:
            page = doc[int(ds.get("page_num", 0))]
            img = _page_to_numpy(page, scale=3.0)
            img = auto_deskew(img)
            png = _numpy_to_png_bytes(img)
            rect = page.rect
            page.clean_contents()
            page.insert_image(rect, stream=png)
        except Exception:
            pass

    doc.save(str(pdf_out), garbage=4, deflate=True, clean=True)
    doc.close()
    return pdf_out
