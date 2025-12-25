# 📖 Manual del Validador - IncaNeurobaeza

## 🎯 Descripción de los Botones

### ✅ **Completa**
- **Cuándo usar**: Cuando todos los documentos están correctos y completos
- **Qué hace**: 
  - Mueve el archivo a `Incapacidades_validadas/{Empresa}/`
  - Crea una copia en `Completas/{Empresa}/`
  - Envía email de confirmación al empleado
  - Cambia el estado a "COMPLETA"

### ❌ **Incompleta**
- **Cuándo usar**: Cuando faltan documentos o están incompletos
- **Qué hace**:
  - Abre modal para seleccionar qué falta
  - Mueve el archivo a `Incompletas/{Empresa}/Faltan_Soportes/`
  - Envía email con lista detallada de lo que falta
  - Permite adjuntar imágenes de ejemplo

### 📋 **EPS**
- **Cuándo usar**: Cuando la incapacidad requiere transcripción en EPS
- **Qué hace**:
  - Mueve el archivo a `Incompletas/{Empresa}/EPS_No_Transcritas/`
  - Envía email indicando que debe ir a la EPS
  - Cambia el estado a "EPS_TRANSCRIPCION"

### 🚨 **TTHH**
- **Cuándo usar**: Cuando detectas posible fraude o irregularidades
- **Qué hace**:
  - Envía alerta a Talento Humano (`xoblaxbaezaospino@gmail.com`)
  - Mueve el archivo a `Incompletas/{Empresa}/THH_Falsas/`
  - Envía email de confirmación al empleado (sin revelar la alerta)
  - Permite seleccionar problemas encontrados

### ✉️ **Extra**
- **Cuándo usar**: Para comunicaciones personalizadas
- **Qué hace**:
  - Permite escribir un mensaje libre
  - Envía email personalizado al empleado
  - **NO cambia el estado del caso**
  - Permite adjuntar archivos

## 🔍 Checks Disponibles

### Calidad de Imagen
- **Documento recortado**: No se ven todos los bordes
- **Documento borroso**: Foto desenfocada o con poca luz
- **Documento manchado**: Tiene reflejos o manchas

### Faltantes
- **Falta epicrisis**: No adjuntó el resumen clínico
- **Epicrisis incompleta**: Faltan páginas
- **Falta incapacidad**: No hay soporte oficial
- *(Más checks según el tipo de incapacidad)*

## 💡 Tips

1. **Siempre revisa el tipo de incapacidad** antes de validar
2. **Puedes seleccionar múltiples checks** en un solo email
3. **Usa el botón Extra** para aclaraciones rápidas
4. **Los adjuntos son opcionales** pero útiles para mostrar ejemplos

## 🆘 Soporte

Si tienes dudas, contacta a: soporte@incaneuroba