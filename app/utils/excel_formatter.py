"""
FORMATEADOR DE EXCEL
Utilidades para exportar a Excel, CSV y JSON con formato profesional
"""

import pandas as pd
from io import BytesIO
import json
from typing import Any
import logging

logger = logging.getLogger(__name__)


class ExcelFormatter:
    """Formateador para exportaciones de datos"""
    
    @staticmethod
    def crear_excel(df: pd.DataFrame, titulo: str = "Reporte") -> bytes:
        """
        Crea archivo Excel con formato profesional
        
        Args:
            df: DataFrame con datos
            titulo: Título del reporte
        
        Returns:
            Bytes del archivo Excel
        """
        try:
            output = BytesIO()
            
            # Crear writer de Excel
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                # Escribir DataFrame
                df.to_excel(writer, sheet_name='Datos', index=False)
                
                # Obtener workbook y worksheet
                workbook = writer.book
                worksheet = writer.sheets['Datos']
                
                # Aplicar formato a encabezados
                for cell in worksheet[1]:
                    cell.font = cell.font.copy(bold=True)
                    cell.fill = cell.fill.copy(patternType="solid", fgColor="1F4E78")
                    cell.font = cell.font.copy(color="FFFFFF")
                
                # Ajustar ancho de columnas
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = min(max_length + 2, 50)
                    worksheet.column_dimensions[column_letter].width = adjusted_width
            
            output.seek(0)
            return output.read()
        
        except Exception as e:
            logger.error(f"Error creando Excel: {str(e)}")
            raise
    
    @staticmethod
    def crear_csv(df: pd.DataFrame) -> bytes:
        """
        Crea archivo CSV
        
        Args:
            df: DataFrame con datos
        
        Returns:
            Bytes del archivo CSV
        """
        try:
            output = BytesIO()
            df.to_csv(output, index=False, encoding='utf-8-sig')
            output.seek(0)
            return output.read()
        
        except Exception as e:
            logger.error(f"Error creando CSV: {str(e)}")
            raise
    
    @staticmethod
    def crear_json(df: pd.DataFrame) -> bytes:
        """
        Crea archivo JSON
        
        Args:
            df: DataFrame con datos
        
        Returns:
            Bytes del archivo JSON
        """
        try:
            # Convertir DataFrame a dict y luego a JSON
            datos = df.to_dict(orient='records')
            json_str = json.dumps(datos, ensure_ascii=False, indent=2)
            return json_str.encode('utf-8')
        
        except Exception as e:
            logger.error(f"Error creando JSON: {str(e)}")
            raise
