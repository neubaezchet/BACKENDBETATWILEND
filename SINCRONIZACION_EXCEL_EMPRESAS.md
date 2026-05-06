# 📋 Sincronización Excel ↔ Base de Datos Railway
## Flujo de Desactivación de Empresas y Empleados

---

## 📌 Objetivo Principal
**Lo que pasa en el Excel pasa en la Base de Datos**

Cuando se elimina una fila del Excel (empresa o empleado), en lugar de eliminar físicamente los registros de la BD, se **marcan como desactivados**. Esto permite:
- ✅ Reactivar si se agregan de nuevo al Excel
- ✅ Mantener historial y referencias
- ✅ Recuperar datos si fue error

---

## 🔄 Flujo de Sincronización

### **ANTES (Sin sincronización de desactivaciones)**
```
Excel: Empresa A, B, C
BD:    Empresa A, B, C, X (X no está en Excel)

Sync ejecutado ❌ 
→ X sigue visible en admin
```

### **AHORA (Con sincronización completa)**
```
Excel: Empresa A, B, C
BD:    Empresa A (activa), B (activa), C (activa), X (desactivada)

Sync ejecutado ✅
→ X NO aparece en admin
→ Si vuelve A aparecer al Excel: se reactiva automáticamente
```

---

## 🛠️ Cambios Implementados

### **1. SINCRONIZACIÓN (Backend: `sync_excel.py`)**

#### **Función: `sincronizar_excel_completo()`**

**Paso 1: Procesar Hoja 1 (Empleados)**
```python
# Recolectar todas las cédulas y empresas del Excel
cedulas_excel = {cedula1, cedula2, cedula3, ...}
empresas_excel = {empresa_A, empresa_B, empresa_C, ...}

# Para cada empleado en Excel:
# - Crear o actualizar
# - Si estaba desactivado → reactivar

# Para empleados NOT en Excel:
# - Marcar como activo = False (desactivados)
```

**Paso 2: Procesar Hoja 2 (Emails de copia)**
```python
# Recolectar empresas de Hoja 2
empresas_en_hoja2 = {empresa_A, empresa_X, ...}

# Combinar empresas de ambas hojas
todas_empresas_excel = empresas_excel | empresas_en_hoja2

# Para cada empresa:
# - Si está en Excel → activa = True
# - Si NO está en Excel → activa = False
```

**Paso 3: Desactivar Empresas**
```python
# Para cada empresa en BD:
#   Si (nombre NOT en Excel) Y (activa == True):
#       → activa = False (desactivada)
#       → print("Empresa desactivada: {nombre}")
```

#### **Logs de Ejemplo**
```
🔄 Iniciando sync Google Sheets a PostgreSQL...

📊 Procesando Hoja 1: Empleados...
📊 Empleados en Excel: 45 filas
✅ Empleados: 3 nuevos, 2 actualizados, 1 desactivado

📊 Procesando Hoja 2: Emails de Copia...
📊 Empresas con emails: 12 filas
🔄 Empresa XYZ reactivada desde Hoja 2
✅ Emails de copia: 2 actualizados

🏢 Procesando desactivación de empresas...
✅ Empresa desactivada: Empresa Vieja
✅ Empresa desactivada: Prueba Temporal
✅ Empresas: 2 desactivadas

✅ Sync completado
```

---

## 🔐 Filtros en Backend

### **admin.py**

| Endpoint | Cambio |
|----------|--------|
| `GET /admin/empresas` | ✅ Filtra `activa == True` |
| `GET /admin/correos` | ✅ Busca empresa CON validación de `activa` |
| `POST /admin/correos` | ✅ Valida que empresa esté `activa` |

**Ejemplo - Filtro en GET /admin/empresas:**
```python
empresas = db.query(Company).filter(
    Company.activa == True
).order_by(Company.nombre).all()
```

### **alertas.py**

| Endpoint | Cambio |
|----------|--------|
| `GET /alertas-180/empresas` | ✅ Filtra `activa == True` |
| `GET /alertas-180/emails` | ✅ Busca empresa CON validación de `activa` |
| `POST /alertas-180/emails` | ✅ Valida que empresa esté `activa` |
| `GET /alertas-180/correos-notificacion` | ✅ Busca empresa CON validación de `activa` |

---

## 🎨 Frontend (admin-neurobaeza)

### **ConnectionDirectory.jsx**
```javascript
// El endpoint ya filtra por activas
const data = await getEmpresas()
// Retorna: { empresas: [{ id, nombre, ... }] }
// Solo empresas con activa == True
```

### **EmailDirectory.jsx**
```javascript
// También usa el mismo endpoint
const [empresas, setEmpresas] = useState([])
// Solo muestra empresas activas
```

**Resultado Visual:**
- ✅ Empresas activas aparecen en dropdowns
- ❌ Empresas desactivadas NO aparecen
- 🔄 Si se vuelven a agregar al Excel → Reaparecen

---

## 🧪 Prueba del Sistema

### **Escenario 1: Eliminar empresa del Excel**
```
1. Excel tiene: Empresa A, B, C
2. Ejecutar sync
3. Resultado: Todas visibles ✅

4. ELIMINAR Empresa C del Excel
5. Ejecutar sync
6. Resultado: 
   - BD: A(activa), B(activa), C(DESACTIVADA)
   - Admin: Solo A y B ✅
```

### **Escenario 2: Restaurar empresa**
```
1. Empresa C estaba desactivada
2. Agregar Empresa C nuevamente al Excel
3. Ejecutar sync
4. Resultado:
   - BD: C(activa) ← reactivada
   - Admin: A, B, C ✅
```

### **Escenario 3: Error en sync**
```
1. Sync falla por timeout
2. Datos originales intactos (soft delete)
3. Reintentar sync
4. Resultado: Se recupera automáticamente ✅
```

---

## 📊 Estructura de Datos

### **Tabla: `companies`**
```sql
CREATE TABLE companies (
    id          INTEGER PRIMARY KEY,
    nombre      VARCHAR(200) UNIQUE NOT NULL,
    nit         VARCHAR(50) UNIQUE,
    email_copia VARCHAR(500),
    activa      BOOLEAN DEFAULT TRUE,  -- ✅ CLAVE: Soft delete
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP
);
```

### **Tabla: `employees`**
```sql
CREATE TABLE employees (
    id          INTEGER PRIMARY KEY,
    cedula      VARCHAR(50) UNIQUE NOT NULL,
    nombre      VARCHAR(200) NOT NULL,
    company_id  INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    activo      BOOLEAN DEFAULT TRUE,  -- ✅ CLAVE: Soft delete
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP
);
```

---

## ⚙️ Configuración del Scheduler

**Archivo: `sync_scheduler.py`**

El sync se ejecuta automáticamente cada **60 segundos**:

```python
@scheduler.scheduled_job('interval', seconds=60, id='sync_excel_job')
def job_sync_excel():
    print("🔄 Ejecutando sync automático...")
    sincronizar_excel_completo()
```

---

## 🔍 Verificación

### **Querys útiles para verificar estado**

```sql
-- Empresas activas
SELECT nombre, activa FROM companies WHERE activa = TRUE;

-- Empresas desactivadas
SELECT nombre, activa FROM companies WHERE activa = FALSE;

-- Empleados desactivados por empresa
SELECT e.nombre, c.nombre, e.activo 
FROM employees e 
JOIN companies c ON e.company_id = c.id 
WHERE e.activo = FALSE;

-- Total de cambios en última sincronización
SELECT COUNT(*) as desactivadas FROM companies WHERE updated_at > NOW() - INTERVAL '5 minutes';
```

---

## ✅ Checklist de Validación

- ✅ Sync desactiva empresas no presentes en Excel
- ✅ Sync desactiva empleados no presentes en Excel
- ✅ Admin solo muestra empresas activas
- ✅ Endpoint `/admin/empresas` filtra `activa == True`
- ✅ Endpoint `/alertas-180/empresas` filtra `activa == True`
- ✅ Empresas se reactivan si vuelven al Excel
- ✅ Errores de sync no pierden datos
- ✅ Soft delete (no se eliminan datos, solo se marcan)

---

## 📝 Notas Importantes

1. **Soft Delete vs Hard Delete:**
   - ✅ Soft delete (desactivar) es más seguro
   - ❌ Hard delete (eliminar) perderí​a referencias

2. **Reactivación Automática:**
   - Si una empresa reaparece al Excel
   - Automáticamente se reactiva `activa = True`
   - Retorno a normalidad sin intervención manual

3. **Sincronización Atómica:**
   - Si falla una parte del sync: `db.rollback()`
   - No queda en estado inconsistente

4. **Auditoría y Logs:**
   - Cada cambio se registra en `updated_at`
   - Se puede rastrear quién/cuándo se desactivó

---

**Última actualización:** 6 de mayo de 2026
**Responsable:** Sistema de Sincronización Automática
**Estado:** ✅ Implementado y Testeado
