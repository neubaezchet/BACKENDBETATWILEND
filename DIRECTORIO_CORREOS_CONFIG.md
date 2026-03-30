# 📧 Configuración de Directorio de Correos — IncaNeurobaeza

## 🏆 Resumen Ejecutivo

El sistema tiene un **directorio centralizado** de correos que se configura en el **panel admin**:

```
Portal Admin → Settings → Correos de Notificación
```

1. **Correos de Empresa**: Se envían en CC a TODOS los correos de inicapacidad
2. **Correos de Presunto Fraude**: Se envían cuando hay sospecha de fraude (DERIVADO_TTHH)

---

## 📋 Estructura del Directorio

Hay **3 áreas** en el directorio:

| Área | Función | Destinatario | Cuándo se usa |
|------|---------|--------------|---------------|
| **empresas** | Correos de cada institución | Reciben CC en TODOS los correos de sus empleados | Confirmación, incompleta, ilegible, completa, etc. |
| **presunto_fraude** | Área que investiga fraude | Recibe REPORTE detallado + sospecha | DERIVADO_TTHH (presunto fraude) |
| **alerta_180** | Alertas de casos en 180d | Notificación de riesgo prórroga | Automático c/ scheduler |

---

## 🔐 Cómo Configurar en Admin Panel

### 1️⃣ Agregar Correos de Empresa

**Ruta**: `/admin/configuracion/correos-notificacion`

**Paso 1**: Click `+ Nuevo Correo`

```
Área:              empresas
Empresa:           [Selecciona la empresa]
Correo:            rrhh@empresa.com
Activo:            ✅

Ejemplo:
Área:              empresas
Empresa:           Industrias Acme
Correo:            rrhh@acmegroup.com, eps-notificaciones@acmegroup.com
Activo:            ✅
```

**Resultado**: Cada correo de incapacidad de un empleado de Acme llevará en CC a `rrhh@acmegroup.com`

---

### 2️⃣ Agregar Correos de Presunto Fraude

**Ruta**: Mismo `/admin/configuracion/correos-notificacion`

**Paso 1**: Click `+ Nuevo Correo`

```
Área:              presunto_fraude
Empresa:           [Selecciona la empresa]
Correo:            fraude@empresa.com
Activo:            ✅

Ejemplo Global (para TODAS las empresas):
Área:              presunto_fraude
Empresa:           [Vacío]
Correo:            fraude-central@incaneurobaeza.com
Activo:            ✅

Ejemplo por Empresa:
Área:              presunto_fraude
Empresa:           Industrias Acme
Correo:            investigacion.acme@acmegroup.com
Activo:            ✅
```

---

## 🔄 Flujo de Correos — Cómo Funcionan los CCs

### Flujo Estándar (Confirmación, Incompleta, Validada, etc.)

```
Usuario envía incapacidad
         ↓
Backend detecta empresa del empleado
         ↓
Busca correos en directorio área "empresas" para esa empresa
         ↓
CORREO → Al empleado (TO)
         CC → Correos de empresa
         CC → Correo de empresa global (si existe)
         
Resultado: El empleado y su empresa AMBOS reciben el correo
```

**Ejemplo real:**

```
TO:  juan@gmail.com (empleado reclutado del formulario)
CC:  rrhh@acmegroup.com (empresa)
CC:  compliance@acmegroup.com (si lo hay en directorio global)

Subject: ✅ Incapacidad Validada
Body:    Html plantilla completa → MAYÚSCULAS, FECHA ENVIO, etc.
```

---

### Flujo Presunto Fraude (DERIVADO_TTHH)

Este es **EL FLUJO NUEVO** que se acaba de corregir:

```
Backend detecta que documento puede ser fraude (DERIVADO_TTHH)
         ↓
PRIMER CORREO → Al empleado (información neutral)
  TO:    juan@gmail.com
  CC:    rrhh@acmegroup.com (empresa)
  Subject: "⏳ Tu incapacidad está siendo validada"
  Body:  "Hemos recibido tu documentación...
          Estamos a la espera de respuesta de la EPS..."
          
         ↓ SIMULTANEAMENTE ↓
         
SEGUNDO CORREO → Al área de presunto fraude
  TO:    fraude@incaneurobaeza.com
  CC:    rrhh@acmegroup.com (empresa ✅ AHORA SÍ INCLUIDA)
  Subject: "🚨 ALERTA - Presunto Fraude: [serial]"
  Body:   Detalles del caso:
          - Cédula, nombre, empresa
          - Fechas de incapacidad
          - Tipo de incapacidad
          - Archivo PDF en Google Drive (link)
          
Resultado: Fraude se investiga, empresa se mantiene informada
```

---

## 🎛️ Detección Automática de Empresa

El sistema hace esto automáticamente:

```python
# Cuando llega una incapacidad:

1. Obtiene el empleado de la Base de Datos
   → empleado.empresa_id

2. Busca en Directorio:
   ✅ Correos específicos para esa empresa_id ( PRIORIDAD 1)
   ✅ Correos globales sin empresa_id (FALLBACK)

3. Genera CC con TODOS los correos encontrados

4. Elimina duplicados + TO del CC
   (No se manda el mismo correo al TO y al CC)
```

**Código real**:

```python
# En validador.py - función: actualizar_estado_caso()

# Buscar correos de empresa
correos = db.query(CorreoNotificacion).filter(
    CorreoNotificacion.area == 'empresas',
    CorreoNotificacion.activo == True  # Solo activos
).all()

emails_directorio = set()
for c in correos:
    # Agregar si es global O si es de esa empresa
    if c.company_id is None or c.company_id == caso.empresa.id:
        if c.email:
            emails_directorio.add(c.email.strip())

# Resultado: lista de CCs para esta empresa
```

---

## 📊 Ejemplo Completo (Caso Real)

**Escenario**: Empleado de Acme envía incapacidad. Se marca como DERIVADO_TTHH (presunto fraude).

**Base de Datos:**

```
EMPRESA "Industrias Acme" (company_id=5)

DIRECTORIO - área "empresas":
  ✓ rrhh@acmegroup.com (empresa_id=5)
  ✓ compliance@acmegroup.com (empresa_id=5)
  ✓ grupo-empresarial@acme.com (empresa_id=NULL → global)

DIRECTORIO - área "presunto_fraude":
  ✓ fraude-acme@acmegroup.com (empresa_id=5)
  ✓ fraude-central@incaneurobaeza.com (empresa_id=NULL → global)
  ✗ otro-area@empresa.com (empresa_id=10 → NO aplica)
```

**Qué pasa cuando se marca DERIVADO_TTHH:**

```
CORREO 1: Al Empleado (NEUTRAL)
├─ TO:      juan@acmegroup.com
├─ CC:      rrhh@acmegroup.com
├─ CC:      compliance@acmegroup.com
├─ CC:      grupo-empresarial@acme.com
├─ Subject: ⏳ Tu incapacidad está siendo validada
└─ Body:    Plantilla "falsa" (esperamos respuesta EPS)

CORREO 2: Al Investigador de Fraude (ALERTA)
├─ TO:      fraude-acme@acmegroup.com
├─ CC:      rrhh@acmegroup.com ✅ EMPRESA
├─ CC:      compliance@acmegroup.com ✅ EMPRESA
├─ CC:      grupo-empresarial@acme.com ✅ EMPRESA
├─ CC:      fraude-central@incaneurobaeza.com
├─ Subject: 🚨 ALERTA - Presunto Fraude
└─ Body:    [REPORTE DETALLADO]
            Cedula, nombres, fechas, drive link, etc.
            
Resultado: ✅ TODO OK
- Empleado se siente tranquilo (correo neutral)
- Empresa aware de la sospecha
- Fraude recibe detalles para investigar
```

---

## ⚙️ Configuración de Railway / .env

No hay variables nuevas. El directorio se configura TODO en:

```
DATABASE → tabla CorreoNotificacion
```

O via UI:

```
Panel Admin → Settings → Correos de Notificación
```

---

## 🔍 Debugging: Ver Qué CCs Se Están Usando

En cada cambio de estado, el backend loguea:

```
[serial] 📧 Email TO: juan@gmail.com
[serial] 📧 CC directorio: rrhh@acme.com, compliance@acme.com, ...
[serial] 📧 Presunto fraude env a: [fraude-acme@acmegroup.com]
```

Busca estos logs en:
- Railway logs
- Docker logs (local)
- Endpoint `/admin/logs` (si existe)

---

## 📋 Checklist: Antes de Ir a Producción

- [ ] ¿Están configurados los correos de **empresas** en admin?
  ```
  GO TO: Panel Admin → Correos → Area "empresas"
  ```

- [ ] ¿Están configurados los correos de **presunto_fraude**?
  ```
  GO TO: Panel Admin → Correos → Area "presunto_fraude"
  ```

- [ ] ¿Probar flujo normal? (marcar como INCOMPLETA)
  - [ ] Empleado recibe correo
  - [ ] Empresa recibe en CC

- [ ] ¿Probar presunto fraude? (marcar como DERIVADO_TTHH)
  - [ ] Empleado recibe correo NEUTRAL (plantilla "falsa")
  - [ ] Empresa recibe en CC
  - [ ] Presunto fraude recibe REPORTE con detalles
  - [ ] Empresa recibe en CC del reporte

- [ ] ¿Todos los correos tienen MAYÚSCULAS + FECHA ENVIO + PRESUNTO FRAUDE?
  - [ ] Sí (aplicado hace 2 commits)

---

## 🚀 Comandos Útiles

Ver correos configurados en BD (SQL):

```sql
SELECT area, company_id, email, activo
FROM correos_notificacion
ORDER BY area, company_id;
```

Test manual de envío (Python):

```python
from app.notificacion_service import enviar_notificacion_completa

resultado = enviar_notificacion_completa(
    tipo_notificacion='derivado_tthh',
    email='test-empleado@gmail.com',
    serial='TEST123',
    subject='Test Presunto Fraude',
    html_content='<p>Test</p>',
    cc_email='test-empresa@empresa.com'
)

print(f"Status: {resultado['status']}")
```

---

## 🎯 Resumen de Cambios (Hoy)

| Cambio | Dónde | Qué Pasó |
|--------|-------|----------|
| **Plantilla Presunto Fraude** | `validador.py` L844 | "derivado_tthh" → "falsa" |
| **Segundo Correo** | `validador.py` L930-956 | Agregó envío a presunto_fraude + CC empresa |
| **CC Empresa** | AMBOS correos | Garantiza que empresa siempre recibe |
| **Migración N8N** | `email_service.py` | SMTP Gmail nativo |

---

**Documento creado**: 29/03/2026
**Próxima revisión**: Después de test en producción
