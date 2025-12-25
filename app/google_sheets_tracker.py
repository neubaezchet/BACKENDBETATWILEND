"""
Google Sheets Tracker - Sincronización automática
"""

import os
import json
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def get_sheets_service():
    """Obtiene el servicio de Google Sheets"""
    try:
        creds_json = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
        if not creds_json:
            print("❌ GOOGLE_SHEETS_CREDENTIALS no configurado")
            return None
        
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        service = build('sheets', 'v4', credentials=creds)
        return service
    except Exception as e:
        print(f"❌ Error creando servicio Sheets: {e}")
        return None

def actualizar_caso_en_sheet(caso, accion="actualizar"):
    """
    Sincroniza un caso con Google Sheets
    
    Args:
        caso: Objeto Case de la BD
        accion: "actualizar" o "crear"
    """
    try:
        service = get_sheets_service()
        if not service:
            return False
        
        spreadsheet_id = os.environ.get("GOOGLE_SHEETS_ID")
        if not spreadsheet_id:
            print("❌ GOOGLE_SHEETS_ID no configurado")
            return False
        
        # Datos del caso
        empleado_nombre = caso.empleado.nombre if caso.empleado else "Desconocido"
        empresa_nombre = caso.empresa.nombre if caso.empresa else "Otra"
        dias_pendiente = (datetime.now() - caso.created_at).days
        
        # Obtener última nota como observación
        ultima_nota = ""
        if caso.notas:
            ultima_nota = caso.notas[0].contenido if caso.notas else ""
        
        # Fila de datos
        valores = [[
            caso.serial,
            empleado_nombre,
            caso.cedula,
            empresa_nombre,
            caso.tipo.value if caso.tipo else "N/A",
            caso.estado.value,
            caso.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            dias_pendiente,
            caso.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
            ultima_nota[:100]  # Primeros 100 caracteres
        ]]
        
        # Buscar si ya existe el caso
        range_name = "Casos_Activos!A:A"
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        
        serials = result.get('values', [])
        fila_existente = None
        
        for idx, row in enumerate(serials):
            if row and row[0] == caso.serial:
                fila_existente = idx + 1
                break
        
        if fila_existente:
            # Actualizar fila existente
            range_update = f"Casos_Activos!A{fila_existente}:J{fila_existente}"
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=range_update,
                valueInputOption="RAW",
                body={"values": valores}
            ).execute()
            print(f"✅ Caso {caso.serial} actualizado en Sheet (fila {fila_existente})")
        else:
            # Agregar nueva fila
            range_append = "Casos_Activos!A:J"
            service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range=range_append,
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": valores}
            ).execute()
            print(f"✅ Caso {caso.serial} agregado al Sheet")
        
        return True
        
    except Exception as e:
        print(f"❌ Error sincronizando con Sheets: {e}")
        return False

def registrar_cambio_estado_sheet(caso, estado_anterior, estado_nuevo, validador="Sistema", observaciones=""):
    """Registra un cambio de estado en la hoja de historial"""
    try:
        service = get_sheets_service()
        if not service:
            return False
        
        spreadsheet_id = os.environ.get("GOOGLE_SHEETS_ID")
        
        valores = [[
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            caso.serial,
            estado_anterior,
            estado_nuevo,
            validador,
            observaciones[:200],  # Primeros 200 caracteres
            "cambio_estado"
        ]]
        
        range_append = "Historial_Cambios!A:G"
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_append,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": valores}
        ).execute()
        
        print(f"✅ Cambio de estado registrado en Sheet: {caso.serial}")
        return True
        
    except Exception as e:
        print(f"❌ Error registrando cambio en Sheets: {e}")
        return False