import tempfile
import shutil
from pathlib import Path
from typing import List, Tuple
from fastapi import UploadFile
import fitz  # PyMuPDF
from PIL import Image
import io

async def merge_pdfs_from_uploads(archivos: List[UploadFile], cedula: str, tipo: str) -> Tuple[Path, List[str]]:
    """
    Combina múltiples archivos (PDF, imágenes) en un solo PDF SIN portada
    
    Args:
        archivos: Lista de archivos subidos
        cedula: Cédula del empleado
        tipo: Tipo de incapacidad
        
    Returns:
        Tuple con la ruta del PDF final y lista de nombres originales
    """
    if not archivos:
        raise ValueError("No se proporcionaron archivos")
    
    # Crear PDF de salida
    pdf_output = fitz.open()
    original_filenames = []
    temp_files = []
    
    try:
        for i, archivo in enumerate(archivos):
            if not archivo or not archivo.filename:
                continue
                
            original_filenames.append(archivo.filename)
            
            # Guardar archivo temporalmente
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(archivo.filename).suffix) as tmp:
                shutil.copyfileobj(archivo.file, tmp)
                temp_path = Path(tmp.name)
                temp_files.append(temp_path)
            
            # Resetear el archivo para próxima lectura si es necesario
            archivo.file.seek(0)
            
            # Procesar según el tipo de archivo
            file_extension = Path(archivo.filename).suffix.lower()
            
            if file_extension == '.pdf':
                # Agregar PDF existente
                pdf_input = fitz.open(temp_path)
                pdf_output.insert_pdf(pdf_input)
                pdf_input.close()
                
            elif file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp']:
                # Convertir imagen a PDF
                img_pdf = convert_image_to_pdf(temp_path)
                if img_pdf:
                    pdf_output.insert_pdf(img_pdf)
                    img_pdf.close()
                    
            elif file_extension in ['.doc', '.docx']:
                # Para documentos Word, crear una página indicativa
                page = pdf_output.new_page()
                text = f"Documento Word incluido:\n{archivo.filename}\n\nNota: Para ver el contenido completo, abrir el archivo original."
                page.insert_text((50, 50), text, fontsize=12)
                
            else:
                # Para otros tipos de archivo, crear página informativa
                page = pdf_output.new_page()
                text = f"Archivo adjunto:\n{archivo.filename}\n\nTipo: {file_extension}\nNota: Archivo no soportado para vista previa."
                page.insert_text((50, 50), text, fontsize=12)
    
    except Exception as e:
        # Limpiar archivos temporales en caso de error
        for temp_file in temp_files:
            temp_file.unlink(missing_ok=True)
        pdf_output.close()
        raise Exception(f"Error procesando archivos: {e}")
    
    finally:
        # Limpiar archivos temporales
        for temp_file in temp_files:
            temp_file.unlink(missing_ok=True)
    
    # Guardar PDF final (SIN portada)
    pdf_final_path = Path(tempfile.mktemp(suffix=f'_{cedula}_{tipo}.pdf'))
    pdf_output.save(pdf_final_path)
    pdf_output.close()
    
    return pdf_final_path, original_filenames


def convert_image_to_pdf(image_path: Path) -> fitz.Document:
    """Convierte una imagen a PDF usando PyMuPDF"""
    try:
        # Abrir imagen con PIL para mejor manejo
        with Image.open(image_path) as img:
            # Convertir a RGB si es necesario
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Guardar como bytes
            img_bytes = io.BytesIO()
            img.save(img_bytes, format='PDF')
            img_bytes.seek(0)
            
            # Crear PDF desde bytes
            pdf_doc = fitz.open(stream=img_bytes.getvalue(), filetype="pdf")
            return pdf_doc
            
    except Exception as e:
        print(f"Error convirtiendo imagen {image_path}: {e}")
        return None