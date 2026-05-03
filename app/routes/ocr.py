"""
✅ Rutas para OCR con Mistral Document AI
SOLO OCR - Endpoints para extraer y exportar texto plano
"""

from fastapi import APIRouter, HTTPException, File, UploadFile, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
import os
import tempfile
import base64
from pathlib import Path
from datetime import datetime

from app.database import Base, get_db, ExtractoIncapacidad, Case
from app.mistral_ocr_service import mistral_ocr
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ocr", tags=["OCR"])


# ──────────────────────────────────────────────
#  POST: Procesar documento - Archivo directo
# ──────────────────────────────────────────────
@router.post("/procesar")
async def procesar_documento(
    file: UploadFile = File(...),
    cedula: str = Query(...),
    tipo_documento: str = Query("incapacidad"),
    tipo_incapacidad: str = Query(None),
    db: Session = Depends(get_db)
):
    """
    ✅ Procesa un documento (PDF o imagen) usando Mistral Document AI OCR
    
    Args:
        file: Archivo PDF o imagen
        cedula: Cédula del empleado
        tipo_documento: Tipo (incapacidad, epicrisis, soat, etc)
        tipo_incapacidad: Tipo de incapacidad (maternidad, etc)
        
    Returns:
        {
            "exito": bool,
            "texto": str,
            "id_extracto": int,
            "paginas": int,
            "error": str
        }
    """
    if not mistral_ocr:
        raise HTTPException(
            status_code=503,
            detail="Servicio OCR no disponible. Configura MISTRAL_API_KEY"
        )
    
    try:
        # Leer contenido del archivo
        contenido = await file.read()
        
        # Convertir a base64
        archivo_base64 = base64.b64encode(contenido).decode('utf-8')
        
        # Detectar tipo de archivo
        extension = Path(file.filename).suffix.lower()
        
        if extension == '.pdf':
            # Procesar como PDF
            resultado = mistral_ocr.procesar_pdf_base64(archivo_base64)
        elif extension in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
            # Procesar como imagen
            tipo_mime = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.gif': 'image/gif',
                '.webp': 'image/webp'
            }.get(extension, 'image/jpeg')
            resultado = mistral_ocr.procesar_imagen_base64(archivo_base64, tipo_mime)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Tipo de archivo no soportado: {extension}"
            )
        
        if not resultado["exito"]:
            raise HTTPException(status_code=400, detail=resultado["error"])
        
        # Guardar en BD
        extracto = ExtractoIncapacidad(
            cedula=cedula,
            tipo_documento=tipo_documento,
            tipo_incapacidad=tipo_incapacidad,
            texto_extraido=resultado["texto"],
            modelo_ocr=resultado["modelo"],
            procesado=True
        )
        
        db.add(extracto)
        db.commit()
        db.refresh(extracto)
        
        logger.info(f"✅ OCR exitoso: Cédula {cedula}, ID {extracto.id}, Páginas: {resultado['paginas']}")
        
        return {
            "exito": True,
            "texto": resultado["texto"],
            "id_extracto": extracto.id,
            "paginas": resultado["paginas"],
            "error": ""
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error OCR: {str(e)}", exc_info=True)
        
        # Guardar error en BD
        try:
            extracto = ExtractoIncapacidad(
                cedula=cedula,
                tipo_documento=tipo_documento,
                texto_extraido="",
                procesado=False,
                error_procesamiento=str(e)[:500]
            )
            db.add(extracto)
            db.commit()
        except:
            pass
        
        raise HTTPException(status_code=500, detail=f"Error al procesar: {str(e)}")


# ──────────────────────────────────────────────
#  POST: Procesar desde URL (PDF o imagen)
# ──────────────────────────────────────────────
@router.post("/procesar-url")
async def procesar_url(
    url: str = Query(...),
    cedula: str = Query(...),
    tipo_documento: str = Query("incapacidad"),
    tipo_incapacidad: str = Query(None),
    db: Session = Depends(get_db)
):
    """
    Procesa un documento desde URL pública
    
    Args:
        url: URL pública del documento (PDF o imagen)
        cedula: Cédula del empleado
        tipo_documento: Tipo
        tipo_incapacidad: Tipo incapacidad
    """
    if not mistral_ocr:
        raise HTTPException(status_code=503, detail="Servicio OCR no disponible")
    
    try:
        # Detectar tipo por extensión URL
        if url.lower().endswith('.pdf'):
            resultado = mistral_ocr.procesar_pdf_url(url)
        else:
            resultado = mistral_ocr.procesar_imagen_url(url)
        
        if not resultado["exito"]:
            raise HTTPException(status_code=400, detail=resultado["error"])
        
        # Guardar en BD
        extracto = ExtractoIncapacidad(
            cedula=cedula,
            tipo_documento=tipo_documento,
            tipo_incapacidad=tipo_incapacidad,
            texto_extraido=resultado["texto"],
            modelo_ocr=resultado["modelo"],
            procesado=True
        )
        
        db.add(extracto)
        db.commit()
        db.refresh(extracto)
        
        return {
            "exito": True,
            "texto": resultado["texto"],
            "id_extracto": extracto.id,
            "paginas": resultado["paginas"],
            "error": ""
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error OCR URL: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# ──────────────────────────────────────────────
#  GET: Obtener extractos de un empleado
# ──────────────────────────────────────────────
@router.get("/extractos/{cedula}")
async def obtener_extractos(
    cedula: str,
    tipo_documento: str = Query(None),
    limite: int = Query(100),
    db: Session = Depends(get_db)
):
    """
    Obtiene todos los textos extraídos de un empleado
    """
    query = db.query(ExtractoIncapacidad).filter(
        ExtractoIncapacidad.cedula == cedula,
        ExtractoIncapacidad.procesado == True
    )
    
    if tipo_documento:
        query = query.filter(ExtractoIncapacidad.tipo_documento == tipo_documento)
    
    extractos = query.order_by(desc(ExtractoIncapacidad.creado_en)).limit(limite).all()
    
    return {
        "cedula": cedula,
        "total": len(extractos),
        "extractos": [
            {
                "id": e.id,
                "tipo_documento": e.tipo_documento,
                "tipo_incapacidad": e.tipo_incapacidad,
                "texto_extraido": e.texto_extraido,
                "creado_en": e.creado_en.isoformat() if e.creado_en else None,
                "modelo": e.modelo_ocr
            }
            for e in extractos
        ]
    }


# ──────────────────────────────────────────────
#  GET: Exportar extractos como JSON
# ──────────────────────────────────────────────
@router.get("/exportar/json/{cedula}")
async def exportar_json(cedula: str, db: Session = Depends(get_db)):
    """Exporta todos los extractos como JSON plano"""
    extractos = db.query(ExtractoIncapacidad).filter(
        ExtractoIncapacidad.cedula == cedula,
        ExtractoIncapacidad.procesado == True
    ).order_by(desc(ExtractoIncapacidad.creado_en)).all()
    
    return [
        {
            "id": e.id,
            "cedula": e.cedula,
            "tipo_documento": e.tipo_documento,
            "tipo_incapacidad": e.tipo_incapacidad,
            "texto": e.texto_extraido,
            "fecha": e.creado_en.isoformat() if e.creado_en else None,
            "modelo": e.modelo_ocr
        }
        for e in extractos
    ]


# ──────────────────────────────────────────────
#  GET: Exportar como CSV
# ──────────────────────────────────────────────
@router.get("/exportar/csv/{cedula}")
async def exportar_csv(cedula: str, db: Session = Depends(get_db)):
    """Exporta como CSV para abrir en Excel"""
    try:
        import pandas as pd
    except ImportError:
        raise HTTPException(status_code=503, detail="pandas no está instalado")
    
    extractos = db.query(ExtractoIncapacidad).filter(
        ExtractoIncapacidad.cedula == cedula,
        ExtractoIncapacidad.procesado == True
    ).order_by(desc(ExtractoIncapacidad.creado_en)).all()
    
    datos = [
        {
            "ID": e.id,
            "Cédula": e.cedula,
            "Tipo Documento": e.tipo_documento,
            "Tipo Incapacidad": e.tipo_incapacidad,
            "Texto Extraído": e.texto_extraido,
            "Fecha": e.creado_en.strftime("%Y-%m-%d %H:%M") if e.creado_en else None,
            "Modelo": e.modelo_ocr
        }
        for e in extractos
    ]
    
    df = pd.DataFrame(datos)
    csv = df.to_csv(index=False, encoding='utf-8-sig')
    
    return {
        "csv": csv,
        "total_filas": len(datos),
        "filename": f"extractos_{cedula}.csv"
    }


# ──────────────────────────────────────────────
#  GET: Health check
# ──────────────────────────────────────────────
@router.get("/health")
async def health_check():
    """Verifica si Mistral OCR está disponible"""
    if not mistral_ocr:
        return {
            "status": "error",
            "mensaje": "MISTRAL_API_KEY no configurada",
            "modelo": None
        }
    
    return {
        "status": "ok",
        "mensaje": "Servicio OCR disponible",
        "modelo": mistral_ocr.model
    }

