# -*- coding: utf-8 -*-
"""
Templates de Email - Automatico por Incapacidades 2026
Compatible: Gmail, Outlook, Yahoo, Apple Mail, Thunderbird
Reglas: Table-based 600px, inline CSS, HTML entities, bgcolor, MSO conditionals
"""

import re


def _parsear_serial(serial):
    """
    Extrae cedula y fechas del serial.
    Serial: '1024541919 03 02 2026 17 02 2026'
    Retorna: (cedula, 'del 03/02/2026 al 17/02/2026') o (serial, '')
    """
    if not serial:
        return (serial or '', '')
    parts = serial.strip().split()
    if len(parts) == 7:
        cedula = parts[0]
        f1 = f"{parts[1]}/{parts[2]}/{parts[3]}"
        f2 = f"{parts[4]}/{parts[5]}/{parts[6]}"
        return (cedula, f"del {f1} al {f2}")
    return (serial, '')


# =====================================================================
# PLANTILLA BASE - SIMPLE, CORTA, ANTI-SPAM
# =====================================================================

def _base_template(titulo, color_header, contenido_body, serial="", telefono="", email_contacto="", link_drive=""):
    """Plantilla base table-based 600px - simple y limpia"""

    cedula, fechas = _parsear_serial(serial)
    subtitulo = f"Incapacidad {fechas}" if fechas else ""

    drive_html = ""
    if link_drive:
        drive_html = f"""
                <tr>
                    <td align="center" style="padding:12px 24px;">
                        <table cellpadding="0" cellspacing="0" border="0"><tr>
                            <td bgcolor="#F3F2F1" style="background-color:#F3F2F1; padding:10px 24px;">
                                <a href="{link_drive}" style="color:#0078D4; text-decoration:underline; font-family:Arial,sans-serif; font-size:13px;">&#128196; Ver documentos en Drive</a>
                            </td>
                        </tr></table>
                    </td>
                </tr>"""

    # Botones de contacto (llamada + WhatsApp)
    contacto_btns = ""
    if telefono:
        tel_limpio = re.sub(r'[^0-9+]', '', telefono)
        wa_link = f"https://wa.me/57{tel_limpio}" if not tel_limpio.startswith('+') else f"https://wa.me/{tel_limpio.replace('+','')}"
        tel_link = f"tel:+57{tel_limpio}" if not tel_limpio.startswith('+') else f"tel:{tel_limpio}"
        contacto_btns = f"""
                <tr>
                    <td style="padding:14px 24px;">
                        <table width="100%" cellpadding="0" cellspacing="0" border="0">
                            <tr>
                                <td align="center" style="padding-bottom:8px;">
                                    <span style="font-size:13px; color:#605E5C; font-family:Arial,sans-serif;">Si tienes dudas comunicate con nosotros:</span>
                                </td>
                            </tr>
                            <tr>
                                <td align="center">
                                    <table cellpadding="0" cellspacing="0" border="0"><tr>
                                        <!--[if mso]>
                                        <td bgcolor="#25D366" style="background-color:#25D366; padding:10px 20px;">
                                            <a href="{wa_link}" style="color:#FFFFFF; text-decoration:none; font-size:13px; font-weight:700; font-family:Arial,sans-serif;">&#9742; WhatsApp</a>
                                        </td>
                                        <td width="10">&nbsp;</td>
                                        <td bgcolor="#0078D4" style="background-color:#0078D4; padding:10px 20px;">
                                            <a href="{tel_link}" style="color:#FFFFFF; text-decoration:none; font-size:13px; font-weight:700; font-family:Arial,sans-serif;">&#128222; Llamar</a>
                                        </td>
                                        <![endif]-->
                                        <!--[if !mso]>-->
                                        <td bgcolor="#25D366" style="background-color:#25D366; padding:10px 20px; border-radius:4px;">
                                            <a href="{wa_link}" style="display:block; color:#FFFFFF; text-decoration:none; font-size:13px; font-weight:700; font-family:Arial,sans-serif;">&#9742; WhatsApp</a>
                                        </td>
                                        <td width="10">&nbsp;</td>
                                        <td bgcolor="#0078D4" style="background-color:#0078D4; padding:10px 20px; border-radius:4px;">
                                            <a href="{tel_link}" style="display:block; color:#FFFFFF; text-decoration:none; font-size:13px; font-weight:700; font-family:Arial,sans-serif;">&#128222; Llamar</a>
                                        </td>
                                        <!--<![endif]-->
                                    </tr></table>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>"""

    subtitulo_html = ""
    if subtitulo:
        subtitulo_html = f"""
                                <tr>
                                    <td align="center" style="color:#FFFFFF; font-size:13px; font-family:Arial,sans-serif; padding-top:4px; opacity:0.9;">
                                        {subtitulo}
                                    </td>
                                </tr>"""

    return f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
    <title>{titulo}</title>
    <!--[if mso]>
    <style type="text/css">
        body, table, td, p, a, span {{font-family: Arial, sans-serif !important;}}
        table {{border-collapse: collapse;}}
    </style>
    <![endif]-->
</head>
<body style="margin:0; padding:0; background-color:#F3F2F1; font-family:Arial,sans-serif; -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%;">
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#F3F2F1;">
        <tr>
            <td align="center" style="padding:16px 8px;">
                <!--[if mso]><table width="600" cellpadding="0" cellspacing="0" border="0" align="center"><tr><td><![endif]-->
                <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:600px; background-color:#FFFFFF;">

                    <!-- HEADER -->
                    <tr>
                        <td bgcolor="{color_header}" style="background-color:{color_header}; padding:24px 20px; text-align:center;">
                            <table width="100%" cellpadding="0" cellspacing="0" border="0">
                                <tr>
                                    <td align="center" style="color:#FFFFFF; font-size:18px; font-weight:700; font-family:Arial,sans-serif; line-height:1.3;">
                                        {titulo}
                                    </td>
                                </tr>
{subtitulo_html}
                            </table>
                        </td>
                    </tr>
                    <tr><td height="3" bgcolor="{color_header}" style="background-color:{color_header}; font-size:1px; line-height:1px; opacity:0.5;">&nbsp;</td></tr>

                    <!-- BODY -->
                    <tr>
                        <td style="padding:20px 24px; font-family:Arial,sans-serif; font-size:14px; color:#323130; line-height:1.6;">
                            <table width="100%" cellpadding="0" cellspacing="0" border="0">
{contenido_body}
                            </table>
                        </td>
                    </tr>
{drive_html}
{contacto_btns}

                    <!-- FOOTER -->
                    <tr>
                        <td bgcolor="#F3F2F1" style="background-color:#F3F2F1; padding:16px 24px; text-align:center; border-top:1px solid #EDEBE9;">
                            <span style="color:#A19F9D; font-size:11px; font-family:Arial,sans-serif;">Automatico por Incapacidades</span>
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
# BLOQUES REUTILIZABLES
# =====================================================================

def _bloque_mensaje(bgcolor, border_color, texto_titulo, texto_cuerpo):
    """Bloque con borde izquierdo"""
    titulo_html = ""
    if texto_titulo:
        titulo_html = f'<strong style="font-size:14px; color:#323130; font-family:Arial,sans-serif; display:block; padding-bottom:4px;">{texto_titulo}</strong>'
    return f"""
                                <tr>
                                    <td style="padding:6px 0;">
                                        <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
                                            <td width="4" bgcolor="{border_color}" style="background-color:{border_color};">&nbsp;</td>
                                            <td bgcolor="{bgcolor}" style="background-color:{bgcolor}; padding:14px 16px;">
                                                {titulo_html}
                                                <span style="font-size:13px; color:#323130; font-family:Arial,sans-serif; line-height:1.5;">{texto_cuerpo}</span>
                                            </td>
                                        </tr></table>
                                    </td>
                                </tr>
"""


def _bloque_alerta(bgcolor, texto, border_color="#EDEBE9"):
    """Alerta centrada"""
    return f"""
                                <tr>
                                    <td style="padding:6px 0;">
                                        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top:1px solid {border_color}; border-bottom:1px solid {border_color};">
                                            <tr>
                                                <td bgcolor="{bgcolor}" style="background-color:{bgcolor}; padding:10px 16px; text-align:center;">
                                                    <span style="font-size:13px; color:#323130; font-family:Arial,sans-serif; line-height:1.4;">{texto}</span>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
"""


def _bloque_boton(url, texto, color_bg):
    """Boton CTA table-based"""
    return f"""
                                <tr>
                                    <td align="center" style="padding:14px 0;">
                                        <table cellpadding="0" cellspacing="0" border="0"><tr>
                                            <!--[if mso]>
                                            <td bgcolor="{color_bg}" style="background-color:{color_bg}; padding:12px 30px;">
                                                <a href="{url}" style="color:#FFFFFF; text-decoration:none; font-size:14px; font-weight:700; font-family:Arial,sans-serif;">{texto}</a>
                                            </td>
                                            <![endif]-->
                                            <!--[if !mso]>-->
                                            <td bgcolor="{color_bg}" style="background-color:{color_bg}; padding:12px 30px; border-radius:4px;">
                                                <a href="{url}" style="display:block; color:#FFFFFF; text-decoration:none; font-size:14px; font-weight:700; font-family:Arial,sans-serif;">{texto}</a>
                                            </td>
                                            <!--<![endif]-->
                                        </tr></table>
                                    </td>
                                </tr>
"""


def _bloque_tabla_info(filas):
    """Tabla key-value"""
    rows = ""
    for i, (label, valor) in enumerate(filas):
        bg = "#FAF9F8" if i % 2 == 0 else "#FFFFFF"
        rows += f"""
                                            <tr>
                                                <td bgcolor="{bg}" style="background-color:{bg}; padding:8px 12px; color:#605E5C; font-size:12px; font-family:Arial,sans-serif; width:120px; vertical-align:top; border-bottom:1px solid #EDEBE9;">{label}</td>
                                                <td bgcolor="{bg}" style="background-color:{bg}; padding:8px 12px; color:#323130; font-size:12px; font-family:Arial,sans-serif; font-weight:600; border-bottom:1px solid #EDEBE9;">{valor}</td>
                                            </tr>"""
    return f"""
                                <tr>
                                    <td style="padding:6px 0;">
                                        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #EDEBE9;">
                                            <tr><td><table width="100%" cellpadding="0" cellspacing="0" border="0">
{rows}
                                            </table></td></tr>
                                        </table>
                                    </td>
                                </tr>
"""


def _bloque_lista(titulo, items, bgcolor="#EFF6FC", color_titulo="#004578"):
    """Lista con bullets"""
    items_html = ""
    for item in items:
        items_html += f"""
                                                <tr>
                                                    <td width="20" style="vertical-align:top; padding:4px 0; font-size:13px; color:#605E5C;">&#8226;</td>
                                                    <td style="padding:4px 0; font-size:13px; color:#323130; font-family:Arial,sans-serif; line-height:1.4;">{item}</td>
                                                </tr>"""
    return f"""
                                <tr>
                                    <td style="padding:6px 0;">
                                        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #D2E3FC;">
                                            <tr>
                                                <td bgcolor="{bgcolor}" style="background-color:{bgcolor}; padding:14px 16px;">
                                                    <strong style="font-size:13px; color:{color_titulo}; font-family:Arial,sans-serif; display:block; padding-bottom:6px;">{titulo}</strong>
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
    """Checklist visual OK/FAIL"""
    rows = ""
    for item_name, item_desc in items_fail:
        rows += f"""
                                            <tr>
                                                <td bgcolor="#FDE8E8" style="background-color:#FDE8E8; padding:10px 12px; border-bottom:2px solid #FFFFFF;">
                                                    <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
                                                        <td width="24" style="vertical-align:top; color:#DC2626; font-size:14px; font-family:Arial,sans-serif;">&#10060;</td>
                                                        <td style="font-family:Arial,sans-serif;">
                                                            <strong style="color:#991B1B; font-size:13px;">{item_name}</strong><br/>
                                                            <span style="color:#B91C1C; font-size:11px;">{item_desc}</span>
                                                        </td>
                                                    </tr></table>
                                                </td>
                                            </tr>"""
    for item_name, item_desc in items_ok:
        rows += f"""
                                            <tr>
                                                <td bgcolor="#F0FDF4" style="background-color:#F0FDF4; padding:10px 12px; border-bottom:2px solid #FFFFFF;">
                                                    <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
                                                        <td width="24" style="vertical-align:top; color:#16A34A; font-size:14px; font-family:Arial,sans-serif;">&#9989;</td>
                                                        <td style="font-family:Arial,sans-serif;">
                                                            <strong style="color:#166534; font-size:13px;">{item_name}</strong><br/>
                                                            <span style="color:#15803D; font-size:11px;">{item_desc}</span>
                                                        </td>
                                                    </tr></table>
                                                </td>
                                            </tr>"""
    return f"""
                                <tr>
                                    <td style="padding:8px 0;">
                                        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #E5E7EB;">
                                            <tr>
                                                <td bgcolor="#F9FAFB" style="background-color:#F9FAFB; padding:10px 14px; border-bottom:2px solid #E5E7EB;">
                                                    <strong style="font-size:13px; color:#374151; font-family:Arial,sans-serif;">&#128203; {titulo}</strong>
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
    """Convierte checks en explicacion"""
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
    """Lista de soportes requeridos segun tipo"""
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
        f"Soportes requeridos ({info['origen']}):",
        info['docs'],
        bgcolor="#EFF6FC",
        color_titulo="#004578"
    )


def generar_checklist_requisitos(tipo_incapacidad, checks_faltantes, tipo_email):
    """Checklist visual"""
    requisitos_completos = {
        'Maternidad': [
            ('incapacidad', 'Incapacidad o licencia de maternidad', 'Documento oficial emitido por EPS'),
            ('epicrisis', 'Epicrisis o resumen de atencion', 'Completo sin recortes'),
            ('nacido_vivo', 'Certificado de nacido vivo', 'Original legible'),
            ('registro_civil', 'Registro civil del bebe', 'Completo y legible'),
        ],
        'Paternidad': [
            ('incapacidad', 'Incapacidad de paternidad', 'Documento oficial emitido por EPS'),
            ('epicrisis', 'Epicrisis de la madre', 'Documento completo'),
            ('cedula_padre', 'Cedula del padre', 'Ambas caras legibles'),
            ('nacido_vivo', 'Certificado de nacido vivo', 'Original legible'),
            ('registro_civil', 'Registro civil del bebe', 'Completo y legible'),
            ('licencia_maternidad', 'Licencia maternidad de la madre', 'Si la madre trabaja'),
        ],
        'Accidente de Transito': [
            ('incapacidad', 'Incapacidad medica', 'Documento oficial emitido por EPS'),
            ('epicrisis', 'Epicrisis o resumen de atencion', 'Completo sin recortes'),
            ('furips', 'FURIPS', 'Completo y legible'),
            ('soat', 'SOAT del vehiculo', 'Si fue identificado'),
        ],
        'Enfermedad General': [
            ('incapacidad', 'Incapacidad medica', 'Documento oficial emitido por EPS'),
            ('epicrisis', 'Epicrisis o resumen de atencion', 'Para incapacidades de 3+ dias'),
        ],
        'Enfermedad Laboral': [
            ('incapacidad', 'Incapacidad medica', 'Documento oficial emitido por ARL'),
            ('epicrisis', 'Epicrisis o resumen de atencion', 'Para incapacidades de 3+ dias'),
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
    """Contenido principal segun tipo - CORTO Y DIRECTO"""

    cedula, fechas = _parsear_serial(serial)

    if tipo_email == 'confirmacion':
        archivos_html = ""
        if archivos_nombres:
            for archivo in archivos_nombres:
                archivos_html += f"""
                                                <tr>
                                                    <td bgcolor="#EFF6FC" style="background-color:#EFF6FC; padding:8px 12px; border-bottom:2px solid #FFFFFF; border-left:3px solid #0078D4;">
                                                        <span style="font-size:13px; color:#004578; font-family:Arial,sans-serif;">&#128196; {archivo}</span>
                                                    </td>
                                                </tr>"""

        resultado = _bloque_mensaje(
            "#EFF6FC", "#0078D4",
            "&#9989; Documentacion recibida",
            f"Tu incapacidad <strong>{fechas}</strong> esta siendo revisada para validar que cumpla con los requisitos de <strong>{tipo_incapacidad}</strong>."
            if fechas else
            f"Tu incapacidad esta siendo revisada para validar que cumpla con los requisitos de <strong>{tipo_incapacidad}</strong>."
        )
        if archivos_html:
            resultado += f"""
                                <tr>
                                    <td style="padding:6px 0;">
                                        <table width="100%" cellpadding="0" cellspacing="0" border="0">
                                            <tr><td style="padding-bottom:4px;"><strong style="font-size:13px; color:#323130; font-family:Arial,sans-serif;">Documentos recibidos:</strong></td></tr>
                                            <tr><td><table width="100%" cellpadding="0" cellspacing="0" border="0">
{archivos_html}
                                            </table></td></tr>
                                        </table>
                                    </td>
                                </tr>
"""
        return resultado

    elif tipo_email == 'incompleta':
        explicacion = generar_explicacion_checks(checks)
        fecha_texto = f" <strong>{fechas}</strong>" if fechas else ""
        soportes_html = generar_lista_soportes_requeridos(tipo_incapacidad)
        return (
            _bloque_mensaje(
                "#FDE8E8", "#DC2626",
                "&#10060; Documentacion Incompleta",
                f"Tu incapacidad{fecha_texto} fue devuelta.<br/><br/><strong>Motivo:</strong><br/>{explicacion}"
            )
            + soportes_html
            + _bloque_alerta(
                "#EFF6FC",
                "Enviar en <strong>PDF escaneado</strong>, completo y legible.",
                "#D2E3FC"
            )
        )

    elif tipo_email == 'ilegible':
        explicacion = generar_explicacion_checks(checks)
        fecha_texto = f" <strong>{fechas}</strong>" if fechas else ""
        return (
            _bloque_mensaje(
                "#FFF4CE", "#D97706",
                "&#9888; Documento Ilegible",
                f"Tu incapacidad{fecha_texto} fue devuelta.<br/><br/><strong>Motivo:</strong><br/>{explicacion}"
            )
            + _bloque_alerta(
                "#EFF6FC",
                "Reenviar en <strong>PDF escaneado</strong>, completo, sin recortes y con buena resolucion.",
                "#D2E3FC"
            )
        )

    elif tipo_email == 'eps':
        fecha_texto = f" {fechas}" if fechas else ""
        return _bloque_mensaje(
            "#FFF4CE", "#CA8A04",
            "&#128203; Transcripcion en EPS requerida",
            f"Tu incapacidad{fecha_texto} requiere <strong>transcripcion en tu EPS</strong>. "
            "Dirigete a tu EPS con tu documento de identidad y solicita la transcripcion. "
            "Una vez tengas el documento transcrito, subelo nuevamente al sistema."
        )

    elif tipo_email == 'completa':
        fecha_texto = f" {fechas}" if fechas else ""
        return _bloque_mensaje(
            "#D1FAE5", "#16A34A",
            "&#9989; Incapacidad validada",
            f"Tu incapacidad{fecha_texto} ha sido subida al sistema exitosamente. "
            "Nos comunicaremos contigo si se requiere algun paso adicional."
        )

    elif tipo_email == 'tthh':
        return _bloque_mensaje(
            "#FDE8E8", "#DC2626",
            "&#9888; Revision por Presunto Fraude",
            "La siguiente incapacidad presenta inconsistencias que requieren "
            "<strong>validacion adicional</strong> con la colaboradora."
        )

    elif tipo_email == 'falsa':
        return _bloque_mensaje(
            "#EFF6FC", "#0078D4",
            "&#9989; Documentacion recibida",
            "Se procedera a realizar la revision correspondiente."
        )

    elif tipo_email == 'recordatorio':
        fecha_texto = f" <strong>{fechas}</strong>" if fechas else ""
        explicacion = generar_explicacion_checks(checks) if checks else ""
        motivo_html = f"<br/><br/><strong>Motivo original:</strong><br/>{explicacion}" if explicacion else ""
        return _bloque_mensaje(
            "#FFF4CE", "#D97706",
            "&#9200; Recordatorio - Documentacion pendiente",
            f"Tu incapacidad{fecha_texto} de tipo <strong>{tipo_incapacidad}</strong> aun tiene documentacion pendiente.{motivo_html}"
        )

    return ""


def generar_seccion_ilegibilidad():
    """Seccion formato PDF"""
    return _bloque_alerta(
        "#EFF6FC",
        "Enviar documentos en <strong>PDF escaneado</strong>, completos, legibles y sin recortes.",
        "#D2E3FC"
    )


def generar_instrucciones(tipo_email):
    """Instrucciones cortas"""
    return _bloque_lista(
        "Que debes hacer:",
        [
            "Adjunta los soportes en <strong>PDF escaneado</strong>",
            "Verifica que esten <strong>completos y legibles</strong>",
            "Incluye <strong>TODOS</strong> los soportes faltantes"
        ],
        bgcolor="#EFF6FC",
        color_titulo="#004578"
    )


def generar_aviso_wasap():
    """Aviso watshapp - ya no se usa, reemplazado por botones de contacto"""
    return ""


def generar_detalles_caso(serial, nombre, empresa, tipo_incapacidad, telefono, email_contacto):
    """Tabla de detalles (TTHH)"""
    cedula, fechas = _parsear_serial(serial)
    return _bloque_tabla_info([
        ("Cedula:", f'<strong style="color:#DC2626;">{cedula}</strong>'),
        ("Periodo:", fechas or serial),
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
    """Plantilla universal 2026 - corta, directa, anti-spam"""

    cedula, fechas = _parsear_serial(serial)

    configs = {
        'confirmacion': {
            'color': '#0078D4',
            'titulo': '&#9989; Incapacidad Recibida',
            'mostrar_requisitos': False,
            'mostrar_boton': False,
            'mostrar_plazo': False,
        },
        'incompleta': {
            'color': '#DC2626',
            'titulo': '&#10060; Documentacion Incompleta',
            'mostrar_requisitos': True,
            'mostrar_boton': True,
            'mostrar_plazo': False,
        },
        'ilegible': {
            'color': '#D97706',
            'titulo': '&#9888; Documento Ilegible',
            'mostrar_requisitos': False,
            'mostrar_boton': True,
            'mostrar_plazo': False,
        },
        'eps': {
            'color': '#CA8A04',
            'titulo': '&#128203; Transcripcion en EPS',
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
            'mostrar_requisitos': False,
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
            'titulo': '&#9200; Recordatorio',
            'mostrar_requisitos': False,
            'mostrar_boton': True,
            'mostrar_plazo': False,
        },
        'alerta_jefe': {
            'color': '#2563EB',
            'titulo': '&#128202; Seguimiento Pendiente',
            'mostrar_requisitos': False,
            'mostrar_boton': False,
            'mostrar_plazo': False,
        },
    }

    config = configs.get(tipo_email, configs['confirmacion'])
    body = ''

    # SALUDO
    if tipo_email == 'tthh':
        body += f"""
                                <tr>
                                    <td style="padding:0 0 10px 0;">
                                        <p style="margin:0; font-size:14px; color:#323130; font-family:Arial,sans-serif;">Estimado equipo de <strong>Talento Humano</strong>,</p>
                                    </td>
                                </tr>
"""
    else:
        body += f"""
                                <tr>
                                    <td style="padding:0 0 10px 0;">
                                        <p style="margin:0; font-size:14px; color:#323130; font-family:Arial,sans-serif;">Hola <strong style="color:#0078D4;">{nombre}</strong>,</p>
                                    </td>
                                </tr>
"""

    # MENSAJE PRINCIPAL
    if contenido_ia:
        body += _bloque_mensaje("#FAF9F8", config['color'], "", contenido_ia)
    else:
        body += generar_mensaje_segun_tipo(tipo_email, checks_seleccionados, tipo_incapacidad, serial, quinzena, archivos_nombres)

    # DETALLES (TTHH)
    if tipo_email == 'tthh':
        body += generar_detalles_caso(serial, nombre, empresa, tipo_incapacidad, telefono, email)

    # CHECKLIST REQUISITOS
    if config['mostrar_requisitos']:
        body += generar_checklist_requisitos(tipo_incapacidad, checks_seleccionados, tipo_email)

    # SECCION JEFE
    if tipo_email == 'alerta_jefe' and empleado_nombre:
        body += _bloque_tabla_info([
            ("Colaborador/a:", empleado_nombre),
            ("Cedula:", cedula),
            ("Periodo:", fechas or serial),
            ("Empresa:", empresa),
            ("Contacto:", f"{telefono} - {email}"),
        ])

    # BOTON REENVIO
    if config['mostrar_boton']:
        body += _bloque_boton(
            "https://repogemin.vercel.app/",
            "&#128260; Subir Documentos Corregidos",
            config['color']
        )

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
# WRAPPER + TEMPLATES LEGACY
# =====================================================================

def get_email_template_universal(tipo_email, nombre, serial, empresa, tipo_incapacidad,
                                 telefono, email, link_drive, checks_seleccionados=[],
                                 archivos_nombres=None, quinzena=None, contenido_ia=None,
                                 empleado_nombre=None):
    """Wrapper principal"""
    return get_email_template_universal_con_ia(
        tipo_email, nombre, serial, empresa, tipo_incapacidad,
        telefono, email, link_drive, checks_seleccionados,
        archivos_nombres, quinzena, contenido_ia, empleado_nombre
    )


def get_confirmation_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive, archivos_nombres=None):
    return get_email_template_universal(
        tipo_email='confirmacion', nombre=nombre, serial=serial,
        empresa=empresa, tipo_incapacidad=tipo_incapacidad,
        telefono=telefono, email=email, link_drive=link_drive,
        archivos_nombres=archivos_nombres
    )


def get_alert_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive, checks_seleccionados=None):
    return get_email_template_universal(
        tipo_email='incompleta', nombre=nombre, serial=serial,
        empresa=empresa, tipo_incapacidad=tipo_incapacidad,
        telefono=telefono, email=email, link_drive=link_drive,
        checks_seleccionados=checks_seleccionados or []
    )


def get_ilegible_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive, checks_seleccionados=None):
    return get_email_template_universal(
        tipo_email='ilegible', nombre=nombre, serial=serial,
        empresa=empresa, tipo_incapacidad=tipo_incapacidad,
        telefono=telefono, email=email, link_drive=link_drive,
        checks_seleccionados=checks_seleccionados or []
    )


def get_eps_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive):
    return get_email_template_universal(
        tipo_email='eps', nombre=nombre, serial=serial,
        empresa=empresa, tipo_incapacidad=tipo_incapacidad,
        telefono=telefono, email=email, link_drive=link_drive
    )


def get_completa_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive):
    return get_email_template_universal(
        tipo_email='completa', nombre=nombre, serial=serial,
        empresa=empresa, tipo_incapacidad=tipo_incapacidad,
        telefono=telefono, email=email, link_drive=link_drive
    )


def get_tthh_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive, checks_seleccionados=None):
    return get_email_template_universal(
        tipo_email='tthh', nombre=nombre, serial=serial,
        empresa=empresa, tipo_incapacidad=tipo_incapacidad,
        telefono=telefono, email=email, link_drive=link_drive,
        checks_seleccionados=checks_seleccionados or []
    )


def get_falsa_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive):
    return get_email_template_universal(
        tipo_email='falsa', nombre=nombre, serial=serial,
        empresa=empresa, tipo_incapacidad=tipo_incapacidad,
        telefono=telefono, email=email, link_drive=link_drive
    )


# =====================================================================
# EMAIL CAMBIO DE TIPO
# =====================================================================

def enviar_email_cambio_tipo(email_to, nombre, serial, tipo_anterior, tipo_nuevo, docs_requeridos):
    """Email cambio de tipo de incapacidad"""
    tipos_nombres = {
        'maternity': 'Maternidad',
        'paternity': 'Paternidad',
        'general': 'Enfermedad General',
        'traffic': 'Accidente de Transito',
        'labor': 'Accidente Laboral'
    }
    tipo_ant_nombre = tipos_nombres.get(tipo_anterior, tipo_anterior)
    tipo_nuevo_nombre = tipos_nombres.get(tipo_nuevo, tipo_nuevo)
    cedula, fechas = _parsear_serial(serial)

    body = f"""
                                <tr>
                                    <td style="padding:0 0 10px 0;">
                                        <p style="margin:0; font-size:14px; color:#323130; font-family:Arial,sans-serif;">Hola <strong style="color:#0078D4;">{nombre}</strong>,</p>
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding:0 0 8px 0;">
                                        <p style="margin:0; font-size:13px; color:#323130; font-family:Arial,sans-serif;">Se actualizo el tipo de tu incapacidad{' ' + fechas if fechas else ''}:</p>
                                    </td>
                                </tr>
"""
    body += _bloque_tabla_info([
        ("Tipo anterior:", tipo_ant_nombre),
        ("Nuevo tipo:", f"<strong>{tipo_nuevo_nombre}</strong>"),
    ])
    body += _bloque_lista(
        "Documentos requeridos:",
        docs_requeridos,
        bgcolor="#EFF6FC",
        color_titulo="#004578"
    )
    body += _bloque_boton(
        "https://repogemin.vercel.app/",
        "&#128260; Subir Documentos",
        "#D97706"
    )

    html = _base_template(
        titulo="&#128260; Cambio de Tipo de Incapacidad",
        color_header="#D97706",
        contenido_body=body,
        serial=serial
    )

    asunto = f"Cambio de Tipo - Incapacidad {fechas if fechas else serial}"

    from app.main import send_html_email
    send_html_email(email_to, asunto, html)
