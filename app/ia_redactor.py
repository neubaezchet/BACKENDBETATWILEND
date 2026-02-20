"""
Redactor de Emails con Claude 3 Opus
IncaBaeza - Sistema de redacción clara para personas mayores
"""

import anthropic
import os

# Cliente de Anthropic
client = anthropic.Anthropic(
    api_key=os.environ.get("ANTHROPIC_API_KEY")
)

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
    Redacta email MUY CLARO Y ESPECÍFICO para casos incompletos
    Diseñado para personas mayores y con poca experiencia tecnológica
    """
    
    from app.checks_disponibles import CHECKS_DISPONIBLES
    
    # Construir lista de problemas
    problemas = []
    for check_key in checks_seleccionados:
        if check_key in CHECKS_DISPONIBLES:
            problemas.append(CHECKS_DISPONIBLES[check_key]['descripcion'])
    
    problemas_texto = "\n".join([f"• {p}" for p in problemas])
    
    # Obtener documentos siempre requeridos
    docs_requeridos = DOCUMENTOS_REQUERIDOS.get(tipo_incapacidad.lower(), [])
    docs_texto = "\n".join([f"• {doc}" for doc in docs_requeridos])
    
    prompt = f"""Redacta un email CORTO, DIRECTO y ESPECÍFICO para {nombre} explicando que su incapacidad (serial {serial}) está incompleta.

**CONTEXTO IMPORTANTE:**
- Sé MUY ESPECÍFICO con el motivo del rechazo
- Ve directo al punto, sin muletillas ni rodeos
- Usa un lenguaje simple y claro

**Problemas encontrados (SÉ MUY ESPECÍFICO con estos motivos):**
{problemas_texto}

**Tipo de incapacidad:** {tipo_incapacidad}

**Documentos SIEMPRE requeridos para {tipo_incapacidad}:**
{docs_texto}

**INSTRUCCIONES DE REDACCIÓN:**
1. Inicia directamente con el motivo específico del rechazo (ej: "Su documento se encuentra recortado e incompleto, hacen falta páginas en el resumen de atención")
2. Lista los soportes requeridos según el tipo (origen común o laboral)
3. Indica que debe enviar en **PDF escaneado**
4. Al final: "Si no cuenta con algún soporte, diríjase al punto de atención más cercano de su EPS y solicítelo"
5. Cierra con: "Comuníquese si tiene alguna duda"

**TONO:**
- Directo y claro, sin muletillas
- Máximo 150 palabras
- No usar frases como "lamentamos informarle", "nos permitimos", etc.

**FORMATO:**
- Solo el cuerpo del mensaje (sin asunto ni firma)
- Usa **negritas** para documentos importantes
- Usa viñetas (•) para listas

**IMPORTANTE:**
- NO inventes información
- NO uses muletillas ni frases de relleno
- SÍ sé muy específico con el motivo exacto
- SÍ menciona "PDF escaneado" en lugar de fotos
- SÍ incluye "diríjase al punto de atención más cercano" al final

Responde ÚNICAMENTE con el contenido del email."""

    try:
        message = client.messages.create(
            model="claude-3-opus-20240229",  # ✅ Claude 3 Opus
            max_tokens=600,
            temperature=0.7,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )
        
        contenido = message.content[0].text.strip()
        print(f"✅ Email redactado con Claude Opus para {serial}")
        return contenido
        
    except Exception as e:
        print(f"❌ Error redactando con IA: {e}")
        # Fallback a plantilla estática DIRECTA
        return f"""Hola {nombre},

Su incapacidad **{serial}** no pudo ser procesada.

**MOTIVO:**
{problemas_texto}

**SOPORTES REQUERIDOS PARA {tipo_incapacidad.upper()}:**
{docs_texto}

**FORMATO DE ENVÍO:** PDF escaneado, completo y legible.

Si no cuenta con algún soporte, **diríjase al punto de atención más cercano de su EPS y solicítelo**.

Comuníquese si tiene alguna duda."""


def redactar_email_ilegible(nombre: str, serial: str, checks_seleccionados: list) -> str:
    """
    Redacta email para documentos ilegibles
    """
    
    from app.checks_disponibles import CHECKS_DISPONIBLES
    
    problemas = []
    for check_key in checks_seleccionados:
        if check_key in CHECKS_DISPONIBLES:
            problemas.append(CHECKS_DISPONIBLES[check_key]['descripcion'])
    
    problemas_texto = "\n".join([f"• {p}" for p in problemas])
    
    prompt = f"""Redacta un email DIRECTO y CONCISO para {nombre} informando que los documentos de su incapacidad {serial} no son legibles.

**Motivo de devolución:**
{problemas_texto}

**INSTRUCCIONES ESTRICTAS:**
- Máximo 120 palabras
- Sin muletillas ni rodeos. Ir al grano desde la primera línea.
- Empezar con el motivo específico de devolución
- Indicar que debe reenviar los documentos en **PDF escaneado**, completo y legible
- Indicar: "Si no cuenta con algún soporte, diríjase al punto de atención más cercano de su EPS y solicítelo"
- Cerrar con: "Comuníquese si tiene alguna duda"
- Usa **negritas** para énfasis
- NO dar tips de fotos, NO decir "estamos para ayudarte"

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
        return f"""Hola {nombre},

Su incapacidad **{serial}** fue devuelta porque los documentos no son legibles.

**MOTIVO:**
{problemas_texto}

**FORMATO DE ENVÍO:** PDF escaneado, completo y legible.

Si no cuenta con algún soporte, **diríjase al punto de atención más cercano de su EPS y solicítelo**.

Comuníquese si tiene alguna duda."""


def redactar_alerta_tthh(empleado_nombre: str, serial: str, empresa: str, checks_seleccionados: list, observaciones: str = "") -> str:
    """
    Redacta email FORMAL para Talento Humano
    """
    
    from app.checks_disponibles import CHECKS_DISPONIBLES
    
    problemas = []
    for check_key in checks_seleccionados:
        if check_key in CHECKS_DISPONIBLES:
            problemas.append(CHECKS_DISPONIBLES[check_key]['label'])
    
    problemas_texto = ", ".join(problemas) if problemas else "Inconsistencias detectadas"
    
    prompt = f"""Redacta un email PROFESIONAL para Talento Humano sobre una incapacidad con inconsistencias.

**Datos:**
- Colaborador/a: {empleado_nombre}
- Empresa: {empresa}
- Serial: {serial}
- Problemas: {problemas_texto}
- Observaciones: {observaciones if observaciones else 'Ninguna'}

**INSTRUCCIONES:**
- Tono PROFESIONAL y OBJETIVO
- Máximo 250 palabras
- NO hacer acusaciones directas
- Usar lenguaje neutral
- Solicitar validación con la colaboradora
- Recordar confidencialidad

Responde ÚNICAMENTE con el contenido."""

    try:
        message = client.messages.create(
            model="claude-3-opus-20240229",
            max_tokens=500,
            temperature=0.5,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return message.content[0].text.strip()
        
    except Exception as e:
        return f"""Se detectó una incapacidad que requiere validación adicional.

**Datos del caso:**
- Colaborador/a: {empleado_nombre}
- Empresa: {empresa}
- Serial: {serial}
- Inconsistencias: {problemas_texto}

Por favor, realizar validación directa con la colaboradora para verificar la autenticidad de la documentación.

Este proceso debe manejarse con confidencialidad."""


def redactar_recordatorio_7dias(nombre: str, serial: str, estado: str) -> str:
    """Recordatorio después de 7 días"""
    
    prompt = f"""Redacta un recordatorio amable pero URGENTE para {nombre} sobre su incapacidad pendiente ({serial}).

**Contexto:**
- Hace 7 días se le notificó que estaba {estado}
- No ha enviado la documentación

**INSTRUCCIONES:**
- Tono amable pero urgente
- Máximo 150 palabras
- Recordar tiempo transcurrido
- Enfatizar importancia
- Ofrecer ayuda

Responde ÚNICAMENTE con el contenido."""

    try:
        message = client.messages.create(
            model="claude-3-opus-20240229",
            max_tokens=300,
            temperature=0.7,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return message.content[0].text.strip()
        
    except Exception as e:
        return f"""Hola {nombre},

Hace **7 días** te notificamos que tu incapacidad (**serial {serial}**) necesita correcciones.

**Aún no hemos recibido los documentos actualizados.**

Es importante que complete este proceso lo antes posible para continuar con el trámite de su incapacidad.

Comuníquese si tiene alguna duda."""


def redactar_alerta_jefe_7dias(jefe_nombre: str, empleado_nombre: str, serial: str, empresa: str) -> str:
    """Alerta para el jefe después de 7 días"""
    
    prompt = f"""Redacta un email PROFESIONAL para {jefe_nombre} sobre una incapacidad pendiente de su colaborador/a.

**Datos:**
- Colaborador/a: {empleado_nombre}
- Empresa: {empresa}
- Serial: {serial}
- Hace 7 días se solicitó documentación, sin respuesta

**INSTRUCCIONES:**
- Tono profesional y respetuoso
- Máximo 200 palabras
- Solicitar apoyo
- Mencionar impacto en tiempos

Responde ÚNICAMENTE con el contenido."""

    try:
        message = client.messages.create(
            model="claude-3-opus-20240229",
            max_tokens=400,
            temperature=0.5,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return message.content[0].text.strip()
        
    except Exception as e:
        return f"""Le informamos que su colaborador/a **{empleado_nombre}** tiene una incapacidad pendiente (**serial {serial}**) que requiere atención.

**Situación:**
Hace 7 días se le solicitó completar/corregir documentación, pero no hemos recibido respuesta.

**Solicitud:**
Agradeceríamos su apoyo para recordarle la importancia de completar este proceso, ya que está afectando los tiempos de trámite.

Quedamos atentos a cualquier inquietud."""


def redactar_mensaje_personalizado(nombre: str, serial: str, mensaje_libre: str) -> str:
    """Redacta email a partir de mensaje libre del validador"""
    
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
        return mensaje_libre

def redactar_mensaje_completo(nombre: str, serial: str, tipo: str) -> str:
    """Email cuando incapacidad es VALIDADA"""
    try:
        message = client.messages.create(
            model="claude-3-opus-20240229", max_tokens=400,
            messages=[{"role": "user", "content": 
                f"Email positivo para {nombre}: incapacidad {serial} ({tipo}) VALIDADA. "
                "Ha sido subida al sistema exitosamente. Agradecer. Máx 150 palabras."}]
        )
        return message.content[0].text.strip()
    except:
        return f"¡Excelentes noticias {nombre}! Su incapacidad **{serial}** fue VALIDADA y subida al sistema exitosamente."