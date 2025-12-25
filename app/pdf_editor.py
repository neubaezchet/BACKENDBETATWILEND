
Editor PDF Avanzado con Mejora de Calidad de Imagen
IncaNeurobaeza - 2024


import os
import io
import numpy as np
import cv2
from PIL import Image
from pathlib import Path
import fitz  # PyMuPDF
from skimage import exposure, restoration
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader

class PDFEnhancer
    Mejorador de calidad de imagen para documentos
    
    @staticmethod
    def enhance_image_quality(image_array)
        
        Mejora dramáticamente la calidad de una imagen de documento
        Inspirado en enhancers como artguru.ai pero optimizado para texto
        
        # Convertir a escala de grises si es necesario
        if len(image_array.shape) == 3
            gray = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
        else
            gray = image_array.copy()
        
        # 1. Reducción de ruido adaptativa
        denoised = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)
        
        # 2. Mejora de contraste adaptativa (CLAHE)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        enhanced = clahe.apply(denoised)
        
        # 3. Sharpening (enfoque)
        kernel = np.array([[-1,-1,-1],
                          [-1, 9,-1],
                          [-1,-1,-1]])
        sharpened = cv2.filter2D(enhanced, -1, kernel)
        
        # 4. Corrección de iluminación desigual
        dilated = cv2.dilate(sharpened, np.ones((7,7), np.uint8))
        bg = cv2.medianBlur(dilated, 21)
        diff = 255 - cv2.absdiff(sharpened, bg)
        normalized = cv2.normalize(diff, None, alpha=0, beta=255, 
                                   norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_8UC1)
        
        # 5. Binarización adaptativa para texto ultra-nítido
        binary = cv2.adaptiveThreshold(normalized, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY, 11, 2)
        
        # 6. Morfología para limpiar ruido residual
        kernel_morph = np.ones((2,2), np.uint8)
        cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel_morph)
        
        # 7. Upscaling con interpolación bicúbica (simula super-resolution)
        height, width = cleaned.shape
        upscaled = cv2.resize(cleaned, (width2, height2), interpolation=cv2.INTER_CUBIC)
        
        # 8. Suavizado final para anti-aliasing
        final = cv2.GaussianBlur(upscaled, (3,3), 0)
        
        return final
    
    @staticmethod
    def auto_deskew(image_array)
        Corrige automáticamente la inclinación del documento
        gray = image_array if len(image_array.shape) == 2 else cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
        
        # Detectar bordes
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        
        # Detectar líneas
        lines = cv2.HoughLines(edges, 1, np.pi180, 200)
        
        if lines is not None
            angles = []
            for rho, theta in lines[, 0]
                angle = np.degrees(theta) - 90
                angles.append(angle)
            
            median_angle = np.median(angles)
            
            # Rotar la imagen
            if abs(median_angle)  0.5  # Solo rotar si hay inclinación significativa
                (h, w) = gray.shape
                center = (w  2, h  2)
                M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
                rotated = cv2.warpAffine(gray, M, (w, h), 
                                        flags=cv2.INTER_CUBIC, 
                                        borderMode=cv2.BORDER_REPLICATE)
                return rotated
        
        return gray
    
    @staticmethod
    def smart_crop(image_array, margin=10)
        Recorte inteligente eliminando bordes vacíos
        # Convertir a escala de grises
        if len(image_array.shape) == 3
            gray = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
        else
            gray = image_array.copy()
        
        # Binarizar
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        
        # Encontrar contornos
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if contours
            # Encontrar el rectángulo que contiene todo el contenido
            x, y, w, h = cv2.boundingRect(np.concatenate(contours))
            
            # Agregar margen
            x = max(0, x - margin)
            y = max(0, y - margin)
            w = min(gray.shape[1] - x, w + 2margin)
            h = min(gray.shape[0] - y, h + 2margin)
            
            # Recortar
            cropped = image_array[yy+h, xx+w]
            return cropped
        
        return image_array


class PDFEditor
    Editor completo de PDF con todas las funcionalidades
    
    def __init__(self, pdf_path)
        self.pdf_path = pdf_path
        self.doc = fitz.open(pdf_path)
        self.modifications = []
    
    def rotate_page(self, page_num, angle)
        Rota una página específica
        page = self.doc[page_num]
        page.set_rotation(angle)
        self.modifications.append(fRotated page {page_num} by {angle}°)
    
    def enhance_page_quality(self, page_num)
        Mejora la calidad de una página específica
        page = self.doc[page_num]
        
        # Renderizar página a imagen de alta resolución
        mat = fitz.Matrix(3.0, 3.0)  # 3x zoom para mejor calidad
        pix = page.get_pixmap(matrix=mat)
        
        # Convertir a numpy array
        img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        
        # Mejorar calidad
        enhancer = PDFEnhancer()
        enhanced = enhancer.enhance_image_quality(img_array)
        
        # Auto-deskew
        enhanced = enhancer.auto_deskew(enhanced)
        
        # Convertir de vuelta a imagen PIL
        enhanced_pil = Image.fromarray(enhanced)
        
        # Crear nueva página con la imagen mejorada
        img_bytes = io.BytesIO()
        enhanced_pil.save(img_bytes, format='PNG', optimize=True)
        img_bytes.seek(0)
        
        # Reemplazar página original
        rect = page.rect
        page.insert_image(rect, stream=img_bytes.getvalue())
        
        self.modifications.append(fEnhanced quality of page {page_num})
    
    def crop_page_custom(self, page_num, x, y, width, height)
        Recorte personalizado con coordenadas específicas
        page = self.doc[page_num]
        
        # Crear rectángulo de recorte
        crop_rect = fitz.Rect(x, y, x + width, y + height)
        
        # Aplicar recorte
        page.set_cropbox(crop_rect)
        
        self.modifications.append(fCustom crop on page {page_num} ({x},{y},{width},{height}))
    
    def auto_crop_page(self, page_num, margin=10)
        Recorte automático inteligente
        page = self.doc[page_num]
        
        # Renderizar a imagen
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        
        # Recorte inteligente
        enhancer = PDFEnhancer()
        cropped = enhancer.smart_crop(img_array, margin)
        
        # Calcular nuevas dimensiones
        h_orig, w_orig = pix.height, pix.width
        h_crop, w_crop = cropped.shape[2]
        
        x = (w_orig - w_crop)  2
        y = (h_orig - h_crop)  2
        
        # Aplicar recorte
        crop_rect = fitz.Rect(x2, y2, (x+w_crop)2, (y+h_crop)2)
        page.set_cropbox(crop_rect)
        
        self.modifications.append(fAuto-cropped page {page_num})
    
    def reorder_pages(self, new_order)
        Reordena las páginas según la lista proporcionada
        # new_order es una lista como [2, 0, 1] para mover páginas
        self.doc.select(new_order)
        self.modifications.append(fReordered pages {new_order})
    
    def delete_page(self, page_num)
        Elimina una página
        self.doc.delete_page(page_num)
        self.modifications.append(fDeleted page {page_num})
    
    def add_annotation(self, page_num, annotation_type, coords, text=, color=(1, 0, 0))
        
        Agrega anotaciones al PDF
        annotation_type 'highlight', 'text', 'arrow', 'rectangle'
        coords (x1, y1, x2, y2)
        
        page = self.doc[page_num]
        
        if annotation_type == 'highlight'
            # Resaltado
            highlight = page.add_highlight_annot(fitz.Rect(coords))
            highlight.set_colors(stroke=color)
            highlight.update()
        
        elif annotation_type == 'text'
            # Nota de texto
            annot = page.add_text_annot(fitz.Point(coords[0], coords[1]), text)
            annot.set_colors(stroke=color)
            annot.update()
        
        elif annotation_type == 'rectangle'
            # Rectángulo
            annot = page.add_rect_annot(fitz.Rect(coords))
            annot.set_colors(stroke=color)
            annot.set_border(width=2)
            annot.update()
        
        elif annotation_type == 'arrow'
            # Flecha
            annot = page.add_line_annot(fitz.Point(coords[0], coords[1]), 
                                       fitz.Point(coords[2], coords[3]))
            annot.set_colors(stroke=color)
            annot.set_border(width=2)
            annot.line_ends = (fitz.PDF_ANNOT_LE_NONE, fitz.PDF_ANNOT_LE_CLOSED_ARROW)
            annot.update()
        
        self.modifications.append(fAdded {annotation_type} annotation on page {page_num})
    
    def save_changes(self, output_path=None)
        Guarda los cambios en el PDF
        if output_path is None
            output_path = self.pdf_path
        
        self.doc.save(output_path, garbage=4, deflate=True, clean=True)
        self.doc.close()
        
        return output_path
    
    def get_modifications_log(self)
        Retorna el log de modificaciones realizadas
        return self.modifications

def aplicar_filtro_imagen(self, page_num, filtro_tipo):
        """
        Aplica filtros de imagen a una página específica
        filtro_tipo: 'grayscale', 'contrast', 'brightness', 'sharpen'
        """
        page = self.doc[page_num]
        
        # Renderizar página a imagen de alta resolución
        mat = fitz.Matrix(3.0, 3.0)
        pix = page.get_pixmap(matrix=mat)
        
        # Convertir a numpy array
        img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        
        # Aplicar filtro según tipo
        if filtro_tipo == 'grayscale':
            if len(img_array.shape) == 3:
                filtered = cv2.cvtColor(img_array, cv2.COLOR_BGR2GRAY)
                filtered = cv2.cvtColor(filtered, cv2.COLOR_GRAY2BGR)
            else:
                filtered = img_array
        
        elif filtro_tipo == 'contrast':
            # Mejora de contraste adaptativa
            lab = cv2.cvtColor(img_array, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
            l = clahe.apply(l)
            filtered = cv2.merge([l, a, b])
            filtered = cv2.cvtColor(filtered, cv2.COLOR_LAB2BGR)
        
        elif filtro_tipo == 'brightness':
            # Aumentar brillo
            hsv = cv2.cvtColor(img_array, cv2.COLOR_BGR2HSV)
            h, s, v = cv2.split(hsv)
            v = cv2.add(v, 30)
            filtered = cv2.merge([h, s, v])
            filtered = cv2.cvtColor(filtered, cv2.COLOR_HSV2BGR)
        
        elif filtro_tipo == 'sharpen':
            # Aplicar enfoque
            kernel = np.array([[-1,-1,-1],
                              [-1, 9,-1],
                              [-1,-1,-1]])
            filtered = cv2.filter2D(img_array, -1, kernel)
        
        else:
            filtered = img_array
        
        # Convertir a PIL y actualizar página
        filtered_pil = Image.fromarray(filtered)
        
        img_bytes = io.BytesIO()
        filtered_pil.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        
        # Reemplazar página
        rect = page.rect
        page.clean_contents()
        page.insert_image(rect, stream=img_bytes.getvalue())
        
        self.modifications.append(f"Applied {filtro_tipo} filter to page {page_num}")
        
class PDFAttachmentManager
    Gestor de adjuntos para emails (imágenes recortadas, anotaciones)
    
    @staticmethod
    def create_highlight_image(pdf_path, page_num, coords, output_path)
        
        Crea una imagen recortada y resaltada para adjuntar al email
        
        doc = fitz.open(pdf_path)
        page = doc[page_num]
        
        # Renderizar área específica
        mat = fitz.Matrix(3.0, 3.0)  # Alta resolución
        clip = fitz.Rect(coords)
        pix = page.get_pixmap(matrix=mat, clip=clip)
        
        # Convertir a PIL para agregar borde rojo
        img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        img = Image.fromarray(img_array)
        
        # Agregar borde rojo grueso
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, img.width-1, img.height-1], outline='red', width=5)
        
        # Guardar
        img.save(output_path, 'PNG')
        doc.close()
        
        return output_path
    
    @staticmethod
    def create_page_preview(pdf_path, page_num, output_path, highlight_areas=None)
        
        Crea un preview de una página completa con áreas resaltadas
        
        doc = fitz.open(pdf_path)
        page = doc[page_num]
        
        # Renderizar página
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        
        # Convertir a PIL
        img = Image.frombuffer(RGB, [pix.width, pix.height], pix.samples, raw, RGB, 0, 1)
        
        # Agregar resaltados si los hay
        if highlight_areas
            draw = ImageDraw.Draw(img)
            for area in highlight_areas
                x1, y1, x2, y2 = area
                # Escalar coordenadas según la matriz
                x1, y1, x2, y2 = x12, y12, x22, y22
                draw.rectangle([x1, y1, x2, y2], outline='red', width=5)
        
        img.save(output_path, 'PNG')
        doc.close()
        
        return output_path