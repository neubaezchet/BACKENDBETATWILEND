"""
Plantillas de WhatsApp (message templates) de IncaNeurobaeza.

**Por qué viven aquí y no en WhatsApp Manager:** mismo criterio que
`app/agentes/` — una plantilla escrita a mano en la consola de Meta queda
fuera de todo diff, nadie sabe quién la cambió ni cómo era antes, y si se
pierde el acceso a la cuenta no hay forma de reconstruirla. Aquí son código:
se revisan, se versionan y se publican con
`python -m app.plantillas.sincronizar`.

**Cuándo hace falta una plantilla:** Meta solo acepta texto libre dentro de
las 24 horas siguientes al último mensaje del colaborador. Pasado ese plazo
responde error 131047 y el mensaje no llega. Como los avisos de esta
operación (radicada, rechazada, pago reconocido, recordatorio de soporte)
salen días después, casi siempre caen fuera de la ventana: sin plantilla el
colaborador simplemente nunca se entera. Ver `app/services/whatsapp_envio.py`,
que elige texto libre o plantilla según la ventana.

**Categoría UTILITY** en todas: son avisos sobre un trámite que el
colaborador ya inició, no publicidad. Es la categoría barata, la que Meta
aprueba rápido, y la única defendible aquí — mandar esto como MARKETING es
pedir que la línea baje de calificación de calidad.

Reglas de Meta que respeta este archivo (romperlas = rechazo en revisión):
  - el cuerpo no empieza ni termina con variable;
  - no hay dos variables seguidas;
  - encabezado <= 60 caracteres, pie <= 60 y sin variables;
  - toda variable trae ejemplo (Meta lo exige para aprobar);
  - en los botones URL la variable va al final de la URL.

Formato: *negrita*, _cursiva_. WhatsApp no tiene más; todo lo demás es
espaciado y jerarquía, que es de donde sale que se vea ordenado y no un
bloque de texto.
"""

import os
from typing import Dict, List, Optional, Sequence

# Meta usa "es" para español genérico. No existe "es_CO": si se pone, la
# creación falla con "Invalid language".
IDIOMA = "es"

# Mismo origen que app/services/portal_links.py — no se duplica la constante
# para que un cambio de dominio no deje las plantillas apuntando al viejo.
REPOGEMIN_ORIGIN = os.environ.get("REPOGEMIN_ORIGIN", "https://repogemin.vercel.app")

# El pie es el mismo en todas a propósito: es la firma de la operación y lo
# que le dice al colaborador que el mensaje no viene de un tercero.
PIE = "IncaNeurobaeza · Gestión de incapacidades"


PLANTILLAS: Dict[str, dict] = {

    # ── 1. Acuse de recibo ────────────────────────────────────────────────
    # Se manda al crear el caso. Es el que más tranquiliza: sin él la gente
    # vuelve a mandar la misma incapacidad por segunda y tercera vez.
    "incapacidad_recibida": {
        "categoria": "UTILITY",
        "encabezado": "Recibimos tu incapacidad",
        "cuerpo": (
            "Hola {{1}}, ya tenemos tu incapacidad y está en revisión.\n"
            "\n"
            "*Radicado interno:* {{2}}\n"
            "*Periodo:* {{3}}\n"
            "*EPS:* {{4}}\n"
            "\n"
            "Por ahora no tienes que hacer nada. Te escribimos por este mismo "
            "chat apenas haya novedad."
        ),
        "pie": PIE,
        "botones": [
            {"tipo": "QUICK_REPLY", "texto": "Ver mis incapacidades"},
        ],
        "variables": ("nombre", "serial", "periodo", "eps"),
        "ejemplo": ("Laura", "INC-2026-0412", "12 al 18 de septiembre", "Compensar"),
    },

    # ── 2. Recordatorio de soporte pendiente ──────────────────────────────
    # El que más se manda y el de más riesgo: si se repite sin medida la gente
    # bloquea el número y Meta baja la calificación de calidad de la línea.
    # La cadencia la controla scheduler_recordatorios.py, no este archivo.
    "incapacidad_soporte_pendiente": {
        "categoria": "UTILITY",
        "encabezado": "Falta un soporte",
        "cuerpo": (
            "Hola {{1}}, tu incapacidad {{2}} todavía no se puede radicar ante "
            "la EPS porque falta documentación.\n"
            "\n"
            "*Falta:* {{3}}\n"
            "*Periodo:* {{4}}\n"
            "\n"
            "Puedes enviarlo desde el botón de abajo; con una foto sirve. "
            "Mientras el soporte no llegue, la EPS no reconoce el pago de "
            "esos días."
        ),
        "pie": PIE,
        "botones": [
            {"tipo": "URL", "texto": "Enviar soporte",
             "url": f"{REPOGEMIN_ORIGIN}/?empresa=",
             "url_ejemplo": f"{REPOGEMIN_ORIGIN}/?empresa=acme"},
            {"tipo": "QUICK_REPLY", "texto": "Ya lo envié"},
        ],
        "variables": ("nombre", "serial", "documento_faltante", "periodo"),
        "ejemplo": ("Laura", "INC-2026-0412", "Resumen de atención",
                    "12 al 18 de septiembre"),
        "variables_boton_url": ("slug_empresa",),
    },

    # ── 3. Radicada ante la EPS ───────────────────────────────────────────
    "incapacidad_radicada": {
        "categoria": "UTILITY",
        "encabezado": "Radicada ante la EPS",
        "cuerpo": (
            "Hola {{1}}, tu incapacidad quedó radicada ante {{2}}.\n"
            "\n"
            "*Radicado EPS:* {{3}}\n"
            "*Periodo:* {{4}}\n"
            "*Días:* {{5}}\n"
            "\n"
            "Guarda ese número: es tu comprobante ante la EPS. El "
            "reconocimiento del pago lo decide la EPS y te avisamos aquí "
            "cuando salga."
        ),
        "pie": PIE,
        "botones": [
            {"tipo": "QUICK_REPLY", "texto": "Ver mis incapacidades"},
        ],
        "variables": ("nombre", "eps", "radicado_eps", "periodo", "dias"),
        "ejemplo": ("Laura", "Compensar", "RAD-8891023",
                    "12 al 18 de septiembre", "7"),
    },

    # ── 4. Devuelta / rechazada por la EPS ────────────────────────────────
    # Clave el cierre: el colaborador NO debe ir a la EPS. Si va, estorba la
    # corrección y además se lleva un mal rato para nada.
    "incapacidad_rechazada": {
        "categoria": "UTILITY",
        "encabezado": "La EPS devolvió tu incapacidad",
        "cuerpo": (
            "Hola {{1}}, la EPS {{2}} devolvió tu incapacidad {{3}} y te "
            "contamos por qué.\n"
            "\n"
            "*Motivo:* {{4}}\n"
            "*Periodo:* {{5}}\n"
            "\n"
            "Nosotros nos encargamos de corregirla y volverla a radicar. Si "
            "necesitamos algo tuyo te lo pedimos por aquí — no tienes que ir "
            "a la EPS."
        ),
        "pie": PIE,
        "botones": [
            {"tipo": "QUICK_REPLY", "texto": "Necesito ayuda"},
        ],
        "variables": ("nombre", "eps", "serial", "motivo", "periodo"),
        "ejemplo": ("Laura", "Compensar", "INC-2026-0412",
                    "Falta resumen de atención", "12 al 18 de septiembre"),
    },

    # ── 5. Pago reconocido ────────────────────────────────────────────────
    # Cierra el ciclo y, por la regla de negocio, apaga la petición de
    # soportes: si la EPS pagó, no se le sigue pidiendo nada al colaborador.
    "incapacidad_pago_reconocido": {
        "categoria": "UTILITY",
        "encabezado": "La EPS reconoció tu pago",
        "cuerpo": (
            "Hola {{1}}, buenas noticias: {{2}} reconoció el pago de tu "
            "incapacidad {{3}}.\n"
            "\n"
            "*Periodo:* {{4}}\n"
            "*Valor reconocido:* {{5}}\n"
            "\n"
            "El desembolso lo hace tu empresa según su calendario de nómina. "
            "Este caso queda cerrado y no necesitamos más documentos tuyos."
        ),
        "pie": PIE,
        "botones": [
            {"tipo": "QUICK_REPLY", "texto": "Ver mis incapacidades"},
        ],
        "variables": ("nombre", "eps", "serial", "periodo", "valor"),
        "ejemplo": ("Laura", "Compensar", "INC-2026-0412",
                    "12 al 18 de septiembre", "$ 412.300"),
    },

    # ── 6. Alerta al jefe ─────────────────────────────────────────────────
    # Va a un interlocutor distinto (líder / TTHH), con el argumento que a esa
    # persona sí le importa: la plata que la empresa deja de recobrar.
    "alerta_soporte_pendiente_jefe": {
        "categoria": "UTILITY",
        "encabezado": "Colaborador con soporte pendiente",
        "cuerpo": (
            "Hola {{1}}, te escribimos porque {{2}} tiene una incapacidad que "
            "no se ha podido radicar ante la EPS.\n"
            "\n"
            "*Documento:* {{3}}\n"
            "*Falta:* {{4}}\n"
            "*Pendiente hace:* {{5}} días\n"
            "\n"
            "Ya le pedimos el soporte directamente y no lo ha enviado. "
            "Mientras siga incompleta, la EPS no reconoce el pago de esos "
            "días a la empresa."
        ),
        "pie": PIE,
        "botones": [
            {"tipo": "QUICK_REPLY", "texto": "Ya lo gestioné"},
        ],
        "variables": ("nombre_jefe", "nombre_colaborador", "documento",
                      "documento_faltante", "dias_pendiente"),
        "ejemplo": ("Andrés", "Laura Gómez", "1.032.445.190",
                    "Resumen de atención", "5"),
    },
}


# ═══════════════════════════════════════════════════════════════════════════
# CONSTRUCCIÓN DE PAYLOADS
# ═══════════════════════════════════════════════════════════════════════════

def componentes_para_crear(nombre: str) -> List[dict]:
    """
    Traduce la definición de arriba al formato que espera
    POST /{WABA_ID}/message_templates.
    """
    p = PLANTILLAS[nombre]
    componentes: List[dict] = []

    if p.get("encabezado"):
        componentes.append({
            "type": "HEADER", "format": "TEXT", "text": p["encabezado"],
        })

    cuerpo: dict = {"type": "BODY", "text": p["cuerpo"]}
    if p.get("ejemplo"):
        # Meta espera una lista de listas: un juego de ejemplos por variable.
        cuerpo["example"] = {"body_text": [list(p["ejemplo"])]}
    componentes.append(cuerpo)

    if p.get("pie"):
        componentes.append({"type": "FOOTER", "text": p["pie"]})

    if p.get("botones"):
        botones = []
        for b in p["botones"]:
            if b["tipo"] == "URL":
                boton = {"type": "URL", "text": b["texto"], "url": b["url"] + "{{1}}"}
                if b.get("url_ejemplo"):
                    boton["example"] = [b["url_ejemplo"]]
                botones.append(boton)
            else:
                botones.append({"type": "QUICK_REPLY", "text": b["texto"]})
        componentes.append({"type": "BUTTONS", "buttons": botones})

    return componentes


def payload_para_crear(nombre: str) -> dict:
    """Cuerpo completo del POST que crea la plantilla en Meta."""
    return {
        "name": nombre,
        "language": IDIOMA,
        "category": PLANTILLAS[nombre]["categoria"],
        "components": componentes_para_crear(nombre),
    }


def payload_para_enviar(
    nombre: str,
    telefono: str,
    valores: Sequence[str],
    valor_boton_url: Optional[str] = None,
) -> dict:
    """
    Cuerpo del POST /{PHONE_ID}/messages para enviar la plantilla ya llena.

    `valores` va en el mismo orden que la tupla `variables` de la definición —
    por eso esa tupla existe: para que el orden esté documentado en un solo
    lugar y no haya que adivinarlo contando llaves dentro del texto.
    """
    p = PLANTILLAS[nombre]
    esperadas = len(p["variables"])
    if len(valores) != esperadas:
        raise ValueError(
            f"La plantilla '{nombre}' espera {esperadas} variables "
            f"{p['variables']} y recibió {len(valores)}."
        )

    componentes: List[dict] = [{
        "type": "body",
        "parameters": [{"type": "text", "text": str(v)} for v in valores],
    }]

    if p.get("variables_boton_url"):
        if valor_boton_url is None:
            raise ValueError(
                f"La plantilla '{nombre}' tiene un botón URL con variable "
                f"{p['variables_boton_url']} y no se pasó `valor_boton_url`."
            )
        componentes.append({
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [{"type": "text", "text": str(valor_boton_url)}],
        })

    return {
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "template",
        "template": {
            "name": nombre,
            "language": {"code": IDIOMA},
            "components": componentes,
        },
    }
