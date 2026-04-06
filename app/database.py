"""
Sistema de Base de Datos - IncaNeurobaeza
Modelos SQLAlchemy para gestión de casos de incapacidades
VERSIÓN 3.0 - Con soporte para jefes y recordatorios
"""

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, ForeignKey, Enum, JSON, text, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os
import enum

# Base para modelos
Base = declarative_base()

# Helper para timestamps - compatible con Python 3.12+
def get_utc_now():
    """Retorna datetime actual en UTC - compatible con Python 3.12+"""
    return datetime.now()


# Enums para estados
class EstadoCaso(str, enum.Enum):
    NUEVO = "NUEVO"
    EN_REVISION = "EN_REVISION"
    INCOMPLETA = "INCOMPLETA"
    ILEGIBLE = "ILEGIBLE"
    INCOMPLETA_ILEGIBLE = "INCOMPLETA_ILEGIBLE"
    EPS_TRANSCRIPCION = "EPS_TRANSCRIPCION"
    DERIVADO_TTHH = "DERIVADO_TTHH"
    CAUSA_EXTRA = "CAUSA_EXTRA"
    COMPLETA = "COMPLETA"
    EN_RADICACION = "EN_RADICACION"

class EstadoDocumento(str, enum.Enum):
    PENDIENTE = "PENDIENTE"
    OK = "OK"
    INCOMPLETO = "INCOMPLETO"
    ILEGIBLE = "ILEGIBLE"

class TipoIncapacidad(str, enum.Enum):
    ENFERMEDAD_GENERAL = "enfermedad_general"
    ENFERMEDAD_LABORAL = "enfermedad_laboral"
    ACCIDENTE_TRANSITO = "accidente_transito"
    ENFERMEDAD_ESPECIAL = "especial"
    MATERNIDAD = "maternidad"
    PATERNIDAD = "paternidad"
    PRELICENCIA = "prelicencia"  # ✅ NUEVO
    CERTIFICADO = "certificado"  # ✅ NUEVO

# ==================== MODELOS ====================

class Company(Base):
    """Empresas registradas en el sistema"""
    __tablename__ = 'companies'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(200), nullable=False, unique=True, index=True)
    nit = Column(String(50), unique=True)
    contacto_email = Column(String(200))
    contacto_telefono = Column(String(50))
    email_copia = Column(String(500))  # ✅ NUEVO: Email de copia
    activa = Column(Boolean, default=True)
    created_at = Column(DateTime, default=get_utc_now)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)
    
    # Relaciones con CASCADE
    empleados = relationship("Employee", back_populates="empresa", cascade="all, delete-orphan")
    casos = relationship("Case", back_populates="empresa")

class Employee(Base):
    """Empleados registrados (Base de datos Excel)"""
    __tablename__ = 'employees'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    cedula = Column(String(50), nullable=False, unique=True, index=True)
    nombre = Column(String(200), nullable=False, index=True)
    correo = Column(String(200))
    telefono = Column(String(50))
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    eps = Column(String(100))
    activo = Column(Boolean, default=True)
    
    # ✅ NUEVAS COLUMNAS - Información de jefes
    jefe_nombre = Column(String(200))
    jefe_email = Column(String(200))
    jefe_cargo = Column(String(100))
    area_trabajo = Column(String(100))
    
    # ✅ COLUMNAS KACTUS - Datos adicionales del empleado
    cargo = Column(String(150))
    centro_costo = Column(String(100))
    fecha_ingreso = Column(DateTime, nullable=True)
    tipo_contrato = Column(String(50))
    ciudad = Column(String(100))
    
    created_at = Column(DateTime, default=get_utc_now)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)
    
    # Relaciones
    empresa = relationship("Company", back_populates="empleados")
    casos = relationship("Case", back_populates="empleado")

class Case(Base):
    """Casos de incapacidad registrados"""
    __tablename__ = 'cases'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    serial = Column(String(50), nullable=False, unique=True, index=True)
    cedula = Column(String(50), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey('employees.id', ondelete='SET NULL'), nullable=True)
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='SET NULL'), nullable=True)
    
    # Datos del caso
    tipo = Column(Enum(TipoIncapacidad), nullable=False)
    subtipo = Column(String(100))
    dias_incapacidad = Column(Integer)
    estado = Column(Enum(EstadoCaso), default=EstadoCaso.NUEVO, index=True)
    
    # Metadata adicional (JSON para flexibilidad)
    metadata_form = Column(JSON)
    
    # Campos adicionales de búsqueda
    eps = Column(String(100), index=True)
    fecha_inicio = Column(DateTime, index=True)
    fecha_fin = Column(DateTime, index=True)
    diagnostico = Column(Text)
    
    # Control de flujo
    bloquea_nueva = Column(Boolean, default=False)
    drive_link = Column(String(500))
    email_form = Column(String(200))
    telefono_form = Column(String(50))
    
    # ✅ COLUMNAS - Rastreo de intentos incompletos
    intentos_incompletos = Column(Integer, default=0)  # Contador: cuántas veces se marcó como INCOMPLETA/ILEGIBLE
    fecha_ultimo_incompleto = Column(DateTime, nullable=True)  # Última fecha que se marcó como incompleta
    
    # ✅ NUEVAS COLUMNAS - Sistema de recordatorios
    recordatorio_enviado = Column(Boolean, default=False)
    fecha_recordatorio = Column(DateTime, nullable=True)
    recordatorios_count = Column(Integer, default=0)  # Contador: 0=ninguno, 1=3días, 2=5días+jefe
    
    # ✅ COLUMNAS KACTUS - Datos de Kactus / validación
    codigo_cie10 = Column(String(20))
    es_prorroga = Column(Boolean, default=False)
    numero_incapacidad = Column(String(50))
    # dias_kactus, medico_tratante, institucion_origen, diagnostico_kactus eliminados - no vienen del Excel Kactus
    
    # ✅ COLUMNA HISTÓRICO - Marca casos históricos que no deben aparecer en dashboard/reportes en vivo
    es_historico = Column(Boolean, default=False, index=True)  # True = registro histórico (sin PDF), False = actual (con PDF)
    
    # ✅ COLUMNAS TRASLAPO - Fechas ajustadas Kactus y detección de solapamiento
    fecha_inicio_kactus = Column(DateTime, nullable=True)
    fecha_fin_kactus = Column(DateTime, nullable=True)
    dias_traslapo = Column(Integer, default=0)
    traslapo_con_serial = Column(String(50), nullable=True)
    kactus_sync_at = Column(DateTime, nullable=True)  # Cuándo se sincronizó este caso con Kactus
    
    # ✅ COLUMNAS PROCESADO - Tracking para Excel exports
    procesado = Column(Boolean, default=False)  # True = caso ya procesado/eliminado en flujo manual
    fecha_procesado = Column(DateTime, nullable=True)  # Cuándo se marcó como procesado
    usuario_procesado = Column(String(200), nullable=True)  # Quién procesó el caso
    
    # Auditoría
    created_at = Column(DateTime, default=get_utc_now, index=True)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)
    
    # Relaciones
    empleado = relationship("Employee", back_populates="casos")
    empresa = relationship("Company", back_populates="casos")
    documentos = relationship("CaseDocument", back_populates="caso", cascade="all, delete-orphan")
    eventos = relationship("CaseEvent", back_populates="caso", cascade="all, delete-orphan")
    notas = relationship("CaseNote", back_populates="caso", cascade="all, delete-orphan")
    
    # ✅ Índice compuesto para búsquedas por cédula + fecha
    __table_args__ = (
        Index('idx_cedula_fecha_inicio', 'cedula', 'fecha_inicio'),
        Index('idx_cedula_fecha_estado', 'cedula', 'fecha_inicio', 'estado'),
        Index('idx_estado_historico', 'estado', 'es_historico'),  # Índice para filtrar dashboard/reportes
        Index('idx_procesado', 'procesado'),  # Índice para encontrar casos no procesados rápidamente
    )

class CaseDocument(Base):
    """Documentos asociados a un caso"""
    __tablename__ = 'case_documents'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey('cases.id', ondelete='CASCADE'), nullable=False)
    
    doc_tipo = Column(String(100), nullable=False)
    requerido = Column(Boolean, default=True)
    estado_doc = Column(Enum(EstadoDocumento), default=EstadoDocumento.PENDIENTE)
    
    # Múltiples versiones (array de URLs)
    drive_urls = Column(JSON)
    version_actual = Column(Integer, default=1)
    
    observaciones = Column(Text)
    calidad_validada = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=get_utc_now)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)
    
    # Relaciones
    caso = relationship("Case", back_populates="documentos")

class CaseEvent(Base):
    """Historial de eventos/cambios de un caso"""
    __tablename__ = 'case_events'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey('cases.id', ondelete='CASCADE'), nullable=False)
    
    actor = Column(String(200))
    accion = Column(String(100), nullable=False)
    estado_anterior = Column(String(50))
    estado_nuevo = Column(String(50))
    motivo = Column(Text)
    metadata_json = Column(JSON)
    
    created_at = Column(DateTime, default=get_utc_now, index=True)
    
    # Relaciones
    caso = relationship("Case", back_populates="eventos")

class CaseNote(Base):
    """Notas rápidas en casos"""
    __tablename__ = 'case_notes'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey('cases.id', ondelete='CASCADE'), nullable=False)
    
    autor = Column(String(200))
    contenido = Column(Text, nullable=False)
    es_importante = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=get_utc_now, index=True)
    
    # Relaciones
    caso = relationship("Case", back_populates="notas")

class SearchHistory(Base):
    """Historial de búsquedas relacionales"""
    __tablename__ = 'search_history'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    usuario = Column(String(200))
    tipo_busqueda = Column(String(50))
    parametros_json = Column(JSON)
    resultados_count = Column(Integer)
    archivo_nombre = Column(String(200))
    
    created_at = Column(DateTime, default=get_utc_now, index=True)


# ==================== CORREOS DE NOTIFICACIÓN POR ÁREA ====================

class CorreoNotificacion(Base):
    """
    Correos de notificación por área/departamento.
    Se gestionan manualmente desde el panel admin o API.
    
    NOTA: Los emails CC por empresa están en companies.email_copia (directorio).
    Esta tabla es para correos adicionales por área específica.
    """
    __tablename__ = 'correos_notificacion'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    area = Column(String(50), nullable=False, index=True)  # talento_humano | seguridad_salud | nomina | incapacidades
    nombre_contacto = Column(String(200))
    email = Column(String(300), nullable=False)
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=True)
    activo = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=get_utc_now)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)
    
    # Relación opcional con empresa (NULL = aplica a todas las empresas)
    empresa = relationship("Company", backref="correos_notificacion")


# ==================== MODELOS CIE-10 / ALERTAS 180 ====================

class AlertaEmail(Base):
    """
    Correos para recibir alertas de 180 días por empresa.
    Permite configurar múltiples destinatarios por cada compañía.
    
    Tipos:
    - talento_humano: correo principal de TTHH de la empresa
    - adicional: correos extra que el admin quiera agregar
    """
    __tablename__ = 'alerta_emails'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=True)
    
    email = Column(String(300), nullable=False)
    nombre_contacto = Column(String(200))
    tipo = Column(String(50), default='talento_humano')  # talento_humano | adicional | admin
    activo = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=get_utc_now)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)
    
    # Relación opcional con empresa (NULL = alerta global para todas las empresas)
    empresa = relationship("Company", backref="alerta_emails")


class AdminUser(Base):
    """
    Usuarios administrativos del portal admin.
    Roles: superadmin | admin | th | sst | nomina | viewer
    """
    __tablename__ = 'admin_users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), nullable=False, unique=True, index=True)
    password_hash = Column(String(300), nullable=False)
    nombre = Column(String(200))
    email = Column(String(300))
    rol = Column(String(50), nullable=False, default='viewer')  # superadmin | admin | th | sst | nomina | viewer
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='SET NULL'), nullable=True)
    permisos = Column(JSON, default=dict)  # {"validador": true, "reportes": true, "powerbi": true, ...}
    activo = Column(Boolean, default=True)
    ultimo_login = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=get_utc_now)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)
    
    empresa = relationship("Company", backref="admin_users")


class Alerta180Log(Base):
    """
    Log de alertas 180 días enviadas.
    Evita enviar la misma alerta repetidamente.
    """
    __tablename__ = 'alertas_180_log'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    cedula = Column(String(30), nullable=False, index=True)
    tipo_alerta = Column(String(50), nullable=False)        # ALERTA_TEMPRANA | ALERTA_CRITICA | LIMITE_180_SUPERADO
    dias_acumulados = Column(Integer)
    cadena_codigos_cie10 = Column(String(500))               # Códigos involucrados
    emails_enviados = Column(Text)                           # Lista de correos notificados
    
    enviado_ok = Column(Boolean, default=False)
    created_at = Column(DateTime, default=get_utc_now, index=True)


class PendienteEnvio(Base):
    """
    Cola persistente de envíos fallidos (Notificaciones y Drive).
    Cuando falla una notificación o Drive falla por token,
    los envíos se guardan aquí para reintentar automáticamente.
    """
    __tablename__ = "pendientes_envio"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    tipo = Column(String(20), nullable=False)    # 'drive' o 'notificacion'
    payload = Column(JSONB, nullable=False)       # Info del archivo/correo pendiente
    intentos = Column(Integer, default=0)
    ultimo_error = Column(String(500), nullable=True)
    creado_en = Column(DateTime, default=get_utc_now)
    actualizado_en = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)
    procesado = Column(Boolean, default=False)

# ==================== FUNCIONES DE INICIALIZACIÓN ====================

def get_database_url():
    """Obtiene la URL de la base de datos desde variables de entorno"""
    database_url = os.environ.get("DATABASE_URL") or os.environ.get("RENDER_URL")
    
    if not database_url:
        database_url = "sqlite:///./incapacidades.db"
        print("⚠️ Usando SQLite (desarrollo). Configura DATABASE_URL para producción.")
    
    # Render usa postgres:// pero SQLAlchemy necesita postgresql://
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    
    return database_url

# Configuración del motor
database_url = get_database_url()

if database_url.startswith("sqlite"):
    # SQLite para desarrollo
    engine = create_engine(
        database_url,
        echo=False,
        connect_args={"check_same_thread": False}
    )
else:
    # PostgreSQL para producción
    engine = create_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_size=10,
        max_overflow=20,
        connect_args={
            "connect_timeout": 10,
            "options": "-c timezone=America/Bogota"
        }
    )

# Sesión
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Crea todas las tablas en la base de datos"""
    try:
        # ✅ CREAR TODAS LAS TABLAS FALTANTES
        Base.metadata.create_all(bind=engine)
        print("✅ Base de datos inicializada correctamente")
        
        # ✅ VERIFICAR QUE TABLAS CRÍTICAS EXISTAN
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tablas_existentes = inspector.get_table_names()
        
        tablas_requeridas = [
            'correos_notificacion',  # CRÍTICO: Directorio de emails
            'admin_users',           # CRÍTICO: Usuarios admin
            'alerta_emails',         # Alertas 180
            'alertas_180_log',       # Log de alertas 180
        ]
        
        for tabla in tablas_requeridas:
            if tabla in tablas_existentes:
                print(f"   ✅ Tabla '{tabla}' existe")
            else:
                print(f"   ⚠️ TABLA FALTANTE: '{tabla}' - intentando crear...")
                # Forzar creación específica
                Base.metadata.create_all(bind=engine, checkfirst=True)
        
        print(f"📊 Total tablas en BD: {len(tablas_existentes)}: {', '.join(sorted(tablas_existentes))}")
        
        # Verificar conexión
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            if database_url.startswith("postgresql"):
                print("✅ Conexión a PostgreSQL exitosa")
            else:
                print("✅ Conexión a SQLite exitosa")
        finally:
            db.close()
            
    except Exception as e:
        print(f"❌ Error inicializando base de datos: {e}")
        raise

def get_db():
    """Dependency para FastAPI - Obtiene sesión de BD"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==================== MIGRACIÓN Y VERIFICACIÓN DE COLUMNAS ====================

def verificar_columnas_fechas():
    """
    Script para verificar si las columnas de fechas ya existen en la tabla cases
    Ejecutar antes de migrar para validar el estado actual
    """
    from sqlalchemy import inspect
    
    try:
        inspector = inspect(engine)
        columns = inspector.get_columns('cases')
        
        tiene_fecha_inicio = any(c['name'] == 'fecha_inicio' for c in columns)
        tiene_fecha_fin = any(c['name'] == 'fecha_fin' for c in columns)
        tiene_eps = any(c['name'] == 'eps' for c in columns)
        
        print("📋 Estado de columnas en tabla 'cases':")
        print(f"   eps: {'✅ Existe' if tiene_eps else '❌ No existe'}")
        print(f"   fecha_inicio: {'✅ Existe' if tiene_fecha_inicio else '❌ No existe'}")
        print(f"   fecha_fin: {'✅ Existe' if tiene_fecha_fin else '❌ No existe'}")
        
        if tiene_fecha_inicio and tiene_fecha_fin and tiene_eps:
            print("\n✅ Todo listo, todas las columnas están presentes")
            return True
        else:
            print("\n⚠️ Faltan columnas. Debes ejecutar la migración SQL")
            return False
            
    except Exception as e:
        print(f"❌ Error verificando columnas: {e}")
        return False

def migrar_columnas_fechas():
    """
    Ejecuta la migración SQL para agregar las columnas de fechas
    EJECUTAR SOLO UNA VEZ - Agrega columnas y sus índices a la tabla cases
    
    Para PostgreSQL:
        - Agrega columna fecha_inicio como DATE
        - Agrega columna fecha_fin como DATE
        - Crea índices para optimizar búsquedas
    
    Para SQLite:
        - Agrega las columnas (SQLite no tiene control estricto de tipos)
    """
    try:
        db = SessionLocal()
        
        print("🔄 Iniciando migración de columnas...")
        
        # Verificar primero si las columnas ya existen
        if verificar_columnas_fechas():
            print("\n✅ No es necesario migrar, las columnas ya existen")
            db.close()
            return True
        
        # Ejecutar migraciones
        try:
            db.execute(text("ALTER TABLE cases ADD COLUMN IF NOT EXISTS eps VARCHAR(100)"))
            print("✅ Columna 'eps' agregada")
        except Exception as e:
            print(f"⚠️ eps: {e}")
        
        try:
            # Intenta agregar como DATE (PostgreSQL)
            db.execute(text("ALTER TABLE cases ADD COLUMN IF NOT EXISTS fecha_inicio DATE"))
            print("✅ Columna 'fecha_inicio' agregada como DATE")
        except Exception:
            # Si falla, intenta como DateTime (SQLite)
            try:
                db.execute(text("ALTER TABLE cases ADD COLUMN IF NOT EXISTS fecha_inicio DATETIME"))
                print("✅ Columna 'fecha_inicio' agregada como DATETIME")
            except:
                print("⚠️ No se pudo agregar fecha_inicio")
        
        try:
            # Intenta agregar como DATE (PostgreSQL)
            db.execute(text("ALTER TABLE cases ADD COLUMN IF NOT EXISTS fecha_fin DATE"))
            print("✅ Columna 'fecha_fin' agregada como DATE")
        except Exception:
            # Si falla, intenta como DateTime (SQLite)
            try:
                db.execute(text("ALTER TABLE cases ADD COLUMN IF NOT EXISTS fecha_fin DATETIME"))
                print("✅ Columna 'fecha_fin' agregada como DATETIME")
            except:
                print("⚠️ No se pudo agregar fecha_fin")
        
        # Crear índices (si la BD lo soporta)
        try:
            db.execute(text("CREATE INDEX IF NOT EXISTS idx_cases_eps ON cases(eps)"))
            print("✅ Índice en 'eps' creado")
        except:
            pass
        
        try:
            db.execute(text("CREATE INDEX IF NOT EXISTS idx_cases_fecha_inicio ON cases(fecha_inicio)"))
            print("✅ Índice en 'fecha_inicio' creado")
        except:
            pass
        
        try:
            db.execute(text("CREATE INDEX IF NOT EXISTS idx_cases_fecha_fin ON cases(fecha_fin)"))
            print("✅ Índice en 'fecha_fin' creado")
        except:
            pass
        
        db.commit()
        print("\n✅ Migración completada exitosamente")
        db.close()
        return True
        
    except Exception as e:
        print(f"\n❌ Error en la migración: {e}")
        db.rollback()
        db.close()
        return False

# ==================== PUNTO DE ENTRADA PARA MIGRACIÓN ====================

if __name__ == "__main__":
    print("=" * 60)
    print("HERRAMIENTAS DE VERIFICACIÓN Y MIGRACIÓN - database.py")
    print("=" * 60)
    print("\nOpciones disponibles:")
    print("  1. Verificar columnas (python database.py verify)")
    print("  2. Migrar columnas (python database.py migrate)")
    print("  3. Inicializar BD (python database.py init)")
    
    import sys
    
    if len(sys.argv) > 1:
        comando = sys.argv[1].lower()
        
        if comando == "verify":
            print("\n🔍 Verificando estado de columnas...")
            verificar_columnas_fechas()
            
        elif comando == "migrate":
            print("\n⚠️ ADVERTENCIA: Esta operación modificará la base de datos")
            print("Asegúrate de tener una copia de seguridad antes de continuar\n")
            confirmacion = input("¿Deseas continuar? (si/no): ").strip().lower()
            if confirmacion in ['si', 'yes', 'y']:
                migrar_columnas_fechas()
            else:
                print("Migración cancelada")
                
        elif comando == "init":
            print("\n🔨 Inicializando base de datos...")
            init_db()
            
        else:
            print(f"\n❌ Comando desconocido: {comando}")
    else:
        print("\nUso: python database.py [verify|migrate|init]")
        print("\nEjemplos:")
        print("  python database.py verify    # Verifica columnas")
        print("  python database.py migrate   # Ejecuta migración")
        print("  python database.py init      # Inicializa BD")