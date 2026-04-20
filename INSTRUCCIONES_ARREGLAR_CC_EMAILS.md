# 🎯 PASOS PARA ARREGLAR EMAIL CC - Guía Rápida

## Estado Actual

El código ya ha sido actualizado con:
- ✅ Fallback a `company.email_copia` si directorio vacío
- ✅ Mejor logging para debugging
- ✅ Manejo mejorado de emails en múltiples fuentes

**Pero necesitas:** Datos correctos en la BD

## 🚀 3 PASOS = LISTO

### PASO 1: Verificar BD en Railway (2 minutos)

Conecta a PostgreSQL en Railway y ejecuta:

```sql
-- Verificar si hay emails en tabla employees
SELECT COUNT(*) as empleados_con_correo,
       COUNT(CASE WHEN correo IS NULL OR correo = '' THEN 1 END) as empleados_sin_correo
FROM employees;

-- Ver empleados específicos sin correo
SELECT cedula, nombre, correo FROM employees 
WHERE correo IS NULL OR correo = '' LIMIT 5;

-- Ver si hay email_copia en companies
SELECT nombre, email_copia FROM companies WHERE email_copia IS NOT NULL LIMIT 5;

-- Ver si hay directorio de empresas
SELECT COUNT(*) FROM correos_notificacion 
WHERE area = 'empresas' AND activo = 1;
```

### PASO 2: Agregar Datos Faltantes (5 minutos)

**OPCIÓN A: Agregar email a empleados (RECOMENDADO)**

Para empleado específico:
```sql
UPDATE employees 
SET correo = 'nombre.apellido@incaneurobaeza.com' 
WHERE cedula = '1085043374'
  AND (correo IS NULL OR correo = '');
```

Para todos los empleados sin correo (usa email_copia de su empresa):
```sql
UPDATE employees e
SET correo = c.email_copia
FROM companies c
WHERE e.empresa_id = c.id
  AND (e.correo IS NULL OR e.correo = '')
  AND c.email_copia IS NOT NULL;
```

---

**OPCIÓN B: Agregar email_copia a empresas (FALLBACK)**

Para empresa específica:
```sql
UPDATE companies 
SET email_copia = 'soporte@incaneurobaeza.com' 
WHERE id = 14
  AND (email_copia IS NULL OR email_copia = '');
```

---

**OPCIÓN C: Poblar directorio correos_notificacion (ADMINISTRATIVO)**

Agregar directorio de empresas:
```sql
INSERT INTO correos_notificacion (email, area, company_id, activo, created_at, updated_at)
VALUES 
  ('rrhh@incaneurobaeza.com', 'empresas', 14, 1, NOW(), NOW()),
  ('soporte@incaneurobaeza.com', 'empresas', NULL, 1, NOW(), NOW());  -- NULL = general

-- Verificar que se insertó
SELECT * FROM correos_notificacion 
WHERE area = 'empresas' AND activo = 1;
```

### PASO 3: Deploy (2 minutos)

Hacer deploy a Railway con los cambios de código:

```bash
# En tu máquina local o en Railway:
cd c:\Users\david.baeza\Documents\BACKENDBETATWILEND

# Ver cambios
git status

# Agregar archivos modificados
git add app/validador.py app/email_service.py app/main.py

# Commit
git commit -m "fix: CC emails - agregar fallback a email_copia y mejorar logging"

# Push a main (se despliega automáticamente a Railway)
git push origin main
```

**Verificar en Railway:**
- Ve a https://railway.app/project/...
- Abre los logs de la aplicación
- Envía un formulario de incapacidad
- Verifica que aparezcan los logs mejorados

## 📋 QUÉ ESPERAR

### Logs correctos después del fix:

```
📧 CC empresa → 2 emails para company_id=14
     directorio[empresa]:cc@empresa.com
     fallback[email_copia]:soporte@incaneurobaeza.com

📋 DETALLES DEL EMAIL CC:
   TO (Formulario): usuario@example.com
   CC (Empleado BD): empleado@incaneurobaeza.com
   CC (Directorio): cc@empresa.com,soporte@incaneurobaeza.com
   ✅ CCs están configurados

📧 CC final: cc@empresa.com,soporte@incaneurobaeza.com
📧 Enviando via Service Account...
✅ Email enviado exitosamente a: To=[usuario@example.com] Cc=[cc@empresa.com, soporte@incaneurobaeza.com]
```

### Email recibido debería llegar a:
- ✅ usuario@example.com (TO - quien llena formulario)
- ✅ cc@empresa.com (CC - desde directorio)
- ✅ soporte@incaneurobaeza.com (CC - fallback email_copia)
- ✅ empleado@incaneurobaeza.com (CC - empleado BD)

## ❌ SI AÚN NO FUNCIONA

Si después del deploy aún no ves CCs:

1. **Revisar logs en Railway** → Copiar el log completo de 10 líneas antes y después de "📧 CC empresa"

2. **Ejecutar script de debug:**
   - Copiar [debug_emails_cc.py](debug_emails_cc.py) a Railway
   - Ejecutar: `python debug_emails_cc.py`
   - Compartir salida

3. **Verificar conectividad a BD:**
   ```sql
   -- En Railway PostgreSQL:
   SELECT version();  -- Debe retornar versión
   SELECT COUNT(*) FROM employees;  -- Debe retornar número
   ```

4. **Contactar soporte con:**
   - Salida de logs de Railway (últimas 30 líneas)
   - Resultado de query `SELECT * FROM correos_notificacion LIMIT 5;`
   - Email del formulario que probaste

## 📝 CHECKLIST FINAL

- [ ] Ejecuté queries de verificación en Railway
- [ ] Agregué datos en BD (al menos UNA opción A, B o C)
- [ ] Hice push de código a Railway
- [ ] Revisé logs de Railway después de enviar formulario
- [ ] Vi "CC final:" con emails en los logs
- [ ] Recibí email con CC en la dirección

¡Listo! 🎉

