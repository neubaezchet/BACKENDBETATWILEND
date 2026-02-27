# 🔧 FIX: Database Column Migration - intentos_incompletos + fecha_ultimo_incompleto

**Date:** 2026-02-27  
**Status:** ✅ Deployed to GitHub (Railway auto-redeploy in progress)

## Problem

The Railway PostgreSQL database was missing two columns that the backend code expected:
- `intentos_incompletos` (INTEGER) - Counter for incomplete case attempts
- `fecha_ultimo_incompleto` (TIMESTAMP) - Last timestamp when case was marked incomplete

This caused **500 Internal Server Error** on all `/validador/casos` endpoints:

```
psycopg2.errors.UndefinedColumn: column cases.intentos_incompletos does not exist
```

## Root Cause

The SQLAlchemy model in `app/database.py` (lines 139-140) had these columns defined:

```python
intentos_incompletos = Column(Integer, default=0)
fecha_ultimo_incompleto = Column(DateTime, nullable=True)
```

But the actual PostgreSQL `cases` table was missing these columns (likely created before these were added to the model).

## Solution

Added **auto-migration code** to the FastAPI startup event in `app/main.py` (lines 223-251).

This approach ensures:
1. ✅ Columns are added automatically on app startup
2. ✅ No manual database access needed from local machine
3. ✅ Works within Railway's internal network
4. ✅ Idempotent (safe to run multiple times - uses `IF NOT EXISTS`)

### Code Added (main.py startup_event)

```python
# ✅ COLUMNAS - Rastreo de intentos incompletos
"ALTER TABLE cases ADD COLUMN IF NOT EXISTS intentos_incompletos INTEGER DEFAULT 0;",
"ALTER TABLE cases ADD COLUMN IF NOT EXISTS fecha_ultimo_incompleto TIMESTAMP;",
```

These are executed as part of the existing migration list that runs on every startup.

## Deployment Timeline

| Time | Event |
|------|-------|
| 00:36 | Error logs show missing columns in Railway |
| 00:40 | Fix implemented in app/main.py |
| 00:45 | Committed to git: `ca4714d` |
| 00:46 | Pushed to GitHub (origin/main) |
| ~00:50 | Railway detects change and triggers auto-redeploy |
| ~01:00 | Backend restarts → migration runs → columns created ✅ |

## What Happens On Next Deploy

When Railway restarts the backend service:

1. **Startup event fires** (`@app.on_event("startup")`)
2. **Auto-migration runs** (`init_db()` + ALTER TABLE statements)
3. **Columns are created** (if they don't exist)
4. **API is ready** ✅ All endpoints work normally

## Verification

Once Railway redeploys, the error should resolve:

```bash
# Before: ❌ 500 Error
GET /validador/casos?empresa=all&estado=NUEVO

# After: ✅ 200 OK
GET /validador/casos?empresa=all&estado=NUEVO
```

Test by checking if you can access the case listing endpoint.

## Files Modified

- `app/main.py` - Added 2 ALTER TABLE statements to auto-migration (lines 245-246)
- `migrate_add_missing_columns.py` - Created (alternate manual migration script)

## Related Documentation

See: [CAMBIOS_RUPTURA_PRORROGA.md](CAMBIOS_RUPTURA_PRORROGA.md) for context on the broader feature implementation.

---

**Next Steps:**
- ✅ Wait for Railway deployment to complete (~5-10 min)
- ✅ Test `/validador/casos` endpoint
- ✅ Verify badge counter works in frontend
- ✅ Check sync properly populates intentos_incompletos
