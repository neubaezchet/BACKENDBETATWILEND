# 🚀 MIGRACIÓN: WAHA → WhatsApp Business API

**Fecha:** 19 de abril de 2026

## ✅ Cambios Realizados

### 1️⃣ Código Actualizado - `app/email_service.py`

| Cambio | Detalles |
|--------|----------|
| ❌ WAHA API | Removida la configuración de WAHA (ya no se usa) |
| ✅ WhatsApp Business API | Agregada nueva integración con Meta Graph API |
| 🔄 Rate Limiting | Removido - Business API no requiere rate limiting restrictivo |
| 🔧 Compatibilidad | Alias `_enviar_whatsapp()` redirecciona a nueva función |

### 2️⃣ Configuración Nueva

**Variables de Entorno Necesarias:**

```
WHATSAPP_BUSINESS_API_TOKEN          # Token de Meta para Graph API
WHATSAPP_PHONE_NUMBER_ID             # ID del número de teléfono
```

**Opcionales (alias):**
```
WHATSAPP_PHONE_ID                    # Alias para WHATSAPP_PHONE_NUMBER_ID
WHATSAPP_API_TOKEN                   # Alias para WHATSAPP_BUSINESS_API_TOKEN
```

### 3️⃣ Cambios en Funciones

#### REMOVIDA: `_enviar_whatsapp()` (vieja - WAHA)
```python
# ❌ YA NO SE USA
url = f"{WAHA_BASE_URL}/api/sendMessage"
payload = {"chatId": f"{numero}@c.us", "text": mensaje}
```

#### AGREGADA: `_enviar_whatsapp_business()` (nueva - Business API)
```python
# ✅ NUEVA
url = f"https://graph.instagram.com/v19.0/{WHATSAPP_PHONE_ID_FINAL}/messages"
payload = {
    "messaging_product": "whatsapp",
    "to": numero,
    "type": "text",
    "text": {"preview_url": False, "body": mensaje}
}
headers = {"Authorization": f"Bearer {WHATSAPP_API_TOKEN}"}
```

## 📋 Guía de Configuración en Railway

### PASO 1: Obtener Credenciales de Meta

1. **Ir a Meta Business Suite:**
   - https://developers.facebook.com/
   - https://www.meta.com/en_US/business/

2. **Crear o acceder a una aplicación de WhatsApp:**
   - Dashboard → Apps → Crear nueva app
   - Tipo: Business
   - Nombre: "IncaNeurobaeza Backend"

3. **Habilitar WhatsApp Product:**
   - Dashboard → Productos → Agregar productos
   - Buscar "WhatsApp"
   - Click en "Set up"

4. **Obtener el Token:**
   - WhatsApp Dashboard → API Setup
   - Copiar: **Temporary Access Token** o generar **Permanent Token**
   - Este es: `WHATSAPP_BUSINESS_API_TOKEN`

5. **Obtener Phone Number ID:**
   - WhatsApp Dashboard → Phone numbers
   - Click en el número que estés usando
   - Copiar el ID de la URL o de los detalles
   - Este es: `WHATSAPP_PHONE_NUMBER_ID`

### PASO 2: Configurar en Railway

1. **Ir a Railway Dashboard:**
   - https://railway.app/project/...
   - Click en "Variables"

2. **Agregar Variables:**

| Variable | Valor | Notas |
|----------|-------|-------|
| `WHATSAPP_BUSINESS_API_TOKEN` | Token de Meta | Debe ser permanente, no temporal |
| `WHATSAPP_PHONE_NUMBER_ID` | ID del teléfono | Formato: números solamente, ej: 1234567890 |

3. **Guardar y Redeploy:**
   - Click "Deploy"
   - Esperar a que la app reinicie

### PASO 3: Verificar Configuración

Revisa los logs en Railway después de redeploy:

**✅ Correcto (deberías ver):**
```
✅ WhatsApp Business API configurada correctamente
```

**❌ Error (si falta algo):**
```
⚠️ ADVERTENCIA: WhatsApp Business API no completamente configurada
✅ WHATSAPP_BUSINESS_API_TOKEN: ✓
✅ WHATSAPP_PHONE_NUMBER_ID: ❌ FALTA
```

## 🔧 Testing & Troubleshooting

### Prueba 1: Envío Simple

Envía un formulario de incapacidad desde el frontend. Deberías ver en logs de Railway:

```
📱 Enviando WhatsApp Business a +57XXXXXXXXX...
✅ WhatsApp Business enviado
```

### Prueba 2: Verificar Configuración

Si no funciona, crea un script Python en Railway:

```python
import os
token = os.environ.get("WHATSAPP_BUSINESS_API_TOKEN", "NO CONFIGURADO")
phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "NO CONFIGURADO")
print(f"Token: {token[:20] if token != 'NO CONFIGURADO' else token}...")
print(f"Phone ID: {phone_id}")
```

### Errores Comunes

| Error | Causa | Solución |
|-------|-------|----------|
| `401 Unauthorized` | Token inválido o expirado | Generar nuevo token permanente en Meta |
| `400 Bad Request` | Phone ID incorrecto | Verificar formato (solo números) |
| `404 Not Found` | Versión API incorrecta | Usar v19.0 o superior |
| `Malformed message` | Formato del mensaje | Validar caracteres especiales en mensaje |

## 📝 Compatibilidad

### Qué se mantiene igual:
- ✅ Función `enviar_notificacion()` - misma firma
- ✅ Generación de mensajes - `generar_mensaje_whatsapp()` igual
- ✅ Lógica de email - `_enviar_email_service_account()` igual
- ✅ Logs y debugging - Mejorados pero compatibles

### Qué cambió:
- ❌ WAHA_BASE_URL - Removida
- ❌ WAHA_API_KEY - Removida
- ❌ WAHA_SESSION_NAME - Removida
- ✅ WHATSAPP_BUSINESS_API_TOKEN - Nueva
- ✅ WHATSAPP_PHONE_NUMBER_ID - Nueva

## 🔗 Referencias

- **Meta Graph API Docs:** https://developers.facebook.com/docs/whatsapp/cloud-api/
- **WhatsApp Business Messaging:** https://www.whatsapp.com/business/
- **Postman Collection:** https://www.postman.com/downloads/ (para testing manual)

## ✅ Checklist de Deployación

- [ ] Obtuve `WHATSAPP_BUSINESS_API_TOKEN` de Meta
- [ ] Obtuve `WHATSAPP_PHONE_NUMBER_ID` correcto
- [ ] Agregué variables en Railway
- [ ] Hice deploy y reinicié la app
- [ ] Vi en logs: "✅ WhatsApp Business API configurada correctamente"
- [ ] Envié formulario y recibí WhatsApp
- [ ] Verifiqué que el número + mensaje sean correctos

¡Listo! 🎉

