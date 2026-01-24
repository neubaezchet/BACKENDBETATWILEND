# 🚀 Migración a Railway PostgreSQL - Enero 2026

## ✅ Cambios Realizados

### 1. **Base de Datos**
- ❌ **ELIMINADO**: Neon PostgreSQL
- ✅ **NUEVO**: Railway PostgreSQL
  ```
  postgresql://postgres:oVNybDmnUBecMCMSDKNTLzAuUzQMpdKW@postgres.railway.internal:5432/railway
  ```

### 2. **Sistema de Emails**
- ❌ **ELIMINADO**: Brevo (Sendinblue)
  - Removido `sib-api-v3-sdk==7.6.0` de requirements.txt
  - Eliminadas todas las referencias en el código
  - Removidos imports de `sib_api_v3_sdk`
- ✅ **CONSOLIDADO**: N8N para todos los emails
  - URL: `https://railway-n8n-production-5a3f.up.railway.app/webhook/incapacidades`
  - Maneja emails transaccionales, recordatorios, alertas
  - Envía WhatsApp automáticamente

### 3. **Archivos Modificados**

#### `.env`
```diff
- DATABASE_URL=postgresql://neondb_owner:npg_...@ep-lingering-star-afnuuy2c-pooler.c-2.us-west-2.aws.neon.tech/neondb?sslmode=require
+ DATABASE_URL=postgresql://postgres:oVNybDmnUBecMCMSDKNTLzAuUzQMpdKW@postgres.railway.internal:5432/railway
```

#### `requirements.txt`
```diff
- # Emails
- sib-api-v3-sdk==7.6.0
```

#### `app/validador.py`
```diff
- import sib_api_v3_sdk
```

#### `app/scheduler_recordatorios.py`
```diff
- # 50+ líneas de código Brevo eliminadas
+ # Ahora usa solo enviar_a_n8n()
```

---

## 🔄 Flujo Actual de Emails

```
Backend (FastAPI)
    ↓
n8n_notifier.py (enviar_a_n8n)
    ↓
N8N Webhook (Railway)
    ↓
├─ Email vía Brevo/Gmail
├─ WhatsApp vía Evolution API
└─ Copias automáticas (empresa + empleado)
```

---

## 📦 Dependencias Actuales

### Backend Python
- ✅ FastAPI + Uvicorn
- ✅ SQLAlchemy + psycopg2-binary
- ✅ Google Drive API
- ✅ Anthropic (Claude IA)
- ✅ Pandas + OpenPyXL
- ✅ PyMuPDF (PDFs)
- ✅ APScheduler
- ❌ ~~Brevo~~ (eliminado)

### Servicios Externos
- ✅ Railway PostgreSQL (nueva DB)
- ✅ N8N (Railway) - Emails + WhatsApp
- ✅ Google Drive - Almacenamiento
- ✅ Evolution API - WhatsApp

---

## 🧪 Testing Requerido

### 1. **Conexión a Base de Datos**
```bash
python migrate_database.py
```
Verificar que se conecte a Railway PostgreSQL correctamente.

### 2. **Envío de Emails**
- Crear un caso de prueba
- Validar que N8N reciba el webhook
- Confirmar que el email llegue
- Verificar que WhatsApp se envíe

### 3. **Recordatorios Automáticos**
- Verificar que `scheduler_recordatorios.py` funcione sin Brevo
- Confirmar que use `enviar_a_n8n()`

### 4. **Frontend**
- **repogemin**: Verificar timeout de 60s (línea 472)
- **portal-neurobaeza**: Confirmar que recibe respuestas de n8n

---

## 📋 Checklist de Migración

- [x] Actualizar DATABASE_URL en .env
- [x] Eliminar sib-api-v3-sdk de requirements.txt
- [x] Remover imports de Brevo
- [x] Limpiar código obsoleto de scheduler_recordatorios
- [x] Verificar que todo use enviar_a_n8n()
- [ ] Migrar datos de Neon → Railway (si necesario)
- [ ] Probar envío de emails
- [ ] Probar recordatorios automáticos
- [ ] Verificar frontend repogemin (timeout)
- [ ] Verificar portal-neurobaeza

---

## 🚨 Importante

### Variables de Entorno Requeridas
```env
DATABASE_URL=postgresql://postgres:oVNybDmnUBecMCMSDKNTLzAuUzQMpdKW@postgres.railway.internal:5432/railway
N8N_WEBHOOK_URL=https://railway-n8n-production-5a3f.up.railway.app/webhook/incapacidades
ADMIN_TOKEN=0b9685e9a9ff3c24652acaad881ec7b2b4c17f6082ad164d10a6e67589f3f67c
```

### Carpeta Obsoleta
- `BACKENDBETATWILEND/neon/` - Puede eliminarse (solo tiene un archivo vacío)

---

## 📞 Soporte

Si algo falla:
1. Verificar logs de Railway (Backend + N8N)
2. Revisar que DATABASE_URL sea correcta
3. Confirmar que N8N esté corriendo
4. Validar que todos los webhooks estén activos

---

**Fecha de migración**: 24 de enero, 2026
**Responsable**: Sistema actualizado automáticamente
