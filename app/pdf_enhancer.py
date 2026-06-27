"""
PDF Enhancer v2 — Mejora HD para incapacidades médicas (IncaNeurobaeza)
========================================================================
Pipeline gratuito, mejores herramientas 2026 para DOCUMENTOS DE TEXTO
(no fotos artísticas). Pensado para correr en Railway (CPU, sin GPU).

DOS MODOS:
  - mode="fast" : solo OpenCV (CPU, ~1-3 s/página). Para AUTO al subir.
  - mode="hd"   : OpenCV + Real-ESRGAN 4x-UltraSharp (lento sin GPU).
                  Solo para el BOTÓN MANUAL de respaldo, docs cortos.

INCLUYE:
  - Auto-orientación: detecta si el soporte está volteado (90/180/270)
    y lo endereza  -> Tesseract OSD (gratis).
  - Deskew: corrige inclinación fina del papel escaneado.
  - Detección de tipo (foto celular / escaneado / digital) + preproceso adaptativo.
  - Color-safe: NO destruye sellos, firmas ni fotos de cédula
    (trabaja el contraste en el canal de luminancia LAB).
  - needs_enhancement(): decide si vale la pena mejorar (para el auto al subir).

INSTALACIÓN (Railway / Linux):
    pip install opencv-python-headless pillow pdf2image img2pdf numpy --break-system-packages
    apt install poppler-utils tesseract-ocr        # poppler obligatorio, tesseract para auto-orientación
    # SOLO si se quiere modo "hd":
    pip install realesrgan basicsr torch torchvision --break-system-packages
    # y descargar el modelo 4x-UltraSharp a la ruta MODEL_PATH:
    # https://huggingface.co/uwg/upscaler/blob/main/ESRGAN/4x-UltraSharp.pth

USO:
    from pdf_enhancer import PDFEnhancer
    enhancer = PDFEnhancer(mode="fast")
    pdf_hd_bytes = enhancer.enhance_bytes(pdf_bytes)        # bytes -> bytes
    enhancer.enhance("in.pdf", "out_HD.pdf")                # archivo -> archivo
"""

import io
import os
import logging
import numpy as np
import cv2
from PIL import Image, ImageFilter
from pdf2image import convert_from_path, convert_from_bytes
import img2pdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("pdf_enhancer")

MODEL_PATH = os.environ.get("ULTRASHARP_MODEL_PATH", "4x-UltraSharp.pth")


# ════════════════════════════════════════════════════════════════════
# 0) AUTO-ORIENTACIÓN — ¿el soporte está volteado? (Tesseract OSD)
# ════════════════════════════════════════════════════════════════════

def detect_orientation(image_np: np.ndarray) -> int:
    """
    Devuelve los grados que hay que rotar EN SENTIDO HORARIO para enderezar
    (0, 90, 180 o 270). Usa Tesseract OSD. Si no está instalado -> 0.
    """
    try:
        import pytesseract
        gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY)
        osd = pytesseract.image_to_osd(gray, output_type=pytesseract.Output.DICT)
        return int(osd.get("rotate", 0)) % 360
    except Exception as e:
        log.debug(f"OSD no disponible (auto-orientación omitida): {e}")
        return 0


def correct_orientation(image_np: np.ndarray) -> np.ndarray:
    """Endereza documentos volteados 90/180/270 grados."""
    rotate = detect_orientation(image_np)
    if rotate == 90:
        log.info("Soporte volteado 90° -> corrigiendo")
        return cv2.rotate(image_np, cv2.ROTATE_90_CLOCKWISE)
    if rotate == 180:
        log.info("Soporte al revés 180° -> corrigiendo")
        return cv2.rotate(image_np, cv2.ROTATE_180)
    if rotate == 270:
        log.info("Soporte volteado 270° -> corrigiendo")
        return cv2.rotate(image_np, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return image_np


# ════════════════════════════════════════════════════════════════════
# 1) DESKEW — corrige inclinación fina (sellos/firmas torcidos)
# ════════════════════════════════════════════════════════════════════

def deskew(image_np: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY)
    thresh = cv2.threshold(cv2.bitwise_not(gray), 0, 255,
                           cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thresh > 0))
    if len(coords) == 0:
        return image_np
    angle = cv2.minAreaRect(coords)[-1]
    angle = -(90 + angle) if angle < -45 else -angle
    if abs(angle) < 0.5:          # inclinación insignificante: no tocar
        return image_np
    if abs(angle) > 20:           # ángulo enorme = lo maneja la auto-orientación
        return image_np
    (h, w) = image_np.shape[:2]
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    return cv2.warpAffine(image_np, M, (w, h),
                          flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


# ════════════════════════════════════════════════════════════════════
# 2) DETECCIÓN DE TIPO Y DE CALIDAD
# ════════════════════════════════════════════════════════════════════

def detect_pdf_type(page_pil: Image.Image) -> str:
    """photo (foto celular) | scan (escaneado) | digital (PDF baja res)."""
    img = np.array(page_pil.convert("L"))
    variance = cv2.Laplacian(img, cv2.CV_64F).var()
    mean_val = img.mean()
    if variance < 50:
        return "digital"
    if mean_val < 200 and variance > 200:
        return "photo"
    return "scan"


def needs_enhancement(page_pil: Image.Image,
                      min_sharpness: float = 120.0,
                      min_width: int = 1000) -> bool:
    """
    ¿Vale la pena mejorar esta página? (para el AUTO al subir).
    True si está borrosa o de baja resolución.
    """
    img = np.array(page_pil.convert("L"))
    sharpness = cv2.Laplacian(img, cv2.CV_64F).var()
    width = page_pil.width
    return sharpness < min_sharpness or width < min_width


# ════════════════════════════════════════════════════════════════════
# 3) PREPROCESO COLOR-SAFE (no destruye sellos/firmas/fotos)
# ════════════════════════════════════════════════════════════════════

def enhance_color_safe(image_np: np.ndarray, doc_type: str) -> np.ndarray:
    """
    Mejora contraste y nitidez SIN binarizar -> conserva el color de
    sellos, firmas y la foto de la cédula (críticos para validar).
    Trabaja la luminancia en espacio LAB.
    """
    lab = cv2.cvtColor(image_np, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    clip = {"photo": 3.0, "scan": 2.0, "digital": 1.5}.get(doc_type, 2.0)
    clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8))
    l = clahe.apply(l)

    merged = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)

    # Denoise que preserva color
    if doc_type == "photo":
        merged = cv2.fastNlMeansDenoisingColored(merged, None, 7, 7, 7, 21)
    elif doc_type == "scan":
        merged = cv2.fastNlMeansDenoisingColored(merged, None, 5, 5, 7, 21)

    # Sharpen suave (unsharp mask)
    blur = cv2.GaussianBlur(merged, (0, 0), 3)
    merged = cv2.addWeighted(merged, 1.5, blur, -0.5, 0)
    return merged


def binarize_bw(image_np: np.ndarray) -> np.ndarray:
    """
    Binarización adaptativa (texto negro / fondo blanco).
    OPCIONAL: solo para documentos de PURO texto impreso sin sellos
    de color ni fotos. Por defecto NO se usa (puede borrar sellos).
    """
    gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, 31, 10)
    return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)


# ════════════════════════════════════════════════════════════════════
# 4) UPSCALE IA (modo "hd") — Real-ESRGAN 4x-UltraSharp
# ════════════════════════════════════════════════════════════════════

def load_ultrasharp_upscaler(model_path: str):
    try:
        from basicsr.archs.rrdbnet_arch import RRDBNet
        from realesrgan import RealESRGANer
        model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64,
                        num_block=23, num_grow_ch=32, scale=4)
        sampler = RealESRGANer(scale=4, model_path=model_path, model=model,
                               tile=512, tile_pad=16, pre_pad=0, half=False)
        log.info("Modelo 4x-UltraSharp cargado")
        return sampler
    except Exception as e:
        log.warning(f"Real-ESRGAN no disponible ({e}); usando upscale cúbico OpenCV")
        return None


def upscale(image_np: np.ndarray, upsampler, factor_cpu: int = 2) -> np.ndarray:
    if upsampler is not None:
        try:
            out, _ = upsampler.enhance(image_np, outscale=4)
            return out
        except Exception as e:
            log.warning(f"Falló Real-ESRGAN ({e}); fallback cúbico")
    h, w = image_np.shape[:2]
    return cv2.resize(image_np, (w * factor_cpu, h * factor_cpu),
                      interpolation=cv2.INTER_CUBIC)


# ════════════════════════════════════════════════════════════════════
# 5) CLASE PRINCIPAL
# ════════════════════════════════════════════════════════════════════

class PDFEnhancer:
    def __init__(self, mode: str = "fast", dpi: int = 200,
                 auto_orientation: bool = True, binarize: bool = False,
                 model_path: str = MODEL_PATH):
        """
        mode: "fast" (OpenCV) | "hd" (Real-ESRGAN si está disponible).
        binarize: True solo para texto puro impreso (riesgo: borra sellos color).
        """
        self.mode = mode
        self.dpi = dpi
        self.auto_orientation = auto_orientation
        self.binarize = binarize
        self.upsampler = None
        if mode == "hd":
            if os.path.exists(model_path):
                self.upsampler = load_ultrasharp_upscaler(model_path)
            else:
                log.warning(f"Modelo HD no encontrado en '{model_path}'. "
                            "Usando upscale cúbico OpenCV como respaldo.")

    def enhance_page(self, page_pil: Image.Image) -> Image.Image:
        doc_type = detect_pdf_type(page_pil)
        img = cv2.cvtColor(np.array(page_pil.convert("RGB")), cv2.COLOR_RGB2BGR)

        if self.auto_orientation:
            img = correct_orientation(img)   # voltear soporte si está al revés
        img = deskew(img)                     # enderezar inclinación fina

        if self.binarize and doc_type != "photo":
            img = binarize_bw(img)
        else:
            img = enhance_color_safe(img, doc_type)

        if self.mode == "hd":
            img = upscale(img, self.upsampler)
        else:
            h, w = img.shape[:2]
            img = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)

        result = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        return result.filter(ImageFilter.SHARPEN)

    def enhance_bytes(self, pdf_bytes: bytes, only_if_needed: bool = False) -> bytes:
        """
        Mejora un PDF en memoria (bytes -> bytes).
        only_if_needed=True: solo mejora páginas borrosas/baja-res (auto al subir).
        Si NINGUNA página lo necesita, devuelve los bytes originales sin tocar.
        """
        pages = convert_from_bytes(pdf_bytes, dpi=self.dpi)
        if only_if_needed and not any(needs_enhancement(p) for p in pages):
            log.info("Calidad ya buena -> no se modifica")
            return pdf_bytes

        out = []
        for i, page in enumerate(pages):
            log.info(f"Mejorando página {i + 1}/{len(pages)} [{self.mode}]")
            buf = io.BytesIO()
            self.enhance_page(page).save(buf, format="PNG", optimize=False)
            out.append(buf.getvalue())
        return img2pdf.convert(out)

    def enhance(self, input_path: str, output_path: str) -> str:
        pages = convert_from_path(str(input_path), dpi=self.dpi)
        out = []
        for i, page in enumerate(pages):
            log.info(f"Mejorando página {i + 1}/{len(pages)} [{self.mode}]")
            buf = io.BytesIO()
            self.enhance_page(page).save(buf, format="PNG", optimize=False)
            out.append(buf.getvalue())
        with open(output_path, "wb") as f:
            f.write(img2pdf.convert(out))
        return str(output_path)


# ════════════════════════════════════════════════════════════════════
# 6) SINGLETONS (cachear para no recargar el modelo en cada request)
# ════════════════════════════════════════════════════════════════════

_enhancer_fast = None
_enhancer_hd = None

def get_enhancer(mode: str = "fast") -> PDFEnhancer:
    global _enhancer_fast, _enhancer_hd
    if mode == "hd":
        if _enhancer_hd is None:
            _enhancer_hd = PDFEnhancer(mode="hd", dpi=200)
        return _enhancer_hd
    if _enhancer_fast is None:
        _enhancer_fast = PDFEnhancer(mode="fast", dpi=200)
    return _enhancer_fast


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Uso: python pdf_enhancer.py in.pdf out_HD.pdf [fast|hd]")
        sys.exit(1)
    m = sys.argv[3] if len(sys.argv) > 3 else "fast"
    PDFEnhancer(mode=m).enhance(sys.argv[1], sys.argv[2])
    print(f"OK -> {sys.argv[2]}")
