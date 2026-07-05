"""
PDF Enhancer v3 — Mejora HD híbrida para incapacidades médicas (IncaNeurobaeza)
================================================================================
Combina LO MEJOR de los dos enfoques, decidiendo automáticamente por página:

  • Página de PURO TEXTO  -> binarización ultra-limpia (look HD blanco/negro)
                             [hereda el mejorador original de pdf_editor.py,
                              "inspirado en artguru.ai pero optimizado para texto"]
  • Página con SELLO de color / foto de cédula / firma de color
                          -> modo color-safe (conserva el color, no lo aplana)

Más: auto-orientación (documento volteado 90/180/270), deskew (inclinación fina),
needs_enhancement() para la auto-mejora al subir (solo si está borroso/baja-res).

100% OpenCV en CPU -> NO necesita API, NI GPU, NI descargar modelos.
(El modo "hd" con Real-ESRGAN es opcional y solo se usa si está instalado.)

NIVELES de escala (los mismos del mejorador original):
    rapido = 1.8x     estandar = 2.5x     premium = 3.5x

MODOS:
    auto  -> decide por página: binariza texto puro, conserva sellos/fotos
    bw    -> forzar blanco/negro limpio en todo
    color -> forzar conservar color en todo
    hd    -> Real-ESRGAN 4x-UltraSharp (si está instalado) + color-safe

COMPATIBILIDAD v2 (no romper código existente):
    get_enhancer("fast")  -> nivel="rapido",   modo="auto"
    get_enhancer("hd")    -> nivel="estandar", modo="hd"
    enhance_bytes(..., only_if_needed=True) sigue funcionando igual.

INSTALACIÓN (Railway / Linux):
    pip install opencv-python-headless pillow pdf2image img2pdf numpy --break-system-packages
    apt install poppler-utils tesseract-ocr
    # opcional modo "hd": pip install realesrgan basicsr torch torchvision

USO:
    from app.pdf_enhancer import PDFEnhancer, get_enhancer
    enh = get_enhancer(nivel="estandar", mode="auto")
    pdf_hd = enh.enhance_bytes(pdf_bytes)          # bytes -> bytes
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

# Niveles -> factor de upscale (los mismos que el mejorador original)
NIVELES = {"rapido": 1.8, "estandar": 2.5, "premium": 3.5}

# Mapeo de los modos legacy v2 -> (nivel, modo) v3
LEGACY_MODES = {"fast": ("rapido", "auto"), "hd": ("estandar", "hd")}


# ════════════════════════════════════════════════════════════════════
# DETECCIÓN: ¿esta página tiene color que vale la pena conservar?
# (sellos azules/rojos, foto de la cédula, firmas de color)
# ════════════════════════════════════════════════════════════════════

def has_significant_color(image_np: np.ndarray, sat_thresh: int = 35,
                          val_thresh: int = 40, min_fraction: float = 0.005) -> bool:
    """
    True si hay suficientes píxeles de color (sello/foto) como para NO binarizar.
    Un escaneo gris de texto tiene saturación ~0 -> devuelve False -> se binariza.
    """
    if len(image_np.shape) == 2:
        return False
    hsv = cv2.cvtColor(image_np, cv2.COLOR_BGR2HSV)
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    colored = (s > sat_thresh) & (v > val_thresh)
    fraction = float(np.count_nonzero(colored)) / colored.size
    return fraction >= min_fraction


# ════════════════════════════════════════════════════════════════════
# AUTO-ORIENTACIÓN (Tesseract OSD) + DESKEW
# ════════════════════════════════════════════════════════════════════

def correct_orientation(image_np: np.ndarray) -> np.ndarray:
    """Endereza documentos volteados 90/180/270 grados (Tesseract OSD)."""
    try:
        import pytesseract
        gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY) if image_np.ndim == 3 else image_np
        osd = pytesseract.image_to_osd(gray, output_type=pytesseract.Output.DICT)
        r = int(osd.get("rotate", 0)) % 360
        if r == 90:
            log.info("Soporte volteado 90° -> corrigiendo")
            return cv2.rotate(image_np, cv2.ROTATE_90_CLOCKWISE)
        if r == 180:
            log.info("Soporte al revés 180° -> corrigiendo")
            return cv2.rotate(image_np, cv2.ROTATE_180)
        if r == 270:
            log.info("Soporte volteado 270° -> corrigiendo")
            return cv2.rotate(image_np, cv2.ROTATE_90_COUNTERCLOCKWISE)
    except Exception as e:
        log.debug(f"OSD no disponible (auto-orientación omitida): {e}")
    return image_np


def deskew(image_np: np.ndarray) -> np.ndarray:
    """Corrige inclinación fina del papel escaneado."""
    gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY) if image_np.ndim == 3 else image_np
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
# DETECCIÓN DE TIPO Y DE CALIDAD (para la auto-mejora al subir)
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
# RUTA A — PURO TEXTO -> binarización ultra-limpia (look HD del original)
# Replica el pipeline de pdf_editor.py (enhance_image_quality) + mejoras.
# ════════════════════════════════════════════════════════════════════

def enhance_clean_bw(image_np: np.ndarray, scale: float) -> np.ndarray:
    gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY) if image_np.ndim == 3 else image_np

    # 1. Denoise
    den = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)
    # 2. CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enh = clahe.apply(den)
    # 3. Sharpen
    kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
    sharp = cv2.filter2D(enh, -1, kernel)
    # 4. Corrección de iluminación desigual (resta de fondo) -> el "truco" del original
    dilated = cv2.dilate(sharp, np.ones((7, 7), np.uint8))
    bg = cv2.medianBlur(dilated, 21)
    diff = 255 - cv2.absdiff(sharp, bg)
    norm = cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8UC1)
    # 5. Binarización adaptativa -> texto negro / fondo blanco puro
    binary = cv2.adaptiveThreshold(norm, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, 11, 2)
    # 6. Limpieza morfológica
    cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    # 7. Upscale bicúbico al factor del nivel
    h, w = cleaned.shape
    up = cv2.resize(cleaned, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
    # 8. Anti-aliasing suave
    return cv2.GaussianBlur(up, (3, 3), 0)


# ════════════════════════════════════════════════════════════════════
# RUTA B — HAY COLOR -> conservar sellos/foto, solo mejorar y subir res
# ════════════════════════════════════════════════════════════════════

def enhance_color_keep(image_np: np.ndarray, scale: float, doc_type: str = "scan") -> np.ndarray:
    # CLAHE solo en luminancia (LAB) para no alterar los colores
    lab = cv2.cvtColor(image_np, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clip = {"photo": 3.0, "scan": 2.0, "digital": 1.5}.get(doc_type, 2.0)
    l = cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8)).apply(l)
    out = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
    # Denoise que preserva color (más fuerte en fotos de celular)
    if doc_type == "photo":
        out = cv2.fastNlMeansDenoisingColored(out, None, 7, 7, 7, 21)
    else:
        out = cv2.fastNlMeansDenoisingColored(out, None, 5, 5, 7, 21)
    # Unsharp mask (nitidez sin halos)
    blur = cv2.GaussianBlur(out, (0, 0), 3)
    out = cv2.addWeighted(out, 1.5, blur, -0.5, 0)
    # Upscale bicúbico
    h, w = out.shape[:2]
    return cv2.resize(out, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)


# ════════════════════════════════════════════════════════════════════
# UPSCALE IA EN LA NUBE (modo "hd") — Real-ESRGAN en GPU vía Replicate
# La misma tecnología de Artguru: redibuja la imagen borrosa en HD.
# Se activa solo si existe REPLICATE_API_TOKEN (variable en Railway).
# Costo aprox: < US$0.01 por página; tarda segundos en GPU.
# ════════════════════════════════════════════════════════════════════

REPLICATE_TOKEN = os.environ.get("REPLICATE_API_TOKEN", "")
REPLICATE_MODEL = os.environ.get(
    "REPLICATE_ESRGAN_MODEL",
    "nightmareai/real-esrgan:f121d640bd286e1fdc67f9799164c1d5be36ff74576ee11e803ae5f665dd97aa",
)

def upscale_replicate(page_pil: Image.Image, scale: int = 2):
    """
    Mejora una página con Real-ESRGAN en GPU (Replicate) y la devuelve en HD.
    Devuelve None si no hay token o si algo falla -> el caller usa el fallback.
    scale=2 sobre el render de 200 dpi ≈ 400 dpi efectivos (suficiente y liviano).
    """
    if not REPLICATE_TOKEN:
        return None
    try:
        import replicate
        buf = io.BytesIO()
        page_pil.convert("RGB").save(buf, format="PNG")
        buf.seek(0)
        buf.name = "pagina.png"
        out = replicate.run(
            REPLICATE_MODEL,
            input={"image": buf, "scale": scale, "face_enhance": False},
        )
        if hasattr(out, "read"):        # FileOutput (cliente replicate >= 1.0)
            data = out.read()
        else:                            # URL (clientes anteriores)
            import requests
            data = requests.get(str(out), timeout=120).content
        log.info("Página mejorada con Real-ESRGAN en Replicate (GPU)")
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as e:
        log.warning(f"Replicate no disponible ({e}); se usará el pipeline local")
        return None


# ════════════════════════════════════════════════════════════════════
# UPSCALE IA LOCAL OPCIONAL (modo "hd") — Real-ESRGAN 4x-UltraSharp
# ════════════════════════════════════════════════════════════════════

def load_ultrasharp(model_path: str):
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
        log.warning(f"Real-ESRGAN no disponible ({e}); se usará OpenCV")
        return None


# ════════════════════════════════════════════════════════════════════
# CLASE PRINCIPAL
# ════════════════════════════════════════════════════════════════════

class PDFEnhancer:
    def __init__(self, nivel: str = "estandar", auto_orientation: bool = True,
                 mode: str = "auto", model_path: str = MODEL_PATH, dpi: int = 200):
        """
        nivel: "rapido" (1.8x) | "estandar" (2.5x) | "premium" (3.5x)
               (acepta también los legacy "fast"/"hd" y los mapea)
        mode:  "auto" -> decide BW vs color por página (recomendado)
               "bw"   -> forzar blanco/negro limpio en todo
               "color"-> forzar conservar color en todo
               "hd"   -> Real-ESRGAN (si está instalado) + color-safe
        """
        if nivel in LEGACY_MODES:          # compat v2: PDFEnhancer(mode="fast"|"hd")
            nivel, mode = LEGACY_MODES[nivel]
        self.scale = NIVELES.get(nivel, 2.5)
        self.nivel = nivel
        self.mode = mode
        self.auto_orientation = auto_orientation
        self.dpi = dpi
        self.upsampler = None
        if mode == "hd":
            if os.path.exists(model_path):
                self.upsampler = load_ultrasharp(model_path)
            elif not REPLICATE_TOKEN:
                log.warning(f"Modo hd sin REPLICATE_API_TOKEN ni modelo local en "
                            f"'{model_path}'. Se usará el pipeline OpenCV como respaldo.")

    def enhance_page(self, page_pil: Image.Image) -> Image.Image:
        doc_type = detect_pdf_type(page_pil)
        img = cv2.cvtColor(np.array(page_pil.convert("RGB")), cv2.COLOR_RGB2BGR)

        if self.auto_orientation:
            img = correct_orientation(img)
        img = deskew(img)

        # Modo HD con IA: 1º Replicate (GPU nube, calidad Artguru),
        #                 2º Real-ESRGAN local, 3º pipeline OpenCV (abajo)
        if self.mode == "hd":
            hd = upscale_replicate(Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
            if hd is not None:
                # Ya viene nítida del modelo; sin sharpen extra para máxima fidelidad
                return hd
            if self.upsampler is not None:
                try:
                    out, _ = self.upsampler.enhance(img, outscale=4)
                    res = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
                    return res.filter(ImageFilter.SHARPEN)
                except Exception as e:
                    log.warning(f"Falló Real-ESRGAN local ({e}); fallback al pipeline OpenCV")

        # Decidir ruta
        if self.mode == "bw":
            use_color = False
        elif self.mode in ("color", "hd"):
            use_color = True
        else:  # auto
            use_color = has_significant_color(img)

        if use_color:
            out = enhance_color_keep(img, self.scale, doc_type)
            mode_used = "color"
        else:
            out = enhance_clean_bw(img, self.scale)
            mode_used = "bw-limpio"
        log.info(f"Página procesada [{mode_used}, {self.scale}x, {doc_type}]")

        if out.ndim == 2:
            res = Image.fromarray(out)
        else:
            res = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
        return res.filter(ImageFilter.SHARPEN)

    def _build(self, pages) -> bytes:
        out = []
        for i, page in enumerate(pages):
            log.info(f"Mejorando página {i + 1}/{len(pages)} [{self.nivel}/{self.mode}]")
            buf = io.BytesIO()
            self.enhance_page(page).save(buf, format="PNG", optimize=False)
            out.append(buf.getvalue())
        return img2pdf.convert(out)

    def enhance_bytes(self, pdf_bytes: bytes, only_if_needed: bool = False) -> bytes:
        """
        Mejora un PDF en memoria (bytes -> bytes).
        only_if_needed=True: solo mejora si hay páginas borrosas/baja-res (auto al subir).
        Si NINGUNA página lo necesita, devuelve los bytes originales sin tocar.
        """
        pages = convert_from_bytes(pdf_bytes, dpi=self.dpi)
        if only_if_needed and not any(needs_enhancement(p) for p in pages):
            log.info("Calidad ya buena -> no se modifica")
            return pdf_bytes
        return self._build(pages)

    def enhance(self, input_path: str, output_path: str) -> str:
        data = self._build(convert_from_path(str(input_path), dpi=self.dpi))
        with open(output_path, "wb") as f:
            f.write(data)
        return str(output_path)


# ════════════════════════════════════════════════════════════════════
# SINGLETONS por (nivel, modo) — no recargar nada en cada request
# ════════════════════════════════════════════════════════════════════

_cache = {}

def get_enhancer(nivel: str = "estandar", mode: str = "auto") -> PDFEnhancer:
    if nivel in LEGACY_MODES:              # compat v2: get_enhancer("fast"|"hd")
        nivel, mode = LEGACY_MODES[nivel]
    key = (nivel, mode)
    if key not in _cache:
        _cache[key] = PDFEnhancer(nivel=nivel, mode=mode)
    return _cache[key]


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Uso: python pdf_enhancer.py in.pdf out_HD.pdf [rapido|estandar|premium]")
        sys.exit(1)
    nivel = sys.argv[3] if len(sys.argv) > 3 else "estandar"
    PDFEnhancer(nivel=nivel).enhance(sys.argv[1], sys.argv[2])
    print(f"OK -> {sys.argv[2]}")
