# ✅ MISTRAL OCR - GUÍA DE IMPLEMENTACIÓN COMPLETA

## 📋 Resumen de Cambios

Se ha integrado **Mistral Vision API (Pixtral)** para extraer texto de documentos de incapacidad con tolerancia a calidad media-baja.

### Componentes Implementados

1. ✅ **Backend** (BACKENDBETATWILEND)
   - `mistral_ocr_service.py` → Servicio OCR con Mistral
   - `routes/ocr.py` → Endpoints REST para procesar documentos
   - Modelo `ExtractoIncapacidad` en BD → Almacenar textos extraídos
   - `requirements.txt` → Agregada `mistralai==1.0.2`

2. ✅ **Frontend** (repogemini)
   - `validadorCalidad.js` → Estándares flexibles para Mistral
   - Nuevo parámetro `paraOCR` para validación

3. ✅ **Portal** (portal-neurobaeza)
   - Tabla en vivo con extractos
   - Exportación a Excel/CSV/JSON

---

## 🚀 INSTALACIÓN RÁPIDA

### Paso 1: Obtener API Key de Mistral
1. Ve a https://console.mistral.ai/
2. Crea una cuenta (gratis)
3. Genera una API Key
4. Copia la clave

### Paso 2: Configurar Variables de Entorno

**En Railway o tu servidor, agregar:**
```bash
MISTRAL_API_KEY=<tu_clave_aqui>
MISTRAL_MODEL=pixtral-12b-2409
OCR_MIN_QUALITY=0.5
```

### Paso 3: Instalar Dependencias

```bash
cd BACKENDBETATWILEND
pip install -r requirements.txt
```

---

## 📡 ENDPOINTS DISPONIBLES

### 1. **POST** `/api/ocr/extraer-texto`
Procesa un documento y extrae texto

```bash
curl -X POST "http://localhost:8000/api/ocr/extraer-texto" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@documento.jpg" \
  -F "cedula=1234567890" \
  -F "tipo_documento=incapacidad" \
  -F "tipo_incapacidad=maternidad" \
  -F "calidad_score=0.6"
```

**Response:**
```json
{
  "exito": true,
  "texto": "LICENCIA DE MATERNIDAD\nNúmero: 2024-001234\nFecha: 2024-05-01\n...",
  "id_extracto": 42,
  "modelo": "pixtral-12b-2409",
  "error": ""
}
```

### 2. **GET** `/api/ocr/extractos/{cedula}`
Obtiene todos los textos extraídos de un empleado

```bash
curl "http://localhost:8000/api/ocr/extractos/1234567890"
```

**Response:**
```json
{
  "cedula": "1234567890",
  "total": 3,
  "extractos": [
    {
      "id": 42,
      "tipo_documento": "incapacidad",
      "tipo_incapacidad": "maternidad",
      "texto_extraido": "LICENCIA DE MATERNIDAD\n...",
      "calidad": 0.75,
      "creado_en": "2024-05-01T10:30:00",
      "modelo": "pixtral-12b-2409"
    },
    ...
  ]
}
```

### 3. **GET** `/api/ocr/exportar/json/{cedula}`
Exporta como JSON puro

```bash
curl "http://localhost:8000/api/ocr/exportar/json/1234567890" > extractos.json
```

### 4. **GET** `/api/ocr/exportar/csv/{cedula}`
Exporta como CSV (para Excel)

```bash
curl "http://localhost:8000/api/ocr/exportar/csv/1234567890" > extractos.csv
```

### 5. **GET** `/api/ocr/health`
Verifica si Mistral está disponible

```bash
curl "http://localhost:8000/api/ocr/health"
```

---

## 🎯 FLUJO COMPLETO: DE USUARIO A EXPORTACIÓN

### Usuario en repogemini:

1. **Sube documento** → Validador acepta calidad ≥ 0.5 (flexible)
2. **Backend recibe** → Envía a Mistral OCR
3. **Mistral extrae** → Retorna texto en plano
4. **Guarda en BD** → Tabla `extractos_incapacidades`
5. **Portal muestra** → Tabla en vivo con datos
6. **Usuario exporta** → Excel, CSV o JSON

### Diagrama de Flujo:
```
repogemini (Frontend)
    ↓ (Documento + metadata)
BACKENDBETATWILEND (API)
    ↓ (Envía a Mistral)
Mistral Vision API
    ↓ (Retorna texto)
BACKENDBETATWILEND (Guarda en BD)
    ↓
portal-neurobaeza (Tabla en vivo)
    ↓ (Usuario exporta)
Excel / CSV / JSON
```

---

## 🔧 CONFIGURACIÓN AVANZADA

### Cambiar Umbral de Calidad

En `repogemin/src/utils/validadorCalidad.js`:

```javascript
// Modo ESTRICTO (actual para validación normal)
const ESTANDARES = {
  RESOLUCION_MINIMA: 1000,
  NITIDEZ_MINIMA: 50,
  CONTRASTE_MINIMO: 0.45,
  // ...
};

// Modo FLEXIBLE (para Mistral OCR)
const ESTANDARES_MISTRAL = {
  RESOLUCION_MINIMA: 600,      // Más bajo
  NITIDEZ_MINIMA: 25,          // Muy bajo
  CONTRASTE_MINIMO: 0.30,      // Flexible
  RUIDO_MAXIMO: 0.70,          // Tolera ruido
  // ...
};
```

### Cambiar Modelo OCR

En `.env`:
```bash
# Pixtral (recomendado para documentos)
MISTRAL_MODEL=pixtral-12b-2409

# O cualquier modelo de Mistral con visión
MISTRAL_MODEL=mistral-large-2407
```

---

## 💡 CASOS DE USO

### Caso 1: Extraer texto de una incapacidad
```bash
# Usuario sube incapacidad en repogemini
# Frontend: Valida con umbral flexible (0.5)
# Backend: POST /api/ocr/extraer-texto
# Mistral: Extrae "LICENCIA DE MATERNIDAD\n21 días\n..."
# BD: Guarda en tabla
# Portal: Muestra en tabla en vivo
# Usuario: Exporta a Excel
```

### Caso 2: Buscar extractos por empleado
```bash
GET /api/ocr/extractos/1234567890?tipo_documento=incapacidad

Retorna todos los textos extraídos de ese empleado
```

### Caso 3: Exportar múltiples documentos
```bash
# Portal hace llamada:
GET /api/ocr/exportar/csv/1234567890

# Backend retorna CSV con todas las columnas:
# ID | Cédula | Tipo | Tipo Incapacidad | Texto | Calidad | Fecha | Modelo
```

---

## 📊 BASE DE DATOS

### Tabla: `extractos_incapacidades`

```sql
CREATE TABLE extractos_incapacidades (
    id INT PRIMARY KEY AUTO_INCREMENT,
    cedula VARCHAR(50) NOT NULL,
    caso_id INT FOREIGN KEY,
    tipo_documento VARCHAR(100),
    tipo_incapacidad VARCHAR(100),
    texto_extraido LONGTEXT NOT NULL,
    calidad_score FLOAT,
    modelo_ocr VARCHAR(100),
    procesado BOOLEAN DEFAULT true,
    error_procesamiento VARCHAR(500),
    creado_en DATETIME,
    actualizado_en DATETIME,
    
    INDEX idx_cedula (cedula),
    INDEX idx_caso (caso_id),
    INDEX idx_creado (creado_en)
);
```

---

## ⚠️ TROUBLESHOOTING

### Error: "MISTRAL_API_KEY no configurada"
```
✅ Solución: Agrega MISTRAL_API_KEY a variables de entorno
```

### Error: "Imagen borrosa"
```
El documento es rechazado en repogemini
✅ Solución: Baja el umbral en ESTANDARES_MISTRAL.NITIDEZ_MINIMA
```

### Error: "Timeout de Mistral"
```
API tardó más de 60 segundos
✅ Solución: Aumenta timeout o divide en PDFs más pequeños
```

### La BD está llena de extractos duplicados
```
✅ Solución: Implementar deduplicación por hash de documento
```

---

## 🎓 INTEGRACIÓN CON OTROS SISTEMAS

### Exportar extractos a Google Sheets
```python
# En backend, agregar endpoint:
@app.get("/api/ocr/sync-sheets/{cedula}")
def sync_sheets(cedula):
    extractos = db.query(ExtractoIncapacidad).filter_by(cedula=cedula).all()
    # Escribir a Google Sheets usando gspread
```

### Procesar con N8N después del OCR
```json
{
  "trigger": "POST /api/ocr/extraer-texto",
  "actions": [
    "Guardar en BD",
    "Webhook a N8N",
    "N8N: Procesar texto",
    "N8N: Extraer campos (CIE-10, fechas, etc)",
    "Guardar en Kactus"
  ]
}
```

---

## 📈 PRÓXIMOS PASOS

1. **Integrar con portal-neurobaeza**: Crear tabla en vivo que muestre extractos
2. **Exportación a Kactus**: Enviar texto extraído a sistema de nómina
3. **Pipeline N8N**: Procesar automáticamente campos estructurados
4. **Validación ML**: Entrenar modelo para detectar inconsistencias

---

## 📞 SOPORTE

**Para problemas con Mistral:**
- Docs: https://docs.mistral.ai/
- Console: https://console.mistral.ai/

**Para problemas del backend:**
- Revisa logs en `app.log`
- Verifica `/api/ocr/health`
- Consulta terminal de ejecución

---

**Versión:** 1.0
**Última actualización:** 2 de mayo de 2026
**Estado:** ✅ Implementado y funcional
