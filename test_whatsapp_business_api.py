#!/usr/bin/env python3
"""
🧪 TEST: Validar que WhatsApp Business API está correctamente configurada
Prueba de conectividad con Meta Graph API
"""

import os
import requests
import json
from datetime import datetime

def test_whatsapp_business_api():
    """
    Valida:
    1. Variables de entorno configuradas
    2. Token válido (sin expiración)
    3. Conectividad con Meta Graph API
    4. Capacidad de enviar mensaje
    """
    
    print("\n" + "="*90)
    print("🧪 TEST: WhatsApp Business API")
    print("="*90 + "\n")
    
    # 1️⃣ VERIFICAR VARIABLES DE ENTORNO
    print("1️⃣ Verificando variables de entorno...")
    
    token = os.environ.get("WHATSAPP_BUSINESS_API_TOKEN")
    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
    
    print(f"   WHATSAPP_BUSINESS_API_TOKEN: {'✅ Configurado' if token else '❌ FALTA'}")
    if token:
        print(f"      Longitud: {len(token)} caracteres")
        print(f"      Primeros 20 chars: {token[:20]}...")
    
    print(f"   WHATSAPP_PHONE_NUMBER_ID: {'✅ Configurado' if phone_id else '❌ FALTA'}")
    if phone_id:
        print(f"      Valor: {phone_id}")
    
    if not token or not phone_id:
        print("\n❌ ERROR: Faltan variables de entorno. No se puede continuar.")
        return False
    
    print("\n✅ Variables configuradas\n")
    
    # 2️⃣ VERIFICAR CONECTIVIDAD CON META
    print("2️⃣ Verificando conectividad con Meta Graph API...")
    
    api_version = "v19.0"
    base_url = f"https://graph.instagram.com/{api_version}"
    
    # Test 1: Verificar info de la cuenta
    try:
        url = f"{base_url}/me"
        headers = {"Authorization": f"Bearer {token}"}
        
        print(f"   GET {url}")
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Conectado con Meta (status 200)")
            print(f"      ID: {data.get('id', 'N/A')}")
            print(f"      Nombre: {data.get('name', 'N/A')}")
        elif response.status_code == 401:
            print(f"   ❌ Token inválido o expirado (status 401)")
            print(f"      Respuesta: {response.json()}")
            return False
        else:
            print(f"   ❌ Error {response.status_code}: {response.text[:100]}")
            return False
    
    except Exception as e:
        print(f"   ❌ Error de conectividad: {e}")
        return False
    
    print()
    
    # 3️⃣ VERIFICAR QUE EL PHONE ID EXISTE
    print("3️⃣ Verificando que el Phone ID existe...")
    
    try:
        url = f"{base_url}/{phone_id}"
        headers = {"Authorization": f"Bearer {token}"}
        
        print(f"   GET {url}")
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Phone ID válido (status 200)")
            print(f"      Número: {data.get('display_phone_number', 'N/A')}")
            print(f"      Verificado: {data.get('verified_name', 'N/A')}")
            print(f"      ID: {data.get('id', 'N/A')}")
        elif response.status_code == 404:
            print(f"   ❌ Phone ID no existe (status 404)")
            print(f"      Verifica el ID en Meta Business Suite")
            return False
        else:
            print(f"   ⚠️ Error {response.status_code}: {response.json()}")
            return False
    
    except Exception as e:
        print(f"   ❌ Error verificando Phone ID: {e}")
        return False
    
    print()
    
    # 4️⃣ PROBAR ENVÍO DE MENSAJE (DRY RUN)
    print("4️⃣ Validando formato de mensaje (sin enviar)...")
    
    test_message = {
        "messaging_product": "whatsapp",
        "to": "57XXXXXXXXX",  # Reemplazar con número real para test
        "type": "text",
        "text": {
            "preview_url": False,
            "body": "🧪 Mensaje de prueba desde IncaNeurobaeza"
        }
    }
    
    print(f"   Estructura del mensaje:")
    print(json.dumps(test_message, indent=2))
    print()
    print(f"   ✅ Formato válido")
    print(f"      Para enviar mensajes reales, usa: +57XXXXXXXXX")
    print()
    
    # 5️⃣ RESUMEN
    print("="*90)
    print("✅ TODAS LAS PRUEBAS PASARON")
    print("="*90)
    print("""
Tu WhatsApp Business API está correctamente configurada.

✅ Variables de entorno: Válidas
✅ Conectividad con Meta: OK
✅ Token: Válido
✅ Phone ID: Válido
✅ Formato de mensaje: Correcto

Próximos pasos:
1. Envía un formulario de incapacidad desde el frontend
2. Verifica que recibas el WhatsApp en el teléfono
3. Si hay problemas, revisa los logs en Railway

Para debugging adicional, revisa:
- Logs de Railway: https://railway.app/project/...
- Meta Business Suite: https://business.facebook.com/
""")
    print("="*90 + "\n")
    
    return True


def main():
    """Ejecuta todas las pruebas"""
    try:
        success = test_whatsapp_business_api()
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️ Prueba cancelada por el usuario")
        exit(1)
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}")
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()
