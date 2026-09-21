"""
Motor de reglas de documentos requeridos — fuente única de verdad.
Extraído de validador.py (/reglas/requisitos) para que el validador manual y
el calificador_service.py (IA) nunca diverjan: ambos llaman esta misma función.
"""

from typing import Optional


def calcular_documentos_requeridos(
    tipo: str,
    dias: Optional[int] = None,
    vehiculo_fantasma: Optional[bool] = None,
    madre_trabaja: Optional[bool] = None,
    semanas_gestacion_indicadas: Optional[bool] = None,
    es_prorroga: bool = False,
) -> dict:
    """Calcula documentos requeridos según tipo de incapacidad y contexto.

    Returns:
        {"documentos": [{"doc": str, "requerido": bool, "aplica": bool}, ...],
         "mensajes": [str, ...]}
    """
    documentos_requeridos = []
    mensajes = []

    if tipo == "enfermedad_general":
        documentos_requeridos.append({"doc": "incapacidad_medica", "requerido": True, "aplica": True})

        if dias and dias >= 3:
            documentos_requeridos.append({"doc": "epicrisis_o_resumen_clinico", "requerido": True, "aplica": True})
            mensajes.append("Enfermedad general ≥3 días requiere epicrisis o resumen clínico")
        else:
            mensajes.append("1-2 días: solo incapacidad médica (salvo validación manual)")

    elif tipo == "enfermedad_laboral":
        documentos_requeridos.append({"doc": "incapacidad_medica", "requerido": True, "aplica": True})
        documentos_requeridos.append({"doc": "epicrisis_o_resumen_clinico", "requerido": True, "aplica": True})
        mensajes.append("Origen laboral: epicrisis o resumen de atención obligatorio sin importar los días (enfermedad laboral ≠ accidente de trabajo, solo el resumen lo aclara)")

    elif tipo == "accidente_transito":
        documentos_requeridos.append({"doc": "incapacidad_medica", "requerido": True, "aplica": True})
        documentos_requeridos.append({"doc": "furips", "requerido": True, "aplica": True})

        if dias and dias >= 3:
            documentos_requeridos.append({"doc": "epicrisis_o_resumen_clinico", "requerido": True, "aplica": True})
            mensajes.append("Accidente de tránsito ≥3 días requiere epicrisis o resumen clínico")
        else:
            mensajes.append("1-2 días: epicrisis/resumen no obligatorio (salvo validación manual); FURIPS sigue siendo obligatorio")

        if vehiculo_fantasma:
            documentos_requeridos.append({"doc": "soat", "requerido": False, "aplica": False})
            mensajes.append("Vehículo fantasma: no se requiere SOAT")
        else:
            documentos_requeridos.append({"doc": "soat", "requerido": True, "aplica": True})
            mensajes.append("Vehículo identificado: SOAT obligatorio")

    elif tipo == "especial":
        documentos_requeridos.append({"doc": "incapacidad_medica", "requerido": True, "aplica": True})
        documentos_requeridos.append({"doc": "epicrisis_o_resumen_clinico", "requerido": True, "aplica": True})

    elif tipo == "maternidad":
        documentos_requeridos.extend([
            {"doc": "licencia_o_incapacidad", "requerido": True, "aplica": True},
            {"doc": "epicrisis_o_resumen_clinico", "requerido": True, "aplica": True},
            {"doc": "nacido_vivo", "requerido": True, "aplica": True},
            {"doc": "registro_civil", "requerido": True, "aplica": True}
        ])
        mensajes.append("Maternidad: 4 documentos básicos obligatorios")

    elif tipo == "paternidad":
        documentos_requeridos.extend([
            {"doc": "cedula_padre", "requerido": True, "aplica": True},
            {"doc": "nacido_vivo", "requerido": True, "aplica": True},
            {"doc": "registro_civil", "requerido": True, "aplica": True}
        ])

        if semanas_gestacion_indicadas:
            documentos_requeridos.append({"doc": "epicrisis_o_resumen_clinico", "requerido": False, "aplica": False})
            mensajes.append("La incapacidad ya indica las semanas de gestación: no se exige resumen de atención")
        else:
            documentos_requeridos.append({"doc": "epicrisis_o_resumen_clinico", "requerido": True, "aplica": True})
            mensajes.append("La incapacidad no indica semanas de gestación: se exige resumen de atención")

        if madre_trabaja:
            documentos_requeridos.append({"doc": "licencia_maternidad", "requerido": True, "aplica": True})
            mensajes.append("Madre trabaja: licencia de maternidad obligatoria")
        else:
            documentos_requeridos.append({"doc": "licencia_maternidad", "requerido": False, "aplica": False})
            mensajes.append("Madre no trabaja: licencia de maternidad no requerida")

    return {
        "documentos": documentos_requeridos,
        "mensajes": mensajes
    }


# Marcadores OCR de formatos oficiales EPS/ARL transcritos (regla R13):
# cuando aparecen, el soporte se autoexcusa de todos los demás requisitos.
FORMATOS_TRANSCRITOS_RECONOCIDOS = [
    {
        "entidad": "SURA (EPS Suramericana S.A.)",
        "marcadores_ocr": ["EPS SURAMERICANA S.A.", "CERTIFICADO DE INCAPACIDAD / LICENCIA"],
    },
    {
        "entidad": "Compensar EPS",
        "marcadores_ocr": ["COMPENSAR EPS", "INCAPACIDAD MÉDICA O LICENCIA"],
    },
    {
        "entidad": "Nueva EPS",
        "marcadores_ocr": ["NUEVA EPS", "CERTIFICADO DE INCAPACIDAD O LICENCIA", "TRANSCRITA"],
    },
    {
        "entidad": "AXA Colpatria (ARL)",
        "marcadores_ocr": ["INCAPACIDAD ARL", "AXACOLPATRIA", "AXA COLPATRIA"],
    },
]


def detectar_formato_transcrito(texto_ocr: str) -> Optional[str]:
    """R13: si el OCR contiene TODOS los marcadores de alguna entidad reconocida,
    retorna el nombre de esa entidad. None si no coincide con ninguna (regla no aplica).
    Comparación case-insensitive, tolerante a acentos ya normalizados por el OCR.
    """
    if not texto_ocr:
        return None
    texto_upper = texto_ocr.upper()
    for formato in FORMATOS_TRANSCRITOS_RECONOCIDOS:
        if all(marcador.upper() in texto_upper for marcador in formato["marcadores_ocr"]):
            return formato["entidad"]
    return None
