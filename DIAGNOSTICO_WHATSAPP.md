# 🚨 DIAGNÓSTICO Y SOLUCIÓN: WhatsApp No Envía

## 🔴 EL PROBLEMA

**Síntomas:**
- ✅ Email se envía correctamente
- ❌ WhatsApp NO se envía 
- ✅ N8N dice "Workflow was started"
- ❌ Pero no llega el mensaje a WhatsApp

## 🔍 CAUSA RAÍZ IDENTIFICADA

El flujo de N8N está respondiendo demasiado rápido (`"message": "Workflow was started"`), lo que significa que:

1. **No está esperando a que WAHA envíe el mensaje**
2. **Probablemente está fallando silenciosamente en el nodo WAHA**
3. **No hay manejo de errores para capturar el fallo**

## ✅ SOLUCIONES APLICADAS

### 1. Mejora en Backend (`n8n_notifier.py`)
```python
# ✅ AGREGADO: Logging detallado de si WhatsApp se envió
if channels.get('whatsapp', {}).get('sent'):
    print(f"✅ WHATSAPP enviado: {wa_info.get('numbers')}")
else:
    print(f"⚠️ WHATSAPP NO enviado: {wa_info.get('error')}")
```

### 2. Corrección en N8N (JSON del Workflow)
```javascript
// ANTES (fallaba):
"chatId": "{{ $json.replace(/\\D/g, '') }}@c.us"

// DESPUÉS (corregido):
"chatId": "{{ String($json).replace(/[^0-9+]/g, '') }}@c.us"
```

### 3. Archivos de Diagnóstico Creados
- ✅ `diagnostico_whatsapp.py` - Test básico
- ✅ `test_whatsapp_flow.py` - Test detallado
- ✅ `test_waha_connection.py` - Verificar conexión directa a WAHA
- ✅ `GUIA_REPARAR_WHATSAPP.md` - Guía paso a paso

## 🧪 CÓMO HACER TEST

### Test 1: Verificar que N8N recibe solicitudes
```bash
cd c:\Users\Administrador\Documents\GitHub\BACKENDBETATWILEND
python diagnostico_whatsapp.py
```

Debería mostrar: `✅ Status: 200`

### Test 2: Hacer Test real con tu número
1. Edita `test_whatsapp_flow.py` línea 32:
   ```python
   "whatsapp": "3005551234",  # ← TU NÚMERO AQUÍ
   ```

2. Ejecuta:
   ```bash
   python test_whatsapp_flow.py
   ```

3. **IMPORTANTE**: Revisa N8N Executions
   - Dashboard → Executions
   - Haz click en la última ejecución
   - Expande el nodo "WAHA - Enviar WhatsApp"
   - Busca el error específico

## 🔧 QUÉ REVISAR EN N8N

Si el WhatsApp no se envía, en N8N Executions busca:

### Nodo "Procesar Datos"
- ✅ `whatsapp_numbers` debe tener el número
- ✅ `send_whatsapp` debe ser `true`
- ❌ Si está vacío o false → problema en formateo del número

### Nodo "¿Enviar WhatsApp?"
- ✅ Debe pasar a Split (verde check)
- ❌ Si no pasa → no hay número válido

### Nodo "Split WhatsApp Numbers"
- ✅ Debe crear items con cada número
- ❌ Si no → array vacío

### Nodo "WAHA - Enviar WhatsApp"
- ✅ Debe recibir HTTP Response exitosa
- ❌ Si falla → verificar:
  1. URL es correcta
  2. Formato del `chatId`
  3. Credenciales de autenticación
  4. Session "default" existe en WAHA

## 📱 REQUISITOS PARA WAHA

WAHA requiere:
1. **Sesión activa** - WhatsApp debe estar conectado
   - En WAHA web: Escanear código QR
   - O conectar teléfono

2. **Número en formato correcto**
   - ✅ `3005551234` (10 dígitos, Colombia)
   - ✅ `+573005551234` (con código país)
   - ❌ `(300) 555-1234` (con formato)

3. **Autenticación**
   - Verificar credenciales "httpHeaderAuth" en N8N
   - Debe tener token/apikey válido

4. **Sesión correcta**
   - En payload: `"session": "default"`
   - O el nombre de la sesión configurada

## 🔐 CÓMO VERIFICAR CREDENCIALES WAHA EN N8N

1. Click en N8N → Credentials
2. Busca "Header Auth account" o similar
3. Verificar que tenga:
   - Authorization header con token
   - O Bearer token configurado
   - O API Key correcta

Si no existe o está incompleta:
1. Create New → HTTP Header Auth
2. Agregar header apropiado
3. Guardar
4. Asignar al nodo WAHA

## 📊 FLUJO CORRECTO (Paso a Paso)

```
1. Backend envía a N8N
   └─ POST /webhook/incapacidades
   └─ Con: email, serial, whatsapp, mensaje, etc.

2. N8N recibe (Webhook)
   └─ Procesar Datos (valida y formatea)
   └─ ¿Enviar Email? SÍ → Gmail Sender
   └─ ¿Enviar WhatsApp? SÍ → Split Numbers

3. Split WhatsApp Numbers
   └─ Convierte ["+573005551234"] en items individuales

4. WAHA - Enviar WhatsApp
   └─ POST https://waha-api.../api/sendText
   └─ Con chatId formateado: "573005551234@c.us"

5. Preparar Respuesta
   └─ Recibe confirmación de Gmail
   └─ Recibe confirmación de WAHA (si tuvo éxito)

6. Respond to Webhook
   └─ Backend recibe: { channels: { email: {...}, whatsapp: {...} } }
```

## 📝 PRÓXIMAS ACCIONES

1. **Ejecuta el diagnóstico:**
   ```bash
   python test_whatsapp_flow.py
   ```

2. **Proporciona:**
   - Screenshot de N8N Executions
   - El error específico del nodo WAHA
   - El número de WhatsApp que intentaste
   - Los logs del backend

3. **Si falla WAHA:**
   - Verifica que WAHA tenga sesión activa
   - Revisa credenciales en N8N
   - Confirma formato del número

4. **Si funciona email pero no WhatsApp:**
   - Probablemente es problema de WAHA
   - Valida que el teléfono esté autorizado
   - Comprueba que la sesión no expiró

---

**Cambios realizados:**
- ✅ `n8n_notifier.py` - Logging mejorado
- ✅ Workflow N8N JSON - chatId corregido
- ✅ Scripts de diagnóstico - 3 archivos nuevos
- ✅ Guía de troubleshooting - GUIA_REPARAR_WHATSAPP.md

**Estado:**
🟡 Esperando que proporciones:
- Un número real de WhatsApp para test
- Screenshot de N8N Executions
- Error específico del nodo WAHA

