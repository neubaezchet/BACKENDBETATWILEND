# 🔧 SOLUCIÓN FINAL: Autenticación WAHA en N8N

## 🎯 EL PROBLEMA REAL

**WAHA está configurado en Railway con:**
```
API Key: 1085043374
URL: https://devlikeaprowaha-production-111a.up.railway.app
Versión: 2025.12.1
Motor: WEBJS
```

**Pero el nodo N8N NO está enviando el API Key**

→ Por eso WAHA rechaza con **401 Unauthorized** o falla silenciosamente

---

## ✅ SOLUCIÓN

### Paso 1: Verificar la autenticación
```bash
cd c:\Users\Administrador\Documents\GitHub\BACKENDBETATWILEND
python test_waha_auth.py
```

Esto prueba:
- ✅ Conexión con X-API-Key header
- ✅ Obtener sesiones disponibles
- ✅ Enviar mensaje real

### Paso 2: Actualizar N8N - Nodo "WAHA - Enviar WhatsApp"

En el workflow JSON (`IncaNeurobaeza - Email + WhatsApp v5 (1).json`):

**ANTES (sin autenticación):**
```json
"credentials": {
  "httpHeaderAuth": {
    "id": "jTS0vO9s08ycQzUi",
    "name": "Header Auth account"
  }
}
```

**DESPUÉS (con API Key):**

El nodo debe tener credenciales de tipo **Header Auth** con:
- Header Name: `X-API-Key`
- Header Value: `1085043374`

O si lo configuras directamente en el Body, agregar:

```json
"jsonBody": "{\n  \"session\": \"default\",\n  \"chatId\": \"{{ String($json).replace(/[^0-9+]/g, '') }}@c.us\",\n  \"text\": \"{{ $('Procesar Datos').first().json.whatsapp_text }}\",\n  \"delay\": 1000\n}",
"headers": {
  "X-API-Key": "1085043374",
  "Content-Type": "application/json"
}
```

### Paso 3: En N8N Dashboard - Configurar Credenciales

1. Click en **Credentials** (lado izquierdo)
2. Click en **+ New** 
3. Selecciona **HTTP Header Auth**
4. Nombre: `WAHA API Key`
5. En Headers:
   - Header Name: `X-API-Key`
   - Header Value: `1085043374`
6. Click **Save**

### Paso 4: Asignar Credenciales al Nodo

1. Abre el nodo "WAHA - Enviar WhatsApp"
2. En **Authentication**: Selecciona `genericCredentialType`
3. En **Generic Auth Type**: Selecciona `httpHeaderAuth`
4. En **Credentials**: Selecciona la credencial recién creada (`WAHA API Key`)
5. Click **Save**

---

## 📋 CHECKLIST

- [ ] API Key configurada en Railway WAHA: `1085043374`
- [ ] N8N tiene credencial "Header Auth" con el API Key
- [ ] Nodo WAHA usa esa credencial
- [ ] Header se envía en cada request: `X-API-Key: 1085043374`
- [ ] Test `test_waha_auth.py` devuelve "ÉXITO"
- [ ] Mensaje llega al WhatsApp real

---

## 🧪 TEST RÁPIDO

```bash
# Test sin número (solo verificar conexión)
python test_waha_auth.py

# Te pedirá un número, ingresa: 573005551234 (o tu número real)
# Si dice "ÉXITO", WhatsApp funciona
```

---

## ❓ SI SIGUE SIN FUNCIONAR

### Opción A: Usar Bearer Token en lugar de X-API-Key
```
Authorization: Bearer 1085043374
```

Cambiar el header a:
```
Header Name: Authorization
Header Value: Bearer 1085043374
```

### Opción B: Usar credenciales de Dashboard
```
Username: admin
Password: wdp_YD17FR0JJMNGG+15
```

Usar **Basic Auth** en lugar de header personalizado.

### Opción C: Verificar si WAHA está activo

En Railway:
1. Ve a tu proyecto Railway
2. Click en **Services**
3. Busca **WAHA**
4. Verifica que esté **"Running"**
5. Si no, reinicia el servicio

---

## 📊 FLUJO CORRECTO AHORA

```
1. Backend envía a N8N
   └─ POST /webhook/incapacidades
   └─ Con: whatsapp=3005551234

2. N8N Procesa Datos
   └─ Formatea número: 573005551234

3. N8N WAHA - Enviar WhatsApp
   └─ POST /api/sendText
   └─ Header: X-API-Key: 1085043374
   └─ Body: { session: "default", chatId: "+573005551234@c.us", text: "..." }

4. WAHA autentica y envía
   ✅ Retorna 200 OK

5. N8N devuelve confirmación
   └─ { channels: { whatsapp: { sent: true, ... } } }

6. Backend recibe
   └─ Logea: "✅ WHATSAPP enviado"

7. Frontend recibe respuesta exitosa
   └─ Muestra: "Solicitud enviada con éxito"
```

---

## 📝 ARCHIVOS A CONSULTAR

1. **test_waha_auth.py** ← Ejecuta esto primero
2. **railway-n8n/wordflok/IncaNeurobaeza - Email + WhatsApp v5 (1).json** ← Actualizar credenciales
3. **app/n8n_notifier.py** ← Ya mejorado con logging

---

## 🚀 PRÓXIMOS PASOS

1. ✅ Ejecuta `test_waha_auth.py`
2. ✅ Configura credenciales en N8N Dashboard
3. ✅ Prueba con un número real
4. ✅ Verifica logs en N8N Executions
5. ✅ Confirma que WhatsApp llega

---

**Información de WAHA:**
- Versión: 2025.12.1
- API Key: 1085043374
- URL: https://devlikeaprowaha-production-111a.up.railway.app
- Motor: WEBJS
- OAS 3.1

**Si todo funciona, el sistema completo debería:**
- ✅ Email llega al instante
- ✅ WhatsApp llega en segundos
- ✅ Frontend muestra "Éxito"
- ✅ Usuario ve confirmación visual

