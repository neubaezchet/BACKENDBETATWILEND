"""
Línea de tiempo de incapacidades prolongadas — una barra por cadena.

Por qué existe este módulo
--------------------------
`prorroga_detector` ya sabe agrupar las incapacidades de una persona en cadenas
por correlación de diagnóstico. Lo que faltaba es lo que decide quién paga:

  1. **Una persona puede tener varias cadenas abiertas al tiempo**, por
     patologías distintas. Sumarlas en un solo contador miente en las dos
     direcciones: dispara alertas de 180 a quien no las ha causado, y esconde a
     quien sí. Aquí cada cadena es su propia barra, con su propio contador.

  2. **El origen cambia todo el cronograma.** En origen común el pagador pasa de
     la EPS a la AFP en el día 181 y vuelve a la EPS en el 541. En origen
     laboral paga la ARL desde el día siguiente al accidente y **no hay traslado
     al fondo de pensiones**: a los 180 el subsidio se prorroga hasta 180 días
     más y luego se califica la pérdida de capacidad laboral. Aplicarle el
     cronograma común a una cadena laboral manda a radicar a la entidad
     equivocada.

  3. Los hitos que valen plata son **120, 150, 180 y 540**, no números redondos.
     El 120 y el 150 son obligaciones de la EPS: si no emite el concepto de
     rehabilitación y no lo envía a la AFP antes del día 150, debe seguir
     pagando después del 180. Vigilarlos es lo que convierte una negación futura
     en una negación apelable.

Todo sale del OCR de los propios soportes (`Case.codigo_cie10`, fechas y días),
que es la única fuente que tenemos completa y al día. No depende de que nadie
suba un reporte de nómina: si el soporte entró, la línea de tiempo ya se puede
armar.

Uso:
    from app.services.prorroga_detector import analizar_historial_empleado
    from app.services.linea_tiempo import linea_de_tiempo

    linea_de_tiempo(analizar_historial_empleado(db, "1020304050"))
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from app.services.motivos import motivo

logger = logging.getLogger(__name__)

ORIGEN_COMUN = "comun"
ORIGEN_LABORAL = "laboral"
ORIGEN_LICENCIA = "licencia"

# De qué cronograma es cada tipo de incapacidad. El accidente de tránsito va por
# el cronograma común a propósito: el SOAT cubre la atención médica, pero la
# prestación económica por incapacidad la sigue reconociendo la EPS.
_ORIGEN_POR_TIPO = {
    "enfermedad_laboral": ORIGEN_LABORAL,
    "enfermedad_general": ORIGEN_COMUN,
    "accidente_transito": ORIGEN_COMUN,
    "especial": ORIGEN_COMUN,
    "certificado": ORIGEN_COMUN,
    "other": ORIGEN_COMUN,
    "maternidad": ORIGEN_LICENCIA,
    "paternidad": ORIGEN_LICENCIA,
    "prelicencia": ORIGEN_LICENCIA,
}

# Capítulo XX del CIE-10 (V00–Y99, causas externas). Solo se usa cuando el tipo
# no viene del formulario: es una pista, no una certeza, y por eso la cadena
# queda marcada con confianza "baja" para que un humano la confirme.
_PREFIJOS_CAUSA_EXTERNA = ("V", "W", "X", "Y")

# Etiqueta que va encima de la barra, tal como la pidió el negocio.
_ETIQUETA = {
    ORIGEN_COMUN: "180 GENERAL",
    ORIGEN_LABORAL: "180 LABORAL",
    ORIGEN_LICENCIA: "LICENCIA",
}

# Hitos del catálogo por origen, en orden. El texto y la norma viven en
# `catalogo_motivos.json`; aquí solo está el orden y a qué cronograma pertenece.
_HITOS = {
    ORIGEN_COMUN: ["HIT-120", "HIT-150", "HIT-180", "HIT-540", "HIT-541"],
    ORIGEN_LABORAL: ["HIT-LAB-180", "HIT-LAB-360"],
    ORIGEN_LICENCIA: [],
}

# Hasta dónde llega la barra dibujada, en días.
_ESCALA = {ORIGEN_COMUN: 540, ORIGEN_LABORAL: 360, ORIGEN_LICENCIA: 180}

# Cuántos días antes de un hito se considera "próximo" y hay que avisar. 30 días
# es lo que alcanza para conseguir un concepto de rehabilitación o armar el
# traslado a la AFP sin que el colaborador se quede sin pago en el intermedio.
DIAS_AVISO_ANTICIPADO = 30

# Tramos de responsabilidad del pago, por origen: (desde, hasta, quién paga).
# `hasta=None` significa "sin tope".
_TRAMOS = {
    ORIGEN_COMUN: [
        (1, 2, "EMPLEADOR", "Los dos primeros días los asume el empleador: no se le cobran a la EPS."),
        (3, 180, "EPS", "Período estándar de salud."),
        (181, 540, "AFP", "Subsidio a cargo del fondo de pensiones."),
        (541, None, "EPS", "Vuelve a la EPS solo si se acredita uno de los cuatro casos especiales."),
    ],
    ORIGEN_LABORAL: [
        (1, 180, "ARL", "La ARL paga desde el día siguiente al accidente; el empleador no asume los dos primeros días."),
        (181, 360, "ARL", "Subsidio prorrogado por hasta 180 días más."),
        (361, None, "ARL", "Agotada la prórroga: debe iniciarse la calificación de pérdida de capacidad laboral."),
    ],
    ORIGEN_LICENCIA: [
        (1, None, "EPS", "Licencia de maternidad o paternidad: no entra en el conteo de los 180 días."),
    ],
}


# ══════════════════════════════════════════════════════════════
#  Origen de la cadena
# ══════════════════════════════════════════════════════════════

def _origen_de_caso(caso: Dict[str, Any]) -> Optional[str]:
    """Origen de una incapacidad suelta, o None si no se puede determinar."""
    tipo = (caso.get("tipo") or "").strip().lower()
    if tipo in _ORIGEN_POR_TIPO:
        return _ORIGEN_POR_TIPO[tipo]
    codigo = (caso.get("codigo_cie10") or "").strip().upper()
    if codigo.startswith(_PREFIJOS_CAUSA_EXTERNA):
        return ORIGEN_LABORAL
    return None


def origen_de_cadena(cadena: Dict[str, Any]) -> Dict[str, Any]:
    """
    Qué cronograma le aplica a una cadena, ponderado por días.

    Una cadena puede traer incapacidades de origen distinto —pasa cuando el
    primer soporte llega sin tipo y el OCR lo dedujo del diagnóstico—. En ese
    caso manda el origen con más días, pero la cadena queda marcada `mixta` y
    con confianza baja: quién paga es ambiguo y eso tiene que verlo una persona,
    no resolverlo el sistema en silencio.
    """
    casos = [cadena.get("caso_inicial") or {}] + list(cadena.get("prorrogas") or [])
    dias_por_origen: Dict[str, int] = {}
    sin_determinar = 0

    for caso in casos:
        dias = max((caso.get("dias_incapacidad") or 0) - (caso.get("dias_traslapo") or 0), 0)
        origen = _origen_de_caso(caso)
        if origen is None:
            sin_determinar += dias
        else:
            dias_por_origen[origen] = dias_por_origen.get(origen, 0) + dias

    if not dias_por_origen:
        # Sin un solo dato de origen: se asume común porque es lo abrumadoramente
        # más frecuente, pero con confianza baja y dicho en voz alta.
        return {"origen": ORIGEN_COMUN, "etiqueta": _ETIQUETA[ORIGEN_COMUN],
                "mixta": False, "confianza": "baja",
                "nota": "Ningún soporte de la cadena indica el origen; se asume enfermedad general."}

    predominante = max(dias_por_origen, key=lambda o: dias_por_origen[o])
    mixta = len(dias_por_origen) > 1
    confianza = "alta"
    nota = None

    if mixta:
        confianza = "baja"
        detalle = ", ".join(f"{o}: {d}d" for o, d in sorted(dias_por_origen.items()))
        nota = (f"La cadena mezcla orígenes ({detalle}). Se aplica el cronograma de "
                f"'{predominante}' por ser el de más días, pero hay que confirmar a "
                f"quién se le radica.")
    elif sin_determinar:
        confianza = "media"
        nota = f"{sin_determinar} día(s) de la cadena sin origen identificado en el soporte."

    return {"origen": predominante, "etiqueta": _ETIQUETA[predominante],
            "mixta": mixta, "confianza": confianza, "nota": nota,
            "dias_por_origen": dias_por_origen}


# ══════════════════════════════════════════════════════════════
#  Fechas de los hitos
# ══════════════════════════════════════════════════════════════

def _a_fecha(valor: Any) -> Optional[date]:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError):
        return None


def _eventos(cadena: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Las incapacidades de la cadena en orden, con sus días efectivos."""
    casos = [cadena.get("caso_inicial") or {}] + list(cadena.get("prorrogas") or [])
    eventos = []
    for caso in casos:
        inicio = _a_fecha(caso.get("fecha_inicio"))
        if not inicio:
            continue
        dias = max((caso.get("dias_incapacidad") or 0) - (caso.get("dias_traslapo") or 0), 0)
        eventos.append({"inicio": inicio, "dias": dias})
    return sorted(eventos, key=lambda e: e["inicio"])


def _fecha_del_dia(cadena: Dict[str, Any], objetivo: int) -> Dict[str, Any]:
    """
    En qué fecha la cadena llega (o llegaría) al día acumulado `objetivo`.

    Si ya lo cruzó, la fecha es exacta: se recorre la cadena sumando días hasta
    dar con la incapacidad dentro de la cual cayó el hito. Si todavía no, se
    proyecta desde el fin de la última incapacidad asumiendo continuidad — que
    es el supuesto útil, porque el aviso hay que darlo antes, no después.
    """
    acumulado = 0
    for ev in _eventos(cadena):
        if acumulado + ev["dias"] >= objetivo:
            return {"fecha": (ev["inicio"] + timedelta(days=objetivo - acumulado - 1)).isoformat(),
                    "proyectada": False}
        acumulado += ev["dias"]

    fin = _a_fecha(cadena.get("fecha_fin_cadena"))
    if not fin:
        return {"fecha": None, "proyectada": True}
    return {"fecha": (fin + timedelta(days=objetivo - acumulado)).isoformat(),
            "proyectada": True}


def _responsable(origen: str, dias: int) -> Dict[str, Any]:
    """Quién debe pagar el día `dias` de esta cadena."""
    for desde, hasta, quien, nota in _TRAMOS.get(origen, []):
        if dias >= desde and (hasta is None or dias <= hasta):
            return {"responsable": quien, "nota": nota, "desde": desde, "hasta": hasta}
    return {"responsable": "EMPLEADOR", "nota": "Aún no inicia el conteo.",
            "desde": 0, "hasta": 0}


# ══════════════════════════════════════════════════════════════
#  La línea de tiempo
# ══════════════════════════════════════════════════════════════

def barra_de_cadena(cadena: Dict[str, Any]) -> Dict[str, Any]:
    """Una barra: la cadena con su origen, su pagador actual y sus hitos."""
    info_origen = origen_de_cadena(cadena)
    origen = info_origen["origen"]
    dias = int(cadena.get("dias_acumulados") or 0)
    escala = _ESCALA[origen]

    hitos = []
    for codigo in _HITOS[origen]:
        h = motivo(codigo)
        if not h:
            continue
        dia_hito = int(h.get("dias") or 0)
        faltan = dia_hito - dias
        if faltan <= 0:
            estado = "cumplido"
        elif faltan <= DIAS_AVISO_ANTICIPADO:
            estado = "proximo"
        else:
            estado = "pendiente"
        hitos.append({
            "codigo": codigo, "dia": dia_hito, "nombre": h.get("nombre"),
            "descripcion": h.get("validador"), "mensaje": h.get("mensaje"),
            "casos_especiales": h.get("casos_especiales"),
            "estado": estado, "dias_faltantes": max(faltan, 0),
            "posicion_pct": round(min(dia_hito / escala * 100, 100), 2),
            **_fecha_del_dia(cadena, dia_hito),
        })

    actual = _responsable(origen, dias)
    proximos = [h for h in hitos if h["estado"] != "cumplido"]

    return {
        "cadena_id": cadena.get("id_cadena"),
        "etiqueta": info_origen["etiqueta"],
        "origen": origen,
        "origen_mixto": info_origen["mixta"],
        "confianza_origen": info_origen["confianza"],
        "nota_origen": info_origen.get("nota"),
        "diagnostico_base": cadena.get("diagnostico_base"),
        "codigos_cie10": cadena.get("codigos_cie10") or [],
        "es_cadena_prorroga": cadena.get("es_cadena_prorroga", False),
        "total_incapacidades": cadena.get("total_incapacidades_cadena", 1),
        "dias_acumulados": dias,
        "fecha_inicio": cadena.get("fecha_inicio_cadena"),
        "fecha_fin": cadena.get("fecha_fin_cadena"),
        "escala_dias": escala,
        "avance_pct": round(min(dias / escala * 100, 100), 2),
        "responsable_actual": actual["responsable"],
        "nota_responsable": actual["nota"],
        "tramos": [
            {"desde": d, "hasta": h, "responsable": q, "nota": n,
             "inicio_pct": round(min((d - 1) / escala * 100, 100), 2),
             "ancho_pct": round(min(((h or escala) - d + 1) / escala * 100, 100), 2),
             "activo": dias >= d and (h is None or dias <= h)}
            for d, h, q, n in _TRAMOS.get(origen, [])
            if d <= escala
        ],
        "hitos": hitos,
        "proximo_hito": proximos[0] if proximos else None,
    }


def linea_de_tiempo(analisis: Dict[str, Any]) -> Dict[str, Any]:
    """
    Las barras de un empleado, una por cadena, a partir del análisis de
    prórrogas. Solo lectura: no toca la base ni envía nada.

    Las cadenas van ordenadas por días acumulados descendente — la que está más
    cerca de un cambio de pagador se lee primero, que es la que cuesta plata.
    """
    barras = [barra_de_cadena(c) for c in analisis.get("cadenas_prorroga") or []]
    barras.sort(key=lambda b: b["dias_acumulados"], reverse=True)

    por_origen: Dict[str, int] = {}
    for b in barras:
        por_origen[b["origen"]] = por_origen.get(b["origen"], 0) + b["dias_acumulados"]

    return {
        "cedula": analisis.get("cedula"),
        "nombre": analisis.get("nombre"),
        "total_barras": len(barras),
        "barras": barras,
        # A propósito NO se suma todo en un solo número: los días de una cadena
        # laboral y los de una común no se acumulan contra el mismo tope ni
        # contra el mismo pagador. Sumarlos es el error que dispara alertas de
        # 180 a quien no las ha causado.
        "dias_por_origen": por_origen,
        "cadena_mas_avanzada": barras[0] if barras else None,
        "requiere_revision_origen": [
            {"cadena_id": b["cadena_id"], "nota": b["nota_origen"]}
            for b in barras if b["confianza_origen"] != "alta"
        ],
    }
