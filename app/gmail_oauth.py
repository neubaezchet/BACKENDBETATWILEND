"""
Gmail OAuth 2.0 — Autorización y Refresh de Tokens
Maneja la autenticación con Google para envío de emails desde Gmail
"""

import os
import json
import requests
from datetime import datetime, timedelta
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from app.database import SessionLocal, OAuthToken


# Variables de entorno
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:3000/auth/callback")

# Scopes de Gmail
SCOPES = ['https://www.googleapis.com/auth/gmail.send']


def obtener_url_autorizacion() -> str:
    """
    Genera la URL para que el usuario autorice el acceso a Gmail.
    
    Returns:
        str: URL de Google para autorización
    """
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise ValueError("❌ GOOGLE_CLIENT_ID o GOOGLE_CLIENT_SECRET no configurados")
    
    params = {
        'client_id': GOOGLE_CLIENT_ID,
        'redirect_uri': GOOGLE_REDIRECT_URI,
        'response_type': 'code',
        'scope': ' '.join(SCOPES),
        'access_type': 'offline',
        'prompt': 'consent'  # ← Siempre pide permiso, asegura refresh token
    }
    
    auth_url = 'https://accounts.google.com/o/oauth2/v2/auth?' + '&'.join(
        f'{k}={requests.utils.quote(v)}' for k, v in params.items()
    )
    return auth_url


def procesar_codigo_autorizacion(code: str) -> dict:
    """
    Intercambia el código de autorización por tokens (access_token + refresh_token).
    
    Args:
        code: Código recibido del callback de Google
    
    Returns:
        dict: {'access_token', 'refresh_token', 'expires_in'}
    """
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise ValueError("❌ Credenciales de Google no configuradas")
    
    token_url = 'https://oauth2.googleapis.com/token'
    
    payload = {
        'code': code,
        'client_id': GOOGLE_CLIENT_ID,
        'client_secret': GOOGLE_CLIENT_SECRET,
        'redirect_uri': GOOGLE_REDIRECT_URI,
        'grant_type': 'authorization_code'
    }
    
    response = requests.post(token_url, data=payload)
    
    if response.status_code != 200:
        print(f"❌ Error en intercambio de código: {response.text}")
        raise ValueError(f"Error en autorización: {response.text}")
    
    data = response.json()
    
    # Guardar en BD
    db = SessionLocal()
    token_bd = db.query(OAuthToken).filter(OAuthToken.servicio == 'gmail').first()
    
    if not token_bd:
        token_bd = OAuthToken(servicio='gmail')
    
    token_bd.access_token = data.get('access_token')
    token_bd.refresh_token = data.get('refresh_token')
    token_bd.expires_at = datetime.utcnow() + timedelta(seconds=data.get('expires_in', 3600))
    token_bd.autorizado_en = datetime.utcnow()
    
    db.add(token_bd)
    db.commit()
    db.close()
    
    print(f"✅ Token de Gmail guardado en BD")
    return data


def obtener_access_token() -> str:
    """
    Obtiene el access token actual, refrescando si es necesario.
    
    Returns:
        str: Access token válido
    """
    db = SessionLocal()
    token_bd = db.query(OAuthToken).filter(OAuthToken.servicio == 'gmail').first()
    db.close()
    
    if not token_bd:
        raise ValueError("❌ No hay tokens OAuth guardados. Autoriza primero en /auth/authorize")
    
    # ✅ Si el token ha expirado, refrescarlo
    if datetime.utcnow() >= token_bd.expires_at:
        print(f"🔄 Refrescando token de Gmail...")
        token_bd = refrescar_token(token_bd.refresh_token)
    
    return token_bd.access_token


def refrescar_token(refresh_token: str) -> 'OAuthToken':
    """
    Refresca el access token usando el refresh token.
    
    Args:
        refresh_token: Refresh token guardado
    
    Returns:
        OAuthToken: Objeto con nuevo access token
    """
    token_url = 'https://oauth2.googleapis.com/token'
    
    payload = {
        'client_id': GOOGLE_CLIENT_ID,
        'client_secret': GOOGLE_CLIENT_SECRET,
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token'
    }
    
    response = requests.post(token_url, data=payload)
    
    if response.status_code != 200:
        print(f"❌ Error refrescando token: {response.text}")
        raise ValueError("No se pudo refrescar el token de Gmail")
    
    data = response.json()
    
    # Actualizar en BD
    db = SessionLocal()
    token_bd = db.query(OAuthToken).filter(OAuthToken.servicio == 'gmail').first()
    
    if token_bd:
        token_bd.access_token = data.get('access_token')
        token_bd.expires_at = datetime.utcnow() + timedelta(seconds=data.get('expires_in', 3600))
        db.add(token_bd)
        db.commit()
    
    db.close()
    
    print(f"✅ Token de Gmail refrescado")
    return token_bd


def esta_autorizado() -> bool:
    """
    Verifica si ya hay un token OAuth válido guardado.
    
    Returns:
        bool: True si está autorizado
    """
    db = SessionLocal()
    token_bd = db.query(OAuthToken).filter(OAuthToken.servicio == 'gmail').first()
    db.close()
    
    return token_bd is not None and token_bd.refresh_token is not None
