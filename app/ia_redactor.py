"""
Redactor de Emails - IncaBaeza
Plantillas estáticas + IA solo para mensajes personalizados
"""

import os

# Cliente de Anthropic (solo se usa para mensajes personalizados)
try:
    import anthropic
    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY")
    )
    IA_DISPONIBLE = bool(os.environ.get("ANTHROPIC_API_KEY"))
except:
    client = None
    IA_DISPONIBLE = False

# ✅ Documentos requeridos por tipo (para incluir en emails)
DOCUMENTOS_REQUERIDOS = {
    'maternidad': [
        'Licencia de maternidad',
        'Certificado de nacido vivo',
        'Registro civil del bebé',
        'Epicrisis o resumen clínico'
    ],
    'paternidad': [
        'Certificado de nacido vivo',
        'Registro civil del bebé',
        'Cédula del padre (ambas caras)',
        'Licencia de maternidad de la madre emitida por la EPS',
        'Epicrisis o resumen clínico'
    ],
    'enfermedad_general': [
        'Incapacidad médica',
        'Epicrisis o resumen clínico'
    ],
    'accidente_transito': [
        'Incapacidad médica',
        'Epicrisis o resumen clínico',
        'FURIPS',
        'SOAT'
    ],
    'enfermedad_laboral': [
        'Incapacidad médica',
        'Epicrisis o resumen clínico'
    ]
}

def redactar_email_incompleta(nombre: str, serial: str, checks_seleccionados: list, tipo_incapacidad: str) -> str:
    """
    Plantilla estática para casos incompletos
    """
    from app.checks_disponibles import CHECKS_DISPONIBLES
    
    # Construir lista de problemas
    problemas = []
    for check_key in checks_seleccionados:
        if check_key in CHECKS_DISPONIBLES:
            problemas.append(CHECKS_DISPONIBLES[check_key]['descripcion'])
    
    problemas_texto = "\n".join([f"• {p}" for p in problemas]) if problemas else "• Documentación incompleta"
    
    # Obtener documentos requeridos
    docs_requeridos = DOCUMENTOS_REQUERIDOS.get(tipo_incapacidad.lower(), ['Incapacidad médica', 'Epicrisis o resumen clínico'])
    docs_texto = "\n".join([f"• {doc}" for doc in docs_requeridos])
    
    return f"""Hola {nombre},

Su incapacidad **{serial}** fue devuelta.

**MOTIVO:**
{problemas_texto}

**SOPORTES REQUERIDOS PARA {tipo_incapacidad.upper()}:**
{docs_texto}

**FORMATO DE ENVÍO:** PDF escaneado, completo y legible.

Si no cuenta con algún soporte, **diríjase al punto de atención más cercano de su EPS y solicítelo**.

Comuníquese si tiene alguna duda."""


def redactar_email_ilegible(nombre: str, serial: str, checks_seleccionados: list) -> str:
    """
    Redacta email para documentos ilegibles - PLANTILLA ESTÁTICA
    """
    from app.checks_disponibles import CHECKS_DISPONIBLES
    
    problemas = []
    for check_key in checks_seleccionados:
        if check_key in CHECKS_DISPONIBLES:
            problemas.append(CHECKS_DISPONIBLES[check_key]['descripcion'])
    
    problemas_texto = "\n".join([f"• {p}" for p in problemas])
    
    return f"""Su incapacidad **{serial}** fue devuelta porque los documentos no son legibles.

**MOTIVO:**
{problemas_texto}

**FORMATO DE ENVÍO:** PDF escaneado, completo y legible.

Si no cuenta con algún soporte, **diríjase al punto de atención más cercano de su EPS y solicítelo**.

Comuníquese si tiene alguna duda."""


def redactar_alerta_tthh(empleado_nombre: str, serial: str, empresa: str, checks_seleccionados: list, observaciones: str = "") -> str:
    """
    Redacta email FORMAL para Talento Humano - PLANTILLA ESTÁTICA
    """
    from app.checks_disponibles import CHECKS_DISPONIBLES
    
    problemas = []
    for check_key in checks_seleccionados:
        if check_key in CHECKS_DISPONIBLES:
            problemas.append(CHECKS_DISPONIBLES[check_key]['label'])
    
    problemas_texto = ", ".join(problemas) if problemas else "Inconsistencias detectadas"
    obs_texto = observaciones if observaciones else "Ninguna"
    
    return f"""Se detectó una incapacidad que requiere validación adicional.

**Datos del caso:**
- Colaborador/a: {empleado_nombre}
- Empresa: {empresa}
- Serial: {serial}
- Inconsistencias: {problemas_texto}
- Observaciones: {obs_texto}

Por favor, realizar validación directa con la colaboradora para verificar la autenticidad de la documentación.

Este proceso debe manejarse con confidencialidad."""


def redactar_recordatorio_7dias(nombre: str, serial: str, estado: str) -> str:
    """Recordatorio después de 7 días - PLANTILLA ESTÁTICA"""
    return f"""Hace **7 días** le notificamos que su incapacidad (**serial {serial}**) se encuentra **{estado}** y requiere correcciones.

**Aún no hemos recibido los documentos actualizados.**

Es importante que complete este proceso lo antes posible para continuar con el trámite de su incapacidad.

Comuníquese si tiene alguna duda."""


def redactar_alerta_jefe_7dias(jefe_nombre: str, empleado_nombre: str, serial: str, empresa: str, fecha_inicio: str = "", fecha_fin: str = "", motivo: str = "") -> str:
    """Alerta para el jefe después de 7 días - PLANTILLA ESTÁTICA"""
    fechas = ""
    if fecha_inicio or fecha_fin:
        fechas = f"\n- Fecha inicio: {fecha_inicio}\n- Fecha fin: {fecha_fin}"
    
    motivo_texto = f"\n- Motivo pendiente: {motivo}" if motivo else ""
    
    return f"""El colaborador **{empleado_nombre}** cuenta con incapacidades pendientes.

**Datos:**
- Serial: {serial}
- Empresa: {empresa}{fechas}{motivo_texto}

Hace 7 días se solicitó completar/corregir documentación, pero no hemos recibido respuesta.

Agradeceríamos su apoyo para recordarle la importancia de completar este proceso."""


def redactar_mensaje_personalizado(nombre: str, serial: str, mensaje_libre: str) -> str:
    """Redacta email a partir de mensaje libre del validador - USA CLAUDE SI DISPONIBLE"""
    if not IA_DISPONIBLE or not client:
        # Sin IA, devolver mensaje original formateado
        return f"""Estimado/a {nombre},

Respecto a su incapacidad **{serial}**:

{mensaje_libre}

Comuníquese si tiene alguna duda."""
    
    prompt = f"""Convierte este mensaje informal en un email profesional pero claro para {nombre} (caso {serial}).

**Mensaje del validador:**
{mensaje_libre}

**INSTRUCCIONES:**
- Mantener el mensaje principal
- Hacerlo más profesional pero claro
- Máximo 200 palabras
- Lenguaje simple

Responde ÚNICAMENTE con el contenido."""

    try:
        message = client.messages.create(
            model="claude-3-opus-20240229",
            max_tokens=400,
            temperature=0.7,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text.strip()
    except Exception as e:
        return f"""Estimado/a {nombre},

Respecto a su incapacidad **{serial}**:

{mensaje_libre}

Comuníquese si tiene alguna duda."""

def redactar_mensaje_completo(nombre: str, serial: str, tipo: str) -> str:
    """Email cuando incapacidad es VALIDADA - PLANTILLA ESTÁTICA"""
    return f"""¡Excelentes noticias!

Su incapacidad **{serial}** ({tipo}) fue **VALIDADA** exitosamente.

La documentación ha sido procesada y subida al sistema.

¡Gracias por su colaboración!"""

# ✅ ALIAS para mantener compatibilidad
redactar_mensaje_completa = redactar_mensaje_completo

def redactar_whatsapp_completa(nombre: str, serial: str) -> str:
    """WhatsApp cuando incapacidad es COMPLETA/VALIDADA - PLANTILLA ESTÁTICA"""
    return f"🎉 Tu incapacidad {serial} fue validada exitosamente. Se procederá a subirla al sistema. ¡Gracias!"