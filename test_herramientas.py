"""
Test rápido para verificar que las herramientas PDF funcionan en producción
"""
import requests
import json

# Configuración
API_BASE_URL = "https://web-production-95ed.up.railway.app"
ADMIN_TOKEN = "0b9685e9a9ff3c24652acaad881ec7b2b4c17f6082ad164d10a6e67589f3f67c"

# Obtener un caso de prueba
print("📋 Obteniendo lista de casos...")
response = requests.get(
    f"{API_BASE_URL}/validador/casos",
    headers={"X-Admin-Token": ADMIN_TOKEN},
    params={"page": 1, "page_size": 1}
)

if response.status_code != 200:
    print(f"❌ Error obteniendo casos: {response.status_code}")
    print(response.text)
    exit(1)

data = response.json()
if not data.get("casos"):
    print("⚠️ No hay casos en la base de datos")
    exit(1)

caso = data["casos"][0]
serial = caso["serial"]
print(f"✅ Caso de prueba: {serial}")

# Probar endpoint de edición PDF
print(f"\n🔧 Probando endpoint /editar-pdf...")
print(f"   URL: {API_BASE_URL}/validador/casos/{serial}/editar-pdf")

# Operación simple: rotar 90°
operaciones = {
    "operaciones": {
        "rotate": [
            {"page_num": 0, "angle": 90}
        ]
    }
}

print(f"📤 Enviando operación: rotar página 0 a 90°")

try:
    response = requests.post(
        f"{API_BASE_URL}/validador/casos/{serial}/editar-pdf",
        headers={
            "X-Admin-Token": ADMIN_TOKEN,
            "Content-Type": "application/json"
        },
        json=operaciones,
        timeout=60  # 60 segundos
    )
    
    print(f"\n📡 Respuesta HTTP: {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ SUCCESS - PDF editado correctamente")
        print(f"   Serial: {result.get('serial')}")
        print(f"   Nuevo link: {result.get('nuevo_link')}")
        print(f"   Modificaciones: {result.get('modificaciones')}")
    elif response.status_code == 404:
        print(f"❌ ERROR 404 - Endpoint no encontrado")
        print(f"   Verifica que el backend tenga la ruta /validador/casos/{{serial}}/editar-pdf")
    elif response.status_code == 500:
        print(f"❌ ERROR 500 - Error interno del servidor")
        print(f"   Respuesta: {response.text}")
        print(f"\n💡 Causa probable:")
        print(f"   - Dependencias no instaladas (pymupdf, opencv, etc.)")
        print(f"   - Error de Google Drive (token expirado)")
    else:
        print(f"❌ ERROR {response.status_code}")
        print(f"   Respuesta: {response.text}")

except requests.exceptions.Timeout:
    print(f"⏰ TIMEOUT - La operación tomó más de 60 segundos")
    print(f"   Esto puede ser normal si el PDF es grande")
    print(f"   Verifica los logs de Railway para ver si está procesando")
except requests.exceptions.ConnectionError:
    print(f"❌ ERROR DE CONEXIÓN")
    print(f"   No se pudo conectar a {API_BASE_URL}")
except Exception as e:
    print(f"❌ ERROR INESPERADO: {e}")

print("\n" + "="*60)
print("SIGUIENTE PASO:")
print("1. Si funcionó → Las herramientas están OK, solo tardan tiempo normal")
print("2. Si ERROR 404 → El endpoint no existe, verificar deployment")
print("3. Si ERROR 500 → Revisar logs de Railway con: railway logs")
print("="*60)
