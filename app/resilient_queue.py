"""
Cola Resiliente con Persistencia en BD - IncaNeurobaeza
=======================================================
Cuando fallan los envíos o Drive, los pendientes se guardan en la tabla
`pendientes_envio` (PostgreSQL).

Un worker background revisa periódicamente la tabla y reintenta los envíos.
Desde portal-neurobaeza se puede monitorear el estado de la cola.

TIPOS de pendientes:
- 'notificacion': Notificaciones (email + WhatsApp) que no pudieron enviarse
- 'drive': Archivos que no pudieron subirse a Google Drive
"""

import threading
import time
import traceback
import json
from datetime import datetime
from typing import Optional


# ==================== GUARDAR PENDIENTES EN BD ====================

def guardar_pendiente_notificacion(payload: dict, error: str = None):
    """
    Guarda una notificación fallida en la tabla pendientes_envio.
    """
    try:
        from app.database import SessionLocal, PendienteEnvio
        db = SessionLocal()
        
        pendiente = PendienteEnvio(
            tipo='notificacion',
            payload=payload,
            intentos=0,
            ultimo_error=str(error)[:500] if error else None,
            procesado=False
        )
        db.add(pendiente)
        db.commit()
        print(f"💾 [COLA-BD] Notificación guardada en cola persistente: {payload.get('serial', '?')}")
        db.close()
        return True
    except Exception as e:
        print(f"❌ [COLA-BD] Error guardando pendiente de notificación: {e}")
        traceback.print_exc()
        return False


def guardar_pendiente_drive(payload: dict, error: str = None):
    """
    Guarda un upload de Drive fallido en la tabla pendientes_envio.
    Se llama cuando el token de Drive expira o falla la subida.
    
    El payload debe contener:
    - file_path: ruta del archivo temporal (guardada en /tmp)
    - empresa, cedula, tipo, serial, fecha_inicio, fecha_fin, etc.
    """
    try:
        from app.database import SessionLocal, PendienteEnvio
        db = SessionLocal()
        
        pendiente = PendienteEnvio(
            tipo='drive',
            payload=payload,
            intentos=0,
            ultimo_error=str(error)[:500] if error else None,
            procesado=False
        )
        db.add(pendiente)
        db.commit()
        print(f"💾 [COLA-BD] Upload Drive guardado en cola persistente: {payload.get('serial', '?')}")
        db.close()
        return True
    except Exception as e:
        print(f"❌ [COLA-BD] Error guardando pendiente Drive: {e}")
        traceback.print_exc()
        return False


# ==================== PROCESADOR DE COLA PERSISTENTE ====================

class ResilientQueueProcessor:
    """
    Worker background que procesa la tabla pendientes_envio.
    - Revisa cada 60 segundos si hay pendientes
    - Reintenta notificaciones y Drive automáticamente
    - Máximo 10 intentos por pendiente (después se marca como fallido permanente)
    - Thread-safe
    """
    
    MAX_INTENTOS = 10
    INTERVALO_REVISION = 60  # segundos entre revisiones
    
    def __init__(self):
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._stats = {
            "procesados_ok": 0,
            "procesados_error": 0,
            "ultima_revision": None,
            "notificaciones_recuperadas": 0,
            "drive_recuperados": 0,
        }
    
    def iniciar(self):
        """Inicia el worker de cola resiliente"""
        if self._running:
            return
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="ResilientQueueWorker"
        )
        self._worker_thread.start()
        print("🛡️ Cola resiliente (BD) iniciada — revisando pendientes cada 60s")
    
    def detener(self):
        """Detiene el worker"""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=10)
        print("🛡️ Cola resiliente detenida")
    
    def _worker_loop(self):
        """Bucle principal: revisa pendientes cada INTERVALO_REVISION segundos"""
        # Esperar 30s al inicio para que la app arranque completamente
        time.sleep(30)
        
        while self._running:
            try:
                self._procesar_pendientes()
            except Exception as e:
                print(f"❌ [COLA-BD] Error en worker loop: {e}")
                traceback.print_exc()
            
            # Dormir hasta la próxima revisión
            for _ in range(self.INTERVALO_REVISION):
                if not self._running:
                    break
                time.sleep(1)
    
    def _procesar_pendientes(self):
        """Procesa todos los pendientes no procesados"""
        from app.database import SessionLocal, PendienteEnvio
        
        db = SessionLocal()
        try:
            pendientes = db.query(PendienteEnvio).filter(
                PendienteEnvio.procesado == False,
                PendienteEnvio.intentos < self.MAX_INTENTOS
            ).order_by(PendienteEnvio.creado_en.asc()).limit(20).all()
            
            if not pendientes:
                self._stats["ultima_revision"] = datetime.now().isoformat()
                db.close()
                return
            
            print(f"\n🛡️ [COLA-BD] Procesando {len(pendientes)} pendientes...")
            self._stats["ultima_revision"] = datetime.now().isoformat()
            
            for pendiente in pendientes:
                try:
                    if pendiente.tipo == 'notificacion':
                        exito = self._reintentar_notificacion(pendiente.payload)
                    elif pendiente.tipo == 'drive':
                        exito = self._reintentar_drive(pendiente.payload)
                    else:
                        print(f"⚠️ Tipo desconocido: {pendiente.tipo}")
                        exito = False
                    
                    pendiente.intentos += 1
                    pendiente.actualizado_en = datetime.now()
                    
                    if exito:
                        pendiente.procesado = True
                        pendiente.ultimo_error = None
                        self._stats["procesados_ok"] += 1
                        if pendiente.tipo == 'notificacion':
                            self._stats["notificaciones_recuperadas"] += 1
                        else:
                            self._stats["drive_recuperados"] += 1
                        print(f"✅ [COLA-BD] Pendiente #{pendiente.id} ({pendiente.tipo}) procesado OK")
                    else:
                        pendiente.ultimo_error = f"Intento {pendiente.intentos} fallido"
                        if pendiente.intentos >= self.MAX_INTENTOS:
                            pendiente.procesado = True  # Marcar como procesado (fallido permanente)
                            pendiente.ultimo_error = f"FALLIDO PERMANENTE después de {self.MAX_INTENTOS} intentos"
                            self._stats["procesados_error"] += 1
                            print(f"❌ [COLA-BD] Pendiente #{pendiente.id} FALLIDO PERMANENTE")
                        else:
                            print(f"⏳ [COLA-BD] Pendiente #{pendiente.id} intento {pendiente.intentos}/{self.MAX_INTENTOS}")
                    
                    db.commit()
                    
                except Exception as e:
                    pendiente.intentos += 1
                    pendiente.ultimo_error = str(e)[:500]
                    pendiente.actualizado_en = datetime.now()
                    db.commit()
                    print(f"❌ [COLA-BD] Error procesando pendiente #{pendiente.id}: {e}")
                
                # Procesamiento continuo: sin pausa artificial entre pendientes
        
        finally:
            db.close()
    
    def _reintentar_notificacion(self, payload: dict) -> bool:
        """Reintenta enviar notificación usando el backend nativo"""
        try:
            from app.email_service import enviar_notificacion
            
            resultado = enviar_notificacion(
                tipo_notificacion=payload.get('tipo_notificacion', 'confirmacion'),
                email=payload.get('email', ''),
                serial=payload.get('serial', ''),
                subject=payload.get('subject', ''),
                html_content=payload.get('html_content', ''),
                cc_email=payload.get('cc_email'),
                correo_bd=payload.get('correo_bd'),
                whatsapp=payload.get('whatsapp'),
                whatsapp_message=payload.get('whatsapp_message'),
                adjuntos_base64=payload.get('adjuntos_base64', []),
                drive_link=payload.get('drive_link')
            )
            return bool(resultado)
        except Exception as e:
            print(f"❌ [COLA-BD] Error reintentando notificación: {e}")
            return False
    
    def _reintentar_drive(self, payload: dict) -> bool:
        """Reintenta subir archivo a Google Drive"""
        try:
            from pathlib import Path
            from app.drive_uploader import upload_inteligente
            
            file_path = payload.get('file_path')
            if not file_path:
                print("⚠️ [COLA-BD] No hay file_path en payload de Drive")
                return False
            
            # Verificar que el archivo aún existe
            p = Path(file_path)
            if not p.exists():
                print(f"⚠️ [COLA-BD] Archivo ya no existe: {file_path}")
                # No se puede recuperar — marcar como fallido
                return False  # Se marcará como procesado si llegó a MAX_INTENTOS
            
            from datetime import date as date_type
            
            # Reconstruir fechas si están en el payload
            fecha_inicio = None
            fecha_fin = None
            if payload.get('fecha_inicio'):
                try:
                    fecha_inicio = date_type.fromisoformat(payload['fecha_inicio'])
                except:
                    pass
            if payload.get('fecha_fin'):
                try:
                    fecha_fin = date_type.fromisoformat(payload['fecha_fin'])
                except:
                    pass
            
            link = upload_inteligente(
                file_path=p,
                empresa=payload.get('empresa', ''),
                cedula=payload.get('cedula', ''),
                tipo=payload.get('tipo', ''),
                serial=payload.get('serial', ''),
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                tiene_soat=payload.get('tiene_soat'),
                tiene_licencia=payload.get('tiene_licencia'),
                subtipo=payload.get('subtipo')
            )
            
            if link:
                # Actualizar el drive_link en el caso si existe
                try:
                    from app.database import SessionLocal, Case
                    db = SessionLocal()
                    serial = payload.get('serial')
                    if serial:
                        caso = db.query(Case).filter(Case.serial == serial).first()
                        if caso:
                            caso.drive_link = link
                            db.commit()
                            print(f"✅ [COLA-BD] drive_link actualizado para {serial}: {link}")
                    db.close()
                except Exception as e:
                    print(f"⚠️ [COLA-BD] No se pudo actualizar drive_link: {e}")
                
                return True
            return False
            
        except Exception as e:
            print(f"❌ [COLA-BD] Error reintentando Drive: {e}")
            return False
    
    def obtener_estado(self) -> dict:
        """Retorna el estado de la cola resiliente para el portal"""
        from app.database import SessionLocal, PendienteEnvio
        
        db = SessionLocal()
        try:
            total_pendientes = db.query(PendienteEnvio).filter(
                PendienteEnvio.procesado == False
            ).count()
            
            pendientes_notificacion = db.query(PendienteEnvio).filter(
                PendienteEnvio.procesado == False,
                PendienteEnvio.tipo == 'notificacion'
            ).count()
            
            pendientes_drive = db.query(PendienteEnvio).filter(
                PendienteEnvio.procesado == False,
                PendienteEnvio.tipo == 'drive'
            ).count()
            
            fallidos_permanentes = db.query(PendienteEnvio).filter(
                PendienteEnvio.procesado == True,
                PendienteEnvio.intentos >= self.MAX_INTENTOS
            ).count()
            
            # Últimos 20 pendientes
            ultimos = db.query(PendienteEnvio).order_by(
                PendienteEnvio.creado_en.desc()
            ).limit(20).all()
            
            ultimos_list = []
            for p in ultimos:
                serial = "?"
                if p.payload and isinstance(p.payload, dict):
                    serial = p.payload.get('serial', '?')
                
                ultimos_list.append({
                    "id": p.id,
                    "tipo": p.tipo,
                    "serial": serial,
                    "intentos": p.intentos,
                    "procesado": p.procesado,
                    "ultimo_error": p.ultimo_error,
                    "creado_en": p.creado_en.isoformat() if p.creado_en else None,
                    "actualizado_en": p.actualizado_en.isoformat() if p.actualizado_en else None,
                })
            
            return {
                "worker_activo": self._running,
                "total_pendientes": total_pendientes,
                "pendientes_notificacion": pendientes_notificacion,
                "pendientes_drive": pendientes_drive,
                "fallidos_permanentes": fallidos_permanentes,
                "stats": self._stats,
                "ultimos": ultimos_list,
            }
        finally:
            db.close()
    
    def forzar_procesamiento(self):
        """Fuerza el procesamiento inmediato de la cola"""
        print("🔄 [COLA-BD] Procesamiento forzado solicitado")
        try:
            self._procesar_pendientes()
            return {"ok": True, "mensaje": "Procesamiento completado"}
        except Exception as e:
            return {"ok": False, "error": str(e)}


# ✅ INSTANCIA GLOBAL (singleton)
resilient_queue = ResilientQueueProcessor()
