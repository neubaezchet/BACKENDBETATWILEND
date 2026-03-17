"""
Cola de Notificaciones por Incapacidad - IncaNeurobaeza
Cada caso/serial tiene su propia cola FIFO de notificaciones.
Se procesan en background (thread) para no bloquear el endpoint.
Incluye reintentos automáticos.
"""

import threading
import time
import traceback
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict
from enum import Enum


class TipoNotificacion(str, Enum):
    CONFIRMACION = "confirmacion"
    COMPLETA = "completa"
    INCOMPLETA = "incompleta"
    ILEGIBLE = "ilegible"
    INCOMPLETA_ILEGIBLE = "incompleta_ilegible"
    EPS_TRANSCRIPCION = "eps_transcripcion"
    DERIVADO_TTHH = "derivado_tthh"
    CAUSA_EXTRA = "causa_extra"
    EN_RADICACION = "en_radicacion"
    RECORDATORIO = "recordatorio"


@dataclass
class NotificacionPendiente:
    """Representa una notificación pendiente en la cola"""
    serial: str
    tipo: str
    email: str
    subject: str
    html_content: str
    cc_email: Optional[str] = None
    correo_bd: Optional[str] = None
    whatsapp: Optional[str] = None
    whatsapp_message: Optional[str] = None
    adjuntos_base64: List[Dict] = field(default_factory=list)
    drive_link: Optional[str] = None
    # Control interno
    intentos: int = 0
    max_intentos: int = 3
    creado_at: str = field(default_factory=lambda: datetime.now().isoformat())
    ultimo_error: Optional[str] = None


class NotificationQueue:
    """
    Cola de notificaciones por serial (incapacidad).
    Cada serial tiene su propia cola FIFO.
    Un hilo worker se encarga de procesar todas las colas.
    """
    
    def __init__(self):
        self._colas: Dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()
        self._event = threading.Event()  # Para despertar al worker
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        
        # Estadísticas
        self.total_encoladas = 0
        self.total_enviadas = 0
        self.total_fallidas = 0
        self._historial: deque = deque(maxlen=200)  # Últimas 200 notificaciones
        
        # Iniciar worker automáticamente
        self.iniciar()
    
    def iniciar(self):
        """Inicia el hilo worker que procesa las colas"""
        if self._running:
            return
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="NotificationQueueWorker"
        )
        self._worker_thread.start()
        print("🔔 Cola de notificaciones iniciada")
    
    def detener(self):
        """Detiene el worker"""
        self._running = False
        self._event.set()
        if self._worker_thread:
            self._worker_thread.join(timeout=10)
        print("🔕 Cola de notificaciones detenida")
    
    def encolar(self, notificacion: NotificacionPendiente):
        """
        Agrega una notificación a la cola del serial correspondiente.
        Thread-safe. No bloquea.
        """
        with self._lock:
            self._colas[notificacion.serial].append(notificacion)
            self.total_encoladas += 1
        
        print(f"🔔 [{notificacion.serial}] Notificación encolada: {notificacion.tipo} "
              f"→ {notificacion.email} (cola: {len(self._colas[notificacion.serial])} pendientes)")
        
        # Despertar al worker
        self._event.set()
    
    def encolar_completa(self, serial: str, email: str, nombre_empleado: str,
                          empresa: str, tipo_incapacidad: str, telefono: str,
                          drive_link: str, cc_email: str = None,
                          correo_bd: str = None, motivo: str = None):
        """
        Atajo para encolar notificación de COMPLETA con template y WhatsApp.
        Genera el HTML y mensaje WhatsApp internamente.
        """
        from app.email_templates import get_email_template_universal
        
        motivo_email = motivo or "Validado correctamente por el validador"
        
        # Generar HTML
        html = get_email_template_universal(
            "completa", nombre_empleado, serial,
            empresa, tipo_incapacidad,
            telefono or 'N/A', email,
            drive_link,
            contenido_ia=motivo_email
        )
        
        # Generar mensaje WhatsApp
        whatsapp_msg = None
        if telefono:
            try:
                from app.ia_redactor import redactar_whatsapp_completa
                whatsapp_msg = redactar_whatsapp_completa(nombre_empleado, serial)
            except Exception as e:
                print(f"⚠️ IA WhatsApp falló, usando estático: {e}")
                whatsapp_msg = (
                    f"✅ *Incapacidad Validada*\n\n"
                    f"Hola {nombre_empleado}, tu incapacidad {serial} ha sido validada exitosamente.\n"
                    f"Procederemos a subirla al sistema.\n\n"
                    f"Nos comunicaremos contigo si se requiere algo adicional.\n\n"
                    f"_Automatico por Incapacidades_"
                )
        
        subject = f"✅ Incapacidad Validada - {serial}"
        
        notif = NotificacionPendiente(
            serial=serial,
            tipo="completa",
            email=email,
            subject=subject,
            html_content=html,
            cc_email=cc_email,
            correo_bd=correo_bd,
            whatsapp=telefono,
            whatsapp_message=whatsapp_msg,
            drive_link=drive_link
        )
        self.encolar(notif)
    
    def encolar_notificacion_estado(self, serial: str, tipo: str, email: str,
                                      nombre_empleado: str, empresa: str,
                                      tipo_incapacidad: str, telefono: str,
                                      drive_link: str, subject: str,
                                      template: str, cc_email: str = None,
                                      correo_bd: str = None, motivo: str = None,
                                      whatsapp_msg: str = None):
        """
        Encola una notificación genérica para cualquier cambio de estado.
        """
        from app.email_templates import get_email_template_universal
        
        motivo_email = motivo or f"El caso ha sido marcado como {tipo.upper()}"
        
        html = get_email_template_universal(
            template, nombre_empleado, serial,
            empresa, tipo_incapacidad,
            telefono or 'N/A', email,
            drive_link,
            contenido_ia=motivo_email
        )
        
        notif = NotificacionPendiente(
            serial=serial,
            tipo=tipo,
            email=email,
            subject=subject,
            html_content=html,
            cc_email=cc_email,
            correo_bd=correo_bd,
            whatsapp=telefono,
            whatsapp_message=whatsapp_msg,
            drive_link=drive_link
        )
        self.encolar(notif)
    
    def _worker_loop(self):
        """Bucle principal del worker que procesa notificaciones"""
        print("🔔 Worker de notificaciones activo")
        
        while self._running:
            # Esperar hasta que haya algo que procesar (o timeout de 5s)
            self._event.wait(timeout=5)
            self._event.clear()
            
            # Procesar todas las colas que tengan elementos
            seriales_a_procesar = []
            with self._lock:
                for serial, cola in self._colas.items():
                    if len(cola) > 0:
                        seriales_a_procesar.append(serial)
            
            for serial in seriales_a_procesar:
                self._procesar_cola_serial(serial)
    
    def _procesar_cola_serial(self, serial: str):
        """Procesa la siguiente notificación en la cola de un serial"""
        notif = None
        with self._lock:
            if serial in self._colas and len(self._colas[serial]) > 0:
                notif = self._colas[serial][0]  # Peek, no pop aún
        
        if not notif:
            return
        
        print(f"\n{'='*60}")
        print(f"📤 [{serial}] Procesando: {notif.tipo} → {notif.email}")
        print(f"   Intento {notif.intentos + 1}/{notif.max_intentos}")
        print(f"{'='*60}")
        
        try:
            from app.n8n_notifier import enviar_a_n8n
            
            resultado = enviar_a_n8n(
                tipo_notificacion=notif.tipo,
                email=notif.email,
                serial=notif.serial,
                subject=notif.subject,
                html_content=notif.html_content,
                cc_email=notif.cc_email,
                correo_bd=notif.correo_bd,
                whatsapp=notif.whatsapp,
                whatsapp_message=notif.whatsapp_message,
                adjuntos_base64=notif.adjuntos_base64,
                drive_link=notif.drive_link
            )
            
            if resultado:
                # ✅ ÉXITO - Remover de la cola
                with self._lock:
                    if serial in self._colas and len(self._colas[serial]) > 0:
                        self._colas[serial].popleft()
                        if len(self._colas[serial]) == 0:
                            del self._colas[serial]
                    self.total_enviadas += 1
                
                self._historial.append({
                    "serial": serial,
                    "tipo": notif.tipo,
                    "email": notif.email,
                    "whatsapp": notif.whatsapp or "N/A",
                    "estado": "enviada",
                    "intentos": notif.intentos + 1,
                    "timestamp": datetime.now().isoformat()
                })
                
                print(f"✅ [{serial}] Notificación {notif.tipo} ENVIADA a {notif.email}")
                if notif.whatsapp:
                    print(f"   📱 WhatsApp enviado a: {notif.whatsapp}")
            else:
                # ❌ FALLO - Reintentar o descartar
                notif.intentos += 1
                notif.ultimo_error = "enviar_a_n8n retornó False"
                
                if notif.intentos >= notif.max_intentos:
                    # ✅ GUARDAR EN COLA PERSISTENTE (BD) en vez de descartar
                    try:
                        from app.resilient_queue import guardar_pendiente_n8n
                        guardar_pendiente_n8n({
                            'tipo_notificacion': notif.tipo,
                            'email': notif.email,
                            'serial': notif.serial,
                            'subject': notif.subject,
                            'html_content': notif.html_content,
                            'cc_email': notif.cc_email,
                            'correo_bd': notif.correo_bd,
                            'whatsapp': notif.whatsapp,
                            'whatsapp_message': notif.whatsapp_message,
                            'drive_link': notif.drive_link,
                        }, error=notif.ultimo_error)
                    except Exception as save_err:
                        print(f"❌ [{serial}] No se pudo guardar en cola BD: {save_err}")
                    
                    with self._lock:
                        if serial in self._colas and len(self._colas[serial]) > 0:
                            self._colas[serial].popleft()
                            if len(self._colas[serial]) == 0:
                                del self._colas[serial]
                        self.total_fallidas += 1
                    
                    self._historial.append({
                        "serial": serial,
                        "tipo": notif.tipo,
                        "email": notif.email,
                        "estado": "guardada_en_cola_bd",
                        "intentos": notif.intentos,
                        "error": notif.ultimo_error,
                        "timestamp": datetime.now().isoformat()
                    })
                    
                    print(f"💾 [{serial}] Notificación {notif.tipo} guardada en COLA BD después de {notif.intentos} intentos")
                else:
                    # Esperar antes de reintentar
                    espera = 5 * notif.intentos  # 5s, 10s, 15s
                    print(f"⏳ [{serial}] Reintentando en {espera}s (intento {notif.intentos}/{notif.max_intentos})")
                    time.sleep(espera)
                    
        except Exception as e:
            notif.intentos += 1
            notif.ultimo_error = str(e)
            print(f"❌ [{serial}] Error procesando notificación: {e}")
            traceback.print_exc()
            
            if notif.intentos >= notif.max_intentos:
                # ✅ GUARDAR EN COLA PERSISTENTE (BD) en vez de perder
                try:
                    from app.resilient_queue import guardar_pendiente_n8n
                    guardar_pendiente_n8n({
                        'tipo_notificacion': notif.tipo,
                        'email': notif.email,
                        'serial': notif.serial,
                        'subject': notif.subject,
                        'html_content': notif.html_content,
                        'cc_email': notif.cc_email,
                        'correo_bd': notif.correo_bd,
                        'whatsapp': notif.whatsapp,
                        'whatsapp_message': notif.whatsapp_message,
                        'drive_link': notif.drive_link,
                    }, error=str(e))
                except Exception as save_err:
                    print(f"❌ [{serial}] No se pudo guardar en cola BD: {save_err}")
                
                with self._lock:
                    if serial in self._colas and len(self._colas[serial]) > 0:
                        self._colas[serial].popleft()
                        if len(self._colas[serial]) == 0:
                            del self._colas[serial]
                    self.total_fallidas += 1
                
                self._historial.append({
                    "serial": serial,
                    "tipo": notif.tipo,
                    "email": notif.email,
                    "estado": "guardada_en_cola_bd",
                    "intentos": notif.intentos,
                    "error": str(e),
                    "timestamp": datetime.now().isoformat()
                })
    
    def obtener_estado(self) -> dict:
        """Retorna el estado actual de todas las colas"""
        with self._lock:
            colas_info = {}
            for serial, cola in self._colas.items():
                colas_info[serial] = {
                    "pendientes": len(cola),
                    "siguiente": {
                        "tipo": cola[0].tipo,
                        "email": cola[0].email,
                        "intentos": cola[0].intentos
                    } if len(cola) > 0 else None
                }
            
            return {
                "worker_activo": self._running,
                "total_encoladas": self.total_encoladas,
                "total_enviadas": self.total_enviadas,
                "total_fallidas": self.total_fallidas,
                "colas_activas": len(self._colas),
                "colas": colas_info,
                "historial_reciente": list(self._historial)[-20:]  # Últimas 20
            }
    
    def obtener_historial_serial(self, serial: str) -> list:
        """Retorna el historial de notificaciones de un serial"""
        return [h for h in self._historial if h["serial"] == serial]


# ✅ INSTANCIA GLOBAL (singleton)
notification_queue = NotificationQueue()
