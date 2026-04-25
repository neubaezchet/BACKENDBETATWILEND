#!/usr/bin/env python3
"""
Prueba de Configuración WhatsApp Business API
Verifica si las variables de entorno están correctas y el token es válido.
"""

import os
import requests
import json
from datetime import datetime

print("\n" + "="*90)
print("🧪 DIAGNÓSTICO WHATSAPP BUSINESS API")
print("="*90 + "\n")

# ✅ PASO 1: Verificar variables de entorno
print("1️⃣ VERIFICANDO VARIABLES DE ENTORNO:")
print("-" * 90)

WHATSAPP_BUSINESS_API_TOKEN = os.environ.get("WHATSAPP_BUSINESS_API_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")

print(f"✓ WHATSAPP_BUSINESS_API_TOKEN: {'✅ EXISTE' if WHATSAPP_BUSINESS_API_TOKEN else '❌ FALTA'}")
if WHATSAPP_BUSINESS_API_TOKEN:
    # Mostrar primeros y últimos caracteres del token (sin revelar todo)
    token_display = WHATSAPP_BUSINESS_API_TOKEN[:15] + "..." + WHATSAPP_BUSINESS_API_TOKEN[-5:] if len(WHATSAPP_BUSINESS_API_TOKEN) > 20 else "***"
    print(f"  Valor: {token_display}")
    print(f"  Longitud: {len(WHATSAPP_BUSINESS_API_TOKEN)} caracteres")

print(f"✓ WHATSAPP_PHONE_NUMBER_ID: {'✅ EXISTE' if WHATSAPP_PHONE_NUMBER_ID else '❌ FALTA'}")
if WHATSAPP_PHONE_NUMBER_ID:
    print(f"  Valor: {WHATSAPP_PHONE_NUMBER_ID}")

print()

# ✅ PASO 2: Validar formato del token
print("2️⃣ VALIDANDO FORMATO DEL TOKEN:")
print("-" * 90)

if not WHATSAPP_BUSINESS_API_TOKEN:
    print("❌ Token no está configurado - IMPOSIBLE CONTINUAR\n")
    exit(1)

if WHATSAPP_BUSINESS_API_TOKEN.startswith("EAAL"):
    print("✅ Token comienza con 'EAAL...' (formato correcto para token permanente)")
elif WHATSAPP_BUSINESS_API_TOKEN.startswith("EAA"):
    print("⚠️ Token comienza con 'EAA...' (posible token temporal)")
else:
    print("❌ Token NO comienza con 'EAAL' o 'EAA' - formato incorrecto")

# Revisar espacios en blanco
if WHATSAPP_BUSINESS_API_TOKEN != WHATSAPP_BUSINESS_API_TOKEN.strip():
    print("❌ Token tiene espacios en blanco al inicio/final - PROBLEMA")
else:
    print("✅ Token no tiene espacios en blanco")

print()

# ✅ PASO 3: Probar conexión a la API
print("3️⃣ PROBANDO CONEXIÓN A META GRAPH API:")
print("-" * 90)

if not WHATSAPP_PHONE_NUMBER_ID:
    print("❌ Phone Number ID no está configurado - IMPOSIBLE CONTINUAR\n")
    exit(1)

# Construir URL según documentación Meta
WHATSAPP_API_VERSION = "v19.0"
WHATSAPP_API_BASE_URL = f"https://graph.instagram.com/{WHATSAPP_API_VERSION}"
url_test = f"{WHATSAPP_API_BASE_URL}/{WHATSAPP_PHONE_NUMBER_ID}"

print(f"URL a probar: {url_test}")
print()

headers = {
    "Authorization": f"Bearer {WHATSAPP_BUSINESS_API_TOKEN}",
    "Content-Type": "application/json"
}

# Hacer request GET para verificar autenticación
print("📡 Enviando GET a /about para verificar autenticación...")
response = requests.get(url_test + "/about", headers=headers, timeout=10)

print(f"Status Code: {response.status_code}")
print()

if response.status_code == 200:
    print("✅ AUTENTICACIÓN EXITOSA")
    print()
    data = response.json()
    print("📋 Información del Phone Number:")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print()
elif response.status_code == 401:
    print("❌ AUTENTICACIÓN FALLIDA - Error 401")
    print()
    try:
        error_data = response.json()
        print(f"Error: {error_data.get('error', {}).get('message', 'Unknown')}")
    except:
        print(f"Response: {response.text[:200]}")
    print()
    print("🔧 POSIBLES SOLUCIONES:")
    print("  1. Token es temporal (expira en 1 hora) - Necesita generar token permanente")
    print("  2. Token es del tipo incorrecto - Debe ser desde la app 'incapacidades patprimo'")
    print("  3. Token tiene espacios o caracteres corruptos")
    print()
elif response.status_code == 400:
    print("❌ ERROR 400 - Solicitud inválida")
    print()
    try:
        error_data = response.json()
        print(f"Error: {error_data.get('error', {}).get('message', 'Unknown')}")
    except:
        print(f"Response: {response.text[:200]}")
    print()
    print("🔧 VERIFICAR:")
    print(f"  - Phone Number ID: {WHATSAPP_PHONE_NUMBER_ID} (correcto: 1065658909966623)")
    print()
else:
    print(f"❌ ERROR {response.status_code}")
    print()
    print(f"Response: {response.text[:300]}")
    print()

# ✅ PASO 4: Probar envío de mensaje (si autenticación OK)
print()
print("4️⃣ PROBANDO ENVÍO DE MENSAJE DE PRUEBA:")
print("-" * 90)

if response.status_code == 200:
    # Número de teléfono de prueba (USA)
    test_number = "14155552671"  # Número de prueba de Meta
    
    payload = {
        "messaging_product": "whatsapp",
        "to": test_number,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": "Prueba de configuración - IncaNeurobaeza"
        }
    }
    
    print(f"Enviando mensaje a número de prueba: +{test_number}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    print()
    
    response_msg = requests.post(
        f"{WHATSAPP_API_BASE_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages",
        json=payload,
        headers=headers,
        timeout=15
    )
    
    print(f"Status Code: {response_msg.status_code}")
    
    if response_msg.status_code in [200, 201, 202]:
        print("✅ MENSAJE ENVIADO EXITOSAMENTE")
        data_msg = response_msg.json()
        print(f"Message ID: {data_msg.get('messages', [{}])[0].get('id', 'N/A')}")
    else:
        print(f"❌ ERROR en envío: {response_msg.status_code}")
        try:
            error_data = response_msg.json()
            print(f"Error: {json.dumps(error_data, indent=2)}")
        except:
            print(f"Response: {response_msg.text[:300]}")
    print()
else:
    print("⏭️ Saltando prueba de mensaje (autenticación fallida)")
    print()

# ✅ PASO 5: Resumen
print()
print("="*90)
print("📊 RESUMEN")
print("="*90)
print()

issues = []

if not WHATSAPP_BUSINESS_API_TOKEN:
    issues.append("❌ WHATSAPP_BUSINESS_API_TOKEN no está configurado")
if not WHATSAPP_PHONE_NUMBER_ID:
    issues.append("❌ WHATSAPP_PHONE_NUMBER_ID no está configurado")

if issues:
    print("PROBLEMAS ENCONTRADOS:")
    for issue in issues:
        print(f"  {issue}")
    print()
    print("✅ SOLUCIÓN INMEDIATA:")
    print("  1. Ir a: https://developers.facebook.com/")
    print("  2. Seleccionar app: 'incapacidades patprimo'")
    print("  3. Ir a Tools → API Explorer")
    print("  4. Seleccionar: GET /{WHATSAPP_PHONE_NUMBER_ID}/about")
    print("  5. Copiar el Access Token que aparece")
    print("  6. Configurar en Railway:")
    print("     - WHATSAPP_BUSINESS_API_TOKEN = [token copiado]")
    print("     - WHATSAPP_PHONE_NUMBER_ID = 1065658909966623")
    print()
else:
    if response.status_code == 200:
        print("✅ CONFIGURACIÓN CORRECTA - Todo OK")
    elif response.status_code == 401:
        print("❌ AUTENTICACIÓN FALLIDA")
        print()
        print("✅ SOLUCIONES POSIBLES:")
        print("  A) Token temporal (expira en 1 hora):")
        print("     - Generar token PERMANENTE desde Meta Business Suite")
        print("     - Seleccionar 'Never Expires' en lugar de '1 hour'")
        print()
        print("  B) Token del tipo incorrecto:")
        print("     - Asegurarse de generar token desde 'incapacidades patprimo'")
        print("     - NO desde 'Neurobaeza'")
        print()
        print("  C) Token corrupto:")
        print("     - Copiar nuevamente desde Meta")
        print("     - Verificar sin espacios en blanco")
    else:
        print(f"❌ ERROR {response.status_code}")

print()
print("="*90)
