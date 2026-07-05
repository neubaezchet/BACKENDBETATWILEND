"""
Tenant Provisioning Service
============================
Provisionamiento automático de recursos al registrar una nueva empresa:
  - Empresa única    → 1 Sheet propio (Empleados + Kactus)
  - Holding / Multi  → 1 Sheet con pestañas separadas por sub-empresa
                        Empleados_SubA | Kactus_SubA | Empleados_SubB | Kactus_SubB ...

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


# ─── Duplicar Sheet maestro ───────────────────────────────────────────────────

def duplicar_sheet_maestro(company_nombre: str, company_id: int) -> dict:
    """
    Duplica el Google Sheet maestro y lo renombra para la empresa.

    Returns dict con:
      - ok: bool
      - spreadsheet_id: ID del nuevo Sheet
      - spreadsheet_url: URL del nuevo Sheet
      - error: mensaje si falló
    """
    master_id = os.environ.get("GOOGLE_DRIVE_FILE_ID")
    if not master_id:
        logger.warning("GOOGLE_DRIVE_FILE_ID no configurado — omitiendo creación de Sheet")
        return {"ok": False, "error": "GOOGLE_DRIVE_FILE_ID no configurado",
                "spreadsheet_id": None, "spreadsheet_url": None}

    try:
        drive = _get_drive_service()
        nombre_sheet = f"{company_nombre} — Base de Datos"

        # Carpeta destino dentro de la Unidad Compartida (ej. INCAPACIDADES/Sheets Empresas).
        # Sin esto, la copia queda en el My Drive de la service account (cuota limitada).
        tenants_folder_id = os.environ.get("GOOGLE_TENANTS_FOLDER_ID")
        body = {"name": nombre_sheet}
        if tenants_folder_id:
            body["parents"] = [tenants_folder_id]
        else:
            logger.warning(
                "⚠️ GOOGLE_TENANTS_FOLDER_ID no configurado — el Sheet quedará "
                "en el My Drive de la service account (no recomendado en producción)"
            )

        resultado = drive.files().copy(
            fileId=master_id,
            body=body,
            supportsAllDrives=True,
            fields="id,name,webViewLink"
        ).execute()

        nuevo_id = resultado.get("id")
        nuevo_url = resultado.get("webViewLink",
                                  f"https://docs.google.com/spreadsheets/d/{nuevo_id}")

        logger.info(f"✅ Sheet creado para '{company_nombre}' (company_id={company_id}): {nuevo_id}")
        return {"ok": True, "spreadsheet_id": nuevo_id,
                "spreadsheet_url": nuevo_url, "error": None}

    except Exception as e:
        logger.error(f"❌ Error duplicando Sheet para '{company_nombre}': {e}")
        return {"ok": False, "spreadsheet_id": None,
                "spreadsheet_url": None, "error": str(e)[:300]}


# ─── Vaciar filas de datos de la copia ────────────────────────────────────────

def vaciar_filas_datos(spreadsheet_id: str) -> bool:
    """
    Borra todas las filas de datos (fila 2 en adelante) de TODAS las pestañas,
    conservando los encabezados. El Sheet maestro es un sheet vivo con datos
    reales, así que la copia nace con empleados de otras empresas si no se limpia.
    """
    try:
        svc = _get_sheets_service()
        meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        titulos = [h["properties"]["title"] for h in meta.get("sheets", [])]

        if not titulos:
            return True

        rangos = [f"'{t}'!A2:ZZ" for t in titulos]
        svc.spreadsheets().values().batchClear(
            spreadsheetId=spreadsheet_id,
            body={"ranges": rangos},
        ).execute()

        logger.info(f"✅ Filas de datos vaciadas en Sheet {spreadsheet_id} ({len(titulos)} pestañas)")
        return True
    except Exception as e:
        logger.error(f"❌ Error vaciando filas de datos en {spreadsheet_id}: {e}")
        return False


# ─── Pestañas adicionales para Holdings ──────────────────────────────────────

def _nombre_corto(nombre: str, max_len: int = 25) -> str:
    """Limpia y acorta el nombre de una sub-empresa para usarlo en título de pestaña."""
    return nombre.strip()[:max_len].replace("/", "-").replace("\\", "-")


def configurar_pestanas_holding(spreadsheet_id: str, sub_empresas: list) -> bool:
    """
    Para un Holding: renombra las 2 pestañas originales para la 1ra sub-empresa
    y agrega un par (Empleados + Kactus) por cada sub-empresa adicional.

    Estructura final del Sheet:
      Empleados_<SubA>  |  Kactus_<SubA>
      Empleados_<SubB>  |  Kactus_<SubB>
      ...

    Args:
        spreadsheet_id: ID del Sheet ya creado (copia del maestro)
        sub_empresas:   Lista de nombres de sub-empresas ej. ["SubA", "SubB", "SubC"]

    Returns:
        bool — True si exitoso
    """
    if not sub_empresas:
        return True  # Nada que hacer

    try:
        svc = _get_sheets_service()

        # Obtener pestañas actuales (el Sheet maestro tiene 2: Empleados + Kactus)
        meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        hojas_actuales = meta.get("sheets", [])

        if len(hojas_actuales) < 2:
            logger.warning(
                f"⚠️ Sheet {spreadsheet_id} tiene menos de 2 pestañas, "
                f"se esperaban Empleados + Kactus"
            )
            return False

        # IDs de las 2 pestañas originales
        sheet_empleados_id = hojas_actuales[0]["properties"]["sheetId"]
        sheet_kactus_id    = hojas_actuales[1]["properties"]["sheetId"]

        primera = _nombre_corto(sub_empresas[0])
        requests_batch = []

        # 1. Renombrar las 2 pestañas originales con el nombre de la 1ra sub-empresa
        requests_batch += [
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_empleados_id,
                        "title": f"Empleados_{primera}",
                    },
                    "fields": "title",
                }
            },
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_kactus_id,
                        "title": f"Kactus_{primera}",
                    },
                    "fields": "title",
                }
            },
        ]

        # 2. Por cada sub-empresa adicional, duplicar la pestaña Empleados y la Kactus
        for i, sub in enumerate(sub_empresas[1:], start=1):
            corto = _nombre_corto(sub)

            # Duplicar pestaña Empleados
            requests_batch.append({
                "duplicateSheet": {
                    "sourceSheetId": sheet_empleados_id,
                    "insertSheetIndex": i * 2,
                    "newSheetName": f"Empleados_{corto}",
                }
            })
            # Duplicar pestaña Kactus
            requests_batch.append({
                "duplicateSheet": {
                    "sourceSheetId": sheet_kactus_id,
                    "insertSheetIndex": i * 2 + 1,
                    "newSheetName": f"Kactus_{corto}",
                }
            })

        # Ejecutar todo en un solo batch
        svc.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests_batch}
        ).execute()

        logger.info(
            f"✅ Holding configurado: {len(sub_empresas)} sub-empresas → "
            f"{len(sub_empresas) * 2} pestañas en Sheet {spreadsheet_id}"
        )
        return True

    except Exception as e:
        logger.error(f"❌ Error configurando pestañas holding en {spreadsheet_id}: {e}")
        return False


# ─── Compartir Sheet con el admin ─────────────────────────────────────────────

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
            emailMessage=(
                "Tu base de datos de incapacidades ha sido creada y configurada. "
                "Puedes consultarla en este enlace."
            ),
            supportsAllDrives=True,
            fields="id"
        ).execute()
        logger.info(f"✅ Sheet {spreadsheet_id} compartido con {email} (rol: {rol})")
        return True
    except Exception as e:
        logger.warning(f"⚠️ No se pudo compartir Sheet {spreadsheet_id} con {email}: {e}")
        return False


# ─── Función principal ────────────────────────────────────────────────────────

def provisionar_tenant_completo(
    company_nombre: str,
    company_id: int,
    contacto_email: str,
    tipo_estructura: str = "unica",
    sub_empresas: list = None,
) -> dict:
    """
    Provisiona todos los recursos para un nuevo tenant.

    - Empresa única   → 1 Sheet (2 pestañas: Empleados + Kactus)
    - Holding/Multi   → 1 Sheet (2 pestañas por cada sub-empresa:
                        Empleados_<Sub> + Kactus_<Sub>)

    Args:
        company_nombre:   Nombre oficial de la empresa / holding
        company_id:       ID en la BD
        contacto_email:   Correo del administrador
        tipo_estructura:  'unica' | 'holding'
        sub_empresas:     Lista de nombres de sub-empresas (solo para holding)

    Returns:
        dict con google_sheets_id, google_sheets_url, errores, sub_empresas_configuradas
    """
    sub_empresas = sub_empresas or []

    resultado = {
        "google_sheets_id": None,
        "google_sheets_url": None,
        "errores": [],
        "tipo_estructura": tipo_estructura,
        "sub_empresas_configuradas": 0,
    }

    # PASO 1: Duplicar Sheet maestro (igual para unica y holding)
    sheet_result = duplicar_sheet_maestro(company_nombre, company_id)

    if not sheet_result["ok"]:
        resultado["errores"].append(f"Sheet: {sheet_result['error']}")
        logger.warning(f"⚠️ No se pudo crear Sheet para empresa {company_id}")
        return resultado

    nuevo_id  = sheet_result["spreadsheet_id"]
    nuevo_url = sheet_result["spreadsheet_url"]
    resultado["google_sheets_id"]  = nuevo_id
    resultado["google_sheets_url"] = nuevo_url

    # PASO 1b: Vaciar los datos heredados del maestro (el cliente empieza con Sheet limpio).
    # Se hace ANTES de configurar pestañas holding para que las duplicadas nazcan limpias.
    if not vaciar_filas_datos(nuevo_id):
        resultado["errores"].append(
            "El Sheet se creó pero no se pudieron vaciar los datos de la plantilla — revisar manualmente"
        )

    # PASO 2: Si es Holding → configurar pestañas por sub-empresa
    if tipo_estructura == "holding" and sub_empresas:
        logger.info(
            f"🏗️  Configurando Holding '{company_nombre}' con "
            f"{len(sub_empresas)} sub-empresas: {sub_empresas}"
        )
        ok_tabs = configurar_pestanas_holding(nuevo_id, sub_empresas)
        if ok_tabs:
            resultado["sub_empresas_configuradas"] = len(sub_empresas)
        else:
            resultado["errores"].append(
                "No se pudieron crear las pestañas por sub-empresa "
                "(el Sheet existe pero con estructura estándar)"
            )
    else:
        logger.info(f"🏢 Empresa única '{company_nombre}' — estructura estándar (2 pestañas)")

    # PASO 3: Compartir con el admin de la empresa (solo lectura)
    if contacto_email:
        compartir_sheet_con_email(nuevo_id, contacto_email, rol="reader")

    return resultado
