# 1. OPCIONAL: Crear un entorno virtual
python -m venv env
.\env\Scripts\Activate

# 2. Instalar las librerías necesarias
pip install --upgrade pip
pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib

# 3. Script Python para lanzar el flujo de autorización
$pythonScript = @"
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
import os

SCOPES = ['https://www.googleapis.com/auth/drive.file']

def get_user_service():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return build('drive', 'v3', credentials=creds)

if __name__ == '__main__':
    get_user_service()
    print('¡Autorización exitosa! Se generó el archivo token.pickle')
"@

# 4. Guardar y ejecutar el script python
Set-Content -Path "autoriza_drive.py" -Value $pythonScript -Encoding UTF8
python autoriza_drive.py