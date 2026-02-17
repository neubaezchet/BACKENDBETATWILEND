"""
Gestor de Carpeta Completes - Sincronización y Respaldos
IncaNeurobaeza - 2026

Funciones:
1. Copiar caso COMPLETO a Completes/{Empresa}/
2. Detectar cambios y crear ZIPs de respaldo (24h)
3. Auto-limpiar ZIPs expirados
"""

import re
import os
import zipfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from app.drive_uploader import get_authenticated_service, create_folder_if_not_exists
from app.database import SessionLocal, Case, EstadoCaso, Company


class CompletesManager:
    """Gestor de la carpeta operativa Completes"""
    
    def __init__(self):
        self.service = None
        self.completes_root_id = None
        self.respaldos_root_id = None

    def _get_service(self):
        """Obtiene servicio de Drive bajo demanda."""
        if self.service is None:
            self.service = get_authenticated_service()
        return self.service
    
    def _init_completes_structure(self):
        """Inicializa estructura Completes y _Respaldos_24h"""
        self._get_service()
        if not self.completes_root_id:
            self.completes_root_id = create_folder_if_not_exists(
                self.service, b'Completes', 'root'
            )
        
        if not self.respaldos_root_id:
            self.respaldos_root_id = create_folder_if_not_exists(
                self.service, b'_Respaldos_24h', self.completes_root_id
            )
    
    # ==================== FUNCIÓN 1: COPIAR A COMPLETES ====================
    
    def copiar_caso_a_completes(self, caso):
        """
        Copia un caso COMPLETO a Completes/{Empresa}/
        
        Se ejecuta cuando validador aprueba (estado = COMPLETA)
        
        Args:
            caso: Objeto Case de BD con drive_link
        
        Returns:
            str: Link del archivo copiado en Completes, o None si error
        """
        try:
            if not caso.drive_link:
                print(f"⚠️ Caso {caso.serial} sin drive_link, no se copia")
                return None
            # Extraer file_id del link
            file_id = self._extract_file_id(caso.drive_link)
            if not file_id:
                print(f"❌ No se pudo extraer file_id de {caso.drive_link}")
                return None
            # Inicializar estructura
            self._init_completes_structure()
            # Crear/obtener carpeta de empresa en Completes
            empresa_nombre = caso.empresa.nombre if caso.empresa else "OTRA_EMPRESA"
            empresa_folder_id = create_folder_if_not_exists(
                self.service,
                empresa_nombre.encode(),
                self.completes_root_id
            )
            # Copiar archivo
            copied_file = self.service.files().copy(
                fileId=file_id,
                body={'parents': [empresa_folder_id]}
            ).execute()
            copied_file_id = copied_file.get('id')
            copied_link = f"https://drive.google.com/file/d/{copied_file_id}/view"
            # Eliminar archivo de incompletas si existe
            try:
                from app.drive_manager import DriveFileManager
                drive_manager = DriveFileManager()
                incompletas_folder_id = drive_manager.get_or_create_folder_structure(empresa_nombre, 'INCOMPLETA')
                incompleta_file_id = drive_manager.get_file_id_by_name(caso.serial + ".pdf", incompletas_folder_id)
                if incompleta_file_id:
                    drive_manager.eliminar_version_incompleta(incompleta_file_id)
            except Exception as e:
                print(f"⚠️ Error eliminando incompleta: {e}")
            print(f"✅ Caso {caso.serial} copiado a Completes/{empresa_nombre}/")
            return copied_link
        except Exception as e:
            print(f"❌ Error copiando caso {caso.serial} a Completes: {e}")
            return None
    
    # ==================== FUNCIÓN 2: DETECTAR CAMBIOS Y CREAR ZIP ====================
    
    def detectar_cambios_y_crear_respaldo(self):
        """
        CRON JOB (cada 2-4 horas):
        - Revisa Completes/{Empresa}/
        - Compara contra BD (qué debería estar)
        - Si falta archivo → CREA ZIP con lo eliminado
        - ZIP dura 24h en _Respaldos_24h/
        
        Returns:
            dict: {empresa: [archivos_en_zip], ...}
        """
        try:
            self._init_completes_structure()
            
            # Obtener todas las empresas en Completes
            empresas_folders = self.service.files().list(
                q=f"'{self.completes_root_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
                spaces='drive',
                fields='files(id, name)'
            ).execute().get('files', [])
            
            respaldos_creados = {}
            
            for empresa_folder in empresas_folders:
                if empresa_folder['name'] == '_Respaldos_24h':
                    continue
                
                empresa_id = empresa_folder['id']
                empresa_nombre = empresa_folder['name']
                
                # Archivos actuales en Completes/{Empresa}/
                archivos_actuales = self._get_files_in_folder(empresa_id)
                
                # Archivos que DEBERÍA haber (COMPLETA en BD)
                archivos_esperados = self._get_expected_files_from_db(empresa_nombre)
                
                # Detectar eliminados
                archivos_faltantes = set(archivos_esperados.keys()) - set(archivos_actuales.keys())
                
                if archivos_faltantes:
                    print(f"\n🔍 Detectadas {len(archivos_faltantes)} eliminaciones en Completes/{empresa_nombre}/")
                    
                    # Crear ZIP con metadata de los eliminados
                    zip_path = self._crear_zip_respaldo(
                        empresa_nombre,
                        archivos_faltantes,
                        archivos_esperados
                    )
                    
                    # Subir ZIP a Drive en _Respaldos_24h/
                    if zip_path:
                        link_zip = self._subir_zip_a_respaldos(zip_path, empresa_nombre)
                        respaldos_creados[empresa_nombre] = {
                            'archivos': list(archivos_faltantes),
                            'zip': link_zip,
                            'cantidad': len(archivos_faltantes)
                        }
                        
                        # Eliminar archivo temporal
                        Path(zip_path).unlink()
                        
                        print(f"✅ ZIP creado para {empresa_nombre}: {link_zip}")
            
            return respaldos_creados
            
        except Exception as e:
            print(f"❌ Error en detección de cambios: {e}")
            return {}
    
    def _get_files_in_folder(self, folder_id):
        """Obtiene archivos (no carpetas) en una carpeta de Drive"""
        try:
            files = self.service.files().list(
                q=f"'{folder_id}' in parents and mimeType!='application/vnd.google-apps.folder' and trashed=false",
                spaces='drive',
                fields='files(id, name, modifiedTime)',
                pageSize=1000
            ).execute().get('files', [])
            
            # Usar name como clave, pero almacenar id para referencia
            result = {}
            for f in files:
                result[f['name']] = {
                    'id': f['id'], 
                    'modified': f.get('modifiedTime'),
                    'filename': f['name']
                }
            return result
        except:
            return {}
    
    def _get_expected_files_from_db(self, empresa_nombre):
        """
        Obtiene archivos que DEBERÍA haber en BD
        (todos los casos COMPLETA de esa empresa)
        """
        try:
            from sqlalchemy import and_
            
            # Crear sesión local
            db = SessionLocal()
            
            # Obtener empresa
            empresa = db.query(Company).filter(
                Company.nombre == empresa_nombre
            ).first()
            
            if not empresa:
                db.close()
                return {}
            
            # Obtener casos COMPLETA de esa empresa
            casos_completa = db.query(Case).filter(
                and_(
                    Case.estado == EstadoCaso.COMPLETA,
                    Case.empresa_id == empresa.id
                )
            ).all()
            
            # Extraer nombres de archivo esperados
            archivos = {}
            for caso in casos_completa:
                if caso.drive_link:
                    # Usar file_id como clave más confiable que filename
                    file_id = self._extract_file_id(caso.drive_link)
                    if file_id:
                        # Intentar obtener nombre real del archivo desde Drive
                        try:
                            file_info = self.service.files().get(
                                fileId=file_id,
                                fields='name'
                            ).execute()
                            filename = file_info.get('name', f'UNKNOWN_{file_id}')
                        except:
                            filename = f'UNKNOWN_{file_id}'
                        
                        archivos[filename] = {
                            'serial': caso.serial,
                            'cedula': caso.cedula,
                            'tipo': caso.tipo.value if caso.tipo else 'unknown',
                            'file_id': file_id
                        }
            
            db.close()
            return archivos
            
        except Exception as e:
            print(f"⚠️ Error obteniendo archivos esperados: {e}")
            import traceback
            traceback.print_exc()
            return {}
    
    def _crear_zip_respaldo(self, empresa_nombre, archivos_faltantes, archivos_esperados):
        """
        Crea ZIP con JSON de archivos eliminados
        
        No descargamos los archivos (ya se borraron)
        Solo guardamos registro de qué se eliminó
        """
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            zip_filename = f"{timestamp}_{empresa_nombre}_eliminados.zip"
            zip_path = f"/tmp/{zip_filename}"
            
            # Crear ZIP con listado
            with zipfile.ZipFile(zip_path, 'w') as zf:
                # Archivo de manifest
                manifest = {
                    'fecha_creacion': timestamp,
                    'empresa': empresa_nombre,
                    'archivos_eliminados': [],
                    'total': len(archivos_faltantes)
                }
                
                for archivo in archivos_faltantes:
                    info = archivos_esperados.get(archivo, {})
                    manifest['archivos_eliminados'].append({
                        'nombre': archivo,
                        'serial': info.get('serial'),
                        'cedula': info.get('cedula'),
                        'tipo': info.get('tipo')
                    })
                
                # Guardar manifest en ZIP
                import json
                manifest_json = json.dumps(manifest, indent=2, ensure_ascii=False)
                zf.writestr('MANIFEST.json', manifest_json)
            
            print(f"📦 ZIP creado: {zip_path}")
            return zip_path
            
        except Exception as e:
            print(f"❌ Error creando ZIP: {e}")
            return None
    
    def _subir_zip_a_respaldos(self, zip_path, empresa_nombre):
        """Sube ZIP a _Respaldos_24h en Drive"""
        try:
            from googleapiclient.http import MediaFileUpload
            
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"{timestamp}_{empresa_nombre}_eliminados.zip"
            
            file_metadata = {
                'name': filename,
                'parents': [self.respaldos_root_id],
                'description': f'Respaldo 24h - Incapacidades eliminadas de Completes/{empresa_nombre}'
            }
            
            media = MediaFileUpload(zip_path, mimetype='application/zip', resumable=True)
            
            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink'
            ).execute()
            
            return file.get('webViewLink')
            
        except Exception as e:
            print(f"❌ Error subiendo ZIP a Drive: {e}")
            return None
    
    # ==================== FUNCIÓN 3: LIMPIAR RESPALDOS EXPIRADOS ====================
    
    def limpiar_respaldos_expirados(self):
        """
        CRON JOB (cada 6 horas):
        - Revisa _Respaldos_24h/
        - Elimina ZIPs más viejos que 24h
        """
        try:
            self._init_completes_structure()
            
            # Obtener ZIPs en _Respaldos_24h
            zips = self.service.files().list(
                q=f"'{self.respaldos_root_id}' in parents and mimeType='application/zip' and trashed=false",
                spaces='drive',
                fields='files(id, name, createdTime)',
                pageSize=100
            ).execute().get('files', [])
            
            ahora = datetime.now(datetime.now().astimezone().tzinfo)
            expirados = []
            
            for zip_file in zips:
                fecha_creacion = datetime.fromisoformat(zip_file['createdTime'].replace('Z', '+00:00'))
                edad = ahora - fecha_creacion
                
                if edad > timedelta(hours=24):
                    # Marcar como eliminado (soft delete)
                    self.service.files().update(
                        fileId=zip_file['id'],
                        body={'trashed': True}
                    ).execute()
                    
                    expirados.append(zip_file['name'])
                    print(f"🗑️ ZIP expirado (>{edad.total_seconds()/3600:.1f}h): {zip_file['name']}")
            
            if expirados:
                print(f"✅ Limpiados {len(expirados)} respaldos expirados")
            
            return expirados
            
        except Exception as e:
            print(f"❌ Error limpiando respaldos: {e}")
            return []
    
    # ==================== HELPERS ====================
    
    def _extract_file_id(self, drive_link):
        """Extrae ID de archivo desde link de Drive"""
        patterns = [
            r'/file/d/([a-zA-Z0-9_-]+)',
            r'/d/([a-zA-Z0-9_-]+)',
            r'id=([a-zA-Z0-9_-]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, drive_link)
            if match:
                return match.group(1)
        
        return None
    
    def _extract_filename(self, drive_link):
        """Intenta extraer nombre de archivo desde el link"""
        try:
            # Si el link contiene el nombre, lo usa
            if '#' in drive_link:
                return drive_link.split('#')[-1]
            return None
        except:
            return None


# ==================== INSTANCIA GLOBAL ====================

completes_mgr = CompletesManager()
