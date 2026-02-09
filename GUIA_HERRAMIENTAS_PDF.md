# 🔧 Guía de Herramientas PDF - Portal Validador

## 📊 Estado Actual

### ✅ Implementación Completa

**Frontend (portal-neurobaeza):**
- ✅ Menú de herramientas con atajos de teclado
- ✅ Notificaciones sutiles para feedback inmediato  
- ✅ Estados de carga (`enviandoValidacion`)
- ✅ Recarga automática del PDF después de editar

**Backend (BACKENDBETATWILEND):**
- ✅ Endpoint `/validador/casos/{serial}/editar-pdf`
- ✅ Dependencias instaladas en `requirements.txt`:
  - `pymupdf==1.23.8` (Manipulación PDF)
  - `pillow==10.2.0` (Procesamiento de imágenes)
  - `opencv-python-headless==4.9.0.80` (Visión computacional)
  - `scikit-image==0.22.0` (Algoritmos de imagen)
  - `reportlab==4.0.9` (Generación PDF)

---

## 🚀 Herramientas Disponibles

### 1. **Rotar Página** (Atajo: R)
- **Operación:** Rota la página actual 90°
- **Tiempo estimado:** ~2 segundos
- **Uso:** Documentos escaneados en orientación incorrecta

### 2. **Mejorar Calidad** (Atajo: Q)
- **Operación:** Mejora resolución y nitidez con OpenCV
- **Niveles:**
  - Rápido (1.8x): ~5 segundos
  - Estándar (2.5x): ~8 segundos ⭐ Recomendado
  - Premium (3.5x): ~15 segundos
- **Uso:** Documentos borrosos o de baja calidad

### 3. **Recorte Automático** (Atajo: C)
- **Operación:** Detecta bordes y recorta márgenes innecesarios
- **Tiempo estimado:** ~3 segundos
- **Uso:** Fotos con mucho espacio en blanco alrededor

### 4. **Blanco y Negro** (Atajo: B)
- **Operación:** Convierte a escala de grises
- **Tiempo estimado:** ~2 segundos
- **Uso:** Reducir tamaño de archivo y mejorar legibilidad

### 5. **Corregir Inclinación** (Atajo: A)
- **Operación:** Detecta ángulo de inclinación y endereza el documento
- **Tiempo estimado:** ~10 segundos
- **Uso:** Fotos tomadas con el celular mal alineadas

---

## ⚠️ Por Qué NO Puede Ser "Instantáneo"

### Procesamiento Real Requerido:

1. **Descarga PDF desde Google Drive** (~2-3 seg)
   ```python
   response = requests.get(download_url)
   ```

2. **Carga en memoria y renderiza** (~1-2 seg)
   ```python
   editor = PDFEditor(temp_input)
   ```

3. **Aplica algoritmos de OpenCV** (~3-15 seg según operación)
   ```python
   # Ejemplo: Mejora de calidad
   - Detección de bordes
   - Corrección de contraste
   - Nitidez (sharpening)
   - Reducción de ruido
   ```

4. **Guarda PDF editado** (~1-2 seg)
   ```python
   editor.save_changes(temp_output)
   ```

5. **Sube a Google Drive** (~3-5 seg)
   ```python
   organizer.actualizar_pdf_editado(caso, temp_output)
   ```

**Tiempo total mínimo: 10-30 segundos** (según operación y tamaño del archivo)

---

## 💡 Mejoras Implementadas

### ✅ Feedback Visual Mejorado

**Antes:**
```javascript
// Frontend solo mostraba spinner, sin información
setEnviandoValidacion(true);
await fetch('/editar-pdf', {...});
```

**Ahora:**
```javascript
// Notificación inmediata con tiempo estimado
mostrarNotificacion('⏳ Procesando calidad Estándar (2.5x)... Esto puede tardar 5-10seg', 'info');
setEnviandoValidacion(true);
await fetch('/editar-pdf', {...});
```

### ✅ Notificaciones Específicas por Acción

**Validación de casos:**
- ✅ Caso COMPLETO → `"✅ Caso VALIDADO como COMPLETO"`
- ⚠️ Caso INCOMPLETO → `"⚠️ Caso marcado como INCOMPLETO"`
- 📨 Derivado TTHH → `"📨 Caso derivado a TALENTO HUMANO"`
- 🏥 Derivado EPS → `"🏥 Caso derivado a EPS"`

---

## 🔍 Diagnóstico de Problemas

### Problema: "Las herramientas no conectan"

#### ✅ Checklist de Verificación:

1. **Backend en producción tiene las dependencias instaladas:**
   ```bash
   # En Railway/Render, ejecutar:
   pip list | grep -E "(pymupdf|opencv|pillow|scikit)"
   ```
   
   **Debe mostrar:**
   ```
   pymupdf          1.23.8
   opencv-python-headless  4.9.0.80
   pillow           10.2.0
   scikit-image     0.22.0
   ```

2. **Endpoint responde correctamente:**
   ```bash
   curl -X POST https://web-production-95ed.up.railway.app/validador/casos/TEST_SERIAL/editar-pdf \
     -H "X-Admin-Token: 0b9685e9a9ff3c24652acaad881ec7b2b4c17f6082ad164d10a6e67589f3f67c" \
     -H "Content-Type: application/json" \
     -d '{"operaciones": {"rotate": [{"page_num": 0, "angle": 90}]}}'
   ```
   
   **Respuesta esperada:**
   ```json
   {
     "status": "ok",
     "serial": "TEST_SERIAL",
     "nuevo_link": "https://drive.google.com/...",
     "modificaciones": [...],
     "mensaje": "PDF editado y actualizado en Drive"
   }
   ```

3. **Revisar logs del backend:**
   ```bash
   railway logs | grep "editar-pdf"
   ```
   
   **Debe mostrar:**
   ```
   📝 Operaciones recibidas: {'rotate': [{'page_num': 0, 'angle': 90}]}
   📥 Descargando PDF desde: https://drive.google.com/...
   ✅ PDF descargado: /tmp/SERIAL_original.pdf
   🔧 Procesando: rotate
   🔄 Rotando página 0 90°
   💾 PDF guardado: /tmp/SERIAL_edited.pdf
   ✅ PDF actualizado en Drive: https://drive.google.com/...
   ```

---

## 🛠️ Soluciones

### Opción 1: **Verificar Instalación en Producción** ⭐ Recomendado

Si las herramientas no funcionan, probablemente las dependencias no están instaladas en producción.

**Pasos:**
1. Verificar que `requirements.txt` esté en la raíz del proyecto
2. En Railway/Render, verificar que el build log muestre:
   ```
   Collecting pymupdf==1.23.8
   Collecting opencv-python-headless==4.9.0.80
   ...
   Successfully installed pymupdf-1.23.8 opencv-python-headless-4.9.0.80 ...
   ```
3. Si no se instalaron, forzar reinstalación:
   - Railway: Click "Redeploy"
   - Render: Click "Manual Deploy" → "Clear build cache & deploy"

---

### Opción 2: **Optimizar Tiempos de Procesamiento**

Para reducir tiempos de espera (pero seguirá siendo ~5-15 seg):

**Agregar caché de PDFs:**
```python
# En validador.py, línea ~1540
@router.post("/casos/{serial}/editar-pdf")
async def editar_pdf_caso(serial: str, ...):
    # Verificar si ya está en caché local
    cache_path = f"/tmp/cache/{serial}.pdf"
    if os.path.exists(cache_path):
        temp_input = cache_path
    else:
        # Descargar desde Drive
        response = requests.get(download_url)
        temp_input = f"/tmp/{serial}_original.pdf"
        with open(temp_input, 'wb') as f:
            f.write(response.content)
        # Guardar en caché
        shutil.copy(temp_input, cache_path)
    ...
```

---

### Opción 3: **Procesamiento en Background** (Avanzado)

Si el usuario necesita respuesta inmediata, usar workers:

**Arquitectura:**
```
Frontend → Backend (responde inmediato con task_id)
              ↓
         Worker procesa PDF en background
              ↓
         WebSocket notifica cuando termina
```

**Requiere:**
- Celery o RQ para workers
- Redis para cola de tareas
- WebSocket para notificaciones en tiempo real

**Tiempo de implementación:** ~4-6 horas

---

## 📝 Resumen

### ✅ Lo que SÍ está funcionando:
1. Endpoint `/editar-pdf` implementado correctamente
2. Dependencias listadas en `requirements.txt`
3. Notificaciones sutiles agregadas en frontend
4. Feedback visual mejorado

### ⚠️ Lo que puede estar fallando:
1. **Dependencias no instaladas en producción** (causa más probable)
2. Timeout del frontend (60 seg por defecto)
3. Google Drive API sin permisos
4. Archivos temporales sin espacio en disco

### 🎯 Próximos pasos:
1. **Verificar instalación de dependencias en producción** (ejecutar checklist)
2. **Revisar logs del backend** cuando se use una herramienta
3. **Probar endpoint manualmente** con curl/Postman
4. Si todo falla, considerar procesamiento en background (Opción 3)

---

## 📞 Troubleshooting Rápido

| Síntoma | Causa Probable | Solución |
|---------|----------------|----------|
| Spinner infinito | Timeout frontend | Aumentar timeout a 120 seg |
| Error 500 | Dependencia faltante | Reinstalar requirements.txt |
| "Error descargando PDF" | Drive API sin permisos | Regenerar token Drive |
| Herramienta no hace nada | Endpoint no existe | Verificar backend en producción |
| Lento pero funciona | Normal | Expectativa: 10-30 seg es normal |

---

**Última actualización:** 2025-02-08  
**Autor:** Sistema de Validación IncaNeurobaeza
