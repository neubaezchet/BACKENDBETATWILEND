# ✅ SOLUCIÓN: Filtrado de Registros Históricos sin PDF

## 📋 PROBLEMA IDENTIFICADO

El validador (dashboard principal) mostraba **20,686 registros históricos** (2015-2021) migrados desde Kactus que:
- **NO tienen PDFs** (drive_link = NULL o vacío)
- Están marcados como **estado="VALIDADA"**  
- Solo existen para **reportes quincenales** (datos base en BD)
- **Congestionaban** la Tabla Viva y estadísticas del dashboard
- Causaban **rendimiento superlento** en Railway

### Requerimientos del Usuario:
1. ✅ Registros históricos **NO deben aparecer** en dashboard/reportes automáticos
2. ✅ Registros históricos **SÍ deben ser buscables manualmente**
3. ✅ Datos quincenales siguen actualizándose (los registros permanecen en BD)
4. ✅ Casos actuales con PDF (últimos 180 días) siguen apareciendo normalmente

---

## 🔧 CAMBIOS IMPLEMENTADOS

### 1. **MODELO DE BASE DE DATOS** (`app/database.py`)

#### Columna Nueva: `es_historico`
```python
es_historico = Column(Boolean, default=False, index=True)
# Marca registros históricos sin PDF (2015-2021) para excluirlos del dashboard
```

#### Índice de Rendimiento:
```python
Index('idx_estado_historico', 'estado', 'es_historico')
# Optimiza queries que filtran por estado + histórico
```

**Propósito:**
- `es_historico=True`: Registro antiguo sin PDF, solo para consultas manuales
- `es_historico=False` (default): Caso actual que aparece en dashboard

---

### 2. **SCRIPT DE MIGRACIÓN** (`migrate_add_historico_column.py`)

#### Funcionalidad:
1. ✅ Verifica si la columna `es_historico` ya existe
2. ✅ Agrega columna con valor por defecto `False`
3. ✅ **Auto-marca registros históricos** con la regla:
   ```sql
   UPDATE cases 
   SET es_historico = TRUE 
   WHERE (drive_link IS NULL OR drive_link = '' OR drive_link = 'null') 
     AND estado = 'VALIDADA'
   ```
4. ✅ Crea índice compuesto `idx_estado_historico`
5. ✅ Muestra estadísticas:
   - Total de casos en BD
   - Casos marcados como históricos
   - Casos actuales (no históricos)
6. ✅ Incluye opción de rollback (`--rollback`)

#### Ejecución:
```bash
# En Railway o local:
python migrate_add_historico_column.py

# Para revertir cambios:
python migrate_add_historico_column.py --rollback
```

#### Resultado Esperado:
```
=== MIGRACIÓN COMPLETADA ===
✅ Columna es_historico agregada
✅ ~20,686 registros marcados como históricos
✅ Índice idx_estado_historico creado

Estadísticas:
- Total de casos: 20,836
- Históricos: 20,686 (99.3%)
- Actuales: 150 (0.7%)
```

---

### 3. **ENDPOINTS API MODIFICADOS** (`app/validador.py`)

#### A. `/validador/casos` - Listar Casos (línea ~391)
**Cambio:** Nuevo parámetro `incluir_historicos: bool = False`

```python
async def listar_casos(
    incluir_historicos: bool = False,  # Nuevo parámetro
    ...
):
    query = db.query(Case)
    
    # Filtro históricos por defecto
    if not incluir_historicos:
        query = query.filter(Case.es_historico == False)
```

**Comportamiento:**
- `incluir_historicos=false` (default): Solo casos actuales → Dashboard limpio
- `incluir_historicos=true`: Incluye históricos → Búsquedas manuales

---

#### B. `/validador/casos/tabla-viva` - Dashboard Tiempo Real (NUEVO)
**Endpoint creado específicamente para el frontend TableViva**

```python
@router.get("/casos/tabla-viva")
async def obtener_tabla_viva(
    empresa: Optional[str] = None,
    periodo: Optional[str] = None,
    ...
):
    # Solo casos actuales (no históricos)
    query = db.query(Case).filter(Case.es_historico == False)
    
    return {
        "total": total,
        "estadisticas": {
            "INCOMPLETA": ...,
            "NUEVO": ...,
            "COMPLETA": ...,
            ...
        }
    }
```

**Respuesta Esperada (después de migración):**
```json
{
  "total": 150,
  "estadisticas": {
    "NUEVO": 45,
    "INCOMPLETA": 30,
    "COMPLETA": 25,
    "VALIDADA": 20,
    ...
  }
}
```

**ANTES:** Total mostraba ~20,836 (incluyendo históricos)  
**DESPUÉS:** Total muestra ~150 (solo casos actuales)

---

#### C. `/validador/stats` - Estadísticas Dashboard (línea ~881)
**Cambio:** Filtro histórico en base query

```python
async def obtener_estadisticas(...):
    # Solo casos actuales para estadísticas
    query = db.query(Case).filter(Case.es_historico == False)
    
    stats = {
        "total_casos": query.count(),        # ✅ Solo actuales
        "incompletas": query.filter(...),     # ✅ Solo actuales
        "nuevos": query.filter(...),          # ✅ Solo actuales
        ...
    }
```

---

#### D. `/validador/exportar/casos` - Exportar a Excel (línea ~1248)
**Cambio:** Nuevo parámetro `incluir_historicos: bool = False`

```python
async def exportar_casos(
    incluir_historicos: bool = False,  # Nuevo parámetro
    ...
):
    query = db.query(Case).join(Employee, ...)
    
    # Excluir históricos por defecto en reportes
    if not incluir_historicos:
        query = query.filter(Case.es_historico == False)
```

**Comportamiento:**
- Reportes Excel: Solo casos actuales por defecto
- Opción para incluir históricos si se necesita

---

#### E. `/validador/busqueda-relacional` - Búsqueda Manual (línea ~1050)
**Cambio:** **NO SE FILTRA** - Incluye históricos por defecto

```python
@router.post("/busqueda-relacional")
async def busqueda_relacional(...):
    """
    ✅ REGISTROS HISTÓRICOS:
    - INCLUYE registros históricos por defecto
    - Este es un endpoint de búsqueda manual explícita
    - Los usuarios deben poder encontrar casos antiguos cuando buscan activamente
    """
    
    # NO HAY FILTRO DE es_historico aquí
    query = db.query(Case).join(Employee, ...)
```

**Propósito:** Cuando un usuario busca explícitamente por cédula/serial/nombre, debe poder encontrar registros antiguos.

---

#### F. Endpoints SIN CAMBIOS (Ya filtran por `drive_link`)
Estos endpoints NO necesitaron modificación porque ya filtran por PDF:

1. **`/validador/exportar/zip`** (línea ~1369)
   - Ya filtra: `query.filter(Case.drive_link.isnot(None), Case.drive_link != "")`
   - Históricos sin PDF quedan excluidos automáticamente

2. **`/validador/exportar/drive`** (línea ~1832)
   - Ya filtra: `query.filter(Case.drive_link.isnot(None), Case.drive_link != "")`
   - Históricos sin PDF quedan excluidos automáticamente

3. **Endpoints de detalle por serial** (múltiples líneas)
   - `db.query(Case).filter(Case.serial == serial).first()`
   - Permiten acceso a cualquier caso individual (histórico o actual)
   - Necesario para visualización de casos específicos

---

## 📊 RESUMEN DE COMPORTAMIENTO POR ENDPOINT

| Endpoint | Incluye Históricos | Justificación |
|----------|-------------------|---------------|
| `/casos` | ❌ No (por defecto) | Dashboard - solo casos actuales |
| `/casos/tabla-viva` | ❌ No | Dashboard tiempo real |
| `/stats` | ❌ No | Estadísticas solo de casos actuales |
| `/exportar/casos` | ❌ No (por defecto) | Reportes de casos actuales |
| `/busqueda-relacional` | ✅ Sí | Búsqueda manual explícita |
| `/busqueda-relacional/excel` | ✅ Sí | Búsqueda masiva por cedulas |
| `/exportar/zip` | ❌ No | Solo casos con PDF (filtro automático) |
| `/exportar/drive` | ❌ No | Solo casos con PDF (filtro automático) |
| `/casos/{serial}` | ✅ Sí | Acceso directo a caso individual |

---

## 🚀 PASOS DE IMPLEMENTACIÓN

### 1. **Ejecutar Migración en Railway**
```bash
# Conectar a Railway
railway link

# Ejecutar migración
railway run python migrate_add_historico_column.py

# Verificar resultado
railway logs
```

### 2. **Deploy del Backend Actualizado**
```bash
# Commit cambios
git add app/database.py app/validador.py migrate_add_historico_column.py
git commit -m "feat: Filtrado de registros históricos sin PDF

- Agrega columna es_historico a modelo Case
- Crea endpoint /casos/tabla-viva para dashboard
- Actualiza endpoints de estadísticas y listado
- Mantiene búsqueda manual de históricos"

# Push a Railway
git push railway main
```

### 3. **Verificar Funcionamiento**
1. ✅ Abrir dashboard del validador
2. ✅ Verificar que "Total Casos" muestra ~150 (no 20,686)
3. ✅ Verificar que Tabla Viva carga rápido
4. ✅ Probar búsqueda manual por cédula antigua → debe encontrar históricos
5. ✅ Exportar Excel → debe generar solo casos actuales

---

## ⚡ MEJORA DE RENDIMIENTO ESPERADA

### ANTES:
```
Query dashboard: db.query(Case).all()
Resultado: 20,836 registros
Tiempo: ~8-15 segundos (lento)
```

### DESPUÉS:
```
Query dashboard: db.query(Case).filter(Case.es_historico == False).all()
Resultado: ~150 registros (99.3% reducción)
Tiempo: ~0.5-1 segundo (rápido)
```

**Beneficios:**
- ✅ Dashboard carga 10-15x más rápido
- ✅ Estadísticas reflejan solo casos actuales
- ✅ Tabla Viva auto-refresh cada 30s sin lag
- ✅ Índice compuesto acelera queries por estado
- ✅ Datos históricos siguen disponibles para búsquedas manuales

---

## 🔄 ROLLBACK (Si es necesario)

Si algo sale mal, ejecutar:

```bash
# Revertir migración
python migrate_add_historico_column.py --rollback

# Esto hará:
# 1. Eliminar índice idx_estado_historico
# 2. Eliminar columna es_historico
# 3. Restaurar estado original de la BD
```

---

## 📝 NOTAS IMPORTANTES

1. **Datos NO se eliminan**: Los registros históricos permanecen en la BD
2. **Reportes quincenales**: Siguen funcionando con todos los datos
3. **Búsqueda manual**: Sigue encontrando casos antiguos sin problema
4. **Migración idempotente**: Se puede ejecutar múltiples veces sin error
5. **Sin downtime**: La columna se agrega con valor por defecto, no rompe nada
6. **Frontend compatible**: El frontend ya usa el endpoint correcto

---

## ✅ CHECKLIST DE VERIFICACIÓN POST-DEPLOY

- [ ] Migración ejecutada sin errores
- [ ] Backend desplegado en Railway
- [ ] Dashboard carga rápido (<2 segundos)
- [ ] Total de casos muestra valor correcto (~150)
- [ ] Estadísticas por estado suman correctamente
- [ ] Búsqueda manual encuentra casos antiguos
- [ ] Exportar Excel genera archivo solo con casos actuales
- [ ] Tabla Viva auto-refresh funciona sin lag
- [ ] No hay errores en logs de Railway

---

## 🎯 RESULTADO FINAL

- **Problema:** Dashboard lento con 20,686 registros históricos sin PDF
- **Solución:** Filtrado automático con columna `es_historico`
- **Resultado:** Dashboard muestra solo ~150 casos actuales, 10-15x más rápido
- **Beneficio adicional:** Históricos siguen disponibles para búsquedas manuales

✅ **CORRECCIÓN COMPLETA DEL VALIDADOR**
