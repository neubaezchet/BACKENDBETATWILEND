"""
Migration Script - Add Missing Columns to Cases Table
Adds: intentos_incompletos, fecha_ultimo_incompleto
"""

import os
import sys
from sqlalchemy import create_engine, text
from datetime import datetime

# Import DB config
sys.path.insert(0, os.path.dirname(__file__))

def get_db_url():
    """Get database URL from environment"""
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        raise ValueError("DATABASE_URL env var not set!")
    # Railway uses postgresql://, convert to psycopg2 driver
    if db_url.startswith('postgresql://'):
        db_url = db_url.replace('postgresql://', 'postgresql+psycopg2://', 1)
    return db_url

def run_migration():
    """Run migration"""
    try:
        db_url = get_db_url()
        engine = create_engine(db_url, echo=True)
        
        with engine.connect() as conn:
            # Check if columns already exist
            print("\n🔍 Checking if columns exist...")
            
            check_query = text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='cases' 
                AND column_name IN ('intentos_incompletos', 'fecha_ultimo_incompleto')
            """)
            result = conn.execute(check_query).fetchall()
            
            if len(result) == 2:
                print("✅ Both columns already exist! Migration skipped.")
                return True
            
            # Add intentos_incompletos column
            if not any(col[0] == 'intentos_incompletos' for col in result):
                print("\n➕ Adding intentos_incompletos column...")
                conn.execute(text("""
                    ALTER TABLE cases 
                    ADD COLUMN intentos_incompletos INTEGER DEFAULT 0
                """))
                print("✅ Added intentos_incompletos")
            
            # Add fecha_ultimo_incompleto column
            if not any(col[0] == 'fecha_ultimo_incompleto' for col in result):
                print("\n➕ Adding fecha_ultimo_incompleto column...")
                conn.execute(text("""
                    ALTER TABLE cases 
                    ADD COLUMN fecha_ultimo_incompleto TIMESTAMP NULL
                """))
                print("✅ Added fecha_ultimo_incompleto")
            
            conn.commit()
            print("\n✅ Migration completed successfully!")
            return True
            
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
