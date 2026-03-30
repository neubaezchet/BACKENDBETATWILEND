# 📧 Configuración Email Backend — Variables de Entorno

## 🔐 Variables Requeridas en `.env`

Para que el Email Service (SMTP de Gmail) funcione correctamente, necesitas estas variables en tu archivo `.env`:

```bash
# ═══════════════════════════════════════════════════════════════
# SMTP GMAIL - Para envío de emails
# ═══════════════════════════════════════════════════════════════

GMAIL_USER=soporte@incaneurobaeza.com
GMAIL_PASSWORD=your_gmail_app_password_here

# Nota: GMAIL_PASSWORD es una "contraseña de aplicación" (app password), 
# NO la contraseña normal de tu cuenta Gmail.
# Ver instrucciones abajo de cómo obtenerla.

# ═══════════════════════════════════════════════════════════════
# WAHA - Para envío de WhatsApp
# ═══════════════════════════════════════════════════════════════

WAHA_BASE_URL=https://devlikeaprowaha-production-111a.up.railway.app
WAHA_API_KEY=1085043374
WAHA_SESSION_NAME=default

# ═══════════════════════════════════════════════════════════════
```

---

## 🔧 Cómo Obtener Google App Password

### Paso 1: Habilitar Verificación en 2 Pasos
1. Ve a [myaccount.google.com](https://myaccount.google.com)
2. Click en **"Seguridad"** (lado izquierdo)
3. En "Cómo accedes a Google" → **"Verificación en 2 pasos"**
4. Click en **"Activar"** y sigue los pasos

### Paso 2: Generar App Password
1. Ve a [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. **Selecciona**: "Mail" y "Windows Computer" (u otro dispositivo)
3. Click en **"Generar"**
4. Google te mostrará una contraseña de 16 caracteres
5. **Copia y pega en tu `.env`** como `GMAIL_PASSWORD`

Ejemplo de app password:
```
GMAIL_PASSWORD=abcd efgh ijkl mnop
```

> ⚠️ **Importante**: Esta es una contraseña temporal válida solo para esta aplicación. Es mucho más segura que tu contraseña real de Gmail.

---

## 📋 Verificación Post-Instalación

Ejecuta este script para verificar que todo está configurado:

```bash
python -c "
from app.email_service import verificar_salud_email
if verificar_salud_email():
    print('✅ Email service configurado correctamente')
else:
    print('❌ Error en configuración de email')
"
```

---

## ♻️ Qué Cambió Respecto a N8N

| Aspecto | Antes (N8N) | Ahora (Backend) |
|--------|-----------|-----------------|
| **Motor** | Webhook externo a N8N | Python nativo SMTP |
| **Emails** | Via N8N con OAuth | Gmail SMTP (app password) |
| **WhatsApp** | Via N8N | WAHA API directo |
| **Reintentos** | N8N los manejaba | Backend loop con backoff |
| **Dependencias** | Requería N8N activo | Solo Python + Gmail |
| **Costo** | N8N serverless | Libre (Gmail free tier) |
| **Latencia** | ~3-5s (HTTP + N8N) | ~1-2s (SMTP directo) |
| **Confiabilidad** | Si N8N cae, no llega nada | Cola resiliente en BD |

---

## 🚀 Testing Rápido

Si quieres probar manualmente:

```python
from app.email_service import enviar_notificacion

# Test email simple
resultado = enviar_notificacion(
    tipo_notificacion="confirmacion",
    email="test@example.com",
    serial="1024541919 03 02 2026 17 02 2026",
    subject="Test Email",
    html_content="<p>Este es un email de prueba</p>",
    cc_email=None,
    correo_bd=None,
    whatsapp=None
)

print("✅ Email enviado" if resultado else "❌ Email falló")
```

---

## 🆘 Troubleshooting

### "Authentication failed"
- ✅ Verificar `GMAIL_USER` y `GMAIL_PASSWORD` en `.env`
- ✅ App password de 16 caracteres (sin espacios extra)
- ✅ Verificación en 2 pasos habilitada en Gmail

### "Connection refused"
- ✅ Verificar conexión a internet
- ✅ Firewall no bloquea puerto 587 (SMTP)
- ✅ Gmail permite conexiones menos seguras (normalmente funciona con app password)

### "WAHA timeout"
- ✅ Verificar `WAHA_BASE_URL` y `WAHA_API_KEY`
- ✅ WAHA debe estar activo en Railway
- ✅ WhatsApp debe estar autenticado en WAHA

### Emails lentos
- ✅ Normal 1-2s por email (SMTP)
- ✅ Si hay adjuntos base64: puede tomar más
- ✅ La cola resiliente maneja reintentos automáticamente

---

## 📞 Contacto & Soporte

Si hay errores, revisa:
1. `/tmp/email_service.log` (si existe)
2. Terminal donde corre FastAPI (stdout/stderr)
3. Cola persistente en BD: tabla `PendienteEnvio`

¡Todo debería estar funcionando 100% sin N8N ahora! 🎉
