#!/usr/bin/env python3
"""
Script simple para probar WhatsApp Business API y enviar mensaje
"""

import requests
import json
from datetime import datetime

print("\n" + "="*90)
print("🧪 PRUEBA WHATSAPP BUSINESS API")
print("="*90 + "\n")

# Variables
TOKEN = "EAALZBZAAxkIMgBRZAvDX9lnZBC8qSPZByIpwCSA9IHdg7UfGmsoNW8XXHLwJ2E0GOAtQNZBaRttOnXVR9UkCxV0MzDIsKb1bZAmIF3IusxoAfgy90eWwZBnE5ZAZAhRGyllaDl6r50zYb0ZBLqlHrvCt3k06hmGSRtZBnupgs69k4snqR3zTRGApfiJTZAwwjpBjcXpu5JwZDZD"
PHONE_ID = "1065658909966623"
TO_NUMBER = "573208757593"  # Número del usuario
API_VERSION = "v19.0"
API_BASE_URL = f"https://graph.instagram.com/{API_VERSION}"

print("📋 CONFIGURACIÓN:")
print("-" * 90)
print(f"Token (primeros 20 caracteres): {TOKEN[:20]}...")
print(f"Phone Number ID: {PHONE_ID}")
print(f"Número destino: +{TO_NUMBER}")
print(f"API Version: {API_VERSION}")
print()

# ═══════════════════════════════════════════════════════════════════════════════════
# PASO 1: Validar Autenticación (GET /about)
# ═══════════════════════════════════════════════════════════════════════════════════

print("1️⃣ VALIDANDO AUTENTICACIÓN")
print("-" * 90)

url_about = f"{API_BASE_URL}/{PHONE_ID}/about"
headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

print(f"GET {url_about}")
print()

try:
    response = requests.get(url_about, headers=headers, timeout=10)
    status_code = response.status_code
    
    print(f"Status Code: {status_code}")
    print()
    
    if status_code == 200:
        print("✅ AUTENTICACIÓN EXITOSA")
        data = response.json()
        print()
        print("📱 Información del Número:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        print()
    else:
        print(f"❌ ERROR {status_code}")
        try:
            error_data = response.json()
            print(json.dumps(error_data, indent=2, ensure_ascii=False))
        except:
            print(response.text)
        print()
        exit(1)
        
except Exception as e:
    print(f"❌ ERROR: {e}")
    print()
    exit(1)

# ═══════════════════════════════════════════════════════════════════════════════════
# PASO 2: Enviar Mensaje de Prueba
# ═══════════════════════════════════════════════════════════════════════════════════

print()
print("2️⃣ ENVIANDO MENSAJE DE PRUEBA")
print("-" * 90)

url_messages = f"{API_BASE_URL}/{PHONE_ID}/messages"

payload = {
    "messaging_product": "whatsapp",
    "to": TO_NUMBER,
    "type": "text",
    "text": {
        "preview_url": False,
        "body": "Prueba de configuración - IncaNeurobaeza ✅\n\nEste mensaje fue enviado correctamente."
    }
}

print(f"POST {url_messages}")
print()
print("Payload:")
print(json.dumps(payload, indent=2, ensure_ascii=False))
print()

try:
    response = requests.post(url_messages, json=payload, headers=headers, timeout=15)
    status_code = response.status_code
    
    print(f"Status Code: {status_code}")
    print()
    
    if status_code in [200, 201, 202]:
        print("✅ MENSAJE ENVIADO EXITOSAMENTE")
        data = response.json()
        print()
        print("📋 Respuesta:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        message_id = data.get("messages", [{}])[0].get("id", "N/A")
        print()
        print(f"Message ID: {message_id}")
        print()
        print("✨ El mensaje debería llegar a tu celular en unos segundos")
        print()
    else:
        print(f"❌ ERROR {status_code}")
        try:
            error_data = response.json()
            print()
            print("Detalles del error:")
            print(json.dumps(error_data, indent=2, ensure_ascii=False))
        except:
            print(response.text)
        print()
        exit(1)
        
except Exception as e:
    print(f"❌ ERROR: {e}")
    print()
    exit(1)

# ═══════════════════════════════════════════════════════════════════════════════════
# RESUMEN
# ═══════════════════════════════════════════════════════════════════════════════════

print()
print("="*90)
print("✅ PRUEBA COMPLETADA")
print("="*90)
print()
print("📊 RESUMEN:")
print(f"  ✅ Token válido y autenticado")
print(f"  ✅ Número de teléfono configurado correctamente")
print(f"  ✅ Mensaje enviado exitosamente a +{TO_NUMBER}")
print()
print("🎯 PRÓXIMOS PASOS:")
print("  1. Verifica que el mensaje llegó a tu celular")
print("  2. Si llegó: Actualiza este token en Railway")
print("     - Variable: WHATSAPP_BUSINESS_API_TOKEN")
print("     - Valor: " + TOKEN)
print("  3. Redeploy Railway")
print("  4. Prueba enviando un formulario de incapacidad")
print()
print("="*90)
