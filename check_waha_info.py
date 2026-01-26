#!/usr/bin/env python3
"""
Script para obtener información y versión de WAHA
"""

import requests
import json
from datetime import datetime

WAHA_URL = "https://devlikeaprowaha-production-111a.up.railway.app"

print("=" * 100)
print("🔍 INFORMACIÓN DE WAHA - Diagnóstico Completo")
print("=" * 100)
print(f"Fecha/Hora del test: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# Test 1: Health check
print("\n1️⃣ HEALTH CHECK")
print("-" * 100)

endpoints_to_check = [
    ("/healthz", "Health status"),
    ("/api", "API base endpoint"),
    ("/api/version", "API version"),
    ("/api/info", "API info"),
    ("/health", "Health endpoint (alternativo)"),
    ("/api/status", "Status endpoint"),
]

for endpoint, description in endpoints_to_check:
    try:
        r = requests.get(f"{WAHA_URL}{endpoint}", timeout=5)
        print(f"✅ {endpoint:20} | Status: {r.status_code:3} | {description}")
        
        # Mostrar respuesta si es JSON
        try:
            data = r.json()
            if isinstance(data, dict):
                # Mostrar solo primeras 200 chars
                resp_str = json.dumps(data, indent=2)[:200]
                print(f"   Response: {resp_str}")
        except:
            print(f"   Response: {r.text[:100]}")
    
    except requests.exceptions.Timeout:
        print(f"⏱️  {endpoint:20} | TIMEOUT     | {description}")
    except Exception as e:
        print(f"❌ {endpoint:20} | ERROR       | {str(e)[:50]}")

# Test 2: Headers y información del servidor
print("\n2️⃣ INFORMACIÓN DEL SERVIDOR")
print("-" * 100)

try:
    r = requests.get(f"{WAHA_URL}/api", timeout=5)
    
    print("Headers recibidos:")
    for key, value in r.headers.items():
        if key.lower() in ['server', 'x-powered-by', 'version', 'x-version']:
            print(f"  {key}: {value}")
    
    print(f"\nServer responde: {r.headers.get('Server', 'No disponible')}")
    print(f"Content-Type: {r.headers.get('Content-Type', 'No disponible')}")

except Exception as e:
    print(f"Error: {e}")

# Test 3: Intentar obtener sesiones
print("\n3️⃣ SESIONES ACTIVAS EN WAHA")
print("-" * 100)

try:
    r = requests.get(f"{WAHA_URL}/api/sessions", timeout=5)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        try:
            data = r.json()
            print(f"Sesiones encontradas: {json.dumps(data, indent=2)[:500]}")
        except:
            print(f"Respuesta: {r.text[:200]}")
    else:
        print(f"Respuesta: {r.text[:200]}")
except Exception as e:
    print(f"❌ Error: {e}")

# Test 4: Verificar autenticación
print("\n4️⃣ AUTENTICACIÓN REQUERIDA")
print("-" * 100)

# Intentar sin autenticación
try:
    r = requests.get(f"{WAHA_URL}/api/sendText", timeout=5)
    print(f"Sin auth - Status: {r.status_code}")
    if r.status_code == 401:
        print("✅ WAHA requiere autenticación (401)")
        print(f"   Headers: {json.dumps(dict(r.headers), indent=2)[:200]}")
    elif r.status_code == 403:
        print("✅ WAHA requiere permisos (403)")
    else:
        print(f"   Respuesta: {r.text[:100]}")
except Exception as e:
    print(f"Error: {e}")

# Test 5: Configuración esperada para N8N
print("\n5️⃣ CONFIGURACIÓN ESPERADA EN N8N")
print("-" * 100)

print("""
Para que WAHA funcione en N8N, el nodo HTTP Request debe tener:

URL: https://devlikeaprowaha-production-111a.up.railway.app/api/sendText

Headers necesarios:
  - Content-Type: application/json
  - Authorization: Bearer <TOKEN> (si se requiere)

Body JSON:
{
  "session": "default",
  "chatId": "+573005551234@c.us",
  "text": "Mensaje de prueba",
  "delay": 1000
}

Autenticación:
  [ ] Sin autenticación
  [ ] Basic Auth
  [ ] Bearer Token (especificar)
  [ ] Custom Header
""")

# Test 6: Verificar version/información
print("\n6️⃣ INFORMACIÓN TÉCNICA DE WAHA")
print("-" * 100)

endpoints_info = [
    "/api/version",
    "/version",
    "/api/info",
    "/info",
    "/api/config",
]

version_found = False

for endpoint in endpoints_info:
    try:
        r = requests.get(f"{WAHA_URL}{endpoint}", timeout=5)
        if r.status_code == 200:
            print(f"✅ Encontrado en {endpoint}")
            try:
                data = r.json()
                print(json.dumps(data, indent=2))
                version_found = True
                break
            except:
                print(r.text[:300])
                version_found = True
                break
    except:
        pass

if not version_found:
    print("❌ No se pudo obtener información de versión")
    print("   WAHA podría no tener endpoint de versión públicamente disponible")

# Test 7: Verificar DNS/Conectividad
print("\n7️⃣ VERIFICACIÓN DE CONECTIVIDAD")
print("-" * 100)

import socket

try:
    hostname = "devlikeaprowaha-production-111a.up.railway.app"
    ip = socket.gethostbyname(hostname)
    print(f"✅ DNS resuelve correctamente")
    print(f"   {hostname} → {ip}")
except socket.gaierror:
    print(f"❌ Error resolviendo DNS")
except Exception as e:
    print(f"❌ Error: {e}")

# Test 8: Verificar que N8N puede alcanzar WAHA
print("\n8️⃣ VERIFICACIÓN DE LATENCIA")
print("-" * 100)

import time

try:
    start = time.time()
    r = requests.get(f"{WAHA_URL}/api", timeout=10)
    elapsed = (time.time() - start) * 1000  # en ms
    
    print(f"✅ Latencia: {elapsed:.0f}ms")
    print(f"   Status: {r.status_code}")
    
    if elapsed > 5000:
        print("⚠️  ADVERTENCIA: Latencia muy alta (>5s)")
except Exception as e:
    print(f"❌ Error: {e}")

print("\n" + "=" * 100)
print("📊 RESUMEN")
print("=" * 100)

print("""
INFORMACIÓN IMPORTANTE:

1. URL de WAHA: https://devlikeaprowaha-production-111a.up.railway.app
   - Está en Railway (Producción)
   - Debe estar corriendo 24/7

2. Endpoint para enviar: /api/sendText
   - Método: POST
   - Body: JSON

3. Requisitos:
   - Sesión activa (nombre: "default" o personalizado)
   - WhatsApp conectado y autenticado
   - Número de teléfono registrado

4. Autenticación:
   - Verificar si requiere Bearer token
   - O si es abierto sin autenticación

5. Formato del mensaje:
   - chatId: "+57XXXXXXXXXX@c.us" (WhatsApp Business format)
   - text: Mensaje a enviar
   - delay: Milisegundos de espera

Si hay problemas:
1. Revisa si WAHA está corriendo en Railway
2. Verifica logs en Railway → Services → WAHA
3. Comprueba que WhatsApp esté conectado
4. Valida tokens/credenciales de autenticación
""")

print("=" * 100)
print("Próximo paso: Ejecuta test_whatsapp_flow.py con un número real")
print("=" * 100)
