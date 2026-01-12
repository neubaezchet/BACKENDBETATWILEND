"""
Script para regenerar REFRESH_TOKEN usando archivo credentials.json
"""

from google_auth_oauthlib.flow import Flow
import webbrowser
import json
import os

SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/spreadsheets.readonly'
]

def main():
    print("=" * 80)
    print("🔧 REGENERANDO REFRESH TOKEN DE GOOGLE DRIVE")
    print("=" * 80)
    print()
    
    # Buscar archivo credentials.json (sin filtro de 'client_secret')
    json_files = [f for f in os.listdir('.') if f.endswith('.json') and f != 'package.json']
    
    if not json_files:
        print("❌ No se encontró archivo de credenciales JSON")
        print()
        print("📝 Pasos:")
        print("1. Ve a: https://console.cloud.google.com/apis/credentials")
        print("2. Descarga el archivo JSON de tu OAuth Client")
        print("3. Renómbralo a 'credentials.json'")
        print("4. Ponlo en la misma carpeta que este script")
        print("5. Ejecuta el script de nuevo")
        return
    
    # Priorizar credentials.json si existe
    if 'credentials.json' in json_files:
        credentials_file = 'credentials.json'
    else:
        credentials_file = json_files[0]
    
    print(f"✅ Usando credenciales: {credentials_file}")
    print()
    
    try:
        # Leer archivo JSON
        with open(credentials_file, 'r', encoding='utf-8') as f:
            client_config = json.load(f)
        
        # Verificar que tenga la estructura correcta
        if 'web' not in client_config and 'installed' not in client_config:
            print("❌ El archivo JSON no tiene el formato correcto")
            print("   Debe contener 'web' o 'installed' como clave principal")
            return
        
        # Crear flujo OAuth con localhost
        flow = Flow.from_client_config(
            client_config,
            scopes=SCOPES,
            redirect_uri='http://localhost:8080'
        )
        
        # Generar URL de autorización
        auth_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        
        print("📋 INSTRUCCIONES:")
        print("-" * 80)
        print()
        print("1️⃣  Se abrirá tu navegador (o copia la URL abajo)")
        print("2️⃣  Inicia sesión con Google")
        print("3️⃣  Acepta todos los permisos")
        print("4️⃣  Serás redirigido a localhost (mostrará error de conexión)")
        print("5️⃣  COPIA toda la URL de la barra del navegador")
        print()
        
        # Abrir navegador
        try:
            webbrowser.open(auth_url)
            print("✅ Navegador abierto automáticamente")
        except:
            print("⚠️  Abre esta URL manualmente:")
            print(auth_url)
        
        print()
        print("-" * 80)
        
        # Solicitar URL de callback
        callback_url = input("\n🔗 Pega la URL completa de localhost: ").strip()
        
        if not callback_url or 'code=' not in callback_url:
            print("\n❌ URL inválida. Debe contener 'code='")
            return
        
        print("\n⏳ Validando código...")
        
        # Extraer código
        code = callback_url.split('code=')[1].split('&')[0]
        
        # Obtener tokens
        flow.fetch_token(code=code)
        credentials = flow.credentials
        
        print()
        print("=" * 80)
        print("✅ ¡TOKEN GENERADO EXITOSAMENTE!")
        print("=" * 80)
        print()
        print("🔑 REFRESH TOKEN:")
        print("-" * 80)
        print()
        print(credentials.refresh_token)
        print()
        print("-" * 80)
        
        # Guardar en archivo
        with open("REFRESH_TOKEN_RAILWAY.txt", "w") as f:
            f.write(credentials.refresh_token)
        
        print()
        print("💾 Token guardado en: REFRESH_TOKEN_RAILWAY.txt")
        print()
        print("📌 SIGUIENTE PASO:")
        print("1. Copia el token de arriba")
        print("2. Ve a Railway → tu servicio → Variables")
        print("3. Actualiza: GOOGLE_DRIVE_REFRESH_TOKEN")
        print()
        print("=" * 80)
        
    except FileNotFoundError:
        print(f"\n❌ No se encontró: {credentials_file}")
    except json.JSONDecodeError:
        print(f"\n❌ Archivo JSON inválido: {credentials_file}")
    except Exception as e:
        print()
        print("=" * 80)
        print("❌ ERROR:")
        print("=" * 80)
        print(str(e))
        print()
        print("💡 TIP: Asegúrate de que http://localhost:8080 esté en las")
        print("   URIs de redirección autorizadas en Google Cloud Console")
        print()

if __name__ == "__main__":
    main()