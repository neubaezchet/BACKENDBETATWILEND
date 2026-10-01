"""
Sistema de Base de Datos - IncaNeurobaeza
Modelos SQLAlchemy para gestión de casos de incapacidades
VERSIÓN 3.0 - Con soporte para jefes y recordatorios
"""

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Date, Boolean, Text, ForeignKey, Enum, JSON, text, Index, Float, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os
import enum

try:
    from pgvector.sqlalchemy import Vector
    PGVECTOR_INSTALADO = True
except ImportError:
    # Paquete no instalado (p.ej. entorno viejo sin requirements actualizados).
    # Las columnas de embeddings quedan sin tipo vectorial real; el servicio de
    # calificación IA detecta esto y cae a modo "sin búsqueda semántica".
    PGVECTOR_INSTALADO = False
    Vector = lambda dim: JSON  # noqa: E731 - fallback de tipo, nunca se usa en producción

# Dimensión de embeddings: gemini-embedding-001 con output_dimensionality=768
# (ver app/embeddings_service.py). Cambiar aquí obliga a re-embeber todo lo existente.
EMBEDDING_DIM = 768

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
    PRELICENCIA = "prelicencia"
    CERTIFICADO = "certificado"
    OTHER = "other"  # ✅ Para tipos no mapeados

class DecisionValidacion(str, enum.Enum):
    """Decisiones de validación de incapacidades con IA"""
    ACEPTAR = "ACEPTAR"
    RECHAZAR = "RECHAZAR"
    REVISAR = "REVISAR"

# ==================== MODELOS ====================

class Company(Base):
    """Empresas registradas en el sistema"""
    __tablename__ = 'companies'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(200), nullable=False, unique=True, index=True)
    slug = Column(String(120), unique=True, index=True, nullable=True)  # URL por empresa: repogemin.vercel.app/?empresa={slug}
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

def slugify_empresa(nombre: str) -> str:
    """Convierte un nombre de empresa en slug para URL: 'Mi Empresa S.A.S' → 'mi-empresa-s-a-s'."""
    import re
    import unicodedata
    s = unicodedata.normalize('NFKD', nombre or '').encode('ascii', 'ignore').decode()
    s = re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')
    return s[:100] or 'empresa'


def asignar_slug(db, company) -> str:
    """Asigna un slug único a la Company (agrega sufijo -2, -3... si ya existe). No hace commit."""
    base = slugify_empresa(company.nombre)
    slug = base
    i = 2
    while db.query(Company).filter(Company.slug == slug, Company.id != company.id).first():
        slug = f"{base}-{i}"
        i += 1
    company.slug = slug
    return slug


class Employee(Base):
    """Empleados registrados (Base de datos Excel)"""
    __tablename__ = 'employees'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    # ✅ MULTI-TENANT: la cédula es única POR EMPRESA (no global) — el mismo
    # empleado puede existir en dos empresas cliente sin mezclar datos.
    cedula = Column(String(50), nullable=False, index=True)
    nombre = Column(String(200), nullable=False, index=True)
    correo = Column(String(200))
    telefono = Column(String(50))
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    eps = Column(String(100))
    activo = Column(Boolean, default=True)

    # ✅ Verificación mensual de EPS (CoreSoft / ADRES-BDUA) — ver app/services/eps_verificacion.py
    # eps_anterior solo se llena cuando la verificación detecta un cambio real.
    eps_anterior = Column(String(100), nullable=True)
    eps_actualizado_en = Column(DateTime, nullable=True)
    # Se sella en CADA verificación exitosa, cambie o no la EPS: sin esto no hay
    # manera de saber si el dato está fresco (eps_actualizado_en solo se llena
    # cuando hubo cambio, así que un empleado nunca verificado y uno verificado
    # ayer sin novedad se veían idénticos).
    eps_verificado_en = Column(DateTime, nullable=True)
    # Datos informativos de BDUA, se refrescan en cada verificación (cambie o no la EPS)
    eps_regimen = Column(String(50), nullable=True)
    eps_estado = Column(String(50), nullable=True)
    eps_tipo_afiliado = Column(String(50), nullable=True)
    eps_fecha_afiliacion = Column(Date, nullable=True)

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

    __table_args__ = (
        UniqueConstraint('company_id', 'cedula', name='uq_employee_company_cedula'),
    )

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
    
    # ✅ PAGO RECONOCIDO POR LA EPS (viene del recobro — ver app/services/recobro_service.py)
    # Si la EPS ya pagó la incapacidad, deja de tener sentido seguir pidiéndole
    # soportes al colaborador: el dinero ya entró. Esta marca cierra el ciclo de
    # recordatorios aunque al caso le faltara un soporte mínimo.
    pago_eps_reconocido = Column(Boolean, default=False, index=True)
    pago_eps_en = Column(DateTime, nullable=True)
    pago_eps_valor = Column(Float, nullable=True)
    pago_eps_radicado = Column(String(100), nullable=True)

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


# ==================== CENTRO DE COSTOS — SERVICIOS Y SUSCRIPCIONES PAGAS ====================
# Ver app/routes/servicios_pago.py y app/tasks/servicios_pago_alertas.py

class ServicioPago(Base):
    """
    Inventario centralizado de todos los servicios/APIs pagos que Sebastián debe
    pagar (Google Workspace, Mistral, Gemini, GLM, Anthropic, Browserbase, CoreSoft,
    Replicate, ICD API, Railway, WhatsApp Business, OneDrive, etc.)

    NO consolida el pago real (cada proveedor cobra por su lado a la tarjeta) —
    es el panel único de seguimiento + alertas antes de que algo se venza,
    se agote o suba de precio.
    """
    __tablename__ = 'servicios_pago'

    id = Column(Integer, primary_key=True, autoincrement=True)

    nombre = Column(String(150), nullable=False)         # "Google Workspace", "Anthropic Claude API"...
    proveedor = Column(String(150), nullable=True)        # "Google", "Anthropic", "Meta"...
    categoria = Column(String(50), nullable=False, default='otros')
    # categoria: ia | infraestructura | comunicaciones | almacenamiento | desarrollo | otros

    costo_mensual = Column(Float, nullable=True)          # estimado/actual en la moneda de abajo
    moneda = Column(String(10), nullable=False, default='COP')  # COP | USD
    ciclo_facturacion = Column(String(20), nullable=False, default='mensual')  # mensual | anual

    fecha_proximo_cobro = Column(Date, nullable=True)     # próxima fecha de cobro/renovación
    dia_cobro = Column(Integer, nullable=True)             # día del mes en que cobra (1-31), informativo

    metodo_pago = Column(String(150), nullable=True)      # "Tarjeta •••• 1234", texto libre
    url_panel = Column(String(500), nullable=True)        # link al dashboard de facturación del proveedor

    estado = Column(String(20), nullable=False, default='activo')
    # estado: activo | en_riesgo | suspendido | cancelado | pendiente (aún no contratado)

    # Verificación programática de saldo/crédito restante (solo para servicios medidos)
    tipo_verificacion = Column(String(30), nullable=False, default='ninguna')
    # tipo_verificacion: ninguna | coresoft_creditos | browserbase_uso | railway_uso
    umbral_alerta_dias = Column(Integer, nullable=False, default=5)      # avisar X días antes del cobro
    umbral_alerta_credito_pct = Column(Integer, nullable=False, default=15)  # avisar si queda < X% de crédito

    email_alertas = Column(String(500), nullable=True)     # correos separados por coma; vacío = usar default
    whatsapp_alertas = Column(String(100), nullable=True)  # número E.164 opcional para alertas por WhatsApp

    notas = Column(Text, nullable=True)
    activo = Column(Boolean, default=True)  # false = archivado, ya no se sigue

    creado_en = Column(DateTime, default=get_utc_now)
    actualizado_en = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)


class ServicioPagoHistorial(Base):
    """
    Historial de cambios relevantes de un ServicioPago — principalmente para
    detectar y mostrar cuándo un proveedor subió de precio ("si suben, que me
    avise"). Se registra automáticamente al editar costo_mensual o estado.
    """
    __tablename__ = 'servicios_pago_historial'

    id = Column(Integer, primary_key=True, autoincrement=True)
    servicio_id = Column(Integer, ForeignKey('servicios_pago.id', ondelete='CASCADE'), nullable=False, index=True)

    campo = Column(String(50), nullable=False)     # "costo_mensual" | "estado" | ...
    valor_anterior = Column(String(200), nullable=True)
    valor_nuevo = Column(String(200), nullable=True)

    registrado_en = Column(DateTime, default=get_utc_now)

    servicio = relationship("ServicioPago", backref="historial")


class ServicioPagoAlertaLog(Base):
    """
    Evita reenviar la misma alerta (renovación próxima, crédito bajo, vencido)
    varias veces seguidas — una por servicio+tipo+ciclo.
    """
    __tablename__ = 'servicios_pago_alerta_log'

    id = Column(Integer, primary_key=True, autoincrement=True)
    servicio_id = Column(Integer, ForeignKey('servicios_pago.id', ondelete='CASCADE'), nullable=False, index=True)
    tipo = Column(String(30), nullable=False)  # renovacion_proxima | credito_bajo | vencido | precio_subio
    referencia_ciclo = Column(String(20), nullable=True)  # p.ej. "2026-09" para no repetir en el mismo mes
    enviado_en = Column(DateTime, default=get_utc_now)

    __table_args__ = (
        Index('idx_alerta_servicio_tipo_ciclo', 'servicio_id', 'tipo', 'referencia_ciclo'),
    )


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

    # ✅ MULTI-TENANT: Columnas para gestión por empresa
    es_tenant_admin = Column(Boolean, default=False)  # True = admin de una empresa cliente
    tenant_permisos = Column(JSON, default=dict)      # {"tabla_viva":true,"reportes":true,...}
    invited_by = Column(Integer, nullable=True)       # ID del AdminUser que lo invitó

    created_at = Column(DateTime, default=get_utc_now)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)

    empresa = relationship("Company", backref="admin_users")


# ==================== MULTI-TENANT ====================

class TenantConfig(Base):
    """
    Configuración personalizada de un tenant (empresa cliente).
    Una empresa puede tener exactamente una TenantConfig (relación 1:1).
    """
    __tablename__ = 'tenant_configs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, unique=True)

    # Identidad
    nit = Column(String(50))
    logo_url = Column(Text)  # base64 data URL — sin límite de longitud

    # Personalización visual
    paleta_id = Column(String(50), default='ocean')
    paleta_colores = Column(JSON, default=dict)       # {primary, secondary, accent}
    estilo_ui = Column(String(50), default='default') # default | futurista | minimalista | ux_focus
    # Paleta distinta por portal (opcional). Si un portal no aparece aquí, usa la paleta general.
    # {"admin": {"paleta_id": "...", "colores": {...}}, "portal": {...}, "repogemin": {...}}
    paletas_portales = Column(JSON, default=dict)

    # Estructura
    tipo_estructura = Column(String(20), default='unica')  # unica | holding
    sub_empresas = Column(JSON, default=list)              # lista de nombres si es holding

    # Configuración operativa
    ciclo_reporte = Column(String(20), default='mensual')  # quincenal | mensual
    contacto_email = Column(String(200))
    correo_drive = Column(String(200))
    zona_horaria = Column(String(100), default='America/Bogota')

    # Google Drive (modo LEGACY: cliente pega el ID de SU PROPIA carpeta y el
    # archivo original se sube directo ahí, sin pasar por el histórico de
    # Neurobaeza. Se mantiene por compatibilidad; el flujo nuevo es Entrega.)
    google_workspace_drive_id = Column(String(200))
    drive_verificado = Column(Boolean, default=False)

    # ✅ Storage multi-proveedor — Fase 0 (ver app/entrega_manager.py y
    # app/storage/contract.py). El histórico (Incapacidades/Completas/
    # Incompletas) sigue viviendo SIEMPRE en el Drive de Neurobaeza; Entrega
    # es una copia paralela en la nube de Neurobaeza compartida con el
    # cliente. Lo que el cliente cambie en Entrega nunca toca el histórico.
    storage_provider = Column(String(20), default='google')        # google | microsoft | dropbox | ninguno
    entrega_status = Column(String(20), default='pendiente')       # pendiente | ok | error
    entrega_folder_id = Column(String(200), nullable=True)         # Entrega/{Empresa} en la nube de Neurobaeza
    entrega_compartido_en = Column(DateTime, nullable=True)
    entrega_error = Column(Text, nullable=True)

    # ✅ Google Sheets por empresa (cada tenant tiene su propio Sheet)
    google_sheets_id = Column(String(200), nullable=True)   # ID del spreadsheet de esta empresa
    google_sheets_url = Column(String(500), nullable=True)  # URL del spreadsheet

    # ✅ Estado del aprovisionamiento background (visibilidad + reintentos desde el admin)
    sheet_status = Column(String(20), default='pendiente')   # pendiente | ok | error
    drive_status = Column(String(20), default='pendiente')   # pendiente | ok | error | sin_drive
    provision_error = Column(Text, nullable=True)            # último error (diagnóstico)

    # Estado del onboarding
    onboarding_completado = Column(Boolean, default=False)
    onboarding_step = Column(Integer, default=1)
    onboarding_data_json = Column(JSON, default=dict)  # Datos acumulados del wizard

    created_at = Column(DateTime, default=get_utc_now)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)

    empresa = relationship("Company", backref="tenant_config")


class TenantInvitation(Base):
    """
    Invitaciones de onboarding generadas por superadmin/admin.
    Un token de un solo uso con expiración de 7 días.
    """
    __tablename__ = 'tenant_invitations'

    id = Column(Integer, primary_key=True, autoincrement=True)
    token = Column(String(128), unique=True, index=True, nullable=False)
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    creado_por = Column(String(200))  # username del admin que generó la invitación
    usado = Column(Boolean, default=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=get_utc_now)
    # ✅ Liga la invitación con su solicitud de demo (si viene de ese flujo)
    demo_request_id = Column(Integer, ForeignKey('demo_requests.id', ondelete='SET NULL'), nullable=True)


class DemoRequest(Base):
    """
    ✅ NUEVO: Solicitudes de demo/acceso al sistema.
    Flujo: empresa llena formulario público → admin revisa → aprueba → envía link.
    """
    __tablename__ = 'demo_requests'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Datos de la empresa solicitante
    empresa_nombre = Column(String(200), nullable=False)
    nit = Column(String(50), nullable=True)
    contacto_nombre = Column(String(200), nullable=False)
    contacto_email = Column(String(300), nullable=False, index=True)
    contacto_telefono = Column(String(50), nullable=True)
    como_conocio = Column(String(200), nullable=True)  # "referido", "google", "linkedin", etc
    mensaje = Column(Text, nullable=True)               # Mensaje libre del solicitante

    # Estado del lead
    estado = Column(String(20), default='pendiente', index=True)  # pendiente | aprobado | rechazado
    notas_internas = Column(Text, nullable=True)        # Notas del admin al revisar
    aprobado_por = Column(String(200), nullable=True)   # username del admin que aprobó/rechazó

    # Vínculo con la empresa creada al aprobar
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='SET NULL'), nullable=True)

    created_at = Column(DateTime, default=get_utc_now, index=True)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)

    __table_args__ = (
        Index('idx_demo_estado_fecha', 'estado', 'created_at'),
    )


class DemoSession(Base):
    """
    Sesión de demo temporal para empresas que quieren probar el sistema.
    Se crea al aprobar un lead como 'demo'. Se elimina automáticamente al vencer.
    """
    __tablename__ = 'demo_sessions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, unique=True)
    demo_request_id = Column(Integer, ForeignKey('demo_requests.id', ondelete='SET NULL'), nullable=True)

    horas = Column(Integer, default=4)
    expires_at = Column(DateTime, nullable=False)
    activa = Column(Boolean, default=True)

    # Dato adicional del formulario público
    cantidad_empleados = Column(String(20), nullable=True)  # "1-10", "11-50", "51-200", "200+"

    # Feedback al finalizar
    feedback_calificacion = Column(Integer, nullable=True)   # 1-5 estrellas
    feedback_mejoras = Column(Text, nullable=True)
    feedback_quiere_contratar = Column(String(20), nullable=True)  # "si" | "no" | "despues"
    feedback_enviado_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=get_utc_now)


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

class OAuthToken(Base):
    """
    Tokens OAuth guardados (Gmail, Drive, etc).
    Se guarda el access_token y refresh_token después de autorizar.
    """
    __tablename__ = "oauth_tokens"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    servicio = Column(String(50), nullable=False, unique=True, index=True)  # 'gmail', 'drive', etc
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    autorizado_en = Column(DateTime, default=get_utc_now)
    actualizado_en = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)


class ExtractoIncapacidad(Base):
    """
    ✅ NUEVO: Tabla para almacenar texto extraído de documentos de incapacidad
    Permite consultar y exportar el texto extraído por Mistral
    """
    __tablename__ = 'extractos_incapacidades'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Referencias
    cedula = Column(String(50), nullable=False, index=True)
    caso_id = Column(Integer, ForeignKey('cases.id', ondelete='CASCADE'), nullable=True, index=True)
    
    # Metadata del documento
    tipo_documento = Column(String(100))  # 'incapacidad', 'epicrisis', 'soat', etc
    tipo_incapacidad = Column(String(100))  # 'maternidad', 'enfermedad_general', etc
    
    # Texto extraído
    texto_extraido = Column(Text, nullable=False)
    
    # Calidad y metadata
    calidad_score = Column(Float)  # Score del validador (0.0 a 1.0)
    modelo_ocr = Column(String(100), default='pixtral-12b-2409')  # Modelo usado
    
    # Control de procesamiento
    procesado = Column(Boolean, default=True)
    error_procesamiento = Column(String(500))  # Si hubo error
    
    # Auditoría
    creado_en = Column(DateTime, default=get_utc_now, index=True)
    actualizado_en = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)
    
    # Índices para búsqueda rápida
    __table_args__ = (
        Index('idx_cedula_tipo', 'cedula', 'tipo_documento'),
        Index('idx_caso_creado', 'caso_id', 'creado_en'),
    )


class ResultadoValidacion(Base):
    """
    ✅ NUEVO: Resultados de validación con IA (Gemini/Claude)
    Almacena la decisión, reglas fallidas y datos extraídos
    """
    __tablename__ = 'resultados_validacion'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Referencias
    cedula = Column(String(50), nullable=False, index=True)
    extracto_id = Column(Integer, ForeignKey('extractos_incapacidades.id', ondelete='CASCADE'), nullable=True, index=True)
    caso_id = Column(Integer, ForeignKey('cases.id', ondelete='CASCADE'), nullable=True, index=True)
    
    # Resultado de validación
    decision = Column(Enum(DecisionValidacion), default=DecisionValidacion.REVISAR, nullable=False)
    motivo = Column(Text)  # Explicación de la decisión
    
    # Reglas y análisis
    reglas_fallidas = Column(JSON, default=list)  # Array de IDs de reglas que fallaron
    reglas_procesadas = Column(Integer, default=0)  # Total de reglas evaluadas
    
    # Datos extraídos por la IA
    datos_extraidos = Column(JSON, default=dict)  # Nombre, cédula, fechas, diagnóstico, etc
    
    # Metadata
    modelo_ia = Column(String(100), default='gemini-2.0-flash')  # Modelo usado
    version_reglas = Column(String(50), default='1.0')  # Versión de ruleset
    
    # Control
    validado_exitosamente = Column(Boolean, default=True)
    error_validacion = Column(String(500))  # Si hubo error
    
    # Auditoría
    creado_en = Column(DateTime, default=get_utc_now, index=True)
    actualizado_en = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)
    
    # Índices
    __table_args__ = (
        Index('idx_cedula_decision', 'cedula', 'decision'),
        Index('idx_extracto_validacion', 'extracto_id'),
        Index('idx_caso_validacion', 'caso_id'),
    )


# ==================== CALIFICACIÓN IA: REGLAS Y PRECEDENTES (RAG) ====================

class ReglaValidacionIA(Base):
    """
    Reglas de validación editables en vivo (reemplaza data/reglas_validacion.json).
    Cada regla se vectoriza (embedding) para que el calificador solo traiga por RAG
    las reglas relevantes al soporte que está evaluando, en vez de mandar las 30+
    reglas completas en cada prompt (más barato y más preciso).

    Reglas globales (company_id NULL) aplican a todas las empresas; una empresa
    puede tener reglas propias además de las globales.
    """
    __tablename__ = 'reglas_validacion_ia'

    id = Column(Integer, primary_key=True, autoincrement=True)
    codigo = Column(String(20), unique=True, nullable=False)  # R01, R12... o slug generado
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=True, index=True)

    nombre = Column(String(200), nullable=False)
    descripcion = Column(Text, nullable=False)  # texto fuente (lenguaje natural o estructurado)
    decision = Column(Enum(DecisionValidacion), nullable=False, default=DecisionValidacion.REVISAR)
    tipo = Column(String(50))  # estructural, identidad, coherencia, completitud, calidad, especializada...
    tipos_incapacidad = Column(JSON, default=list)  # [] = aplica a todos los TipoIncapacidad
    motivo_rechazo_template = Column(Text)  # plantilla del mensaje al colaborador, con placeholders {campo}

    embedding = Column(Vector(EMBEDDING_DIM), nullable=True)

    activa = Column(Boolean, default=True, nullable=False, index=True)
    version = Column(Integer, default=1, nullable=False)
    reemplaza_a_id = Column(Integer, ForeignKey('reglas_validacion_ia.id', ondelete='SET NULL'), nullable=True)

    creada_por = Column(String(150))  # email del admin que la escribió por chat
    origen = Column(String(20), default='chat')  # 'chat' | 'seed_json' | 'sistema'

    creado_en = Column(DateTime, default=get_utc_now, index=True)
    actualizado_en = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)

    __table_args__ = (
        Index('idx_regla_ia_activa_company', 'activa', 'company_id'),
    )


class PrecedenteValidacion(Base):
    """
    Memoria de casos ya resueltos por un humano, vectorizada como precedente
    para dar contexto (RAG) al calificador y para detectar si una regla nueva
    contradice decisiones históricas ya tomadas.

    Se alimenta de dos formas: automáticamente desde el historial de CaseEvent
    ya existente (backfill), y en vivo cada vez que un validador confirma o
    corrige un veredicto del calificador IA (modo prueba / uso real).
    """
    __tablename__ = 'precedentes_validacion'

    id = Column(Integer, primary_key=True, autoincrement=True)
    caso_id = Column(Integer, ForeignKey('cases.id', ondelete='SET NULL'), nullable=True, index=True)
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='SET NULL'), nullable=True, index=True)
    serial = Column(String(100), index=True)

    resumen = Column(Text, nullable=False)  # texto corto: tipo, hallazgos, contexto relevante del caso
    decision_humana = Column(String(50), nullable=False)  # EstadoCaso al que lo movió el validador
    motivo = Column(Text)
    checks_aplicados = Column(JSON, default=list)

    sugerencia_ia_original = Column(String(50), nullable=True)  # decisión que había dado el calificador
    fue_correccion_ia = Column(Boolean, default=False)  # True si el humano corrigió a la IA

    embedding = Column(Vector(EMBEDDING_DIM), nullable=True)

    creado_en = Column(DateTime, default=get_utc_now, index=True)

    __table_args__ = (
        Index('idx_precedente_company_creado', 'company_id', 'creado_en'),
    )


# ==================== CONFIGURACIÓN DE BOTS POR EMPRESA ====================

class EmpresaBotConfig(Base):
    """
    ✅ NUEVO: Configuración de bots de radicación por empresa
    Vincula empresas con los bots disponibles (SURA, Famisanar, etc)
    y almacena sus credenciales en vivo.
    
    Una empresa puede tener múltiples bots configurados.
    El estado indica si el bot está activo, en configuración, etc.
    
    Ejemplo:
    - Empresa: "EMPRESA ABC"
    - Bot: "sura_eps"
    - Credenciales: {"usuario": "900123456", "tipo_doc": "NIT", "clave": "****"}
    """
    __tablename__ = 'empresa_bot_config'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Referencia a empresa (por nombre como solicitó el usuario)
    nombre_empresa = Column(String(200), nullable=False, index=True)
    
    # Nombre del bot (ej: sura_eps, famisanar, compensar, arl_sura, etc)
    bot_nombre = Column(String(100), nullable=False)
    
    # Tipo de bot: portal, email, api, etc
    bot_tipo_medio = Column(String(50), default='portal')  # portal | email | api
    
    # Estado del bot para esta empresa
    estado = Column(String(50), default='configuracion')  # configuracion | activo | inactivo | suspendido
    
    # Credenciales almacenadas (JSON)
    # Estructura varía según el bot:
    # - SURA: {"usuario": "...", "tipo_doc": "C|A|E", "clave": "..."}
    # - Famisanar: {"correo_destino": "..."}
    # - etc
    credenciales = Column(JSON, default=dict)
    
    # Metadata adicional
    observaciones = Column(Text, nullable=True)

    # Soporte adjunto (certificado bancario u otro doc requerido por la EPS)
    # Se adjunta automáticamente junto a la incapacidad en cada radicación
    soporte_drive_url = Column(String(500), nullable=True)   # URL de Drive del soporte
    soporte_nombre    = Column(String(200), nullable=True)   # Nombre original del archivo
    soporte_actualizado_en = Column(DateTime, nullable=True) # Última subida/reemplazo

    # Auditoría
    creado_por = Column(String(200))  # Usuario admin que lo creó
    actualizado_por = Column(String(200))  # Usuario admin que lo actualizó

    # ✅ Browserbase — sesión de navegador persistente (context) por bot
    # Guarda cookies/login del portal EPS entre radicaciones (cifrado en Browserbase)
    browserbase_context_id = Column(String(100), nullable=True)
    context_ultimo_login   = Column(DateTime, nullable=True)   # Última vez que se hizo login manual
    context_login_session  = Column(String(100), nullable=True) # Sesión de login en curso (si hay una abierta)

    creado_en = Column(DateTime, default=get_utc_now, index=True)
    actualizado_en = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)
    
    # Índices para búsquedas rápidas
    __table_args__ = (
        Index('idx_empresa_bot', 'nombre_empresa', 'bot_nombre', unique=True),
        Index('idx_empresa_activo', 'nombre_empresa', 'estado'),
    )


# ==================== RADICACIÓN — SKILLS Y SESIONES ====================

class RadicacionSkill(Base):
    """
    Registro de skills de browser-use por EPS/ARL.
    Cuando browser-use genera un Playwright script cacheado para una EPS,
    lo registra aquí. El admin panel muestra 'Activa' vs 'Pendiente'.
    """
    __tablename__ = 'radicacion_skills'

    id             = Column(Integer, primary_key=True, autoincrement=True)
    eps_key        = Column(String(100), nullable=False, unique=True, index=True)
    estado         = Column(String(50), default='pendiente')   # pendiente | activa | fallo
    cache_key      = Column(String(64))                        # MD5 del template
    script_path    = Column(String(500))                       # Ruta en Railway
    primer_run_tokens = Column(Integer, default=0)
    usos_totales   = Column(Integer, default=0)
    ultimo_uso_at  = Column(DateTime, nullable=True)
    primer_run_at  = Column(DateTime, nullable=True)
    # Schema dinámico del formulario de login que descubrió el bot.
    # Formato: [{"key":"nit","label":"NIT empresa","tipo":"text"},{"key":"tipo_doc","tipo":"select","opciones":["NIT","CC"]}]
    campos_credenciales = Column(JSON, nullable=True)
    # Límite de peso del PDF aceptado por el portal (MB). El bot comprimirá antes de subir.
    # Sobreescribe el valor por defecto del MANIFEST si se detectó un límite distinto en vivo.
    max_pdf_mb     = Column(Float, nullable=True)
    # ID del Agent reutilizable en Browserbase para esta EPS/ARL (uno por eps_key, no por empresa —
    # el portal es el mismo para todas las empresas, solo cambian las credenciales).
    # Se registra vía PUT /admin/radicacion/skills/{eps_key} sin necesidad de deploy.
    agent_id       = Column(String(100), nullable=True)
    # ID del Agent de Browserbase que consulta el ESTADO/reportes en este mismo portal
    # (misma credencial de arriba — solo cambia la tarea: leer en vez de radicar).
    agent_id_reportes = Column(String(100), nullable=True)
    creado_en      = Column(DateTime, default=get_utc_now)
    actualizado_en = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)


class RadicacionSesion(Base):
    """
    Sesiones de radicación iniciadas por browser-use.
    Permite que el admin panel monitoree en vivo el estado de cada radicación.
    """
    __tablename__ = 'radicacion_sesiones'

    id           = Column(Integer, primary_key=True, autoincrement=True)
    sesion_id    = Column(String(100), nullable=False, unique=True, index=True)
    empresa      = Column(String(200), nullable=False, index=True)
    eps          = Column(String(100), nullable=False)
    medio        = Column(String(50), default='portal')   # portal | email
    documento    = Column(String(50))                      # CC/NIT del trabajador
    estado       = Column(String(50), default='en_curso')  # en_curso | exitosa | fallida | enviado | error | esperando
    radicado     = Column(String(200))                     # N° radicado si exitosa
    error_msg    = Column(Text)
    cached       = Column(Boolean, default=False)
    progreso     = Column(Integer, default=0)              # 0-100
    logs         = Column(JSON, default=list)              # Lista de pasos del agente
    iniciado_en  = Column(DateTime, default=get_utc_now, index=True)
    finalizado_en = Column(DateTime, nullable=True)
    actualizado_en = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)


class RadicacionCola(Base):
    """
    Cola persistente de radicaciones con reintentos automáticos y backoff escalado.

    Estados:
      pendiente         → esperando ser procesada (respeta proximo_intento)
      procesando        → actualmente en proceso por browser-use
      exitosa           → radicación completada exitosamente (o registrada manualmente con radicado)
      fallo_temporal    → falló, se reintentará según backoff
      fallo_definitivo  → se agotaron los reintentos (~48 h) o error irrecuperable
      bloqueado_revision→ el calificador IA marcó el caso RECHAZAR (faltan datos básicos:
                          diagnóstico, días, datos del médico, fecha) — no se radica
                          automáticamente hasta que un humano lo revise

    Backoff de reintentos (intentos acumulados):
      1-2   → cada 5 min
      3-4   → cada 20 min
      5-6   → cada 1 hora
      7-8   → cada 4 horas
      9+    → próximo día a las 8 am (Colombia)
      >12   → fallo_definitivo
    """
    __tablename__ = 'radicacion_cola'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Referencia al caso
    serial_caso  = Column(String(50), nullable=True, index=True)
    case_id      = Column(Integer, ForeignKey('cases.id', ondelete='SET NULL'), nullable=True)

    # Destino
    empresa          = Column(String(200), nullable=False, index=True)
    eps_key          = Column(String(100), nullable=False, index=True)
    tipo_incapacidad = Column(String(100), default='enfermedad_general')

    # Archivos
    pdf_path      = Column(String(500))   # Ruta local en /app/archivos/ (volumen Docker)
    pdf_drive_url = Column(String(500))   # URL del PDF en Drive (respaldo)

    # Datos para rellenar el formulario del portal
    datos_ocr      = Column(JSONB, default=dict)   # Campos extraídos por OCR
    datos_manuales = Column(JSONB, default=dict)   # Campos adicionales manuales

    # Control de reintentos
    estado          = Column(String(50), default='pendiente', index=True)
    intentos        = Column(Integer, default=0)
    proximo_intento = Column(DateTime, default=get_utc_now, index=True)

    # Resultado
    radicado          = Column(String(200), nullable=True)
    observacion       = Column(Text, nullable=True)   # Observación del portal (éxito o rechazo)
    ultimo_error      = Column(Text, nullable=True)
    historial_errores = Column(JSONB, default=list)   # [{intento, error, ts}]
    fallo_motivo      = Column(Text, nullable=True)   # Resumen del fallo definitivo

    # Sesión browser-use que lo procesó (o está procesando)
    sesion_id = Column(String(100), nullable=True)

    # Radicación manual: cuando el bot falló o hubo error y un humano radicó
    # por fuera del sistema. Deja trazabilidad sin perder el registro.
    resuelto_manualmente = Column(Boolean, default=False)
    resuelto_por = Column(String(200), nullable=True)   # nombre de quien la radicó a mano
    resuelto_en  = Column(DateTime, nullable=True)

    # Timestamps
    creado_en    = Column(DateTime, default=get_utc_now, index=True)
    procesado_en = Column(DateTime, nullable=True)
    actualizado_en = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)

    __table_args__ = (
        Index('idx_cola_eps_estado',  'eps_key', 'estado'),
        Index('idx_cola_proximo_est', 'proximo_intento', 'estado'),
    )


class RecobroFila(Base):
    """
    Libro mayor del recobro: una fila por incapacidad tal como la reporta el
    portal de la EPS. Es la contraparte de radicacion_cola (lo que NOSOTROS
    radicamos) contra lo que la EPS RECONOCE y PAGA.

    Por qué existe una tabla y no se consulta el portal cada vez: bajar el
    reporte cuesta un run de navegador y minutos de espera. Bajándolo una vez
    por rango y acumulándolo aquí, el histórico de una persona (o de la empresa
    entera, o de tres años atrás) se responde con un SELECT, gratis e
    instantáneo. El bot escribe una vez; la base responde infinitas veces.

    Idempotencia: `clave_natural` identifica la fila en el portal. Un reporte
    re-descargado (rangos que se solapan, un reintento) actualiza la fila en vez
    de duplicarla, así que volver a bajar un mes ya bajado nunca ensucia datos.

    `origen` distingue los dos reportes de Compensar, que no traen las mismas
    columnas:
      radicadas → listado de incapacidades radicadas y su estado
      pagadas   → "Incapacidades pagadas": lo que la EPS efectivamente giró
    """
    __tablename__ = 'recobro_filas'

    id = Column(Integer, primary_key=True, autoincrement=True)

    empresa = Column(String(200), nullable=False, index=True)
    eps_key = Column(String(100), nullable=False, index=True)
    origen  = Column(String(30), nullable=False, default='radicadas')  # radicadas | pagadas

    # Identidad de la fila dentro del portal (radicado, o nro. incapacidad + cédula
    # si el reporte no trae radicado). Ver recobro_service._clave_natural.
    clave_natural = Column(String(200), nullable=False, index=True)

    # Datos de la incapacidad según el portal
    radicado            = Column(String(200), nullable=True, index=True)
    numero_incapacidad  = Column(String(100), nullable=True, index=True)
    cedula              = Column(String(50),  nullable=True, index=True)
    nombre_trabajador   = Column(String(300), nullable=True)
    fecha_inicio        = Column(Date, nullable=True)
    fecha_fin           = Column(Date, nullable=True)
    dias                = Column(Integer, nullable=True)
    diagnostico         = Column(String(300), nullable=True)
    motivo              = Column(String(200), nullable=True)

    # Resultado económico
    estado_portal  = Column(String(200), nullable=True, index=True)  # texto crudo: "Pagada", "Rechazada"…
    motivo_rechazo = Column(Text, nullable=True)
    valor_reconocido = Column(Float, nullable=True)
    valor_pagado     = Column(Float, nullable=True)
    fecha_pago       = Column(Date, nullable=True)

    # Trazabilidad: fila cruda completa del reporte. Las EPS agregan y quitan
    # columnas sin avisar; guardarla entera evita tener que volver a bajar el
    # reporte cuando mañana necesitemos un dato que hoy no mapeamos.
    datos_crudos = Column(JSONB, default=dict)

    # Enlace con nuestro lado (lo llena el cruce; puede quedar vacío si la EPS
    # reporta una incapacidad que nosotros no radicamos)
    case_id = Column(Integer, ForeignKey('cases.id', ondelete='SET NULL'), nullable=True)
    cola_id = Column(Integer, nullable=True, index=True)

    # Rango del reporte que trajo esta fila (para saber qué se ha cubierto)
    periodo_desde = Column(Date, nullable=True)
    periodo_hasta = Column(Date, nullable=True)

    creado_en      = Column(DateTime, default=get_utc_now, index=True)
    actualizado_en = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)

    __table_args__ = (
        # Idempotencia real a nivel de BD: dos runs simultáneos del mismo reporte
        # no pueden crear la fila dos veces.
        UniqueConstraint('empresa', 'eps_key', 'origen', 'clave_natural',
                         name='uq_recobro_fila_natural'),
        Index('idx_recobro_empresa_eps', 'empresa', 'eps_key', 'origen'),
        Index('idx_recobro_cedula_fecha', 'cedula', 'fecha_inicio'),
    )


class Apelacion(Base):
    """
    Seguimiento de una apelación o un reintento de radicación — los dos casos
    en que una incapacidad ya procesada necesita volver a moverse:

      negacion_apelable    → la EPS/ARL negó por un motivo controvertible
                              (recobro_service.cruce marcó `negada_apelable`,
                              vía motivos.clasificar_negacion). Referencia
                              recobro_fila_id / radicacion_cola_id.
      incompleta_completada → el caso se radicó (o se iba a radicar) incompleto
                              y ya se completó; hay que volver a radicarlo.
                              Referencia case_id.

    Esta tabla es solo el seguimiento del caso a caso (quién decidió apelar,
    con qué justificación, qué pasó). La clasificación de qué es apelable ya
    la hace motivos.clasificar_negacion; esto no la duplica. El reenvío real al
    portal sigue pasando por radicacion_cola — aquí solo queda el enlace
    (radicacion_cola_id) una vez que alguien decide re-radicar.
    """
    __tablename__ = 'apelaciones'

    id = Column(Integer, primary_key=True, autoincrement=True)

    cedula  = Column(String(50), nullable=False, index=True)
    empresa = Column(String(200), nullable=False, index=True)
    eps_key = Column(String(100), nullable=False, index=True)

    tipo = Column(String(30), nullable=False, index=True)  # negacion_apelable | incompleta_completada

    case_id            = Column(Integer, ForeignKey('cases.id', ondelete='SET NULL'), nullable=True, index=True)
    recobro_fila_id    = Column(Integer, ForeignKey('recobro_filas.id', ondelete='SET NULL'), nullable=True, index=True)
    radicacion_cola_id = Column(Integer, ForeignKey('radicacion_cola.id', ondelete='SET NULL'), nullable=True, index=True)

    motivo_codigo   = Column(String(20), nullable=True)   # NEG-xx del catálogo, si aplica
    motivo_original = Column(Text, nullable=True)         # texto de rechazo/observación que originó esto
    justificacion   = Column(Text, nullable=True)         # lo que argumenta el validador para apelar
    datos_corregidos = Column(JSONB, default=dict)        # campos que cambiaron frente al envío original

    # pendiente → alguien la creó y falta actuar
    # radicada  → ya se creó un radicacion_cola_id y se reenvió al portal
    # resuelta  → la EPS respondió tras la apelación/reenvío (ver resultado)
    # descartada → un validador decidió no apelar (motivo_original explica por qué)
    estado = Column(String(30), default='pendiente', index=True)
    resultado = Column(Text, nullable=True)

    creado_por  = Column(String(200), nullable=True)
    creado_en   = Column(DateTime, default=get_utc_now, index=True)
    resuelto_en = Column(DateTime, nullable=True)

    __table_args__ = (
        Index('idx_apelacion_cedula_estado', 'cedula', 'estado'),
        Index('idx_apelacion_empresa_estado', 'empresa', 'estado'),
    )


class RecobroSync(Base):
    """
    Hasta qué fecha está descargado el reporte de cada empresa/EPS/origen.

    Es lo que permite bajar solo lo nuevo: el siguiente run pide desde
    `cubierto_hasta` menos unos días de solape (las EPS actualizan el estado de
    una incapacidad semanas después de radicarla) en vez de mes por mes desde el
    principio. Como la ingesta es idempotente, el solape no duplica nada.
    """
    __tablename__ = 'recobro_sync'

    id = Column(Integer, primary_key=True, autoincrement=True)

    empresa = Column(String(200), nullable=False, index=True)
    eps_key = Column(String(100), nullable=False, index=True)
    origen  = Column(String(30), nullable=False, default='radicadas')

    cubierto_desde = Column(Date, nullable=True)   # fecha más antigua ya descargada
    cubierto_hasta = Column(Date, nullable=True)   # fecha más reciente ya descargada

    ultimo_run_id  = Column(String(100), nullable=True)
    ultimo_estado  = Column(String(50), default='pendiente')  # pendiente|en_curso|ok|error
    ultimo_error   = Column(Text, nullable=True)
    filas_totales  = Column(Integer, default=0)
    ultimo_sync_en = Column(DateTime, nullable=True)

    creado_en      = Column(DateTime, default=get_utc_now)
    actualizado_en = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)

    __table_args__ = (
        UniqueConstraint('empresa', 'eps_key', 'origen', name='uq_recobro_sync'),
    )


class WhatsAppConversacion(Base):
    """
    Estado del bot conversacional de WhatsApp, una fila por número de teléfono.
    Mismo patrón de "paso + JSON acumulado" que TenantConfig.onboarding_step.

    `modulo` deja preparado el router para futuros bots (cartera, servicio
    automovilístico) sobre el mismo número/webhook sin cambiar este modelo.
    `ultimo_message_id` da idempotencia contra reintentos del webhook de Meta.
    """
    __tablename__ = 'whatsapp_conversaciones'

    id = Column(Integer, primary_key=True, autoincrement=True)
    telefono = Column(String(50), nullable=False, unique=True, index=True)
    modulo = Column(String(50), default='incapacidades', index=True)
    paso = Column(String(50), default='inicio')
    datos_json = Column(JSON, default=dict)  # numero_documento, employee_id, company_id, nombre...
    intentos_confirmacion = Column(Integer, default=0)
    ultimo_message_id = Column(String(100), nullable=True)

    # Última vez que ESTE número nos escribió. De aquí sale si la ventana de
    # 24 horas de Meta está abierta (texto libre gratis) o cerrada (hay que
    # mandar plantilla, y esa sí se factura). Va aparte de `updated_at` porque
    # `updated_at` se mueve con cualquier escritura del bot, y de este dato
    # depende el costo de cada aviso. Ver app/services/whatsapp_envio.py.
    ultimo_entrante_en = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=get_utc_now)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)


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

def _asegurar_extension_pgvector():
    """
    Crea la extensión `vector` en PostgreSQL si no existe. Debe correr ANTES de
    create_all() porque las tablas reglas_validacion_ia/precedentes_validacion
    usan una columna tipo VECTOR. Fail-safe: si falla (SQLite, o el usuario de
    BD no tiene permiso de CREATE EXTENSION), el calificador IA cae a modo sin
    búsqueda semántica en vez de romper el arranque.
    """
    global PGVECTOR_DISPONIBLE
    PGVECTOR_DISPONIBLE = False

    if not PGVECTOR_INSTALADO:
        print("⚠️ Paquete 'pgvector' no instalado — calificación IA sin búsqueda semántica")
        return

    if database_url.startswith("sqlite"):
        print("ℹ️  SQLite (desarrollo): extensión pgvector no aplica, se omite")
        return

    try:
        db = SessionLocal()
        db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        db.commit()
        db.close()
        PGVECTOR_DISPONIBLE = True
        print("✅ Extensión pgvector lista en PostgreSQL")
    except Exception as e:
        print(f"⚠️ No se pudo crear la extensión pgvector (se omite búsqueda semántica): {e}")


# Bandera consultada por el servicio de calificación IA para saber si puede
# hacer búsqueda vectorial o debe usar todas las reglas activas sin filtrar.
PGVECTOR_DISPONIBLE = False


def init_db():
    """Crea todas las tablas en la base de datos"""
    try:
        # ✅ Asegurar extensión pgvector ANTES de crear tablas (las usan como tipo de columna)
        _asegurar_extension_pgvector()

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

        # ✅ Migrar columnas tenant en admin_users (seguro de re-ejecutar)
        migrar_columnas_tenant()

        # ✅ Migrar columnas de radicación (seguro de re-ejecutar)
        migrar_columnas_radicacion()

        # ✅ Migrar columnas de demo/tenant sheets (seguro de re-ejecutar)
        migrar_columnas_demo_tenant()

        # ✅ Migrar columnas de Entrega / storage multi-proveedor (seguro de re-ejecutar)
        migrar_columnas_entrega()

        # ✅ Migrar tabla cola de radicación (seguro de re-ejecutar)
        migrar_cola_radicacion()

        # ✅ Migrar tablas de recobro (cruce radicado vs pagado) (seguro de re-ejecutar)
        migrar_recobro()

        # ✅ Migrar columnas de verificación mensual de EPS (CoreSoft) (seguro de re-ejecutar)
        migrar_columnas_eps_tracking()

        # ✅ Migrar columnas de Browserbase en empresa_bot_config (seguro de re-ejecutar)
        migrar_columnas_browserbase()

        # ✅ Seed de reglas de calificación IA + índice vectorial (seguro de re-ejecutar)
        migrar_reglas_validacion_ia()

        # ✅ Centro de Costos — precarga inventario de servicios/APIs pagos (seguro de re-ejecutar)
        # Import diferido: evita import circular (el módulo importa modelos desde app.database)
        try:
            from app.services.servicios_pago import seed_servicios_pago_iniciales
            seed_servicios_pago_iniciales()
        except Exception as e:
            print(f"❌ Error precargando Centro de Costos: {e}")

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

def migrar_columnas_tenant():
    """
    Agrega columnas multi-tenant a admin_users si no existen.
    Ejecutar después de agregar los modelos TenantConfig / TenantInvitation.
    Seguro de re-ejecutar (IF NOT EXISTS).
    """
    try:
        db = SessionLocal()
        print("🔄 Migrando columnas multi-tenant en admin_users...")

        migraciones = [
            ("es_tenant_admin", "BOOLEAN DEFAULT FALSE"),
            ("tenant_permisos",  "TEXT DEFAULT '{}'"),
            ("invited_by",       "INTEGER"),
        ]
        for col, tipo in migraciones:
            try:
                if database_url.startswith("sqlite"):
                    db.execute(text(f"ALTER TABLE admin_users ADD COLUMN {col} {tipo}"))
                else:
                    db.execute(text(f"ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS {col} {tipo}"))
                print(f"   ✅ Columna '{col}' en admin_users agregada")
            except Exception as e:
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    print(f"   ℹ️  Columna '{col}' ya existe")
                else:
                    print(f"   ⚠️  {col}: {e}")

        db.commit()
        print("✅ Migración multi-tenant completada")
        db.close()
        return True
    except Exception as e:
        print(f"❌ Error en migración tenant: {e}")
        return False


def migrar_columnas_browserbase():
    """
    Agrega columnas de Browserbase (context persistente) a empresa_bot_config.
    Seguro de re-ejecutar (IF NOT EXISTS en PostgreSQL).
    """
    try:
        db = SessionLocal()
        print("🔄 Migrando columnas de Browserbase...")

        migraciones = [
            ("empresa_bot_config", "browserbase_context_id", "VARCHAR(100)"),
            ("empresa_bot_config", "context_ultimo_login",   "TIMESTAMP"),
            ("empresa_bot_config", "context_login_session",  "VARCHAR(100)"),
            ("radicacion_cola",    "observacion",            "TEXT"),
            ("radicacion_skills",  "agent_id",                "VARCHAR(100)"),
            ("radicacion_skills",  "agent_id_reportes",       "VARCHAR(100)"),
            # Ventana de 24h de WhatsApp: decide texto libre (gratis) vs.
            # plantilla (facturada). Ver app/services/whatsapp_envio.py.
            ("whatsapp_conversaciones", "ultimo_entrante_en",  "TIMESTAMP"),
        ]
        for tabla, col, tipo in migraciones:
            try:
                if database_url.startswith("sqlite"):
                    db.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {col} TEXT"))
                else:
                    db.execute(text(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS {col} {tipo}"))
                print(f"   ✅ Columna '{col}' en {tabla} agregada")
            except Exception as e:
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    print(f"   ℹ️  Columna '{col}' ya existe en {tabla}")
                else:
                    print(f"   ⚠️  {tabla}.{col}: {e}")

        db.commit()

        # Seed único: el agente de Compensar vivía hardcodeado en AGENTES_POR_BOT
        # (app/routes/browserbase.py). Lo copiamos a la tabla de skills para que de
        # ahora en adelante el registro de agentes nuevos sea un PUT a
        # /admin/radicacion/skills/{eps_key}, sin tocar código ni hacer deploy.
        try:
            skill = db.query(RadicacionSkill).filter(RadicacionSkill.eps_key == "compensar").first()
            if not skill:
                skill = RadicacionSkill(eps_key="compensar", estado="activa")
                db.add(skill)
            if not skill.agent_id:
                skill.agent_id = "82ccb16d-1776-4ee2-8e7b-227cb033a0db"
                db.commit()
                print("   ✅ Seed: agent_id de Compensar registrado en radicacion_skills")
        except Exception as e:
            db.rollback()
            print(f"   ⚠️  Seed agent_id Compensar omitido: {e}")

        print("✅ Migración Browserbase completada")
        db.close()
        return True
    except Exception as e:
        print(f"❌ Error en migración Browserbase: {e}")
        return False


def migrar_reglas_validacion_ia():
    """
    Sincroniza reglas_validacion_ia con data/reglas_validacion.json (upsert por
    código) + índice vectorial para búsqueda semántica.
    Seguro de re-ejecutar: cada regla del JSON se inserta si no existe, o se
    actualiza SOLO si su fila en BD todavía tiene origen='seed_json' (nunca
    pisa reglas editadas a mano/por chat, que quedan con otro origen). Si el
    texto cambia, se limpia el embedding para que se regenere con el texto
    nuevo. Los embeddings nuevos quedan en NULL — los llena por separado
    app/embeddings_service.py (requiere llamar a la API de Gemini, no se hace
    en el arranque para no bloquear ni gastar tokens en cada deploy).
    """
    try:
        db = SessionLocal()
        print("🔄 Sincronizando reglas_validacion_ia con reglas_validacion.json...")

        import json as _json
        ruta_json = os.path.join(os.path.dirname(__file__), "data", "reglas_validacion.json")
        try:
            with open(ruta_json, "r", encoding="utf-8") as f:
                data = _json.load(f)
        except FileNotFoundError:
            print(f"   ⚠️  No se encontró {ruta_json}, se omite sincronización")
            data = None
        except Exception as e:
            print(f"   ⚠️  Error leyendo {ruta_json}: {e}")
            data = None

        if data is not None:
            insertadas = 0
            actualizadas = 0
            omitidas_editadas = 0
            for r in data.get("reglas", []):
                decision_raw = (r.get("decision") or "REVISAR").upper()
                decision = {
                    "RECHAZAR": DecisionValidacion.RECHAZAR,
                    "ACEPTAR": DecisionValidacion.ACEPTAR,
                    "DEVOLVER": DecisionValidacion.REVISAR,
                }.get(decision_raw, DecisionValidacion.REVISAR)
                nombre = r.get("nombre", r["id"])
                descripcion = r.get("descripcion", "")
                tipo = r.get("tipo")
                motivo_rechazo_template = r.get("motivo_rechazo")

                existente = db.query(ReglaValidacionIA).filter(
                    ReglaValidacionIA.codigo == r["id"]
                ).first()

                if existente is None:
                    db.add(ReglaValidacionIA(
                        codigo=r["id"],
                        company_id=None,  # regla global
                        nombre=nombre,
                        descripcion=descripcion,
                        decision=decision,
                        tipo=tipo,
                        tipos_incapacidad=[],
                        motivo_rechazo_template=motivo_rechazo_template,
                        activa=True,
                        version=1,
                        creada_por="sistema",
                        origen="seed_json",
                    ))
                    insertadas += 1
                elif existente.origen == "seed_json":
                    cambio = (
                        existente.nombre != nombre
                        or existente.descripcion != descripcion
                        or existente.decision != decision
                        or existente.tipo != tipo
                        or existente.motivo_rechazo_template != motivo_rechazo_template
                    )
                    if cambio:
                        existente.nombre = nombre
                        existente.descripcion = descripcion
                        existente.decision = decision
                        existente.tipo = tipo
                        existente.motivo_rechazo_template = motivo_rechazo_template
                        existente.embedding = None  # texto cambió: forzar re-embed
                        existente.version = (existente.version or 1) + 1
                        actualizadas += 1
                else:
                    # Editada a mano/por chat (origen != 'seed_json'): no se toca.
                    omitidas_editadas += 1

            try:
                db.commit()
                print(f"   ✅ Sync reglas: {insertadas} nuevas, {actualizadas} actualizadas, {omitidas_editadas} editadas (sin tocar)")
            except Exception as e:
                db.rollback()
                print(f"   ⚠️  Error sincronizando reglas: {e}")

        # Índice vectorial (HNSW, coseno) — solo si pgvector está disponible.
        # No es crítico: sin índice, la búsqueda funciona igual (scan secuencial),
        # solo más lenta a partir de miles de filas.
        if PGVECTOR_DISPONIBLE:
            for tabla in ("reglas_validacion_ia", "precedentes_validacion"):
                try:
                    db.execute(text(
                        f"CREATE INDEX IF NOT EXISTS idx_{tabla}_embedding_hnsw "
                        f"ON {tabla} USING hnsw (embedding vector_cosine_ops)"
                    ))
                    db.commit()
                    print(f"   ✅ Índice HNSW en {tabla}.embedding listo")
                except Exception as e:
                    db.rollback()
                    print(f"   ⚠️  Índice vectorial en {tabla} omitido: {e}")

        db.close()
        return True
    except Exception as e:
        print(f"❌ Error en migración de reglas_validacion_ia: {e}")
        return False


def migrar_columnas_radicacion():
    """
    Agrega columnas nuevas a radicacion_skills y radicacion_sesiones si no existen.
    Seguro de re-ejecutar (IF NOT EXISTS en PostgreSQL).
    """
    try:
        db = SessionLocal()
        print("🔄 Migrando columnas de radicación...")

        migraciones = [
            ("radicacion_skills", "campos_credenciales", "JSONB"),
            ("radicacion_skills", "max_pdf_mb",          "FLOAT"),
        ]
        for tabla, col, tipo in migraciones:
            try:
                if database_url.startswith("sqlite"):
                    db.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {col} TEXT"))
                else:
                    db.execute(text(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS {col} {tipo}"))
                print(f"   ✅ Columna '{col}' en {tabla} agregada")
            except Exception as e:
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    print(f"   ℹ️  Columna '{col}' ya existe en {tabla}")
                else:
                    print(f"   ⚠️  {tabla}.{col}: {e}")

        db.commit()
        print("✅ Migración radicación completada")
        db.close()
        return True
    except Exception as e:
        print(f"❌ Error en migración radicación: {e}")
        return False


def migrar_columnas_demo_tenant():
    """
    Agrega columnas nuevas a tenant_configs y tenant_invitations.
    También agrega campo demo_request_id a tenant_invitations.
    Seguro de re-ejecutar (IF NOT EXISTS en PostgreSQL).
    """
    try:
        db = SessionLocal()
        print("🔄 Migrando columnas demo/tenant sheets...")

        # Columnas nuevas en tenant_configs
        cols_tenant_config = [
            ("tenant_configs", "google_sheets_id",  "VARCHAR(200)"),
            ("tenant_configs", "google_sheets_url", "VARCHAR(500)"),
        ]
        # Columna nueva en tenant_invitations
        cols_invitations = [
            ("tenant_invitations", "demo_request_id", "INTEGER"),
        ]

        for tabla, col, tipo in cols_tenant_config + cols_invitations:
            try:
                if database_url.startswith("sqlite"):
                    db.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {col} {tipo}"))
                else:
                    db.execute(text(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS {col} {tipo}"))
                print(f"   ✅ Columna '{col}' en {tabla} agregada")
            except Exception as e:
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    print(f"   ℹ️  Columna '{col}' en {tabla} ya existe")
                else:
                    print(f"   ⚠️  {tabla}.{col}: {e}")

        db.commit()
        print("✅ Migración demo/tenant sheets completada")
        db.close()
        return True
    except Exception as e:
        print(f"❌ Error en migración demo/tenant: {e}")
        return False


def migrar_columnas_entrega():
    """
    Fase 0 del sistema multi-proveedor de almacenamiento (ver app/entrega_manager.py).
    Agrega a tenant_configs las columnas de Entrega: la copia compartida con el
    cliente, separada del histórico. Seguro de re-ejecutar (IF NOT EXISTS en PostgreSQL).
    """
    try:
        db = SessionLocal()
        print("🔄 Migrando columnas de Entrega (storage multi-proveedor)...")

        columnas = [
            ("tenant_configs", "storage_provider",      "VARCHAR(20) DEFAULT 'google'"),
            ("tenant_configs", "entrega_status",        "VARCHAR(20) DEFAULT 'pendiente'"),
            ("tenant_configs", "entrega_folder_id",     "VARCHAR(200)"),
            ("tenant_configs", "entrega_compartido_en", "TIMESTAMP"),
            ("tenant_configs", "entrega_error",         "TEXT"),
        ]
        for tabla, col, tipo in columnas:
            try:
                if database_url.startswith("sqlite"):
                    db.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {col} TEXT"))
                else:
                    db.execute(text(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS {col} {tipo}"))
                print(f"   ✅ Columna '{col}' en {tabla} agregada")
            except Exception as e:
                msg = str(e).lower()
                if "duplicate column" in msg or "already exists" in msg:
                    print(f"   ℹ️  Columna '{col}' en {tabla} ya existe")
                else:
                    print(f"   ⚠️  {tabla}.{col}: {e}")

        db.commit()
        print("✅ Migración de Entrega completada")
        db.close()
        return True
    except Exception as e:
        print(f"❌ Error en migración de Entrega: {e}")
        return False


def migrar_columnas_eps_tracking():
    """
    Agrega a employees las columnas de verificación mensual de EPS (CoreSoft/ADRES-BDUA)
    y a cases las del pago reconocido por la EPS (recobro → fin de recordatorios).
    Ver app/coresoft_client.py y app/tasks/scheduler_tasks.py (tarea_actualizar_eps_mensual).
    Seguro de re-ejecutar (IF NOT EXISTS en PostgreSQL).
    """
    try:
        db = SessionLocal()
        print("🔄 Migrando columnas de verificación de EPS y pago EPS...")

        columnas = [
            ("employees", "eps_anterior",         "VARCHAR(100)"),
            ("employees", "eps_actualizado_en",   "TIMESTAMP"),
            ("employees", "eps_verificado_en",    "TIMESTAMP"),
            ("employees", "eps_regimen",          "VARCHAR(50)"),
            ("employees", "eps_estado",           "VARCHAR(50)"),
            ("employees", "eps_tipo_afiliado",    "VARCHAR(50)"),
            ("employees", "eps_fecha_afiliacion", "DATE"),
            # Pago reconocido por la EPS → cierra el ciclo de recordatorios
            ("cases",     "pago_eps_reconocido",  "BOOLEAN DEFAULT FALSE"),
            ("cases",     "pago_eps_en",          "TIMESTAMP"),
            ("cases",     "pago_eps_valor",       "DOUBLE PRECISION"),
            ("cases",     "pago_eps_radicado",    "VARCHAR(100)"),
        ]
        for tabla, col, tipo in columnas:
            try:
                if database_url.startswith("sqlite"):
                    db.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {col} TEXT"))
                else:
                    db.execute(text(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS {col} {tipo}"))
                print(f"   ✅ Columna '{col}' en {tabla} agregada")
            except Exception as e:
                msg = str(e).lower()
                if "duplicate column" in msg or "already exists" in msg:
                    print(f"   ℹ️  Columna '{col}' en {tabla} ya existe")
                else:
                    print(f"   ⚠️  {tabla}.{col}: {e}")

        db.commit()
        print("✅ Migración de verificación de EPS completada")
        db.close()
        return True
    except Exception as e:
        print(f"❌ Error en migración de verificación de EPS: {e}")
        return False


def migrar_cola_radicacion():
    """
    Crea/asegura la tabla radicacion_cola y sus columnas.
    Seguro de re-ejecutar (IF NOT EXISTS).
    """
    try:
        db = SessionLocal()
        print("🔄 Migrando tabla radicacion_cola...")

        # La tabla se crea con create_all, pero por seguridad verificamos columnas clave
        columnas_extra = [
            ("radicacion_cola", "historial_errores", "JSONB DEFAULT '[]'"),
            ("radicacion_cola", "fallo_motivo",      "TEXT"),
            ("radicacion_cola", "pdf_drive_url",     "VARCHAR(500)"),
            ("radicacion_cola", "datos_manuales",    "JSONB DEFAULT '{}'"),
            # Radicación manual (bot falló o hubo error y alguien radicó por fuera del sistema)
            ("radicacion_cola", "resuelto_manualmente", "BOOLEAN DEFAULT FALSE"),
            ("radicacion_cola", "resuelto_por",         "VARCHAR(200)"),
            ("radicacion_cola", "resuelto_en",          "TIMESTAMP"),
        ]
        for tabla, col, tipo in columnas_extra:
            try:
                if database_url.startswith("sqlite"):
                    db.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {col} TEXT"))
                else:
                    db.execute(text(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS {col} {tipo}"))
                print(f"   ✅ Columna '{col}' en {tabla} asegurada")
            except Exception as e:
                msg = str(e).lower()
                if "duplicate column" in msg or "already exists" in msg:
                    print(f"   ℹ️  Columna '{col}' en {tabla} ya existe")
                else:
                    print(f"   ⚠️  {tabla}.{col}: {e}")

        db.commit()
        print("✅ Migración cola radicación completada")
        db.close()
        return True
    except Exception as e:
        print(f"❌ Error en migración cola radicación: {e}")
        return False


def migrar_recobro():
    """
    Crea/asegura las tablas del recobro (recobro_filas, recobro_sync).
    Las tablas las crea create_all; aquí se aseguran los índices y la
    restricción de unicidad que dan la idempotencia de la ingesta.
    Seguro de re-ejecutar (IF NOT EXISTS).
    """
    try:
        db = SessionLocal()
        print("🔄 Migrando tablas de recobro...")

        # create_all ya corrió en init_db; si la tabla aún no existe (BD vieja
        # que no reinició), la creamos solo a ella y salimos sin tocar índices.
        Base.metadata.create_all(
            bind=engine, checkfirst=True,
            tables=[RecobroFila.__table__, RecobroSync.__table__],
        )

        if not database_url.startswith("sqlite"):
            indices = [
                ("uq_recobro_fila_natural",
                 "CREATE UNIQUE INDEX IF NOT EXISTS uq_recobro_fila_natural "
                 "ON recobro_filas(empresa, eps_key, origen, clave_natural)"),
                ("idx_recobro_empresa_eps",
                 "CREATE INDEX IF NOT EXISTS idx_recobro_empresa_eps "
                 "ON recobro_filas(empresa, eps_key, origen)"),
                ("idx_recobro_cedula_fecha",
                 "CREATE INDEX IF NOT EXISTS idx_recobro_cedula_fecha "
                 "ON recobro_filas(cedula, fecha_inicio)"),
                ("uq_recobro_sync",
                 "CREATE UNIQUE INDEX IF NOT EXISTS uq_recobro_sync "
                 "ON recobro_sync(empresa, eps_key, origen)"),
            ]
            for nombre, sql in indices:
                try:
                    db.execute(text(sql))
                    print(f"   ✅ Índice '{nombre}' asegurado")
                except Exception as e:
                    msg = str(e).lower()
                    if "already exists" in msg or "duplicate" in msg:
                        print(f"   ℹ️  Índice '{nombre}' ya existe")
                    else:
                        print(f"   ⚠️  {nombre}: {e}")

        db.commit()
        print("✅ Migración de recobro completada")
        db.close()
        return True
    except Exception as e:
        print(f"❌ Error en migración de recobro: {e}")
        return False


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