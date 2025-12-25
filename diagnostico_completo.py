"""
🔍 DIAGNÓSTICO COMPLETO - Portal Validadores + Backend
Ejecutar: python diagnostico_completo.py
"""

import os
import sys
import requests
from datetime import datetime

print("=" * 80)
print("🔍 DIAGNÓSTICO COMPLETO DEL SISTEMA")
print("=" * 80)
print(f"⏰ Iniciado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

# Colores para terminal
class Color:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'

def test_result(passed, message):
    symbol = f"{Color.GREEN}✅" if passed else f"{Color.RED}❌"
    print(f"{symbol} {message}{Color.END}")
    return passed

# ==================== CONFIGURACIÓN ====================
API_BASE_URL = "https://bakcend-gemi-cha-2.onrender.com"
ADMIN_TOKEN = "0b9685e9a9ff3c24652acaad881ec7b2b4c17f6082ad164d10a6e67589f3f67c"

print(f"{Color.BLUE}📡 URL del Backend:{Color.END} {API_BASE_URL}")
print(f"{Color.BLUE}🔑 Token Admin:{Color.END} {ADMIN_TOKEN[:20]}...{ADMIN_TOKEN[-10:]}\n")

# ==================== TEST 1: CONEXIÓN BÁSICA ====================
print("=" * 80)
print("TEST 1: Conexión Básica al Backend")
print("=" * 80)

try:
    response = requests.get(f"{API_BASE_URL}/", timeout=10)
    test_result(response.status_code == 200, f"Backend responde (Status: {response.status_code})")
    if response.status_code == 200:
        data = response.json()
        print(f"   Respuesta: {data.get('message', 'N/A')}")
except requests.exceptions.Timeout:
    test_result(False, "Backend NO responde (Timeout)")
    print(f"   {Color.RED}El servidor tardó más de 10 segundos en responder{Color.END}")
except requests.exceptions.ConnectionError:
    test_result(False, "Backend NO accesible (Connection Error)")
    print(f"   {Color.RED}No se pudo conectar al servidor{Color.END}")
except Exception as e:
    test_result(False, f"Error inesperado: {str(e)}")

print()

# ==================== TEST 2: HEALTH CHECK ====================
print("=" * 80)
print("TEST 2: Health Check")
print("=" * 80)

try:
    response = requests.get(f"{API_BASE_URL}/health", timeout=10)
    if response.status_code == 200:
        data = response.json()
        test_result(True, f"Health check OK - Status: {data.get('status', 'unknown')}")
        print(f"   Base de datos: {data.get('database', 'unknown')}")
        print(f"   Versión: {data.get('version', 'unknown')}")
        print(f"   CORS: {data.get('cors_enabled', False)}")
    else:
        test_result(False, f"Health check FALLÓ (Status: {response.status_code})")
except Exception as e:
    test_result(False, f"Health check ERROR: {str(e)}")

print()

# ==================== TEST 3: AUTENTICACIÓN ====================
print("=" * 80)
print("TEST 3: Verificación de Token Admin")
print("=" * 80)

headers = {
    "X-Admin-Token": ADMIN_TOKEN,
    "Content-Type": "application/json"
}

try:
    # Intentar acceder a stats que requiere autenticación
    response = requests.get(f"{API_BASE_URL}/validador/stats", headers=headers, timeout=10)
    
    if response.status_code == 200:
        test_result(True, "Token Admin VÁLIDO")
        data = response.json()
        print(f"   Total casos: {data.get('total_casos', 0)}")
    elif response.status_code == 403:
        test_result(False, "Token Admin INVÁLIDO o RECHAZADO")
        print(f"   {Color.YELLOW}Respuesta del servidor: {response.text[:200]}{Color.END}")
    else:
        test_result(False, f"Error de autenticación (Status: {response.status_code})")
        print(f"   Respuesta: {response.text[:200]}")
except Exception as e:
    test_result(False, f"Error verificando token: {str(e)}")

print()

# ==================== TEST 4: ENDPOINT DE EMPRESAS ====================
print("=" * 80)
print("TEST 4: Endpoint /validador/empresas")
print("=" * 80)

try:
    response = requests.get(f"{API_BASE_URL}/validador/empresas", headers=headers, timeout=10)
    
    if response.status_code == 200:
        data = response.json()
        empresas = data.get('empresas', [])
        
        if len(empresas) > 0:
            test_result(True, f"Endpoint OK - {len(empresas)} empresa(s) encontrada(s)")
            print(f"\n   {Color.GREEN}📋 Empresas disponibles:{Color.END}")
            for i, emp in enumerate(empresas, 1):
                print(f"      {i}. {emp}")
        else:
            test_result(False, "Endpoint responde pero NO hay empresas en la BD")
            print(f"   {Color.YELLOW}⚠️  La tabla 'companies' está vacía{Color.END}")
    
    elif response.status_code == 403:
        test_result(False, "Acceso DENEGADO - Token inválido")
    
    elif response.status_code == 500:
        test_result(False, "ERROR INTERNO del servidor")
        print(f"   {Color.RED}Detalles: {response.text[:300]}{Color.END}")
    
    else:
        test_result(False, f"Respuesta inesperada (Status: {response.status_code})")
        print(f"   Respuesta: {response.text[:200]}")

except requests.exceptions.Timeout:
    test_result(False, "Timeout - El servidor no respondió a tiempo")
except Exception as e:
    test_result(False, f"Error: {str(e)}")

print()

# ==================== TEST 5: ENDPOINT DE CASOS ====================
print("=" * 80)
print("TEST 5: Endpoint /validador/casos")
print("=" * 80)

try:
    response = requests.get(f"{API_BASE_URL}/validador/casos?page=1&page_size=5", 
                          headers=headers, timeout=10)
    
    if response.status_code == 200:
        data = response.json()
        casos = data.get('items', [])
        total = data.get('total', 0)
        
        test_result(True, f"Endpoint OK - {total} caso(s) total(es), mostrando {len(casos)}")
        
        if len(casos) > 0:
            print(f"\n   {Color.GREEN}📄 Primeros casos:{Color.END}")
            for caso in casos[:3]:
                print(f"      • {caso.get('serial')} - {caso.get('nombre')} ({caso.get('estado')})")
    else:
        test_result(False, f"Error obteniendo casos (Status: {response.status_code})")

except Exception as e:
    test_result(False, f"Error: {str(e)}")

print()

# ==================== TEST 6: CORS ====================
print("=" * 80)
print("TEST 6: Configuración CORS")
print("=" * 80)

try:
    # Hacer petición OPTIONS (preflight)
    response = requests.options(f"{API_BASE_URL}/validador/empresas", headers=headers, timeout=10)
    
    cors_headers = {
        'Access-Control-Allow-Origin': response.headers.get('Access-Control-Allow-Origin', 'N/A'),
        'Access-Control-Allow-Methods': response.headers.get('Access-Control-Allow-Methods', 'N/A'),
        'Access-Control-Allow-Headers': response.headers.get('Access-Control-Allow-Headers', 'N/A'),
    }
    
    if cors_headers['Access-Control-Allow-Origin'] == '*':
        test_result(True, "CORS configurado correctamente (permite todos los orígenes)")
    elif 'vercel.app' in cors_headers['Access-Control-Allow-Origin']:
        test_result(True, f"CORS permite: {cors_headers['Access-Control-Allow-Origin']}")
    else:
        test_result(False, "CORS podría estar bloqueando el frontend")
    
    print(f"   Headers CORS:")
    for key, value in cors_headers.items():
        print(f"      {key}: {value}")

except Exception as e:
    print(f"   {Color.YELLOW}⚠️  No se pudo verificar CORS: {str(e)}{Color.END}")

print()

# ==================== TEST 7: BASE DE DATOS ====================
print("=" * 80)
print("TEST 7: Verificación de Base de Datos (si tienes acceso local)")
print("=" * 80)

try:
    # Intentar importar módulos locales
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from app.database import SessionLocal, Company, Employee, Case
    
    db = SessionLocal()
    
    # Contar registros
    empresas_count = db.query(Company).filter(Company.activa == True).count()
    empleados_count = db.query(Employee).filter(Employee.activo == True).count()
    casos_count = db.query(Case).count()
    
    test_result(True, "Acceso directo a la BD exitoso")
    print(f"   📊 Registros en BD:")
    print(f"      • Empresas activas: {empresas_count}")
    print(f"      • Empleados activos: {empleados_count}")
    print(f"      • Casos totales: {casos_count}")
    
    if empresas_count == 0:
        print(f"\n   {Color.RED}⚠️  PROBLEMA DETECTADO: No hay empresas en la BD{Color.END}")
        print(f"   {Color.YELLOW}Solución: Migra el Excel con:{Color.END}")
        print(f"      python -c \"from app.database import init_db; init_db()\"")
        print(f"      curl -X POST {API_BASE_URL}/admin/migrar-excel")
    
    # Listar empresas
    if empresas_count > 0:
        empresas = db.query(Company).filter(Company.activa == True).all()
        print(f"\n   {Color.GREEN}🏢 Empresas registradas:{Color.END}")
        for emp in empresas[:10]:
            print(f"      • {emp.nombre} (ID: {emp.id})")
    
    db.close()

except ImportError:
    print(f"   {Color.YELLOW}⚠️  No se puede acceder a la BD desde aquí (normal si estás en local){Color.END}")
    print(f"   Este test solo funciona si ejecutas el script en el servidor")
except Exception as e:
    print(f"   {Color.YELLOW}⚠️  Error accediendo a BD: {str(e)}{Color.END}")

print()

# ==================== RESUMEN FINAL ====================
print("=" * 80)
print("📊 RESUMEN Y RECOMENDACIONES")
print("=" * 80)

print(f"\n{Color.BLUE}🔍 Problemas detectados:{Color.END}")
print("   (Los tests fallidos de arriba)")

print(f"\n{Color.GREEN}✅ Siguientes pasos:{Color.END}")
print("   1. Si NO hay empresas en la BD:")
print("      → Ejecuta: python -c 'from app.database import init_db; init_db()'")
print(f"      → O visita: {API_BASE_URL}/admin/migrar-excel")
print()
print("   2. Si el token falla:")
print("      → Verifica que en Render Dashboard → Environment esté:")
print(f"        ADMIN_TOKEN={ADMIN_TOKEN}")
print()
print("   3. Si CORS falla:")
print("      → Verifica en app/main.py que allow_origins=['*']")
print()
print("   4. Si todo está OK pero el frontend no conecta:")
print("      → Verifica en el navegador (F12 → Console) si hay errores de red")
print("      → Verifica que REACT_APP_API_URL apunte a: " + API_BASE_URL)

print("\n" + "=" * 80)
print(f"⏰ Diagnóstico completado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)