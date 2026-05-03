"""
✅ Servicio OCR con Mistral Document AI
SOLO OCR - Extrae texto plano sin análisis
Costo ultra bajo, máxima flexibilidad
"""

import os
import base64
from pathlib import Path
from mistralai.client import Mistral

# ──────────────────────────────────────────────
#  CONFIGURACIÓN
# ──────────────────────────────────────────────
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_OCR_MODEL = os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")


class MistralDocumentAIOCR:
    """Servicio OCR usando Mistral Document AI"""
    
    def __init__(self):
        if not MISTRAL_API_KEY:
            raise ValueError("❌ MISTRAL_API_KEY no está configurada en variables de entorno")
        self.client = Mistral(api_key=MISTRAL_API_KEY)
        self.model = MISTRAL_OCR_MODEL
    
    def procesar_pdf_url(self, url_pdf: str) -> dict:
        """
        Procesa un PDF desde URL usando Document AI OCR
        
        Args:
            url_pdf: URL pública del PDF (ej: https://example.com/doc.pdf)
            
        Returns:
            {
                "exito": bool,
                "texto": str,         # Texto extraído en markdown
                "paginas": int,
                "modelo": str,
                "error": str
            }
        """
        try:
            response = self.client.ocr.process(
                model=self.model,
                document={
                    "type": "document_url",
                    "document_url": url_pdf
                },
                table_format="markdown"  # Tablas como markdown
            )
            
            # Extraer texto de todas las páginas
            textos_paginas = []
            for page in response.pages:
                textos_paginas.append(page.markdown)
            
            texto_completo = "\n\n---\n\n".join(textos_paginas)
            
            return {
                "exito": True,
                "texto": texto_completo,
                "paginas": len(response.pages),
                "modelo": response.model,
                "error": ""
            }
            
        except Exception as e:
            return {
                "exito": False,
                "texto": "",
                "paginas": 0,
                "modelo": self.model,
                "error": f"Error OCR: {str(e)}"
            }
    
    def procesar_pdf_base64(self, pdf_base64: str) -> dict:
        """
        Procesa un PDF desde base64
        
        Args:
            pdf_base64: PDF codificado en base64
            
        Returns:
            Dict con texto extraído
        """
        try:
            response = self.client.ocr.process(
                model=self.model,
                document={
                    "type": "document_url",
                    "document_url": f"data:application/pdf;base64,{pdf_base64}"
                },
                table_format="markdown"
            )
            
            textos_paginas = []
            for page in response.pages:
                textos_paginas.append(page.markdown)
            
            texto_completo = "\n\n---\n\n".join(textos_paginas)
            
            return {
                "exito": True,
                "texto": texto_completo,
                "paginas": len(response.pages),
                "modelo": response.model,
                "error": ""
            }
            
        except Exception as e:
            return {
                "exito": False,
                "texto": "",
                "paginas": 0,
                "modelo": self.model,
                "error": f"Error OCR: {str(e)}"
            }
    
    def procesar_imagen_url(self, url_imagen: str) -> dict:
        """
        Procesa una imagen desde URL
        
        Args:
            url_imagen: URL pública de imagen (jpg, png, etc)
            
        Returns:
            Dict con texto extraído
        """
        try:
            response = self.client.ocr.process(
                model=self.model,
                document={
                    "type": "image_url",
                    "image_url": url_imagen
                }
            )
            
            texto = response.pages[0].markdown if response.pages else ""
            
            return {
                "exito": True,
                "texto": texto,
                "paginas": len(response.pages),
                "modelo": response.model,
                "error": ""
            }
            
        except Exception as e:
            return {
                "exito": False,
                "texto": "",
                "paginas": 0,
                "modelo": self.model,
                "error": f"Error OCR: {str(e)}"
            }
    
    def procesar_imagen_base64(self, imagen_base64: str, tipo_mime: str = "image/jpeg") -> dict:
        """
        Procesa una imagen desde base64
        
        Args:
            imagen_base64: Imagen codificada en base64
            tipo_mime: Tipo MIME (image/jpeg, image/png, etc)
            
        Returns:
            Dict con texto extraído
        """
        try:
            response = self.client.ocr.process(
                model=self.model,
                document={
                    "type": "image_url",
                    "image_url": f"data:{tipo_mime};base64,{imagen_base64}"
                }
            )
            
            texto = response.pages[0].markdown if response.pages else ""
            
            return {
                "exito": True,
                "texto": texto,
                "paginas": len(response.pages),
                "modelo": response.model,
                "error": ""
            }
            
        except Exception as e:
            return {
                "exito": False,
                "texto": "",
                "paginas": 0,
                "modelo": self.model,
                "error": f"Error OCR: {str(e)}"
            }


# Crear instancia global
try:
    mistral_ocr = MistralDocumentAIOCR()
except ValueError as e:
    print(f"⚠️ Advertencia: {e}")
    mistral_ocr = None

