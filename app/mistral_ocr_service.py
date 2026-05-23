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
        Procesa un PDF desde base64.

        Returns dict con:
          exito, texto, paginas, modelo, error  — compatibles con el resto del backend
          raw_pages  — lista completa por página: markdown, tables, images (bboxes), dimensions
          usage_info — pages_processed, doc_size_bytes
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
            raw_pages = []

            for page in response.pages:
                md = page.markdown or ""

                # ── Recopila contenido de tablas (SDK v2.x: .content; v1.x: .markdown) ──
                # Los soportes de incapacidad vienen en 3 formatos:
                #   1. Foto/escaneado   → Mistral OCR ya extrae texto en page.markdown
                #   2. PDF digital con tablas → page.markdown tiene [tbl-N.md](tbl-N.md)
                #                               y el contenido real está en page.tables
                #   3. PDF texto simple  → page.markdown tiene el texto directamente
                # En todos los casos extraemos TODO el contenido disponible.
                tablas_contenido = []  # (id, contenido) para fallback
                if hasattr(page, "tables") and page.tables:
                    for tabla in page.tables:
                        tabla_id = getattr(tabla, "id", None)
                        # SDK mistralai v2.x usa 'content'; v1.x usaba 'markdown'
                        tabla_contenido = (
                            getattr(tabla, "content", None)
                            or getattr(tabla, "markdown", None)
                            or ""
                        )
                        if tabla_id and tabla_contenido:
                            tablas_contenido.append((tabla_id, tabla_contenido))
                            # Reemplazar referencia en markdown (todos los formatos posibles)
                            for ref_id in [tabla_id, f"{tabla_id}.md"]:
                                md = md.replace(f"![{ref_id}]({ref_id})", tabla_contenido)
                                md = md.replace(f"[{ref_id}]({ref_id})", tabla_contenido)

                # ── Fallback garantizado: si aún quedan referencias sin resolver ──
                # (ocurre cuando el ID en el markdown no coincide exactamente con tabla.id)
                # Agregar el contenido de todas las tablas al final del texto
                import re as _re
                referencias_pendientes = _re.findall(r'\[tbl-\d+(?:\.md)?\]\([^)]+\)', md)
                if referencias_pendientes and tablas_contenido:
                    contenidos_extra = "\n\n".join(c for _, c in tablas_contenido)
                    md = md + "\n\n" + contenidos_extra

                # ── Fallback extra: si el markdown está vacío/mínimo pero hay tablas ──
                # (casos donde page.markdown = "" y todo el contenido está en tables)
                if len(md.strip()) < 30 and tablas_contenido:
                    md = "\n\n".join(c for _, c in tablas_contenido)

                textos_paginas.append(md)

                page_dict = {
                    "index": page.index,
                    "markdown": md,  # Texto final con tablas expandidas
                }
                if hasattr(page, "images") and page.images:
                    page_dict["images"] = [
                        {
                            "id": img.id,
                            "top_left_x": img.top_left_x,
                            "top_left_y": img.top_left_y,
                            "bottom_right_x": img.bottom_right_x,
                            "bottom_right_y": img.bottom_right_y,
                        }
                        for img in page.images
                    ]
                if tablas_contenido:
                    # Guardar con el campo correcto 'content' para raw_pages
                    page_dict["tables"] = [
                        {"id": tid, "content": tc}
                        for tid, tc in tablas_contenido
                    ]
                if hasattr(page, "dimensions") and page.dimensions:
                    d = page.dimensions
                    page_dict["dimensions"] = {
                        "dpi": getattr(d, "dpi", None),
                        "height": getattr(d, "height", None),
                        "width": getattr(d, "width", None),
                    }
                raw_pages.append(page_dict)

            usage = {}
            if hasattr(response, "usage_info") and response.usage_info:
                u = response.usage_info
                usage = {
                    "pages_processed": getattr(u, "pages_processed", None),
                    "doc_size_bytes": getattr(u, "doc_size_bytes", None),
                }

            texto_final = "\n\n---\n\n".join(textos_paginas)

            return {
                "exito": True,
                "texto": texto_final,
                "paginas": len(response.pages),
                "modelo": response.model,
                "error": "",
                "raw_pages": raw_pages,
                "usage_info": usage,
            }


        except Exception as e:
            return {
                "exito": False,
                "texto": "",
                "paginas": 0,
                "modelo": self.model,
                "error": f"Error OCR: {str(e)}",
                "raw_pages": [],
                "usage_info": {},
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

