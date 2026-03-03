"""
Google Drive Upload con Cache, Thread-Safety y Auto-Recuperación
IncaNeurobaeza - 2024
"""

import os
import json
import time
import datetime
import threading
import functools
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Variables de entorno
CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN")
REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI")

# Archivo de cache del token (Render usa /tmp)
TOKEN_FILE = Path("/tmp/google_token.json")

# ==================== CACHE Y LOCKS ====================

# Cache global del servicio de Drive
_service_cache = None
_service_cache_lock = threading.Lock()

# Lock para renovación de credenciales (evita renovaciones simultáneas)
_creds_lock = threading.Lock()

# Contador de errores para auto-recuperación
_error_count = 0
_max_errors_before_clear = 3

# ==================== FUNCIONES DE CACHE ====================

def clear_service_cache():
    """Limpia el cache del servicio (útil cuando hay errores)"""
    global _service_cache, _error_count
    with _service_cache_lock:
        _service_cache = None
        _error_count = 0
    print("🧹 Cache del servicio limpiado")

def clear_token_cache():
    """Elimina el archivo de cache del token"""
    try:
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
            print("🧹 Token cache eliminado")
    except Exception as e:
        print(f"⚠️ Error eliminando token cache: {e}")

# ==================== DECORADOR DE RETRY ====================

def retry_on_error(max_retries=3, delay=2):
    """Decorator para reintentar automáticamente en caso de error"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    error_str = str(e).lower()
                    
                    print(f"⚠️ Error en {func.__name__} (intento {attempt+1}/{max_retries}): {e}")
                    
                    # Si es error de autenticación, limpiar cache
                    if any(x in error_str for x in ['unauthorized', 'invalid', 'expired', 'invalid_grant']):
                        print("🔄 Error de autenticación detectado, limpiando cache...")
                        clear_service_cache()
                        clear_token_cache()
                        
                        if attempt < max_retries - 1:
                            wait_time = delay * (2 ** attempt)  # Backoff exponencial
                            print(f"⏳ Esperando {wait_time}s antes de reintentar...")
                            time.sleep(wait_time)
                            continue
                    
                    # Si no es error de auth, no reintentar
                    raise
            
            raise last_exception
        return wrapper
    return decorator

# ==================== RENOVACIÓN DE CREDENCIALES ====================
def _get_or_refresh_credentials():
    """
    Obtiene o renueva las credenciales de Google Drive
    - Thread-safe (usa lock)
    - Renovación preventiva (5 minutos antes)
    - Auto-recuperación en caso de error
    ✅ CORREGIDO: Ahora siempre genera nuevo token si caduca
    """
    
    with _creds_lock:  # ← EVITA RENOVACIONES SIMULTÁNEAS
        creds = None
        needs_refresh = False
        
        # Validar que tenemos las credenciales necesarias
        if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
            raise ValueError(
                "❌ Faltan credenciales de Google Drive:\n"
                f"  CLIENT_ID: {'✅' if CLIENT_ID else '❌'}\n"
                f"  CLIENT_SECRET: {'✅' if CLIENT_SECRET else '❌'}\n"
                f"  REFRESH_TOKEN: {'✅' if REFRESH_TOKEN else '❌'}\n"
                "Configura estas variables en Render Dashboard → Environment"
            )
        
        # PASO 1: Intentar cargar token existente del cache
        if TOKEN_FILE.exists():
            try:
                with open(TOKEN_FILE, 'r') as token:
                    token_data = json.load(token)
                    creds = Credentials.from_authorized_user_info(
                        token_data, 
                        scopes=["https://www.googleapis.com/auth/drive.file"]
                    )
                    
                    # ✅ VERIFICAR SI NECESITA RENOVACIÓN
                    if creds.expiry:
                        now = datetime.datetime.now()
                        time_until_expiry = (creds.expiry - now).total_seconds()
                        minutes_left = time_until_expiry / 60
                        
                        # Renovar si expira en menos de 5 minutos o ya expiró
                        if time_until_expiry < 300:
                            if minutes_left < 0:
                                print(f"⚠️ Token EXPIRADO hace {abs(minutes_left):.1f} minutos")
                            else:
                                print(f"⏰ Token expira en {minutes_left:.1f} min, renovando preventivamente...")
                            needs_refresh = True
                        else:
                            print(f"✅ Token válido por {minutes_left:.1f} minutos más")
                            return creds  # ✅ Token válido, retornar
                    else:
                        # Si no tiene expiry, asumir que está válido
                        print("✅ Token sin fecha de expiración (válido)")
                        return creds
                        
            except Exception as e:
                print(f"⚠️ Error cargando token del cache: {e}")
                needs_refresh = True
        else:
            print("📝 No existe cache de token, generando nuevo...")
            needs_refresh = True
        
        # PASO 2: ✅ RENOVAR O GENERAR NUEVO TOKEN
        if needs_refresh or not creds:
            print("🔄 Generando/renovando access_token con refresh_token...")
            
            try:
                # ✅ SIEMPRE crear credenciales desde REFRESH_TOKEN
                # Esto funciona tanto si creds existe como si no
                new_creds = Credentials(
                    token=None,
                    refresh_token=REFRESH_TOKEN,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=CLIENT_ID,
                    client_secret=CLIENT_SECRET,
                    scopes=["https://www.googleapis.com/auth/drive.file"]
                )
                
                # Renovar para obtener el access_token
                new_creds.refresh(Request())
                
                print("✅ Token generado/renovado exitosamente")
                creds = new_creds
                
            except Exception as e:
                error_str = str(e)
                
                # ✅ DETECTAR SI EL REFRESH_TOKEN FUE REVOCADO
                if 'invalid_grant' in error_str.lower():
                    raise Exception(
                        "❌ ERROR CRÍTICO: El REFRESH_TOKEN ha sido revocado o es inválido.\n\n"
                        "SOLUCIÓN:\n"
                        "1. Ejecuta localmente: python regenerar_token.py\n"
                        "2. Copia el nuevo REFRESH_TOKEN\n"
                        "3. Actualízalo en Render Dashboard → Environment → GOOGLE_REFRESH_TOKEN\n"
                        "4. Guarda cambios y espera 1-2 minutos\n\n"
                        f"Detalles técnicos: {error_str}"
                    )
                
                raise Exception(f"Error renovando token: {error_str}")
        
        # PASO 3: Guardar token renovado en cache
        if creds:
            try:
                token_data = {
                    'token': creds.token,
                    'refresh_token': creds.refresh_token or REFRESH_TOKEN,  # ✅ Preservar refresh_token
                    'token_uri': creds.token_uri,
                    'client_id': creds.client_id,
                    'client_secret': creds.client_secret,
                    'scopes': creds.scopes,
                    'expiry': creds.expiry.isoformat() if creds.expiry else None
                }
                
                TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)  # ✅ Crear directorio si no existe
                
                with open(TOKEN_FILE, 'w') as token:
                    json.dump(token_data, token)
                
                print("💾 Token guardado en cache")
                
            except Exception as e:
                print(f"⚠️ No se pudo guardar token en cache: {e}")
                # No es crítico, podemos continuar
        
        return creds

# ==================== SERVICIO DE DRIVE ====================

@retry_on_error(max_retries=3, delay=2)
def get_authenticated_service():
    """
    Obtiene el servicio autenticado de Google Drive
    - Con cache para reutilizar servicio
    - Con retry automático en caso de error
    - Thread-safe
    """
    global _service_cache, _error_count
    
    # PASO 1: Si ya tenemos el servicio en cache, verificar si sigue válido
    with _service_cache_lock:
        if _service_cache is not None:
            try:
                # Test rápido: listar 1 archivo para verificar conexión
                _service_cache.files().list(pageSize=1, fields="files(id)").execute()
                _error_count = 0  # Reset contador de errores
                return _service_cache
            except Exception as e:
                print(f"⚠️ Servicio en cache inválido: {e}")
                _service_cache = None
                _error_count += 1
                
                # Si hay muchos errores consecutivos, limpiar todo
                if _error_count >= _max_errors_before_clear:
                    print(f"⚠️ {_error_count} errores consecutivos, limpiando cache completo...")
                    clear_token_cache()
                    _error_count = 0
    
    # PASO 2: Necesitamos crear/renovar el servicio
    print("🔧 Creando nuevo servicio de Google Drive...")
    creds = _get_or_refresh_credentials()
    
    try:
        service = build('drive', 'v3', credentials=creds)
        
        # Verificar que el servicio funciona
        service.files().list(pageSize=1, fields="files(id)").execute()
        print("✅ Servicio de Drive creado y verificado")
        
        # Guardar en cache
        with _service_cache_lock:
            _service_cache = service
            _error_count = 0
        
        return service
    except Exception as e:
        print(f"❌ Error creando servicio de Drive: {e}")
        raise

# ==================== FUNCIONES DE UTILIDAD ====================

def create_folder_if_not_exists(service, folder_name, parent_folder_id='root'):
    """Crea una carpeta en Drive si no existe"""
    folder_name_bytes = folder_name if isinstance(folder_name, bytes) else folder_name.encode()
    parent_id = parent_folder_id if isinstance(parent_folder_id, str) else parent_folder_id.decode()
    
    # Buscar carpeta existente
    query = f"name='{folder_name_bytes.decode()}' and mimeType='application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed=false"
    results = service.files().list(q=query, spaces='drive', fields="files(id, name)").execute()
    folders = results.get('files', [])
    
    if folders:
        print(f"📁 Carpeta '{folder_name_bytes.decode()}' ya existe (ID: {folders[0]['id']})")
        return folders[0]['id']
    
    # Crear carpeta
    folder_metadata = {
        'name': folder_name_bytes.decode(),
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id]
    }
    
    folder = service.files().create(body=folder_metadata, fields='id').execute()
    print(f"✅ Carpeta '{folder_name_bytes.decode()}' creada (ID: {folder.get('id')})")
    return folder.get('id')

def get_quinzena_folder_name():
    """Determina el nombre de la carpeta de quincena actual"""
    from datetime import datetime
    import calendar
    
    today = datetime.now()
    mes = today.strftime("%B")
    
    meses_es = {
        'January': 'Enero', 'February': 'Febrero', 'March': 'Marzo',
        'April': 'Abril', 'May': 'Mayo', 'June': 'Junio',
        'July': 'Julio', 'August': 'Agosto', 'September': 'Septiembre',
        'October': 'Octubre', 'November': 'Noviembre', 'December': 'Diciembre'
    }
    mes_es = meses_es.get(mes, mes)
    
    if today.day <= 15:
        return f"Primera_Quincena_{mes_es}"
    else:
        return f"Segunda_Quincena_{mes_es}"

def normalize_tipo_incapacidad(tipo: str, subtipo: str = None) -> str:
    """Normaliza el tipo de incapacidad al formato de carpeta"""
    tipo_a_usar = subtipo if subtipo else tipo
    
    tipo_map = {
        'maternidad': 'Maternidad',
        'maternity': 'Maternidad',
        'paternidad': 'Paternidad',
        'paternity': 'Paternidad',
        'enfermedad general': 'Enfermedad_General',
        'enfermedad_general': 'Enfermedad_General',
        'general': 'Enfermedad_General',
        'accidente laboral': 'Accidente_Laboral',
        'accidente_laboral': 'Accidente_Laboral',
        'labor': 'Accidente_Laboral',
        'accidente de tránsito': 'Accidente_Transito',
        'accidente_transito': 'Accidente_Transito',
        'accidente de transito': 'Accidente_Transito',
        'traffic': 'Accidente_Transito',
        'especial': 'Enfermedad_Especial',
        'certificado_hospitalizacion': 'Certificado_Hospitalizacion',
        'certificado': 'Certificado_Hospitalizacion',
        'prelicencia': 'Prelicencia'
    }
    return tipo_map.get(tipo_a_usar.lower(), tipo_a_usar.replace(' ', '_').title())

# ==================== FUNCIÓN PRINCIPAL DE UPLOAD ====================

@retry_on_error(max_retries=3, delay=2)
def upload_to_drive(
    file_path: Path, 
    empresa: str, 
    cedula: str, 
    tipo: str, 
    consecutivo: str = None,
    tiene_soat: bool = None,
    tiene_licencia: bool = None,
    subtipo: str = None,
    fecha_inicio = None,
    fecha_fin = None
) -> str:
    """
    Sube archivo a Google Drive con estructura de carpetas
    - Con retry automático
    - Con auto-recuperación de errores
    """
    from datetime import datetime
    
    try:
        service = get_authenticated_service()
        
        año_actual = str(datetime.now().year)
        fecha = datetime.now().strftime("%Y%m%d")
        
        # Crear estructura de carpetas
        print(f"📁 Creando estructura de carpetas en Drive...")
        main_folder_id = create_folder_if_not_exists(service, b"Incapacidades", 'root')
        empresa_folder_id = create_folder_if_not_exists(service, empresa.encode() if isinstance(empresa, str) else empresa, main_folder_id)
        year_folder_id = create_folder_if_not_exists(service, año_actual.encode(), empresa_folder_id)
        
        quinzena_nombre = get_quinzena_folder_name()
        quinzena_folder_id = create_folder_if_not_exists(service, quinzena_nombre.encode(), year_folder_id)
        
        tipo_normalizado = normalize_tipo_incapacidad(tipo, subtipo)
        tipo_folder_id = create_folder_if_not_exists(service, tipo_normalizado.encode(), quinzena_folder_id)
        
        final_folder_id = tipo_folder_id
        
        # Subcarpetas especiales
        if tipo_normalizado == 'Accidente_Transito' and tiene_soat is not None:
            subfolder_name = 'Con_SOAT' if tiene_soat else 'Sin_SOAT'
            final_folder_id = create_folder_if_not_exists(service, subfolder_name.encode(), tipo_folder_id)
        
        elif tipo_normalizado == 'Paternidad' and tiene_licencia is not None:
            subfolder_name = 'Con_Licencia' if tiene_licencia else 'Sin_Licencia'
            final_folder_id = create_folder_if_not_exists(service, subfolder_name.encode(), tipo_folder_id)
        
        # Nombre del archivo - CÉDULA + FECHA INICIO + FECHA FIN
        if fecha_inicio and fecha_fin:
            # Formatear fechas a DD MM YYYY
            try:
                from datetime import date as _date_type
                if isinstance(fecha_inicio, _date_type):
                    fi_str = fecha_inicio.strftime("%d %m %Y")
                else:
                    fi_str = str(fecha_inicio).replace("-", " ")
                if isinstance(fecha_fin, _date_type):
                    ff_str = fecha_fin.strftime("%d %m %Y")
                else:
                    ff_str = str(fecha_fin).replace("-", " ")
            except:
                fi_str = str(fecha_inicio)
                ff_str = str(fecha_fin)
            filename = f"{cedula} {fi_str} {ff_str}.pdf"
        else:
            filename = f"{cedula} {fecha}.pdf"
        
        print(f"📤 Subiendo archivo: {filename}")
        
        file_metadata = {
            'name': filename,
            'parents': [final_folder_id],
            'description': f'Incapacidad {tipo} - Cédula: {cedula} - Empresa: {empresa}'
        }
        
        media = MediaFileUpload(str(file_path), mimetype='application/pdf', resumable=True)
        
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id,webViewLink,webContentLink'
        ).execute()
        
        # Hacer público
        try:
            service.permissions().create(
                fileId=file.get('id'),
                body={'role': 'reader', 'type': 'anyone'}
            ).execute()
        except Exception as e:
            print(f"⚠️ No se pudo hacer público: {e}")
        
        link = file.get('webViewLink', f"https://drive.google.com/file/d/{file.get('id')}/view")
        print(f"✅ Archivo subido exitosamente")
        print(f"🔗 Link: {link}")
        return link
        
    except Exception as e:
        error_msg = f"Error subiendo archivo a Drive: {str(e)}"
        print(f"❌ {error_msg}")
        raise Exception(error_msg)

def get_folder_link(empresa: str) -> str:
    """Obtiene el link de la carpeta de una empresa"""
    try:
        service = get_authenticated_service()
        main_folder_id = create_folder_if_not_exists(service, b"Incapacidades", 'root')
        empresa_folder_id = create_folder_if_not_exists(service, empresa.encode() if isinstance(empresa, str) else empresa, main_folder_id)
        return f"https://drive.google.com/drive/folders/{empresa_folder_id}"
    except Exception as e:
        return f"Error: {str(e)}"

# ==================== DRIVE UPLOADER V3 - CERTIFICADOS Y PRELICENCIAS ====================
"""
Drive Uploader V3 - Solo para Certificados y Prelicencias
IncaNeurobaeza - 2025

NO TOCA NADA DE INCAPACIDADES NI INCOMPLETAS
"""

from datetime import date as date_type

def get_quinzena_from_date(fecha: date_type) -> str:
    """Determina la quincena desde una fecha"""
    meses_es = {
        1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
        5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
        9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
    }
    
    mes_nombre = meses_es[fecha.month]
    
    if fecha.day <= 15:
        return f"Primera_Quincena_{mes_nombre}"
    else:
        return f"Segunda_Quincena_{mes_nombre}"


def upload_certificado_o_prelicencia(
    file_path: Path,
    empresa: str,
    cedula: str,
    tipo: str,  # 'certificado_hospitalizacion' o 'prelicencia'
    serial: str,
    fecha_inicio: date_type
) -> str:
    """
    Sube certificado o prelicencia a Drive
    
    Estructura:
    Certificados_Hospitalizacion/  o  Prelicencias/
    └── 2026/
        └── {Empresa}/
            └── Primera_Quincena_Enero/
                └── 1085043374-12-01-2026-02-02-2026.pdf
    
    Args:
        file_path: Ruta del PDF
        empresa: Nombre de la empresa
        cedula: Cédula del empleado
        tipo: 'certificado_hospitalizacion' o 'prelicencia'
        serial: Serial completo (ej: "1085043374-12-01-2026-02-02-2026" en formato DD-MM-YYYY)
        fecha_inicio: Fecha de inicio para determinar quincena
    
    Returns:
        str: Link de Google Drive
    """
    
    try:
        service = get_authenticated_service()
        
        # Determinar carpeta raíz
        if 'certificado' in tipo.lower() or 'hospitalizacion' in tipo.lower():
            carpeta_raiz_nombre = 'Certificados_Hospitalizacion'
        elif 'prelicencia' in tipo.lower():
            carpeta_raiz_nombre = 'Prelicencias'
        else:
            raise ValueError(f"Tipo no soportado: {tipo}")
        
        # === CREAR ESTRUCTURA ===
        
        # 1. Carpeta raíz
        carpeta_raiz_id = create_folder_if_not_exists(
            service,
            carpeta_raiz_nombre.encode(),
            'root'
        )
        
        # 2. Año
        año_str = str(fecha_inicio.year)
        año_folder_id = create_folder_if_not_exists(
            service,
            año_str.encode(),
            carpeta_raiz_id
        )
        
        # 3. Empresa
        empresa_folder_id = create_folder_if_not_exists(
            service,
            empresa.encode() if isinstance(empresa, str) else empresa,
            año_folder_id
        )
        
        # 4. Quincena
        quinzena_nombre = get_quinzena_from_date(fecha_inicio)
        quinzena_folder_id = create_folder_if_not_exists(
            service,
            quinzena_nombre.encode(),
            empresa_folder_id
        )
        
        # === SUBIR ARCHIVO ===
        
        filename = f"{serial}.pdf"
        
        print(f"📤 Subiendo {carpeta_raiz_nombre}:")
        print(f"   📁 {año_str}/{empresa}/{quinzena_nombre}/")
        print(f"   📄 {filename}")
        
        file_metadata = {
            'name': filename,
            'parents': [quinzena_folder_id],
            'description': f'{tipo.upper()} - Cédula: {cedula} - Empresa: {empresa} - Fecha: {fecha_inicio}'
        }
        
        media = MediaFileUpload(
            str(file_path),
            mimetype='application/pdf',
            resumable=True
        )
        
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id,webViewLink,webContentLink'
        ).execute()
        
        # Hacer público
        try:
            service.permissions().create(
                fileId=file.get('id'),
                body={'role': 'reader', 'type': 'anyone'}
            ).execute()
        except Exception as e:
            print(f"⚠️ No se pudo hacer público: {e}")
        
        link = file.get('webViewLink', f"https://drive.google.com/file/d/{file.get('id')}/view")
        
        print(f"✅ Subido exitosamente")
        print(f"🔗 Link: {link}")
        
        return link
        
    except Exception as e:
        print(f"❌ Error subiendo a Drive: {e}")
        raise


def upload_inteligente(
    file_path: Path,
    empresa: str,
    cedula: str,
    tipo: str,
    serial: str,
    fecha_inicio: date_type = None,
    fecha_fin: date_type = None,
    **kwargs  # Para mantener compatibilidad
) -> str:
    """
    Upload inteligente que decide automáticamente:
    - Certificados/Prelicencias → Nueva estructura
    - Incapacidades → Sistema actual (sin tocar)
    
    Args:
        file_path: Ruta del archivo
        empresa: Empresa
        cedula: Cédula
        tipo: Tipo de documento
        serial: Serial único
        fecha_inicio: Fecha inicio (requerida para certificados y como parte del nombre)
        fecha_fin: Fecha fin (para incluir en nombre del archivo)
        **kwargs: tiene_soat, tiene_licencia, subtipo (para incapacidades)
    
    Returns:
        str: Link de Drive
    """
    
    tipo_lower = tipo.lower()
    
    # CERTIFICADOS O PRELICENCIAS → Nueva estructura
    if tipo_lower in ['certificado_hospitalizacion', 'prelicencia', 'hospitalizacion']:
        
        if not fecha_inicio:
            fecha_inicio = date_type.today()
            print(f"⚠️ No se proporcionó fecha, usando hoy: {fecha_inicio}")
        
        return upload_certificado_o_prelicencia(
            file_path, empresa, cedula, tipo, serial, fecha_inicio
        )
    
    # INCAPACIDADES TRADICIONALES → Mantener sistema actual
    else:
        print(f"📋 Usando sistema tradicional para: {tipo}")
        
        return upload_to_drive(
            file_path,
            empresa,
            cedula,
            tipo,
            serial,
            tiene_soat=kwargs.get('tiene_soat'),
            tiene_licencia=kwargs.get('tiene_licencia'),
            subtipo=kwargs.get('subtipo'),
            fecha_inicio=fecha_inicio,   # ✅ FIX: Usar parámetro directo, no kwargs
            fecha_fin=fecha_fin          # ✅ FIX: Usar parámetro directo, no kwargs
        )


# ==================== WRAPPER INTELIGENTE ====================

def upload_to_drive_v3(file_path, empresa, cedula, tipo, serial, **kwargs):
    """
    Wrapper inteligente que detecta automáticamente:
    - Certificados/Prelicencias → Nueva estructura V3
    - Incapacidades → Sistema tradicional
    
    NOTA: No reemplaza la función upload_to_drive original
    """
    
    fecha_inicio = kwargs.get('fecha_inicio')
    
    return upload_inteligente(
        file_path, empresa, cedula, tipo, serial,
        fecha_inicio, **kwargs
    )


# ==================== TESTS ====================

def test_estructura_certificados():
    """Prueba la creación de estructura para certificados"""
    
    print("🧪 Probando estructura Drive V3...\n")
    
    # Test 1: Determinar quincena
    print("Test 1: Determinación de quincena")
    test_dates = [
        date_type(2025, 1, 10),   # Primera quincena enero
        date_type(2025, 1, 20),   # Segunda quincena enero
        date_type(2025, 2, 1)     # Primera quincena febrero
    ]
    
    for test_date in test_dates:
        quinzena = get_quinzena_from_date(test_date)
        print(f"  {test_date} → {quinzena}")
    
    print("\n✅ Tests completados")


if __name__ == "__main__":
    test_estructura_certificados()