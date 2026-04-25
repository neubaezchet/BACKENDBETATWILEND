# 🚨 ACCIÓN INMEDIATA: WhatsApp No Envía Mensajes

## Estado Actual
- ✅ Código de WhatsApp Business API: Correcto y desplegado
- ✅ Emails: Enviándose correctamente
- ❌ WhatsApp: NO está enviando mensajes
- **Causa Probable:** Token no está configurado correctamente en Railway

---

## 🎯 QUÉ HACER AHORA MISMO (5-10 minutos)

### PASO 1: Verificar Token Actual en Railway (1 min)

1. Abre: https://railway.app/
2. Entra al proyecto **BACKEND**
3. Pestanya: **Variables**
4. Busca: `WHATSAPP_BUSINESS_API_TOKEN`

#### Si NO existe la variable:
```
❌ PROBLEMA ENCONTRADO
→ Ir a PASO 2 (generar token nuevo)
```

#### Si SÍ existe:
- Copia los primeros 10 caracteres del valor
- Si comienza con `EAAL` → Posiblemente permanente ✅
- Si comienza con `EAA` → Probablemente temporal ❌
- → Ir a PASO 2 (generar token nuevo)

---

### PASO 2: Generar Token Permanente en Meta (3-5 min)

#### Opción A (Más Fácil) - API Explorer:

1. Abre: https://developers.facebook.com/
2. En la esquina superior izquierda, selecciona: **Apps** → **incapacidades patprimo**
   - ⚠️ **IMPORTANTE:** No selecciones "Neurobaeza"
3. En el menú lateral: **Tools** → **API Explorer**
4. En la parte superior derecha, verás el botón **"Get Token"** o **"Access Token"**
5. Haz clic y selecciona:
   - [ ] App Token (a veces aparece)
   - [x] User Token (escoger esta)
6. Si pide seleccionar app: **incapacidades patprimo**
7. Si pide validar token: haz clic en el token que aparece arriba
8. En la ventana de token, asegúrate que dice: **"Never Expires"** o **"Permanent"**
   - Si dice "1 hour" → cancela y pide nuevo
9. **Copia el token completo** (desde el principio hasta el final)
   - Longitud: ~200 caracteres
   - Comienza con: `EAAL`

#### Opción B - Token Settings:

1. Ve a: https://developers.facebook.com/
2. Selecciona app: **incapacidades patprimo**
3. Configuración: **Settings** → **Basic**
4. Busca: **Access Tokens** o **User Tokens**
5. Haz clic en **"Generate"**
6. Copia el token (debe ser permanente)

#### Opción C - Business App Settings:

1. https://business.facebook.com/
2. Settings → Users → System Users (si aplica)
3. O Settings → Apps and Websites → Apps Connected
4. Genera token del sistema

**⚠️ VERIFICACIÓN ANTES DE COPIAR:**
```
Token debe:
✅ Comenzar con "EAAL"
✅ Tener ~200 caracteres
✅ Mostrar "Never Expires" o "Permanent" (NO "1 hour")
✅ Ser de app "incapacidades patprimo" (NO "Neurobaeza")
```

---

### PASO 3: Actualizar Token en Railway (2 min)

1. Railway: https://railway.app/
2. Proyecto: **BACKEND**
3. Pestanya: **Variables**
4. **Si NO existe `WHATSAPP_BUSINESS_API_TOKEN`:**
   - Botón: **+ Add Variable**
   - Nombre: `WHATSAPP_BUSINESS_API_TOKEN`
   - Valor: `[pega el token que copiaste]`
   - Guardar ✅
5. **Si YA existe:**
   - Haz clic en el lápiz (edit)
   - Borra el valor actual
   - Pega el token nuevo
   - Guardar ✅

**También verifica:**
- Variable: `WHATSAPP_PHONE_NUMBER_ID`
- Valor: `1065658909966623`
- Si no existe, crear

---

### PASO 4: Redeploy y Esperar (3 min)

1. Railway detectará cambios automáticamente
2. Irá a: **Deployments** y verás "Deployment in progress..."
3. Espera a que termine (buscará en el status verde: "Deployment Successful ✅")
4. **Espera 2-3 minutos más** antes de probar

---

### PASO 5: Probar WhatsApp (2 min)

#### Opción A: Formulario Real
1. Abre portal: https://repogemin.vercel.app/
2. Llenar:
   - Cédula: `80123456` (o cualquiera)
   - Tipo: **`Enfermedad General`** (muy importante: NO "Otro")
   - Email: `tu_email@gmail.com`
   - Teléfono: tu celular real (ej: `3001234567`)
   - Archivos: Sube un PDF
3. Enviar
4. Espera 2-3 minutos
5. Chequea:
   - ✅ ¿Llegó email? → Sistema OK
   - ✅ ¿Llegó WhatsApp? → PROBLEMA RESUELTO ✨
   - ❌ ¿No llegó WhatsApp? → Ir a sección "Troubleshooting"

#### Opción B: Prueba Rápida (Terminal PowerShell)
```powershell
# Ejecuta esto en PowerShell:
$token = "tu_token_aqui"
$phone_id = "1065658909966623"
$to_number = "573001234567"  # Reemplaza con tu número

$body = @{
    messaging_product = "whatsapp"
    to = $to_number
    type = "text"
    text = @{
        preview_url = $false
        body = "Prueba desde PowerShell"
    }
} | ConvertTo-Json

$headers = @{
    Authorization = "Bearer $token"
    "Content-Type" = "application/json"
}

$response = Invoke-WebRequest `
    -Uri "https://graph.instagram.com/v19.0/$phone_id/messages" `
    -Headers $headers `
    -Method Post `
    -Body $body

$response.Content | ConvertFrom-Json | ConvertTo-Json
```

---

## 🆘 Si Aún No Funciona

### Ejecutar Script de Diagnóstico:

1. Abre PowerShell
2. Ve a la carpeta: `cd "C:\Users\david.baeza\Documents\BACKENDBETATWILEND"`
3. Ejecuta:
```powershell
# Primero, configura el token en este terminal:
$env:WHATSAPP_BUSINESS_API_TOKEN = "EAAL...pega_tu_token_aqui"
$env:WHATSAPP_PHONE_NUMBER_ID = "1065658909966623"

# Luego corre el verificador:
PowerShell -ExecutionPolicy Bypass -File .\test_whatsapp.ps1
```

4. Leerá los resultados:
   - ✅ Si ve "RESPUESTA EXITOSA" → Token es válido, problema es en Railway
   - ❌ Si ve "ERROR 401" → Token es temporal o inválido
   - ❌ Si ve "ERROR 400" → Verificar Phone Number ID

---

## 📋 Checklist Rápido

Antes de enviar un formulario de prueba:

- [ ] ¿Generaste token NUEVO desde Meta?
- [ ] ¿El token comienza con "EAAL"?
- [ ] ¿El token es PERMANENTE (Never Expires)?
- [ ] ¿El token es de app "incapacidades patprimo"?
- [ ] ¿Actualizaste WHATSAPP_BUSINESS_API_TOKEN en Railway?
- [ ] ¿Verificaste WHATSAPP_PHONE_NUMBER_ID = 1065658909966623?
- [ ] ¿Hizo Railway redeploy automático?
- [ ] ¿Esperaste 2-3 minutos después del redeploy?
- [ ] ¿Probaste con tipo = "Enfermedad General" (NO "Otro")?
- [ ] ¿Incluiste un número de teléfono válido?

---

## 🔗 Referencias

- Generador de Token: https://developers.facebook.com/apps
- Dashboard Railway: https://railway.app/
- Portal Repogemin: https://repogemin.vercel.app/
- Documentación Meta: https://developers.facebook.com/docs/whatsapp/cloud-api

---

## ⏱️ Tiempo Estimado Total: 10-15 minutos

1. Verificar en Railway: 1 min
2. Generar token en Meta: 3-5 min
3. Actualizar en Railway: 2 min
4. Redeploy y esperar: 3 min
5. Probar: 2 min

**TOTAL: 11-13 minutos**

Después, si funciona, ¡el WhatsApp debería enviarse para todas las nuevas incapacidades!
