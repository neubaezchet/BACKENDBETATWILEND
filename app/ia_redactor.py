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
    
    prompt = f"""Redacta un email MUY CLARO Y DETALLADO para {nombre} explicando que su incapacidad (serial {serial}) está incompleta.

**CONTEXTO IMPORTANTE:**
- El destinatario puede ser una persona mayor o con poca experiencia
- Debes ser EXTREMADAMENTE específico y claro
- Usa un lenguaje simple, sin tecnicismos
- Repite instrucciones si es necesario para mayor claridad

**Problemas encontrados:**
{problemas_texto}

**Tipo de incapacidad:** {tipo_incapacidad}

**Documentos SIEMPRE requeridos para {tipo_incapacidad}:**
{docs_texto}

**INSTRUCCIONES DE REDACCIÓN:**
1. Saluda de forma amable
2. Explica QUÉ documentos faltan o tienen problemas (usa **negritas** para resaltar nombres de documentos)
3. Da instrucciones PASO A PASO de cómo corregir
4. Si falta un documento, explica DÓNDE conseguirlo (EPS, Notaría, etc.)
5. Si está recortado/ilegible, da consejos PRÁCTICOS de cómo tomar fotos
6. Incluye la lista completa de documentos siempre requeridos al final
7. Recuerda que debe enviar TODO junto
8. Cierra de forma motivadora

**TONO:**
- Amable pero firme
- Paciente y comprensivo
- Máximo 250 palabras
- Usa saltos de línea para mejor legibilidad

**FORMATO:**
- Solo el cuerpo del mensaje (sin asunto ni firma)
- Usa **negritas** para documentos importantes
- Usa números para pasos (1., 2., 3.)
- Usa viñetas (•) para listas

**IMPORTANTE:**
- NO inventes información
- NO menciones leyes o normativas
- NO uses lenguaje técnico o jurídico
- SÍ sé específico con nombres de documentos
- SÍ da instrucciones claras y repetidas

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
        # Fallback a plantilla estática MUY CLARA
        return f"""Hola {nombre},

Tu incapacidad **{serial}** necesita correcciones:

**PROBLEMAS ENCONTRADOS:**
{problemas_texto}

**DOCUMENTOS SIEMPRE REQUERIDOS PARA {tipo_incapacidad.upper()}:**
{docs_texto}

**QUÉ DEBES HACER:**
1. Revisa los problemas de arriba
2. Corrige o consigue los documentos que faltan
3. Asegúrate de enviar TODOS los documentos juntos
4. Verifica que las fotos sean claras y completas

**CONSEJOS PARA FOTOS CLARAS:**
- Usa buena luz (preferible luz natural)
- Coloca el documento plano sobre una mesa
- Asegúrate de que se vean TODOS los bordes
- No uses flash (causa reflejos)
- Verifica que el texto sea legible

Por favor, envía todo de nuevo lo antes posible.

Estamos para ayudarte."""


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
    
    prompt = f"""Redacta un email MUY CLARO para {nombre} explicando que sus documentos (serial {serial}) tienen problemas de calidad.

**Problemas de calidad:**
{problemas_texto}

**INSTRUCCIONES:**
- Tono amable y paciente
- Máximo 200 palabras
- Da consejos PRÁCTICOS y DETALLADOS para tomar fotos claras
- Usa lenguaje simple (para personas mayores)
- Usa **negritas** para énfasis
- Incluye lista numerada de pasos

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

Tus documentos (**serial {serial}**) no se pueden leer bien por estos problemas:

{problemas_texto}

**CÓMO TOMAR FOTOS CLARAS (Paso a paso):**

1. **Luz:** Colócate cerca de una ventana (luz natural es mejor)
2. **Mesa:** Pon el documento sobre una mesa o superficie plana
3. **Posición:** Toma la foto desde arriba, perpendicular al documento
4. **Bordes:** Asegúrate de que se vean LOS 4 BORDES del documento
5. **Sin flash:** No uses flash (causa reflejos)
6. **Verifica:** Antes de enviar, aumenta la imagen y verifica que puedes leer el texto

**IMPORTANTE:** Si el documento es de varias páginas, toma foto a CADA página por separado.

Vuelve a enviar los documentos con mejor calidad, por favor."""


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

Es MUY IMPORTANTE que completes este proceso lo antes posible para poder continuar con tu radicación.

Si tienes dudas sobre qué documentos necesitas enviar, contáctanos.

Estamos para ayudarte."""


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
Agradeceríamos su apoyo para recordarle la importancia de completar este proceso, ya que está afectando los tiempos de radicación.

Si tiene dudas, estamos disponibles para brindar soporte.

Gracias por su colaboración."""


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
                "Pasa a radicación. Agradecer. Máx 150 palabras."}]
        )
        return message.content[0].text.strip()
    except:
        return f"¡Excelentes noticias {nombre}! Tu incapacidad **{serial}** fue VALIDADA. Pasa a radicación."