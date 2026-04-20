# 🔐 Configurar Domain-Wide Delegation para Service Account

**Objetivo:** Permitir que el Service Account envíe emails como `soporte@incaneurobaeza.com` sin expiración de tokens.

---

## 1️⃣ Obtener el Client ID del Service Account

En tu variable de entorno `GOOGLE_SERVICE_ACCOUNT_KEY` (Railway/Vercel), el JSON debe tener:

```json
{
  "client_id": "XXXXXXXXXXXXXX.apps.googleusercontent.com",
  "client_email": "inca-backend@mi-proyecto.iam.gserviceaccount.com",
  ...
}
```

**Copia el `client_id`** (el número largo)

---

## 2️⃣ Ir a Google Admin Console

1. Ve a https://admin.google.com/
2. Inicia sesión con tu cuenta de Google Workspace (admin)
3. Busca **Security** en el menú (o esquina superior derecha → búsqueda rápida)

---

## 3️⃣ Habilitar Domain-Wide Delegation

1. **Security** → **API controls** → **Manage Domain Wide Delegation**
2. Haz clic en **Add new** (o **Agregar nuevo**)
3. Pega el **Client ID** (del paso 1)
4. En **OAuth scopes**, pega estos scopes (separados por coma):

```
https://www.googleapis.com/auth/gmail.send,https://www.googleapis.com/auth/drive
```

5. Haz clic en **Authorize** (o **Autorizar**)

✅ **¡Listo! Domain-Wide Delegation está configurado**

---

## 4️⃣ Verificar que Railway/Vercel tenga las variables correctas

En tu deploy (Railway), asegúrate de que tienes:

```env
GMAIL_USER=soporte@incaneurobaeza.com
GOOGLE_SERVICE_ACCOUNT_KEY={"client_id":"...", "client_email":"...", ...}
```

---

## 5️⃣ Testear el envío

Cuando ejecutes el backend, deberías ver:

```
✅ Service Account con delegación activada → soporte@incaneurobaeza.com
📧 Enviando via Gmail API (Service Account)...
✅ Email enviado exitosamente via Service Account
```

---

## ⚠️ Si aún falla con error 400

Si ves:
```
❌ Error Gmail API 400: Precondition check failed
```

Significa que:
- [ ] Domain-Wide Delegation NO está autorizado en Google Admin
- [ ] El `client_id` no es correcto
- [ ] El usuario `soporte@incaneurobaeza.com` no existe en tu Workspace

**Verifica:**
1. Vuelve a Google Admin Console
2. **Manage Domain Wide Delegation** → busca tu Service Account
3. Confirma que está en la lista con los scopes correctos

---

## 📝 Referencias

- [Google Workspace Domain-Wide Delegation](https://developers.google.com/identity/protocols/oauth2/service-account#delegating_authority_to_the_application)
- [Gmail API Scopes](https://developers.google.com/gmail/api/auth/scopes)
