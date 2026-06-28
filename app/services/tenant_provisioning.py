"""
Tenant Provisioning Service
============================
Provisionamiento automático de recursos al registrar una nueva empresa:
  1. Duplicar el Google Sheet maestro → Sheet propio del tenant
  (Drive doble se agrega en una fase futura)

Requiere:
  - GOOGLE_DRIVE_FILE_ID: ID del spreadsheet maestro (plantilla)
  - GOOGLE_SERVICE_ACCOUNT_KEY / GOOGLE_CREDENTIALS_JSON: credenciales
"""

import os
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ─── Helpers de autenticación ────────────────────────────────────────────────

def _get_credentials():
    """Obtiene credenciales de service account desde variables de entorno."""
    creds_json = (
        os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
        or os.environ.get("GOOGLE_CREDENTIALS_JSON")
        or os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
    )
    if not creds_json:
        raise ValueError("No hay credenciales de Google configuradas (GOOGLE_SERVICE_ACCOUNT_KEY)")
    return json.loads(creds_json)


def _get_drive_service():
    """Construye el servicio de Google Drive API v3."""
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    SCOPES = [
        'https://www.googleapis.com/auth/drive',
        'https://www.googleapis.com/auth/spreadsheets',
    ]
    creds_dict = _get_credentials()
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)


def _get_sheets_service():
    """Construye el servicio de Google Sheets API v4."""
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    creds_dict = _get_credentials()
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return build('sheets', 'v4', credentials=creds)


# ─── Función principal: duplicar Sheet maestro ───────────────────────────────

def duplicar_sheet_maestro(company_nombre: str, company_id: int) -> dict:
    """
    Duplica el Google Sheet maestro y lo renombra para la empresa.

    Args:
        company_nombre: Nombre de la empresa (ej: "Empresa ABC S.A.S.")
        company_id: ID interno de la empresa

    Returns:
        dict con:
          - ok: bool
          - spreadsheet_id: ID del nuevo Sheet
          - spreadsheet_url: URL para compartir
          - error: mensaje si falló
    """
    master_id = os.environ.get("GOOGLE_DRIVE_FILE_ID")
    if not master_id:
        logger.warning("GOOGLE_DRIVE_FILE_ID no configurado — omitiendo creación de Sheet")
        return {"ok": False, "error": "GOOGLE_DRIVE_FILE_ID no configurado", "spreadsheet_id": None, "spreadsheet_url": None}

    try:
        drive = _get_drive_service()

        # Nombre del nuevo Sheet
        nombre_sheet = f"{company_nombre} — Base de Datos"

        # Copiar el archivo maestro
        copy_metadata = {
            "name": nombre_sheet,
        }
        resultado = drive.files().copy(
            fileId=master_id,
            body=copy_metadata,
            fields="id,name,webViewLink"
        ).execute()

        nuevo_id = resultado.get("id")
        nuevo_url = resultado.get("webViewLink", f"https://docs.google.com/spreadsheets/d/{nuevo_id}")

        logger.info(f"✅ Sheet creado para empresa '{company_nombre}' (ID {company_id}): {nuevo_id}")

        return {
            "ok": True,
            "spreadsheet_id": nuevo_id,
            "spreadsheet_url": nuevo_url,
            "error": None,
        }

    except Exception as e:
        logger.error(f"❌ Error duplicando Sheet para empresa '{company_nombre}': {e}")
        return {
            "ok": False,
            "spreadsheet_id": None,
            "spreadsheet_url": None,
            "error": str(e)[:300],
        }


def renombrar_pestanas_sheet(spreadsheet_id: str, company_nombre: str) -> bool:
    """
    Renombra las pestañas del nuevo Sheet para incluir el nombre de la empresa.
    Por ejemplo: "Base_Empleados" → "Base_Empleados — Empresa ABC"
    Esto es opcional y no bloquea el flujo si falla.
    """
    try:
        sheets = _get_sheets_service()

        # Obtener pestañas actuales
        meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        hojas = meta.get("sheets", [])

        requests = []
        for hoja in hojas:
            props = hoja.get("properties", {})
            sheet_id = props.get("sheetId")
            titulo_actual = props.get("title", "")

            # Solo renombrar si no tiene ya el nombre de la empresa
            if company_nombre[:20] not in titulo_actual:
                nuevo_titulo = f"{titulo_actual}"  # Dejamos igual por ahora, solo registramos
                # Si quieres agregar el nombre: nuevo_titulo = f"{titulo_actual} [{company_nombre[:15]}]"

        if requests:
            sheets.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": requests}
            ).execute()

        return True
    except Exception as e:
        logger.warning(f"⚠️ No se pudieron renombrar pestañas del Sheet {spreadsheet_id}: {e}")
        return False


def compartir_sheet_con_email(spreadsheet_id: str, email: str, rol: str = "reader") -> bool:
    """
    Comparte el Sheet con el email del administrador de la empresa.
    rol: 'reader' (solo lectura) | 'writer' (puede editar)
    """
    try:
        drive = _get_drive_service()
        permission = {
            "type": "user",
            "role": rol,
            "emailAddress": email,
        }
        drive.permissions().create(
            fileId=spreadsheet_id,
            body=permission,
            sendNotificationEmail=True,
            emailMessage=f"Tu base de datos de incapacidades ha sido creada y configurada. Puedes consultarla en este enlace.",
            fields="id"
        ).execute()
        logger.info(f"✅ Sheet {spreadsheet_id} compartido con {email} (rol: {rol})")
        return True
    except Exception as e:
        logger.warning(f"⚠️ No se pudo compartir Sheet {spreadsheet_id} con {email}: {e}")
        return False


def provisionar_tenant_completo(company_nombre: str, company_id: int, contacto_email: str) -> dict:
    """
    Función principal: provisiona todos los recursos para un nuevo tenant.
    Actualmente: crea y comparte el Google Sheet.

    Args:
        company_nombre: Nombre oficial de la empresa
        company_id: ID en la BD
        contacto_email: Correo del administrador de la empresa

    Returns:
        dict con todos los IDs y URLs generados
    """
    resultado = {
        "google_sheets_id": None,
        "google_sheets_url": None,
        "errores": [],
    }

    # 1. Duplicar Sheet maestro
    sheet_result = duplicar_sheet_maestro(company_nombre, company_id)
    if sheet_result["ok"]:
        resultado["google_sheets_id"] = sheet_result["spreadsheet_id"]
        resultado["google_sheets_url"] = sheet_result["spreadsheet_url"]

        # 2. Compartir con el admin de la empresa (solo lectura)
        if contacto_email:
            compartir_sheet_con_email(
                sheet_result["spreadsheet_id"],
                contacto_email,
                rol="reader"
            )
    else:
        resultado["errores"].append(f"Sheet: {sheet_result['error']}")
        logger.warning(f"⚠️ No se pudo crear Sheet para empresa {company_id} — continuando sin él")

    return resultado
