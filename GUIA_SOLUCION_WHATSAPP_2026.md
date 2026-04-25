# 🆘 GUÍA COMPLETA: Solucionar WhatsApp Business API No Envía Mensajes

## Síntomas del Problema
- ✅ Emails se envían correctamente
- ✅ Base de datos se actualiza correctamente
- ✅ Código de WhatsApp se ejecuta sin errores
- ❌ **WhatsApp NO envía mensajes**
- Logs muestran: HTTP 401 "Invalid OAuth access token" O sin intentos de envío

---

## 🎯 Diagnóstico Paso a Paso

### PASO 1: Verificar Variables de Entorno en Railway

**Ubicación:** https://railway.app/ → Proyecto → Variables

#### ✅ Variables Correctas:
```
WHATSAPP_BUSINESS_API_TOKEN = EAAL...
WHATSAPP_PHONE_NUMBER_ID = 1065658909966623
```

#### ❌ Variables Incorrectas (Problemas):
```
WHATSAPP_API_TOKEN = algo              ← ⚠️ Nombre variable incorrecto
WHATSAPP_API_URL = https://...         ← ⚠️ No se usa, solo token
WHATSAPP_BUSINESS_ACCOUNT_ID = 123     ← ⚠️ No se usa, solo phone ID
```

**Acción:**
- [ ] Ir a Railway → proyecto BACKEND
- [ ] Verificar pestanya "Variables"
- [ ] Confirmar que existen EXACTAMENTE:
  - `WHATSAPP_BUSINESS_API_TOKEN` (comienza con `EAAL`)
  - `WHATSAPP_PHONE_NUMBER_ID` (valor: `1065658909966623`)
- [ ] Si faltan: crear variables (siguiente paso)
- [ ] Si están mal nombradas: eliminar variables incorrectas

---

### PASO 2: Generar Token Permanente de Meta

El problema MÁS PROBABLE es que el token actual es **temporal** (expira cada hora).

#### Instrucciones para Generar Token Permanente:

1. **Ir a Meta Business Suite:**
   - https://business.facebook.com/
   - O https://developers.facebook.com/

2. **Seleccionar la App Correcta:**
   - ⚠️ **IMPORTANTE:** Debe ser `incapacidades patprimo`
   - ❌ NO uses `Neurobaeza` (tiene acceso parcial)

3. **Navegar a Generador de Token:**
   - Opción A (Recomendado): 
     - Tools → Explorador de API (API Explorer)
     - Seleccionar: `GET /{WHATSAPP_PHONE_NUMBER_ID}/about`
     - Buscar el botón "Access Token" en la parte superior
     - Copiar el token completo (empieza con `EAAL`)
   
   - Opción B:
     - Ir a Settings → User Tokens
     - Generar nuevo token con scopes: `whatsapp_business_messaging`

4. **CRUCIAL: Verificar Tipo de Token:**
   - Cuando generes, asegúrate de seleccionar:
     - **"Never Expires"** o **"Permanent"** (NO "1 hour")
     - Si ya tiene "1 hour", rechaza y pide nuevo

5. **Copiar el Token Completo:**
   - Ejemplo: `EAAL0OQ0XJ3kBAOmMHBvmYZCrMXB...`
   - Longitud: ~200 caracteres
   - Comienza con `EAAL`

#### Verificación Rápida del Token:
```bash
# Reemplaza el_token_aqui con tu token
curl -X GET "https://graph.instagram.com/v19.0/1065658909966623?access_token=el_token_aqui"

# Respuesta exitosa:
# {"id":"1065658909966623","display_phone_number":"57 323 7064766","phone_number_id":"1065658909966623",...}

# Error si es temporal o inválido:
# {"error":{"message":"Invalid OAuth access token...","type":"OAuthException"}}
```

---

### PASO 3: Actualizar Token en Railway

1. **Abrir Railway:**
   - https://railway.app/ → Proyecto BACKEND

2. **Editar Variables:**
   - Pestanya: "Variables"
   - Buscar: `WHATSAPP_BUSINESS_API_TOKEN`
   - Acción: Editar (pencil icon)
   - Pegar el nuevo token completo (sin espacios al inicio/final)
   - Guardar

3. **Verificar Datos Adicionales:**
   - `WHATSAPP_PHONE_NUMBER_ID` = `1065658909966623`
   - Si no existe: crear variable con este valor

4. **IMPORTANTE: Redeploy**
   - Railway debería redeploy automático
   - Si no: Deployments → Redeploy latest
   - Esperar a que aparezca "Deployment Successful" ✅

---

### PASO 4: Probar WhatsApp después de Actualizar

**Esperar 2-3 minutos** después del redeploy.

#### Opción A: Prueba desde Form:
1. Ir a: https://repogemin.vercel.app/ (o tu portal)
2. Llenar formulario con:
   - Cédula: cualquiera
   - Tipo: `Enfermedad General` (O `Accidente Laboral` O `Accidente Tránsito`)
   - ⚠️ **NO use "Otro"** (genera error enum)
   - Email: tuEmail@gmail.com
   - Teléfono: tu_celular (ej: 3001234567)
   - Archivos: subir PDF válido
3. Enviar
4. Esperar 2-3 minutos
5. Revisar:
   - ✅ Email llega (para confirmar sistema funciona)
   - ✅ WhatsApp llega

#### Opción B: Prueba Manual (Avanzado):
```python
import requests

TOKEN = "EAAL..."  # Tu nuevo token
PHONE_ID = "1065658909966623"
NUMBER = "573001234567"  # Tu número con +57

payload = {
    "messaging_product": "whatsapp",
    "to": NUMBER,
    "type": "text",
    "text": {
        "preview_url": False,
        "body": "Prueba WhatsApp"
    }
}

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

response = requests.post(
    f"https://graph.instagram.com/v19.0/{PHONE_ID}/messages",
    json=payload,
    headers=headers
)

print(f"Status: {response.status_code}")
print(response.text)
```

---

## 🔍 Tabla de Solución de Problemas

### Problema: Error 401 "Invalid OAuth access token"

| Causa | Síntomas | Solución |
|-------|----------|----------|
| **Token temporal** | Error 401 después de 1-2 horas | Generar token PERMANENTE ("Never Expires") |
| **Token expirado** | Error 401 constante | Generar nuevo token permanente |
| **Token de app incorrecta** | Error 401 | Generar token desde `incapacidades patprimo` (NO Neurobaeza) |
| **Token corrupto** | Error 401 o 400 | Copiar token nuevamente, sin espacios |
| **Variable mal nombrada** | WhatsApp no intenta enviar | Usar exactamente: `WHATSAPP_BUSINESS_API_TOKEN` |
| **Phone ID incorrecto** | Error 400 o 404 | Usar: `1065658909966623` |
| **Phone ID mal nombrado** | WhatsApp no intenta enviar | Usar exactamente: `WHATSAPP_PHONE_NUMBER_ID` |

### Problema: WhatsApp No Intenta Enviar (Sin Logs)

| Causa | Síntomas | Solución |
|-------|----------|----------|
| **Token no configurado** | Log vacío, sin intentos | Configurar `WHATSAPP_BUSINESS_API_TOKEN` en Railway |
| **Phone ID no configurado** | Log vacío, sin intentos | Configurar `WHATSAPP_PHONE_NUMBER_ID` en Railway |
| **Parámetro whatsapp=None** | Log vacío, sin intentos | Verificar que formulario envía `telefono` |
| **Tipo de incapacidad = "otro"** | Mata proceso antes de enviar | Usar solo: accidente_transito, accidente_laboral, enfermedad_general |

### Problema: Email OK pero WhatsApp Falla

| Causa | Síntomas | Solución |
|-------|----------|----------|
| **Token inválido** | Email ✅, WhatsApp ❌ con 401 | Verificar/regenerar token |
| **Acción correcta** | Email ✅, WhatsApp falla pero sigue | Normal - email Service Account es independiente |
| **Reintentos activos** | Múltiples intentos fallidos | Esperar a que expire retry o redeploy |

---

## 📋 Checklist Final

**ANTES de reportar que aún no funciona, verificar:**

- [ ] Variable `WHATSAPP_BUSINESS_API_TOKEN` existe en Railway
- [ ] Token comienza con `EAAL` (no `EAA` solamente)
- [ ] Token NO tiene espacios al inicio/final
- [ ] Variable `WHATSAPP_PHONE_NUMBER_ID` = `1065658909966623`
- [ ] Token fue generado desde app `incapacidades patprimo` (NO `Neurobaeza`)
- [ ] Token es PERMANENTE ("Never Expires"), NO temporal ("1 hour")
- [ ] Se hizo Redeploy después de actualizar variables
- [ ] Esperaste 2-3 minutos después del redeploy
- [ ] Probaste con tipo de incapacidad VÁLIDO (no "otro")
- [ ] Verificaste logs en Railway después de enviar (buscar "Enviando WhatsApp")
- [ ] Email llegó correctamente (confirma sistema conectado)

---

## 🆘 Si Aún No Funciona

Proporciona:

1. **Token actual** (primeros 20 caracteres):
   ```
   EAAL...?
   ```

2. **Primer error en logs:**
   ```
   Error HTTP: 401, 400, 500, etc?
   Mensaje de error exacto
   ```

3. **Verificación rápida:**
   ```bash
   # Copia y ejecuta (reemplaza el_token_aqui):
   curl "https://graph.instagram.com/v19.0/1065658909966623?access_token=el_token_aqui"
   
   # Resultado:
   ```

---

## 🎓 Referencia Rápida

**API Meta WhatsApp Business:**
- Documentación: https://developers.facebook.com/docs/whatsapp/cloud-api/
- Versión: v19.0
- Endpoint: `https://graph.instagram.com/v19.0/{PHONE_NUMBER_ID}/messages`
- Auth: Bearer token en header
- Account: Debe ser propietario del phone number +57 323 7064766

**Nuestro Setup:**
- App: `incapacidades patprimo` (ID: 842655611494600)
- Phone: +57 323 7064766
- Phone ID: 1065658909966623
- Business Account ID: 4323018671298033
