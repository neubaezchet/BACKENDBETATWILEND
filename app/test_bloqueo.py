"""
Test manual del sistema de bloqueo
Ejecutar: python test_bloqueo.py
"""

import requests

BACKEND_URL = "http://localhost:8000"  # Cambiar si usas otro puerto
CEDULA_TEST = "1085043374"  # Cambiar por una cédula real de tu sistema

def test_flujo_completo():
    print("🧪 INICIANDO TEST DE BLOQUEO\n")
    
    # 1. Verificar empleado
    print("1️⃣ Consultando empleado...")
    r = requests.get(f"{BACKEND_URL}/empleados/{CEDULA_TEST}")
    if r.status_code == 200:
        print(f"✅ Empleado encontrado: {r.json()['nombre']}")
    else:
        print(f"❌ Error: {r.json()}")
        return
    
    # 2. Verificar bloqueo (no debería haber)
    print("\n2️⃣ Verificando bloqueo inicial...")
    r = requests.get(f"{BACKEND_URL}/verificar-bloqueo/{CEDULA_TEST}")
    data = r.json()
    
    if data['bloqueado']:
        print(f"⚠️ Ya existe caso bloqueante: {data['caso_pendiente']['serial']}")
        serial_bloqueante = data['caso_pendiente']['serial']
    else:
        print("✅ No hay bloqueo activo")
        serial_bloqueante = None
    
    # 3. Si hay bloqueo, probar completar
    if serial_bloqueante:
        print(f"\n3️⃣ Simulando completar caso {serial_bloqueante}...")
        
        # Crear archivo de prueba
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(b'%PDF-1.4\nTest PDF')
            temp_path = f.name
        
        with open(temp_path, 'rb') as f:
            files = {'archivos': ('test.pdf', f, 'application/pdf')}
            r = requests.post(
                f"{BACKEND_URL}/casos/{serial_bloqueante}/completar",
                files=files
            )
        
        if r.status_code == 200:
            print(f"✅ Caso completado: {r.json()}")
        else:
            print(f"❌ Error completando: {r.json()}")
    
    # 4. Verificar bloqueo después (no debería haber)
    print("\n4️⃣ Verificando bloqueo después de completar...")
    r = requests.get(f"{BACKEND_URL}/verificar-bloqueo/{CEDULA_TEST}")
    data = r.json()
    
    if data['bloqueado']:
        print(f"❌ ERROR: Aún hay bloqueo: {data['caso_pendiente']['serial']}")
    else:
        print("✅ Bloqueo eliminado correctamente")
    
    print("\n✅ TEST COMPLETADO")

if __name__ == "__main__":
    test_flujo_completo()