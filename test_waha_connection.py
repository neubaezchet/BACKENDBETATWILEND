#!/usr/bin/env python3
"""
Verificar conexión directa a WAHA
"""

import requests
import json

WAHA_URL = "https://devlikeaprowaha-production-111a.up.railway.app/api/sendText"

print("=" * 80)
print("🔍 TEST: Conexión Directa a WAHA")
print("=" * 80)

# Test 1: Health check
print("\n1️⃣ Health Check de WAHA")
print("-" * 80)

try:
    r = requests.get(
        "https://devlikeaprowaha-production-111a.up.railway.app/api",
        timeout=10
    )
    print(f"✅ WAHA responde")
    print(f"   Status: {r.status_code}")
    print(f"   Response: {r.text[:200]}")
except Exception as e:
    print(f"❌ Error conectando a WAHA: {e}")

# Test 2: Intentar enviar un mensaje (sin token)
print("\n2️⃣ Test de envío (puede fallar por falta de token)")
print("-" * 80)

payload = {
    "session": "default",
    "chatId": "573005551234@c.us",  # Formato WhatsApp: +57 3005551234
    "text": "Mensaje de prueba desde script",
    "delay": 1000
}

try:
    r = requests.post(
        WAHA_URL,
        json=payload,
        timeout=10,
        headers={
            'Content-Type': 'application/json',
            # SIN token - probablemente falle pero podemos ver el error
        }
    )
    print(f"Status: {r.status_code}")
    print(f"Response: {json.dumps(r.json() if r.text else {}, indent=2)}")
except Exception as e:
    print(f"Error: {e}")

print("\n" + "=" * 80)
print("Notas:")
print("  • WAHA usa formato: +57XXXXXXXXXX@c.us (WhatsApp Business)")
print("  • Necesita autenticación (Authorization header)")
print("  • Requiere sesión activa en el teléfono")
print("=" * 80)
