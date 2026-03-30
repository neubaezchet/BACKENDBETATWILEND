# -*- coding: utf-8 -*-
"""
Servicio de Notificaciones — Orquestador Principal
Reemplaza completamente el workflow de N8N
Flujo: Webhook → Procesar Datos → Email SMTP + WhatsApp WAHA → Cola resiliente

Versión: 1.0 — 29/03/2026
Compatible 100% con interfaz anterior (enviar_a_n8n → enviar_notificacion)
"""

import re
import logging
from typing import Optional, List, Dict, Tuple
from datetime import datetime
from html2text import html2text as html_to_text_converter

from app.email_service import enviar_notificacion, verificar_salud_email
from app.n8n_notifier import generar_mensaje_whatsapp  # Templates WhatsApp

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════════════
# PROCESAMIENTO DE DATOS — Lógica del nodo "Procesar Datos" de N8N
# ════════════════════════════════════════════════════════════════════════════════════

def procesar_datos_notificacion(
    email: str,
    subject: str,
    html_content: str,
    cc_email: Optional[str] = None,
    correo_bd: Optional[str] = None,
    whatsapp: Optional[str] = None,
    whatsapp_message: Optional[str] = None,
    serial: Optional[str] = None,
    tipo_notificacion: Optional[str] = None,
    drive_link: Optional[str] = None
) -> Dict:
    """
    Procesa datos brutos de la notificación
    Limpia, valida y formatea para envío
    
    Retorna:
        {
            'email': str,
            'cc_emails': List[str],
            'subject': str,
            'html_content': str,
            'whatsapp_numbers': List[str],
            'whatsapp_text': str,
            'send_email': bool,
            'send_whatsapp': bool,
            'serial': str,
            'tipo_notificacion': str,
            'timestamp': str
        }
    """
    
    logger.info(
        f"🔍 PROCESANDO DATOS DE NOTIFICACIÓN\n"
        f"   Email TO: {email}\n"
        f"   CC Empresa: {cc_email or 'N/A'}\n"
        f"   CC BD: {correo_bd or 'N/A'}\n"
        f"   WhatsApp: {whatsapp or 'N/A'}\n"
        f"   Serial: {serial or 'N/A'}"
    )
    
    # ─────────────────────────────────────────────────────────────────────
    # 1. PROCESAR EMAILS CC
    # ─────────────────────────────────────────────────────────────────────
    cc_emails = _procesar_emails_cc(email, cc_email, correo_bd)
    
    # ─────────────────────────────────────────────────────────────────────
    # 2. PROCESAR TELÉFONOS WHATSAPP
    # ─────────────────────────────────────────────────────────────────────
    whatsapp_numbers = _procesar_telefonos_whatsapp(whatsapp)
    
    # ─────────────────────────────────────────────────────────────────────
    # 3. PROCESAR TEXTO WHATSAPP
    # ─────────────────────────────────────────────────────────────────────
    whatsapp_text = _procesar_texto_whatsapp(
        whatsapp_message, html_content, serial
    )
    
    # ─────────────────────────────────────────────────────────────────────
    # 4. ARMADOS RESULTADO
    # ─────────────────────────────────────────────────────────────────────
    resultado = {
        'email': email,
        'cc_emails': cc_emails,
        'subject': subject,
        'html_content': html_content,
        'whatsapp_numbers': whatsapp_numbers,
        'whatsapp_text': whatsapp_text,
        'send_email': bool(email and email.strip()),
        'send_whatsapp': bool(whatsapp_numbers),
        'serial': serial or 'AUTO',
        'tipo_notificacion': tipo_notificacion or 'general',
        'drive_link': drive_link,
        'timestamp': datetime.now().isoformat()
    }
    
    logger.info(
        f"\n✅ DATOS PROCESADOS:\n"
        f"   Email TO: {email}\n"
        f"   CC: {resultado['cc_emails']}\n"
        f"   WhatsApp #: {resultado['whatsapp_numbers']}\n"
        f"   Send email: {resultado['send_email']}\n"
        f"   Send WhatsApp: {resultado['send_whatsapp']}\n"
        f"   Timestamp: {resultado['timestamp']}"
    )
    
    return resultado


def _procesar_emails_cc(
    email_principal: str,
    cc_email: Optional[str] = None,
    correo_bd: Optional[str] = None
) -> List[str]:
    """
    Extrae y limpia lista de CCs
    - Valida formato
    - Elimina duplicados (case-insensitive)
    - Elimina email principal si está en CC
    """
    cc_list = []
    
    # Agregar correo_bd (primer CC)
    if correo_bd and correo_bd.strip():
        if correo_bd.lower().strip() != email_principal.lower().strip():
            cc_list.append(correo_bd.strip())
    
    # Agregar cc_email (puede ser múltiples separados por coma)
    if cc_email and cc_email.strip():
        for ce in cc_email.split(','):
            ce = ce.strip()
            if ce and '@' in ce and '.' in ce.split('@')[1]:
                # Validación básica
                if ce.lower() not in [c.lower() for c in cc_list]:
                    if ce.lower() != email_principal.lower():
                        cc_list.append(ce)
    
    # Eliminar duplicados (case-insensitive)
    cc_unique = []
    seen = set()
    for cc in cc_list:
        lower = cc.lower()
        if lower not in seen:
            cc_unique.append(cc)
            seen.add(lower)
    
    logger.debug(f"   📧 CC limpiados: {cc_unique}")
    return cc_unique


def _procesar_telefonos_whatsapp(whatsapp_str: Optional[str]) -> List[str]:
    """
    Formatea números WhatsApp a estándar internacional (57XXXXXXXXXX)
    Soporta:
    - "3001234567" (solo dígitos, asume Colombia)
    - "573001234567" (con país)
    - "+573001234567" (con +)
    - "300,1234567" (múltiples separados por coma)
    """
    if not whatsapp_str or not str(whatsapp_str).strip():
        return []
    
    numeros = []
    for num in str(whatsapp_str).split(','):
        num = num.strip().replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        
        # Quitar + si existe
        if num.startswith('+'):
            num = num[1:]
        
        # Limpiar solo dígitos
        num = re.sub(r'[^0-9]', '', num)
        
        # Formatear:
        if num.startswith('57') and len(num) == 12:
            # Ya está en formato correcto (57 + 10 dígitos)
            numeros.append(num)
        elif len(num) == 10 and (num.startswith('3') or num.startswith('2')):
            # Número colombiano sin código de país
            numeros.append('57' + num)
        elif len(num) == 12:
            # Podría ser 57 + 10
            numeros.append(num)
        else:
            # No se puede determinar el formato
            logger.warning(f"   ⚠️ Número WhatsApp inválido: {whatsapp_str} → {num} (descartado)")
    
    logger.debug(f"   📱 WhatsApp números procesados: {numeros}")
    return numeros


def _procesar_texto_whatsapp(
    whatsapp_message: Optional[str],
    html_content: str,
    serial: Optional[str] = None
) -> str:
    """
    Convierte HTML a texto limpio para WhatsApp
    Si no hay mensaje, extrae del HTML
    """
    
    # Si hay mensaje específico, usarlo como base
    if whatsapp_message and str(whatsapp_message).strip():
        mensaje = str(whatsapp_message).strip()
    else:
        # Convertir HTML a texto
        try:
            # Quitar CSS y JS
            clean_html = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.IGNORECASE | re.DOTALL)
            clean_html = re.sub(r'<script[^>]*>.*?</script>', '', clean_html, flags=re.IGNORECASE | re.DOTALL)
            
            # Conversiones específicas
            clean_html = re.sub(r'<br\s*/?>', '\n', clean_html, flags=re.IGNORECASE)
            clean_html = re.sub(r'</p>', '\n\n', clean_html, flags=re.IGNORECASE)
            clean_html = re.sub(r'</div>', '\n', clean_html, flags=re.IGNORECASE)
            clean_html = re.sub(r'<li>', '• ', clean_html, flags=re.IGNORECASE)
            
            # Quitar tags HTML
            clean_html = re.sub(r'<[^>]+>', '', clean_html)
            
            # Descodificar entities
            clean_html = clean_html.replace('&nbsp;', ' ')
            clean_html = clean_html.replace('&amp;', '&')
            clean_html = clean_html.replace('&lt;', '<')
            clean_html = clean_html.replace('&gt;', '>')
            clean_html = clean_html.replace('&quot;', '"')
            clean_html = clean_html.replace('&#39;', "'")
            
            # Limpiar múltiples saltos de línea
            clean_html = re.sub(r'\n{3,}', '\n\n', clean_html)
            clean_html = re.sub(r'[ \t]+', ' ', clean_html)
            
            mensaje = clean_html.strip()
        except Exception as e:
            logger.warning(f"   ⚠️ Error convirtiendo HTML a texto: {e}")
            mensaje = f"Se ha procesado tu {serial or 'solicitud'}. Revisa tu email para más detalles."
    
    # Limitar a 1500 caracteres (WhatsApp permite ~4096, pero mobile es más conservador)
    if len(mensaje) > 1500:
        mensaje = mensaje[:1497] + '...'
    
    # Agregar header con serial si existe
    if serial and serial != 'AUTO':
        mensaje = f"📋 *Incapacidad {serial}*\n\n{mensaje}"
    
    # Footer
    mensaje += f"\n\n_Mensaje automático - IncaNeurobaeza_"
    
    logger.debug(f"   💬 WhatsApp mensaje procesado (primeros 100 car): {mensaje[:100]}...")
    return mensaje


# ════════════════════════════════════════════════════════════════════════════════════
# ORQUESTADOR PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════════════

def enviar_notificacion_completa(
    tipo_notificacion: str,
    email: str,
    serial: str,
    subject: str,
    html_content: str,
    cc_email: Optional[str] = None,
    correo_bd: Optional[str] = None,
    whatsapp: Optional[str] = None,
    whatsapp_message: Optional[str] = None,
    adjuntos_base64: List[Dict] = [],
    drive_link: Optional[str] = None
) -> Dict:
    """
    Orquestador principal - Reemplaza completamente el workflow de N8N
    
    Flujo:
    1. Procesa datos (limpia, valida, formatea)
    2. Envía email via SMTP
    3. Envía WhatsApp via WAHA
    4. Retorna response consolidado
    5. Si falla algo, entra a cola resiliente
    
    Returns:
        {
            'status': 'success' | 'partial' | 'failed',
            'serial': str,
            'timestamp': str,
            'channels': {
                'email': {...},
                'whatsapp': {...}
            },
            'error': str o None
        }
    """
    
    logger.info(f"\n{'='*80}\n"
                f"📤 ENVIAR NOTIFICACIÓN COMPLETA (Backend Nativo — Sin N8N)\n"
                f"{'='*80}\n")
    
    # ─────────────────────────────────────────────────────────────────────
    # 1. PROCESAR DATOS
    # ─────────────────────────────────────────────────────────────────────
    try:
        datos_procesados = procesar_datos_notificacion(
            email=email,
            subject=subject,
            html_content=html_content,
            cc_email=cc_email,
            correo_bd=correo_bd,
            whatsapp=whatsapp,
            whatsapp_message=whatsapp_message,
            serial=serial,
            tipo_notificacion=tipo_notificacion,
            drive_link=drive_link
        )
    except Exception as e:
        logger.error(f"❌ Error procesando datos: {e}")
        return {
            'status': 'failed',
            'serial': serial,
            'timestamp': datetime.now().isoformat(),
            'channels': {},
            'error': f"Error en procesamiento: {str(e)}"
        }
    
    # ─────────────────────────────────────────────────────────────────────
    # 2. ENVIAR EMAIL
    # ─────────────────────────────────────────────────────────────────────
    response = {
        'status': 'failed',
        'serial': serial,
        'timestamp': datetime.now().isoformat(),
        'channels': {}
    }
    
    email_enviado = False
    if datos_procesados['send_email']:
        try:
            email_enviado = enviar_notificacion(
                tipo_notificacion=tipo_notificacion,
                email=datos_procesados['email'],
                serial=serial,
                subject=datos_procesados['subject'],
                html_content=datos_procesados['html_content'],
                cc_email=','.join(datos_procesados['cc_emails']) if datos_procesados['cc_emails'] else None,
                correo_bd=correo_bd,
                whatsapp=None,  # Lo enviamos luego
                adjuntos_base64=adjuntos_base64
            )
            
            response['channels']['email'] = {
                'enviado': email_enviado,
                'to': datos_procesados['email'],
                'cc': datos_procesados['cc_emails']
            }
        except Exception as e:
            logger.error(f"❌ Error enviando email: {e}")
            response['channels']['email'] = {
                'enviado': False,
                'error': str(e),
                'to': datos_procesados['email']
            }
    
    # ─────────────────────────────────────────────────────────────────────
    # 3. ENVIAR WHATSAPP
    # ─────────────────────────────────────────────────────────────────────
    wa_enviado = False
    if datos_procesados['send_whatsapp']:
        try:
            # Llamar a email_service para enviar WhatsApp
            from app.email_service import _enviar_whatsapp
            
            wa_enviados = 0
            wa_error = None
            
            for numero in datos_procesados['whatsapp_numbers']:
                try:
                    if _enviar_whatsapp(numero, datos_procesados['whatsapp_text']):
                        wa_enviados += 1
                except Exception as e:
                    logger.warning(f"   ⚠️ Error en número {numero}: {e}")
                    wa_error = str(e)
            
            wa_enviado = wa_enviados > 0
            response['channels']['whatsapp'] = {
                'enviado': wa_enviado,
                'total_numeros': len(datos_procesados['whatsapp_numbers']),
                'exitosos': wa_enviados,
                'numeros': datos_procesados['whatsapp_numbers']
            }
            
            if wa_error:
                response['channels']['whatsapp']['error'] = wa_error
        
        except Exception as e:
            logger.error(f"❌ Error enviando WhatsApp: {e}")
            response['channels']['whatsapp'] = {
                'enviado': False,
                'error': str(e),
                'numeros': datos_procesados['whatsapp_numbers']
            }
    
    # ─────────────────────────────────────────────────────────────────────
    # 4. DETERMINAR STATUS GENERAL
    # ─────────────────────────────────────────────────────────────────────
    if email_enviado or wa_enviado:
        response['status'] = 'success' if (email_enviado and wa_enviado or not datos_procesados['send_email'] or not datos_procesados['send_whatsapp']) else 'partial'
    else:
        response['status'] = 'failed'
    
    logger.info(f"\n✅ RESPUESTA FINAL:\n"
                f"   Status: {response['status']}\n"
                f"   Email:  {response['channels'].get('email', {}).get('enviado', 'N/A')}\n"
                f"   WhatsApp: {response['channels'].get('whatsapp', {}).get('enviado', 'N/A')}\n"
                f"{'='*80}\n")
    
    return response


# ════════════════════════════════════════════════════════════════════════════════════
# COMPATIBILIDAD
# ════════════════════════════════════════════════════════════════════════════════════

# Alias para reemplazar directamente enviar_a_n8n en todo el código
def enviar_a_n8n(*args, **kwargs) -> bool:
    """Compatibilidad: llama a enviar_notificacion_completa"""
    resultado = enviar_notificacion_completa(*args, **kwargs)
    return resultado['status'] in ['success', 'partial']
