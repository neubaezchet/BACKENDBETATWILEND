
# 🔧 GUÍA: Reparar N8N - WhatsApp no envía

## 📋 Problema
El flujo de N8N envía emails correctamente pero **WhatsApp NO se envía**.

## ✅ Checklist de Verificación

### 1. Backend → N8N
- [ ] El backend envía `whatsapp` con un número válido
- [ ] El número tiene formato: `3005551234` o `+573005551234`
- [ ] En logs del backend verifica: `WhatsApp: 3005551234` (no vacío)

### 2. N8N - Nodo "Procesar Datos"
El nodo debe:
- [ ] Recibir los datos del webhook correctamente
- [ ] Validar y formatear el número a `+57XXXXXXXXXX`
- [ ] Establecer `send_whatsapp: true` cuando hay número válido
- [ ] Log: `console.log('📱 WhatsApp números:', whatsapp_numbers);`

### 3. N8N - Condición "¿Enviar WhatsApp?"
- [ ] Debe verificar `send_whatsapp === true`
- [ ] Solo ejecuta si hay número válido

### 4. N8N - Nodo "Split WhatsApp Numbers"
- [ ] Divide el array `whatsapp_numbers`
- [ ] Cada item es un string con el número

### 5. N8N - Nodo "WAHA - Enviar WhatsApp"
- [ ] Es un HTTP Request a: `https://devlikeaprowaha-production-111a.up.railway.app/api/sendText`
- [ ] **MUY IMPORTANTE**: Tiene credenciales de autenticación configuradas
- [ ] El `chatId` se construye como: `+57XXXXXXXXXX@c.us`
- [ ] El método es POST
- [ ] Body es JSON

```json
{
  "session": "default",
  "chatId": "{{ String($json).replace(/[^0-9+]/g, '') }}@c.us",
  "text": "{{ $('Procesar Datos').first().json.whatsapp_text }}",
  "delay": 1000
}
```

## 🔐 Autenticación WAHA

El nodo WAHA debe tener **Header Auth** configurada:
- [ ] Authorization header con token válido
- [ ] O verificar si WAHA requiere token en query params

**En N8N**:
1. Click en nodo WAHA
2. Busca "Credentials" o "Authentication"
3. Debe haber credenciales "httpHeaderAuth" asignadas

Si no hay credenciales:
1. Crea nueva credencial "Header Auth"
2. Agrega header: `Authorization: Bearer <TOKEN>`

## 🧪 Test

Ejecuta el script de diagnóstico:
```bash
cd c:\Users\Administrador\Documents\GitHub\BACKENDBETATWILEND
python diagnostico_whatsapp.py
```

Debe mostrar:
```
✅ WhatsApp: ✅
   Enviados: 1/1
   Números: ['+573005551234']
```

Si muestra `❌ WhatsApp: ❌`, verifica:
1. El error específico en N8N
2. Las credenciales de WAHA
3. El formato del número

## 📊 Debug en N8N

En el nodo "Procesar Datos", agrega antes del return:
```javascript
console.log('📊 DEBUG:');
console.log('  whatsapp_numbers:', whatsapp_numbers);
console.log('  send_whatsapp:', whatsapp_numbers.length > 0);
```

En el nodo WAHA, agrégale error handling:
```
Se puede agregar un nodo "Try-Catch" o "Error Handler"
```

## 🔗 URLs Verificadas
- ✅ N8N: https://railway-n8n-production-5a3f.up.railway.app/webhook/incapacidades
- ✅ WAHA: https://devlikeaprowaha-production-111a.up.railway.app/api/sendText
- ⏳ Verificar estado de WAHA en Railway

## 📝 Cambios Realizados

1. ✅ Mejorado logging en `n8n_notifier.py`
2. ✅ Corregida construcción de `chatId` en N8N
3. ✅ Agregada validación de número en "Procesar Datos"
4. ✅ Creado script de diagnóstico `diagnostico_whatsapp.py`

## ❓ Preguntas para el Usuario

1. ¿Cuál es el **número de teléfono** exacto de prueba?
   - Formato correcto: `3005551234` o `+573005551234`

2. ¿Qué **error específico** devuelve WAHA?
   - Ver en logs de N8N → Executions

3. ¿WAHA está **autenticado correctamente**?
   - Tiene token válido?
   - Sesión de WhatsApp activa?

4. ¿El **número está registrado** en WAHA?
   - Necesita scanear código QR primero?

---

**Próximo paso**: Ejecuta `diagnostico_whatsapp.py` con un número real y comparte los logs.

