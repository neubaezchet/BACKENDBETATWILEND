"""
✨ Editor PDF Avanzado con IA de Mejora de Calidad
IncaNeurobaeza - 2026

Bibliotecas usadas (todas gratuitas y enterprise-grade):
- PyMuPDF (fitz) → Manipulación PDF ultra-rápida
- OpenCV → Procesamiento de imagen profesional
- scikit-image → Algoritmos avanzados de mejora
- Pillow → Conversión de formatos
- numpy → Operaciones matriciales
"""

import os
import io
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageEnhance
from pathlib import Path
import fitz  # PyMuPDF
from skimage import exposure, filters, restoration
from typing import List, Tuple, Optional


class PDFEnhancer:
    """
    🎨 Mejorador de calidad de imagen para documentos
    Algoritmos de última generación para mejorar legibilidad
    """
    
    @staticmethod
    def enhance_image_quality(image_array: np.ndarray, scale: float = 2.5) -> np.ndarray:
        """
        ✨ Mejora dramáticamente la calidad de una imagen de documento
        
        Algoritmos:
        - Reducción de ruido adaptativa (Non-Local Means Denoising)
        - CLAHE (Contrast Limited Adaptive Histogram Equalization)
        - Unsharp masking para nitidez
        - Corrección de iluminación desigual
        - Binarización adaptativa Gaussian
        - Morfología para limpieza
        - Super-resolution con bicúbica
        """
        # Convertir a escala de grises si es necesario
        if len(image_array.shape) == 3:
            gray = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
        else:
            gray = image_array.copy()
        
        # 1. Reducción de ruido adaptativa (más agresiva)
        denoised = cv2.fastNlMeansDenoising(
            gray, 
            None, 
            h=12,  # Más fuerte
            templateWindowSize=7, 
            searchWindowSize=21
        )
        
        # 2. Mejora de contraste adaptativa (CLAHE)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8,8))
        enhanced = clahe.apply(denoised)
        
        # 3. Unsharp masking (enfoque profesional)
        gaussian = cv2.GaussianBlur(enhanced, (0, 0), 2.0)
        sharpened = cv2.addWeighted(enhanced, 1.5, gaussian, -0.5, 0)
        
        # 4. Corrección de iluminación desigual
        dilated = cv2.dilate(sharpened, np.ones((7,7), np.uint8))
        bg = cv2.medianBlur(dilated, 21)
        diff = 255 - cv2.absdiff(sharpened, bg)
        normalized = cv2.normalize(
            diff, None, 
            alpha=0, beta=255, 
            norm_type=cv2.NORM_MINMAX, 
            dtype=cv2.CV_8UC1
        )
        
        # 5. Binarización adaptativa para texto ultra-nítido
        binary = cv2.adaptiveThreshold(
            normalized, 255, 
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 
            blockSize=11, 
            C=2
        )
        
        # 6. Morfología para limpiar ruido residual
        kernel_morph = np.ones((2,2), np.uint8)
        cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel_morph)
        
        # 7. Upscaling con interpolación bicúbica (super-resolution)
        height, width = cleaned.shape
        new_width = int(width * scale)
        new_height = int(height * scale)
        upscaled = cv2.resize(
            cleaned, 
            (new_width, new_height), 
            interpolation=cv2.INTER_CUBIC
        )
        
        # 8. Suavizado final para anti-aliasing
        final = cv2.GaussianBlur(upscaled, (3,3), 0)
        
        return final
    
    @staticmethod
    def auto_deskew(image_array: np.ndarray) -> np.ndarray:
        """
        🔄 Corrige automáticamente la inclinación del documento
        Usa Hough Transform para detectar líneas dominantes
        """
        gray = image_array if len(image_array.shape) == 2 else cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
        
        # Detectar bordes con Canny
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        
        # Detectar líneas con Hough Transform
        lines = cv2.HoughLines(edges, 1, np.pi/180, 200)
        
        if lines is not None:
            angles = []
            for rho, theta in lines[:, 0]:
                angle = np.degrees(theta) - 90
                angles.append(angle)
            
            # Usar la mediana para robustez
            median_angle = np.median(angles)
            
            # Solo rotar si hay inclinación significativa (> 0.5°)
            if abs(median_angle) > 0.5:
                (h, w) = gray.shape[:2]
                center = (w // 2, h // 2)
                M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
                rotated = cv2.warpAffine(
                    gray, M, (w, h), 
                    flags=cv2.INTER_CUBIC, 
                    borderMode=cv2.BORDER_REPLICATE
                )
                return rotated
        
        return gray
    
    @staticmethod
    def smart_crop(image_array: np.ndarray, margin: int = 10) -> np.ndarray:
        """
        ✂️ Recorte inteligente eliminando bordes vacíos
        Detecta contenido real y elimina espacios en blanco
        """
        # Convertir a escala de grises
        if len(image_array.shape) == 3:
            gray = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
        else:
            gray = image_array.copy()
        
        # Binarizar con Otsu (umbral automático)
        _, binary = cv2.threshold(
            gray, 0, 255, 
            cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
        )
        
        # Encontrar contornos
        contours, _ = cv2.findContours(
            binary, 
            cv2.RETR_EXTERNAL, 
            cv2.CHAIN_APPROX_SIMPLE
        )
        
        if contours:
            # Encontrar el rectángulo que contiene todo el contenido
            all_contours = np.concatenate(contours)
            x, y, w, h = cv2.boundingRect(all_contours)
            
            # Agregar margen de seguridad
            x = max(0, x - margin)
            y = max(0, y - margin)
            w = min(gray.shape[1] - x, w + 2*margin)
            h = min(gray.shape[0] - y, h + 2*margin)
            
            # Recortar
            cropped = image_array[y:y+h, x:x+w]
            return cropped
        
        return image_array
    
    @staticmethod
    def aplicar_filtro(image_array: np.ndarray, filtro_tipo: str) -> np.ndarray:
        """
        🎨 Aplica filtros profesionales de imagen
        
        Filtros disponibles:
        - grayscale: Escala de grises
        - contrast: Mejora de contraste adaptativa
        - brightness: Aumento de brillo
        - sharpen: Enfoque agresivo
        - denoise: Reducción de ruido
        - invert: Invertir colores (para escaneos negativos)
        """
        if filtro_tipo == 'grayscale':
            if len(image_array.shape) == 3:
                return cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
            return image_array
        
        elif filtro_tipo == 'contrast':
            # CLAHE en canal L de LAB
            if len(image_array.shape) == 2:
                # Ya es escala de grises
                clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
                return clahe.apply(image_array)
            else:
                lab = cv2.cvtColor(image_array, cv2.COLOR_BGR2LAB)
                l, a, b = cv2.split(lab)
                clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
                l = clahe.apply(l)
                enhanced = cv2.merge([l, a, b])
                return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
        
        elif filtro_tipo == 'brightness':
            # Aumentar brillo en HSV
            if len(image_array.shape) == 2:
                return cv2.add(image_array, 30)
            else:
                hsv = cv2.cvtColor(image_array, cv2.COLOR_BGR2HSV)
                h, s, v = cv2.split(hsv)
                v = cv2.add(v, 30)
                enhanced = cv2.merge([h, s, v])
                return cv2.cvtColor(enhanced, cv2.COLOR_HSV2BGR)
        
        elif filtro_tipo == 'sharpen':
            # Kernel de enfoque agresivo
            kernel = np.array([[-1,-1,-1],
                              [-1, 9,-1],
                              [-1,-1,-1]])
            return cv2.filter2D(image_array, -1, kernel)
        
        elif filtro_tipo == 'denoise':
            # Non-Local Means Denoising
            if len(image_array.shape) == 2:
                return cv2.fastNlMeansDenoising(image_array, None, h=10)
            else:
                return cv2.fastNlMeansDenoisingColored(image_array, None, 10, 10, 7, 21)
        
        elif filtro_tipo == 'invert':
            return cv2.bitwise_not(image_array)
        
        return image_array


class PDFEditor:
    """
    📄 Editor completo de PDF con todas las funcionalidades profesionales
    """
    
    def __init__(self, pdf_path: str):
        """Inicializa el editor con un archivo PDF"""
        self.pdf_path = pdf_path
        self.doc = fitz.open(pdf_path)
        self.modifications: List[str] = []
        self.enhancer = PDFEnhancer()
    
    def rotate_page(self, page_num: int, angle: int):
        """
        🔄 Rota una página específica
        angle: 90, 180, 270, o -90
        """
        if page_num < 0 or page_num >= len(self.doc):
            raise ValueError(f"Número de página inválido: {page_num}")
        
        page = self.doc[page_num]
        current_rotation = page.rotation
        new_rotation = (current_rotation + angle) % 360
        page.set_rotation(new_rotation)
        self.modifications.append(f"Rotated page {page_num} by {angle}°")
    
    def enhance_page_quality(self, page_num: int, scale: float = 2.5):
        """
        ✨ Mejora la calidad de una página específica
        scale: Factor de upscaling (1.8, 2.5, 3.5)
        """
        if page_num < 0 or page_num >= len(self.doc):
            raise ValueError(f"Número de página inválido: {page_num}")
        
        page = self.doc[page_num]
        
        # Renderizar página a imagen de alta resolución
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat)
        
        # Convertir a numpy array
        img_array = np.frombuffer(
            pix.samples, 
            dtype=np.uint8
        ).reshape(pix.height, pix.width, pix.n)
        
        # Mejorar calidad con algoritmos avanzados
        enhanced = self.enhancer.enhance_image_quality(img_array, scale=1.0)
        
        # Auto-deskew (corregir inclinación)
        enhanced = self.enhancer.auto_deskew(enhanced)
        
        # Convertir de vuelta a imagen PIL
        enhanced_pil = Image.fromarray(enhanced)
        
        # Crear nueva página con la imagen mejorada
        img_bytes = io.BytesIO()
        enhanced_pil.save(img_bytes, format='PNG', optimize=True, dpi=(300, 300))
        img_bytes.seek(0)
        
        # Reemplazar contenido de la página
        rect = page.rect
        page.clean_contents()
        page.insert_image(rect, stream=img_bytes.getvalue())
        
        self.modifications.append(f"Enhanced quality of page {page_num} (scale={scale})")
    
    def aplicar_filtro_imagen(self, page_num: int, filtro_tipo: str):
        """
        🎨 Aplica filtros de imagen a una página específica
        filtro_tipo: 'grayscale', 'contrast', 'brightness', 'sharpen', 'denoise', 'invert'
        """
        if page_num < 0 or page_num >= len(self.doc):
            raise ValueError(f"Número de página inválido: {page_num}")
        
        page = self.doc[page_num]
        
        # Renderizar página a imagen de alta resolución
        mat = fitz.Matrix(3.0, 3.0)
        pix = page.get_pixmap(matrix=mat)
        
        # Convertir a numpy array
        img_array = np.frombuffer(
            pix.samples, 
            dtype=np.uint8
        ).reshape(pix.height, pix.width, pix.n)
        
        # Aplicar filtro
        filtered = self.enhancer.aplicar_filtro(img_array, filtro_tipo)
        
        # Convertir a PIL
        if len(filtered.shape) == 2:
            # Escala de grises → Convertir a RGB para PDF
            filtered_pil = Image.fromarray(filtered).convert('RGB')
        else:
            filtered_pil = Image.fromarray(filtered)
        
        # Crear bytes
        img_bytes = io.BytesIO()
        filtered_pil.save(img_bytes, format='PNG', optimize=True)
        img_bytes.seek(0)
        
        # Reemplazar página
        rect = page.rect
        page.clean_contents()
        page.insert_image(rect, stream=img_bytes.getvalue())
        
        self.modifications.append(f"Applied {filtro_tipo} filter to page {page_num}")
    
    def auto_crop_page(self, page_num: int, margin: int = 10):
        """
        ✂️ Recorte automático inteligente
        Elimina bordes vacíos y centra el contenido
        """
        if page_num < 0 or page_num >= len(self.doc):
            raise ValueError(f"Número de página inválido: {page_num}")
        
        page = self.doc[page_num]
        
        # Renderizar a imagen
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        img_array = np.frombuffer(
            pix.samples, 
            dtype=np.uint8
        ).reshape(pix.height, pix.width, pix.n)
        
        # Recorte inteligente
        cropped = self.enhancer.smart_crop(img_array, margin)
        
        # Calcular nuevas dimensiones
        h_crop, w_crop = cropped.shape[:2]
        h_orig, w_orig = pix.height, pix.width
        
        # Calcular offset para centrar
        x_offset = (w_orig - w_crop) / 2
        y_offset = (h_orig - h_crop) / 2
        
        # Escalar de vuelta a coordenadas PDF
        scale = 1.0 / 2.0
        crop_rect = fitz.Rect(
            x_offset * scale, 
            y_offset * scale, 
            (x_offset + w_crop) * scale, 
            (y_offset + h_crop) * scale
        )
        
        # Aplicar recorte
        page.set_cropbox(crop_rect)
        
        self.modifications.append(f"Auto-cropped page {page_num}")
    
    def delete_pages(self, page_numbers: List[int]):
        """
        🗑️ Elimina múltiples páginas
        page_numbers: Lista de números de página (0-indexed)
        """
        # Ordenar descendente para eliminar sin afectar índices
        for page_num in sorted(page_numbers, reverse=True):
            if 0 <= page_num < len(self.doc):
                self.doc.delete_page(page_num)
                self.modifications.append(f"Deleted page {page_num}")
    
    def reorder_pages(self, new_order: List[int]):
        """
        🔀 Reordena las páginas según la lista proporcionada
        new_order: Lista como [2, 0, 1] para mover páginas
        """
        self.doc.select(new_order)
        self.modifications.append(f"Reordered pages: {new_order}")
    
    def save_changes(self, output_path: Optional[str] = None) -> str:
        """
        💾 Guarda los cambios en el PDF
        Aplica compresión y limpieza para optimizar tamaño
        """
        if output_path is None:
            output_path = self.pdf_path
        
        self.doc.save(
            output_path, 
            garbage=4,      # Máxima limpieza
            deflate=True,   # Compresión deflate
            clean=True,     # Limpiar contenido redundante
            pretty=False    # No pretty print (reduce tamaño)
        )
        self.doc.close()
        
        return output_path
    
    def get_modifications_log(self) -> List[str]:
        """📋 Retorna el log de modificaciones realizadas"""
        return self.modifications
    
    def __enter__(self):
        """Context manager support"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Cierra el documento al salir del contexto"""
        if hasattr(self, 'doc') and self.doc:
            self.doc.close()


class PDFAttachmentManager:
    """
    📎 Gestor de adjuntos para emails
    Crea imágenes recortadas y previews con resaltados
    """
    
    @staticmethod
    def create_highlight_image(
        pdf_path: str, 
        page_num: int, 
        coords: Tuple[float, float, float, float], 
        output_path: str
    ) -> str:
        """
        🖼️ Crea una imagen recortada y resaltada para adjuntar al email
        coords: (x1, y1, x2, y2) en coordenadas PDF
        """
        doc = fitz.open(pdf_path)
        
        try:
            page = doc[page_num]
            
            # Renderizar área específica en alta resolución
            mat = fitz.Matrix(3.0, 3.0)
            clip = fitz.Rect(coords)
            pix = page.get_pixmap(matrix=mat, clip=clip)
            
            # Convertir a PIL
            img_array = np.frombuffer(
                pix.samples, 
                dtype=np.uint8
            ).reshape(pix.height, pix.width, pix.n)
            img = Image.fromarray(img_array)
            
            # Agregar borde rojo grueso
            draw = ImageDraw.Draw(img)
            draw.rectangle(
                [0, 0, img.width-1, img.height-1], 
                outline='red', 
                width=8
            )
            
            # Guardar
            img.save(output_path, 'PNG', optimize=True)
            
            return output_path
        
        finally:
            doc.close()
    
    @staticmethod
    def create_page_preview(
        pdf_path: str, 
        page_num: int, 
        output_path: str, 
        highlight_areas: Optional[List[Tuple]] = None
    ) -> str:
        """
        📄 Crea un preview de una página completa con áreas resaltadas
        highlight_areas: Lista de tuplas (x1, y1, x2, y2)
        """
        doc = fitz.open(pdf_path)
        
        try:
            page = doc[page_num]
            
            # Renderizar página
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat)
            
            # Convertir a PIL
            img = Image.frombuffer(
                'RGB', 
                [pix.width, pix.height], 
                pix.samples, 
                'raw', 'RGB', 0, 1
            )
            
            # Agregar resaltados si los hay
            if highlight_areas:
                draw = ImageDraw.Draw(img)
                for area in highlight_areas:
                    x1, y1, x2, y2 = area
                    # Escalar coordenadas según la matriz (2x)
                    x1, y1, x2, y2 = x1*2, y1*2, x2*2, y2*2
                    draw.rectangle(
                        [x1, y1, x2, y2], 
                        outline='red', 
                        width=5
                    )
            
            # Guardar
            img.save(output_path, 'PNG', optimize=True)
            
            return output_path
        
        finally:
            doc.close()
