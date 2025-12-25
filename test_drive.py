from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Detecta el archivo como tu backend
if Path("/etc/secrets/incapacidades-sa.json").exists():
    SERVICE_ACCOUNT_FILE = Path("/etc/secrets/incapacidades-sa.json")
else:
    SERVICE_ACCOUNT_FILE = Path("incapacidades-sa.json")

SCOPES = ["https://www.googleapis.com/auth/drive"]

def test_drive_connection():
    try:
        creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        service = build("drive", "v3", credentials=creds)
        results = service.files().list(pageSize=5, fields="files(name, id)").execute()
        items = results.get("files", [])
        print("✅ Conexión exitosa a Google Drive")
        print("Archivos encontrados:")
        for item in items:
            print(f"- {item['name']} ({item['id']})")
    except Exception as e:
        print("❌ Error al conectar con Google Drive:")
        print(e)

if __name__ == "__main__":
    test_drive_connection()