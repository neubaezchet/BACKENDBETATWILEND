#!/usr/bin/env python3
"""
Test completo del flujo WhatsApp N8N
Simula lo que hace el backend
"""

import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

# URL de N8N
N8N_WEBHOOK_URL = os.getenv(
    "N8N_WEBHOOK_URL",
    "https://railway-n8n-production-5a3f.up.railway.app/webhook/incapacidades"
)

def test_whatsapp_sending():
    """Test de envío de WhatsApp a través de N8N"""
    
    print("=" * 80)
    print("🧪 TEST: Envío de WhatsApp vía N8N + WAHA")
    print("=" * 80)
    
    # Simulando datos del backend
    payload = {
        "tipo_notificacion": "confirmacion",
        "email": "davidbaezaospino@gmail.com",  # Tu email
        "serial": "INC-2026-01-25-001",
        "subject": "Test WhatsApp - Confirmación de Incapacidad",
        "html_content": "<h2>Test de WhatsApp</h2><p>Este es un mensaje de prueba para verificar que WhatsApp se envía correctamente.</p>",
        "cc_email": "",
        "correo_bd": "",
        "whatsapp": "3005551234",  # ⚠️ CAMBIAR POR UN NÚMERO REAL
        "whatsapp_message": "Hola, este es un mensaje de prueba de IncaNeurobaeza.",
        "adjuntos": []
    }
    
    print(f"\n📤 Enviando payload a N8N:")
    print(json.dumps(payload, indent=2))
    
    try:
        print(f"\n🔗 URL: {N8N_WEBHOOK_URL}")
        
        response = requests.post(
            N8N_WEBHOOK_URL,
            json=payload,
            timeout=30,
            headers={
                'Content-Type': 'application/json',
                'User-Agent': 'Test-WhatsApp-Flow'
            }
        )
        
        print(f"\n✅ Respuesta recibida")
        print(f"   Status: {response.status_code}")
        
        try:
            resp_data = response.json()
            print(f"   JSON Response:")
            print(json.dumps(resp_data, indent=2))
            
            # Analizar respuesta
            if 'channels' in resp_data:
                print(f"\n📊 Análisis de canales:")
                
                if 'email' in resp_data['channels']:
                    email_status = resp_data['channels']['email']
                    print(f"   📧 Email: {'✅ Enviado' if email_status.get('sent') else '❌ NO enviado'}")
                    if not email_status.get('sent'):
                        print(f"      Error: {email_status.get('error', 'Desconocido')}")
                
                if 'whatsapp' in resp_data['channels']:
                    wa_status = resp_data['channels']['whatsapp']
                    print(f"   📱 WhatsApp: {'✅ Enviado' if wa_status.get('sent') else '❌ NO enviado'}")
                    if wa_status.get('sent'):
                        print(f"      Total enviados: {wa_status.get('successful', 0)}")
                        print(f"      Números: {wa_status.get('numbers', [])}")
                    else:
                        print(f"      Error: {wa_status.get('error', 'Desconocido')}")
                        print(f"      Números intentados: {wa_status.get('numbers', [])}")
        except:
            print(f"   Respuesta de texto: {response.text[:500]}")
    
    except requests.exceptions.Timeout:
        print("❌ Timeout esperando respuesta")
    except requests.exceptions.ConnectionError as e:
        print(f"❌ Error de conexión: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("\n⚠️  IMPORTANTE:")
    print("   1. Edita el número de WhatsApp en la línea ~32 con un número real")
    print("   2. Debe ser formato: 3005551234 (Colombia sin +57)")
    print("   3. O también: +573005551234 (con código país)")
    print()
    
    input("Presiona ENTER cuando hayas actualizado el número...")
    test_whatsapp_sending()
