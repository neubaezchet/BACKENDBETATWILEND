"""
╔══════════════════════════════════════════════════════════════════╗
║           TEST LOCAL — Flujo completo OCR → Plano IA            ║
║   Mistral OCR  →  extracción de texto  →  Gemini extrae campos  ║
╚══════════════════════════════════════════════════════════════════╝

Uso:
    python test_plano_local.py soporte.pdf
    python test_plano_local.py foto_incapacidad.jpg
    python test_plano_local.py carpeta/con/varios/  (procesa todos los PDF/JPG)

Necesita en el entorno (o en .env):
    MISTRAL_API_KEY=...
    GEMINI_API_KEY=...
"""

import sys
import json
import base64
import os
import time
from pathlib import Path
from dotenv import load_dotenv

# ── Cargar .env ────────────────────────────────────────────────────────────────
load_dotenv()

# ── Colores ANSI ───────────────────────────────────────────────────────────────
R  = "\033[91m"   # rojo
G  = "\033[92m"   # verde
Y  = "\033[93m"   # amarillo
B  = "\033[94m"   # azul
C  = "\033[96m"   # cyan
W  = "\033[97m"   # blanco
DIM = "\033[2m"   # gris
BOLD = "\033[1m"
RST = "\033[0m"   # reset

EXTENSIONES_VALIDAS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif"}

# ── Ayudas visuales ────────────────────────────────────────────────────────────
def titulo(texto):
    linea = "═" * (len(texto) + 4)
    print(f"\n{BOLD}{C}╔{linea}╗")
    print(f"║  {texto}  ║")
    print(f"╚{linea}╝{RST}")

def seccion(texto):
    print(f"\n{BOLD}{B}── {texto} {'─' * max(0, 50 - len(texto))}{RST}")

def ok(texto):
    print(f"  {G}✅{RST}  {texto}")

def warn(texto):
    print(f"  {Y}⚠️ {RST}  {texto}")

def error(texto):
    print(f"  {R}❌{RST}  {texto}")

def campo(nombre, valor, ancho=22):
    if valor and str(valor).strip() and str(valor).strip() not in ("0", ""):
        print(f"  {C}{nombre:<{ancho}}{RST}  {BOLD}{W}{valor}{RST}")
    else:
        print(f"  {DIM}{nombre:<{ancho}}  —{RST}")


# ══════════════════════════════════════════════════════════════════════════════
#  PASO 1: OCR (Mistral)
# ══════════════════════════════════════════════════════════════════════════════
def paso_ocr(archivo: Path) -> dict:
    """Corre Mistral OCR sobre el archivo. Soporta PDF e imágenes."""
    from app.mistral_ocr_service import MistralDocumentAIOCR

    servicio = MistralDocumentAIOCR()
    ext = archivo.suffix.lower()

    if ext == ".pdf":
        pdf_b64 = base64.b64encode(archivo.read_bytes()).decode()
        resultado = servicio.procesar_pdf_base64(pdf_b64)
    else:
        # Imagen directa (jpg, png, etc.)
        mime_map = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp",
            ".tiff": "image/tiff", ".tif": "image/tiff",
        }
        mime = mime_map.get(ext, "image/jpeg")
        img_b64 = base64.b64encode(archivo.read_bytes()).decode()
        resultado = servicio.procesar_imagen_base64(img_b64, tipo_mime=mime)

    return resultado


# ══════════════════════════════════════════════════════════════════════════════
#  PASO 2: Gemini Plano
# ══════════════════════════════════════════════════════════════════════════════
def paso_gemini(texto_ocr: str) -> dict:
    from app.gemini_plano_service import GeminiPlanoService
    servicio = GeminiPlanoService()
    return servicio.estructurar_plano(texto_ocr)


# ══════════════════════════════════════════════════════════════════════════════
#  MOSTRAR RESULTADO
# ══════════════════════════════════════════════════════════════════════════════
def mostrar_resultado(archivo: Path, res_ocr: dict, res_gemini: dict):
    titulo(f"RESULTADO: {archivo.name}")

    # ── OCR ──
    seccion("MISTRAL OCR")
    if res_ocr.get("exito"):
        ok(f"Páginas procesadas  : {res_ocr.get('paginas', '?')}")
        ok(f"Modelo OCR          : {res_ocr.get('modelo', '?')}")
        chars = len(res_ocr.get("texto", ""))
        ok(f"Caracteres extraídos: {chars:,}")
        tablas_por_pag = [len(p.get("tables", [])) for p in res_ocr.get("raw_pages", [])]
        total_tablas = sum(tablas_por_pag)
        if total_tablas:
            ok(f"Tablas detectadas   : {total_tablas}  (por página: {tablas_por_pag})")
        else:
            ok("Tablas detectadas   : ninguna (texto plano o foto sin tabla estructurada)")
    else:
        error(f"OCR falló: {res_ocr.get('error')}")
        return

    # ── Texto OCR crudo ──
    seccion("TEXTO OCR EXTRAÍDO (primeros 800 chars)")
    texto = res_ocr.get("texto", "")
    print(f"{DIM}{texto[:800]}{'…' if len(texto) > 800 else ''}{RST}")

    # ── Gemini ──
    seccion("GEMINI — CAMPOS EXTRAÍDOS")
    if res_gemini.get("exito"):
        ok(f"Modelo Gemini: {res_gemini.get('modelo', '?')}")
        plano = res_gemini.get("plano", {})
        print()
        campo("tipo_documento",      plano.get("tipo_documento"))
        campo("numero_documento",    plano.get("numero_documento"))
        campo("eps",                 plano.get("eps"))
        campo("empresa",             plano.get("empresa"))
        campo("dias_incapacidad",    plano.get("dias_incapacidad"))
        campo("fecha_inicio",        plano.get("fecha_inicio"))
        campo("fecha_fin",           plano.get("fecha_fin"))
        campo("medico",              plano.get("medico"))
        campo("registro_medico",     plano.get("registro_medico"))
        campo("lugar_atencion",      plano.get("lugar_atencion"))
        campo("nit_lugar_atencion",  plano.get("nit_lugar_atencion"))
        campo("diagnostico",         plano.get("diagnostico"))
        campo("codigo_cie10",        plano.get("codigo_cie10"))
        campo("origen",              plano.get("origen"))
        campo("tipo_incapacidad",    plano.get("tipo_incapacidad"))

        # Resumen de campos vacíos
        vacios = [k for k, v in plano.items() if not v or str(v).strip() in ("0", "")]
        llenos = [k for k, v in plano.items() if v and str(v).strip() not in ("0", "")]
        print()
        ok(f"Campos extraídos : {len(llenos)}")
        if vacios:
            warn(f"Campos vacíos    : {len(vacios)}  → {', '.join(vacios)}")
    else:
        error(f"Gemini falló: {res_gemini.get('error')}")
        if res_gemini.get("plano") == {}:
            warn("El texto OCR puede ser muy corto o ilegible para Gemini")

    # ── Vista dashboard ──
    seccion("ASÍ APARECE EN EL DASHBOARD (tabla Plano Incapacidades)")
    plano = res_gemini.get("plano", {})
    print(f"""
  ┌─────────────────────────────────────────────────────────────┐
  │  Médico          │ {(plano.get('medico') or '—'):<42} │
  │  Lugar atención  │ {(plano.get('lugar_atencion') or '—'):<42} │
  │  NIT lugar       │ {(plano.get('nit_lugar_atencion') or '—'):<42} │
  │  Tipo documento  │ {(plano.get('tipo_documento') or '—'):<42} │
  │  CIE-10          │ {(plano.get('codigo_cie10') or '—'):<42} │
  │  Días            │ {str(plano.get('dias_incapacidad') or '—'):<42} │
  │  Origen          │ {(plano.get('origen') or '—'):<42} │
  └─────────────────────────────────────────────────────────────┘""")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
def procesar_archivo(archivo: Path):
    print(f"\n{BOLD}{Y}▶ Procesando: {archivo.name}  ({archivo.stat().st_size / 1024:.1f} KB){RST}")

    # Validar keys
    if not os.getenv("MISTRAL_API_KEY"):
        error("MISTRAL_API_KEY no está en el entorno / .env")
        sys.exit(1)
    if not os.getenv("GEMINI_API_KEY"):
        error("GEMINI_API_KEY no está en el entorno / .env")
        sys.exit(1)

    # PASO 1: OCR
    print(f"\n  {C}[1/2]{RST} Mistral OCR...", end="", flush=True)
    t0 = time.time()
    res_ocr = paso_ocr(archivo)
    t_ocr = time.time() - t0
    print(f"  {G}listo en {t_ocr:.1f}s{RST}")

    if not res_ocr.get("exito") or not res_ocr.get("texto", "").strip():
        mostrar_resultado(archivo, res_ocr, {"exito": False, "plano": {}, "error": "Sin texto OCR"})
        return

    # PASO 2: Gemini
    print(f"  {C}[2/2]{RST} Gemini extrae campos...", end="", flush=True)
    t0 = time.time()
    res_gemini = paso_gemini(res_ocr["texto"])
    t_gemini = time.time() - t0
    print(f"  {G}listo en {t_gemini:.1f}s{RST}")

    mostrar_resultado(archivo, res_ocr, res_gemini)

    # Guardar JSON de resultado
    salida = archivo.parent / f"{archivo.stem}_plano.json"
    with open(salida, "w", encoding="utf-8") as f:
        json.dump({
            "archivo": archivo.name,
            "ocr": {
                "exito": res_ocr["exito"],
                "paginas": res_ocr.get("paginas"),
                "modelo": res_ocr.get("modelo"),
                "chars": len(res_ocr.get("texto", "")),
                "texto_completo": res_ocr.get("texto", ""),
            },
            "gemini": res_gemini,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  {DIM}💾 JSON completo guardado en: {salida.name}{RST}")


def main():
    if len(sys.argv) < 2:
        print(f"""
{BOLD}Uso:{RST}
    python test_plano_local.py soporte.pdf
    python test_plano_local.py foto.jpg
    python test_plano_local.py carpeta/          # procesa todos los archivos

{BOLD}Variables de entorno requeridas{RST} (en .env o en el sistema):
    MISTRAL_API_KEY=...
    GEMINI_API_KEY=...
""")
        sys.exit(0)

    objetivo = Path(sys.argv[1])

    if objetivo.is_dir():
        archivos = sorted([
            f for f in objetivo.iterdir()
            if f.suffix.lower() in EXTENSIONES_VALIDAS
        ])
        if not archivos:
            error(f"No se encontraron PDF/imágenes en: {objetivo}")
            sys.exit(1)
        print(f"\n{BOLD}Carpeta: {objetivo}  —  {len(archivos)} archivos encontrados{RST}")
        for arch in archivos:
            procesar_archivo(arch)
            print()
    else:
        if not objetivo.exists():
            error(f"Archivo no encontrado: {objetivo}")
            sys.exit(1)
        if objetivo.suffix.lower() not in EXTENSIONES_VALIDAS:
            error(f"Extensión no soportada: {objetivo.suffix}  (acepta: pdf, jpg, png, webp, tiff)")
            sys.exit(1)
        procesar_archivo(objetivo)

    print(f"\n{BOLD}{G}✅ Test finalizado.{RST}\n")


if __name__ == "__main__":
    main()
