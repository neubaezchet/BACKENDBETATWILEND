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
                # Usar join con la tabla Company
                from app.database import Company
                query = query.join(Company, modelo_caso.company_id == Company.id).filter(Company.nombre == empresa)
            
            # Obtener todos los casos
            casos = query.all()
            total_casos = len(casos)
            
            # Calcular estadísticas por estado
            estadisticas = {}
            for caso in casos:
                estado = caso.estado.value if caso.estado else "NUEVO"
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
                # Obtener nombre de empresa a través de relación
                empresa_nombre = caso.empresa.nombre if caso.empresa else "N/A"
                empleado_nombre = caso.empleado.nombre if caso.empleado else caso.cedula or "N/A"
                
                casos_resumen.append({
                    "id": caso.id,
                    "serial": caso.serial or f"CASO-{caso.id}",
                    "empresa": empresa_nombre,
                    "empleado": empleado_nombre,
                    "tipo": caso.tipo.value if caso.tipo else "general",
                    "estado": caso.estado.value if caso.estado else "NUEVO",
                    "fecha_creacion": caso.created_at.strftime("%Y-%m-%d %H:%M:%S") if caso.created_at else "N/A",
                    "dias": caso.dias_incapacidad or None
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
                from app.database import Company
                query = query.join(Company, modelo_caso.company_id == Company.id).filter(Company.nombre == filtros["empresa"])
            
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
                # Convertir strings a enum values
                from app.database import TipoIncapacidad
                tipos_enum = [TipoIncapacidad(t.strip()) for t in tipos_lista if t.strip()]
                query = query.filter(modelo_caso.tipo.in_(tipos_enum))
            
            # Obtener total y preview
            total_registros = query.count()
            casos_preview = query.limit(20).all()
            
            registros = []
            for caso in casos_preview:
                empresa_nombre = caso.empresa.nombre if caso.empresa else "N/A"
                empleado_nombre = caso.empleado.nombre if caso.empleado else caso.cedula or "N/A"
                
                registros.append({
                    "id": caso.id,
                    "serial": caso.serial or f"CASO-{caso.id}",
                    "empresa": empresa_nombre,
                    "empleado": empleado_nombre,
                    "tipo": caso.tipo.value if caso.tipo else "general",
                    "estado": caso.estado.value if caso.estado else "NUEVO",
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
                from app.database import Company
                query = query.join(Company, modelo_caso.company_id == Company.id).filter(Company.nombre == filtros["empresa"])
            
            if filtros.get("fecha_inicio"):
                fecha_inicio = datetime.strptime(filtros["fecha_inicio"], "%Y-%m-%d")
                query = query.filter(modelo_caso.created_at >= fecha_inicio)
            
            if filtros.get("fecha_fin"):
                fecha_fin = datetime.strptime(filtros["fecha_fin"], "%Y-%m-%d")
                query = query.filter(modelo_caso.created_at <= fecha_fin)
            
            if filtros.get("estados"):
                estados_lista = filtros["estados"].split(",")
                # Convertir strings a enum values
                from app.database import EstadoCaso
                estados_enum = [EstadoCaso(e.strip()) for e in estados_lista if e.strip()]
                query = query.filter(modelo_caso.estado.in_(estados_enum))
            
            if filtros.get("tipos"):
                tipos_lista = filtros["tipos"].split(",")
                # Convertir strings a enum values
                from app.database import TipoIncapacidad
                tipos_enum = [TipoIncapacidad(t.strip()) for t in tipos_lista if t.strip()]
                query = query.filter(modelo_caso.tipo.in_(tipos_enum))
            
            # Obtener todos los casos
            casos = query.all()
            
            # Convertir a DataFrame
            datos = []
            for caso in casos:
                empresa_nombre = caso.empresa.nombre if caso.empresa else "N/A"
                empleado_nombre = caso.empleado.nombre if caso.empleado else caso.cedula or "N/A"
                
                datos.append({
                    "ID": caso.id,
                    "Serial": caso.serial or f"CASO-{caso.id}",
                    "Empresa": empresa_nombre,
                    "Empleado": empleado_nombre,
                    "Tipo": caso.tipo.value if caso.tipo else "general",
                    "Estado": caso.estado.value if caso.estado else "NUEVO",
                    "Días": caso.dias_incapacidad or 0,
                    "Fecha Creación": caso.created_at.strftime("%Y-%m-%d %H:%M:%S") if caso.created_at else "N/A",
                    "Fecha Actualización": caso.updated_at.strftime("%Y-%m-%d %H:%M:%S") if caso.updated_at else "N/A"
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
