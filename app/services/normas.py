"""
Normas — el texto legal como fuente citable, no como PDF suelto.

Por qué existe este módulo
--------------------------
Las reglas de validación de soportes salen de una norma: el contenido mínimo de
un certificado de incapacidad y de una licencia de maternidad. Ese texto vive hoy
en el Decreto 780 de 2016, cuyos capítulos 1 a 4 del Título 3 fueron sustituidos
por el Decreto 2126 de 2023 —que a su vez reemplazó lo que el Decreto 1427 de
2022 había puesto ahí un año y medio antes—. Exactamente por eso este módulo
existe: si la norma vive solo en un PDF en el escritorio o en una app de notas,
pasan tres cosas malas:

  1. El backend no puede leerla en producción, así que las reglas se copian a
     mano y se desfasan del texto sin que nadie lo note.
  2. Un rechazo no se puede sustentar: decirle a una empresa "le devolvimos el
     soporte" sin el artículo exacto no se sostiene ante la EPS ni ante nadie.
  3. Cuando salga el decreto que sustituya a este, no hay forma de saber qué
     reglas quedaron colgando de un texto derogado.

Aquí la norma queda partida por artículo, con el texto literal y el hash del PDF
del que salió, y cada regla de validación la referencia por número de artículo.
Así el motivo que le llega al colaborador puede citar la fuente, y cambiar de
norma es cambiar un archivo, no rastrear reglas a mano.

Deliberadamente NO se usa búsqueda semántica (embeddings / vector DB): el corpus
es cerrado y pequeño (13 páginas, ~40 artículos) y las reglas ya saben qué
artículo las sustenta. Recuperar por número es determinístico, gratis y
auditable; recuperar por similitud daría un veredicto distinto según qué trozo
alcanzó a entrar en el prompt. Patrón del repo: explorar con IA → congelar en
determinístico.

Uso:
    from app.services.normas import citar, texto_de_articulos

    citar("2.2.3.3.2")
    # 'Decreto 2126 de 2023, art. 2.2.3.3.2 (Certificado de incapacidad)'
    citar("2.2.3.7.1")   # capítulo que el 2126 no tocó
    # 'Decreto 1427 de 2022, art. 2.2.3.7.1 (Situaciones de abuso del derecho)'

Regenerar el JSON cuando llegue una norma nueva:
    python -m app.services.normas --convertir Decreto_XXXX.pdf --id decreto_xxxx
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DIR_NORMAS = Path(__file__).resolve().parent.parent / "data" / "normas"

# Norma vigente para la validación de soportes de incapacidad en Colombia.
NORMA_INCAPACIDADES = "decreto_2126_2023"

# Qué norma rige hoy y qué pasó con la anterior. Esto es el motivo por el que el
# módulo existe: el Decreto 1427 de 2022 parecía ser "la" norma de incapacidades
# y en diciembre de 2023 el Decreto 2126 le sustituyó los capítulos 1 a 4 —los
# que definen el certificado de incapacidad y el trámite—. Una regla que cite
# capítulos sustituidos no se sostiene ante una EPS. El desfase se ve aquí, no en
# una glosa.
HISTORIAL_NORMAS: Dict[str, Dict[str, Any]] = {
    "decreto_2126_2023": {
        "vigente": True,
        "nota": "Sustituye los capítulos 1, 2, 3 y 4 del Título 3, Parte 2, Libro 2 del "
                "Decreto 780 de 2016. Rige desde el 12/12/2023. Es la norma a citar para "
                "certificado de incapacidad (2.2.3.3.2), retroactividad (2.2.3.3.4), "
                "licencias y trámite.",
    },
    "decreto_1427_2022": {
        "vigente": False,
        "nota": "Sustituido en sus capítulos 1 a 4 por el Decreto 2126 de 2023. Siguen "
                "vigentes sus capítulos 5 (revisión periódica), 6 (incapacidades "
                "superiores a 540 días) y 7 (abuso del derecho), que el 2126 no tocó.",
    },
}

# Capítulos del Decreto 1427 que el 2126 NO sustituyó: para esos, el 1427 sigue
# siendo la fuente correcta (artículos 2.2.3.5.x, 2.2.3.6.x y 2.2.3.7.x).
_CAPITULOS_VIGENTES_1427 = ("2.2.3.5.", "2.2.3.6.", "2.2.3.7.")


def norma_para(articulo: str) -> str:
    """
    Qué norma citar para un artículo dado. Evita el error silencioso de sustentar
    una regla de 'abuso del derecho' en el decreto equivocado, y al revés.
    """
    numero = _normalizar_numero(articulo)
    if numero.startswith(_CAPITULOS_VIGENTES_1427):
        return "decreto_1427_2022"
    return NORMA_INCAPACIDADES


# ══════════════════════════════════════════════════════════════════════════════
#  Lectura
# ══════════════════════════════════════════════════════════════════════════════

@lru_cache(maxsize=8)
def cargar_norma(norma_id: str = NORMA_INCAPACIDADES) -> Dict[str, Any]:
    """
    Carga una norma del disco. Cacheada: el archivo no cambia en caliente.

    Devuelve {} si no existe, en vez de reventar: una cita que falta degrada el
    mensaje, no tumba la validación de un soporte.
    """
    ruta = DIR_NORMAS / f"{norma_id}.json"
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"⚠️ Norma no encontrada: {ruta}")
        return {}
    except Exception as e:
        logger.error(f"❌ No se pudo leer la norma {norma_id}: {e}")
        return {}


def obtener_articulo(articulo: str, norma_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Un artículo por su número ('2.2.3.3.2'). None si no está.

    Sin norma_id se resuelve sola cuál es la vigente para ese artículo, que es lo
    que hay que citar; se pasa explícita solo para consultar una norma histórica.
    """
    norma = cargar_norma(norma_id or norma_para(articulo))
    clave = _normalizar_numero(articulo)
    for art in norma.get("articulos", []):
        if art.get("numero") == clave:
            return art
    return None


def citar(articulo: str, norma_id: Optional[str] = None) -> str:
    """
    Cita corta para ponerle al colaborador o a la empresa en el motivo:
    'Decreto 1427 de 2022, art. 2.2.3.3.2 (Certificado de incapacidad)'.

    Si el artículo no está, devuelve la cita sin epígrafe en vez de vacío: es
    preferible una cita incompleta a un motivo sin fundamento.
    """
    norma_id = norma_id or norma_para(articulo)
    norma = cargar_norma(norma_id)
    titulo = norma.get("titulo") or norma_id
    art = obtener_articulo(articulo, norma_id)
    if art and art.get("epigrafe"):
        return f"{titulo}, art. {art['numero']} ({art['epigrafe']})"
    return f"{titulo}, art. {_normalizar_numero(articulo)}"


def texto_de_articulos(articulos: List[str], norma_id: Optional[str] = None,
                       max_caracteres: int = 12000) -> str:
    """
    Texto literal de los artículos pedidos, listo para anclar un prompt.

    Se pasan solo los artículos que sustentan las reglas que aplican al caso —no
    la norma entera— para que el modelo juzgue contra el texto exacto y no
    contra lo que recuerde. El tope de caracteres es un freno de costo: si se
    pasa, se corta y queda dicho en el texto, nunca en silencio.
    """
    partes, total = [], 0
    for numero in articulos:
        art = obtener_articulo(numero, norma_id)
        if not art:
            continue
        bloque = f"--- {citar(numero, norma_id)} ---\n{art.get('texto', '')}"
        if total + len(bloque) > max_caracteres:
            partes.append(f"[...se omitieron {len(articulos) - len(partes)} artículos por límite de tamaño...]")
            break
        partes.append(bloque)
        total += len(bloque)
    return "\n\n".join(partes)


def _normalizar_numero(numero: str) -> str:
    """
    '2.2.3. 7.3' → '2.2.3.7.3'. Las transcripciones oficiales parten el número con
    espacios ('2.2.3. 7.3'), lo duplican ('2. 2..3.3.4') o meten una coma
    ('2.2.3.4,6'). Todas esas variantes son el mismo artículo y deben resolver a
    la misma clave, o una regla queda citando al aire.
    """
    limpio = re.sub(r"\s+", "", str(numero or "")).replace(",", ".")
    return re.sub(r"\.{2,}", ".", limpio).strip(".")


# ══════════════════════════════════════════════════════════════════════════════
#  Conversión PDF → JSON (se corre una vez por norma, no en producción)
# ══════════════════════════════════════════════════════════════════════════════

# Encabezados de página del PDF de la Función Pública, que se repiten en medio
# del articulado y hay que sacar para que el texto de cada artículo quede limpio.
_RUIDO_PAGINA = (
    re.compile(r"^Departamento Administrativo de la Función Pública$"),
    re.compile(r"^EVA\s*-\s*Gestor Normativo$"),
    re.compile(r"^\d{1,3}$"),
)

_ENCABEZADO_ARTICULO = re.compile(
    r"^ART[IÍ]CULO\s+(\d+(?:\s*[.,]+\s*\d+)*)\s*[.,]?\s+(.*)$", re.IGNORECASE
)

# El epígrafe es la primera oración del artículo ("Certificado de incapacidad."),
# que en el PDF a veces se parte en dos renglones. Se busca sobre el texto ya
# unido, no sobre la línea del encabezado, y con tope para no tragarse un
# párrafo entero cuando el artículo arranca sin epígrafe (el art. 1, por ejemplo).
_FIN_EPIGRAFE = re.compile(r"^(.{3,160}?)\.\s", re.DOTALL)


def _limpiar_ligaduras(texto: str) -> str:
    """El PDF trae ﬁ/ﬂ como un solo carácter: 'aﬁliado' rompe cualquier búsqueda."""
    return unicodedata.normalize("NFKC", texto)


def _partir_epigrafe(texto: str) -> tuple:
    """
    Separa el epígrafe del cuerpo: ('Certificado de incapacidad', 'El médico...').

    Si no hay una primera oración corta —el art. 1 arranca directo con el
    mandato— devuelve epígrafe vacío y el texto completo, que es lo correcto:
    inventarle un título a un artículo que no lo tiene sería peor que no tenerlo.
    """
    m = _FIN_EPIGRAFE.match(texto)
    if not m:
        return "", texto
    return re.sub(r"\s+", " ", m.group(1)).strip(), texto[m.end():].strip()


def convertir_pdf(ruta_pdf: Path, norma_id: str, titulo: str,
                  expedido: str = "", origen: str = "") -> Dict[str, Any]:
    """
    Parte el PDF de una norma en artículos. Se ejecuta a mano cuando llega una
    norma nueva; el resultado queda versionado en el repo y es lo que lee
    producción, para que nadie dependa de tener el PDF a mano.
    """
    import pymupdf  # import perezoso: producción no necesita abrir PDFs aquí

    crudo = ruta_pdf.read_bytes()
    with pymupdf.open(stream=crudo, filetype="pdf") as doc:
        texto = "\n".join(p.get_text() for p in doc)
        paginas = doc.page_count

    lineas = [l.rstrip() for l in _limpiar_ligaduras(texto).splitlines()]
    lineas = [l for l in lineas
              if l.strip() and not any(p.match(l.strip()) for p in _RUIDO_PAGINA)
              and l.strip() != titulo]

    articulos: List[Dict[str, Any]] = []
    actual: Optional[Dict[str, Any]] = None
    for linea in lineas:
        m = _ENCABEZADO_ARTICULO.match(linea.strip())
        if m:
            if actual:
                articulos.append(actual)
            resto = m.group(2).strip()
            actual = {"numero": _normalizar_numero(m.group(1)),
                      "lineas": [resto] if resto else []}
        elif actual:
            actual["lineas"].append(linea.strip())
    if actual:
        articulos.append(actual)

    for art in articulos:
        art["epigrafe"], art["texto"] = _partir_epigrafe("\n".join(art.pop("lineas")).strip())

    return {
        "id": norma_id,
        "titulo": titulo,
        "expedido": expedido,
        "fuente": {
            "archivo": ruta_pdf.name,
            "sha256": hashlib.sha256(crudo).hexdigest(),
            "paginas": paginas,
            "origen": origen,
            "extraido_en": date.today().isoformat(),
        },
        "articulos": articulos,
    }


def _cli() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Convierte el PDF de una norma en JSON citable.")
    ap.add_argument("--convertir", required=True, help="ruta del PDF")
    ap.add_argument("--id", required=True, help="identificador, ej. decreto_1427_2022")
    ap.add_argument("--titulo", required=True, help="ej. 'Decreto 1427 de 2022'")
    ap.add_argument("--expedido", default="", help="YYYY-MM-DD")
    ap.add_argument("--origen", default="", help="de dónde se bajó el PDF")
    args = ap.parse_args()

    norma = convertir_pdf(Path(args.convertir), args.id, args.titulo, args.expedido, args.origen)
    DIR_NORMAS.mkdir(parents=True, exist_ok=True)
    destino = DIR_NORMAS / f"{args.id}.json"
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(norma, f, ensure_ascii=False, indent=2)

    print(f"✅ {destino}")
    print(f"   {len(norma['articulos'])} artículos, {norma['fuente']['paginas']} páginas")
    print(f"   sha256 {norma['fuente']['sha256'][:16]}…")
    for art in norma["articulos"]:
        print(f"   art. {art['numero']:<12} {art['epigrafe'][:70]}")


if __name__ == "__main__":
    _cli()
