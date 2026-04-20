# 🔧 FIX: Email CC no se está enviando - Solución Completa

## 📋 Problema Identificado

Los emails de confirmación se envían al usuario que llena el formulario, pero **NO se envían en CC a**:
1. ❌ Email del empleado en la BD
2. ❌ Emails configurados en el directorio de empresas

**Error en logs:**
```
⚠️ CC empresa → Sin emails para company_id=14
📧 CC final: N/A
```

## 🔍 Causa Raíz

1. **Campo `correo` del empleado está VACÍO** en tabla `employees`
   - O el campo `correo` no tiene email para ese empleado
   - El sistema intenta usar `correo_bd = empleado_bd.correo` pero es vacío

2. **No hay emails en el directorio de empresas**
   - La tabla `correos_notificacion` no tiene registros para esa empresa
   - Cuando busca `area='empresas'` con `company_id=14`, no encuentra nada

## ✅ SOLUCIÓN (Orden de Prioridad)

### PASO 1: Verificar BD
Ejecuta estas queries en la BD (Railway):

```sql
-- Revisar empleados sin email en campo correo
SELECT cedula, nombre, correo, empresa_id FROM employees 
WHERE correo IS NULL OR correo = '' 
LIMIT 20;

-- Revisar qué empresas NO tienen emails en directorio
SELECT c.id, c.nombre, COUNT(e.id) as empleados
FROM companies c
LEFT JOIN employees e ON e.empresa_id = c.id
WHERE c.id NOT IN (
    SELECT DISTINCT company_id FROM correos_notificacion 
    WHERE area = 'empresas' AND company_id IS NOT NULL AND activo = 1
)
GROUP BY c.id;
```

**Archivo completo:** [FIX_CC_EMAILS_QUERIES.sql](FIX_CC_EMAILS_QUERIES.sql)

### PASO 2: Arreglar datos en BD

**OPCIÓN A: Agregar email a empleados**
```sql
-- Para empleado específico:
UPDATE employees 
SET correo = 'empleado@incaneurobaeza.com' 
WHERE cedula = '1085043374';

-- O agregar email_copia en companies si es fallback:
UPDATE companies 
SET email_copia = 'rrhh@incaneurobaeza.com' 
WHERE id = 14;
```

**OPCIÓN B: Poblar tabla correos_notificacion (directorio de empresas)**
```sql
-- Ver qué hay en correos_notificacion actualmente:
SELECT * FROM correos_notificacion WHERE area = 'empresas' AND activo = 1;

-- Agregar email CC para empresa 14:
INSERT INTO correos_notificacion (email, area, company_id, activo, created_at)
VALUES ('soporte@incaneurobaeza.com', 'empresas', 14, 1, NOW());
```

### PASO 3: Mejorar el código (Ya está casi listo)

El código en `app/main.py` línea 1502-1511 ya obtiene:
- `correo_empleado` = email del empleado
- `cc_empresa` = emails del directorio

Y en `app/email_service.py` línea 260-305 construye la lista de CC.

**Cambios adicionales necesarios:**

1. **En `email_service.py`**: Agregar fallback a `company.email_copia` si directorio está vacío
2. **En `validador.py`**: Mejorar `obtener_emails_empresa_directorio()` para incluir fallback
3. **En `main.py`**: Agregar logging para saber qué emails se están usando

## 🚀 Implementación del Fix (CÓDIGO)

### Cambio 1: Mejorar `obtener_emails_empresa_directorio()` en `validador.py`

```python
def obtener_emails_empresa_directorio(company_id, db=None):
    """Obtiene emails CC por empresa.
    Orden: 1) Directorio correos_notificacion, 2) email_copia de Company
    """
    emails = set()
    close_db = False
    try:
        if not db:
            from app.database import SessionLocal
            db = SessionLocal()
            close_db = True
        
        # Fuente 1: tabla correos_notificacion (directorio admin)
        correos = db.query(CorreoNotificacion).filter(
            CorreoNotificacion.area == 'empresas',
            CorreoNotificacion.activo == True,
            (CorreoNotificacion.company_id == None) | (CorreoNotificacion.company_id == company_id)
        ).all()
        
        for c in correos:
            if c.email and c.email.strip():
                emails.add(c.email.strip().lower())
        
        # Fuente 2: email_copia de Company (fallback)
        if company_id:
            company = db.query(Company).filter(Company.id == company_id).first()
            if company and company.email_copia:
                for em in company.email_copia.split(","):
                    em = em.strip().lower()
                    if em and "@" in em:
                        emails.add(em)
        
        emails = list(emails)
        if emails:
            print(f"📧 CC empresa → {len(emails)} emails: {emails}")
        else:
            print(f"⚠️ CC empresa → Sin emails para company_id={company_id}")
        
        return emails
    except Exception as e:
        print(f"⚠️ Error obteniendo emails CC: {e}")
        return []
    finally:
        if close_db and db:
            db.close()
```

### Cambio 2: Mejorar fallback en `email_service.py` línea ~280-305

En la sección `enviar_notificacion()`, después de construir `cc_list`, agregar:

```python
# Si cc_list está vacío, intentar obtener desde company.email_copia
if not cc_list and serial and serial != 'AUTO':
    try:
        from app.database import SessionLocal, Case, Company
        _db = SessionLocal()
        caso = _db.query(Case).filter(Case.serial == serial).first()
        
        if caso and caso.company_id:
            company = _db.query(Company).filter(Company.id == caso.company_id).first()
            if company and company.email_copia:
                for em in company.email_copia.split(','):
                    em = em.strip().lower()
                    if em and "@" in em and em != email.lower():
                        cc_list.append(em)
                        print(f"📧 CC desde Company.email_copia: {em}")
        
        _db.close()
    except Exception as e:
        print(f"⚠️ Error en fallback email_copia: {e}")
```

### Cambio 3: Agregar logging en main.py línea ~1630

```python
# ANTES de llamar a enviar_notificacion():
print(f"\n📧 CONFIGURACIÓN DE EMAIL CC:")
print(f"   Correo del empleado (BD): {correo_empleado or '❌ VACÍO'}")
print(f"   Correos del directorio: {cc_empresa or '❌ VACÍO'}")
```

## 📝 Checklist de Solución

- [ ] Ejecutar queries de verificación en BD (Railway)
- [ ] Agregar emails a tabla `employees.correo` o `companies.email_copia`
- [ ] Aplicar Cambios 1-3 en código (o esperar siguiente deploy)
- [ ] Verificar que emails de CC se reciben en notificaciones
- [ ] Documentar en `CorreoNotificacion` todos los emails de dirección

## 🔗 Archivos Relacionados

- [FIX_CC_EMAILS_QUERIES.sql](FIX_CC_EMAILS_QUERIES.sql) - Queries de verificación
- [app/email_service.py](app/email_service.py#L260-L305) - Construcción de CC
- [app/validador.py](app/validador.py#L110-L145) - Obtención de emails directorio
- [app/main.py](app/main.py#L1502-L1630) - Obtención de emails antes de enviar

