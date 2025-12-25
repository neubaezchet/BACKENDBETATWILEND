"""
Verificar que la sincronización automática esté activa
"""
import requests
import time
from datetime import datetime

API_URL = "https://bakcend-gemi-cha-2.onrender.com"
TOKEN = "0b9685e9a9ff3c24652acaad881ec7b2b4c17f6082ad164d10a6e67589f3f67c"

headers = {"X-Admin-Token": TOKEN}

print("=" * 70)
print("🔄 VERIFICACIÓN DE SINCRONIZACIÓN AUTOMÁTICA")
print("=" * 70)

# Primera lectura
print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 1️⃣ Obteniendo estado inicial...")
try:
    r = requests.get(f"{API_URL}/validador/empresas", headers=headers, timeout=10)
    if r.status_code == 200:
        empresas_inicial = r.json().get('empresas', [])
        print(f"   ✅ {len(empresas_inicial)} empresas encontradas:")
        for emp in empresas_inicial:
            print(f"      • {emp}")
    else:
        print(f"   ❌ Error: {r.status_code}")
        exit(1)
except Exception as e:
    print(f"   ❌ Error: {e}")
    exit(1)

# Esperar 70 segundos (más de 60 para asegurar que haya al menos 1 sync)
print(f"\n⏳ Esperando 70 segundos para verificar sincronización...")
print("   (La sincronización ocurre cada 60 segundos)")

for i in range(70, 0, -10):
    print(f"   ⏱️  {i} segundos restantes...")
    time.sleep(10)

# Segunda lectura
print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 2️⃣ Verificando después de la sincronización...")
try:
    r = requests.get(f"{API_URL}/validador/empresas", headers=headers, timeout=10)
    if r.status_code == 200:
        empresas_final = r.json().get('empresas', [])
        print(f"   ✅ {len(empresas_final)} empresas encontradas:")
        for emp in empresas_final:
            print(f"      • {emp}")
        
        # Comparar
        if empresas_inicial == empresas_final:
            print("\n📊 RESULTADO:")
            print("   ✅ Sincronización activa (no hubo cambios en el Excel)")
        else:
            nuevas = set(empresas_final) - set(empresas_inicial)
            eliminadas = set(empresas_inicial) - set(empresas_final)
            
            print("\n📊 RESULTADO:")
            print("   ✅ ¡Sincronización DETECTÓ cambios!")
            if nuevas:
                print(f"   ➕ Nuevas empresas: {', '.join(nuevas)}")
            if eliminadas:
                print(f"   ➖ Empresas eliminadas: {', '.join(eliminadas)}")
    else:
        print(f"   ❌ Error: {r.status_code}")
except Exception as e:
    print(f"   ❌ Error: {e}")

print("\n" + "=" * 70)
print("✅ Verificación completada")
print("=" * 70)