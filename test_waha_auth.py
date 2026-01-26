#!/usr/bin/env python3
"""
Test de WAHA con autenticación correcta
Usando API Key: 1085043374
"""

import requests
import json
from datetime import datetime

WAHA_URL = "https://devlikeaprowaha-production-111a.up.railway.app"
WAHA_API_KEY = "1085043374"

print("=" * 100)
print("🔍 TEST: WAHA con AUTENTICACIÓN CORRECTA")
print("=" * 100)
print(f"API Key: {WAHA_API_KEY}")
print(f"Base URL: {WAHA_URL}")
print(f"Versión WAHA: 2025.12.1")
print(f"Motor: WEBJS")

# Headers con autenticación
headers = {
    "Content-Type": "application/json",
    "X-API-Key": WAHA_API_KEY,  # ← OPCIÓN 1
}

headers_bearer = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {WAHA_API_KEY}",  # ← OPCIÓN 2
}

print("\n1️⃣ TEST: Health Check CON Autenticación")
print("-" * 100)

# Test con X-API-Key
try:
    r = requests.get(f"{WAHA_URL}/healthz", headers=headers, timeout=5)
    print(f"✅ X-API-Key header - Status: {r.status_code}")
    if r.status_code == 200:
        print(f"   ✅ FUNCIONA con X-API-Key")
        print(f"   Response: {r.text[:100]}")
    elif r.status_code == 401:
        print(f"   ❌ No autorizado - Probar con Bearer")
except Exception as e:
    print(f"❌ Error: {e}")

# Test con Bearer Token
try:
    r = requests.get(f"{WAHA_URL}/healthz", headers=headers_bearer, timeout=5)
    print(f"\n✅ Bearer token header - Status: {r.status_code}")
    if r.status_code == 200:
        print(f"   ✅ FUNCIONA con Bearer Token")
        print(f"   Response: {r.text[:100]}")
except Exception as e:
    print(f"❌ Error: {e}")

print("\n2️⃣ TEST: Obtener sesiones")
print("-" * 100)

try:
    r = requests.get(f"{WAHA_URL}/api/sessions", headers=headers, timeout=5)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"✅ Sesiones encontradas:")
        print(json.dumps(data, indent=2))
    else:
        print(f"Response: {r.text[:200]}")
except Exception as e:
    print(f"Error: {e}")

print("\n3️⃣ TEST: Enviar mensaje de WhatsApp")
print("-" * 100)

NUMERO_WA = input("📱 Ingresa número de WhatsApp (ej: 573005551234): ").strip()

if not NUMERO_WA:
    print("⚠️  Número requerido. Usando número de prueba.")
    NUMERO_WA = "573005551234"

# Asegurar que empiece con 57
if not NUMERO_WA.startswith("57") and not NUMERO_WA.startswith("+57"):
    if len(NUMERO_WA) == 10:
        NUMERO_WA = "57" + NUMERO_WA
    else:
        print(f"⚠️  Formato de número incierto: {NUMERO_WA}")

payload = {
    "session": "default",
    "chatId": f"{NUMERO_WA}@c.us",
    "text": f"🧪 Mensaje de prueba WAHA - {datetime.now().strftime('%H:%M:%S')}",
    "delay": 1000
}

print(f"\n📤 Payload:")
print(json.dumps(payload, indent=2))

try:
    r = requests.post(
        f"{WAHA_URL}/api/sendText",
        json=payload,
        headers=headers,
        timeout=10
    )
    
    print(f"\n✅ Respuesta del servidor")
    print(f"   Status: {r.status_code}")
    
    try:
        data = r.json()
        print(f"   Response: {json.dumps(data, indent=2)}")
        
        if r.status_code in [200, 201]:
            print(f"\n✅ ¡ÉXITO! Mensaje enviado")
            print(f"   Deberías recibir el WhatsApp en {NUMERO_WA}")
        else:
            print(f"\n❌ Error al enviar")
            if "error" in data:
                print(f"   Error: {data['error']}")
    except:
        print(f"   Response text: {r.text[:300]}")

except requests.exceptions.Timeout:
    print(f"❌ Timeout - WAHA tardó demasiado")
except requests.exceptions.ConnectionError as e:
    print(f"❌ Error de conexión: {e}")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n4️⃣ INFORMACIÓN PARA N8N")
print("-" * 100)

print("""
✅ CONFIGURACIÓN CORRECTA EN N8N:

URL: https://devlikeaprowaha-production-111a.up.railway.app/api/sendText

Método: POST

Headers (Authentication):
  Type: Header Auth o Custom Headers
  Header: X-API-Key
  Value: 1085043374

Body JSON:
{
  "session": "default",
  "chatId": "{{ String($json).replace(/[^0-9+]/g, '') }}@c.us",
  "text": "{{ $('Procesar Datos').first().json.whatsapp_text }}",
  "delay": 1000
}

IMPORTANTE:
- El header X-API-Key debe estar configurado
- Sin él, WAHA rechaza 401
- Asegurar que se envíe en cada request
""")

print("\n" + "=" * 100)
