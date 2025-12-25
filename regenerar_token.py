"""
Script para regenerar el REFRESH_TOKEN de Google Drive
USA URIs AUTORIZADAS de producción
"""

from google_auth_oauthlib.flow import Flow
import webbrowser

# Credenciales desde credentials.json
CLIENT_ID = "680515257259-9bvnl3cu8cgpit0oak7ljrjvdh8q2rmb.apps.googleusercontent.com"
CLIENT_SECRET = "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"

SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/spreadsheets.readonly'
]

def main():
    print("=" * 80)
    print("🔧 REGENERANDO REFRESH TOKEN DE GOOGLE DRIVE")
    print("=" * 80)
    print()
    
    # Configuración con URI de producción autorizada
    client_config = {
        "web": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uris": ["https://bakcend-gemi-cha-2.onrender.com/auth/callback"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    
    try:
        # Crear flujo OAuth con redirect_uri de producción
        flow = Flow.from_client_config(
            client_config,
            scopes=SCOPES,
            redirect_uri='https://bakcend-gemi-cha-2.onrender.com/auth/callback'
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
        print("1️⃣  COPIA esta URL completa y ábrela en tu navegador:")
        print()
        print(auth_url)
        print()
        print("-" * 80)
        print()
        print("2️⃣  Inicia sesión con: davidbaezaospino@gmail.com")
        print("3️⃣  Acepta TODOS los permisos")
        print("4️⃣  Serás redirigido a una página que puede mostrar error")
        print("     (esto es normal)")
        print("5️⃣  COPIA la URL COMPLETA de esa página")
        print("     Ejemplo: https://bakcend-gemi-cha-2.onrender.com/auth/callback?code=4/0A...")
        print()
        
        # Intentar abrir en navegador
        try:
            webbrowser.open(auth_url)
            print("✅ Navegador abierto automáticamente")
        except:
            print("⚠️  Copia la URL manualmente")
        
        print()
        print("-" * 80)
        
        # Solicitar URL de callback completa
        callback_url = input("\n📝 Pega la URL completa de la página de redirección: ").strip()
        
        if not callback_url or 'code=' not in callback_url:
            print("\n❌ URL inválida. Debe contener 'code='")
            return
        
        print("\n⏳ Validando código...")
        
        # Extraer código de la URL
        code = callback_url.split('code=')[1].split('&')[0]
        
        # Intercambiar código por tokens
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
        with open("NUEVO_REFRESH_TOKEN.txt", "w") as f:
            f.write(f"GOOGLE_DRIVE_REFRESH_TOKEN={credentials.refresh_token}\n")
            f.write(f"\n# Copia la línea de arriba\n")
            f.write(f"# Dashboard → bakcend-gemi-cha-2 → Environment\n")
            f.write(f"# Pega en: GOOGLE_DRIVE_REFRESH_TOKEN\n")
        
        print()
        print("💾 Token guardado en: NUEVO_REFRESH_TOKEN.txt")
        print()
        print("📝 SIGUIENTE PASO:")
        print("1. Copia el token de arriba")
        print("2. Ve a: https://dashboard.render.com/")
        print("3. Click en: bakcend-gemi-cha-2")
        print("4. Click en: Environment")
        print("5. Busca: GOOGLE_DRIVE_REFRESH_TOKEN")
        print("6. Pega el nuevo token")
        print("7. Save Changes")
        print()
        print("✅ El sistema se auto-renovará después (cada 5 minutos)")
        print("=" * 80)
        print()
        
    except Exception as e:
        print()
        print("=" * 80)
        print("❌ ERROR:")
        print("=" * 80)
        print(str(e))
        print()
        print("💡 Verifica que:")
        print("1. Copiaste la URL COMPLETA (con el 'code=' al final)")
        print("2. No esperaste mucho (el código expira en 1-2 minutos)")
        print("3. Aceptaste todos los permisos en Google")
        print()
        print("=" * 80)

if __name__ == "__main__":
    main()