# -*- coding: utf-8 -*-
"""
Sistema de Templates de Email - Compatible con TODOS los clientes de correo
IncaNeurobaeza - 2026

Compatibilidad: Gmail, Outlook (Desktop/Web/Mobile), Yahoo, Apple Mail, Thunderbird
Principios:
  - Table-based layout (600px) - NO div/flexbox/grid
  - Inline CSS en cada elemento
  - HTML entities para iconos (&#9989; &#10060; etc) - NO emojis UTF-8 raw
  - bgcolor en <td> para fondos - NO background-color CSS solo
  - MSO conditional comments para Outlook
  - Fuentes seguras: Segoe UI, Arial, sans-serif
  - Estilo Microsoft 365 2026
"""


# =====================================================================
# PLANTILLA BASE - ESTRUCTURA TABLE-BASED UNIVERSAL
# =====================================================================

def _base_template(titulo, color_header, contenido_body, serial="", telefono="", email_contacto="", link_drive=""):
    """
    Plantilla base table-based compatible con TODOS los clientes.
    Estructura: wrapper > container 600px > header + body + footer
    """
    contacto_html = ""
    if telefono or email_contacto:
        contacto_html = f"""
                <!-- CONTACTO -->
                <tr>
                    <td bgcolor="#F3F2F1" style="background-color:#F3F2F1; padding:16px 24px; text-align:center; font-family:'Segoe UI',Arial,sans-serif; font-size:13px; color:#605E5C;">
                        &#128222; <strong>{telefono}</strong> &nbsp;&nbsp;|&nbsp;&nbsp; &#9993; <strong>{email_contacto}</strong>
                    </td>
                </tr>"""

    drive_html = ""
    if link_drive:
        drive_html = f"""
                <!-- LINK DRIVE -->
                <tr>
                    <td align="center" style="padding:16px 24px;">
                        <table cellpadding="0" cellspacing="0" border="0">
                            <tr>
                                <td bgcolor="#F3F2F1" style="background-color:#F3F2F1; padding:12px 28px;">
                                    <a href="{link_drive}" style="color:#0078D4; text-decoration:underline; font-family:'Segoe UI',Arial,sans-serif; font-size:14px; font-weight:600;">&#128196; Ver documentos en Drive</a>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>"""

    return f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
    <title>{titulo} - {serial}</title>
    <!--[if mso]>
    <style type="text/css">
        body, table, td, p, a, span {{font-family: Arial, sans-serif !important;}}
        table {{border-collapse: collapse;}}
    </style>
    <![endif]-->
</head>
<body style="margin:0; padding:0; background-color:#F3F2F1; font-family:'Segoe UI',Arial,sans-serif; -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%;">

    <!-- WRAPPER -->
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#F3F2F1;">
        <tr>
            <td align="center" style="padding:20px 10px;">

                <!--[if mso]><table width="600" cellpadding="0" cellspacing="0" border="0" align="center"><tr><td><![endif]-->
                <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:600px; background-color:#FFFFFF;">

                    <!-- HEADER -->
                    <tr>
                        <td bgcolor="{color_header}" style="background-color:{color_header}; padding:32px 24px; text-align:center;">
                            <table width="100%" cellpadding="0" cellspacing="0" border="0">
                                <tr>
                                    <td align="center" style="padding-bottom:12px;">
                                        <table cellpadding="0" cellspacing="0" border="0">
                                            <tr>
                                                <td width="48" height="48" bgcolor="#FFFFFF" style="background-color:#FFFFFF; text-align:center; font-size:24px; line-height:48px; color:{color_header};">
                                                    <!--[if mso]><v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" style="height:48px;v-text-anchor:middle;width:48px;" arcsize="50%" fillcolor="#FFFFFF" stroke="f"><v:textbox><center style="color:{color_header};font-size:24px;">&#9679;</center></v:textbox></v:roundrect><![endif]-->
                                                    <!--[if !mso]>-->&#9679;<!--<![endif]-->
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                                <tr>
                                    <td align="center" style="color:#FFFFFF; font-size:22px; font-weight:700; font-family:'Segoe UI',Arial,sans-serif; line-height:1.3;">
                                        {titulo}
                                    </td>
                                </tr>
                                <tr>
                                    <td align="center" style="color:#FFFFFF; font-size:13px; font-family:'Segoe UI',Arial,sans-serif; padding-top:6px; font-style:italic; opacity:0.9;">
                                        IncaNeurobaeza
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- BARRA DECORATIVA -->
                    <tr>
                        <td height="4" bgcolor="{color_header}" style="background-color:{color_header}; font-size:1px; line-height:1px; opacity:0.6;">&nbsp;</td>
                    </tr>

                    <!-- BODY -->
                    <tr>
                        <td style="padding:28px 24px; font-family:'Segoe UI',Arial,sans-serif; font-size:15px; color:#323130; line-height:1.6;">
                            <table width="100%" cellpadding="0" cellspacing="0" border="0">
{contenido_body}
                            </table>
                        </td>
                    </tr>
{drive_html}
{contacto_html}

                    <!-- FOOTER -->
                    <tr>
                        <td bgcolor="#F3F2F1" style="background-color:#F3F2F1; padding:24px; text-align:center; border-top:2px solid #EDEBE9;">
                            <table width="100%" cellpadding="0" cellspacing="0" border="0">
                                <tr>
                                    <td align="center" style="padding-bottom:6px;">
                                        <strong style="color:#0078D4; font-size:17px; font-family:'Segoe UI',Arial,sans-serif;">IncaNeurobaeza</strong>
                                    </td>
                                </tr>
                                <tr>
                                    <td align="center">
                                        <span style="color:#605E5C; font-size:12px; font-family:'Segoe UI',Arial,sans-serif; font-style:italic;">"Trabajando para ayudarte"</span>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                </table>
                <!--[if mso]></td></tr></table><![endif]-->

            </td>
        </tr>
    </table>

</body>
</html>"""


# =====================================================================
# BLOQUES REUTILIZABLES (Table-based, Outlook-safe)
# =====================================================================

def _bloque_mensaje(bgcolor, border_color, texto_titulo, texto_cuerpo):
    """Bloque de mensaje con borde izquierdo - estilo Microsoft 365"""
    titulo_html = ""
    if texto_titulo:
        titulo_html = f'<strong style="font-size:15px; color:#323130; font-family:\'Segoe UI\',Arial,sans-serif; display:block; padding-bottom:6px;">{texto_titulo}</strong>'
    return f"""
                                <tr>
                                    <td style="padding:8px 0;">
                                        <table width="100%" cellpadding="0" cellspacing="0" border="0">
                                            <tr>
                                                <td width="4" bgcolor="{border_color}" style="background-color:{border_color};">&nbsp;</td>
                                                <td bgcolor="{bgcolor}" style="background-color:{bgcolor}; padding:18px 20px;">
                                                    {titulo_html}
                                                    <span style="font-size:14px; color:#323130; font-family:'Segoe UI',Arial,sans-serif; line-height:1.6;">{texto_cuerpo}</span>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
"""


def _bloque_alerta(bgcolor, texto, border_color="#EDEBE9"):
    """Bloque de alerta centrado con borde superior"""
    return f"""
                                <tr>
                                    <td style="padding:8px 0;">
                                        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top:2px solid {border_color}; border-bottom:2px solid {border_color};">
                                            <tr>
                                                <td bgcolor="{bgcolor}" style="background-color:{bgcolor}; padding:14px 20px; text-align:center;">
                                                    <span style="font-size:14px; color:#323130; font-family:'Segoe UI',Arial,sans-serif; line-height:1.5;">{texto}</span>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
"""


def _bloque_boton(url, texto, color_bg):
    """Boton CTA estilo Microsoft 365 - table-based, Outlook compatible"""
    return f"""
                                <tr>
                                    <td align="center" style="padding:20px 0;">
                                        <table cellpadding="0" cellspacing="0" border="0">
                                            <tr>
                                                <!--[if mso]>
                                                <td bgcolor="{color_bg}" style="background-color:{color_bg}; padding:14px 36px;">
                                                    <a href="{url}" style="color:#FFFFFF; text-decoration:none; font-size:15px; font-weight:700; font-family:Arial,sans-serif;">{texto}</a>
                                                </td>
                                                <![endif]-->
                                                <!--[if !mso]>-->
                                                <td bgcolor="{color_bg}" style="background-color:{color_bg}; padding:14px 36px; border-radius:4px;">
                                                    <a href="{url}" style="display:block; color:#FFFFFF; text-decoration:none; font-size:15px; font-weight:700; font-family:'Segoe UI',Arial,sans-serif;">{texto}</a>
                                                </td>
                                                <!--<![endif]-->
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
"""


def _bloque_tabla_info(filas):
    """Tabla de datos key-value estilo Fluent UI / Microsoft 365"""
    rows = ""
    for i, (label, valor) in enumerate(filas):
        bg = "#FAF9F8" if i % 2 == 0 else "#FFFFFF"
        rows += f"""
                                                    <tr>
                                                        <td bgcolor="{bg}" style="background-color:{bg}; padding:10px 14px; color:#605E5C; font-size:13px; font-family:'Segoe UI',Arial,sans-serif; width:140px; vertical-align:top; border-bottom:1px solid #EDEBE9;">{label}</td>
                                                        <td bgcolor="{bg}" style="background-color:{bg}; padding:10px 14px; color:#323130; font-size:13px; font-family:'Segoe UI',Arial,sans-serif; font-weight:600; border-bottom:1px solid #EDEBE9;">{valor}</td>
                                                    </tr>"""
    return f"""
                                <tr>
                                    <td style="padding:10px 0;">
                                        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #EDEBE9;">
                                            <tr>
                                                <td>
                                                    <table width="100%" cellpadding="0" cellspacing="0" border="0">
{rows}
                                                    </table>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
"""


def _bloque_lista(titulo, items, bgcolor="#EFF6FC", color_titulo="#004578"):
    """Lista con bullets - table-based, compatible Outlook"""
    items_html = ""
    for item in items:
        items_html += f"""
                                                        <tr>
                                                            <td width="24" style="vertical-align:top; padding:5px 0; font-size:14px; color:#605E5C;">&#8226;</td>
                                                            <td style="padding:5px 0; font-size:14px; color:#323130; font-family:'Segoe UI',Arial,sans-serif; line-height:1.5;">{item}</td>
                                                        </tr>"""
    return f"""
                                <tr>
                                    <td style="padding:8px 0;">
                                        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #D2E3FC;">
                                            <tr>
                                                <td bgcolor="{bgcolor}" style="background-color:{bgcolor}; padding:18px 20px;">
                                                    <strong style="font-size:14px; color:{color_titulo}; font-family:'Segoe UI',Arial,sans-serif; display:block; padding-bottom:10px;">{titulo}</strong>
                                                    <table width="100%" cellpadding="0" cellspacing="0" border="0">
{items_html}
                                                    </table>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
"""


def _bloque_checklist(titulo, items_ok, items_fail):
    """Checklist visual con OK/FAIL estilo Teams/Planner"""
    rows = ""
    for item_name, item_desc in items_fail:
        rows += f"""
                                                    <tr>
                                                        <td bgcolor="#FDE8E8" style="background-color:#FDE8E8; padding:12px 14px; border-bottom:2px solid #FFFFFF;">
                                                            <table width="100%" cellpadding="0" cellspacing="0" border="0">
                                                                <tr>
                                                                    <td width="30" style="vertical-align:top; color:#DC2626; font-size:16px; font-family:Arial,sans-serif;">&#10060;</td>
                                                                    <td style="font-family:'Segoe UI',Arial,sans-serif;">
                                                                        <strong style="color:#991B1B; font-size:14px;">{item_name}</strong><br/>
                                                                        <span style="color:#B91C1C; font-size:12px;">{item_desc}</span>
                                                                    </td>
                                                                </tr>
                                                            </table>
                                                        </td>
                                                    </tr>"""
    for item_name, item_desc in items_ok:
        rows += f"""
                                                    <tr>
                                                        <td bgcolor="#F0FDF4" style="background-color:#F0FDF4; padding:12px 14px; border-bottom:2px solid #FFFFFF;">
                                                            <table width="100%" cellpadding="0" cellspacing="0" border="0">
                                                                <tr>
                                                                    <td width="30" style="vertical-align:top; color:#16A34A; font-size:16px; font-family:Arial,sans-serif;">&#9989;</td>
                                                                    <td style="font-family:'Segoe UI',Arial,sans-serif;">
                                                                        <strong style="color:#166534; font-size:14px;">{item_name}</strong><br/>
                                                                        <span style="color:#15803D; font-size:12px;">{item_desc}</span>
                                                                    </td>
                                                                </tr>
                                                            </table>
                                                        </td>
                                                    </tr>"""
    return f"""
                                <tr>
                                    <td style="padding:10px 0;">
                                        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #E5E7EB;">
                                            <tr>
                                                <td bgcolor="#F9FAFB" style="background-color:#F9FAFB; padding:14px 18px; border-bottom:2px solid #E5E7EB;">
                                                    <strong style="font-size:15px; color:#374151; font-family:'Segoe UI',Arial,sans-serif;">&#128203; {titulo}</strong>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td style="padding:0;">
                                                    <table width="100%" cellpadding="0" cellspacing="0" border="0">
{rows}
                                                    </table>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
"""


# =====================================================================
# FUNCIONES DE CONTENIDO
# =====================================================================

def generar_explicacion_checks(checks):
    """Convierte checks en explicacion en lenguaje natural"""
    from app.checks_disponibles import CHECKS_DISPONIBLES

    mensajes = []
    for check_key in checks:
        if check_key in CHECKS_DISPONIBLES:
            mensajes.append(CHECKS_DISPONIBLES[check_key]['descripcion'])

    if not mensajes:
        return "Se encontraron observaciones que requieren correccion."
    elif len(mensajes) == 1:
        return mensajes[0]
    else:
        return "<br/>".join([f"&#8226; {msg}" for msg in mensajes])


def generar_lista_soportes_requeridos(tipo_incapacidad):
    """Genera lista de soportes requeridos segun tipo"""

    soportes = {
        'Enfermedad General': {
            'origen': 'Origen Comun',
            'docs': [
                'Incapacidad medica (emitida por la EPS)',
                'Epicrisis o resumen de atencion (todas las paginas)'
            ]
        },
        'Enfermedad Laboral': {
            'origen': 'Origen Laboral',
            'docs': [
                'Incapacidad medica (emitida por la ARL)',
                'Epicrisis o resumen de atencion (todas las paginas)'
            ]
        },
        'Maternidad': {
            'origen': 'Origen Comun',
            'docs': [
                'Licencia de maternidad (emitida por la EPS)',
                'Epicrisis o resumen de atencion (todas las paginas)',
                'Certificado de nacido vivo',
                'Registro civil del bebe'
            ]
        },
        'Paternidad': {
            'origen': 'Origen Comun',
            'docs': [
                'Incapacidad de paternidad (emitida por la EPS)',
                'Epicrisis o resumen de atencion de la madre (todas las paginas)',
                'Cedula del padre (ambas caras)',
                'Certificado de nacido vivo',
                'Registro civil del bebe',
                'Licencia de maternidad de la madre (si trabaja)'
            ]
        },
        'Accidente de Transito': {
            'origen': 'Origen Comun',
            'docs': [
                'Incapacidad medica (emitida por la EPS)',
                'Epicrisis o resumen de atencion (todas las paginas)',
                'FURIPS (Formato Unico de Reporte)',
                'SOAT del vehiculo (si fue identificado)'
            ]
        }
    }

    info = soportes.get(tipo_incapacidad)
    if not info:
        return ''

    return _bloque_lista(
        f"&#128203; Soportes requeridos para {info['origen']}:",
        info['docs'],
        bgcolor="#EFF6FC",
        color_titulo="#004578"
    )


def generar_checklist_requisitos(tipo_incapacidad, checks_faltantes, tipo_email):
    """Genera checklist visual estilo Teams/Planner"""

    requisitos_completos = {
        'Maternidad': [
            ('incapacidad', 'Incapacidad o licencia de maternidad', 'Documento oficial emitido por EPS con todas las paginas'),
            ('epicrisis', 'Epicrisis o resumen de atencion', 'Documento completo con todas las paginas, sin recortes'),
            ('nacido_vivo', 'Certificado de nacido vivo', 'Original legible y sin recortes'),
            ('registro_civil', 'Registro civil del bebe', 'Completo y legible'),
        ],
        'Paternidad': [
            ('incapacidad', 'Incapacidad de paternidad', 'Documento oficial emitido por EPS'),
            ('epicrisis', 'Epicrisis o resumen de atencion de la madre', 'Documento completo con todas las paginas'),
            ('cedula_padre', 'Cedula del padre', 'Ambas caras legibles'),
            ('nacido_vivo', 'Certificado de nacido vivo', 'Original legible'),
            ('registro_civil', 'Registro civil del bebe', 'Completo y legible'),
            ('licencia_maternidad', 'Licencia de maternidad de la madre (si trabaja)', 'Solo si la madre esta activa laboralmente'),
        ],
        'Accidente de Transito': [
            ('incapacidad', 'Incapacidad medica', 'Documento oficial emitido por EPS con todas las paginas'),
            ('epicrisis', 'Epicrisis o resumen de atencion', 'Documento completo, sin recortes'),
            ('furips', 'FURIPS (Formato Unico de Reporte)', 'Completo y legible'),
            ('soat', 'SOAT del vehiculo', 'Solo si el vehiculo fue identificado'),
        ],
        'Enfermedad General': [
            ('incapacidad', 'Incapacidad medica', 'Documento oficial emitido por EPS con todas las paginas'),
            ('epicrisis', 'Epicrisis o resumen de atencion', 'Requerido para incapacidades de 3 o mas dias'),
        ],
        'Enfermedad Laboral': [
            ('incapacidad', 'Incapacidad medica', 'Documento oficial emitido por ARL con todas las paginas'),
            ('epicrisis', 'Epicrisis o resumen de atencion', 'Requerido para incapacidades de 3 o mas dias'),
        ],
    }

    requisitos = requisitos_completos.get(tipo_incapacidad, [])
    if not requisitos:
        return ''

    items_ok = []
    items_fail = []
    for codigo, nombre_r, descripcion in requisitos:
        faltante = any(codigo in check for check in checks_faltantes)
        if faltante:
            items_fail.append((nombre_r, descripcion))
        else:
            items_ok.append((nombre_r, descripcion))

    return _bloque_checklist(f"Requisitos para {tipo_incapacidad}", items_ok, items_fail)


def generar_mensaje_segun_tipo(tipo_email, checks, tipo_incapacidad, serial, quinzena=None, archivos_nombres=None):
    """Genera contenido principal segun tipo de notificacion"""

    if tipo_email == 'confirmacion':
        archivos_html = ""
        if archivos_nombres:
            for archivo in archivos_nombres:
                archivos_html += f"""
                                                        <tr>
                                                            <td bgcolor="#EFF6FC" style="background-color:#EFF6FC; padding:10px 14px; border-bottom:2px solid #FFFFFF; border-left:4px solid #0078D4;">
                                                                <span style="font-size:14px; color:#004578; font-family:'Segoe UI',Arial,sans-serif;">&#128196; {archivo}</span>
                                                            </td>
                                                        </tr>"""

        resultado = _bloque_mensaje(
            "#EFF6FC", "#0078D4",
            "&#9989; Confirmo recibido de la documentacion",
            f"Se procedera a realizar la revision para validar que cumpla con los requisitos establecidos para <strong>{tipo_incapacidad}</strong>."
        )

        if archivos_html:
            resultado += f"""
                                <tr>
                                    <td style="padding:8px 0;">
                                        <table width="100%" cellpadding="0" cellspacing="0" border="0">
                                            <tr>
                                                <td style="padding-bottom:8px;">
                                                    <strong style="font-size:14px; color:#323130; font-family:'Segoe UI',Arial,sans-serif;">&#128270; Documentos recibidos:</strong>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td>
                                                    <table width="100%" cellpadding="0" cellspacing="0" border="0">
{archivos_html}
                                                    </table>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
"""
        return resultado

    elif tipo_email == 'incompleta':
        explicacion = generar_explicacion_checks(checks)
        soportes_html = generar_lista_soportes_requeridos(tipo_incapacidad)
        return (
            _bloque_mensaje(
                "#FDE8E8", "#DC2626",
                f"&#10060; Incapacidad {serial} - Documentacion Incompleta",
                f"<strong>Motivo:</strong><br/>{explicacion}"
            )
            + soportes_html
            + _bloque_alerta(
                "#EFF6FC",
                "&#128196; <strong>Formato:</strong> Enviar en <strong>PDF escaneado</strong>. Asegurese de que el documento este completo y legible.",
                "#D2E3FC"
            )
            + _bloque_alerta(
                "#FFF4CE",
                "Si no cuenta con algun soporte, <strong>dirijase al punto de atencion mas cercano de su EPS y solicitelo</strong>.",
                "#FFE066"
            )
            + _bloque_alerta(
                "#F3F2F1",
                "Comuniquese si tiene alguna duda.",
                "#EDEBE9"
            )
        )

    elif tipo_email == 'ilegible':
        explicacion = generar_explicacion_checks(checks)
        return (
            _bloque_mensaje(
                "#FFF4CE", "#D97706",
                f"&#9888; Incapacidad {serial} - Documento Ilegible",
                f"<strong>Motivo:</strong><br/>{explicacion}"
            )
            + _bloque_alerta(
                "#EFF6FC",
                "&#128196; <strong>Formato:</strong> Enviar en <strong>PDF escaneado</strong>. Asegurese de que el documento este completo, sin recortes y con buena resolucion.",
                "#D2E3FC"
            )
            + _bloque_alerta(
                "#FFF4CE",
                "Si no cuenta con algun soporte, <strong>dirijase al punto de atencion mas cercano de su EPS y solicitelo</strong>.",
                "#FFE066"
            )
            + _bloque_alerta(
                "#F3F2F1",
                "Comuniquese si tiene alguna duda.",
                "#EDEBE9"
            )
        )

    elif tipo_email == 'eps':
        return _bloque_mensaje(
            "#FFF4CE", "#CA8A04",
            "&#128203; Transcripcion en EPS requerida",
            "Tu incapacidad requiere <strong>transcripcion fisica en tu EPS</strong>. "
            "Por favor, dirigete a tu EPS con tu documento de identidad y solicita la "
            "transcripcion de esta incapacidad. Una vez tengas el documento transcrito, "
            "subelo nuevamente al sistema."
        )

    elif tipo_email == 'completa':
        return (
            _bloque_mensaje(
                "#D1FAE5", "#16A34A",
                "&#9989; Tu incapacidad ha sido validada exitosamente",
                "Tu caso ha sido subido al sistema exitosamente para el proceso de validacion. "
                "Nos comunicaremos contigo cuando el proceso este completo."
            )
            + _bloque_alerta(
                "#F3F2F1",
                "&#128204; Recepcion &rarr; <strong>Validacion</strong> &rarr; Subida al sistema",
                "#EDEBE9"
            )
        )

    elif tipo_email == 'tthh':
        return _bloque_mensaje(
            "#FDE8E8", "#DC2626",
            "&#9888; Incapacidad en Revision por Presunto Fraude",
            "La siguiente incapacidad presenta inconsistencias que requieren "
            "<strong>validacion adicional</strong> con la colaboradora."
        )

    elif tipo_email == 'falsa':
        return _bloque_mensaje(
            "#EFF6FC", "#0078D4",
            "&#9989; Confirmo recibido de la documentacion",
            "Se procedera a realizar la revision correspondiente."
        )

    return ""


def generar_seccion_ilegibilidad():
    """Seccion de formato PDF escaneado"""
    return (
        _bloque_alerta(
            "#EFF6FC",
            "&#128196; <strong>Formato de envio:</strong> Enviar los documentos en <strong>PDF escaneado</strong>. Asegurese de que esten completos, legibles y sin recortes.",
            "#D2E3FC"
        )
        + _bloque_alerta(
            "#FFF4CE",
            "Si no cuenta con algun soporte, <strong>dirijase al punto de atencion mas cercano de su EPS y solicitelo</strong>.",
            "#FFE066"
        )
    )


def generar_instrucciones(tipo_email):
    """Instrucciones para correccion"""
    return (
        _bloque_lista(
            "&#128221; Que debes hacer:",
            [
                "Adjunta nuevamente los soportes en <strong>PDF escaneado</strong>",
                "Verifica que los documentos esten <strong>completos y legibles</strong>",
                "Incluye <strong>TODOS</strong> los soportes marcados como faltantes"
            ],
            bgcolor="#EFF6FC",
            color_titulo="#004578"
        )
        + _bloque_alerta(
            "#FFF4CE",
            "Si no cuenta con algun soporte, <strong>dirijase al punto de atencion mas cercano de su EPS y solicitelo</strong>.",
            "#FFE066"
        )
        + _bloque_alerta(
            "#F3F2F1",
            "Comuniquese si tiene alguna duda.",
            "#EDEBE9"
        )
    )


def generar_aviso_wasap():
    """Aviso WhatsApp estilo Microsoft 365"""
    return _bloque_alerta(
        "#FFF4CE",
        "&#9888; <strong>IMPORTANTE:</strong> Estar pendiente<br/>"
        "&#128241; Primero via <strong>WhatsApp</strong> y luego por &#9993; <strong>correo electronico</strong><br/>"
        "<span style='font-size:12px;'>Comuniquese si tiene alguna duda.</span>",
        "#FFE066"
    )


def generar_detalles_caso(serial, nombre, empresa, tipo_incapacidad, telefono, email_contacto):
    """Tabla de detalles del caso (para TTHH)"""
    return _bloque_tabla_info([
        ("Serial:", f'<strong style="color:#DC2626;">{serial}</strong>'),
        ("Colaborador/a:", nombre),
        ("Empresa:", empresa),
        ("Tipo:", tipo_incapacidad),
        ("Telefono:", telefono),
        ("Email:", email_contacto),
    ])


# =====================================================================
# FUNCION PRINCIPAL
# =====================================================================

def get_email_template_universal_con_ia(
    tipo_email,
    nombre,
    serial,
    empresa,
    tipo_incapacidad,
    telefono,
    email,
    link_drive,
    checks_seleccionados=[],
    archivos_nombres=None,
    quinzena=None,
    contenido_ia=None,
    empleado_nombre=None
):
    """
    PLANTILLA UNIVERSAL 2026 - Compatible con TODOS los clientes de correo.
    Table-based, HTML entities, bgcolor, MSO conditionals.
    Estilo Microsoft 365 / Fluent UI.
    """

    configs = {
        'confirmacion': {
            'color': '#0078D4',
            'titulo': '&#9989; Incapacidad Recibida',
            'mostrar_requisitos': True,
            'mostrar_boton': False,
            'mostrar_plazo': False,
        },
        'incompleta': {
            'color': '#DC2626',
            'titulo': '&#10060; Documentacion Incompleta',
            'mostrar_requisitos': True,
            'mostrar_boton': True,
            'mostrar_plazo': True,
        },
        'ilegible': {
            'color': '#D97706',
            'titulo': '&#9888; Documento Ilegible',
            'mostrar_requisitos': True,
            'mostrar_boton': True,
            'mostrar_plazo': True,
        },
        'eps': {
            'color': '#CA8A04',
            'titulo': '&#128203; Transcripcion en EPS Requerida',
            'mostrar_requisitos': False,
            'mostrar_boton': True,
            'mostrar_plazo': False,
        },
        'completa': {
            'color': '#16A34A',
            'titulo': '&#9989; Incapacidad Validada',
            'mostrar_requisitos': False,
            'mostrar_boton': False,
            'mostrar_plazo': False,
        },
        'tthh': {
            'color': '#DC2626',
            'titulo': '&#9888; ALERTA - Presunto Fraude',
            'mostrar_requisitos': True,
            'mostrar_boton': False,
            'mostrar_plazo': False,
        },
        'falsa': {
            'color': '#0078D4',
            'titulo': '&#9989; Recibido Confirmado',
            'mostrar_requisitos': False,
            'mostrar_boton': False,
            'mostrar_plazo': False,
        },
        'recordatorio': {
            'color': '#D97706',
            'titulo': '&#9200; Recordatorio - Documentacion Pendiente',
            'mostrar_requisitos': False,
            'mostrar_boton': True,
            'mostrar_plazo': True,
        },
        'alerta_jefe': {
            'color': '#2563EB',
            'titulo': '&#128202; Seguimiento - Incapacidad Pendiente',
            'mostrar_requisitos': False,
            'mostrar_boton': False,
            'mostrar_plazo': False,
        },
    }

    config = configs.get(tipo_email, configs['confirmacion'])

    # ========== SALUDO ==========
    body = ''

    if tipo_email == 'tthh':
        body += f"""
                                <tr>
                                    <td style="padding:0 0 14px 0;">
                                        <p style="margin:0; font-size:15px; color:#323130; font-family:'Segoe UI',Arial,sans-serif;">Estimado equipo de <strong>Talento Humano</strong>,</p>
                                    </td>
                                </tr>
"""
    else:
        body += f"""
                                <tr>
                                    <td style="padding:0 0 14px 0;">
                                        <p style="margin:0; font-size:15px; color:#323130; font-family:'Segoe UI',Arial,sans-serif;">Hola <strong style="color:#0078D4;">{nombre}</strong>,</p>
                                    </td>
                                </tr>
"""

    # ========== MENSAJE PRINCIPAL ==========
    if contenido_ia:
        body += _bloque_mensaje(
            "#FAF9F8", config['color'],
            "",
            contenido_ia
        )
    else:
        body += generar_mensaje_segun_tipo(tipo_email, checks_seleccionados, tipo_incapacidad, serial, quinzena, archivos_nombres)

    # ========== DETALLES CASO (TTHH) ==========
    if tipo_email == 'tthh':
        body += generar_detalles_caso(serial, nombre, empresa, tipo_incapacidad, telefono, email)

    # ========== CHECKLIST REQUISITOS ==========
    if config['mostrar_requisitos']:
        body += generar_checklist_requisitos(tipo_incapacidad, checks_seleccionados, tipo_email)

    # ========== SECCION ILEGIBILIDAD ==========
    if 'ilegible' in tipo_email or any('ilegible' in c or 'recortada' in c or 'borrosa' in c for c in checks_seleccionados):
        body += generar_seccion_ilegibilidad()

    # ========== INSTRUCCIONES ==========
    if tipo_email in ['incompleta', 'ilegible']:
        body += generar_instrucciones(tipo_email)

    # ========== SECCION JEFE ==========
    if tipo_email == 'alerta_jefe' and empleado_nombre:
        body += _bloque_tabla_info([
            ("Colaborador/a:", empleado_nombre),
            ("Serial:", f'<strong style="color:#DC2626;">{serial}</strong>'),
            ("Empresa:", empresa),
            ("Contacto:", f"{telefono} &bull; {email}"),
        ])

    # ========== BOTON REENVIO ==========
    if config['mostrar_boton']:
        body += _bloque_boton(
            "https://repogemin.vercel.app/",
            "&#128260; Subir Documentos Corregidos",
            config['color']
        )

    # ========== PLAZO ==========
    if config['mostrar_plazo']:
        body += _bloque_alerta(
            "#FFF4CE",
            "&#9200; Por favor, envia la documentacion corregida lo antes posible",
            "#FFE066"
        )

    # ========== AVISO WHATSAPP ==========
    if tipo_email in ['confirmacion', 'incompleta', 'ilegible']:
        body += generar_aviso_wasap()

    # ========== HTML FINAL ==========
    return _base_template(
        titulo=config['titulo'],
        color_header=config['color'],
        contenido_body=body,
        serial=serial,
        telefono=telefono,
        email_contacto=email,
        link_drive=link_drive
    )


# =====================================================================
# WRAPPER PRINCIPAL (mantiene compatibilidad con todos los callers)
# =====================================================================

def get_email_template_universal(tipo_email, nombre, serial, empresa, tipo_incapacidad,
                                 telefono, email, link_drive, checks_seleccionados=[],
                                 archivos_nombres=None, quinzena=None, contenido_ia=None,
                                 empleado_nombre=None):
    """Wrapper principal - mantiene compatibilidad con todos los callers"""
    return get_email_template_universal_con_ia(
        tipo_email, nombre, serial, empresa, tipo_incapacidad,
        telefono, email, link_drive, checks_seleccionados,
        archivos_nombres, quinzena, contenido_ia, empleado_nombre
    )


# =====================================================================
# TEMPLATES LEGACY (compatibilidad con imports existentes)
# =====================================================================

def get_confirmation_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive, archivos_nombres=None):
    """Template de confirmacion"""
    return get_email_template_universal(
        tipo_email='confirmacion', nombre=nombre, serial=serial,
        empresa=empresa, tipo_incapacidad=tipo_incapacidad,
        telefono=telefono, email=email, link_drive=link_drive,
        archivos_nombres=archivos_nombres
    )


def get_alert_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive, checks_seleccionados=None):
    """Template para alertas incompleta/ilegible"""
    return get_email_template_universal(
        tipo_email='incompleta', nombre=nombre, serial=serial,
        empresa=empresa, tipo_incapacidad=tipo_incapacidad,
        telefono=telefono, email=email, link_drive=link_drive,
        checks_seleccionados=checks_seleccionados or []
    )


def get_ilegible_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive, checks_seleccionados=None):
    """Template para documentos ilegibles"""
    return get_email_template_universal(
        tipo_email='ilegible', nombre=nombre, serial=serial,
        empresa=empresa, tipo_incapacidad=tipo_incapacidad,
        telefono=telefono, email=email, link_drive=link_drive,
        checks_seleccionados=checks_seleccionados or []
    )


def get_eps_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive):
    """Template para transcripcion en EPS"""
    return get_email_template_universal(
        tipo_email='eps', nombre=nombre, serial=serial,
        empresa=empresa, tipo_incapacidad=tipo_incapacidad,
        telefono=telefono, email=email, link_drive=link_drive
    )


def get_completa_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive):
    """Template para caso validado completo"""
    return get_email_template_universal(
        tipo_email='completa', nombre=nombre, serial=serial,
        empresa=empresa, tipo_incapacidad=tipo_incapacidad,
        telefono=telefono, email=email, link_drive=link_drive
    )


def get_tthh_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive, checks_seleccionados=None):
    """Template para alertas a Talento Humano"""
    return get_email_template_universal(
        tipo_email='tthh', nombre=nombre, serial=serial,
        empresa=empresa, tipo_incapacidad=tipo_incapacidad,
        telefono=telefono, email=email, link_drive=link_drive,
        checks_seleccionados=checks_seleccionados or []
    )


def get_falsa_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive):
    """Template para confirmacion falsa"""
    return get_email_template_universal(
        tipo_email='falsa', nombre=nombre, serial=serial,
        empresa=empresa, tipo_incapacidad=tipo_incapacidad,
        telefono=telefono, email=email, link_drive=link_drive
    )


# =====================================================================
# EMAIL CAMBIO DE TIPO
# =====================================================================

def enviar_email_cambio_tipo(email_to, nombre, serial, tipo_anterior, tipo_nuevo, docs_requeridos):
    """Envia email informando cambio de tipo de incapacidad"""
    tipos_nombres = {
        'maternity': 'Maternidad',
        'paternity': 'Paternidad',
        'general': 'Enfermedad General',
        'traffic': 'Accidente de Transito',
        'labor': 'Accidente Laboral'
    }

    tipo_ant_nombre = tipos_nombres.get(tipo_anterior, tipo_anterior)
    tipo_nuevo_nombre = tipos_nombres.get(tipo_nuevo, tipo_nuevo)

    body = f"""
                                <tr>
                                    <td style="padding:0 0 14px 0;">
                                        <p style="margin:0; font-size:15px; color:#323130; font-family:'Segoe UI',Arial,sans-serif;">Hola <strong style="color:#0078D4;">{nombre}</strong>,</p>
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding:0 0 10px 0;">
                                        <p style="margin:0; font-size:14px; color:#323130; font-family:'Segoe UI',Arial,sans-serif;">Hemos actualizado el tipo de tu incapacidad <strong>{serial}</strong>:</p>
                                    </td>
                                </tr>
"""
    body += _bloque_tabla_info([
        ("Tipo anterior:", tipo_ant_nombre),
        ("Nuevo tipo:", f"<strong>{tipo_nuevo_nombre}</strong>"),
    ])
    body += _bloque_lista(
        "&#128221; Documentos requeridos:",
        docs_requeridos,
        bgcolor="#EFF6FC",
        color_titulo="#004578"
    )
    body += _bloque_lista(
        "&#128270; Que debes hacer:",
        [
            "Revisa la nueva lista de documentos",
            "Prepara TODOS los documentos solicitados",
            "Ingresa al portal con tu cedula",
            "Completa la incapacidad subiendo los documentos"
        ],
        bgcolor="#EFF6FC",
        color_titulo="#004578"
    )
    body += _bloque_boton(
        "https://repogemin.vercel.app/",
        "&#128260; Subir Documentos",
        "#D97706"
    )

    html = _base_template(
        titulo="&#128260; Actualizacion de Tipo de Incapacidad",
        color_header="#D97706",
        contenido_body=body,
        serial=serial
    )

    asunto = f"Cambio de Tipo de Incapacidad - {serial}"

    from app.main import send_html_email
    send_html_email(email_to, asunto, html)
