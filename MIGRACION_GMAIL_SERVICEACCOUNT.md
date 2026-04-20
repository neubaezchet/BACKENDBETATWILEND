# ✅ Migración completada: Gmail Personal → Service Account + Domain-Wide Delegation

**Fecha:** 19 de abril de 2026  
**Objetivo:** Eliminar dependencia de tokens OAuth que expiran, usar Service Account permanente

---

## 🎯 Cambios realizados:

### 1️⃣ `email_service.py` — Actualizado para SOLO usar Service Account

**Cambios:**
- ✅ Agregada validación que LANZA ERROR si Service Account no está disponible
- ✅ `_load_service_account_credentials()` ahora usa `.with_subject(GMAIL_USER)` para Domain-Wide Delegation
- ✅ Eliminado fallback a OAuth personal
- ✅ Mejor diagnóstico de errores (muestra solución si falla "Precondition check failed")

**Código:**
```python
# ✅ VALIDACIÓN: FUERZA SOLO SERVICE ACCOUNT (sin fallback a OAuth personal)
_SERVICE_ACCOUNT_AVAILABLE = bool(
    GOOGLE_SERVICE_ACCOUNT_KEY 
    or GOOGLE_CREDENTIALS_JSON 
    or GOOGLE_SHEETS_CREDENTIALS 
    or GOOGLE_SERVICE_ACCOUNT_FILE
)

if not _SERVICE_ACCOUNT_AVAILABLE:
    raise ValueError("Service Account NO disponible para Gmail")
```

---

### 2️⃣ Domain-Wide Delegation — Configurado en Google Workspace

**Ya realizado:**
- ✅ Client ID: `116056328142341258100`
- ✅ Scopes autorizados: `gmail.send`, `drive`
- ✅ El Service Account puede actuar como `soporte@incaneurobaeza.com`

**Referencia:** Google Admin Console → Security → API controls → Domain wide delegation

---

### 3️⃣ `validate_service_account.py` — Script de validación

Nuevo archivo para verificar que TODO está configurado antes de deploy.

```bash
python validate_service_account.py
```

---

### 4️⃣ `SETUP_DOMAIN_WIDE_DELEGATION.md` — Guía de configuración

Documento con pasos exactos para habilitar Domain-Wide Delegation.

---

## 🚀 Próximos pasos:

### 1. Verificar en Railway que tiene estas variables:

```env
GMAIL_USER=soporte@incaneurobaeza.com
GOOGLE_SERVICE_ACCOUNT_KEY={"client_id":"116056328142341258100", "client_email":"...", ...}
```

**⚠️ IMPORTANTE:** Debe ser la MISMA Service Account que usa para Drive (GOOGLE_CREDENTIALS_JSON)

### 2. Hacer deploy:

```bash
cd BACKENDBETATWILEND
git add .
git commit -m "Fix: Gmail solo con Service Account + Domain-Wide Delegation"
git push
```

### 3. Esperar a que Railway haga deploy (2-5 minutos)

### 4. Testear:

Sube una incapacidad. Deberías ver en los logs:

```
✅ Service Account con delegación activada → soporte@incaneurobaeza.com
📧 Enviando via Gmail API (Service Account)...
✅ Email enviado exitosamente via Service Account
```

---

## ✅ Beneficios:

| Antes (OAuth personal) | Ahora (Service Account) |
|---|---|
| ❌ Token expira cada 1 hora | ✅ Sin expiración |
| ❌ Requiere refresh manual | ✅ Automático y permanente |
| ❌ Dependencia de `authorize_gmail.py` | ✅ Completamente automatizado |
| ❌ Falla si olvidas refrescar | ✅ Falla si falta configuración (ERROR claro) |
| ❌ Problema en producción | ✅ Production-ready |

---

## 🔧 Si falla con error 400 "Precondition check failed":

Significa que Domain-Wide Delegation NO está correctamente autorizado.

**Solución:**
1. Ve a Google Admin Console
2. **Security** → **API controls** → **Manage Domain Wide Delegation**
3. Busca `116056328142341258100`
4. Confirma que tiene los scopes: `gmail.send`, `drive`
5. Si no está, agrégalo de nuevo

---

## 📝 Archivos modificados:

- ✅ `app/email_service.py` — Service Account + delegación
- ✅ `validate_service_account.py` — Script de validación (nuevo)
- ✅ `SETUP_DOMAIN_WIDE_DELEGATION.md` — Guía (nuevo)

---

## 🎓 Referencias técnicas:

- [Google Workspace Domain-Wide Delegation](https://developers.google.com/identity/protocols/oauth2/service-account#delegating_authority_to_the_application)
- [Gmail API Scopes](https://developers.google.com/gmail/api/auth/scopes)
- [Google Drive Shared Drives API](https://developers.google.com/drive/api/guides/about-shareddrives)
