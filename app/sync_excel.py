"""
Sincronización AUTOMÁTICA Google Sheets → PostgreSQL
✅ SYNC EXACTO: La BD refleja el Excel tal cual (misma cantidad, mismo orden)
✅ Cases_Kactus: Crea casos, marca procesados con fecha, limpia > 15 días
"""

import os
import pandas as pd
import requests
from datetime import datetime, timedelta
from app.database import SessionLocal, Employee, Company, Case, CorreoNotificacion
from io import BytesIO

GOOGLE_DRIVE_FILE_ID = os.environ.get("GOOGLE_DRIVE_FILE_ID", "1POt2ytSN61XbSpXUSUPyHdOVy2g7CRas")
EXCEL_DOWNLOAD_URL = f"https://docs.google.com/spreadsheets/d/{GOOGLE_DRIVE_FILE_ID}/export?format=xlsx"
LOCAL_CACHE_PATH = "/tmp/base_empleados_cache.xlsx"

# Configuración de limpieza automática
DIAS_ANTIGUEDAD_LIMPIEZA = 15  # Eliminar filas procesadas hace más de 15 días
COLUMNA_PROCESADO = "Procesado"  # Nombre de la columna de fecha de procesamiento


def _get_sheets_service():
    """Obtiene el servicio de Google Sheets API."""
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    import json
    
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        print("   ⚠️ Sin credenciales de Google")
        return None
    
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    return build('sheets', 'v4', credentials=creds)


def _marcar_filas_procesadas_kactus(filas: list, columna_procesado_idx: int = None):
    """
    Marca filas como procesadas escribiendo la fecha actual en la columna "Procesado".
    Si la columna no existe, la crea automáticamente.
    
    Args:
        filas: Lista de números de fila (1-indexed, incluye header, así que fila 2 es primera de datos)
        columna_procesado_idx: Índice de la columna Procesado (0-indexed). Si es None, se detecta/crea.
    """
    if not filas:
        return
    
    try:
        service = _get_sheets_service()
        if not service:
            return
        
        # Obtener info del spreadsheet
        spreadsheet = service.spreadsheets().get(spreadsheetId=GOOGLE_DRIVE_FILE_ID).execute()
        sheets = spreadsheet.get('sheets', [])
        
        if len(sheets) < 2:
            print("   ⚠️ No existe Hoja 2 (Cases_Kactus) en el Sheet")
            return
        
        sheet_name = sheets[1]['properties']['title']
        
        # Leer la primera fila (headers) para encontrar o crear columna "Procesado"
        headers_result = service.spreadsheets().values().get(
            spreadsheetId=GOOGLE_DRIVE_FILE_ID,
            range=f"'{sheet_name}'!1:1"
        ).execute()
        
        headers = headers_result.get('values', [[]])[0]
        
        # Buscar o crear columna "Procesado"
        if COLUMNA_PROCESADO in headers:
            col_idx = headers.index(COLUMNA_PROCESADO)
        else:
            # Crear columna al final
            col_idx = len(headers)
            col_letter = _idx_to_col_letter(col_idx)
            
            # Escribir header "Procesado"
            service.spreadsheets().values().update(
                spreadsheetId=GOOGLE_DRIVE_FILE_ID,
                range=f"'{sheet_name}'!{col_letter}1",
                valueInputOption='RAW',
                body={'values': [[COLUMNA_PROCESADO]]}
            ).execute()
            print(f"   📝 Creada columna '{COLUMNA_PROCESADO}' en posición {col_letter}")
        
        col_letter = _idx_to_col_letter(col_idx)
        fecha_procesado = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # Actualizar cada fila con la fecha de procesamiento
        data = []
        for fila in filas:
            data.append({
                'range': f"'{sheet_name}'!{col_letter}{fila}",
                'values': [[fecha_procesado]]
            })
        
        if data:
            service.spreadsheets().values().batchUpdate(
                spreadsheetId=GOOGLE_DRIVE_FILE_ID,
                body={
                    'valueInputOption': 'RAW',
                    'data': data
                }
            ).execute()
            print(f"   ✅ {len(filas)} filas marcadas como procesadas ({fecha_procesado})")
    
    except Exception as e:
        print(f"   ⚠️ Error marcando filas procesadas: {e}")


def _limpiar_filas_antiguas_kactus(dias_antiguedad: int = None):
    """
    Elimina filas de Cases_Kactus que fueron procesadas hace más de X días.
    
    Args:
        dias_antiguedad: Días de antigüedad (default: DIAS_ANTIGUEDAD_LIMPIEZA = 15)
    
    Returns:
        int: Número de filas eliminadas
    """
    if dias_antiguedad is None:
        dias_antiguedad = DIAS_ANTIGUEDAD_LIMPIEZA
    
    try:
        service = _get_sheets_service()
        if not service:
            return 0
        
        # Obtener info del spreadsheet
        spreadsheet = service.spreadsheets().get(spreadsheetId=GOOGLE_DRIVE_FILE_ID).execute()
        sheets = spreadsheet.get('sheets', [])
        
        if len(sheets) < 2:
            print("   ℹ️ No existe Hoja 2 (Cases_Kactus)")
            return 0
        
        sheet_name = sheets[1]['properties']['title']
        sheet_id = sheets[1]['properties']['sheetId']
        
        # Leer todos los datos de la hoja
        result = service.spreadsheets().values().get(
            spreadsheetId=GOOGLE_DRIVE_FILE_ID,
            range=f"'{sheet_name}'"
        ).execute()
        
        all_values = result.get('values', [])
        if len(all_values) < 2:  # Solo header o vacío
            print("   ℹ️ Hoja Cases_Kactus vacía")
            return 0
        
        headers = all_values[0]
        
        # Buscar columna "Procesado"
        if COLUMNA_PROCESADO not in headers:
            print(f"   ℹ️ Columna '{COLUMNA_PROCESADO}' no encontrada - nada que limpiar")
            return 0
        
        col_idx = headers.index(COLUMNA_PROCESADO)
        fecha_limite = datetime.now() - timedelta(days=dias_antiguedad)
        filas_a_eliminar = []
        
        # Revisar cada fila (desde la 2 porque la 1 es header)
        for i, row in enumerate(all_values[1:], start=2):  # i = número de fila en Excel (1-indexed)
            if len(row) > col_idx and row[col_idx]:
                try:
                    # Intentar parsear la fecha
                    fecha_str = row[col_idx].strip()
                    if fecha_str:
                        # Soportar formato "YYYY-MM-DD HH:MM" o "YYYY-MM-DD"
                        if ' ' in fecha_str:
                            fecha_procesado = datetime.strptime(fecha_str, "%Y-%m-%d %H:%M")
                        else:
                            fecha_procesado = datetime.strptime(fecha_str, "%Y-%m-%d")
                        
                        if fecha_procesado < fecha_limite:
                            filas_a_eliminar.append(i)
                except ValueError:
                    pass  # Fecha inválida, ignorar
        
        if not filas_a_eliminar:
            print(f"   ℹ️ No hay filas con más de {dias_antiguedad} días de procesadas")
            return 0
        
        # Ordenar descendente para eliminar desde abajo (no afecta índices)
        filas_ordenadas = sorted(filas_a_eliminar, reverse=True)
        
        # Crear requests de eliminación
        requests_delete = []
        for fila in filas_ordenadas:
            requests_delete.append({
                'deleteDimension': {
                    'range': {
                        'sheetId': sheet_id,
                        'dimension': 'ROWS',
                        'startIndex': fila - 1,  # 0-indexed
                        'endIndex': fila
                    }
                }
            })
        
        service.spreadsheets().batchUpdate(
            spreadsheetId=GOOGLE_DRIVE_FILE_ID,
            body={'requests': requests_delete}
        ).execute()
        
        print(f"   🗑️ {len(filas_ordenadas)} filas antiguas eliminadas (> {dias_antiguedad} días)")
        return len(filas_ordenadas)
    
    except Exception as e:
        print(f"   ⚠️ Error limpiando filas antiguas: {e}")
        return 0


def _idx_to_col_letter(idx: int) -> str:
    """Convierte índice 0-based a letra de columna Excel (0=A, 1=B, 26=AA, etc.)"""
    result = ""
    while idx >= 0:
        result = chr(idx % 26 + ord('A')) + result
        idx = idx // 26 - 1
    return result

def descargar_excel_desde_drive():
    """Descarga el Excel desde Google Drive"""
    try:
        print(f"📥 Descargando Excel desde Google Sheets...")
        response = requests.get(EXCEL_DOWNLOAD_URL, timeout=30)
        
        if response.status_code == 200:
            with open(LOCAL_CACHE_PATH, 'wb') as f:
                f.write(response.content)
            print(f"✅ Excel descargado correctamente ({len(response.content)} bytes)")
            return LOCAL_CACHE_PATH
        else:
            print(f"❌ Error descargando Excel: HTTP {response.status_code}")
            if os.path.exists(LOCAL_CACHE_PATH):
                print(f"⚠️ Usando cache anterior")
                return LOCAL_CACHE_PATH
            return None
    except Exception as e:
        print(f"❌ Error descargando Excel: {e}")
        if os.path.exists(LOCAL_CACHE_PATH):
            print(f"⚠️ Usando cache anterior")
            return LOCAL_CACHE_PATH
        return None


def sincronizar_empleado_desde_excel(cedula: str):
    """Sincroniza UN empleado especifico (sync instantanea)"""
    db = SessionLocal()
    try:
        empleado_bd = db.query(Employee).filter(Employee.cedula == cedula).first()
        if empleado_bd:
            print(f"✅ Empleado {cedula} ya esta en BD")
            return empleado_bd
        
        excel_path = descargar_excel_desde_drive()
        if not excel_path:
            print(f"❌ No se pudo descargar el Excel")
            return None
        
        df = pd.read_excel(excel_path, sheet_name=0)
        try:
            cedula_int = int(cedula)
        except ValueError:
            print(f"❌ Cedula invalida: {cedula}")
            return None
        
        empleado_excel = df[df["cedula"] == cedula_int]
        if empleado_excel.empty:
            print(f"❌ Empleado {cedula} no encontrado en Excel")
            return None
        
        row = empleado_excel.iloc[0]
        empresa_nombre = row["empresa"]
        company = db.query(Company).filter(Company.nombre == empresa_nombre).first()
        if not company:
            company = Company(nombre=empresa_nombre, activa=True)
            db.add(company)
            db.commit()
            db.refresh(company)
        
        nuevo_empleado = Employee(
            cedula=str(row["cedula"]),
            nombre=row["nombre"],
            correo=row["correo"],
            telefono=str(row.get("telefono", "")) if pd.notna(row.get("telefono")) else None,
            company_id=company.id,
            eps=row.get("eps", None),
            jefe_nombre=row.get("jefe_nombre", None),
            jefe_email=row.get("jefe_email", None),
            jefe_cargo=row.get("jefe_cargo", None),
            area_trabajo=row.get("area_trabajo", None),
            cargo=row.get("cargo", None) if pd.notna(row.get("cargo", None)) else None,
            centro_costo=row.get("centro_costo", None) if pd.notna(row.get("centro_costo", None)) else None,
            fecha_ingreso=pd.to_datetime(row.get("fecha_ingreso")) if pd.notna(row.get("fecha_ingreso", None)) else None,
            tipo_contrato=row.get("tipo_contrato", None) if pd.notna(row.get("tipo_contrato", None)) else None,
            ciudad=row.get("ciudad", None) if pd.notna(row.get("ciudad", None)) else None,
            activo=True
        )
        db.add(nuevo_empleado)
        db.commit()
        db.refresh(nuevo_empleado)
        print(f"✅ Empleado {cedula} sincronizado: {nuevo_empleado.nombre}")
        return nuevo_empleado
    except Exception as e:
        print(f"❌ Error sincronizando {cedula}: {e}")
        db.rollback()
        return None
    finally:
        db.close()


def sincronizar_excel_completo():
    """
    ✅ SYNC EXACTO POR POSICIÓN
    - Fila 1 Excel = ID 1 en BD
    - Fila 2 Excel = ID 2 en BD
    - Si editas Fila 3, actualiza ID 3 (NO crea ID 9)
    - Si Excel tiene 8 filas, BD tiene 8 empleados activos
    """
    db = SessionLocal()
    try:
        print(f"\n{'='*60}")
        print(f"🔄 SYNC EXACTO Excel → PostgreSQL - {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*60}\n")
        
        excel_path = descargar_excel_desde_drive()
        if not excel_path:
            print(f"❌ No se pudo descargar el Excel, sync cancelado\n")
            return
        
        # ========== PASO 1: EMPRESAS (Hoja 2) — OMITIDO ==========
        # ✅ Los emails de copia por empresa ahora se gestionan desde el DIRECTORIO
        # del admin portal (correos_notificacion area='empresas').
        # Ya NO se sincronizan desde el Excel Hoja 2.
        print(f"📊 PASO 1: Emails empresas → Se gestionan desde el Directorio del Admin Portal (omitido)")
        print(f"   ℹ️ Si necesita cambiar emails, use el Directorio en el portal admin\n")
        
        # ========== PASO 2: SYNC EMPLEADOS EXACTO ==========
        print(f"📊 PASO 2: Sincronizando empleados (MODO EXACTO)...")
        
        df = pd.read_excel(excel_path, sheet_name=0)
        print(f"   📋 Excel tiene {len(df)} filas")
        
        # Obtener TODOS los empleados de BD ordenados por ID
        empleados_bd = db.query(Employee).order_by(Employee.id).all()
        print(f"   📋 BD tiene {len(empleados_bd)} empleados totales")
        
        # Crear lista de empleados activos en BD
        empleados_activos = [e for e in empleados_bd if e.activo]
        print(f"   📋 BD tiene {len(empleados_activos)} empleados activos")
        
        nuevos = actualizados = eliminados = 0
        
        # ✅ SINCRONIZACIÓN POSICIÓN POR POSICIÓN
        for idx, row in df.iterrows():
            try:
                if pd.isna(row.get("cedula")) or pd.isna(row.get("nombre")):
                    continue
                
                # Datos del Excel
                cedula = str(int(row["cedula"]))
                nombre = row["nombre"]
                correo = row.get("correo", "")
                telefono = str(row.get("telefono", "")) if pd.notna(row.get("telefono")) else None
                eps = row.get("eps", None)
                empresa_nombre = row["empresa"]
                
                jefe_nombre = row.get("jefe_nombre", None)
                jefe_email = row.get("jefe_email", None)
                jefe_cargo = row.get("jefe_cargo", None)
                area_trabajo = row.get("area_trabajo", None)
                
                # ✅ COLUMNAS KACTUS
                cargo = row.get("cargo", None) if pd.notna(row.get("cargo", None)) else None
                centro_costo = row.get("centro_costo", None) if pd.notna(row.get("centro_costo", None)) else None
                fecha_ingreso_raw = row.get("fecha_ingreso", None)
                fecha_ingreso = None
                if pd.notna(fecha_ingreso_raw):
                    try:
                        fecha_ingreso = pd.to_datetime(fecha_ingreso_raw)
                    except Exception:
                        fecha_ingreso = None
                tipo_contrato = row.get("tipo_contrato", None) if pd.notna(row.get("tipo_contrato", None)) else None
                # dias_kactus eliminado: ya no se usa en empleados
                ciudad = row.get("ciudad", None) if pd.notna(row.get("ciudad", None)) else None
                
                # Buscar o crear empresa
                company = db.query(Company).filter(Company.nombre == empresa_nombre).first()
                if not company:
                    company = Company(nombre=empresa_nombre, activa=True)
                    db.add(company)
                    db.commit()
                    db.refresh(company)
                
                # ✅ LÓGICA CLAVE: Buscar empleado en la MISMA POSICIÓN
                empleado = None
                
                # Si ya existe un empleado en esta posición (índice)
                if idx < len(empleados_activos):
                    empleado = empleados_activos[idx]
                
                if empleado:
                    # ✅ ACTUALIZAR el empleado existente en esta posición
                    empleado.cedula = cedula
                    empleado.nombre = nombre
                    empleado.correo = correo
                    empleado.telefono = telefono
                    empleado.company_id = company.id
                    empleado.eps = eps
                    empleado.jefe_nombre = jefe_nombre
                    empleado.jefe_email = jefe_email
                    empleado.jefe_cargo = jefe_cargo
                    empleado.area_trabajo = area_trabajo
                    empleado.cargo = cargo
                    empleado.centro_costo = centro_costo
                    empleado.fecha_ingreso = fecha_ingreso
                    empleado.tipo_contrato = tipo_contrato
                    # empleado.dias_kactus eliminado
                    empleado.ciudad = ciudad
                    empleado.activo = True
                    empleado.updated_at = datetime.now()
                    db.commit()
                    actualizados += 1
                else:
                    # ✅ CREAR nuevo empleado (si Excel tiene más filas que BD)
                    nuevo_empleado = Employee(
                        cedula=cedula,
                        nombre=nombre,
                        correo=correo,
                        telefono=telefono,
                        company_id=company.id,
                        eps=eps,
                        jefe_nombre=jefe_nombre,
                        jefe_email=jefe_email,
                        jefe_cargo=jefe_cargo,
                        area_trabajo=area_trabajo,
                        cargo=cargo,
                        centro_costo=centro_costo,
                        fecha_ingreso=fecha_ingreso,
                        tipo_contrato=tipo_contrato,
                        # dias_kactus eliminado,
                        ciudad=ciudad,
                        activo=True
                    )
                    db.add(nuevo_empleado)
                    db.commit()
                    nuevos += 1
            
            except Exception as e:
                print(f"   ❌ Error en fila {idx + 2}: {e}")
                db.rollback()
        
        # ✅ ELIMINAR empleados sobrantes (si BD tiene más que Excel)
        total_filas_excel = len(df)
        if len(empleados_activos) > total_filas_excel:
            print(f"   🗑️ BD tiene {len(empleados_activos) - total_filas_excel} empleados de más, eliminando...")
            for i in range(total_filas_excel, len(empleados_activos)):
                empleado_sobra = empleados_activos[i]
                empleado_sobra.activo = False
                empleado_sobra.updated_at = datetime.now()
                db.commit()
                eliminados += 1
        
        # RESUMEN
        print(f"\n{'='*60}")
        print(f"✅ SYNC COMPLETADO")
        print(f"   • Emails empresas: Gestionados desde Directorio (admin portal)")
        print(f"   • Empleados nuevos: {nuevos}")
        print(f"   • Empleados actualizados: {actualizados}")
        print(f"   • Empleados eliminados: {eliminados}")
        print(f"   • Total activos en BD: {total_filas_excel}")
        print(f"{'='*60}\n")
        
        # ========== PASO 3: SYNC CASES_KACTUS (Hoja 2) — IMPORTAR CASOS (INCLUYE HISTÓRICOS) ==========
        # ═══════════════════════════════════════════════════════════════════════════════════════════════
        # COLUMNAS SOPORTADAS EN HOJA 2 (Cases_Kactus):
        # ────────────────────────────────────────────────────────────────────────────────────────────────
        # OBLIGATORIAS:
        #   - cedula             : Número de identificación del empleado
        #   - fecha_inicio       : Fecha de inicio de la incapacidad (DD/MM/YYYY)
        #
        # OPCIONALES:
        #   - fecha_fin          : Fecha de fin de la incapacidad
        #   - dias / Numero de dias : Días de incapacidad
        #   - numero_incapacidad : Número de la incapacidad (EPS/ARL)
        #   - codigo_cie10       : Código diagnóstico CIE-10 (ej: M54.5)
        #   - diagnostico        : Descripción del diagnóstico
        #   - tipo               : Tipo de incapacidad:
        #                          general | laboral | maternidad | paternidad | trafico | hospitalizacion
        #   - historico          : SI → Dato histórico (no se elimina de la hoja, se marca como histórico)
        #   - Procesado          : Fecha de procesamiento (se llena automáticamente)
        # ═══════════════════════════════════════════════════════════════════════════════════════════════
        try:
            df_cases = pd.read_excel(excel_path, sheet_name=1)  # ✅ Hoja 2 = Cases_Kactus (índice 1)
            if len(df_cases) > 0:
                print(f"📊 PASO 3: Procesando Cases_Kactus ({len(df_cases)} filas)...")
                cases_creados = 0
                cases_actualizados = 0
                cases_historicos = 0
                filas_procesadas = []  # Para marcar como procesadas (no históricos)
                filas_ya_procesadas = 0  # Contador de filas que ya estaban procesadas
                
                from sqlalchemy import and_, func, or_
                from app.database import EstadoCaso, TipoIncapacidad
                
                # Mapeo de tipos de incapacidad desde texto
                TIPO_MAP = {
                    # Enfermedad General
                    "general": TipoIncapacidad.ENFERMEDAD_GENERAL,
                    "enfermedad": TipoIncapacidad.ENFERMEDAD_GENERAL,
                    "enfermedad_general": TipoIncapacidad.ENFERMEDAD_GENERAL,
                    # Enfermedad Laboral / Accidente de Trabajo
                    "laboral": TipoIncapacidad.ENFERMEDAD_LABORAL,
                    "enfermedad_laboral": TipoIncapacidad.ENFERMEDAD_LABORAL,
                    "accidente_trabajo": TipoIncapacidad.ENFERMEDAD_LABORAL,
                    "trabajo": TipoIncapacidad.ENFERMEDAD_LABORAL,
                    "arl": TipoIncapacidad.ENFERMEDAD_LABORAL,
                    # Accidente de Tránsito
                    "trafico": TipoIncapacidad.ACCIDENTE_TRANSITO,
                    "transito": TipoIncapacidad.ACCIDENTE_TRANSITO,
                    "accidente_transito": TipoIncapacidad.ACCIDENTE_TRANSITO,
                    "soat": TipoIncapacidad.ACCIDENTE_TRANSITO,
                    # Maternidad
                    "maternidad": TipoIncapacidad.MATERNIDAD,
                    "licencia_maternidad": TipoIncapacidad.MATERNIDAD,
                    # Paternidad
                    "paternidad": TipoIncapacidad.PATERNIDAD,
                    "licencia_paternidad": TipoIncapacidad.PATERNIDAD,
                    # Certificados
                    "hospitalizacion": TipoIncapacidad.CERTIFICADO,
                    "certificado": TipoIncapacidad.CERTIFICADO,
                    "certificado_hospitalizacion": TipoIncapacidad.CERTIFICADO,
                    # Prelicencia
                    "prelicencia": TipoIncapacidad.PRELICENCIA,
                }
                
                for idx, row in df_cases.iterrows():
                    try:
                        # ═══ VERIFICAR SI YA FUE PROCESADA (tiene fecha en columna "Procesado" o "procesado") ═══
                        # Buscar columna procesado case-insensitive
                        # Crear diccionario con claves en minúsculas para búsqueda case-insensitive
                        row_lower = {str(k).lower(): v for k, v in row.items()}
                        
                        procesado_val = row_lower.get("procesado")
                        if pd.notna(procesado_val) and str(procesado_val).strip():
                            filas_ya_procesadas += 1
                            continue  # Omitir filas ya procesadas
                        
                        cedula_raw = row_lower.get("cedula")
                        if pd.isna(cedula_raw):
                            continue
                        
                        cedula_case = str(int(cedula_raw))
                        
                        # ═══ VERIFICAR SI ES DATO HISTÓRICO ═══
                        es_historico = False
                        historico_val = row_lower.get("historico")
                        if pd.notna(historico_val) and str(historico_val).strip().upper() in ["SI", "SÍ", "YES", "1", "TRUE", "HISTORICO"]:
                            es_historico = True
                        
                        # Leer datos de la fila
                        fecha_inicio_raw = row_lower.get("fecha_inicio")
                        fecha_fin_raw = row_lower.get("fecha_fin")
                        fecha_inicio = pd.to_datetime(fecha_inicio_raw) if pd.notna(fecha_inicio_raw) else None
                        fecha_fin = pd.to_datetime(fecha_fin_raw) if pd.notna(fecha_fin_raw) else None
                        
                        num_incap = str(row_lower.get("numero_incapacidad", "")).strip() if pd.notna(row_lower.get("numero_incapacidad")) else None
                        codigo_cie = str(row_lower.get("codigo_cie10", "")).strip() if pd.notna(row_lower.get("codigo_cie10")) else None
                        
                        # Días de incapacidad (soportar ambos nombres)
                        dias_raw = row_lower.get("numero de dias") or row_lower.get("dias")
                        dias = int(dias_raw) if pd.notna(dias_raw) else None
                        
                        # Diagnóstico textual (opcional - si no hay, se busca por código CIE-10)
                        diagnostico = str(row_lower.get("diagnostico", "")).strip() if pd.notna(row_lower.get("diagnostico")) else None
                        
                        # Tipo de incapacidad
                        tipo_raw = str(row_lower.get("tipo", "")).strip().lower() if pd.notna(row_lower.get("tipo")) else ""
                        tipo_incap = TIPO_MAP.get(tipo_raw, TipoIncapacidad.ENFERMEDAD_GENERAL)
                        
                        if not fecha_inicio:
                            print(f"   ⚠️ Fila {idx+2} sin fecha_inicio, saltando...")
                            continue
                        
                        # ═══ BUSCAR SI YA EXISTE EN BD ═══
                        caso = db.query(Case).filter(
                            Case.cedula == cedula_case,
                            func.date(Case.fecha_inicio) == fecha_inicio.date()
                        ).first()
                        
                        # Si no existe por fecha_inicio, buscar por numero_incapacidad
                        if not caso and num_incap:
                            caso = db.query(Case).filter(
                                Case.cedula == cedula_case,
                                Case.numero_incapacidad == num_incap
                            ).first()
                        
                        if caso:
                            # ═══ ACTUALIZAR CASO EXISTENTE ═══
                            if num_incap:
                                caso.numero_incapacidad = num_incap
                            if codigo_cie:
                                caso.codigo_cie10 = codigo_cie
                            if diagnostico:
                                caso.diagnostico = diagnostico
                            if fecha_fin:
                                caso.fecha_fin_kactus = fecha_fin
                                if not caso.fecha_fin:  # Si no tenía fecha_fin, asignarla
                                    caso.fecha_fin = fecha_fin
                            if dias and not caso.dias_incapacidad:
                                caso.dias_incapacidad = dias
                            caso.fecha_inicio_kactus = fecha_inicio
                            caso.kactus_sync_at = datetime.now()
                            caso.updated_at = datetime.now()
                            db.commit()
                            cases_actualizados += 1
                            print(f"   🔄 Actualizado: CC {cedula_case} | {fecha_inicio.strftime('%d/%m/%Y')}")
                        else:
                            # ═══ CREAR CASO NUEVO ═══
                            # Buscar empleado para obtener company_id y nombre
                            empleado = db.query(Employee).filter(Employee.cedula == cedula_case).first()
                            
                            # Generar serial: CEDULA DD MM YYYY DD MM YYYY
                            fi_str = fecha_inicio.strftime("%d %m %Y")
                            ff_str = fecha_fin.strftime("%d %m %Y") if fecha_fin else fi_str
                            serial = f"{cedula_case} {fi_str} {ff_str}"
                            
                            # Verificar que el serial no exista
                            serial_existente = db.query(Case).filter(Case.serial == serial).first()
                            if serial_existente:
                                print(f"   ⚠️ Serial {serial} ya existe, saltando...")
                                if not es_historico:
                                    filas_procesadas.append(idx + 2)
                                continue
                            
                            # Determinar origen según si es histórico o no
                            origen = "kactus_historico" if es_historico else "kactus_excel"
                            
                            nuevo_caso = Case(
                                serial=serial,
                                cedula=cedula_case,
                                employee_id=empleado.id if empleado else None,
                                company_id=empleado.company_id if empleado else None,
                                tipo=tipo_incap,
                                estado=EstadoCaso.COMPLETA,  # Viene de Kactus = ya validada
                                fecha_inicio=fecha_inicio,
                                fecha_fin=fecha_fin,
                                fecha_inicio_kactus=fecha_inicio,
                                fecha_fin_kactus=fecha_fin,
                                dias_incapacidad=dias,
                                numero_incapacidad=num_incap,
                                codigo_cie10=codigo_cie,
                                diagnostico=diagnostico,
                                kactus_sync_at=datetime.now(),
                                metadata_form={
                                    "origen": origen,
                                    "fila_excel": idx + 2,
                                    "importado_en": datetime.now().isoformat(),
                                    "es_historico": es_historico
                                }
                            )
                            db.add(nuevo_caso)
                            db.commit()
                            
                            # ✅ VERIFICAR SI ES PRÓRROGA EN CONTEXTO DE MATERNIDAD/PRELICENCIA
                            try:
                                from app.services.prorroga_detector import verificar_prorroga_contexto_maternidad
                                resultado_maternidad = verificar_prorroga_contexto_maternidad(db, nuevo_caso)
                                if resultado_maternidad.get("es_prorroga_cadena_previa"):
                                    print(f"   ✅ PRÓRROGA MATERNIDAD: {nuevo_caso.serial}")
                            except Exception as e:
                                pass  # No bloquear sync si falla verificación
                            
                            if es_historico:
                                cases_historicos += 1
                                print(f"   📜 HISTÓRICO: CC {cedula_case} | {serial} | {dias or '?'}d | {tipo_raw or 'general'}")
                            else:
                                cases_creados += 1
                                print(f"   ✅ CREADO: CC {cedula_case} | {serial} | {dias or '?'}d")
                        
                        # Marcar fila para procesar (NO marcar históricos - permanecen en el Excel como referencia)
                        if not es_historico:
                            filas_procesadas.append(idx + 2)  # +2 porque Excel es 1-indexed + header
                        
                    except Exception as e:
                        print(f"   ❌ Error fila {idx+2}: {e}")
                        db.rollback()
                
                print(f"\n   📊 Resumen Cases_Kactus:")
                print(f"      • Casos CREADOS (nuevos): {cases_creados}")
                print(f"      • Casos HISTÓRICOS importados: {cases_historicos}")
                print(f"      • Casos actualizados: {cases_actualizados}")
                print(f"      • Filas nuevas procesadas: {len(filas_procesadas)}")
                print(f"      • Filas ya procesadas (omitidas): {filas_ya_procesadas}")
                
                # ═══ MARCAR FILAS COMO PROCESADAS (con fecha) ═══
                if filas_procesadas:
                    try:
                        _marcar_filas_procesadas_kactus(filas_procesadas)
                    except Exception as e:
                        print(f"   ⚠️ Error marcando filas procesadas: {e}")
                
                # ═══ LIMPIAR FILAS ANTIGUAS (> 15 días) ═══
                try:
                    _limpiar_filas_antiguas_kactus()
                except Exception as e:
                    print(f"   ⚠️ Error limpiando filas antiguas: {e}")
                
            else:
                print(f"   ℹ️ Hoja Cases_Kactus vacía o sin datos")
        except Exception as e:
            if "Worksheet index" in str(e) or "No sheet" in str(e):
                print(f"   ℹ️ Hoja 2 (Cases_Kactus) no existe aún, omitiendo...")
            else:
                print(f"   ⚠️ Error leyendo Cases_Kactus: {e}")
        
        # ========== PASO 4: CORREOS NOTIFICACIÓN → GESTIONADOS DESDE ADMIN PORTAL ==========
        # Los correos de notificación ya NO se sincronizan desde el Excel.
        # Se gestionan exclusivamente desde el portal admin (admin-incapacidades).
        # Tabla: correos_notificacion → CRUD en /admin/correos
        print(f"\n📧 PASO 4: Correos de notificación → Se gestionan desde Admin Portal (omitido)")
        total_correos = db.query(CorreoNotificacion).filter(CorreoNotificacion.activo == True).count()
        print(f"   ✅ {total_correos} correos activos en base de datos (gestionados desde admin portal)")
        
        
    except Exception as e:
        print(f"\n❌ ERROR GENERAL EN SYNC: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════
# DETECCIÓN AUTOMÁTICA DE TRASLAPOS ENTRE INCAPACIDADES
# ══════════════════════════════════════════════════════════════════

def _detectar_traslapos_globales(db):
    """
    Detecta traslapos (solapamiento de fechas) entre incapacidades del mismo empleado.
    Ejemplo: Incap A del 31/01 al 02/02 e Incap B del 02/02 al 04/02 → 1 día traslapado.
    En Kactus se subiría como 03/02 al 04/02 (2 días en vez de 3).
    """
    from sqlalchemy import func, and_
    
    try:
        # Obtener todas las cédulas con más de 1 caso activo
        cedulas = db.query(Case.cedula).filter(
            Case.fecha_inicio != None,
            Case.fecha_fin != None
        ).group_by(Case.cedula).having(func.count(Case.id) > 1).all()
        
        traslapos_detectados = 0
        
        for (cedula,) in cedulas:
            casos = db.query(Case).filter(
                Case.cedula == cedula,
                Case.fecha_inicio != None,
                Case.fecha_fin != None
            ).order_by(Case.fecha_inicio.asc()).all()
            
            for i in range(len(casos) - 1):
                caso_actual = casos[i]
                caso_siguiente = casos[i + 1]
                
                if not caso_actual.fecha_fin or not caso_siguiente.fecha_inicio:
                    continue
                
                # ¿Se traslapa? fecha_fin del actual >= fecha_inicio del siguiente
                if caso_actual.fecha_fin.date() >= caso_siguiente.fecha_inicio.date():
                    dias_overlap = (caso_actual.fecha_fin.date() - caso_siguiente.fecha_inicio.date()).days + 1
                    
                    # Solo marcar si no tiene ya Kactus override (que es la fecha real ajustada)
                    if not caso_siguiente.fecha_inicio_kactus and caso_siguiente.dias_traslapo == 0:
                        caso_siguiente.dias_traslapo = dias_overlap
                        caso_siguiente.traslapo_con_serial = caso_actual.serial
                        
                        # Calcular fecha Kactus sugerida (inicio original + días traslapo)
                        from datetime import timedelta
                        nueva_fecha_inicio = caso_siguiente.fecha_inicio + timedelta(days=dias_overlap)
                        caso_siguiente.fecha_inicio_kactus = nueva_fecha_inicio
                        
                        # Recalcular días Kactus si no los tiene
                        caso_siguiente.updated_at = datetime.now()
                        db.commit()
                        traslapos_detectados += 1
        
        if traslapos_detectados > 0:
            print(f"   🔀 {traslapos_detectados} traslapos detectados automáticamente")
    
    except Exception as e:
        print(f"   ⚠️ Error detectando traslapos: {e}")
        db.rollback()


# ══════════════════════════════════════════════════════════════════
# LIMPIEZA QUINCENAL DE HOJA KACTUS (respaldo)
# ══════════════════════════════════════════════════════════════════

def vaciar_hoja_kactus_quincenal():
    """
    Cada quincena (1 y 16 del mes), ejecuta una limpieza forzada de la Hoja Kactus.
    
    NOTA: Con el nuevo sistema, las filas se marcan como "Procesado" con fecha
    y se eliminan automáticamente cuando tienen más de 15 días.
    Esta función es un respaldo que fuerza la limpieza si algo quedó pendiente.
    """
    try:
        from datetime import datetime
        hoy = datetime.now()
        dia = hoy.day
        
        # Solo ejecutar el 1 y el 16 de cada mes
        if dia not in (1, 16):
            return
        
        print(f"\n🗑️ LIMPIEZA QUINCENAL — Hoja 2 (Cases_Kactus) — {hoy.strftime('%d/%m/%Y')}")
        print(f"   Eliminando filas procesadas hace más de {DIAS_ANTIGUEDAD_LIMPIEZA} días...")
        
        filas_eliminadas = _limpiar_filas_antiguas_kactus()
        
        if filas_eliminadas > 0:
            print(f"   ✅ Limpieza quincenal completada — {filas_eliminadas} filas antiguas eliminadas\n")
        else:
            print(f"   ℹ️ No había filas antiguas que limpiar\n")
        
    except Exception as e:
        print(f"   ❌ Error en limpieza quincenal: {e}")


# ══════════════════════════════════════════════════════════════════
# ESTADO DE SINCRONIZACIÓN
# ══════════════════════════════════════════════════════════════════

def obtener_estado_sync():
    """Retorna el estado actual de la sincronización BD ↔ Excel"""
    db = SessionLocal()
    try:
        from sqlalchemy import func
        
        total_empleados = db.query(Employee).filter(Employee.activo == True).count()
        total_casos = db.query(Case).count()
        casos_con_kactus = db.query(Case).filter(Case.kactus_sync_at != None).count()
        casos_sin_kactus = total_casos - casos_con_kactus
        casos_con_diagnostico = db.query(Case).filter(
            Case.diagnostico != None,
            Case.diagnostico != ''
        ).count()
        casos_con_cie10 = db.query(Case).filter(
            Case.codigo_cie10 != None,
            Case.codigo_cie10 != ''
        ).count()
        casos_con_traslapo = db.query(Case).filter(
            Case.dias_traslapo > 0
        ).count()
        
        ultima_sync_kactus = db.query(func.max(Case.kactus_sync_at)).scalar()
        ultimo_caso_creado = db.query(func.max(Case.created_at)).scalar()
        
        # Traslapos por empleado
        traslapos_detalle = []
        if casos_con_traslapo > 0:
            traslapos = db.query(Case).filter(Case.dias_traslapo > 0).order_by(Case.updated_at.desc()).limit(20).all()
            for t in traslapos:
                emp = db.query(Employee).filter(Employee.cedula == t.cedula).first()
                traslapos_detalle.append({
                    "serial": t.serial,
                    "cedula": t.cedula,
                    "nombre": emp.nombre if emp else "?",
                    "fecha_inicio": str(t.fecha_inicio.date()) if t.fecha_inicio else None,
                    "fecha_fin": str(t.fecha_fin.date()) if t.fecha_fin else None,
                    "fecha_inicio_kactus": str(t.fecha_inicio_kactus.date()) if t.fecha_inicio_kactus else None,
                    "fecha_fin_kactus": str(t.fecha_fin_kactus.date()) if t.fecha_fin_kactus else None,
                    "dias_traslapo": t.dias_traslapo,
                    "traslapo_con": t.traslapo_con_serial,
                })
        
        return {
            "ok": True,
            "timestamp": datetime.now().isoformat(),
            "resumen": {
                "total_empleados_activos": total_empleados,
                "total_casos": total_casos,
                "casos_con_kactus": casos_con_kactus,
                "casos_sin_kactus": casos_sin_kactus,
                "casos_con_diagnostico": casos_con_diagnostico,
                "casos_con_cie10": casos_con_cie10,
                "casos_con_traslapo": casos_con_traslapo,
                "pct_kactus": round((casos_con_kactus / total_casos * 100) if total_casos > 0 else 0, 1),
                "pct_diagnostico": round((casos_con_diagnostico / total_casos * 100) if total_casos > 0 else 0, 1),
            },
            "ultima_sync_kactus": str(ultima_sync_kactus) if ultima_sync_kactus else None,
            "ultimo_caso_creado": str(ultimo_caso_creado) if ultimo_caso_creado else None,
            "traslapos_recientes": traslapos_detalle,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()