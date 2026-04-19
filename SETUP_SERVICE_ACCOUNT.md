# 🔐 Configuración de Gmail con Service Account

## ¿Por qué Service Account?

✅ **No expira nunca** — A diferencia de OAuth 2.0 que requiere refresh  
✅ **No requiere autorización manual** — Sin ventanas de navegador  
✅ **Ideal para backend en producción** — Más robusto que contraseña de app  
✅ **Sin contraseña de app** — Más seguro  

---

## 📋 Pasos para Crear Service Account

### **1️⃣ Ir a Google Cloud Console**

```
https://console.cloud.google.com/iam-admin/serviceaccounts
```

### **2️⃣ Crear una Service Account**

- Click en **+ Crear una cuenta de servicio**
- Nombre: `incapacidades-backend` (o similar)
- Click en **Crear y continuar**

### **3️⃣ Habilitar Gmail API**

En el proyecto, ve a:  
```
https://console.cloud.google.com/apis/library/gmail.googleapis.com
```

- Click en **Habilitar**

### **4️⃣ Crear Clave JSON**

En la Service Account creada:
- Tab: **Claves**
- Click en **+ Agregar clave > Crear clave nueva**
- Tipo: **JSON**
- Click **Crear**

Se descargará automáticamente un archivo como:  
```
incapacidades-backend-XXXXX.json
```

### **5️⃣ Configurar Delegación de Dominio (Si es necesario)**

Si necesitas enviar desde una dirección específica (ej: `soporte@incaneurobaeza.com`):

#### **A. Habilitar delegación en la Service Account**

En Google Cloud Console → IAM → Service Account:
- Click en la cuenta de servicio
- Tab **Detalles**
- Click en **Mostrar la información avanzada**
- Copiar el **ID único del cliente**

#### **B. Configurar delegación en Google Workspace**

1. Ve a [Google Workspace Admin](https://admin.google.com)
2. Ve a **Seguridad → Acceso y control de datos → Controles de aplicaciones**
3. Click en **Agregar aplicación**
4. Pega el ID único del cliente
5. Permisos: `https://www.googleapis.com/auth/gmail.send`

---

## 📂 Configuración en el Backend

### **Opción 1: Variables de Entorno (Railway/Producción)**

En Railway:
1. Ve a tu servicio Backend
2. Tab **Variables**
3. Agregar:

```env
GOOGLE_SERVICE_ACCOUNT_FILE=/app/service_account.json
GOOGLE_SERVICE_ACCOUNT_USER=soporte@incaneurobaeza.com
GMAIL_USER=soporte@incaneurobaeza.com
```

4. Cargar el archivo JSON en el repositorio (o via secrets)

### **Opción 2: Local (Desarrollo)**

1. Guarda el JSON en la carpeta del backend:
```
BACKENDBETATWILEND/service_account.json
```

2. Configura `.env`:
```env
GOOGLE_SERVICE_ACCOUNT_FILE=service_account.json
GMAIL_USER=soporte@incaneurobaeza.com
```

---

## ✅ Verificar que Funciona

Ejecuta el backend y envía un email:

```bash
# Ver logs
tail -f logs/backend.log

# Buscar: "EMAIL ENVIADO VIA SERVICE ACCOUNT"
```

---

## 🔒 Seguridad

⚠️ **NUNCA comittear el JSON a Git** — Agrega a `.gitignore`:

```gitignore
service_account.json
*.json
!package.json
!tsconfig.json
```

✅ **En Railway**: Usa variables secretas encriptadas  
✅ **Permisos mínimos**: Solo `gmail.send` (no todo Google Drive)  

---

## 📞 Troubleshooting

| Problema | Solución |
|----------|----------|
| `Service Account no encontrado` | Verificar ruta en `GOOGLE_SERVICE_ACCOUNT_FILE` |
| `Error 403 - Permission denied` | Habilitar Gmail API en Google Cloud |
| `Error 400 - Invalid email` | Verificar `GMAIL_USER` es válido |
| `Error 403 - Delegated user not found` | Configurar delegación en Google Workspace Admin |

---

## 💡 Código en email_service.py

La función `_enviar_email_service_account()` ya está configurada para:

✅ Cargar el JSON automáticamente  
✅ Refrescar credenciales si es necesario  
✅ Delegar a un usuario específico (si está configurado)  
✅ Enviar con adjuntos y CCs  

**No necesita reintentos — es 100% confiable en producción.**
