"""
Motivos — el vocabulario único del ciclo de una incapacidad.

Por qué existe este módulo
--------------------------
Hoy cada etapa dice lo suyo con sus propias palabras: el calificador devuelve
`motivo_rechazo` armado a mano, el cruce de recobro guarda el texto tal cual lo
escribió el portal de la EPS, y las alertas de 180 días viven aparte. Eso tiene
tres consecuencias caras:

  1. **No se puede sumar.** "Negada por mora", "PERIODO DESCUBIERTO" y "cartera"
     son lo mismo escrito de tres formas; sin normalizar no hay forma de decirle
     a la empresa "la EPS le negó $X por períodos descubiertos".
  2. **No se puede decidir.** Apelar o castigar una cartera depende del motivo
     exacto; con texto libre esa decisión la toma una persona, caso por caso.
  3. **No se puede sustentar.** Un motivo sin artículo detrás es una opinión.

Aquí cada motivo tiene un código estable, qué ve el validador, qué se le dice a
la empresa, el artículo que lo sustenta —resuelto por `normas.citar()`, que ya
sabe si va al Decreto 2126 de 2023 o al 1427 de 2022— y qué hacer con él.

Los códigos son contrato: no se renombran ni se reciclan, porque quedan escritos
en casos viejos. Un motivo que deja de usarse se marca `vigente: false`.

Uso:
    from app.services.motivos import motivo, describir, clasificar_negacion

    describir("RIE-01")
    # 'En trámite con la EPS. Tiene posible causal de negación por
    #  retroactividad: ... (Decreto 2126 de 2023, art. 2.2.3.3.4 — ...)'

    clasificar_negacion("NEGADA - PERIODOS DESCUBIERTOS DEL APORTANTE")
    # {'codigo': 'NEG-01', 'nombre': 'Períodos descubiertos / mora en aportes',
    #  'apelable': False, 'accion': 'castigar', ...}

El catálogo vive en `app/data/catalogo_motivos.json` para poder crecer sin tocar
código: agregar un motivo nuevo es agregar un objeto, y agregarle patrones a un
NEG- existente es afinar la clasificación sin desplegar lógica nueva.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.normas import citar

logger = logging.getLogger(__name__)

RUTA_CATALOGO = Path(__file__).resolve().parent.parent / "data" / "catalogo_motivos.json"

# Cuando la EPS responde algo que ningún patrón reconoce. No es un error: es la
# señal de que al catálogo le falta un patrón, y se ve en el reporte.
MOTIVO_NEGACION_DESCONOCIDA = "NEG-99"


@lru_cache(maxsize=1)
def cargar_catalogo() -> Dict[str, Any]:
    """
    Carga el catálogo una vez por proceso. Fail-safe: si el archivo no está o no
    parsea, devuelve un catálogo vacío y lo registra. Ninguna etapa del flujo
    (recepción, calificación, radicación, recobro) puede caerse porque falte un
    archivo de texto: en el peor caso se sigue con el motivo literal, sin código.
    """
    try:
        with open(RUTA_CATALOGO, encoding="utf-8") as f:
            datos = json.load(f)
        motivos = {m["codigo"]: m for m in datos.get("motivos", [])
                   if m.get("vigente", True)}
        return {"grupos": datos.get("grupos", {}), "motivos": motivos,
                "version": datos.get("version")}
    except Exception as e:
        logger.error(f"❌ No se pudo cargar el catálogo de motivos ({RUTA_CATALOGO}): {e}")
        return {"grupos": {}, "motivos": {}, "version": None}


def motivo(codigo: str) -> Dict[str, Any]:
    """El motivo por su código, o {} si no existe. Nunca lanza."""
    return cargar_catalogo()["motivos"].get((codigo or "").strip().upper(), {})


def motivos_de(grupo: str) -> List[Dict[str, Any]]:
    """Todos los motivos de un grupo ('MIN', 'RIE', 'NEG', 'CAR', 'HIT')."""
    grupo = (grupo or "").strip().upper()
    return [m for m in cargar_catalogo()["motivos"].values() if m.get("grupo") == grupo]


def radica(codigo: str) -> bool:
    """
    ¿Este motivo permite radicar? La regla que fijó el negocio: solo se detiene
    lo que no cumple el contenido mínimo del decreto (grupo MIN). Todo lo demás
    —retroactiva, extemporánea, prórroga sin marcar— se radica igual, con la
    observación puesta. Un caso extenso de extemporaneidad suele ser una
    hospitalización, y no radicarlo es perder la prestación por nuestra cuenta.
    """
    m = motivo(codigo)
    if not m:
        return True
    return bool(m.get("radica", m.get("grupo") != "MIN"))


def describir(codigo: str, para: str = "empresa", **contexto: Any) -> str:
    """
    El texto que se le muestra a alguien, con la cita de la norma pegada.

    `para="empresa"` usa el mensaje redactado para el colaborador o la empresa;
    `para="validador"` usa la versión corta y técnica de la tabla interna.
    `contexto` rellena los placeholders del catálogo ({campos_faltantes}).
    """
    m = motivo(codigo)
    if not m:
        return ""

    texto = m.get("mensaje" if para == "empresa" else "validador") or m.get("validador", "")
    if contexto:
        try:
            texto = texto.format(**contexto)
        except (KeyError, IndexError):
            # Falta un dato de contexto: mejor el texto con el placeholder crudo
            # que una excepción en mitad de una radicación.
            logger.warning(f"[motivos] Contexto incompleto para {codigo}: {list(contexto)}")

    articulo = m.get("articulo")
    return f"{texto} — {citar(articulo)}" if articulo else texto


# ══════════════════════════════════════════════════════════════
#  Normalizar lo que responde la EPS
# ══════════════════════════════════════════════════════════════

def _plano(texto: str) -> str:
    """
    Minúsculas, sin tildes y con espacios colapsados. Los portales escriben
    'NEGADA – Períodos  Descubiertos' un día y 'negada por periodo descubierto'
    al siguiente; los patrones del catálogo se escriben sobre esta forma plana.
    """
    sin_tildes = unicodedata.normalize("NFKD", str(texto or ""))
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_tildes).strip().lower()


@lru_cache(maxsize=1)
def _patrones_negacion() -> List[tuple]:
    """(codigo, [regex compiladas]) en el orden del catálogo. Un patrón que no
    compila se descarta con log; no tumba la clasificación de los demás."""
    compilados = []
    for m in cargar_catalogo()["motivos"].values():
        if m.get("grupo") != "NEG" or not m.get("patrones"):
            continue
        regex = []
        for p in m["patrones"]:
            try:
                regex.append(re.compile(p))
            except re.error as e:
                logger.error(f"❌ Patrón inválido en {m['codigo']}: {p!r} ({e})")
        if regex:
            compilados.append((m["codigo"], regex))
    return compilados


def clasificar_negacion(texto_portal: str) -> Dict[str, Any]:
    """
    Convierte el motivo en texto libre de la EPS en un motivo del catálogo.

    Devuelve el motivo con `texto_portal` (lo literal que dijo la EPS, que se
    conserva siempre: es la prueba ante una apelación) y `clasificado` en False
    cuando ningún patrón coincidió. Ese caso cae en NEG-99 a propósito, para que
    se vea en el reporte cuántos motivos está diciendo la EPS que todavía no
    sabemos leer, en vez de esconderlos en un cajón de "otros".
    """
    plano = _plano(texto_portal)
    if plano:
        for codigo, regex in _patrones_negacion():
            if any(r.search(plano) for r in regex):
                return {**motivo(codigo), "texto_portal": texto_portal, "clasificado": True}

    return {**motivo(MOTIVO_NEGACION_DESCONOCIDA),
            "texto_portal": texto_portal, "clasificado": False}


def es_apelable(texto_portal: str) -> bool:
    """
    Atajo para la cola de apelaciones: ¿vale la pena controvertir esta negación?

    'depende' cuenta como apelable — significa que hay algo que revisar, y el
    validador decide. Solo los motivos marcados `apelable: false` (mora,
    exclusión, origen ARL) salen directo a castigar: en esos no hay nada que
    apelar y perseguirlos es tiempo de un analista gastado en nada.
    """
    return clasificar_negacion(texto_portal).get("apelable") is not False


def recargar() -> None:
    """Relee el catálogo sin reiniciar el proceso (útil tras editar el JSON)."""
    cargar_catalogo.cache_clear()
    _patrones_negacion.cache_clear()
