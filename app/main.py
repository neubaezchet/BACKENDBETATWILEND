from typing import List, Optional
from fastapi import FastAPI, UploadFile, Form, File, Depends, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
import pandas as pd
import os, uuid
from pathlib import Path
from datetime import datetime, date
import calendar
from dotenv import load_dotenv

# ✅ Cargar variables de entorno desde .env
load_dotenv()

from app.drive_uploader import upload_to_drive, upload_inteligente
from app.pdf_merger import merge_pdfs_from_uploads
from app.email_templates import get_confirmation_template, get_alert_template
from app.database import (
    get_db, init_db, engine, Case, CaseDocument, Employee, Company,
    EstadoCaso, EstadoDocumento, TipoIncapacidad, CorreoNotificacion
)
from app.validador import router as validador_router, obtener_emails_empresa_directorio
from app.sync_excel import sincronizar_empleado_desde_excel  # ✅ NUEVO
from app.serial_generator import generar_serial_unico  # ✅ NUEVO
from app.ocr_service import extraer_texto_pdf
from app.mistral_ocr_service import mistral_ocr as _mistral_ocr_instance
from app.gemini_plano_service import gemini_plano as _gemini_plano_instance

from app.email_service import enviar_notificacion  # ✅ Backend nativo
from fastapi import Request, Header
from app.database import CaseEvent

# ⭐ AGREGAR ESTO - Reportes y Scheduler
from app.routes.reportes import router as reportes_router
from app.routes.cie10 import router as cie10_router
from app.routes.alertas import router as alertas_router
from app.routes.admin import router as admin_router
from app.routes.ocr import router as ocr_router
from app.routes.tenants import router as tenants_router, public_router as tenants_public_router
from app.routes.radicacion import router as radicacion_router
from app.routes.demo import demo_router, leads_router  # ✅ Demo/Leads
from app.routes.browserbase import router as browserbase_router  # ✅ Browserbase Agents (navegador cloud)
from app.tasks.scheduler_tasks import iniciar_scheduler, detener_scheduler

# ✅ Cola resiliente persistente (Drive)
from app.resilient_queue import resilient_queue, guardar_pendiente_drive


def _aplicar_ocr_a_metadata(metadata: dict, pdf_path: Path) -> dict:
    """GLM-OCR sobre el PDF fusionado; guarda resumen y texto en metadata_form."""
    resultado = extraer_texto_pdf(str(pdf_path))
    metadata["ocr_glm"] = {
        "exito": resultado["exito"],
        "paginas": resultado["paginas"],
        "error": resultado["error"] or None,
    }
    if resultado["exito"] and resultado.get("texto"):
        metadata["texto_ocr_glm"] = resultado["texto"]
    elif not resultado["exito"]:
        print(f"⚠️ OCR GLM: {resultado['error']}")
    return resultado


def _aplicar_mistral_ocr_a_metadata(metadata: dict, pdf_path: Path) -> dict:
    """OCR con Mistral Document AI sobre el PDF fusionado (envío base64).

    Usa base64 en lugar de URL porque los links de Drive no son accesibles
    públicamente por la API de Mistral.
    """
    import base64

    if _mistral_ocr_instance is None:
        err = "MISTRAL_API_KEY no configurada"
        print(f"⚠️ Mistral OCR: {err}")
        metadata["ocr_mistral"] = {"exito": False, "paginas": 0, "error": err}
        return {"exito": False, "texto": "", "paginas": 0, "modelo": "", "error": err}

    try:
        pdf_b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        resultado = _mistral_ocr_instance.procesar_pdf_base64(pdf_b64)
    except Exception as e:
        resultado = {"exito": False, "texto": "", "paginas": 0, "modelo": "", "error": str(e)}

    metadata["ocr_mistral"] = {
        "exito": resultado["exito"],
        "paginas": resultado["paginas"],
        "modelo": resultado.get("modelo", ""),
        "error": resultado.get("error") or None,
    }
    if resultado["exito"] and resultado.get("texto"):
        metadata["texto_ocr_mistral"] = resultado["texto"]
        print(f"✅ Mistral OCR: {resultado['paginas']} página(s), modelo={resultado.get('modelo','')}")
    else:
        print(f"⚠️ Mistral OCR: {resultado.get('error')}")
    return resultado


def _estructurar_plano_con_gemini(metadata: dict, texto_ocr: str) -> None:
    """Pasa el texto OCR de Mistral a Gemini 3 Flash para estructurar el plano de incapacidades.
    Guarda el resultado en metadata['plano_incapacidad'].
    """
    if _gemini_plano_instance is None:
        print("[Gemini Plano] GEMINI_API_KEY no configurada — se omite estructuración")
        metadata["plano_incapacidad"] = {"exito": False, "error": "GEMINI_API_KEY no configurada"}
        return

    resultado = _gemini_plano_instance.estructurar_plano(texto_ocr)
    metadata["plano_incapacidad"] = resultado
    if resultado["exito"]:
        plano = resultado.get("plano", {})
        print(
            f"[Gemini Plano] OK: origen={plano.get('origen')}, "
            f"dias={plano.get('dias_incapacidad')}, cie10={plano.get('codigo_cie10')}"
        )
    else:
        print(f"[Gemini Plano] Error: {resultado.get('error')}")


def _ocr_respuesta_api(resultado: dict) -> dict:
    """Payload ligero para el frontend (sin volcar todo el texto)."""
    texto = (resultado.get("texto") or "")
    preview = texto[:500] + ("…" if len(texto) > 500 else "")
    exito = bool(resultado.get("exito"))
    return {
        "exito": exito,
        "paginas": int(resultado.get("paginas") or 0),
        "error": resultado.get("error") or None,
        "texto_preview": preview if exito and texto else None,
    }


def _mensaje_drive_usuario(error_texto: str) -> str:
    """Normaliza errores técnicos de Drive a mensaje claro para frontend."""
    if not error_texto:
        return "No se pudo subir el archivo a Drive."
    err = error_texto.lower()
    if "service accounts do not have storage quota" in err or "storagequotaexceeded" in err:
        return "Drive rechazó la subida: la cuenta de servicio no tiene cuota en esa ubicación. Usa una carpeta dentro de la Unidad Compartida."
    if "json inválido en credenciales de cuenta de servicio" in err or "expecting property name enclosed in double quotes" in err:
        return "Credenciales de cuenta de servicio inválidas. Revisa el JSON de GOOGLE_SERVICE_ACCOUNT_JSON en variables de entorno."
    return f"No se pudo subir el archivo a Drive: {error_texto[:240]}"


# ==================== FUNCIÓN: DOCUMENTOS REQUERIDOS ====================
def obtener_documentos_requeridos(tipo: str, dias: int = None, phantom: bool = None, mother_works: bool = None) -> list:
    """
    Retorna lista de documentos requeridos según el tipo
    """
    if tipo == 'maternity':
        return [
            'Licencia o incapacidad de maternidad',
            'Epicrisis o resumen clínico',
            'Cédula de la madre',
            'Registro civil',
            'Certificado de nacido vivo'
        ]
    
    elif tipo == 'paternity':
        docs = [
            'Epicrisis o resumen clínico',
            'Cédula del padre',
            'Registro civil',
            'Certificado de nacido vivo'
        ]
        if mother_works:
            docs.append('Licencia o incapacidad de maternidad')
        return docs
    
    elif tipo == 'general':
        if dias and dias <= 2:
            return ['Incapacidad médica']
        else:
            return ['Incapacidad médica', 'Epicrisis o resumen clínico']
    
    elif tipo == 'labor':
        if dias and dias <= 2:
            return ['Incapacidad médica']
        else:
            return ['Incapacidad médica', 'Epicrisis o resumen clínico']
    
    elif tipo == 'traffic':
        docs = ['Incapacidad médica', 'Epicrisis o resumen clínico', 'FURIPS']
        if not phantom:
            docs.append('SOAT')
        return docs
    
    else:
        return ['Incapacidad médica']  # Default
app = FastAPI(title="IncaNeurobaeza API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# ⭐ AGREGAR ESTO - Router de reportes
app.include_router(reportes_router)

# ⭐ CIE-10 - Motor de diagnósticos y detección de prórrogas
app.include_router(cie10_router)

# ⭐ Alertas 180 días - Emails a Talento Humano
app.include_router(alertas_router)

# ⭐ Panel Admin - Auth, Correos, Usuarios, Consola
app.include_router(admin_router)
app.include_router(tenants_router)
app.include_router(tenants_public_router)  # ✅ Branding público por slug (/public/portal/{slug})
app.include_router(demo_router)   # ✅ Solicitudes de demo (público)
app.include_router(leads_router)  # ✅ Gestión de leads (admin)

# ⭐ Radicación — Skills, Sesiones, Manifests, Monitoreo
app.include_router(radicacion_router)

# ⭐ OCR con Mistral - Extracción de texto de documentos
app.include_router(ocr_router)

# ⭐ Browserbase — Agentes de navegador autónomos en la nube
app.include_router(browserbase_router)

app.include_router(validador_router)

# ==================== HEALTH CHECK DE GOOGLE DRIVE ====================

from fastapi import APIRouter
from app.drive_uploader import (
    get_authenticated_service, 
    clear_service_cache, 
    clear_token_cache,
    TOKEN_FILE,
    is_service_account_mode,
)
import json

drive_router = APIRouter(prefix="/drive", tags=["Google Drive"])

@drive_router.get("/health")
async def drive_health_check():
    """
    Verifica el estado de la conexión con Google Drive
    Útil para monitoreo con Uptime Robot, etc.
    """
    try:
        service = get_authenticated_service()
        
        # Test: listar 1 archivo
        service.files().list(pageSize=1, fields="files(id)").execute()
        
        # Obtener info del token
        token_info = None
        if TOKEN_FILE.exists():
            try:
                with open(TOKEN_FILE, 'r') as f:
                    token_data = json.load(f)
                    expiry_str = token_data.get('expiry')
                    if expiry_str:
                        expiry = datetime.fromisoformat(expiry_str)
                        now = datetime.now()
                        remaining = (expiry - now).total_seconds()
                        token_info = {
                            'expires_in_minutes': round(remaining / 60, 1),
                            'expires_at': expiry_str,
                            'status': 'valid' if remaining > 0 else 'expired'
                        }
            except Exception as e:
                token_info = {'error': str(e)}
        
        return {
            "status": "healthy",
            "service": "connected",
            "token_info": token_info,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

@drive_router.post("/refresh-cache")
async def refresh_drive_cache():
    """
    Fuerza la renovación del cache del servicio
    Útil si hay problemas y quieres forzar reconexión
    """
    try:
        clear_service_cache()
        service = get_authenticated_service()
        return {
            "status": "ok",
            "message": "Cache renovado exitosamente"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

@drive_router.post("/clear-all-cache")
async def clear_all_drive_cache():
    """
    Limpia TODO el cache (servicio + token)
    Útil para debugging o si necesitas forzar re-autenticación completa
    """
    try:
        clear_service_cache()
        clear_token_cache()
        service = get_authenticated_service()
        return {
            "status": "ok",
            "message": "Todo el cache limpiado y servicio recreado"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

# Agregar el router al app
app.include_router(drive_router)
DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "base_empleados.xlsx")

# ==================== INICIALIZACIÓN ====================

from app.sync_scheduler import iniciar_sincronizacion_automatica
from app.scheduler_recordatorios import iniciar_scheduler_recordatorios  # ✅ NUEVO
from app.scheduler_token_drive import iniciar_scheduler_token

scheduler_sync = None
scheduler_recordatorios = None  # ✅ NUEVO
scheduler_token = None

@app.on_event("startup")
def startup_event():
    global scheduler_sync, scheduler_recordatorios, scheduler_token
    init_db()
    print("🚀 API iniciada")

    usa_cuenta_servicio = is_service_account_mode()
    print(f"🔐 Modo Google Auth: {'service_account' if usa_cuenta_servicio else 'refresh_token'}")
    
    # ⭐ AUTO-MIGRACIÓN: Agregar columnas nuevas si no existen
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            migraciones = [
                # Employees - Kactus
                "ALTER TABLE employees ADD COLUMN IF NOT EXISTS cargo VARCHAR(150);",
                "ALTER TABLE employees ADD COLUMN IF NOT EXISTS centro_costo VARCHAR(100);",
                "ALTER TABLE employees ADD COLUMN IF NOT EXISTS fecha_ingreso TIMESTAMP;",
                "ALTER TABLE employees ADD COLUMN IF NOT EXISTS tipo_contrato VARCHAR(50);",
                "ALTER TABLE employees ADD COLUMN IF NOT EXISTS ciudad VARCHAR(100);",
                # Cases - Kactus (solo lo que viene del Excel: numero_incapacidad, codigo_cie10, fechas)
                "ALTER TABLE cases ADD COLUMN IF NOT EXISTS codigo_cie10 VARCHAR(20);",
                "ALTER TABLE cases ADD COLUMN IF NOT EXISTS es_prorroga BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE cases ADD COLUMN IF NOT EXISTS numero_incapacidad VARCHAR(50);",
                # Traslapo + Kactus enhanced
                "ALTER TABLE cases ADD COLUMN IF NOT EXISTS fecha_inicio_kactus TIMESTAMP;",
                "ALTER TABLE cases ADD COLUMN IF NOT EXISTS fecha_fin_kactus TIMESTAMP;",
                "ALTER TABLE cases ADD COLUMN IF NOT EXISTS dias_traslapo INTEGER DEFAULT 0;",
                "ALTER TABLE cases ADD COLUMN IF NOT EXISTS traslapo_con_serial VARCHAR(50);",
                "ALTER TABLE cases ADD COLUMN IF NOT EXISTS kactus_sync_at TIMESTAMP;",
                # Recordatorios mejorados
                "ALTER TABLE cases ADD COLUMN IF NOT EXISTS recordatorios_count INTEGER DEFAULT 0;",
                # ✅ COLUMNAS - Rastreo de intentos incompletos
                "ALTER TABLE cases ADD COLUMN IF NOT EXISTS intentos_incompletos INTEGER DEFAULT 0;",
                "ALTER TABLE cases ADD COLUMN IF NOT EXISTS fecha_ultimo_incompleto TIMESTAMP;",
                # ✅ logo_url — ampliar de VARCHAR(500) a TEXT para soportar base64
                "ALTER TABLE tenant_configs ALTER COLUMN logo_url TYPE TEXT;",
                # ✅ Soporte EPS — certificado bancario adjunto por empresa+EPS
                "ALTER TABLE empresa_bot_config ADD COLUMN IF NOT EXISTS soporte_drive_url VARCHAR(500);",
                "ALTER TABLE empresa_bot_config ADD COLUMN IF NOT EXISTS soporte_nombre VARCHAR(200);",
                "ALTER TABLE empresa_bot_config ADD COLUMN IF NOT EXISTS soporte_actualizado_en TIMESTAMP;",
                # ✅ Multi-tenant: slug por empresa (URL propia) + paleta por portal
                "ALTER TABLE companies ADD COLUMN IF NOT EXISTS slug VARCHAR(120);",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_slug ON companies (slug);",
                "ALTER TABLE tenant_configs ADD COLUMN IF NOT EXISTS paletas_portales JSON;",
                # ✅ Multi-tenant: cédula única POR EMPRESA (no global)
                "ALTER TABLE employees DROP CONSTRAINT IF EXISTS employees_cedula_key;",
                "DROP INDEX IF EXISTS ix_employees_cedula;",
                "CREATE INDEX IF NOT EXISTS ix_employees_cedula ON employees (cedula);",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_employee_company_cedula ON employees (company_id, cedula);",
                # ✅ Estado de aprovisionamiento (Sheet/Drive) con reintentos
                "ALTER TABLE tenant_configs ADD COLUMN IF NOT EXISTS sheet_status VARCHAR(20);",
                "ALTER TABLE tenant_configs ADD COLUMN IF NOT EXISTS drive_status VARCHAR(20);",
                "ALTER TABLE tenant_configs ADD COLUMN IF NOT EXISTS provision_error TEXT;",
                # Backfill: configs existentes con Sheet/Drive ya funcionando quedan en 'ok'
                "UPDATE tenant_configs SET sheet_status='ok' WHERE google_sheets_id IS NOT NULL AND sheet_status IS NULL;",
                "UPDATE tenant_configs SET sheet_status='pendiente' WHERE sheet_status IS NULL;",
                "UPDATE tenant_configs SET drive_status='ok' WHERE drive_verificado = TRUE AND drive_status IS NULL;",
                "UPDATE tenant_configs SET drive_status='pendiente' WHERE drive_status IS NULL;",
            ]
            for sql in migraciones:
                conn.execute(text(sql))
            conn.commit()
        print("✅ Auto-migración completada (columnas verificadas)")

        # ⭐ BACKFILL: asignar slug a las empresas existentes que no lo tengan
        try:
            from app.database import SessionLocal, Company, asignar_slug
            _db = SessionLocal()
            try:
                sin_slug = _db.query(Company).filter(Company.slug == None).all()
                for c in sin_slug:
                    asignar_slug(_db, c)
                if sin_slug:
                    _db.commit()
                    print(f"✅ Slugs asignados a {len(sin_slug)} empresas existentes")
            finally:
                _db.close()
        except Exception as e:
            print(f"⚠️ Backfill de slugs: {e}")


        # ⭐ AUTO-MIGRACIÓN: Agregar valores faltantes al enum tipoincapacidad
        # IMPORTANTE: ALTER TYPE ADD VALUE no puede correr dentro de una transacción
        # en PostgreSQL. Necesitamos AUTOCOMMIT para que funcione correctamente.
        try:
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                enum_values = ['other', 'prelicencia', 'maternidad', 'paternidad',
                               'certificado', 'enfermedad_especial']
                for val in enum_values:
                    try:
                        conn.execute(text(f"ALTER TYPE tipoincapacidad ADD VALUE IF NOT EXISTS '{val}';"))
                        print(f"  ✅ Enum '{val}' verificado/agregado")
                    except Exception as e:
                        print(f"  ℹ️ Enum '{val}': {e}")
        except Exception as e:
            print(f"  ⚠️ Enum migration (modo transacción): {e}")
        print("✅ Auto-migración de enum completada")
        
        # ⭐ LIMPIEZA: Eliminar columnas obsoletas que ya no vienen de Kactus
        with engine.connect() as conn:
            for col in ["dias_kactus", "medico_tratante", "institucion_origen", "diagnostico_kactus"]:
                try:
                    conn.execute(text(f"ALTER TABLE cases DROP COLUMN IF EXISTS {col}"))
                except Exception:
                    pass
            # Eliminar dias_kactus de employees también (ya estaba comentado en modelo)
            try:
                conn.execute(text("ALTER TABLE employees DROP COLUMN IF EXISTS dias_kactus"))
            except Exception:
                pass
            conn.commit()
        print("✅ Limpieza columnas obsoletas completada")
        
        # ⭐ AUTO-MIGRACIÓN: Tabla correos_notificacion
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS correos_notificacion (
                    id SERIAL PRIMARY KEY,
                    area VARCHAR(50) NOT NULL,
                    nombre_contacto VARCHAR(200),
                    email VARCHAR(300) NOT NULL,
                    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
                    activo BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_correos_notif_area ON correos_notificacion(area);"))
            conn.commit()
        print("✅ Tabla correos_notificacion verificada")
        
        # ⭐ LIMPIEZA: Empresas duplicadas (nombres con \n o espacios)
        try:
            with engine.connect() as conn:
                # 1. Encontrar duplicados por nombre limpio (ANTES de renombrar)
                dupes = conn.execute(text("""
                    SELECT TRIM(BOTH FROM REPLACE(nombre, E'\\n', '')) as nombre_limpio,
                           MIN(id) as keep_id, ARRAY_AGG(id ORDER BY id) as all_ids
                    FROM companies
                    GROUP BY TRIM(BOTH FROM REPLACE(nombre, E'\\n', ''))
                    HAVING COUNT(*) > 1
                """)).fetchall()
                
                for row in dupes:
                    nombre = row[0]
                    keep_id = row[1]
                    all_ids = row[2]
                    remove_ids = [i for i in all_ids if i != keep_id]
                    
                    if remove_ids:
                        # Mover empleados, casos, correos al ID que se conserva
                        for rid in remove_ids:
                            conn.execute(text(f"UPDATE employees SET company_id = {keep_id} WHERE company_id = {rid}"))
                            conn.execute(text(f"UPDATE cases SET company_id = {keep_id} WHERE company_id = {rid}"))
                            conn.execute(text(f"UPDATE correos_notificacion SET company_id = {keep_id} WHERE company_id = {rid}"))
                            try:
                                conn.execute(text(f"UPDATE alerta_emails SET company_id = {keep_id} WHERE company_id = {rid}"))
                            except Exception:
                                pass
                            conn.execute(text(f"DELETE FROM companies WHERE id = {rid}"))
                        conn.commit()
                        print(f"   🧹 Empresa '{nombre}': mergeado IDs {remove_ids} → {keep_id}")
                
                # 2. Ahora que no hay duplicados, strip los nombres restantes
                conn.execute(text("UPDATE companies SET nombre = TRIM(BOTH FROM REPLACE(nombre, E'\\n', ''))"))
                conn.commit()
                
                if not dupes:
                    print("   ✅ Sin empresas duplicadas")
        except Exception as e:
            print(f"   ⚠️ Error limpiando duplicados: {e}")
        print("✅ Limpieza empresas duplicadas completada")
        
        # ⭐ AUTO-MIGRACIÓN: Tablas CIE-10 / Alertas 180 días
        with engine.connect() as conn:
            tablas_cie10 = [
                """CREATE TABLE IF NOT EXISTS alerta_emails (
                    id SERIAL PRIMARY KEY,
                    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
                    email VARCHAR(300) NOT NULL,
                    nombre_contacto VARCHAR(200),
                    tipo VARCHAR(50) DEFAULT 'talento_humano',
                    activo BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );""",
                """CREATE TABLE IF NOT EXISTS alertas_180_log (
                    id SERIAL PRIMARY KEY,
                    cedula VARCHAR(30) NOT NULL,
                    tipo_alerta VARCHAR(50) NOT NULL,
                    dias_acumulados INTEGER,
                    cadena_codigos_cie10 VARCHAR(500),
                    emails_enviados TEXT,
                    enviado_ok BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW()
                );""",
                "CREATE INDEX IF NOT EXISTS idx_alerta_emails_company ON alerta_emails(company_id);",
                "CREATE INDEX IF NOT EXISTS idx_alertas_180_log_cedula ON alertas_180_log(cedula);",
                "CREATE INDEX IF NOT EXISTS idx_alertas_180_log_created ON alertas_180_log(created_at);",
            ]
            for sql in tablas_cie10:
                try:
                    conn.execute(text(sql))
                except Exception:
                    pass
            conn.commit()
        print("✅ Tablas CIE-10/Alertas inicializadas")
    except Exception as e:
        print(f"⚠️ Auto-migración: {e}")
    
    # ⭐ AGREGAR - Scheduler de tabla viva
    try:
        iniciar_scheduler()
        print("✅ Scheduler de tabla viva activado")
    except Exception as e:
        print(f"⚠️ Error iniciando scheduler tabla viva: {e}")
    
    try:
        # Sincronización Excel
        scheduler_sync = iniciar_sincronizacion_automatica()
        print("✅ Sincronización automática activada")
    except Exception as e:
        print(f"⚠️ Error iniciando sync: {e}")
    
    try:
        # ✅ NUEVO: Scheduler de recordatorios
        scheduler_recordatorios = iniciar_scheduler_recordatorios()
        print("✅ Sistema de recordatorios activado")
    except Exception as e:
        print(f"⚠️ Error iniciando recordatorios: {e}")
    
    try:
        # ✅ NUEVO: Scheduler de renovación de token
        scheduler_token = iniciar_scheduler_token()
        if scheduler_token:
            print("✅ Sistema de auto-renovación de token activado")
        else:
            print("✅ Scheduler de token omitido (modo cuenta de servicio)")
    except Exception as e:
        print(f"⚠️ Error iniciando scheduler token: {e}")
    
    try:
        # ✅ NUEVO: Cola resiliente (BD) para Drive
        from app.resilient_queue import resilient_queue
        resilient_queue.iniciar()
        print("✅ Cola resiliente (BD) activada — reintentos automáticos de Drive")
    except Exception as e:
        print(f"⚠️ Error iniciando cola resiliente: {e}")
    
    # ⭐ Scheduler de alertas 180 días (diario a las 7am)
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from app.services.alerta_180_service import ejecutar_revision_alertas
        from app.database import SessionLocal
        
        def _revision_diaria_180():
            try:
                db = SessionLocal()
                resultado = ejecutar_revision_alertas(db, "all")
                print(f"📧 Revisión 180 días: {resultado['alertas_enviadas']} alertas enviadas, {resultado['alertas_omitidas']} omitidas")
                db.close()
            except Exception as e:
                print(f"⚠️ Error revisión 180 días: {e}")
        
        scheduler_180 = BackgroundScheduler()
        scheduler_180.add_job(_revision_diaria_180, 'cron', hour=7, minute=0, id='alerta_180_diaria')
        scheduler_180.start()
        print("✅ Alertas 180 días programadas (diario 7:00 AM)")
    except Exception as e:
        print(f"⚠️ Error iniciando scheduler alertas 180: {e}")
    
    # ⭐ Limpieza automática de carpetas de exportación temporales (cada 6 horas)
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from app.validador import limpiar_exportaciones_temporales_sync
        
        scheduler_limpieza = BackgroundScheduler()
        scheduler_limpieza.add_job(limpiar_exportaciones_temporales_sync, 'interval', hours=6, id='limpieza_exportaciones')
        scheduler_limpieza.start()
        print("✅ Limpieza de exportaciones temporales programada (cada 6h)")
    except Exception as e:
        print(f"⚠️ Error iniciando limpieza exportaciones: {e}")

@app.on_event("shutdown")
def shutdown_event():
    global scheduler_sync, scheduler_recordatorios, scheduler_token
    
    # ⭐ AGREGAR - Detener scheduler tabla viva
    try:
        detener_scheduler()
        print("🛑 Scheduler de tabla viva detenido")
    except Exception as e:
        print(f"⚠️ Error deteniendo scheduler tabla viva: {e}")
    
    if scheduler_sync:
        scheduler_sync.shutdown()
        print("🛑 Sincronización detenida")
    
    if scheduler_recordatorios:  # ✅ NUEVO
        scheduler_recordatorios.shutdown()
        print("🛑 Recordatorios detenidos")
    
    if scheduler_token:
        scheduler_token.shutdown()
        print("🛑 Renovación de token detenida")

# ==================== FACTORY RESET ====================

@app.post("/admin/factory-reset")
async def factory_reset(
    body: dict,
    authorization: str = Header(...),
):
    """
    Borra TODA la data operativa del sistema (empresas, empleados, casos, tenants).
    Preserva: superadmins, configs LLM, OAuth, skills de radicación.
    Requiere confirmacion: "RESET" en el body.
    """
    from app.validador import verificar_token_admin
    verificar_token_admin(authorization)

    if body.get("confirmacion") != "RESET":
        raise HTTPException(status_code=400, detail="Debes enviar confirmacion: 'RESET'")

    db = SessionLocal()
    resumen = {}
    try:
        from sqlalchemy import text

        # Capturar los Sheets de los tenants ANTES de borrar tenant_configs,
        # para eliminarlos también de Drive (si no, quedan huérfanos en la Unidad Compartida)
        sheets_a_borrar = []
        try:
            rows = db.execute(text(
                "SELECT google_sheets_id FROM tenant_configs "
                "WHERE google_sheets_id IS NOT NULL AND google_sheets_id != ''"
            )).fetchall()
            sheets_a_borrar = [r[0] for r in rows]
        except Exception as e:
            print(f"⚠️ No se pudieron listar Sheets de tenants: {e}")

        tablas_en_orden = [
            # Sub-tablas de casos primero
            "case_events",
            "case_notes",
            "case_documents",
            "resultados_validacion",
            "plano_incapacidades",
            "extractos_incapacidades",
            "search_history",
            "radicacion_sesiones",
            # Alertas y colas
            "alertas_180_log",
            "alerta_emails",
            "pendientes_envio",
            "radicacion_cola",
            # Datos principales
            "cases",
            "correos_notificacion",
            "empresa_bot_config",
            "employees",
            # Demo (antes de companies por FK)
            "demo_sessions",
            # Tenant
            "tenant_invitations",
            "tenant_configs",
            # Leads (después de tenant_invitations que las referencia)
            "demo_requests",
            # Empresas
            "companies",
        ]

        for tabla in tablas_en_orden:
            try:
                result = db.execute(text(f"DELETE FROM {tabla}"))
                resumen[tabla] = result.rowcount
            except Exception as e:
                resumen[tabla] = f"error: {str(e)[:80]}"

        # Admin users: solo los de tenants (no superadmins del sistema)
        result = db.execute(text("DELETE FROM admin_users WHERE es_tenant_admin = TRUE"))
        resumen["admin_users_tenant"] = result.rowcount

        db.commit()

        # Borrar los Sheets de Drive (best-effort, después del commit para no revertir la BD)
        sheets_borrados = 0
        if sheets_a_borrar:
            try:
                from app.services.tenant_provisioning import _get_drive_service
                drive = _get_drive_service()
                for sheet_id in sheets_a_borrar:
                    try:
                        drive.files().delete(fileId=sheet_id, supportsAllDrives=True).execute()
                        sheets_borrados += 1
                    except Exception as e:
                        print(f"⚠️ No se pudo borrar Sheet {sheet_id}: {str(e)[:100]}")
            except Exception as e:
                print(f"⚠️ Sin servicio Drive para borrar Sheets: {e}")
        resumen["sheets_drive_borrados"] = sheets_borrados

        print(f"🔴 FACTORY RESET ejecutado. Resumen: {resumen}")
        return {"ok": True, "resumen": resumen}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error en factory reset: {str(e)}")
    finally:
        db.close()


# ==================== TEST RECORDATORIOS ====================

@app.post("/admin/test-recordatorios")
async def test_recordatorios(
    authorization: str = Header(...)
):
    """Ejecuta manualmente la verificación de recordatorios (para testing)"""
    from app.validador import verificar_token_admin
    verificar_token_admin(authorization)
    from app.scheduler_recordatorios import verificar_casos_pendientes
    try:
        verificar_casos_pendientes()
        return {"status": "ok", "mensaje": "Verificación de recordatorios ejecutada. Revisa los logs del servidor."}
    except Exception as e:
        return {"status": "error", "error": str(e)}

# ==================== UTILIDADES ====================

def get_current_quinzena():
    today = date.today()
    mes_nombre = calendar.month_name[today.month]
    return f"primera quincena de {mes_nombre}" if today.day <= 15 else f"segunda quincena de {mes_nombre}"

def send_html_email(to_email: str, subject: str, html_body: str, caso=None, db: Session = None):
    """Envía email + WhatsApp con soporte para copias"""
    tipo_map = {
        'Confirmación': 'confirmacion',
        'Copia': 'confirmacion',
        'ALERTA': 'extra',
        'Incompleta': 'incompleta',
        'Ilegible': 'ilegible',
        'Validada': 'completa',
        'EPS': 'eps',
        'TTHH': 'tthh'
    }
    
    tipo_notificacion = 'confirmacion'
    for key, value in tipo_map.items():
        if key in subject:
            tipo_notificacion = value
            break
    
    # ✅ OBTENER EMAIL DE COPIA DE LA EMPRESA Y TELÉFONO
    cc_email = None
    whatsapp = None
    correo_bd = None
    
    db_local = db
    cerrar_db_local = False

    if caso:
        if db_local is None:
            from app.database import SessionLocal
            db_local = SessionLocal()
            cerrar_db_local = True

        # ✅ CC EMPRESA: Ahora viene del DIRECTORIO (no de BD)
        if hasattr(caso, 'company_id') and caso.company_id:
            emails_dir = obtener_emails_empresa_directorio(caso.company_id, db=db_local)
            if emails_dir:
                cc_email = ",".join(emails_dir)  # ✅ TODOS los emails del directorio
                print(f"📧 CC desde DIRECTORIO: {cc_email} (empresa_id={caso.company_id})")
            else:
                print(f"⚠️ Sin emails en directorio para empresa_id={caso.company_id}")
        
        # ✅ OBTENER TELÉFONO DEL FORMULARIO (prioritario)
        if hasattr(caso, 'telefono_form') and caso.telefono_form:
            whatsapp = caso.telefono_form
            print(f"📱 WhatsApp desde formulario: {whatsapp}")
        
        # ✅ OBTENER CORREO DE BD
        if hasattr(caso, 'empleado') and caso.empleado:
            if hasattr(caso.empleado, 'correo') and caso.empleado.correo:
                correo_bd = caso.empleado.correo
                print(f"📧 Correo BD: {correo_bd}")

    if cerrar_db_local and db_local is not None:
        db_local.close()
    
    resultado = enviar_notificacion(
        tipo_notificacion=tipo_notificacion,
        email=to_email,
        serial=caso.serial if caso else 'AUTO',
        subject=subject,
        html_content=html_body,
        cc_email=cc_email,
        correo_bd=correo_bd,
        whatsapp=whatsapp,
        whatsapp_message=None,
        adjuntos_base64=[]
    )
    
    if resultado:
        canales = "Email"
        if whatsapp:
            canales += " + WhatsApp"
        print(f"✅ {canales} enviado: {to_email} (CC: {cc_email or 'ninguno'}, Tel: {whatsapp or 'ninguno'})")
        return True, None
    else:
        print(f"❌ Error enviando notificación")
        return False, "Error notificación"
    

def enviar_email_cambio_tipo(email: str, nombre: str, serial: str, tipo_anterior: str, tipo_nuevo: str, docs_requeridos: list):
    """
    Envía email informando del cambio de tipo de incapacidad
    """
    # Mapeo de tipos a nombres legibles
    tipos_nombres = {
        'maternity': 'Maternidad',
        'paternity': 'Paternidad',
        'general': 'Enfermedad General',
        'traffic': 'Accidente de Tránsito',
        'labor': 'Accidente Laboral'
    }
    
    tipo_ant_nombre = tipos_nombres.get(tipo_anterior, tipo_anterior)
    tipo_nuevo_nombre = tipos_nombres.get(tipo_nuevo, tipo_nuevo)
    
    # Generar lista de documentos
    docs_html = "<ul style='margin: 10px 0; padding-left: 20px;'>"
    for doc in docs_requeridos:
        docs_html += f"<li style='margin: 5px 0;'>{doc}</li>"
    docs_html += "</ul>"
    
    asunto = f"🔄 Cambio de Tipo de Incapacidad - {serial}"
    
    cuerpo = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 10px;">
            <h2 style="color: #f59e0b;">🔄 Actualización de Tipo de Incapacidad</h2>
            
            <p>Hola <strong>{nombre}</strong>,</p>
            
            <p>Hemos actualizado el tipo de tu incapacidad <strong>{serial}</strong>:</p>
            
            <div style="background-color: #fef3c7; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p style="margin: 0;">
                    <strong>Tipo anterior:</strong> {tipo_ant_nombre}<br>
                    <strong>Nuevo tipo:</strong> {tipo_nuevo_nombre}
                </p>
            </div>
            
            <p>Debido a este cambio, los documentos requeridos son:</p>
            
            {docs_html}
            
            <div style="background-color: #dbeafe; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <h3 style="margin-top: 0; color: #1e40af;">📝 Qué debes hacer:</h3>
                <ol style="margin: 10px 0; padding-left: 20px;">
                    <li style="margin: 5px 0;">Revisa la nueva lista de documentos</li>
                    <li style="margin: 5px 0;">Prepara TODOS los documentos solicitados</li>
                    <li style="margin: 5px 0;">Ingresa al portal con tu cédula</li>
                    <li style="margin: 5px 0;">Completa la incapacidad subiendo los documentos</li>
                </ol>
            </div>
            
            <p style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 12px;">
                Este es un correo automático del sistema de gestión de incapacidades.<br>
                No respondas a este mensaje.
            </p>
        </div>
    </body>
    </html>
    """
    
    send_html_email(email, asunto, cuerpo)

def mapear_tipo_incapacidad(tipo_frontend: str) -> TipoIncapacidad:
    tipo_map = {
        'maternity': TipoIncapacidad.MATERNIDAD,
        'paternidad': TipoIncapacidad.PATERNIDAD,
        'paternity': TipoIncapacidad.PATERNIDAD,
        'general': TipoIncapacidad.ENFERMEDAD_GENERAL,
        'labor': TipoIncapacidad.ENFERMEDAD_LABORAL,
        'traffic': TipoIncapacidad.ACCIDENTE_TRANSITO,
        'especial': TipoIncapacidad.ENFERMEDAD_ESPECIAL,
        'prelicencia': TipoIncapacidad.PRELICENCIA,  # ✅ NUEVO
        'certificado': TipoIncapacidad.CERTIFICADO,  # ✅ NUEVO
    }
    return tipo_map.get(tipo_frontend.lower(), TipoIncapacidad.ENFERMEDAD_GENERAL)

# ==================== ENDPOINTS ====================

@app.get("/")
def root():
    return {
        "message": "✅ API IncaNeurobaeza v2.0 - Trabajando para ayudarte",
        "status": "online",
        "cors": "enabled"
    }
@app.get("/ping")
async def ping():
    """Endpoint para mantener vivo el servidor - usado por UptimeRobot"""
    from datetime import datetime
    return {"status": "alive", "timestamp": datetime.now().isoformat()}

@app.get("/status")
async def status_dashboard(db: Session = Depends(get_db)):
    """Dashboard de estado del sistema"""
    from datetime import datetime
    
    # Verificar BD
    try:
        total_casos = db.query(Case).count()
        db_status = "✅ connected"
    except:
        total_casos = 0
        db_status = "❌ error"
    
    # Verificar Drive
    try:
        from app.drive_uploader import TOKEN_FILE
        drive_status = "✅ authenticated" if TOKEN_FILE.exists() else "⚠️ no token"
    except:
        drive_status = "❌ error"
    
    return {
        "timestamp": datetime.now().isoformat(),
        "services": {
            "api": "✅ online",
            "database": db_status,
            "google_drive": drive_status,
            "scheduler": "✅ running",
            "uptime_robot": "✅ monitoring"
        },
        "stats": {
            "total_casos": total_casos,
            "render_sleep": "disabled",
            "response_time": "<2s"
        }
    }

@app.get("/stats/uptime")
async def uptime_stats():
    """Estadísticas de uptime del servidor"""
    from datetime import datetime
    import os
    
    render_git_commit = os.environ.get("RENDER_GIT_COMMIT", "unknown")
    
    return {
        "status": "online",
        "timestamp": datetime.now().isoformat(),
        "render_commit": render_git_commit[:7] if render_git_commit != "unknown" else "local",
        "message": "Backend funcionando 24/7 gracias a UptimeRobot ⚡",
        "uptime_robot_enabled": True
    }

@app.post("/wake-up")
async def force_wake_up(db: Session = Depends(get_db)):
    """Fuerza renovación de todos los servicios"""
    from datetime import datetime
    from app.drive_uploader import get_authenticated_service
    from sqlalchemy import text
    
    resultados = {}
    
    # Renovar Drive
    try:
        service = get_authenticated_service()
        service.files().list(pageSize=1).execute()
        resultados["drive"] = "✅ renovado"
    except Exception as e:
        resultados["drive"] = f"❌ {str(e)[:50]}"
    
    # Test BD
    try:
        db.execute(text("SELECT 1"))
        resultados["database"] = "✅ conectada"
    except Exception as e:
        resultados["database"] = f"❌ {str(e)[:50]}"
    
    return {
        "status": "fully_awake",
        "timestamp": datetime.now().isoformat(),
        "services": resultados,
        "message": "Todos los servicios renovados ⚡"
    }

def _company_por_slug(db: Session, slug):
    """Resuelve la empresa desde el slug de la URL (?empresa=mi-empresa). None si no viene o no existe."""
    if not slug:
        return None
    return db.query(Company).filter(Company.slug == str(slug).strip().lower()).first()


@app.get("/empleados/{cedula}")
def obtener_empleado(cedula: str, empresa: str = None, db: Session = Depends(get_db)):
    """
    Consulta empleado (con sync instantánea).
    Si viene ?empresa={slug} (link por empresa de repogemin), la búsqueda queda
    AISLADA a esa empresa: solo se ven/crean empleados de ella.
    """
    company_scope = _company_por_slug(db, empresa)

    # PASO 1: Buscar en BD (scoped si hay slug; si no, preferir la fila activa)
    q = db.query(Employee).filter(Employee.cedula == cedula)
    if company_scope:
        q = q.filter(Employee.company_id == company_scope.id)
    else:
        q = q.order_by(Employee.activo.desc())
    empleado = q.first()

    if empleado:
        return {
            "nombre": empleado.nombre,
            "empresa": empleado.empresa.nombre if empleado.empresa else "No especificada",
            "correo": empleado.correo,
            "eps": empleado.eps
        }

    # PASO 2: Sincronizar desde Excel (lee el Sheet propio de la empresa si hay slug)
    print(f"📄 Sync instantánea para {cedula}...")
    empleado_sync = sincronizar_empleado_desde_excel(
        cedula, company_id=company_scope.id if company_scope else None
    )

    if empleado_sync:
        return {
            "nombre": empleado_sync.nombre,
            "empresa": empleado_sync.empresa.nombre if empleado_sync.empresa else "No especificada",
            "correo": empleado_sync.correo,
            "eps": empleado_sync.eps
        }

    return JSONResponse(status_code=404, content={"error": "Empleado no encontrado"})
@app.get("/verificar-bloqueo/{cedula}")
def verificar_bloqueo_empleado(
    cedula: str,
    empresa: str = None,
    db: Session = Depends(get_db)
):
    """
    Verifica si el empleado tiene casos pendientes que bloquean nuevos envíos.
    Con ?empresa={slug} solo cuentan los casos de ESA empresa (un caso pendiente
    en otra empresa cliente no bloquea al mismo empleado aquí).
    """
    company_scope = _company_por_slug(db, empresa)

    q = db.query(Case).filter(
        Case.cedula == cedula,
        Case.estado.in_([
            EstadoCaso.INCOMPLETA,
            EstadoCaso.ILEGIBLE,
            EstadoCaso.INCOMPLETA_ILEGIBLE
        ]),
        Case.bloquea_nueva == True
    )
    if company_scope:
        q = q.filter(Case.company_id == company_scope.id)
    caso_bloqueante = q.first()
    
    if caso_bloqueante:
        # Obtener checks seleccionados (si existen)
        checks_faltantes = []
        if hasattr(caso_bloqueante, 'metadata_form') and caso_bloqueante.metadata_form:
            checks_faltantes = caso_bloqueante.metadata_form.get('checks_seleccionados', [])
        
        # ✅ NUEVO: Obtener total de reenvíos
        total_reenvios = 0
        if caso_bloqueante.metadata_form:
            total_reenvios = caso_bloqueante.metadata_form.get('total_reenvios', 0)
        
        # ✅ NUEVO: Generar mensaje específico de documentos faltantes
        motivo_detallado = caso_bloqueante.diagnostico
        if not motivo_detallado and checks_faltantes:
            docs_faltantes = []
            for check in checks_faltantes:
                # Validar que check sea un diccionario
                if isinstance(check, dict) and check.get('estado') in ['INCOMPLETO', 'ILEGIBLE', 'PENDIENTE']:
                    docs_faltantes.append(check.get('nombre', 'Documento'))
                elif isinstance(check, str) and check in ['INCOMPLETO', 'ILEGIBLE', 'PENDIENTE']:
                    docs_faltantes.append(check)
            
            if docs_faltantes:
                motivo_detallado = f"Documentos faltantes o ilegibles: {', '.join(docs_faltantes)}"
            else:
                motivo_detallado = "Documentos faltantes o ilegibles"
        elif not motivo_detallado:
            motivo_detallado = "Documentos faltantes o ilegibles"
        
        return {
            "bloqueado": True,
            "mensaje": f"Tienes una incapacidad pendiente de completar",
            "caso_pendiente": {
                "serial": caso_bloqueante.serial,
                "tipo": caso_bloqueante.tipo.value if caso_bloqueante.tipo else "General",
                "estado": caso_bloqueante.estado.value,
                "fecha_envio": caso_bloqueante.created_at.strftime("%d/%m/%Y"),
                "fecha_inicio": caso_bloqueante.fecha_inicio.isoformat() if caso_bloqueante.fecha_inicio else None,
                "fecha_fin": caso_bloqueante.fecha_fin.isoformat() if caso_bloqueante.fecha_fin else None,
                "motivo": motivo_detallado,
                "checks_faltantes": checks_faltantes,
                "drive_link": caso_bloqueante.drive_link,
                "total_reenvios": total_reenvios
            }
        }
    
    return {
        "bloqueado": False,
        "mensaje": "Puedes continuar con el envío"
    }
@app.post("/casos/{serial}/reenviar")
async def reenviar_caso_incompleto(
    serial: str,
    archivos: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    """
    Permite al empleado reenviar una incapacidad incompleta
    - NO crea nuevo caso
    - Agrega nueva versión al caso existente
    - Alerta al validador para comparar
    """
    
    # 1. Buscar caso existente
    caso = db.query(Case).filter(
        Case.serial == serial,
        Case.estado.in_([
            EstadoCaso.INCOMPLETA,
            EstadoCaso.ILEGIBLE,
            EstadoCaso.INCOMPLETA_ILEGIBLE
        ])
    ).first()
    
    if not caso:
        return JSONResponse(
            status_code=404,
            content={"error": "Caso no encontrado o no está incompleto"}
        )
    
    try:
        # 2. Procesar nuevos archivos
        pdf_final_path, original_filenames = await merge_pdfs_from_uploads(
            archivos,
            caso.cedula,
            caso.tipo.value if caso.tipo else "general"
        )

        ocr_patch = {}
        resultado_ocr_reenvio = _aplicar_ocr_a_metadata(ocr_patch, pdf_final_path)
        
        # 3. Subir NUEVO archivo a Drive (NO reemplazar el viejo aún)
        from app.serial_generator import extraer_iniciales
        
        empresa_destino = caso.empresa.nombre if caso.empresa else "OTRA_EMPRESA"
        
        # Generar nombre único para versión nueva
        nuevo_nombre = f"{serial}_REENVIO_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        nuevo_link = upload_to_drive(
            pdf_final_path,
            empresa_destino,
            caso.cedula,
            caso.tipo.value if caso.tipo else "general",
            nuevo_nombre
        )
        
        pdf_final_path.unlink()
        
        # 4. Guardar metadata del reenvío en el caso
        if not caso.metadata_form:
            caso.metadata_form = {}
        
        caso.metadata_form['ocr_glm'] = ocr_patch.get('ocr_glm')
        if 'texto_ocr_glm' in ocr_patch:
            caso.metadata_form['texto_ocr_glm'] = ocr_patch['texto_ocr_glm']
        
        if 'reenvios' not in caso.metadata_form:
            caso.metadata_form['reenvios'] = []
        
        caso.metadata_form['reenvios'].append({
            'fecha': datetime.now().isoformat(),
            'link': nuevo_link,
            'archivos': original_filenames,
            'estado': 'PENDIENTE_REVISION',
            'ocr_glm': ocr_patch.get('ocr_glm'),
        })
        flag_modified(caso, 'metadata_form')
        
        # 5. Cambiar estado a "NUEVO" para que validador lo vea
        estado_anterior = caso.estado.value
        caso.estado = EstadoCaso.NUEVO
        caso.updated_at = datetime.now()
        
        # ✅ Resetear recordatorios para nuevo ciclo de validación
        caso.recordatorio_enviado = False
        caso.recordatorios_count = 0
        caso.fecha_recordatorio = None
        
        # 6. Registrar evento
        evento = CaseEvent(
            case_id=caso.id,
            accion="reenvio_detectado",
            estado_anterior=estado_anterior,
            estado_nuevo="NUEVO",
            actor="Empleado",
            motivo=f"Reenvío #{len(caso.metadata_form['reenvios'])}",
            metadata_json={
                'nuevo_link': nuevo_link,
                'total_reenvios': len(caso.metadata_form['reenvios'])
            }
        )
        db.add(evento)
        
        db.commit()
        
        print(f"✅ Reenvío detectado para {serial}")
        print(f"   📁 Versión anterior: {caso.drive_link}")
        print(f"   📁 Versión nueva: {nuevo_link}")
        
        # 7. Notificar al validador (email interno)
        try:
            html_alerta = f"""
            <div style="font-family: Arial; max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #f59e0b;">⚠️ REENVÍO DETECTADO</h2>
                <p><strong>Serial:</strong> {serial}</p>
                <p><strong>Empleado:</strong> {caso.empleado.nombre if caso.empleado else 'N/A'}</p>
                <p><strong>Empresa:</strong> {caso.empresa.nombre if caso.empresa else 'N/A'}</p>
                <hr>
                <p>El empleado ha reenviado documentos. Ingresa al portal para comparar versiones.</p>
                <p><a href="{nuevo_link}">📄 Ver nueva versión</a></p>
                <p><a href="{caso.drive_link}">📄 Ver versión anterior (incompleta)</a></p>
            </div>
            """
            
            enviar_notificacion(
                tipo_notificacion='extra',
                email='xoblaxbaezaospino@gmail.com',
                serial=serial,
                subject=f'🔄 Reenvío - {serial} - {caso.empleado.nombre if caso.empleado else "N/A"}',
                html_content=html_alerta,
                cc_email=None,
                correo_bd=None,
                adjuntos_base64=[]
            )
        except Exception as e:
            print(f"⚠️ Error enviando alerta: {e}")
        
        return {
            "success": True,
            "serial": serial,
            "mensaje": "Documentos reenviados exitosamente. El validador revisará tu caso.",
            "total_reenvios": len(caso.metadata_form['reenvios']),
            "nuevo_link": nuevo_link,
            "ocr_glm": _ocr_respuesta_api(resultado_ocr_reenvio),
        }
        
    except Exception as e:
        print(f"❌ Error procesando reenvío {serial}: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": f"Error procesando archivos: {str(e)}"}
        )

# ==================== CONTINUACIÓN DE main.py ====================

@app.post("/casos/{serial}/completar")
async def completar_caso_incompleto(
    serial: str,
    archivos: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    """
    Permite al empleado completar un caso incompleto 
    subiendo solo los documentos faltantes
    """
    
    # 1. Buscar el caso existente
    caso = db.query(Case).filter(
        Case.serial == serial,
        Case.estado.in_([
            EstadoCaso.INCOMPLETA,
            EstadoCaso.ILEGIBLE,
            EstadoCaso.INCOMPLETA_ILEGIBLE
        ])
    ).first()
    
    if not caso:
        return JSONResponse(
            status_code=404, 
            content={"error": "Caso no encontrado o no está incompleto"}
        )
    
    try:
        # 2. Procesar nuevos archivos
        pdf_final_path, original_filenames = await merge_pdfs_from_uploads(
            archivos, 
            caso.cedula, 
            caso.tipo.value if caso.tipo else "general"
        )

        ocr_patch = {}
        resultado_ocr_completar = _aplicar_ocr_a_metadata(ocr_patch, pdf_final_path)
        
        # 3. Actualizar archivo en Drive (MISMO file_id)
        from app.drive_manager import DriveFileManager, CaseFileOrganizer
        
        # Extraer file_id del link actual
        file_id = None
        if '/file/d/' in caso.drive_link:
            file_id = caso.drive_link.split('/file/d/')[1].split('/')[0]
        elif 'id=' in caso.drive_link:
            file_id = caso.drive_link.split('id=')[1].split('&')[0]
        
        if not file_id:
            raise Exception("No se pudo extraer file_id del link de Drive")
        
        # Actualizar contenido del archivo existente
        drive_manager = DriveFileManager()
        
        # Subir nuevo contenido al mismo file_id
        from googleapiclient.http import MediaFileUpload
        media = MediaFileUpload(str(pdf_final_path), mimetype='application/pdf', resumable=True)
        
        updated_file = drive_manager.service.files().update(
            fileId=file_id,
            media_body=media,
            fields='id, webViewLink, modifiedTime'
        ).execute()
        
        nuevo_link = updated_file.get('webViewLink', caso.drive_link)
        
        # Limpiar archivo temporal
        pdf_final_path.unlink()

        if not caso.metadata_form:
            caso.metadata_form = {}
        caso.metadata_form['ocr_glm'] = ocr_patch.get('ocr_glm')
        if 'texto_ocr_glm' in ocr_patch:
            caso.metadata_form['texto_ocr_glm'] = ocr_patch['texto_ocr_glm']
        flag_modified(caso, 'metadata_form')
        
        # 4. Cambiar estado a NUEVO para que validador revise de nuevo
        estado_anterior = caso.estado.value
        caso.estado = EstadoCaso.NUEVO
        caso.bloquea_nueva = False  # ⚠️ IMPORTANTE: Desbloquear
        caso.drive_link = nuevo_link
        caso.updated_at = datetime.now()
        
        # 5. Registrar evento
        from app.database import CaseEvent
        evento = CaseEvent(
            case_id=caso.id,
            accion="reenvio_completar",
            estado_anterior=estado_anterior,
            estado_nuevo="NUEVO",
            actor="Empleado",
            motivo="Documentos completados por el empleado"
        )
        db.add(evento)
        
        # 6. Mover en Drive de vuelta a "por validar"
        organizer = CaseFileOrganizer()
        organizer.mover_caso_segun_estado(caso, "NUEVO")
        
        db.commit()
        
        print(f"✅ Caso {serial} completado por empleado y desbloqueado")
        
        # 7. Sincronizar con Google Sheets
        try:
            from app.google_sheets_tracker import actualizar_caso_en_sheet
            actualizar_caso_en_sheet(caso, accion="actualizar")
        except Exception as e:
            print(f"⚠️ Error sincronizando con Sheets: {e}")

        return {
            "success": True,
            "serial": serial,
            "mensaje": "Documentos completados exitosamente. El caso será revisado nuevamente.",
            "nuevo_estado": "NUEVO",
            "nuevo_link": nuevo_link,
            "ocr_glm": _ocr_respuesta_api(resultado_ocr_completar),
        }
        
    except Exception as e:
        print(f"❌ Error completando caso {serial}: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": f"Error procesando archivos: {str(e)}"}
        )


# ══════════════════════════════════════════════════════════════════
# VERIFICAR DUPLICADOS (antes de subir incapacidad)
# ══════════════════════════════════════════════════════════════════
@app.get("/verificar-duplicado")
async def verificar_duplicado(
    cedula: str,
    fecha_inicio: str,
    fecha_fin: str,
    tipo: str = None,  # Opcional para compatibilidad
    db: Session = Depends(get_db)
):
    """
    ✅ Verifica si ya existe una incapacidad con las mismas fechas Y MISMO TIPO para esa cédula.
    Un certificado de hospitalización y una incapacidad normal pueden tener las mismas fechas.
    El frontend debe llamar esto ANTES de permitir enviar.
    Retorna: {duplicado: true/false, serial, estado, mensaje}
    """
    try:
        fi = datetime.strptime(fecha_inicio, "%Y-%m-%d").date()
        ff = datetime.strptime(fecha_fin, "%Y-%m-%d").date()
    except ValueError:
        return {"duplicado": False, "error": "Formato de fecha inválido"}
    
    # Buscar caso con MISMA cédula, misma fecha_inicio, misma fecha_fin Y MISMO TIPO
    from sqlalchemy import and_
    
    # Construir filtros base
    filtros = [
        Case.cedula == cedula,
        Case.fecha_inicio == fi,
        Case.fecha_fin == ff
    ]
    
    # Si se proporciona tipo, validar que exista en el enum ANTES de consultar
    if tipo:
        tipo_normalizado = tipo.strip().lower()
        try:
            tipo_enum = TipoIncapacidad(tipo_normalizado)
            filtros.append(Case.tipo == tipo_enum)
        except ValueError:
            # Si el tipo no existe en el enum, ignorar el filtro de tipo
            print(f"⚠️ Tipo '{tipo}' no reconocido, buscando sin filtro de tipo")
    
    try:
        caso_existente = db.query(Case).filter(and_(*filtros)).first()
    except Exception as e:
        print(f"⚠️ Error en verificar_duplicado: {e}")
        db.rollback()
        return {"duplicado": False}
    
    if caso_existente:
        return {
            "duplicado": True,
            "serial": caso_existente.serial,
            "estado": caso_existente.estado.value if caso_existente.estado else None,
            "mensaje": f"Ya existe una incapacidad de este tipo con estas fechas (Serial: {caso_existente.serial}). No puedes enviar la misma incapacidad dos veces."
        }
    
    return {"duplicado": False}


@app.post("/subir-incapacidad/")
async def subir_incapacidad(
    cedula: str = Form(...),
    tipo: str = Form(...),
    email: str = Form(...),
    telefono: str = Form(...),
    archivos: List[UploadFile] = File(...),
    births: Optional[str] = Form(None),
    motherWorks: Optional[str] = Form(None),
    isPhantomVehicle: Optional[str] = Form(None),
    daysOfIncapacity: Optional[str] = Form(None),
    subType: Optional[str] = Form(None),
    incapacityStartDate: Optional[str] = Form(None),
    incapacityEndDate: Optional[str] = Form(None),
    empresa: Optional[str] = Form(None),  # slug de la empresa (link por empresa de repogemin)
    db: Session = Depends(get_db)
):
    """Endpoint de recepción de incapacidades"""

    # ✅ MULTI-TENANT: si viene el slug, TODO queda aislado a esa empresa
    company_scope = _company_por_slug(db, empresa)

    # ✅ PASO 1: Verificar en BD (búsqueda instantánea, scoped si hay slug)
    q_emp = db.query(Employee).filter(Employee.cedula == cedula)
    if company_scope:
        q_emp = q_emp.filter(Employee.company_id == company_scope.id)
    else:
        q_emp = q_emp.order_by(Employee.activo.desc())
    empleado_bd = q_emp.first()

    # ✅ PASO 2: Si NO está en BD, sincronizar desde Excel (Sheet propio si hay slug)
    if not empleado_bd:
        print(f"📄 Sincronización instantánea para {cedula}...")
        empleado_bd = sincronizar_empleado_desde_excel(
            cedula, company_id=company_scope.id if company_scope else None
        )
    
    # ✅ PASO 3: Determinar si el empleado fue encontrado (en BD o Excel)
    if empleado_bd:
        empleado_encontrado = True
    else:
        try:
            if os.path.exists(DATA_PATH):
                df = pd.read_excel(DATA_PATH)
                empleado_encontrado = not df[df["cedula"] == int(cedula)].empty
            else:
                empleado_encontrado = False
        except:
            empleado_encontrado = False
    
    # ✅ INICIALIZAR METADATA Y EXTRAER FECHAS DEL FORMULARIO ANTES DE GENERAR SERIAL
    metadata_form = {}
    tiene_soat = None
    tiene_licencia = None
    fecha_inicio = None
    fecha_fin = None

    # ✅ EXTRAER FECHAS DEL FORMULARIO (maneja ambos formatos: ISO con hora y YYYY-MM-DD)
    if incapacityStartDate:
        try:
            # Detectar formato: YYYY-MM-DD (date) vs ISO con hora (datetime)
            if 'T' in incapacityStartDate or 'Z' in incapacityStartDate:
                # Formato ISO completo: 2025-01-15T00:00:00Z
                fecha_inicio = datetime.fromisoformat(incapacityStartDate.replace('Z', '+00:00')).date()
            else:
                # Formato simple: 2025-01-15
                fecha_inicio = datetime.strptime(incapacityStartDate, '%Y-%m-%d').date()
            
            metadata_form['fecha_inicio_incapacidad'] = incapacityStartDate
            print(f"✅ Fecha inicio parseada: {fecha_inicio}")
        except Exception as e:
            print(f"⚠️ Error parseando fecha inicio '{incapacityStartDate}': {e}")
            fecha_inicio = None

    if incapacityEndDate:
        try:
            # Detectar formato: YYYY-MM-DD (date) vs ISO con hora (datetime)
            if 'T' in incapacityEndDate or 'Z' in incapacityEndDate:
                # Formato ISO completo: 2025-01-15T00:00:00Z
                fecha_fin = datetime.fromisoformat(incapacityEndDate.replace('Z', '+00:00')).date()
            else:
                # Formato simple: 2025-01-15
                fecha_fin = datetime.strptime(incapacityEndDate, '%Y-%m-%d').date()
            
            metadata_form['fecha_fin_incapacidad'] = incapacityEndDate
            print(f"✅ Fecha fin parseada: {fecha_fin}")
        except Exception as e:
            print(f"⚠️ Error parseando fecha fin '{incapacityEndDate}': {e}")
            fecha_fin = None

    # ✅ NUEVO: Verificar si ya existe caso con las MISMAS FECHAS (reenvío)
    caso_existente = None
    nuevo_numero_reenvio = None
    es_reenvio = False
    
    if fecha_inicio and cedula:
        q_caso = db.query(Case).filter(
            Case.cedula == cedula,
            Case.fecha_inicio == fecha_inicio,
            Case.estado.in_([
                EstadoCaso.INCOMPLETA,
                EstadoCaso.ILEGIBLE,
                EstadoCaso.INCOMPLETA_ILEGIBLE
            ])
        )
        if company_scope:
            q_caso = q_caso.filter(Case.company_id == company_scope.id)
        caso_existente = q_caso.first()
    
    if caso_existente:
        # ✅ HAY CASO PREVIO INCOMPLETO → CONTAR REENVÍOS
        es_reenvio = True
        total_reenvios = caso_existente.metadata_form.get('total_reenvios', 0) if caso_existente.metadata_form else 0
        nuevo_numero_reenvio = total_reenvios + 1
        print(f"🔄 Reenvío #{nuevo_numero_reenvio} detectado para caso {caso_existente.serial}")
    
    # ✅ Generar serial único basado en cédula y fechas
    # NUEVO FORMATO: CEDULA_DD_MM_YYYY_DD_MM_YYYY
    serial_base = generar_serial_unico(
        db=db,
        cedula=cedula,
        fecha_inicio=fecha_inicio or date.today(),
        fecha_fin=fecha_fin or date.today()
    )
    
    # ✅ MODIFICAR SERIAL SI ES REENVÍO
    if es_reenvio:
        consecutivo = f"{serial_base}-R{nuevo_numero_reenvio}"
        print(f"   Serial modificado para reenvío: {consecutivo}")
    else:
        consecutivo = serial_base
    
    # Verificar si hay casos bloqueantes
    if empleado_bd:
        caso_bloqueante = db.query(Case).filter(
            Case.employee_id == empleado_bd.id,
            Case.estado.in_([EstadoCaso.INCOMPLETA, EstadoCaso.ILEGIBLE, EstadoCaso.INCOMPLETA_ILEGIBLE]),
            Case.bloquea_nueva == True
        ).first()
        
        if caso_bloqueante:
            return JSONResponse(status_code=409, content={
                "bloqueo": True,
                "serial_pendiente": caso_bloqueante.serial,
                "mensaje": f"Caso pendiente ({caso_bloqueante.serial}) debe completarse primero."
            })
    
    if births:
        metadata_form['nacidos_vivos'] = births
    
    if tipo.lower() == 'paternidad' and motherWorks is not None:
        tiene_licencia = motherWorks.lower() == 'true'
        metadata_form['madre_trabaja'] = 'Sí' if tiene_licencia else 'No'
    
    if isPhantomVehicle is not None:
        tiene_soat = isPhantomVehicle.lower() != 'true'
        metadata_form['vehiculo_fantasma'] = 'Sí' if isPhantomVehicle.lower() == 'true' else 'No'
        metadata_form['tiene_soat'] = 'Sí' if tiene_soat else 'No'
    
    if daysOfIncapacity:
        metadata_form['dias_incapacidad'] = daysOfIncapacity
    
    if subType:
        metadata_form['subtipo'] = subType
    
    
    
    resultado_ocr = {"exito": False, "texto": "", "error": "", "paginas": 0}
    drive_error_detalle = None
    drive_error_usuario = None
    try:
        # Empresa destino: la del empleado; si no se encontró pero el link trae slug, la de la empresa del link
        if empleado_bd and empleado_bd.empresa:
            empresa_destino = empleado_bd.empresa.nombre
        elif company_scope:
            empresa_destino = company_scope.nombre
        else:
            empresa_destino = "OTRA_EMPRESA"

        pdf_final_path, original_filenames = await merge_pdfs_from_uploads(archivos, cedula, tipo)

        # ✅ AUTO-MEJORA HD (solo si está borroso/baja-res). Nunca debe bloquear la subida.
        try:
            from app.pdf_enhancer import get_enhancer
            pdf_original = pdf_final_path.read_bytes()
            # nivel rápido para no demorar la subida; auto decide BW/color por página
            pdf_mejorado = get_enhancer("rapido", "auto").enhance_bytes(pdf_original, only_if_needed=True)
            if pdf_mejorado is not pdf_original and pdf_mejorado != pdf_original:
                pdf_final_path.write_bytes(pdf_mejorado)
                print(f"✅ Auto-mejora HD aplicada a {consecutivo}")
        except Exception as enh_err:
            print(f"⚠️ Auto-mejora HD omitida ({enh_err}) — se continúa con el PDF original")

        resultado_ocr = _aplicar_mistral_ocr_a_metadata(metadata_form, pdf_final_path)

        # Estructurar plano con Gemini 3 Flash si Mistral devolvió texto
        if resultado_ocr.get("exito") and resultado_ocr.get("texto"):
            _estructurar_plano_con_gemini(metadata_form, resultado_ocr["texto"])

        # Obtener carpeta Drive del cliente si tiene onboarding completo
        # (empresa del empleado; o la del slug del link si el empleado no se encontró)
        client_drive_id = None
        client_ciclo_reporte = None
        company_id_drive = (empleado_bd.company_id if empleado_bd else None) or (company_scope.id if company_scope else None)
        if company_id_drive:
            try:
                from app.database import TenantConfig
                # Sin exigir onboarding_completado: si la empresa tiene Drive/ciclo
                # configurados, se respetan aunque el wizard haya quedado a medias.
                tenant_cfg = db.query(TenantConfig).filter(
                    TenantConfig.company_id == company_id_drive,
                ).first()
                if tenant_cfg and tenant_cfg.google_workspace_drive_id:
                    client_drive_id = tenant_cfg.google_workspace_drive_id
                    print(f"📁 Drive del cliente: {client_drive_id}")
                if tenant_cfg and tenant_cfg.ciclo_reporte:
                    client_ciclo_reporte = tenant_cfg.ciclo_reporte
            except Exception as _te:
                print(f"⚠️ No se pudo obtener Drive del cliente: {_te}")

        link_pdf = None
        drive_en_cola = False
        try:
            link_pdf = upload_inteligente(
                file_path=pdf_final_path,
                empresa=empresa_destino,
                cedula=cedula,
                tipo=tipo,
                serial=consecutivo,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                tiene_soat=tiene_soat,
                tiene_licencia=tiene_licencia,
                subtipo=subType,
                client_drive_id=client_drive_id,
                ciclo_reporte=client_ciclo_reporte,
            )
            pdf_final_path.unlink(missing_ok=True)
        except Exception as drive_err:
            # ✅ Drive falló → guardar PDF en /tmp con nombre seguro y meter en cola
            print(f"⚠️ Drive falló ({drive_err}) — caso se guardará en BD y PDF en cola")
            drive_error_detalle = str(drive_err)
            drive_error_usuario = _mensaje_drive_usuario(drive_error_detalle)
            import shutil
            import tempfile
            tmp_dir = Path(tempfile.gettempdir()) / "incapacidades_cola"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            pdf_cola_path = tmp_dir / f"{consecutivo}.pdf"
            shutil.copy2(str(pdf_final_path), str(pdf_cola_path))
            pdf_final_path.unlink(missing_ok=True)
            guardar_pendiente_drive({
                "file_path": str(pdf_cola_path),
                "empresa": empresa_destino,
                "cedula": cedula,
                "tipo": tipo,
                "serial": consecutivo,
                "fecha_inicio": fecha_inicio.isoformat() if fecha_inicio else None,
                "fecha_fin": fecha_fin.isoformat() if fecha_fin else None,
                "tiene_soat": tiene_soat,
                "tiene_licencia": tiene_licencia,
                "subtipo": subType,
                "client_drive_id": client_drive_id,
                "ciclo_reporte": client_ciclo_reporte,
            }, error=str(drive_err))
            drive_en_cola = True
            link_pdf = None  # Se actualizará cuando la cola lo procese

    except Exception as merge_err:
        # Solo llegamos aquí si merge_pdfs_from_uploads falla — sin PDF no hay caso
        return JSONResponse(status_code=500, content={"error": f"Error procesando archivos PDF: {merge_err}"})

    tipo_bd = mapear_tipo_incapacidad(subType if subType else tipo)
    
    nuevo_caso = Case(
        serial=consecutivo,
        cedula=cedula,
        employee_id=empleado_bd.id if empleado_bd else None,
        company_id=(empleado_bd.company_id if empleado_bd else None) or (company_scope.id if company_scope else None),
        tipo=tipo_bd,
        subtipo=subType,
        dias_incapacidad=int(daysOfIncapacity) if daysOfIncapacity else None,
        estado=EstadoCaso.NUEVO,
        metadata_form=metadata_form,
        eps=empleado_bd.eps if empleado_bd else None,
        drive_link=link_pdf,
        email_form=email,
        telefono_form=telefono,
        bloquea_nueva=False,
        fecha_inicio=fecha_inicio,  # ← NUEVO: Guardar fecha de inicio
        fecha_fin=fecha_fin,        # ← NUEVO: Guardar fecha de fin
    )
    
    # ✅ Si es reenvío, guardar metadata de reenvío
    if es_reenvio:
        if not nuevo_caso.metadata_form:
            nuevo_caso.metadata_form = {}
        
        nuevo_caso.metadata_form['es_reenvio'] = True
        nuevo_caso.metadata_form['total_reenvios'] = nuevo_numero_reenvio
        nuevo_caso.metadata_form['caso_original_id'] = caso_existente.id
        nuevo_caso.metadata_form['caso_original_serial'] = caso_existente.serial
        print(f"✅ Reenvío #{nuevo_numero_reenvio} guardado - Original: {caso_existente.serial}")
    
    
    db.add(nuevo_caso)
    db.commit()
    db.refresh(nuevo_caso)
    
    print(f"✅ Caso {consecutivo} guardado (ID {nuevo_caso.id}) - Empresa: {empleado_bd.empresa.nombre if empleado_bd and empleado_bd.empresa else 'N/A'}")

    # ✅ AUTO-ENCOLAR RADICACIÓN (Browserbase) — si la empresa tiene bot para esta EPS
    try:
        from app.services.radicacion_dispatcher import encolar_caso
        cola_id = encolar_caso(db, nuevo_caso)
        if cola_id:
            print(f"🤖 Caso {consecutivo} encolado para radicación automática (cola #{cola_id})")
    except Exception as e:
        print(f"⚠️ Error auto-encolando radicación: {e}")

    # ✅ SINCRONIZAR CON GOOGLE SHEETS
    try:
        from app.google_sheets_tracker import actualizar_caso_en_sheet
        actualizar_caso_en_sheet(nuevo_caso, accion="crear")
        print(f"✅ Caso {consecutivo} sincronizado con Google Sheets")
    except Exception as e:
        print(f"⚠️ Error sincronizando con Sheets: {e}")
    
    # ✅ VERIFICAR SI ES PRÓRROGA EN CONTEXTO DE MATERNIDAD/PRELICENCIA
    # Si hay licencia de maternidad y cadena de prórrogas previa, verificar correlación
    try:
        from app.services.prorroga_detector import verificar_prorroga_contexto_maternidad
        resultado_maternidad = verificar_prorroga_contexto_maternidad(db, nuevo_caso)
        if resultado_maternidad.get("es_prorroga_cadena_previa"):
            print(f"✅ PRÓRROGA MATERNIDAD: {resultado_maternidad['explicacion']}")
        elif resultado_maternidad.get("aplica_regla_maternidad"):
            print(f"ℹ️ Regla maternidad aplicada pero sin correlación: {resultado_maternidad['explicacion']}")
    except Exception as e:
        print(f"⚠️ Error verificando prórroga maternidad: {e}")
    
    quinzena_actual = get_current_quinzena()
    
    if empleado_encontrado and empleado_bd:
        nombre = empleado_bd.nombre
        correo_empleado = empleado_bd.correo
        empresa_reg = empleado_bd.empresa.nombre if empleado_bd.empresa else "No especificada"
        
        # ✅ OBTENER EMAIL DE COPIA DE LA EMPRESA (desde Directorio, no BD)
        cc_empresa = None
        if empleado_bd.empresa and hasattr(empleado_bd.empresa, 'id'):
            emails_dir = obtener_emails_empresa_directorio(empleado_bd.empresa.id, db=db)
            if emails_dir:
                cc_empresa = ",".join(emails_dir)  # ✅ TODOS los emails del directorio
                print(f"📧 CC empresa (directorio): {cc_empresa}")
        
        # ✅ VERIFICAR SI ES CERTIFICADO DE HOSPITALIZACIÓN (mensaje especial)
        es_certificado = tipo_bd and tipo_bd.value.lower() == 'certificado' if tipo_bd else False
        
        if es_certificado:
            # Mensaje simple para certificado de hospitalización
            html_empleado = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 10px;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px 10px 0 0; text-align: center;">
                    <h1>IncaNeurobaeza</h1>
                    <p style="margin: 0; font-style: italic;">"Trabajando para ayudarte"</p>
                </div>
                <div style="padding: 30px 20px;">
                    <p>Hola {nombre},</p>
                    <p><strong>✅ Novedad se a tomado en cuenta</strong></p>
                    <p>Hemos recibido tu certificado de hospitalización.</p>
                    <div style="background: #f8f9fa; padding: 15px; border-left: 4px solid #667eea; margin: 20px 0;">
                        <strong>Serial:</strong> {consecutivo}<br>
                        <strong>Empresa:</strong> {empresa_reg}
                    </div>
                    <p>Gracias por usar IncaNeurobaeza.</p>
                </div>
            </div>
            """
            asunto = f"Certificado de Hospitalización {consecutivo} - {nombre}"
            mensaje_whatsapp = f"""
📋 *Certificado de Hospitalizacion Recibido*
Incapacidad: {consecutivo}

Documentacion recibida. Esta siendo revisada.

_Automatico por Incapacidades_
            """.strip()
        else:
            # Template normal para otras incapacidades
            html_empleado = get_confirmation_template(
                nombre=nombre,
                serial=consecutivo,
                empresa=empresa_reg,
                tipo_incapacidad=tipo_bd.value if tipo_bd else 'General',
                telefono=telefono,
                email=email,
                link_drive=link_pdf,
                archivos_nombres=original_filenames
            )
            asunto = f"Incapacidad {consecutivo} - {nombre} - {empresa_reg}"
            
            # ✅ Mensaje WhatsApp corto y directo
            _parts = consecutivo.strip().split()
            _fechas_wa = f"del {_parts[1]}/{_parts[2]}/{_parts[3]} al {_parts[4]}/{_parts[5]}/{_parts[6]}" if len(_parts) == 7 else ""
            mensaje_whatsapp = f"""📋 *Incapacidad Recibida*
Incapacidad {_fechas_wa}

Documentacion recibida. Esta siendo revisada.
Nos comunicaremos si se requiere algo adicional.

_Automatico por Incapacidades_""".strip()
        
        # ✅ ENVIAR VIA BACKEND NATIVO con COPIAS Y WHATSAPP
        from app.email_service import enviar_notificacion
        
        emails_enviados = []
        notificacion_exitosa = False
        
        print(f"\n{'='*80}")
        print(f"📧 ENVIANDO CONFIRMACIÓN AL USUARIO")
        print(f"{'='*80}\n")
        
        if email:  # Email del formulario como TO principal
            # ✅ MOSTRAR CONFIGURACIÓN DE EMAILS
            print(f"📋 DETALLES DEL EMAIL CC:")
            print(f"   TO (Formulario): {email}")
            print(f"   CC (Empleado BD): {correo_empleado or '❌ VACÍO'}")
            print(f"   CC (Directorio): {cc_empresa or '❌ VACÍO'}")
            if not correo_empleado and not cc_empresa:
                print(f"   ⚠️ ADVERTENCIA: No hay CCs configurados - Revisar BD")
            print()
            
            resultado = enviar_notificacion(
                tipo_notificacion='confirmacion',
                email=email,
                serial=consecutivo,
                subject=asunto,
                html_content=html_empleado,
                cc_email=cc_empresa,
                correo_bd=correo_empleado,
                whatsapp=telefono,
                whatsapp_message=mensaje_whatsapp,
                adjuntos_base64=[],
                drive_link=link_pdf
            )
            if resultado:
                emails_enviados.append(email)
                notificacion_exitosa = True
                print(f"✅ Notificación enviada exitosamente")
            else:
                print(f"⚠️ La notificación no respondió")
                notificacion_exitosa = False
        
        print(f"\n{'='*80}")
        print(f"✅ RESPUESTA FINAL AL FRONTEND")
        print(f"{'='*80}\n")
        
        respuesta_final = {
            "status": "ok",
            "mensaje": "Registro exitoso",
            "consecutivo": consecutivo,
            "case_id": nuevo_caso.id,
            "link_pdf": link_pdf,
            "drive_en_cola": drive_en_cola,
            "archivos_combinados": len(original_filenames),
            "correos_enviados": emails_enviados,
            "notificacion_enviada": notificacion_exitosa,
            "canales_notificados": {
                "email": notificacion_exitosa,
                "whatsapp": notificacion_exitosa and bool(telefono)
            },
            "fecha_inicio": fecha_inicio.isoformat() if fecha_inicio else None,
            "fecha_fin": fecha_fin.isoformat() if fecha_fin else None,
            "serial": consecutivo,
            "ocr_glm": _ocr_respuesta_api(resultado_ocr),
            "drive_error": drive_error_usuario,
            "drive_error_detalle": drive_error_detalle,
        }
        
        print(f"Respondiendo con: {respuesta_final}")
        print(f"{'='*80}\n")
        
        return respuesta_final
    
    else:
        html_alerta = get_alert_template(
            nombre=f"Cédula {cedula}",
            serial=consecutivo,
            empresa="Empleado no registrado",
            tipo_incapacidad=tipo,
            telefono=telefono,
            email=email,
            link_drive=link_pdf
        )
        
        html_confirmacion = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 10px;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px 10px 0 0; text-align: center;">
                <h1>IncaNeurobaeza</h1>
                <p style="margin: 0; font-style: italic;">"Trabajando para ayudarte"</p>
            </div>
            <div style="padding: 30px 20px;">
                <p>Buen día,</p>
                <p>Confirmo recibido de la documentación. Su solicitud está siendo revisada.</p>
                <div style="background: #f8f9fa; padding: 15px; border-left: 4px solid #667eea; margin: 20px 0;">
                    <strong>Consecutivo:</strong> {consecutivo}<br>
                    <strong>Cédula:</strong> {cedula}
                </div>
                <p><strong>Importante:</strong> Su cédula no está en nuestra base de datos. Nos comunicaremos con usted.</p>
            </div>
        </div>
        """
        
        # ✅ ENVIAR WHATSAPP CONFIRMACIÓN CÉDULA NO ENCONTRADA
        mensaje_whatsapp_desconocido = f"""
Hola,

Recibimos tu documentación de incapacidad.
Serial: {consecutivo}

Tu cédula no está en nuestra base de datos.
Nos comunicaremos contigo pronto.

Gracias por usar IncaNeurobaeza.
        """.strip()
        
        notificacion_exitosa = enviar_notificacion(
            tipo_notificacion='confirmacion',
            email=email,
            serial=consecutivo,
            subject=f"Incapacidad {consecutivo} - Desconocido - Pendiente",
            html_content=html_confirmacion,
            cc_email=None,
            correo_bd=None,
            whatsapp=telefono,  # ✅ NUEVO: Enviar teléfono
            whatsapp_message=mensaje_whatsapp_desconocido,  # ✅ NUEVO: Enviar mensaje
            adjuntos_base64=[]
        )
        
        return {
            "status": "warning",
            "mensaje": "Cédula no encontrada - Documentación recibida",
            "consecutivo": consecutivo,
            "case_id": nuevo_caso.id,
            "link_pdf": link_pdf,
            "drive_en_cola": drive_en_cola,
            "correos_enviados": [email],
            "notificacion_enviada": notificacion_exitosa,
            "canales_notificados": {
                "email": notificacion_exitosa,
                "whatsapp": notificacion_exitosa and bool(telefono)
            },
            "ocr_glm": _ocr_respuesta_api(resultado_ocr),
            "drive_error": drive_error_usuario,
            "drive_error_detalle": drive_error_detalle,
        }

@app.post("/admin/migrar-excel")
async def migrar_excel_a_bd(db: Session = Depends(get_db)):
    """Migra empleados desde Excel a BD"""
    
    if not os.path.exists(DATA_PATH):
        return JSONResponse(status_code=404, content={"error": f"Excel no encontrado en {DATA_PATH}"})
    
    try:
        df = pd.read_excel(DATA_PATH)
        migraciones = 0
        errores = []
        
        for _, row in df.iterrows():
            try:
                empresa_nombre = row["empresa"]
                company = db.query(Company).filter(Company.nombre == empresa_nombre).first()
                
                if not company:
                    company = Company(nombre=empresa_nombre, activa=True)
                    db.add(company)
                    db.flush()
                    from app.database import asignar_slug
                    asignar_slug(db, company)
                    db.commit()
                    db.refresh(company)
                
                cedula = str(row["cedula"])
                empleado_existente = db.query(Employee).filter(Employee.cedula == cedula).first()
                
                if not empleado_existente:
                    nuevo_empleado = Employee(
                        cedula=cedula,
                        nombre=row["nombre"],
                        correo=row["correo"],
                        telefono=row.get("telefono", None),
                        company_id=company.id,
                        eps=row.get("eps", None),
                        activo=True
                    )
                    db.add(nuevo_empleado)
                    db.commit()
                    migraciones += 1
                
            except Exception as e:
                errores.append(f"Error en {row.get('cedula', 'N/A')}: {str(e)}")
        
        return {
            "status": "ok",
            "migraciones_exitosas": migraciones,
            "errores": errores,
            "total_procesados": len(df)
        }
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Error: {str(e)}"})

@app.get("/health/drive-token")
async def check_drive_token_health():
    """
    📊 Estado completo del token de Google Drive
    Incluye: estado actual, última renovación, errores, y capacidad de diagnóstico
    """
    from app.drive_uploader import TOKEN_FILE
    import json
    from datetime import datetime

    usa_cuenta_servicio = is_service_account_mode()
    
    result = {
        "timestamp": datetime.now().isoformat(),
        "auth_mode": "service_account" if usa_cuenta_servicio else "refresh_token",
        "token_file": {},
        "scheduler_status": {},
        "recommendation": None
    }
    
    try:
        if usa_cuenta_servicio:
            from app.drive_uploader import get_authenticated_service
            service = get_authenticated_service()
            service.files().list(pageSize=1, fields="files(id)").execute()

            result["token_file"] = {
                "exists": False,
                "status": "not_applicable",
                "detail": "Cuenta de servicio no usa token cache de usuario"
            }
            result["scheduler_status"] = {
                "mode": "disabled",
                "detail": "No se requiere renovación de token"
            }
            result["overall_status"] = "✅ HEALTHY"
            result["recommendation"] = None
            return result

        # 1. Verificar archivo de token en cache
        if TOKEN_FILE.exists():
            with open(TOKEN_FILE, 'r') as f:
                token_data = json.load(f)
                expiry_str = token_data.get('expiry')
                
                if expiry_str:
                    expiry = datetime.fromisoformat(expiry_str)
                    now = datetime.now()
                    remaining = (expiry - now).total_seconds()
                    
                    result["token_file"] = {
                        "exists": True,
                        "status": "healthy" if remaining > 300 else ("expiring_soon" if remaining > 0 else "expired"),
                        "expires_in_minutes": round(remaining / 60, 2),
                        "expires_at": expiry_str,
                    }
                else:
                    result["token_file"] = {"exists": True, "status": "unknown_expiry"}
        else:
            result["token_file"] = {"exists": False, "status": "no_cache"}
        
        # 2. Obtener estado del scheduler de renovación
        try:
            from app.sync_scheduler import get_token_status
            scheduler_status = get_token_status()
            result["scheduler_status"] = scheduler_status
        except Exception as e:
            result["scheduler_status"] = {"error": str(e)}
        
        # 3. Determinar estado general y recomendación
        token_healthy = result["token_file"].get("status") in ["healthy", "expiring_soon"]
        scheduler_healthy = result["scheduler_status"].get("is_healthy", False)
        
        if token_healthy and scheduler_healthy:
            result["overall_status"] = "✅ HEALTHY"
            result["recommendation"] = None
        elif token_healthy and not scheduler_healthy:
            result["overall_status"] = "⚠️ WARNING"
            result["recommendation"] = "Token válido pero scheduler reporta errores. Revisar logs."
        elif not token_healthy and scheduler_healthy:
            result["overall_status"] = "⚠️ RECOVERING"
            result["recommendation"] = "Token expirado pero scheduler intentando renovar. Esperar 2 min."
        else:
            result["overall_status"] = "❌ CRITICAL"
            result["recommendation"] = (
                "Token y scheduler con problemas. Verificar GOOGLE_REFRESH_TOKEN en variables de entorno. "
                "Si persiste, regenerar token ejecutando python regenerar_token.py"
            )
        
        return result
        
    except Exception as e:
        return {
            "overall_status": "❌ ERROR",
            "error": str(e),
            "recommendation": "Error leyendo estado del token. Revisar logs del servidor."
        }


@app.post("/health/drive-token/force-refresh")
async def force_refresh_drive_token(x_admin_token: str = Header(None)):
    """
    🔄 Fuerza una renovación inmediata del token de Drive.
    Solo para administradores.
    """
    # Verificar token admin
    ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
    if not x_admin_token or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Token de administrador requerido")
    
    try:
        from app.drive_uploader import clear_service_cache, clear_token_cache, get_authenticated_service
        from datetime import datetime

        usa_cuenta_servicio = is_service_account_mode()
        
        # Limpiar todo el cache
        clear_service_cache()
        if not usa_cuenta_servicio:
            clear_token_cache()
        
        # Forzar renovación
        service = get_authenticated_service()
        
        # Verificar que funciona
        service.files().list(pageSize=1, fields="files(id)").execute()
        
        return {
            "status": "success",
            "message": "Servicio de Drive refrescado exitosamente" if usa_cuenta_servicio else "Token renovado exitosamente",
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "recommendation": "Si el error persiste, verificar GOOGLE_REFRESH_TOKEN"
        }

@app.post("/validador/casos/{serial}/cambiar-tipo")
async def cambiar_tipo_incapacidad(
    serial: str,
    request: Request,
    token: str = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db)
):
    """
    Permite al validador cambiar el tipo de incapacidad
    cuando detecta que se clasificó mal
    """
    # 1. Validar token
    from app.validador import verificar_token_admin
    verificar_token_admin(token)
    
    # 2. Leer datos del body
    try:
        datos = await request.json()
        nuevo_tipo = datos.get('nuevo_tipo')
    except:
        raise HTTPException(status_code=400, detail="Datos inválidos")
    
    # 3. Validar tipo
    tipos_validos = ['maternity', 'paternity', 'general', 'traffic', 'labor', 'certificado_hospitalizacion', 'prelicencia']
    if nuevo_tipo not in tipos_validos:
        raise HTTPException(status_code=400, detail=f"Tipo inválido. Usa: {', '.join(tipos_validos)}")
    
    # 4. Buscar caso en BD
    caso = db.query(Case).filter(Case.serial == serial).first()
    
    if not caso:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    
    # 5. Guardar tipo anterior y actualizar
    tipo_anterior = caso.tipo.value if caso.tipo else 'desconocido'
    
    # Mapear tipo nuevo a TipoIncapacidad enum
    tipo_map = {
        'maternity': TipoIncapacidad.MATERNIDAD,
        'paternity': TipoIncapacidad.PATERNIDAD,
        'general': TipoIncapacidad.ENFERMEDAD_GENERAL,
        'traffic': TipoIncapacidad.ACCIDENTE_TRANSITO,
        'labor': TipoIncapacidad.ENFERMEDAD_LABORAL,
        'certificado_hospitalizacion': TipoIncapacidad.CERTIFICADO,
        'prelicencia': TipoIncapacidad.PRELICENCIA
    }
    
    caso.tipo = tipo_map[nuevo_tipo]
    caso.subtipo = nuevo_tipo
    
    # Actualizar metadata
    if not caso.metadata_form:
        caso.metadata_form = {}
    
    caso.metadata_form['tipo_anterior'] = tipo_anterior
    caso.metadata_form['cambio_tipo_fecha'] = datetime.now().isoformat()
    caso.metadata_form['cambio_tipo_validador'] = "sistema"
    
    # 6. Cambiar estado a INCOMPLETA (requiere nuevos documentos)
    caso.estado = EstadoCaso.INCOMPLETA
    caso.bloquea_nueva = True
    caso.updated_at = datetime.now()
    
    db.commit()
    
    # 7. Obtener nuevos documentos requeridos
    docs_requeridos = obtener_documentos_requeridos(nuevo_tipo)
    
    # 8. Enviar email al empleado
    empleado_email = caso.email_form
    empleado_nombre = caso.empleado.nombre if caso.empleado else 'Empleado'
    
    if empleado_email:
        try:
            enviar_email_cambio_tipo(
                email=empleado_email,
                nombre=empleado_nombre,
                serial=serial,
                tipo_anterior=tipo_anterior,
                tipo_nuevo=nuevo_tipo,
                docs_requeridos=docs_requeridos
            )
        except Exception as e:
            print(f"Error enviando email: {e}")
    
    # 9. Registrar evento
    from app.validador import registrar_evento
    registrar_evento(
        db, caso.id,
        "cambio_tipo",
        actor="Validador",
        estado_anterior=tipo_anterior,
        estado_nuevo=nuevo_tipo,
        motivo=f"Tipo cambiado de {tipo_anterior} a {nuevo_tipo}",
        metadata={'docs_requeridos': docs_requeridos}
    )
    
    return {
        "mensaje": f"Tipo cambiado exitosamente de {tipo_anterior} a {nuevo_tipo}",
        "tipo_anterior": tipo_anterior,
        "tipo_nuevo": nuevo_tipo,
        "documentos_requeridos": docs_requeridos,
        "email_enviado": empleado_email is not None
    }


# =====================
# ENDPOINT: Ver cola de pendientes
# =====================
from app.database import PendienteEnvio, SessionLocal

@app.get("/pendientes-envio")
async def ver_pendientes_envio(tipo: str = None):
    """
    Devuelve la lista de pendientes de envío (Drive).
    - tipo: 'drive' o None para todos
    """
    db = SessionLocal()
    query = db.query(PendienteEnvio)
    if tipo:
        query = query.filter_by(tipo=tipo)
    pendientes = query.order_by(PendienteEnvio.creado_en.desc()).all()
    db.close()
    from fastapi.responses import JSONResponse
    return JSONResponse([
        {
            "id": p.id,
            "tipo": p.tipo,
            "payload": p.payload,
            "intentos": p.intentos,
            "ultimo_error": p.ultimo_error,
            "creado_en": p.creado_en.isoformat() if p.creado_en else None,
            "procesado": p.procesado
        } for p in pendientes
    ])


# ==================== OAUTH ENDPOINTS - Gmail Authorization ====================

@app.get("/auth/authorize")
async def oauth_authorize():
    """
    📧 PASO 1: Redirige al usuario a Google para autorizar el acceso a Gmail.
    
    Endpoint: GET /auth/authorize
    Usuario hace click en un botón que lo lleva aquí,
    luego Google lo redirige a /auth/callback con un código.
    """
    from app.gmail_oauth import obtener_url_autorizacion
    
    try:
        auth_url = obtener_url_autorizacion()
        print(f"✅ URL de autorización generada")
        print(f"   {auth_url[:100]}...")
        
        return JSONResponse({
            "mensaje": "Abre este enlace en tu navegador para autorizar el acceso a Gmail",
            "url": auth_url,
            "instrucciones": [
                "1. Haz click en el enlace",
                "2. Selecciona tu cuenta de Google",
                "3. Autoriza el acceso",
                "4. Se te redirigirá automáticamente"
            ]
        })
    except Exception as e:
        print(f"❌ Error generando URL de autorización: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Error: {str(e)}"}
        )


@app.get("/auth/callback")
async def oauth_callback(code: str = None, error: str = None, db: Session = Depends(get_db)):
    """
    📧 PASO 2: Google redirige aquí después de que el usuario autoriza.
    
    Endpoint: GET /auth/callback?code=...
    Intercambia el código por tokens y los guarda en BD.
    """
    from app.gmail_oauth import procesar_codigo_autorizacion
    from fastapi.responses import HTMLResponse
    
    if error:
        print(f"❌ Error en Google OAuth: {error}")
        return HTMLResponse(f"""
        <h1>❌ Error en Autorización</h1>
        <p>{error}</p>
        <p><a href="/auth/status">Volver a intentar</a></p>
        """, status_code=400)
    
    if not code:
        return HTMLResponse("""
        <h1>❌ No Authorization Code</h1>
        <p>No se recibió código de autorización</p>
        """, status_code=400)
    
    try:
        print(f"🔄 Procesando código de autorización...")
        data = procesar_codigo_autorizacion(code)
        
        print(f"✅ Token guardado exitosamente en BD")
        
        return HTMLResponse(f"""
        <html>
        <head><title>✅ Autorización Exitosa</title></head>
        <body style="font-family: Arial; text-align: center; padding: 50px;">
            <h1>✅ ¡Autorización Exitosa!</h1>
            <p>Gmail está ahora configurado para enviar emails automáticamente.</p>
            <p style="color: green; font-weight: bold;">El sistema puede cerrar esta ventana.</p>
            <hr>
            <p><small>Token válido por {data.get('expires_in', 3600)} segundos</small></p>
            <p><small>Se refrescará automáticamente cuando sea necesario</small></p>
        </body>
        </html>
        """)
    
    except Exception as e:
        print(f"❌ Error procesando código: {e}")
        return HTMLResponse(f"""
        <html>
        <head><title>❌ Error</title></head>
        <body style="font-family: Arial; text-align: center; padding: 50px;">
            <h1>❌ Error en Autorización</h1>
            <p>No se pudo guardar el token:</p>
            <p style="color: red;"><code>{str(e)[:200]}</code></p>
            <p><a href="/auth/authorize">Intentar de nuevo</a></p>
        </body>
        </html>
        """, status_code=500)


@app.get("/auth/status")
async def oauth_status():
    """
    🔍 Verifica si Gmail ya está autorizado.
    
    Retorna:
    - authorized: true/false
    - Si es false, incluye botón para autorizar
    """
    from app.gmail_oauth import esta_autorizado
    
    autorizado = esta_autorizado()
    
    if autorizado:
        return {
            "authorized": True,
            "servicio": "gmail",
            "mensaje": "Gmail está configurado y funcionando",
            "estado": "✅ Listo para enviar emails"
        }
    else:
        return {
            "authorized": False,
            "servicio": "gmail",
            "mensaje": "Gmail NO está autorizado aún",
            "estado": "⚠️ Necesita autorización",
            "action": "Visita /auth/authorize para configurar",
            "instrucciones": {
                "paso_1": "Abre: https://tudominio.com/auth/authorize",
                "paso_2": "Autoriza el acceso a Gmail",
                "paso_3": "Listo! El sistema enviará emails automáticamente"
            }
        }


# ==================== INICIO DEL SERVIDOR ====================

if __name__ == "__main__":
    import uvicorn
    import os
    
    # Railway usa variable de entorno PORT
    port = int(os.getenv("PORT", 8000))
    
    print(f"🚀 Iniciando servidor en puerto {port}...")
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )


# ══════════════════════════════════════════════════════════════
# ENDPOINT DE PRUEBA: OCR + GEMINI SIN GUARDAR EN BD
# ══════════════════════════════════════════════════════════════
@app.post("/test-plano")
async def test_plano_endpoint(
    archivo: UploadFile = File(...),
    cedula: str = Form(default=""),
):
    """🧪 PRUEBA: PDF → Mistral OCR → Gemini extrae plano. NO guarda en BD."""
    import tempfile, base64 as b64lib
    try:
        content = await archivo.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        # Paso 1: Mistral OCR
        ocr_res = {"exito": False, "texto": "", "paginas": 0, "error": "MISTRAL_API_KEY no configurada"}
        if _mistral_ocr_instance:
            pdf_b64 = b64lib.b64encode(tmp_path.read_bytes()).decode("utf-8")
            ocr_res = _mistral_ocr_instance.procesar_pdf_base64(pdf_b64)

        texto = ocr_res.get("texto", "")

        # Paso 2: Gemini Plano
        plano_res = {"exito": False, "plano": {}, "error": "GEMINI_API_KEY no configurada"}
        if _gemini_plano_instance and texto:
            plano_res = _gemini_plano_instance.estructurar_plano(texto)

        tmp_path.unlink(missing_ok=True)

        return {
            "ok": True,
            "cedula": cedula,
            "ocr": {
                "exito": ocr_res.get("exito"),
                "paginas": ocr_res.get("paginas", 0),
                "modelo": ocr_res.get("modelo", ""),
                "error": ocr_res.get("error"),
                "texto_completo": texto,
            },
            "plano": {
                "exito": plano_res.get("exito"),
                "modelo_gemini": plano_res.get("modelo", ""),
                "error": plano_res.get("error"),
                "campos_extraidos": plano_res.get("plano", {}),
            },
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


# ══════════════════════════════════════════════════════════════
# RE-EXTRACCIÓN: corre Gemini sobre OCR ya almacenado en BD
# Sirve para actualizar casos enviados SIN re-subir archivos
# ══════════════════════════════════════════════════════════════
@app.get("/test-plano/reextract/{serial}")
async def reextract_plano_serial(serial: str, db: Session = Depends(get_db)):
    """Re-extrae el plano Gemini de un caso ya existente usando el OCR guardado en metadata_form."""
    caso = db.query(Case).filter(Case.serial == serial).first()
    if not caso:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"Serial {serial} no encontrado"})

    meta = caso.metadata_form or {}
    texto_ocr = meta.get("texto_ocr_mistral", "")

    if not texto_ocr:
        return {"ok": False, "serial": serial, "error": "Este caso no tiene texto OCR almacenado (subido antes de la integración Mistral)"}

    if _gemini_plano_instance is None:
        return {"ok": False, "error": "GEMINI_API_KEY no configurada"}

    resultado = _gemini_plano_instance.estructurar_plano(texto_ocr)
    if resultado["exito"]:
        meta["plano_incapacidad"] = resultado
        caso.metadata_form = meta
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(caso, "metadata_form")
        db.commit()

    return {
        "ok": resultado["exito"],
        "serial": serial,
        "cedula": caso.cedula,
        "modelo_gemini": resultado.get("modelo", ""),
        "error": resultado.get("error", ""),
        "campos_extraidos": resultado.get("plano", {}),
        "texto_ocr_preview": texto_ocr[:500],
    }


@app.get("/test-plano/reextract-all")
async def reextract_plano_todos(db: Session = Depends(get_db)):
    """Re-extrae el plano Gemini en TODOS los casos que tienen OCR almacenado. Actualiza metadata_form."""
    from sqlalchemy.orm.attributes import flag_modified

    if _gemini_plano_instance is None:
        return {"ok": False, "error": "GEMINI_API_KEY no configurada"}

    casos = db.query(Case).all()
    resultados = {"ok": 0, "error": 0, "sin_ocr": 0, "detalles": []}

    for caso in casos:
        meta = caso.metadata_form or {}
        texto_ocr = meta.get("texto_ocr_mistral", "")
        if not texto_ocr:
            resultados["sin_ocr"] += 1
            continue

        try:
            res = _gemini_plano_instance.estructurar_plano(texto_ocr)
            meta["plano_incapacidad"] = res
            caso.metadata_form = meta
            flag_modified(caso, "metadata_form")
            db.commit()

            resultados["detalles"].append({
                "serial": caso.serial,
                "cedula": caso.cedula,
                "exito": res["exito"],
                "error": res.get("error", ""),
                "campos": res.get("plano", {}),
            })
            if res["exito"]:
                resultados["ok"] += 1
            else:
                resultados["error"] += 1
        except Exception as e:
            db.rollback()
            resultados["error"] += 1
            resultados["detalles"].append({"serial": caso.serial, "exito": False, "error": str(e)})

    return {
        "ok": True,
        "total_procesados": resultados["ok"] + resultados["error"],
        "exitosos": resultados["ok"],
        "errores": resultados["error"],
        "sin_ocr": resultados["sin_ocr"],
        "detalles": resultados["detalles"],
    }


def _es_ocr_malo(texto: str) -> bool:
    """Detecta si el texto OCR guardado es solo referencias de tabla sin contenido real.
    Por ejemplo: '[tbl-0.md](tbl-0.md)' o muy corto / vacío.
    """
    if not texto or not texto.strip():
        return True
    t = texto.strip()
    # Menos de 80 chars probablemente es un placeholder
    if len(t) < 80:
        return True
    # Solo contiene referencias Markdown de tabla, sin texto real
    import re
    sin_referencias = re.sub(r'\[tbl-\d+(?:\.md)?\]\(tbl-\d+(?:\.md)?\)', '', t).strip()
    if not sin_referencias or len(sin_referencias) < 20:
        return True
    return False


@app.get("/test-plano/reocr-from-drive")
async def reocr_desde_drive(db: Session = Depends(get_db)):
    """Re-descarga los PDFs desde Google Drive y re-corre Mistral OCR + Gemini Plano
    en todos los casos con OCR malo (placeholder [tbl-0.md](tbl-0.md)).
    Requiere que drive_link esté guardado en el caso."""
    import io
    import base64
    import re as _re

    if _mistral_ocr_instance is None:
        return {"ok": False, "error": "MISTRAL_API_KEY no configurada"}
    if _gemini_plano_instance is None:
        return {"ok": False, "error": "GEMINI_API_KEY no configurada"}

    try:
        from app.drive_uploader import get_authenticated_service
        from googleapiclient.http import MediaIoBaseDownload
    except Exception as e:
        return {"ok": False, "error": f"No se pudo importar Drive: {e}"}

    casos = db.query(Case).all()
    resultados = {"ok": 0, "error": 0, "sin_drive": 0, "ocr_ok": 0, "detalles": []}

    for caso in casos:
        meta = caso.metadata_form or {}
        texto_ocr = meta.get("texto_ocr_mistral", "")

        if not _es_ocr_malo(texto_ocr):
            continue  # OCR ya es bueno — no tocar

        if not caso.drive_link:
            resultados["sin_drive"] += 1
            resultados["detalles"].append({
                "serial": caso.serial,
                "ok": False,
                "razon": "sin_drive_link",
            })
            continue

        # Extraer file_id del link de Drive
        file_id = None
        if "/file/d/" in caso.drive_link:
            file_id = caso.drive_link.split("/file/d/")[1].split("/")[0]
        elif "id=" in caso.drive_link:
            file_id = caso.drive_link.split("id=")[1].split("&")[0]

        if not file_id:
            resultados["error"] += 1
            resultados["detalles"].append({
                "serial": caso.serial,
                "ok": False,
                "razon": f"no_se_pudo_extraer_file_id de {caso.drive_link}",
            })
            continue

        # Descargar PDF desde Drive
        try:
            service = get_authenticated_service()
            request = service.files().get_media(fileId=file_id)
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            buf.seek(0)
            pdf_bytes = buf.read()
        except Exception as e:
            resultados["error"] += 1
            resultados["detalles"].append({
                "serial": caso.serial,
                "ok": False,
                "razon": f"error_descarga_drive: {e}",
            })
            continue

        # Re-correr Mistral OCR con el PDF descargado (código ya corregido)
        try:
            pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")
            res_ocr = _mistral_ocr_instance.procesar_pdf_base64(pdf_b64)
        except Exception as e:
            resultados["error"] += 1
            resultados["detalles"].append({
                "serial": caso.serial,
                "ok": False,
                "razon": f"error_mistral_ocr: {e}",
            })
            continue

        if not res_ocr.get("exito") or not res_ocr.get("texto"):
            resultados["error"] += 1
            resultados["detalles"].append({
                "serial": caso.serial,
                "ok": False,
                "razon": f"ocr_sin_texto: {res_ocr.get('error')}",
            })
            continue

        texto_nuevo = res_ocr["texto"]
        resultados["ocr_ok"] += 1

        # Actualizar OCR en metadata y correr Gemini Plano
        meta["texto_ocr_mistral"] = texto_nuevo
        meta["ocr_mistral"] = {
            "exito": True,
            "paginas": res_ocr.get("paginas", 0),
            "modelo": res_ocr.get("modelo", ""),
            "reprocessed_at": datetime.utcnow().isoformat(),
        }

        res_gemini = _gemini_plano_instance.estructurar_plano(texto_nuevo)
        meta["plano_incapacidad"] = res_gemini

        caso.metadata_form = meta
        flag_modified(caso, "metadata_form")

        try:
            db.commit()
            resultados["ok"] += 1
            resultados["detalles"].append({
                "serial": caso.serial,
                "ok": True,
                "ocr_chars": len(texto_nuevo),
                "gemini_exito": res_gemini.get("exito"),
                "campos": res_gemini.get("plano", {}),
            })
        except Exception as e:
            db.rollback()
            resultados["error"] += 1
            resultados["detalles"].append({
                "serial": caso.serial,
                "ok": False,
                "razon": f"error_db_commit: {e}",
            })

    return {
        "ok": True,
        "total_con_ocr_malo": resultados["ok"] + resultados["error"] + resultados["sin_drive"],
        "re_procesados_ok": resultados["ok"],
        "errores": resultados["error"],
        "sin_drive_link": resultados["sin_drive"],
        "ocr_nuevo_exitoso": resultados["ocr_ok"],
        "detalles": resultados["detalles"],
    }


# ══════════════════════════════════════════════════════════════
# TEST EN PRODUCCIÓN: sube un PDF/imagen y ve qué extrae OCR+Gemini
# POST /test-plano/upload  (multipart: archivo = el PDF o foto)
# ══════════════════════════════════════════════════════════════
@app.post("/test-plano/upload")
async def test_plano_upload(archivo: UploadFile = File(...)):
    """
    Sube cualquier PDF o imagen (jpg/png) y devuelve:
    - El texto que extrajo Mistral OCR
    - Los campos que estructuró Gemini
    - Estadísticas: páginas, chars, tablas detectadas
    No guarda nada en BD. Solo sirve para probar el flujo OCR → Plano.
    """
    import base64

    if _mistral_ocr_instance is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "MISTRAL_API_KEY no configurada"})
    if _gemini_plano_instance is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "GEMINI_API_KEY no configurada"})

    nombre = archivo.filename or "sin_nombre"
    ext = Path(nombre).suffix.lower()
    contenido = await archivo.read()
    b64 = base64.b64encode(contenido).decode()

    # ── PASO 1: Mistral OCR ──────────────────────────────────────
    try:
        if ext == ".pdf":
            res_ocr = _mistral_ocr_instance.procesar_pdf_base64(b64)
        elif ext in {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif"}:
            mime_map = {
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png",  ".webp": "image/webp",
                ".tiff": "image/tiff", ".tif": "image/tiff",
            }
            res_ocr = _mistral_ocr_instance.procesar_imagen_base64(b64, tipo_mime=mime_map[ext])
        else:
            return JSONResponse(status_code=400, content={
                "ok": False,
                "error": f"Extensión '{ext}' no soportada. Usa pdf, jpg, png, webp o tiff."
            })
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": f"Error OCR: {e}"})

    if not res_ocr.get("exito"):
        return JSONResponse(status_code=422, content={
            "ok": False,
            "etapa": "ocr",
            "error": res_ocr.get("error"),
            "texto_ocr": "",
            "campos": {},
        })

    texto_ocr = res_ocr.get("texto", "")
    tablas_por_pagina = [
        len(p.get("tables", [])) for p in res_ocr.get("raw_pages", [])
    ]

    # ── PASO 2: Gemini Plano ─────────────────────────────────────
    try:
        res_gemini = _gemini_plano_instance.estructurar_plano(texto_ocr)
    except Exception as e:
        res_gemini = {"exito": False, "plano": {}, "error": str(e), "modelo": "?"}

    # ── Respuesta completa ───────────────────────────────────────
    return {
        "ok": True,
        "archivo": nombre,
        "tamano_bytes": len(contenido),
        "ocr": {
            "exito": res_ocr["exito"],
            "modelo": res_ocr.get("modelo", ""),
            "paginas": res_ocr.get("paginas", 0),
            "chars_extraidos": len(texto_ocr),
            "tablas_por_pagina": tablas_por_pagina,
            "total_tablas": sum(tablas_por_pagina),
            "texto_completo": texto_ocr,
            "texto_preview": texto_ocr[:600] + ("…" if len(texto_ocr) > 600 else ""),
        },
        "gemini": {
            "exito": res_gemini.get("exito"),
            "modelo": res_gemini.get("modelo", ""),
            "error": res_gemini.get("error", ""),
            "campos": res_gemini.get("plano", {}),
        },
        "dashboard_preview": {
            "medico":             res_gemini.get("plano", {}).get("medico") or "—",
            "lugar_atencion":     res_gemini.get("plano", {}).get("lugar_atencion") or "—",
            "nit_lugar_atencion": res_gemini.get("plano", {}).get("nit_lugar_atencion") or "—",
            "tipo_documento":     res_gemini.get("plano", {}).get("tipo_documento") or "CC",
            "codigo_cie10":       res_gemini.get("plano", {}).get("codigo_cie10") or "—",
            "dias_incapacidad":   res_gemini.get("plano", {}).get("dias_incapacidad") or "—",
            "origen":             res_gemini.get("plano", {}).get("origen") or "—",
        },
    }

