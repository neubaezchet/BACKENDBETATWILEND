"""
Script de Verificación - Conexión Backend ↔ Base de Datos
Ejecutar: python test_conexion.py
"""

import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Cargar variables de entorno
load_dotenv()

# Importar modelos de la aplicación
try:
    from app.database import get_database_url, SessionLocal, Company, Employee, Case
    print("✅ Módulos importados correctamente\n")
except ImportError as e:
    print(f"❌ Error importando módulos: {e}")
    print("Asegúrate de estar en el directorio raíz del proyecto")
    sys.exit(1)

def test_database_connection():
    """Prueba 1: Verificar conexión a PostgreSQL"""
    print("=" * 60)
    print("🔍 PRUEBA 1: Conexión a Base de Datos")
    print("=" * 60)
    
    try:
        db_url = get_database_url()
        
        # Ocultar credenciales sensibles
        if "postgresql://" in db_url:
            parts = db_url.split("@")
            safe_url = parts[1] if len(parts) > 1 else "..."
            print(f"📌 Conectando a: postgresql://***@{safe_url}")
        else:
            print(f"📌 Usando: SQLite (desarrollo)")
        
        db = SessionLocal()
        result = db.execute(text("SELECT version()"))
        version = result.fetchone()[0]
        print(f"✅ Conexión exitosa")
        print(f"📊 Base de datos: {version[:60]}...")
        db.close()
        return True
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        return False

def test_tables_exist():
    """Prueba 2: Verificar que las tablas existen"""
    print("\n" + "=" * 60)
    print("🔍 PRUEBA 2: Verificación de Tablas")
    print("=" * 60)
    
    try:
        db = SessionLocal()
        
        # Verificar tabla companies
        companies_count = db.query(Company).count()
        print(f"✅ Tabla 'companies': {companies_count} registros")
        
        # Verificar tabla employees
        employees_count = db.query(Employee).count()
        print(f"✅ Tabla 'employees': {employees_count} registros")
        
        # Verificar tabla cases
        cases_count = db.query(Case).count()
        print(f"✅ Tabla 'cases': {cases_count} registros")
        
        db.close()
        return True
    except Exception as e:
        print(f"❌ Error verificando tablas: {e}")
        print("   Ejecuta: python -c 'from app.database import init_db; init_db()'")
        return False

def test_environment_variables():
    """Prueba 3: Verificar variables de entorno"""
    print("\n" + "=" * 60)
    print("🔍 PRUEBA 3: Variables de Entorno")
    print("=" * 60)
    
    required_vars = {
        'DATABASE_URL': '🔵 URL de PostgreSQL',
        'ADMIN_TOKEN': '🔑 Token de admin',
        'GOOGLE_CLIENT_ID': '🔐 Google Drive',
        'BREVO_API_KEY': '📧 Email (Brevo)',
    }
    
    all_ok = True
    for var, desc in required_vars.items():
        value = os.getenv(var)
        if value:
            # Mostrar solo los primeros caracteres por seguridad
            if len(value) > 15:
                masked = value[:10] + "..." + value[-5:]
            else:
                masked = value[:5] + "..."
            print(f"✅ {var:<20} {masked:<20} ({desc})")
        else:
            print(f"❌ {var:<20} {'NO CONFIGURADO':<20} ({desc})")
            all_ok = False
    
    return all_ok

def test_sample_data():
    """Prueba 4: Insertar y leer datos de prueba"""
    print("\n" + "=" * 60)
    print("🔍 PRUEBA 4: Inserción y Lectura de Datos")
    print("=" * 60)
    
    try:
        db = SessionLocal()
        
        # Verificar si existe una empresa de prueba
        test_company = db.query(Company).filter(Company.nombre == "TEST_EMPRESA").first()
        
        if not test_company:
            # Crear empresa de prueba
            test_company = Company(
                nombre="TEST_EMPRESA",
                nit="900000000",
                activa=True
            )
            db.add(test_company)
            db.commit()
            db.refresh(test_company)
            print(f"✅ Empresa de prueba creada: ID {test_company.id}")
        else:
            print(f"✅ Empresa de prueba ya existe: ID {test_company.id}")
        
        # Leer empresas activas
        empresas_activas = db.query(Company).filter(Company.activa == True).all()
        print(f"✅ Total empresas activas: {len(empresas_activas)}")
        
        if empresas_activas:
            print("\n📋 Empresas registradas:")
            for empresa in empresas_activas[:5]:  # Mostrar máximo 5
                print(f"   • {empresa.nombre} (ID: {empresa.id})")
            if len(empresas_activas) > 5:
                print(f"   ... y {len(empresas_activas) - 5} más")
        
        db.close()
        return True
    except Exception as e:
        print(f"❌ Error en prueba de datos: {e}")
        return False

def test_api_endpoints():
    """Prueba 5: Verificar que los endpoints responden"""
    print("\n" + "=" * 60)
    print("🔍 PRUEBA 5: Test de Endpoints (opcional)")
    print("=" * 60)
    
    try:
        import requests
        
        base_url = "https://bakcend-gemi-cha-2.onrender.com"
        
        # Test endpoint raíz
        response = requests.get(f"{base_url}/", timeout=10)
        if response.status_code == 200:
            print(f"✅ GET / → {response.status_code}")
        else:
            print(f"⚠️  GET / → {response.status_code}")
        
        # Test health check
        response = requests.get(f"{base_url}/health", timeout=10)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ GET /health → {data.get('status', 'unknown')}")
        else:
            print(f"⚠️  GET /health → {response.status_code}")
        
        return True
    except ImportError:
        print("⚠️  Librería 'requests' no instalada")
        print("   Instala con: pip install requests")
        return True  # No es crítico
    except Exception as e:
        print(f"⚠️  Error en test de endpoints: {e}")
        return True  # No es crítico

def main():
    """Ejecutar todas las pruebas"""
    print("\n" + "=" * 60)
    print("🧪 SCRIPT DE VERIFICACIÓN - IncaNeurobaeza")
    print("=" * 60)
    print()
    
    results = {
        'Conexión BD': test_database_connection(),
        'Tablas': test_tables_exist(),
        'Variables Env': test_environment_variables(),
        'Datos Prueba': test_sample_data(),
        'API Endpoints': test_api_endpoints(),
    }
    
    print("\n" + "=" * 60)
    print("📊 RESUMEN DE PRUEBAS")
    print("=" * 60)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    all_passed = all(results.values())
    
    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 ¡Todas las pruebas pasaron exitosamente!")
        print("✅ Tu backend está correctamente configurado")
        print("=" * 60)
    else:
        print("⚠️  Algunas pruebas fallaron. Revisa los errores arriba.")
        print("=" * 60)
    
    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)