#!/usr/bin/env python3
"""
Prueba de la plantilla demo "hello_world" que Meta aprueba automáticamente
para toda cuenta de WhatsApp Business (Cloud API), sin necesidad de crear
ni esperar aprobación de una plantilla propia.

Sirve para confirmar que el token + phone_number_id funcionan de punta a
punta ANTES de construir lógica propia (plantillas personalizadas, flujo
conversacional, etc.).

Nota: "hello_world" solo puede enviarse en inglés (idioma en_US) y su texto
es fijo ("Hello World"), lo controla Meta. Es solo para validar conectividad.

Requiere variables de entorno:
  WHATSAPP_BUSINESS_API_TOKEN   -> token permanente (Never Expires) de la app de Meta
  WHATSAPP_PHONE_NUMBER_ID      -> ID del número de WhatsApp (Meta Business Suite > API Setup)
  WHATSAPP_TEST_NUMBER          -> número destino en formato internacional sin '+' (ej: 573001234567)
"""

import os
import json
import requests

API_VERSION = "v19.0"
API_BASE_URL = f"https://graph.facebook.com/{API_VERSION}"

TOKEN = os.environ.get("WHATSAPP_BUSINESS_API_TOKEN")
PHONE_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
TO_NUMBER = os.environ.get("WHATSAPP_TEST_NUMBER")


def main():
    print("\n" + "=" * 90)
    print("🧪 PRUEBA: Plantilla demo 'hello_world' (Meta WhatsApp Cloud API)")
    print("=" * 90 + "\n")

    faltantes = [
        nombre
        for nombre, valor in [
            ("WHATSAPP_BUSINESS_API_TOKEN", TOKEN),
            ("WHATSAPP_PHONE_NUMBER_ID", PHONE_ID),
            ("WHATSAPP_TEST_NUMBER", TO_NUMBER),
        ]
        if not valor
    ]
    if faltantes:
        print("❌ Faltan variables de entorno:")
        for f in faltantes:
            print(f"   - {f}")
        return 1

    url = f"{API_BASE_URL}/{PHONE_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": TO_NUMBER,
        "type": "template",
        "template": {
            "name": "hello_world",
            "language": {"code": "en_US"},
        },
    }
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }

    print(f"POST {url}")
    print(json.dumps(payload, indent=2))
    print()

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
    except Exception as e:
        print(f"❌ Error de red: {e}")
        return 1

    print(f"Status: {response.status_code}")
    try:
        data = response.json()
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception:
        print(response.text)
        data = {}

    if response.status_code in (200, 201, 202):
        msg_id = data.get("messages", [{}])[0].get("id", "N/A")
        print()
        print(f"✅ Plantilla enviada. Message ID: {msg_id}")
        print(f"   Revisa el WhatsApp de +{TO_NUMBER} (llega en inglés: 'Hello World').")
        print("   Si esto llega, el token y el phone_number_id están funcionando")
        print("   correctamente y el problema anterior era solo el dominio incorrecto.")
        return 0

    error_msg = data.get("error", {}).get("message", "desconocido")
    error_code = data.get("error", {}).get("code")
    print()
    print(f"❌ Falló el envío. Código: {error_code} — {error_msg}")
    if error_code == 131047 or "24" in str(error_msg):
        print("   Puede ser la ventana de 24h: 'hello_world' no debería verse afectado,")
        print("   pero si ves esto en mensajes de texto libre, ese es el problema:")
        print("   solo puedes reabrir la conversación con una plantilla aprobada.")
    return 1


if __name__ == "__main__":
    exit(main())
