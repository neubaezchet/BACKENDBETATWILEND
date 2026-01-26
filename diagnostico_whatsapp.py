#!/usr/bin/env python3
"""
Script para verificar la salud del sistema completo
"""

import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

print("=" * 100)
print("🔍 DIAGNÓSTICO COMPLETO: N8N + Backend + WAHA")
print("=" * 100)

# Configuración
N8N_WEBHOOK = os.getenv(
    "N8N_WEBHOOK_URL",
    "https://railway-n8n-production-5a3f.up.railway.app/webhook/incapacidades"
)
BACKEND_URL = "https://web-production-95ed.up.railway.app"
WAHA_URL = "https://devlikeaprowaha-production-111a.up.railway.app"

print("\n1️⃣ VERIFICACIÓN DE SERVICIOS")
print("-" * 100)

# Test N8N
try:
    r = requests.get(N8N_WEBHOOK.replace('/webhook/incapacidades', '/healthz'), timeout=5)
    print(f"✅ N8N: Respondiendo (status {r.status_code})")
except:
    print(f"❌ N8N: No responde")

# Test Backend
try:
    r = requests.get(f"{BACKEND_URL}/validador/stats", timeout=5)
    print(f"✅ Backend: Respondiendo (status {r.status_code})")
except:
    print(f"❌ Backend: No responde")

# Test WAHA
try:
    r = requests.get(f"{WAHA_URL}/api", timeout=5)
    print(f"✅ WAHA: Respondiendo (status {r.status_code})")
except:
    print(f"❌ WAHA: No responde o sin endpoint /api")

print("\n2️⃣ TEST: Envío de Email SOLO (sin WhatsApp)")
print("-" * 100)

payload1 = {
    "tipo_notificacion": "confirmacion",
    "email": "davidbaezaospino@gmail.com",
    "serial": "TEST-EMAIL-ONLY",
    "subject": "Test: Email sin WhatsApp",
    "html_content": "<p>Este es solo un test de email</p>",
    "cc_email": "",
    "correo_bd": "",
    "whatsapp": "",  # ← SIN WHATSAPP
    "whatsapp_message": "",
    "adjuntos": []
}

try:
    r = requests.post(N8N_WEBHOOK_URL, json=payload1, timeout=30)
    print(f"✅ Status: {r.status_code}")
    print(f"📊 Response: {json.dumps(r.json(), indent=2)[:300]}...")
except Exception as e:
    print(f"❌ Error: {e}")

# Test 2: Con WhatsApp vacío (pero presente)
print("\n2️⃣ Test: Con campo WhatsApp vacío")
print("-" * 80)

payload2 = {
    "tipo_notificacion": "confirmacion",
    "email": "davidbaezaospino@gmail.com",
    "serial": "TEST-WA-EMPTY",
    "subject": "Test: WhatsApp vacío",
    "html_content": "<p>Este test tiene campo WhatsApp vacío</p>",
    "cc_email": "",
    "correo_bd": "",
    "whatsapp": "   ",  # ← ESPACIOS SOLO
    "whatsapp_message": "Mensaje de prueba",
    "adjuntos": []
}

try:
    r = requests.post(N8N_WEBHOOK_URL, json=payload2, timeout=30)
    print(f"✅ Status: {r.status_code}")
    resp = r.json()
    if 'channels' in resp and 'whatsapp' in resp['channels']:
        wa = resp['channels']['whatsapp']
        print(f"   WhatsApp enviado: {wa.get('sent', False)}")
        print(f"   Error: {wa.get('error', 'N/A')}")
    else:
        print(f"📊 Response: {json.dumps(resp, indent=2)[:300]}...")
except Exception as e:
    print(f"❌ Error: {e}")

# Test 3: Con número de WhatsApp (POR FAVOR REEMPLAZA)
print("\n3️⃣ Test: Con número de WhatsApp real")
print("-" * 80)
print("⚠️  EDITA EL NÚMERO ABAJO ANTES DE EJECUTAR")

NUMERO_WHATSAPP = "3005551234"  # 👈 CAMBIAR POR UN NÚMERO REAL

if NUMERO_WHATSAPP == "3005551234":
    print("❌ ERROR: Debes cambiar el número de WhatsApp en el script")
    print("   Línea ~45: NUMERO_WHATSAPP = 'TU_NÚMERO_AQUÍ'")
else:
    payload3 = {
        "tipo_notificacion": "confirmacion",
        "email": "davidbaezaospino@gmail.com",
        "serial": "TEST-REAL-WA",
        "subject": "Test: WhatsApp Real",
        "html_content": "<p>Prueba real de WhatsApp</p>",
        "cc_email": "",
        "correo_bd": "",
        "whatsapp": NUMERO_WHATSAPP,
        "whatsapp_message": "Hola, este es un mensaje de prueba de IncaNeurobaeza.",
        "adjuntos": []
    }
    
    try:
        r = requests.post(N8N_WEBHOOK_URL, json=payload3, timeout=30)
        print(f"✅ Status: {r.status_code}")
        resp = r.json()
        
        print(f"\n📊 Respuesta completa:")
        print(json.dumps(resp, indent=2))
        
        if 'channels' in resp:
            print(f"\n📋 Resumen:")
            if 'email' in resp['channels']:
                em = resp['channels']['email']
                print(f"   📧 Email: {'✅' if em.get('sent') else '❌'} ({em.get('to', 'N/A')})")
            
            if 'whatsapp' in resp['channels']:
                wa = resp['channels']['whatsapp']
                print(f"   📱 WhatsApp: {'✅' if wa.get('sent') else '❌'}")
                if wa.get('sent'):
                    print(f"      Enviados: {wa.get('successful', 0)}/{wa.get('total_numbers', 0)}")
                else:
                    print(f"      Error: {wa.get('error', 'N/A')}")
                print(f"      Números: {wa.get('numbers', [])}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 80)
print("Fin del diagnóstico")
print("=" * 80)
