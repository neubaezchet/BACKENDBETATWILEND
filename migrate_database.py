"""
Script de migración de base de datos
Agrega las nuevas columnas a tablas existentes
Ejecutar: python migrate_database.py
"""

from sqlalchemy import text
from app.database import engine, SessionLocal
import os

def migrar_base_datos():
    """Ejecuta migraciones SQL para agregar nuevas columnas"""
    
    print("🔄 Iniciando migración de base de datos...\n")
    
    db = SessionLocal()
    
    try:
        # ========== MIGRACIONES PARA TABLA EMPLOYEES ==========
        print("📊 Migrando tabla 'employees'...")
        
        migraciones_employees = [
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS jefe_nombre VARCHAR(200);",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS jefe_email VARCHAR(200);",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS jefe_cargo VARCHAR(100);",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS area_trabajo VARCHAR(100);",
            # ✅ NUEVAS COLUMNAS KACTUS
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS cargo VARCHAR(150);",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS centro_costo VARCHAR(100);",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS fecha_ingreso TIMESTAMP;",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS tipo_contrato VARCHAR(50);",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS dias_kactus INTEGER;",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS ciudad VARCHAR(100);"
        ]
        
        for sql in migraciones_employees:
            try:
                db.execute(text(sql))
                db.commit()
                print(f"  ✅ {sql.split('ADD COLUMN')[1].split()[2] if 'ADD COLUMN' in sql else 'OK'}")
            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                    print(f"  ⚠️ Columna ya existe, omitiendo...")
                else:
                    print(f"  ❌ Error: {e}")
                db.rollback()
        
        # ========== MIGRACIONES PARA TABLA CASES ==========
        print("\n📊 Migrando tabla 'cases'...")
        
        migraciones_cases = [
            "ALTER TABLE cases ADD COLUMN IF NOT EXISTS recordatorio_enviado BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE cases ADD COLUMN IF NOT EXISTS fecha_recordatorio TIMESTAMP;",
            # ✅ NUEVAS COLUMNAS KACTUS
            "ALTER TABLE cases ADD COLUMN IF NOT EXISTS codigo_cie10 VARCHAR(20);",
            "ALTER TABLE cases ADD COLUMN IF NOT EXISTS dias_kactus INTEGER;",
            "ALTER TABLE cases ADD COLUMN IF NOT EXISTS es_prorroga BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE cases ADD COLUMN IF NOT EXISTS numero_incapacidad VARCHAR(50);",
            "ALTER TABLE cases ADD COLUMN IF NOT EXISTS medico_tratante VARCHAR(200);",
            "ALTER TABLE cases ADD COLUMN IF NOT EXISTS institucion_origen VARCHAR(200);"
        ]
        
        for sql in migraciones_cases:
            try:
                db.execute(text(sql))
                db.commit()
                print(f"  ✅ {sql.split('ADD COLUMN')[1].split()[2] if 'ADD COLUMN' in sql else 'OK'}")
            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                    print(f"  ⚠️ Columna ya existe, omitiendo...")
                else:
                    print(f"  ❌ Error: {e}")
                db.rollback()
        
        # ========== VERIFICAR MIGRACIONES ==========
        print("\n🔍 Verificando migraciones...")
        
        # Verificar employees
        result_employees = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='employees' 
            AND column_name IN ('jefe_nombre', 'jefe_email', 'jefe_cargo', 'area_trabajo',
                                'cargo', 'centro_costo', 'fecha_ingreso', 'tipo_contrato', 'dias_kactus', 'ciudad');
        """))
        columnas_employees = [row[0] for row in result_employees]
        
        if len(columnas_employees) == 10:
            print(f"  ✅ Tabla 'employees': 10/10 columnas nuevas OK")
        else:
            print(f"  ⚠️ Tabla 'employees': {len(columnas_employees)}/10 columnas encontradas")
        
        # Verificar cases
        result_cases = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='cases' 
            AND column_name IN ('recordatorio_enviado', 'fecha_recordatorio',
                                'codigo_cie10', 'dias_kactus', 'es_prorroga', 'numero_incapacidad', 'medico_tratante', 'institucion_origen');
        """))
        columnas_cases = [row[0] for row in result_cases]
        
        if len(columnas_cases) == 8:
            print(f"  ✅ Tabla 'cases': 8/8 columnas nuevas OK")
        else:
            print(f"  ⚠️ Tabla 'cases': {len(columnas_cases)}/8 columnas encontradas")
        
        print("\n✅ Migración completada exitosamente\n")
        
    except Exception as e:
        print(f"\n❌ Error general en migración: {e}")
        db.rollback()
    finally:
        db.close()


def verificar_estructura():
    """Verifica la estructura completa de las tablas"""
    
    print("🔍 Verificando estructura de base de datos...\n")
    
    db = SessionLocal()
    
    try:
        # Verificar employees
        print("📋 Estructura de 'employees':")
        result = db.execute(text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name='employees'
            ORDER BY ordinal_position;
        """))
        
        for row in result:
            print(f"  • {row[0]}: {row[1]}")
        
        # Verificar cases
        print("\n📋 Estructura de 'cases':")
        result = db.execute(text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name='cases'
            ORDER BY ordinal_position;
        """))
        
        for row in result:
            print(f"  • {row[0]}: {row[1]}")
        
        print("\n✅ Verificación completada\n")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    print("""
╔═══════════════════════════════════════════════════════════╗
║     MIGRACIÓN DE BASE DE DATOS - IncaNeurobaeza v3.0     ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    # Verificar que estamos conectados a PostgreSQL
    database_url = os.environ.get("DATABASE_URL", "")
    
    if "postgresql" not in database_url and "postgres" not in database_url:
        print("⚠️ ADVERTENCIA: No se detectó PostgreSQL")
        print(f"   DATABASE_URL: {database_url[:50]}...")
        respuesta = input("\n¿Continuar de todos modos? (s/n): ")
        if respuesta.lower() != 's':
            print("Migración cancelada")
            exit()
    
    print(f"\n📊 Base de datos: {database_url.split('@')[1] if '@' in database_url else 'Local'}\n")
    
    # Ejecutar migraciones
    migrar_base_datos()
    
    # Verificar
    verificar_estructura()
    
    print("""
╔═══════════════════════════════════════════════════════════╗
║  🎉 Migración completada. Ya puedes desplegar el backend ║
╚═══════════════════════════════════════════════════════════╝
    """)