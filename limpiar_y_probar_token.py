#!/usr/bin/env python3
"""
Script para limpiar token de WhatsApp y probar
"""

import requests
import json

print("\n" + "="*90)
print("🔧 LIMPIEZA Y PRUEBA DEL TOKEN")
print("="*90 + "\n")

# Token tal como lo copiaste (con saltos de línea)
TOKEN_ORIGINAL = """EAALZBZAAxkIMgBRZAvDX9lnZBC8qSPZByIpwCSA9IHdg7UfGmsoNW8XXHLwJ2E0GOAtQNZBaRttOnXVR9UkCxV0MzDIsKb1bZAmIF3IusxoAfgy90eWwZBnE5ZAZAhRGyllaDl6r50zYb0ZBLqlHrvCt3k06hmGSRtZBnupgs69k4snqR3zTRGApfiJTZAwwjpBjcXpu5JwZDZD"""

# Limpiar espacios y saltos de línea
TOKEN_LIMPIO = TOKEN_ORIGINAL.strip().replace("\n", "").replace(" ", "")

print("📋 COMPARACIÓN DE TOKENS:")
print("-" * 90)
print(f"Longitud original: {len(TOKEN_ORIGINAL)}")
print(f"Longitud limpia: {len(TOKEN_LIMPIO)}")
print()

if TOKEN_ORIGINAL.strip() != TOKEN_LIMPIO:
    print("⚠️ Token tenía espacios/saltos de línea")
    print()
    print(f"Original (primeros 30): {TOKEN_ORIGINAL[:30]}...")
    print(f"Limpio (primeros 30): {TOKEN_LIMPIO[:30]}...")
    print()
    print("✅ Token limpiado correctamente")
    print()
else:
    print("✅ Token ya estaba limpio")

print()
print("🧪 PROBANDO CON TOKEN LIMPIO:")
print("-" * 90)

PHONE_ID = "1065658909966623"
TO_NUMBER = "573208757593"
API_VERSION = "v19.0"
API_BASE_URL = f"https://graph.instagram.com/{API_VERSION}"

# Paso 1: Validar autenticación
url_about = f"{API_BASE_URL}/{PHONE_ID}/about"
headers = {
    "Authorization": f"Bearer {TOKEN_LIMPIO}",
    "Content-Type": "application/json"
}

print(f"1️⃣ Validando autenticación...")
print(f"   GET {url_about}")

try:
    response = requests.get(url_about, headers=headers, timeout=10)
    
    if response.status_code == 200:
        print(f"   ✅ Status 200 - AUTENTICACIÓN EXITOSA")
        print()
        
        # Paso 2: Enviar mensaje
        print(f"2️⃣ Enviando mensaje de prueba...")
        
        url_messages = f"{API_BASE_URL}/{PHONE_ID}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": TO_NUMBER,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": "✅ Token válido y funcionando correctamente\n\nMensaje de prueba - IncaNeurobaeza"
            }
        }
        
        response_msg = requests.post(url_messages, json=payload, headers=headers, timeout=15)
        
        if response_msg.status_code in [200, 201, 202]:
            print(f"   ✅ Status {response_msg.status_code} - MENSAJE ENVIADO")
            data = response_msg.json()
            msg_id = data.get("messages", [{}])[0].get("id", "N/A")
            print(f"   Message ID: {msg_id}")
            print()
            print("="*90)
            print("✅ TODO FUNCIONANDO CORRECTAMENTE")
            print("="*90)
            print()
            print("📋 PRÓXIMOS PASOS:")
            print()
            print("1. Verifica el mensaje en tu celular (+573208757593)")
            print()
            print("2. Actualiza el token en Railway:")
            print(f"   Variable: WHATSAPP_BUSINESS_API_TOKEN")
            print(f"   Valor: {TOKEN_LIMPIO}")
            print()
            print("3. O copia este token limpio directamente:")
            print()
            print(f"   {TOKEN_LIMPIO}")
            print()
            print("4. Redeploy Railway y prueba un formulario")
            print()
        else:
            print(f"   ❌ Status {response_msg.status_code} - ERROR en envío")
            print(f"   {response_msg.json()}")
    else:
        print(f"   ❌ Status {response.status_code} - AUTENTICACIÓN FALLIDA")
        print(f"   {response.json()}")
        
except Exception as e:
    print(f"   ❌ ERROR: {e}")

print()
