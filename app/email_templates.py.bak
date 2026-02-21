"""
Sistema de Templates de Email Unificado con Checklists DinÃ¡micos
IncaBaeza - 2024
"""

# ==================== PLANTILLA BASE ÃšNICA ====================

def get_email_template_universal(
    tipo_email,  # 'confirmacion', 'incompleta', 'ilegible', 'eps', 'tthh', 'completa', 'falsa'
    nombre,
    serial,
    empresa,
    tipo_incapacidad,
    telefono,
    email,
    link_drive,
    checks_seleccionados=[],
    archivos_nombres=None,
    quinzena=None
):
    """
    PLANTILLA UNIVERSAL - Solo cambia contenido segÃºn tipo
    """
    
    # ========== CONFIGURACIÃ“N SEGÃšN TIPO ==========
    configs = {
        'confirmacion': {
            'color_principal': '#667eea',
            'color_secundario': '#764ba2',
            'icono': 'âœ…',
            'titulo': 'Recibido Confirmado',
            'mostrar_requisitos': True,
            'mostrar_boton_reenvio': False,
            'mostrar_plazo': False,
        },
        'incompleta': {
            'color_principal': '#ef4444',
            'color_secundario': '#dc2626',
            'icono': 'âŒ',
            'titulo': 'DocumentaciÃ³n Incompleta',
            'mostrar_requisitos': True,
            'mostrar_boton_reenvio': True,
            'mostrar_plazo': True,
        },
        'ilegible': {
            'color_principal': '#f59e0b',
            'color_secundario': '#d97706',
            'icono': 'âš ï¸',
            'titulo': 'Documento Ilegible',
            'mostrar_requisitos': True,
            'mostrar_boton_reenvio': True,
            'mostrar_plazo': True,
        },
        'eps': {
            'color_principal': '#ca8a04',
            'color_secundario': '#a16207',
            'icono': 'ðŸ“‹',
            'titulo': 'TranscripciÃ³n en EPS Requerida',
            'mostrar_requisitos': False,
            'mostrar_boton_reenvio': True,
            'mostrar_plazo': False,
        },
        'completa': {
            'color_principal': '#16a34a',
            'color_secundario': '#15803d',
            'icono': 'âœ…',
            'titulo': 'Incapacidad Validada',
            'mostrar_requisitos': False,
            'mostrar_boton_reenvio': False,
            'mostrar_plazo': False,
        },
        'tthh': {
            'color_principal': '#dc2626',
            'color_secundario': '#991b1b',
            'icono': 'ðŸš¨',
            'titulo': 'ALERTA - Presunto Fraude',
            'mostrar_requisitos': True,
            'mostrar_boton_reenvio': False,
            'mostrar_plazo': False,
        },
        'falsa': {
            'color_principal': '#991b1b',
            'color_secundario': '#7f1d1d',
            'icono': 'ðŸš«',
            'titulo': 'Recibido Confirmado',
            'mostrar_requisitos': False,
            'mostrar_boton_reenvio': False,
            'mostrar_plazo': False,
        },
    }
    
    config = configs[tipo_email]
    
    # ========== GENERAR MENSAJE PRINCIPAL DINÃMICO ==========
    mensaje_principal = generar_mensaje_segun_tipo(tipo_email, checks_seleccionados, tipo_incapacidad, serial, quinzena, archivos_nombres)
    
    # ========== GENERAR LISTA DE REQUISITOS ==========
    requisitos_html = ''
    if config['mostrar_requisitos']:
        requisitos_html = generar_checklist_requisitos(tipo_incapacidad, checks_seleccionados, tipo_email)
    
    # ========== GENERAR SECCIONES ADICIONALES ==========
    seccion_ilegibilidad = generar_seccion_ilegibilidad() if 'ilegible' in tipo_email or any('ilegible' in c or 'recortada' in c or 'borrosa' in c for c in checks_seleccionados) else ''
    
    seccion_instrucciones = generar_instrucciones(tipo_email) if tipo_email in ['incompleta', 'ilegible'] else ''
    
    boton_reenvio = f'''
        <div style="text-align: center; margin: 30px 0;">
            <a href="https://repogemin.vercel.app/" 
               style="display: inline-block; background: linear-gradient(135deg, {config['color_principal']} 0%, {config['color_secundario']} 100%); 
                      color: white; padding: 16px 40px; text-decoration: none; border-radius: 25px; 
                      font-weight: bold; font-size: 16px; box-shadow: 0 4px 8px rgba(0,0,0,0.3);">
                ðŸ“„ Subir Documentos Corregidos
            </a>
        </div>
    ''' if config['mostrar_boton_reenvio'] else ''
    
    plazo_html = '''
        <div style="background: #fff3cd; border: 2px solid #ffc107; padding: 15px; border-radius: 8px; margin: 25px 0; text-align: center;">
            <p style="margin: 0; color: #856404; font-weight: bold;">
                â° Por favor, envÃ­a la documentaciÃ³n corregida lo antes posible
            </p>
        </div>
    ''' if config['mostrar_plazo'] else ''
    
    # ========== PLANTILLA HTML COMPLETA ==========
    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>{config['titulo']} - {serial}</title>
    </head>
    <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; margin: 0; padding: 20px;">
        <div style="max-width: 650px; margin: 0 auto; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 8px rgba(0,0,0,0.15);">
            
            <!-- Header -->
            <div style="background: linear-gradient(135deg, {config['color_principal']} 0%, {config['color_secundario']} 100%); color: white; padding: 30px; text-align: center;">
                <h1 style="margin: 0; font-size: 26px;">{config['icono']} {config['titulo']}</h1>
                <p style="margin: 5px 0 0 0; font-style: italic;">IncaNeurobaeza</p>
            </div>
            
            <!-- Content -->
            <div style="padding: 30px;">
                <p style="font-size: 16px; color: #333;">
                    {'Estimado equipo de <strong>Talento Humano</strong>,' if tipo_email == 'tthh' else f'Hola <strong>{nombre}</strong>,'}
                </p>
                
                <!-- Mensaje Principal DinÃ¡mico -->
                {mensaje_principal}
                
                <!-- Detalles del Caso (Solo para TTHH) -->
                {generar_detalles_caso(serial, nombre, empresa, tipo_incapacidad, telefono, email) if tipo_email == 'tthh' else ''}
                
                <!-- Checklist de Requisitos -->
                {requisitos_html}
                
                <!-- SecciÃ³n de Ilegibilidad -->
                {seccion_ilegibilidad}
                
                <!-- Instrucciones -->
                {seccion_instrucciones}
                
                <!-- BotÃ³n de ReenvÃ­o -->
                {boton_reenvio}
                
                <!-- Plazo -->
                {plazo_html}
                
                <!-- Link a Drive -->
                <div style="text-align: center; margin: 20px 0;">
                    <a href="{link_drive}" style="color: #3b82f6; text-decoration: underline; font-size: 14px;">
                        ðŸ“„ Ver documentos en Drive
                    </a>
                </div>
                
                <!-- Aviso WhatsApp (Solo confirmaciÃ³n e incompleta) -->
                {generar_aviso_wasap() if tipo_email in ['confirmacion', 'incompleta', 'ilegible'] else ''}
                
                <!-- Contacto -->
                <div style="background: #f3f4f6; padding: 15px; border-radius: 8px; margin: 20px 0;">
                    <p style="margin: 0; color: #4b5563; font-size: 13px; text-align: center;">
                        ðŸ“ž <strong>{telefono}</strong> &nbsp;|&nbsp; ðŸ“§ <strong>{email}</strong>
                    </p>
                </div>
            </div>
            
            <!-- Footer -->
            <div style="background: #f8f9fa; padding: 20px; text-align: center; border-top: 1px solid #e9ecef;">
                <strong style="color: #667eea; font-size: 16px;">IncaNeurobaeza</strong>
                <div style="color: #6c757d; font-style: italic; margin-top: 5px; font-size: 14px;">
                    "Trabajando para ayudarte"
                </div>
            </div>
        </div>
    </body>
    </html>
    """

# ==================== FUNCIONES MODULARES ====================

def generar_mensaje_segun_tipo(tipo_email, checks, tipo_incapacidad, serial, quinzena=None, archivos_nombres=None):
    """Genera el mensaje principal segÃºn el tipo de email y checks"""
    
    if tipo_email == 'confirmacion':
        archivos_list = "<br>".join([f"â€¢ {archivo}" for archivo in (archivos_nombres or [])])
        return f'''
        <div style="background: #e3f2fd; border-left: 4px solid #2196f3; padding: 20px; margin: 20px 0; border-radius: 0 8px 8px 0;">
            <p style="margin: 0; color: #1565c0; font-weight: bold; font-size: 15px;">
                âœ… Confirmo recibido de la documentaciÃ³n
            </p>
            <p style="margin: 10px 0 0 0; color: #1976d2; line-height: 1.6;">
                Se procederÃ¡ a realizar la revisiÃ³n para validar que cumpla con los requisitos establecidos 
                para <strong>{tipo_incapacidad}</strong>.
            </p>
        </div>
        
        <div style="margin: 20px 0;">
            <h4 style="color: #333; margin-bottom: 10px;">ðŸ”Ž Documentos recibidos:</h4>
            <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; font-size: 14px;">
                {archivos_list if archivos_list else '<em>No especificado</em>'}
            </div>
        </div>
        '''
    
    elif tipo_email == 'incompleta':
        explicacion = generar_explicacion_checks(checks)
        # Obtener soportes requeridos según tipo
        soportes_html = generar_lista_soportes_requeridos(tipo_incapacidad)
        return f'''
        <div style="background: #fee2e2; border-left: 4px solid #ef4444; padding: 20px; margin: 20px 0; border-radius: 0 8px 8px 0;">
            <p style="margin: 0; color: #991b1b; font-weight: bold; font-size: 15px;">
                ❌ Incapacidad {serial} - Documentación Incompleta
            </p>
            <p style="margin: 10px 0 0 0; color: #b91c1c; line-height: 1.6; font-size: 15px;">
                <strong>Motivo:</strong> {explicacion}
            </p>
        </div>
        
        {soportes_html}
        
        <div style="background: #e0f2fe; border: 2px solid #0284c7; padding: 15px; border-radius: 8px; margin: 20px 0;">
            <p style="margin: 0; color: #0c4a6e; font-size: 14px;">
                <strong>📄 Formato:</strong> Enviar en <strong>PDF escaneado</strong>. Asegúrese de que el documento esté completo y legible.
            </p>
        </div>
        
        <div style="background: #fef3c7; border: 2px solid #f59e0b; padding: 15px; border-radius: 8px; margin: 20px 0;">
            <p style="margin: 0; color: #92400e; font-size: 14px;">
                Si no cuenta con algún soporte, <strong>diríjase al punto de atención más cercano de su EPS y solicítelo</strong>.
            </p>
        </div>
        
        <div style="background: #f3f4f6; padding: 15px; border-radius: 8px; margin: 20px 0; text-align: center;">
            <p style="margin: 0; color: #374151; font-size: 14px;">
                Comuníquese si tiene alguna duda.
            </p>
        </div>
        '''
    
    elif tipo_email == 'ilegible':
        explicacion = generar_explicacion_checks(checks)
        return f'''
        <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 20px; margin: 20px 0; border-radius: 0 8px 8px 0;">
            <p style="margin: 0; color: #92400e; font-weight: bold; font-size: 15px;">
                ⚠️ Incapacidad {serial} - Documento Ilegible
            </p>
            <p style="margin: 10px 0 0 0; color: #78350f; line-height: 1.6; font-size: 15px;">
                <strong>Motivo:</strong> {explicacion}
            </p>
        </div>
        
        <div style="background: #e0f2fe; border: 2px solid #0284c7; padding: 15px; border-radius: 8px; margin: 20px 0;">
            <p style="margin: 0; color: #0c4a6e; font-size: 14px;">
                <strong>📄 Formato:</strong> Enviar en <strong>PDF escaneado</strong>. Asegúrese de que el documento esté completo, sin recortes y con buena resolución.
            </p>
        </div>
        
        <div style="background: #fef3c7; border: 2px solid #f59e0b; padding: 15px; border-radius: 8px; margin: 20px 0;">
            <p style="margin: 0; color: #92400e; font-size: 14px;">
                Si no cuenta con algún soporte, <strong>diríjase al punto de atención más cercano de su EPS y solicítelo</strong>.
            </p>
        </div>
        
        <div style="background: #f3f4f6; padding: 15px; border-radius: 8px; margin: 20px 0; text-align: center;">
            <p style="margin: 0; color: #374151; font-size: 14px;">
                Comuníquese si tiene alguna duda.
            </p>
        </div>
        '''
    
    elif tipo_email == 'eps':
        return f'''
        <div style="background: #fef3c7; border-left: 4px solid #ca8a04; padding: 20px; margin: 20px 0; border-radius: 0 8px 8px 0;">
            <p style="margin: 0; color: #92400e; font-weight: bold; font-size: 15px;">
                ðŸ“‹ TranscripciÃ³n en EPS requerida
            </p>
            <p style="margin: 10px 0 0 0; color: #78350f; line-height: 1.6;">
                Tu incapacidad requiere <strong>transcripciÃ³n fÃ­sica en tu EPS</strong>. 
                Por favor, dirÃ­gete a tu EPS con tu documento de identidad y solicita la 
                transcripciÃ³n de esta incapacidad. Una vez tengas el documento transcrito, 
                sÃºbelo nuevamente al sistema.
            </p>
        </div>
        '''
    
    elif tipo_email == 'completa':
        return f'''
        <div style="background: #d1fae5; border: 2px solid #10b981; padding: 20px; margin: 20px 0; border-radius: 8px;">
            <p style="margin: 0; color: #065f46; font-weight: bold; font-size: 15px;">
                âœ… Tu incapacidad ha sido validada exitosamente
            </p>
            <p style="margin: 10px 0 0 0; color: #047857; line-height: 1.6;">
                Tu caso ha sido subido al sistema exitosamente para el proceso de validación. 
                Nos comunicaremos contigo cuando el proceso esté completo.
            </p>
            <div style="text-align: center; margin: 20px 0; font-size: 24px;">
                📌 ➜ 🟢 ➜ ⚪
            </div>
            <p style="margin: 0; text-align: center; color: #059669; font-size: 12px;">
                Recepción → <strong>Validación</strong> → Subida al sistema
            </p>
        </div>
        '''
    
    elif tipo_email == 'tthh':
        return f'''
        <div style="background: #fee2e2; border: 3px solid #ef4444; padding: 25px; margin: 20px 0; border-radius: 8px;">
            <h3 style="margin: 0 0 15px 0; color: #991b1b;">
                âš ï¸ Incapacidad en RevisiÃ³n por Presunto Fraude
            </h3>
            <p style="margin: 0; color: #b91c1c; font-size: 15px; line-height: 1.6;">
                La siguiente incapacidad presenta inconsistencias que requieren 
                <strong>validaciÃ³n adicional</strong> con la colaboradora.
            </p>
        </div>
        '''
    
    elif tipo_email == 'falsa':
        return f'''
        <div style="background: #e3f2fd; border-left: 4px solid #2196f3; padding: 20px; margin: 20px 0; border-radius: 0 8px 8px 0;">
            <p style="margin: 0; color: #1565c0; font-weight: bold; font-size: 15px;">
                âœ… Confirmo recibido de la documentaciÃ³n
            </p>
            <p style="margin: 10px 0 0 0; color: #1976d2; line-height: 1.6;">
                Se procederÃ¡ a realizar la revisiÃ³n correspondiente.
            </p>
        </div>
        '''
    
    return ""

def generar_lista_soportes_requeridos(tipo_incapacidad):
    """Genera lista HTML de soportes requeridos según origen común o laboral"""
    
    soportes = {
        'Enfermedad General': {
            'origen': 'Origen Común',
            'docs': [
                'Incapacidad médica (emitida por la EPS)',
                'Epicrisis o resumen de atención (todas las páginas)'
            ]
        },
        'Enfermedad Laboral': {
            'origen': 'Origen Laboral',
            'docs': [
                'Incapacidad médica (emitida por la ARL)',
                'Epicrisis o resumen de atención (todas las páginas)'
            ]
        },
        'Maternidad': {
            'origen': 'Origen Común',
            'docs': [
                'Licencia de maternidad (emitida por la EPS)',
                'Epicrisis o resumen de atención (todas las páginas)',
                'Certificado de nacido vivo',
                'Registro civil del bebé'
            ]
        },
        'Paternidad': {
            'origen': 'Origen Común',
            'docs': [
                'Incapacidad de paternidad (emitida por la EPS)',
                'Epicrisis o resumen de atención de la madre (todas las páginas)',
                'Cédula del padre (ambas caras)',
                'Certificado de nacido vivo',
                'Registro civil del bebé',
                'Licencia de maternidad de la madre (si trabaja)'
            ]
        },
        'Accidente de Tránsito': {
            'origen': 'Origen Común',
            'docs': [
                'Incapacidad médica (emitida por la EPS)',
                'Epicrisis o resumen de atención (todas las páginas)',
                'FURIPS (Formato Único de Reporte)',
                'SOAT del vehículo (si fue identificado)'
            ]
        }
    }
    
    info = soportes.get(tipo_incapacidad)
    if not info:
        return ''
    
    items_html = ''
    for doc in info['docs']:
        items_html += f'<li style="margin: 6px 0; color: #1e3a8a; font-size: 14px;">{doc}</li>\n'
    
    return f'''
    <div style="background: #dbeafe; border: 2px solid #3b82f6; padding: 20px; border-radius: 8px; margin: 20px 0;">
        <h4 style="margin-top: 0; color: #1e40af; font-size: 15px;">
            📋 Soportes requeridos para incapacidad de {info['origen']}:
        </h4>
        <ol style="line-height: 1.8; margin: 10px 0; padding-left: 20px;">
            {items_html}
        </ol>
    </div>
    '''

def generar_explicacion_checks(checks):
    """Convierte los checks en explicaciÃ³n en lenguaje natural usando las descripciones actualizadas"""
    from app.checks_disponibles import CHECKS_DISPONIBLES
    
    mensajes = []
    for check_key in checks:
        if check_key in CHECKS_DISPONIBLES:
            mensajes.append(CHECKS_DISPONIBLES[check_key]['descripcion'])
    
    if not mensajes:
        return "Se encontrÃ³ incompleta y requiere correcciÃ³n."
    elif len(mensajes) == 1:
        return mensajes[0]
    else:
        # Unir con saltos de lÃ­nea para mejor legibilidad
        return "<br><br>".join([f"â€¢ {msg}" for msg in mensajes])

def generar_checklist_requisitos(tipo_incapacidad, checks_faltantes, tipo_email):
    """Genera la checklist visual de requisitos"""
    
    # Definir requisitos completos por tipo
    requisitos_completos = {
        'Maternidad': [
            ('incapacidad', 'Incapacidad o licencia de maternidad', 'Documento oficial emitido por EPS con todas las pÃ¡ginas'),
            ('epicrisis', 'Epicrisis o resumen de atenciÃ³n', 'Documento completo con todas las pÃ¡ginas, sin recortes'),
            ('nacido_vivo', 'Certificado de nacido vivo', 'Original legible y sin recortes'),
            ('registro_civil', 'Registro civil del bebÃ©', 'Completo y legible'),
        ],
        'Paternidad': [
            ('incapacidad', 'Incapacidad de paternidad', 'Documento oficial emitido por EPS'),
            ('epicrisis', 'Epicrisis o resumen de atenciÃ³n de la madre', 'Documento completo con todas las pÃ¡ginas'),
            ('cedula_padre', 'CÃ©dula del padre', 'Ambas caras legibles'),
            ('nacido_vivo', 'Certificado de nacido vivo', 'Original legible'),
            ('registro_civil', 'Registro civil del bebÃ©', 'Completo y legible'),
            ('licencia_maternidad', 'Licencia de maternidad de la madre (si trabaja)', 'Solo si la madre estÃ¡ activa laboralmente'),
        ],
        'Accidente de TrÃ¡nsito': [
            ('incapacidad', 'Incapacidad mÃ©dica', 'Documento oficial emitido por EPS con todas las pÃ¡ginas'),
            ('epicrisis', 'Epicrisis o resumen de atenciÃ³n', 'Documento completo, sin recortes'),
            ('furips', 'FURIPS (Formato Ãšnico de Reporte)', 'Completo y legible'),
            ('soat', 'SOAT del vehÃ­culo', 'Solo si el vehÃ­culo es identificado (no fantasma)'),
        ],
        'Enfermedad General': [
            ('incapacidad', 'Incapacidad mÃ©dica', 'Documento oficial emitido por EPS con todas las pÃ¡ginas'),
            ('epicrisis', 'Epicrisis o resumen de atenciÃ³n', 'Requerido para incapacidades de 3 o mÃ¡s dÃ­as'),
        ],
        'Enfermedad Laboral': [
            ('incapacidad', 'Incapacidad mÃ©dica', 'Documento oficial emitido por ARL con todas las pÃ¡ginas'),
            ('epicrisis', 'Epicrisis o resumen de atenciÃ³n', 'Requerido para incapacidades de 3 o mÃ¡s dÃ­as'),
        ],
    }
    
    requisitos = requisitos_completos.get(tipo_incapacidad, [])
    if not requisitos:
        return ''
    
    # Determinar el color del borde
    color_borde = '#fecaca' if tipo_email in ['incompleta', 'ilegible'] else '#e0f2fe'
    
    html = f'''
    <div style="background: white; border: 2px solid {color_borde}; padding: 25px; border-radius: 8px; margin: 25px 0;">
        <h3 style="margin-top: 0; color: #374151; border-bottom: 2px solid #d1d5db; padding-bottom: 10px;">
            ðŸ“‹ Requisitos para {tipo_incapacidad}
        </h3>
        <div style="font-size: 14px; line-height: 2;">
    '''
    
    for codigo, nombre, descripcion in requisitos:
        # Verificar si estÃ¡ en la lista de faltantes
        faltante = any(codigo in check for check in checks_faltantes)
        
        if faltante:
            # âŒ FALTANTE
            html += f'''
            <div style="display: flex; align-items: start; margin-bottom: 12px; background: #fee2e2; padding: 12px; border-radius: 6px;">
                <span style="color: #dc2626; font-size: 20px; margin-right: 10px;">âŒ</span>
                <div style="flex: 1;">
                    <strong style="color: #991b1b;">{nombre}</strong>
                    <div style="color: #b91c1c; font-size: 12px; margin-top: 4px;">
                        ({descripcion})
                    </div>
                </div>
            </div>
            '''
        else:
            # âœ… OK
            html += f'''
            <div style="display: flex; align-items: start; margin-bottom: 12px; background: #f0fdf4; padding: 12px; border-radius: 6px; opacity: 0.7;">
                <span style="color: #16a34a; font-size: 20px; margin-right: 10px;">âœ…</span>
                <div style="flex: 1;">
                    <strong style="color: #166534;">{nombre}</strong>
                    <div style="color: #15803d; font-size: 12px; margin-top: 4px;">
                        ({descripcion})
                    </div>
                </div>
            </div>
            '''
    
    html += '</div></div>'
    return html

def generar_seccion_ilegibilidad():
    """Genera indicación de PDF escaneado"""
    return '''
    <div style="background: #e0f2fe; border: 2px solid #0284c7; padding: 20px; border-radius: 8px; margin: 25px 0;">
        <h4 style="margin-top: 0; color: #0c4a6e;">
            📄 Formato de envío:
        </h4>
        <p style="color: #0c4a6e; line-height: 1.8; margin: 10px 0; font-size: 14px;">
            Enviar los documentos en <strong>PDF escaneado</strong>. Asegúrese de que estén completos, legibles y sin recortes.
        </p>
        <p style="color: #92400e; margin: 10px 0; font-size: 14px;">
            Si no cuenta con algún soporte, <strong>diríjase al punto de atención más cercano de su EPS y solicítelo</strong>.
        </p>
    </div>
    '''

def generar_instrucciones(tipo_email):
    """Genera instrucciones claras para corrección"""
    return '''
    <div style="background: #dbeafe; border: 2px solid #3b82f6; padding: 20px; border-radius: 8px; margin: 25px 0;">
        <h4 style="margin-top: 0; color: #1e40af;">📝 Qué debes hacer:</h4>
        <ol style="color: #1e3a8a; line-height: 1.8; margin: 10px 0; padding-left: 20px;">
            <li>Adjunta nuevamente los soportes en <strong>PDF escaneado</strong></li>
            <li>Verifica que los documentos estén <strong>completos y legibles</strong></li>
            <li>Incluye <strong>TODOS</strong> los soportes marcados como faltantes</li>
        </ol>
        <p style="color: #92400e; margin: 15px 0 0 0; font-size: 14px; border-top: 1px solid #93c5fd; padding-top: 12px;">
            Si no cuenta con algún soporte, <strong>diríjase al punto de atención más cercano de su EPS y solicítelo</strong>.
        </p>
    </div>
    <div style="background: #f3f4f6; padding: 15px; border-radius: 8px; margin: 15px 0; text-align: center;">
        <p style="margin: 0; color: #374151; font-size: 14px;">Comuníquese si tiene alguna duda.</p>
    </div>
    '''

def generar_aviso_wasap():
    """Genera aviso de estar pendiente primero por WhatsApp"""
    return '''
    <div style="background: #fff3cd; border: 2px solid #ffc107; padding: 20px; border-radius: 8px; margin: 25px 0;">
        <p style="margin: 0; color: #856404; font-weight: bold; text-align: center; font-size: 15px;">
            ⚠️ IMPORTANTE: Estar pendiente
        </p>
        <p style="margin: 10px 0 0 0; color: #856404; text-align: center;">
            <strong>📱 Primero vía WhatsApp</strong> y luego por <strong>📧 correo electrónico</strong>
        </p>
        <p style="margin: 10px 0 0 0; color: #856404; text-align: center; font-size: 13px;">
            Comuníquese si tiene alguna duda.
        </p>
    </div>
    '''

def generar_detalles_caso(serial, nombre, empresa, tipo_incapacidad, telefono, email):
    """Genera tabla de detalles del caso (para TTHH)"""
    return f'''
    <div style="background: #f8f9fa; border: 2px solid #dee2e6; padding: 20px; border-radius: 8px; margin: 25px 0;">
        <h4 style="margin-top: 0; color: #495057; border-bottom: 2px solid #6c757d; padding-bottom: 10px;">
            ðŸ“‹ InformaciÃ³n del Caso
        </h4>
        <table style="width: 100%; font-size: 14px;">
            <tr>
                <td style="padding: 8px 0; color: #666; font-weight: bold; width: 180px;">Serial:</td>
                <td style="padding: 8px 0; color: #333;"><strong style="color: #dc2626;">{serial}</strong></td>
            </tr>
            <tr>
                <td style="padding: 8px 0; color: #666; font-weight: bold;">Colaboradora:</td>
                <td style="padding: 8px 0; color: #333;">{nombre}</td>
            </tr>
            <tr>
                <td style="padding: 8px 0; color: #666; font-weight: bold;">Empresa:</td>
                <td style="padding: 8px 0; color: #333;">{empresa}</td>
            </tr>
            <tr>
                <td style="padding: 8px 0; color: #666; font-weight: bold;">Tipo:</td>
                <td style="padding: 8px 0; color: #333;">{tipo_incapacidad}</td>
            </tr>
            <tr>
                <td style="padding: 8px 0; color: #666; font-weight: bold;">TelÃ©fono:</td>
                <td style="padding: 8px 0; color: #333;">{telefono}</td>
            </tr>
            <tr>
                <td style="padding: 8px 0; color: #666; font-weight: bold;">Email:</td>
                <td style="padding: 8px 0; color: #333;">{email}</td>
            </tr>
        </table>
    </div>
    '''
def enviar_email_cambio_tipo(email: str, nombre: str, serial: str, tipo_anterior: str, tipo_nuevo: str, docs_requeridos: list):
    """
    EnvÃ­a email informando del cambio de tipo de incapacidad
    """
    # Mapeo de tipos a nombres legibles
    tipos_nombres = {
        'maternity': 'Maternidad',
        'paternity': 'Paternidad',
        'general': 'Enfermedad General',
        'traffic': 'Accidente de TrÃ¡nsito',
        'labor': 'Accidente Laboral'
    }
    
    tipo_ant_nombre = tipos_nombres.get(tipo_anterior, tipo_anterior)
    tipo_nuevo_nombre = tipos_nombres.get(tipo_nuevo, tipo_nuevo)
    
    # Generar lista de documentos
    docs_html = "<ul style='margin: 10px 0; padding-left: 20px;'>"
    for doc in docs_requeridos:
        docs_html += f"<li style='margin: 5px 0;'>{doc}</li>"
    docs_html += "</ul>"
    
    asunto = f"ðŸ”„ Cambio de Tipo de Incapacidad - {serial}"
    
    cuerpo = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 10px;">
            <h2 style="color: #f59e0b;">ðŸ”„ ActualizaciÃ³n de Tipo de Incapacidad</h2>
            
            <p>Hola <strong>{nombre}</strong>,</p>
            
            <p>Hemos actualizado el tipo de tu incapacidad <strong>{serial}</strong>:</p>
            
            <div style="background-color: #fef3c7; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p style="margin: 0;">
                    <strong>Tipo anterior:</strong> {tipo_ant_nombre}<br>
                    <strong>Nuevo tipo:</strong> {tipo_nuevo_nombre}
                </p>
            </div>
            
            <p>Debido a este cambio, los documentos requeridos son:</p>
            
            {docs_html}
            
            <div style="background-color: #dbeafe; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <h3 style="margin-top: 0; color: #1e40af;">ðŸ“ QuÃ© debes hacer:</h3>
                <ol style="margin: 10px 0; padding-left: 20px;">
                    <li style="margin: 5px 0;">Revisa la nueva lista de documentos</li>
                    <li style="margin: 5px 0;">Prepara TODOS los documentos solicitados</li>
                    <li style="margin: 5px 0;">Ingresa al portal con tu cÃ©dula</li>
                    <li style="margin: 5px 0;">Completa la incapacidad subiendo los documentos</li>
                </ol>
            </div>
            
            <p style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 12px;">
                Este es un correo automÃ¡tico del sistema de gestiÃ³n de incapacidades.<br>
                No respondas a este mensaje.
            </p>
        </div>
    </body>
    </html>
    """
    
    # Enviar usando la funciÃ³n existente
    from app.main import send_html_email
    send_html_email(email, asunto, cuerpo)

# ==================== FUNCIONES DE COMPATIBILIDAD (LEGACY) ====================

def get_confirmation_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive, archivos_nombres=None):
    """
    âœ… TEMPLATE ULTRA-COMPATIBLE - Outlook + Gmail + iPhone
    """
    
    # Lista de archivos recibidos
    archivos_html = ""
    if archivos_nombres:
        archivos_html = """
        <table width="100%" cellpadding="0" cellspacing="0" style="margin: 15px 0;">
            <tr><td>
        """
        for archivo in archivos_nombres:
            archivos_html += f"""
                <div style="background: #e0f2fe; padding: 12px; margin: 8px 0; border-radius: 8px; border-left: 4px solid #0369a1;">
                    <span style="font-size: 18px;">&#128196;</span>
                    <span style="color: #0369a1; font-weight: 500; font-size: 14px; margin-left: 8px;">{archivo}</span>
                </div>
            """
        archivos_html += """
            </td></tr>
        </table>
        """
    
    return f"""
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
    <!--[if mso]><style>body, table, td {{font-family: Arial, sans-serif !important;}}</style><![endif]-->
</head>
<body style="margin: 0; padding: 0; background-color: #F3F2F1;">
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #F3F2F1; padding: 20px 0;">
        <tr><td align="center">
            <table width="600" cellpadding="0" cellspacing="0" border="0" style="background-color: #FFFFFF; max-width: 600px;">
                <tr>
                    <td style="background-color: #0078D4; padding: 32px 24px; text-align: center;">
                        <table width="100%" cellpadding="0" cellspacing="0" border="0">
                            <tr><td align="center">
                                <table cellpadding="0" cellspacing="0" border="0" style="margin: 0 auto 16px;">
                                    <tr><td style="width: 56px; height: 56px; background-color: #FFFFFF; border-radius: 28px; text-align: center; line-height: 56px; font-size: 32px;">&#9989;</td></tr>
                                </table>
                            </td></tr>
                            <tr><td align="center" style="color: #FFFFFF; font-size: 24px; font-weight: 600; font-family: 'Segoe UI', Arial, sans-serif;">Incapacidad Recibida</td></tr>
                            <tr><td align="center" style="color: #FFFFFF; font-size: 14px; font-family: 'Segoe UI', Arial, sans-serif; padding-top: 8px;">IncaNeurobaeza</td></tr>
                        </table>
                    </td>
                </tr>
                <tr>
                    <td style="padding: 32px 24px;">
                        <table width="100%" cellpadding="0" cellspacing="0" border="0">
                            <tr><td style="color: #323130; font-size: 16px; font-family: 'Segoe UI', Arial, sans-serif; padding-bottom: 16px;">Hola <strong style="color: #0078D4;">{nombre}</strong></td></tr>
                            <tr><td style="background-color: #EFF6FC; border-left: 4px solid #0078D4; padding: 16px;">
                                <strong style="color: #004578; font-size: 15px;">&#10004; Confirmo recibido</strong><br/><br/>
                                <span style="color: #004578; font-size: 14px;">Se validarÃ¡ que cumpla con los requisitos para <strong>{tipo_incapacidad}</strong>.</span>
                            </td></tr>
                            <tr><td height="24"></td></tr>
                            <tr><td>
                                <table width="100%" cellpadding="12" cellspacing="0" border="0" style="background-color: #FAF9F8;">
                                    <tr><td style="color: #323130; font-size: 15px; font-weight: 600; border-bottom: 1px solid #EDEBE9; padding-bottom: 12px;">InformaciÃ³n del Registro</td></tr>
                                    <tr><td height="8"></td></tr>
                                    <tr><td>
                                        <table width="100%" cellpadding="6" cellspacing="0">
                                            <tr>
                                                <td width="100" style="color: #605E5C; font-size: 13px;">Serial:</td>
                                                <td style="color: #323130; font-weight: 600; font-size: 13px;"><span style="background-color: #FFF4CE; padding: 4px 10px; color: #8A6A00;">{serial}</span></td>
                                            </tr>
                                            <tr>
                                                <td style="color: #605E5C; font-size: 13px;">Empresa:</td>
                                                <td style="color: #323130; font-size: 13px;">{empresa}</td>
                                            </tr>
                                            <tr>
                                                <td style="color: #605E5C; font-size: 13px;">Tipo:</td>
                                                <td style="color: #323130; font-size: 13px;">{tipo_incapacidad}</td>
                                            </tr>
                                        </table>
                                    </td></tr>
                                </table>
                            </td></tr>
                            <tr><td height="24"></td></tr>
                            {f'''
                            <tr><td style="color: #323130; font-size: 15px; font-weight: 600; padding-bottom: 12px;">Documentos Recibidos</td></tr>
                            <tr><td><table width="100%" cellpadding="0" cellspacing="0">{archivos_html}</table></td></tr>
                            <tr><td height="24"></td></tr>
                            ''' if archivos_html else ''}
                            <tr><td align="center" style="padding: 24px 0;">
                                <table cellpadding="0" cellspacing="0"><tr><td style="background-color: #0078D4; border-radius: 4px;">
                                    <a href="{link_drive}" style="display: block; padding: 14px 32px; color: #FFFFFF; text-decoration: none; font-size: 15px; font-weight: 600;">Ver en Drive</a>
                                </td></tr></table>
                            </td></tr>
                            <tr><td style="background-color: #FFF4CE; border: 2px solid #FFB900; padding: 16px; text-align: center;">
                                <strong style="color: #8A6A00; font-size: 14px;">&#9888; IMPORTANTE</strong><br/>
                                <span style="color: #8A6A00; font-size: 13px;">Estar pendiente vÃ­a WhatsApp y correo</span>
                            </td></tr>
                        </table>
                    </td>
                </tr>
                <tr><td style="background-color: #F3F2F1; padding: 24px; text-align: center;">
                    <strong style="color: #0078D4; font-size: 17px;">IncaNeurobaeza</strong><br/>
                    <span style="color: #605E5C; font-size: 13px; font-style: italic;">Trabajando para ayudarte</span>
                </td></tr>
            </table>
        </td></tr>
    </table>
</body>
</html>
    """

def get_alert_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive, checks_seleccionados=None):
    """Wrapper para emails de alerta (incompleta/ilegible)"""
    return get_confirmation_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive, checks_seleccionados)

def get_ilegible_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive, checks_seleccionados=None):
    """Template para documentos ilegibles"""
    return get_confirmation_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive, checks_seleccionados)

def get_eps_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive):
    """Template para casos que requieren transcripciÃ³n en EPS"""
    return get_confirmation_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive)

def get_completa_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive):
    """Template para casos validados completos"""
    return get_confirmation_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive)

def get_tthh_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive, checks_seleccionados=None):
    """Template para alertas a Talento Humano"""
    return get_confirmation_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive, checks_seleccionados)

def get_falsa_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive):
    """Template para confirmaciÃ³n falsa (caso especial)"""
    return get_confirmation_template(nombre, serial, empresa, tipo_incapacidad, telefono, email, link_drive)

def get_email_template_universal_con_ia(
    tipo_email,  # 'confirmacion', 'incompleta', 'ilegible', 'eps', 'tthh', 'completa', 'falsa', 'recordatorio', 'alerta_jefe'
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
    contenido_ia=None,  # âœ… NUEVO: Contenido generado por IA
    empleado_nombre=None  # âœ… NUEVO: Para emails a jefes
):
    """
    PLANTILLA UNIVERSAL CON SOPORTE PARA CONTENIDO IA
    """
    
    configs = {
        'confirmacion': {
            'color_principal': '#667eea',
            'color_secundario': '#764ba2',
            'icono': 'âœ…',
            'titulo': 'Recibido Confirmado',
            'mostrar_requisitos': True,
            'mostrar_boton_reenvio': False,
            'mostrar_plazo': False,
        },
        'incompleta': {
            'color_principal': '#ef4444',
            'color_secundario': '#dc2626',
            'icono': 'âŒ',
            'titulo': 'DocumentaciÃ³n Incompleta',
            'mostrar_requisitos': True,
            'mostrar_boton_reenvio': True,
            'mostrar_plazo': True,
        },
        'ilegible': {
            'color_principal': '#f59e0b',
            'color_secundario': '#d97706',
            'icono': 'âš ï¸',
            'titulo': 'Documento Ilegible',
            'mostrar_requisitos': True,
            'mostrar_boton_reenvio': True,
            'mostrar_plazo': True,
        },
        'tthh': {
            'color_principal': '#dc2626',
            'color_secundario': '#991b1b',
            'icono': 'ðŸš¨',
            'titulo': 'ALERTA - Presunto Fraude',
            'mostrar_requisitos': True,
            'mostrar_boton_reenvio': False,
            'mostrar_plazo': False,
        },
        'recordatorio': {  # âœ… NUEVO
            'color_principal': '#f59e0b',
            'color_secundario': '#d97706',
            'icono': 'â°',
            'titulo': 'Recordatorio - DocumentaciÃ³n Pendiente',
            'mostrar_requisitos': False,
            'mostrar_boton_reenvio': True,
            'mostrar_plazo': True,
        },
        'alerta_jefe': {  # âœ… NUEVO
            'color_principal': '#3b82f6',
            'color_secundario': '#2563eb',
            'icono': 'ðŸ“Š',
            'titulo': 'Seguimiento - Incapacidad Pendiente',
            'mostrar_requisitos': False,
            'mostrar_boton_reenvio': False,
            'mostrar_plazo': False,
        },
        # ... resto de configs existentes
    }
    
    config = configs.get(tipo_email, configs['confirmacion'])
    
    # âœ… GENERAR MENSAJE PRINCIPAL
    if contenido_ia:
        # Si hay contenido generado por IA, usarlo
        mensaje_principal = f'''
        <div style="background: #f8f9fa; border-left: 4px solid {config['color_principal']}; padding: 20px; margin: 20px 0; border-radius: 0 8px 8px 0;">
            <div style="color: #333; line-height: 1.6; white-space: pre-wrap;">
                {contenido_ia}
            </div>
        </div>
        '''
    else:
        # Usar generador estÃ¡tico original
        mensaje_principal = generar_mensaje_segun_tipo(tipo_email, checks_seleccionados, tipo_incapacidad, serial, quinzena, archivos_nombres)
    
    # âœ… GENERAR LISTA DE REQUISITOS
    requisitos_html = ''
    if config['mostrar_requisitos']:
        requisitos_html = generar_checklist_requisitos(tipo_incapacidad, checks_seleccionados, tipo_email)
    
    # âœ… BOTÃ“N DE REENVÃO
    boton_reenvio = ''
    if config['mostrar_boton_reenvio']:
        boton_reenvio = f'''
        <div style="text-align: center; margin: 30px 0;">
            <a href="https://repogemin.vercel.app/" 
               style="display: inline-block; background: linear-gradient(135deg, {config['color_principal']} 0%, {config['color_secundario']} 100%); 
                      color: white; padding: 16px 40px; text-decoration: none; border-radius: 25px; 
                      font-weight: bold; font-size: 16px; box-shadow: 0 4px 8px rgba(0,0,0,0.3);">
                ðŸ“„ Subir Documentos Corregidos
            </a>
        </div>
        '''
    
    # âœ… PLAZO
    plazo_html = ''
    if config['mostrar_plazo']:
        plazo_html = '''
        <div style="background: #fff3cd; border: 2px solid #ffc107; padding: 15px; border-radius: 8px; margin: 25px 0; text-align: center;">
            <p style="margin: 0; color: #856404; font-weight: bold;">
                â° Por favor, envÃ­a la documentaciÃ³n corregida lo antes posible
            </p>
        </div>
        '''
    
    # âœ… SECCIÃ“N ESPECIAL PARA EMAILS A JEFES
    seccion_jefe = ''
    if tipo_email == 'alerta_jefe' and empleado_nombre:
        seccion_jefe = f'''
        <div style="background: #e0f2fe; border: 2px solid #0ea5e9; padding: 20px; border-radius: 8px; margin: 25px 0;">
            <h4 style="margin-top: 0; color: #0369a1;">
                ðŸ‘¤ InformaciÃ³n del Colaborador/a
            </h4>
            <table style="width: 100%; font-size: 14px;">
                <tr>
                    <td style="padding: 8px 0; color: #666; font-weight: bold; width: 150px;">Nombre:</td>
                    <td style="padding: 8px 0; color: #333;">{empleado_nombre}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #666; font-weight: bold;">Serial:</td>
                    <td style="padding: 8px 0; color: #333;"><strong style="color: #dc2626;">{serial}</strong></td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #666; font-weight: bold;">Empresa:</td>
                    <td style="padding: 8px 0; color: #333;">{empresa}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #666; font-weight: bold;">Contacto:</td>
                    <td style="padding: 8px 0; color: #333;">{telefono} â€¢ {email}</td>
                </tr>
            </table>
        </div>
        '''
    
    # âœ… PLANTILLA HTML COMPLETA
    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>{config['titulo']} - {serial}</title>
    </head>
    <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; margin: 0; padding: 20px;">
        <div style="max-width: 650px; margin: 0 auto; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 8px rgba(0,0,0,0.15);">
            
            <!-- Header -->
            <div style="background: linear-gradient(135deg, {config['color_principal']} 0%, {config['color_secundario']} 100%); color: white; padding: 30px; text-align: center;">
                <h1 style="margin: 0; font-size: 26px;">{config['icono']} {config['titulo']}</h1>
                <p style="margin: 5px 0 0 0; font-style: italic;">IncaNeurobaeza</p>
            </div>
            
            <!-- Content -->
            <div style="padding: 30px;">
                <p style="font-size: 16px; color: #333;">
                    {'Estimado/a <strong>' + nombre + '</strong>,' if tipo_email != 'alerta_jefe' else 'Estimado/a <strong>' + nombre + '</strong>,'}
                </p>
                
                <!-- Mensaje Principal (IA o EstÃ¡tico) -->
                {mensaje_principal}
                
                <!-- SecciÃ³n Jefe (solo para alerta_jefe) -->
                {seccion_jefe}
                
                <!-- Checklist de Requisitos -->
                {requisitos_html}
                
                <!-- BotÃ³n de ReenvÃ­o -->
                {boton_reenvio}
                
                <!-- Plazo -->
                {plazo_html}
                
                <!-- Link a Drive -->
                <div style="text-align: center; margin: 20px 0;">
                    <a href="{link_drive}" style="color: #3b82f6; text-decoration: underline; font-size: 14px;">
                        ðŸ“„ Ver documentos en Drive
                    </a>
                </div>
                
                <!-- Contacto -->
                <div style="background: #f3f4f6; padding: 15px; border-radius: 8px; margin: 20px 0;">
                    <p style="margin: 0; color: #4b5563; font-size: 13px; text-align: center;">
                        ðŸ“ž <strong>{telefono}</strong> &nbsp;|&nbsp; ðŸ“§ <strong>{email}</strong>
                    </p>
                </div>
            </div>
            
            <!-- Footer -->
            <div style="background: #f8f9fa; padding: 20px; text-align: center; border-top: 1px solid #e9ecef;">
                <strong style="color: #667eea; font-size: 16px;">IncaNeurobaeza</strong>
                <div style="color: #6c757d; font-style: italic; margin-top: 5px; font-size: 14px;">
                    "Trabajando para ayudarte"
                </div>
            </div>
        </div>
    </body>
    </html>
    """


# âœ… WRAPPER para mantener compatibilidad
def get_email_template_universal(tipo_email, nombre, serial, empresa, tipo_incapacidad, 
                                 telefono, email, link_drive, checks_seleccionados=[], 
                                 archivos_nombres=None, quinzena=None, contenido_ia=None, 
                                 empleado_nombre=None):
    """Wrapper para usar la nueva funciÃ³n con IA"""
    return get_email_template_universal_con_ia(
        tipo_email, nombre, serial, empresa, tipo_incapacidad,
        telefono, email, link_drive, checks_seleccionados,
        archivos_nombres, quinzena, contenido_ia, empleado_nombre
    )
