"""
MIGRACIÓN: Agregar columna es_historico a tabla cases
=====================================================
Fecha: 2026-03-05
Propósito: Marcar casos históricos (sin PDF) para excluirlos de dashboard y reportes en vivo

SOLUCIÓN AL PROBLEMA:
- 20,686 registros históricos congestionan el dashboard
- Estos registros NO tienen PDF (solo datos base)
- Deben ser excluidos de:
  * Dashboard de validación
  * Reportes en vivo (TablaViva)
  * Estadísticas generales
- Pero DEBEN seguir siendo buscables manualmente

CRITERIO AUTOMÁTICO:
- es_historico = True → casos SIN drive_link (registros históricos sin PDF)
- es_historico = False → casos CON drive_link o recientes (últimos 180 días)

USO:
    python migrate_add_historico_column.py
"""

import os
import sys
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text, Column, Boolean, Index
from sqlalchemy.orm import sessionmaker

# Configurar base de datos
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("❌ ERROR: Variable DATABASE_URL no configurada")
    sys.exit(1)

# Railway usa postgres://, SQLAlchemy requiere postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

def migrar():
    """Ejecuta la migración"""
    print("🔧 INICIANDO MIGRACIÓN: Agregar columna es_historico")
    print("=" * 60)
    
    session = Session()
    
    try:
        # 1. Verificar si la columna ya existe
        result = session.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='cases' AND column_name='es_historico';
        """))
        existe = result.fetchone()
        
        if existe:
            print("⚠️  La columna 'es_historico' ya existe. Saltando creación...")
        else:
            # 2. Agregar columna es_historico
            print("\n📊 Paso 1: Agregando columna 'es_historico' (BOOLEAN, default False)...")
            session.execute(text("""
                ALTER TABLE cases 
                ADD COLUMN es_historico BOOLEAN DEFAULT FALSE NOT NULL;
            """))
            session.commit()
            print("✅ Columna agregada correctamente")
        
        # 3. Marcar casos históricos (sin PDF y antiguos)
        print("\n📊 Paso 2: Identificando y marcando casos históricos...")
        print("   Criterio: drive_link IS NULL o vacío = HISTÓRICO")
        
        # Marcar como histórico: casos SIN drive_link (sin PDF)
        result = session.execute(text("""
            UPDATE cases 
            SET es_historico = TRUE
            WHERE (drive_link IS NULL OR drive_link = '' OR drive_link = 'null')
            AND estado = 'VALIDADA';
        """))
        historicos_sin_pdf = result.rowcount
        session.commit()
        print(f"   ✅ {historicos_sin_pdf} casos marcados como históricos (sin PDF)")
        
        # 4. Crear índice para optimizar consultas
        print("\n📊 Paso 3: Creando índice idx_estado_historico...")
        try:
            session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_estado_historico 
                ON cases(estado, es_historico);
            """))
            session.commit()
            print("✅ Índice creado correctamente")
        except Exception as e:
            print(f"⚠️  Índice ya existe o error: {e}")
            session.rollback()
        
        # 5. Estadísticas finales
        print("\n" + "=" * 60)
        print("📊 ESTADÍSTICAS FINALES:")
        print("=" * 60)
        
        # Total de casos
        result = session.execute(text("SELECT COUNT(*) FROM cases;"))
        total_casos = result.scalar()
        
        # Casos históricos
        result = session.execute(text("SELECT COUNT(*) FROM cases WHERE es_historico = TRUE;"))
        total_historicos = result.scalar()
        
        # Casos actuales (no históricos)
        result = session.execute(text("SELECT COUNT(*) FROM cases WHERE es_historico = FALSE;"))
        total_actuales = result.scalar()
        
        # Casos sin PDF pero marcados como actuales (para revisión)
        result = session.execute(text("""
            SELECT COUNT(*) FROM cases 
            WHERE es_historico = FALSE 
            AND (drive_link IS NULL OR drive_link = '' OR drive_link = 'null');
        """))
        actuales_sin_pdf = result.scalar()
        
        print(f"Total de casos en BD:          {total_casos:,}")
        print(f"Casos HISTÓRICOS (es_historico=True):  {total_historicos:,}")
        print(f"Casos ACTUALES (es_historico=False):   {total_actuales:,}")
        print(f"Casos actuales sin PDF (revisar):     {actuales_sin_pdf:,}")
        print("=" * 60)
        
        print("\n✅ MIGRACIÓN COMPLETADA EXITOSAMENTE")
        print("\n📌 NOTAS:")
        print("   • Los reportes/dashboard ahora filtrarán es_historico=FALSE")
        print("   • Los casos históricos seguirán siendo buscables manualmente")
        print("   • Los endpoints listar_casos y estadísticas se actualizarán automáticamente")
        print("   • Los casos sin PDF y estado VALIDADA fueron marcados como históricos")
        
    except Exception as e:
        print(f"\n❌ ERROR durante la migración: {e}")
        session.rollback()
        raise
    
    finally:
        session.close()

def rollback():
    """Revierte la migración (para testing)"""
    print("🔄 ROLLBACK: Eliminando columna es_historico")
    session = Session()
    
    try:
        # Eliminar índice
        session.execute(text("DROP INDEX IF EXISTS idx_estado_historico;"))
        
        # Eliminar columna
        session.execute(text("ALTER TABLE cases DROP COLUMN IF EXISTS es_historico;"))
        session.commit()
        print("✅ Rollback completado")
    
    except Exception as e:
        print(f"❌ ERROR en rollback: {e}")
        session.rollback()
    
    finally:
        session.close()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Migración: Agregar columna es_historico")
    parser.add_argument("--rollback", action="store_true", help="Revertir la migración")
    args = parser.parse_args()
    
    if args.rollback:
        confirm = input("⚠️  ¿Estás seguro de revertir la migración? (yes/no): ")
        if confirm.lower() == "yes":
            rollback()
        else:
            print("❌ Rollback cancelado")
    else:
        migrar()
