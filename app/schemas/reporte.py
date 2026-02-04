"""
SCHEMAS PARA REPORTES
Modelos Pydantic para validación y respuestas
"""

from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class FiltrosExportacion(BaseModel):
    """Filtros para exportación de datos"""
    empresa: str = "all"
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None
    estados: Optional[str] = None
    tipos: Optional[str] = None
    incluir_historial: bool = False


class EstadisticasEstado(BaseModel):
    """Estadísticas por estado"""
    estado: str
    cantidad: int
    porcentaje: float


class CasoResumen(BaseModel):
    """Resumen de un caso para tabla viva"""
    id: int
    serial: str
    empresa: str
    empleado: str
    tipo: str
    estado: str
    fecha_creacion: str
    dias: Optional[int] = None


class TablaVivaResponse(BaseModel):
    """Respuesta de tabla viva"""
    total_casos: int
    periodo: str
    empresa: str
    estadisticas_estados: List[EstadisticasEstado]
    ultimos_casos: List[CasoResumen]
    fecha_actualizacion: str


class PreviewExportResponse(BaseModel):
    """Preview de exportación"""
    total_registros: int
    registros_preview: List[Dict[str, Any]]
    periodo: str
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None


class RegenerarTablaResponse(BaseModel):
    """Respuesta de regeneración de tabla"""
    exito: bool
    casos_archivados: int
    mensaje: str
    fecha_proceso: str
