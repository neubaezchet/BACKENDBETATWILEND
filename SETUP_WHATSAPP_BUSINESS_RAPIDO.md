# ✅ GUÍA RÁPIDA: Cambiar de WAHA a WhatsApp Business API

## 🎯 Resumen de Cambios

**Código actualizado:** `app/email_service.py`
- ❌ Removida integración con WAHA
- ✅ Agregada integración con WhatsApp Business API (Meta)
- ✅ Mantiene la misma API (función `_enviar_whatsapp()` sigue funcionando)

---

## 🚀 3 PASOS = LISTO

### PASO 1: Obtener Credenciales de Meta (15 minutos)

**A. Ir a Meta for Developers:**
1. https://developers.facebook.com/
2. Login con tu cuenta de Meta/Facebook

**B. Crear o acceder a App de WhatsApp:**
1. Dashboard → "Mi Apps" → Crear nueva app
2. Tipo: **Business**
3. Nombre: "IncaNeurobaeza Backend"
4. Click "Crear app"

**C. Configurar WhatsApp Product:**
1. En la app → "Productos"
2. Click "+ Agregar producto"
3. Buscar "WhatsApp"
4. Click "Configurar" o "Set Up"

**D. Obtener el Token:**
1. Ir a: WhatsApp → API Setup
2. Copiar: **Access Token** (o generar uno permanente)
   ```
   WHATSAPP_BUSINESS_API_TOKEN = copiar aquí
   ```

**E. Obtener Phone Number ID:**
1. Ir a: WhatsApp → Números de teléfono
2. Click en tu número (o agregarlo si no existe)
3. Copiar el **ID del número**
   ```
   WHATSAPP_PHONE_NUMBER_ID = copiar aquí
   ```

✅ **Ya tienes:**
- `WHATSAPP_BUSINESS_API_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`

---

### PASO 2: Configurar en Railway (5 minutos)

**A. Ir a Railway:**
1. https://railway.app/project/[tu-project-id]
2. Click en la app "backend" o "main"

**B. Agregar Variables de Entorno:**
1. Click en "Variables"
2. Agregar nueva variable:
   ```
   Clave: WHATSAPP_BUSINESS_API_TOKEN
   Valor: [El token que copiaste en Paso 1D]
   ```
3. Agregar segunda variable:
   ```
   Clave: WHATSAPP_PHONE_NUMBER_ID
   Valor: [El ID que copiaste en Paso 1E]
   ```
4. Click "Save"

**C. Hacer Deploy:**
1. Click "Redeploy" o esperar a que detecte cambios
2. Esperar a que la app reinicie (2-3 minutos)

✅ **Verificar en logs:**
```
✅ WhatsApp Business API configurada correctamente
```

---

### PASO 3: Probar Configuración (5 minutos)

**Opción A: Test Automático (recomendado)**

```bash
# En tu máquina local:
cd c:\Users\david.baeza\Documents\BACKENDBETATWILEND

# Copiar variables de Railway a un archivo .env:
# (O configurarlas manualmente en PowerShell)

# Ejecutar test:
python test_whatsapp_business_api.py
```

**Deberías ver:**
```
✅ TODAS LAS PRUEBAS PASARON
✅ Conectividad con Meta: OK
✅ Phone ID: Válido
```

**Opción B: Test Manual**

1. Abre el frontend
2. Llena un formulario de incapacidad
3. Envía
4. Deberías recibir email + WhatsApp

---

## ✅ Checklist Final

- [ ] Obtuve `WHATSAPP_BUSINESS_API_TOKEN` de Meta
- [ ] Obtuve `WHATSAPP_PHONE_NUMBER_ID` correcto
- [ ] Agregué ambas variables en Railway
- [ ] Hice Redeploy en Railway
- [ ] Verifiqué en logs que dice "✅ WhatsApp Business API configurada"
- [ ] Ejecuté `test_whatsapp_business_api.py` (opcional)
- [ ] Envié un formulario y recibí WhatsApp

✅ **LISTO PARA PRODUCCIÓN**

---

## 🆘 Si Algo No Funciona

### Error 1: "WhatsApp Business API no completamente configurada"

**Causa:** Faltan variables en Railway

**Solución:**
```bash
# En Railway, verifica que existan:
echo $WHATSAPP_BUSINESS_API_TOKEN   # Debe mostrar algo
echo $WHATSAPP_PHONE_NUMBER_ID      # Debe mostrar algo
```

Si está vacío, repite PASO 2.

### Error 2: "401 Unauthorized"

**Causa:** Token inválido o expirado

**Solución:**
1. Ve a https://developers.facebook.com/
2. Genera un nuevo token **PERMANENTE** (no temporal)
3. Reemplaza en Railway
4. Redeploy

### Error 3: "404 Not Found"

**Causa:** Phone ID incorrecto

**Solución:**
1. Verifica en Meta Business Suite que el teléfono existe
2. Copia exactamente el ID (solo números, sin + ni espacios)
3. Reemplaza en Railway
4. Redeploy

### Error 4: "No se envía WhatsApp"

**Solución:**
1. Revisa los logs en Railway (últimas 30 líneas)
2. Busca líneas con "📱 Enviando WhatsApp Business"
3. Copia el error completo
4. Contacta soporte con el error

---

## 📁 Archivos Nuevos/Modificados

| Archivo | Cambio |
|---------|--------|
| `app/email_service.py` | ✅ Actualizado para usar WhatsApp Business API |
| `test_whatsapp_business_api.py` | ✨ Nuevo - Script de testing |
| `MIGRACION_WAHA_A_WHATSAPP_BUSINESS.md` | 📖 Documentación detallada |

---

## 🔗 Enlaces Útiles

- **Meta Developers:** https://developers.facebook.com/
- **WhatsApp Cloud API Docs:** https://developers.facebook.com/docs/whatsapp/cloud-api/
- **Railway Dashboard:** https://railway.app/
- **Meta Business Suite:** https://business.facebook.com/

---

¿Necesitas ayuda? Contacta al equipo técnico con:
- Salida de `test_whatsapp_business_api.py`
- Logs de Railway (últimas 100 líneas)
- Screenshots de Meta Business Suite

¡Listo! 🎉

