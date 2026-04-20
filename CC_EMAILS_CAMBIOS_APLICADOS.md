# ✅ CC EMAILS - CAMBIOS APLICADOS (27/02/2026)

## 📝 Resumen de Cambios

Se han implementado 3 mejoras críticas para **arreglar email CC que no se estaban enviando**:

### 1️⃣ Mejorada función `obtener_emails_empresa_directorio()` - `app/validador.py`

**Cambios:**
- ✅ Agregado fallback a `Company.email_copia` si directorio vacío
- ✅ Mejorado logging para mostrar fuente de cada email (directorio vs fallback)
- ✅ Diferencia entre emails específicos de empresa vs generales

**Resultado:**
```
Antes: ⚠️ CC empresa → Sin emails para company_id=14
Ahora: 📧 CC empresa → 2 emails para company_id=14
       directorio[empresa]:cc@empresa.com
       fallback[email_copia]:soporte@empresa.com
```

### 2️⃣ Agregado fallback en construcción de CC - `app/email_service.py`

**Ubicación:** Líneas 300-325 (después de intentar inyectar directorio)

**Cambios:**
- ✅ Si `cc_list` está vacío después de buscar en directorio
- ✅ Intenta obtener `Company.email_copia` como último recurso
- ✅ Evita que el email se envíe sin CCs cuando la DB está mal configurada

**Código agregado:**
```python
# FALLBACK: Si cc_list vacío, intentar Company.email_copia
if not cc_list and serial and serial != 'AUTO':
    try:
        # Obtener email_copia de la empresa
        # Si existe, agregarlo a cc_list
    except Exception as e:
        print(f"⚠️ Error en fallback email_copia: {e}")
```

### 3️⃣ Mejorado logging en envío de confirmación - `app/main.py`

**Ubicación:** Líneas 1603-1612

**Cambios:**
- ✅ Muestra explícitamente qué emails se están pasando a `enviar_notificacion()`
- ✅ Advertencia clara si los CCs están vacíos
- ✅ Facilita debugging de problemas de CC

**Resultado:**
```
📋 DETALLES DEL EMAIL CC:
   TO (Formulario): usuario@gmail.com
   CC (Empleado BD): empleado@incaneurobaeza.com
   CC (Directorio): rrhh@incaneurobaeza.com,soporte@incaneurobaeza.com
```

## 🔍 Cómo funciona ahora

### Flujo de búsqueda de CCs (en orden):

1. **En `main.py` línea 1502**: Se obtiene `correo_empleado = empleado_bd.correo`
2. **En `main.py` línea 1505-1511**: Se obtiene lista de emails del directorio vía `obtener_emails_empresa_directorio()`
3. **En `email_service.py` línea 260-276**: Se construye `cc_list` con ambos valores
4. **En `email_service.py` línea 300-325 (NUEVO)**: Si `cc_list` vacío, intenta fallback a `company.email_copia`
5. **En `email_service.py` línea 470**: Se agrega header `Cc` al mensaje MIME

## 📋 Checklist de verificación

Para confirmar que los cambios funcionan:

### ✅ Base de Datos debe tener:

**Opción A: Tabla `employees` con correos**
```sql
SELECT cedula, nombre, correo FROM employees 
WHERE correo IS NOT NULL AND correo != '' LIMIT 5;
-- Debe mostrar al menos algunos empleados con email
```

**Opción B: Tabla `companies` con `email_copia`**
```sql
SELECT id, nombre, email_copia FROM companies 
WHERE email_copia IS NOT NULL LIMIT 5;
-- Debe mostrar al menos algunas empresas con email_copia
```

**Opción C: Tabla `correos_notificacion` con directorio**
```sql
SELECT email, company_id FROM correos_notificacion 
WHERE area = 'empresas' AND activo = 1 LIMIT 5;
-- Debe mostrar al menos algunos emails en directorio
```

**Si NO hay datos en ninguna opción, agregar:**
```sql
-- Opción: Agregar email_copia a la empresa
UPDATE companies SET email_copia = 'rrhh@incaneurobaeza.com' WHERE id = 14;

-- O: Agregar email al empleado
UPDATE employees SET correo = 'empleado@incaneurobaeza.com' WHERE cedula = '1085043374';

-- O: Agregar al directorio de empresas
INSERT INTO correos_notificacion (email, area, company_id, activo)
VALUES ('soporte@incaneurobaeza.com', 'empresas', 14, 1);
```

### ✅ Logs deben mostrar:

**Antes (PROBLEMA):**
```
⚠️ CC empresa → Sin emails para company_id=14
📋 DETALLES DEL EMAIL CC:
   TO: usuario@gmail.com
   CC (Empleado BD): ❌ VACÍO
   CC (Directorio): ❌ VACÍO
📧 CC final: N/A
```

**Después (ARREGLADO):**
```
📧 CC empresa → 2 emails para company_id=14
     directorio[empresa]:cc@empresa.com
     fallback[email_copia]:rrhh@empresa.com
📋 DETALLES DEL EMAIL CC:
   TO: usuario@gmail.com
   CC (Empleado BD): empleado@empresa.com
   CC (Directorio): cc@empresa.com,rrhh@empresa.com
📧 CC final: cc@empresa.com,rrhh@empresa.com
📧 Enviando via Service Account...
✅ Email enviado exitosamente
```

## 🚀 Próximos Pasos

1. **Deploy a Railway:**
   ```bash
   git add app/validador.py app/email_service.py app/main.py
   git commit -m "fix: CC emails - agregar fallback y mejorar logging"
   git push origin main
   ```

2. **Verificar en Railway:**
   - Enviar formulario de incapacidad
   - Revisar logs en Railway
   - Confirmar que email CC se recibe en dirección

3. **Si aún no funciona:**
   - Ejecutar queries SQL de [FIX_CC_EMAILS_QUERIES.sql](FIX_CC_EMAILS_QUERIES.sql)
   - Verificar si BD tiene datos en `employees.correo`, `companies.email_copia` o `correos_notificacion`
   - Agregar datos según sea necesario

## 📁 Archivos Modificados

| Archivo | Líneas | Cambios |
|---------|--------|---------|
| [app/validador.py](app/validador.py#L110-L158) | 110-158 | Mejorada obtener_emails_empresa_directorio() con fallback |
| [app/email_service.py](app/email_service.py#L300-L325) | 300-325 | Agregado fallback a company.email_copia |
| [app/main.py](app/main.py#L1603-L1612) | 1603-1612 | Agregado logging detallado de CCs |

## 🔗 Archivos de Apoyo

- [FIX_CC_EMAILS_QUERIES.sql](FIX_CC_EMAILS_QUERIES.sql) - Queries para verificar BD
- [SOLUCION_CC_EMAILS_INCOMPLETO.md](SOLUCION_CC_EMAILS_INCOMPLETO.md) - Documentación detallada

