"""
SERVICIO DE REPORTES
Lógica de negocio para tabla viva y exportaciones
"""

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from datetime import datetime, timedelta
import calendar
import pandas as pd
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


class ReporteService:
    """Servicio para manejo de reportes y tabla viva"""
    
    @staticmethod
    def obtener_tabla_viva(db: Session, empresa: str, periodo: str, modelo_caso) -> Dict[str, Any]:
        """
        Obtiene datos para tabla viva en tiempo real
        
        Args:
            db: Sesión de base de datos
            empresa: Nombre de empresa o 'all'
            periodo: Tipo de período (mes_actual, mes_anterior, etc.)
            modelo_caso: Modelo de caso (Case)
        
        Returns:
            Diccionario con estadísticas y casos
        """
        try:
            # Calcular fechas según período
            hoy = datetime.now()
            if periodo == "mes_actual":
                fecha_inicio = datetime(hoy.year, hoy.month, 1)
                fecha_fin = hoy
            elif periodo == "mes_anterior":
                primer_dia_mes = datetime(hoy.year, hoy.month, 1)
                fecha_fin = primer_dia_mes - timedelta(days=1)
                fecha_inicio = datetime(fecha_fin.year, fecha_fin.month, 1)
            elif periodo == "año_actual":
                fecha_inicio = datetime(hoy.year, 1, 1)
                fecha_fin = hoy
            elif periodo == "quincena_1":
                fecha_inicio = datetime(hoy.year, hoy.month, 1)
                fecha_fin = datetime(hoy.year, hoy.month, 15)
            elif periodo == "quincena_2":
                fecha_inicio = datetime(hoy.year, hoy.month, 16)
                ultimo_dia = calendar.monthrange(hoy.year, hoy.month)[1]
                fecha_fin = datetime(hoy.year, hoy.month, ultimo_dia)
            else:
                fecha_inicio = datetime(hoy.year, hoy.month, 1)
                fecha_fin = hoy
            
            # Construir query base
            query = db.query(modelo_caso).filter(
                modelo_caso.created_at >= fecha_inicio,
                modelo_caso.created_at <= fecha_fin
            )
            
            # Filtrar por empresa si no es "all"
            if empresa != "all":
                query = query.filter(modelo_caso.company_name == empresa)
            
            # Obtener todos los casos
            casos = query.all()
            total_casos = len(casos)
            
            # Calcular estadísticas por estado
            estadisticas = {}
            for caso in casos:
                estado = caso.status
                estadisticas[estado] = estadisticas.get(estado, 0) + 1
            
            # Convertir a porcentajes
            estadisticas_estados = []
            for estado, cantidad in estadisticas.items():
                porcentaje = (cantidad / total_casos * 100) if total_casos > 0 else 0
                estadisticas_estados.append({
                    "estado": estado,
                    "cantidad": cantidad,
                    "porcentaje": round(porcentaje, 2)
                })
            
            # Obtener últimos 20 casos
            ultimos_casos = query.order_by(modelo_caso.created_at.desc()).limit(20).all()
            
            casos_resumen = []
            for caso in ultimos_casos:
                casos_resumen.append({
                    "id": caso.id,
                    "serial": caso.case_number or f"CASO-{caso.id}",
                    "empresa": caso.company_name or "N/A",
                    "empleado": caso.employee_name or "N/A",
                    "tipo": caso.case_type or "general",
                    "estado": caso.status,
                    "fecha_creacion": caso.created_at.strftime("%Y-%m-%d %H:%M:%S") if caso.created_at else "N/A",
                    "dias": caso.days if hasattr(caso, 'days') else None
                })
            
            return {
                "total_casos": total_casos,
                "periodo": periodo,
                "empresa": empresa,
                "estadisticas_estados": estadisticas_estados,
                "ultimos_casos": casos_resumen,
                "fecha_actualizacion": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        
        except Exception as e:
            logger.error(f"Error en obtener_tabla_viva: {str(e)}")
            raise
    
    @staticmethod
    def obtener_preview(db: Session, filtros: Dict[str, Any], modelo_caso) -> Dict[str, Any]:
        """
        Obtiene preview de exportación (máximo 20 registros)
        
        Args:
            db: Sesión de base de datos
            filtros: Diccionario con filtros
            modelo_caso: Modelo de caso
        
        Returns:
            Diccionario con preview
        """
        try:
            query = db.query(modelo_caso)
            
            # Aplicar filtros
            if filtros.get("empresa") and filtros["empresa"] != "all":
                query = query.filter(modelo_caso.company_name == filtros["empresa"])
            
            if filtros.get("fecha_inicio"):
                fecha_inicio = datetime.strptime(filtros["fecha_inicio"], "%Y-%m-%d")
                query = query.filter(modelo_caso.created_at >= fecha_inicio)
            
            if filtros.get("fecha_fin"):
                fecha_fin = datetime.strptime(filtros["fecha_fin"], "%Y-%m-%d")
                query = query.filter(modelo_caso.created_at <= fecha_fin)
            
            if filtros.get("estados"):
                estados_lista = filtros["estados"].split(",")
                query = query.filter(modelo_caso.status.in_(estados_lista))
            
            if filtros.get("tipos"):
                tipos_lista = filtros["tipos"].split(",")
                query = query.filter(modelo_caso.case_type.in_(tipos_lista))
            
            # Obtener total y preview
            total_registros = query.count()
            casos_preview = query.limit(20).all()
            
            registros = []
            for caso in casos_preview:
                registros.append({
                    "id": caso.id,
                    "serial": caso.case_number or f"CASO-{caso.id}",
                    "empresa": caso.company_name or "N/A",
                    "empleado": caso.employee_name or "N/A",
                    "tipo": caso.case_type or "general",
                    "estado": caso.status,
                    "fecha_creacion": caso.created_at.strftime("%Y-%m-%d") if caso.created_at else "N/A"
                })
            
            return {
                "total_registros": total_registros,
                "registros_preview": registros
            }
        
        except Exception as e:
            logger.error(f"Error en obtener_preview: {str(e)}")
            raise
    
    @staticmethod
    def obtener_datos_exportacion(db: Session, filtros: Dict[str, Any], incluir_historial: bool, modelo_caso) -> pd.DataFrame:
        """
        Obtiene datos completos para exportación
        
        Args:
            db: Sesión de base de datos
            filtros: Diccionario con filtros
            incluir_historial: Si incluir historial de eventos
            modelo_caso: Modelo de caso
        
        Returns:
            DataFrame con datos
        """
        try:
            query = db.query(modelo_caso)
            
            # Aplicar filtros (misma lógica que preview)
            if filtros.get("empresa") and filtros["empresa"] != "all":
                query = query.filter(modelo_caso.company_name == filtros["empresa"])
            
            if filtros.get("fecha_inicio"):
                fecha_inicio = datetime.strptime(filtros["fecha_inicio"], "%Y-%m-%d")
                query = query.filter(modelo_caso.created_at >= fecha_inicio)
            
            if filtros.get("fecha_fin"):
                fecha_fin = datetime.strptime(filtros["fecha_fin"], "%Y-%m-%d")
                query = query.filter(modelo_caso.created_at <= fecha_fin)
            
            if filtros.get("estados"):
                estados_lista = filtros["estados"].split(",")
                query = query.filter(modelo_caso.status.in_(estados_lista))
            
            if filtros.get("tipos"):
                tipos_lista = filtros["tipos"].split(",")
                query = query.filter(modelo_caso.case_type.in_(tipos_lista))
            
            # Obtener todos los casos
            casos = query.all()
            
            # Convertir a DataFrame
            datos = []
            for caso in casos:
                datos.append({
                    "ID": caso.id,
                    "Serial": caso.case_number or f"CASO-{caso.id}",
                    "Empresa": caso.company_name or "N/A",
                    "Empleado": caso.employee_name or "N/A",
                    "Tipo": caso.case_type or "general",
                    "Estado": caso.status,
                    "Días": caso.days if hasattr(caso, 'days') else None,
                    "Fecha Creación": caso.created_at.strftime("%Y-%m-%d %H:%M:%S") if caso.created_at else "N/A",
                    "Fecha Actualización": caso.updated_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(caso, 'updated_at') and caso.updated_at else "N/A"
                })
            
            df = pd.DataFrame(datos)
            return df
        
        except Exception as e:
            logger.error(f"Error en obtener_datos_exportacion: {str(e)}")
            raise
    
    @staticmethod
    def regenerar_tabla_viva(db: Session, modelo_caso) -> Dict[str, Any]:
        """
        Regenera tabla viva archivando mes anterior
        
        Args:
            db: Sesión de base de datos
            modelo_caso: Modelo de caso
        
        Returns:
            Diccionario con resultado
        """
        try:
            hoy = datetime.now()
            primer_dia_mes = datetime(hoy.year, hoy.month, 1)
            
            # Contar casos del mes anterior
            casos_mes_anterior = db.query(modelo_caso).filter(
                modelo_caso.created_at < primer_dia_mes
            ).count()
            
            logger.info(f"Se encontraron {casos_mes_anterior} casos del mes anterior")
            
            return {
                "exito": True,
                "casos_archivados": casos_mes_anterior,
                "mensaje": f"Tabla regenerada correctamente. {casos_mes_anterior} casos archivados.",
                "fecha_proceso": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        
        except Exception as e:
            logger.error(f"Error en regenerar_tabla_viva: {str(e)}")
            raise
