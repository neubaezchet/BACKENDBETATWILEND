"""
Rate Limiter avanzado para WhatsApp vía WAHA
Previene bans por spam masivo
"""

from datetime import datetime, timedelta
from collections import deque
import time
import threading

class WAHARateLimiter:
    """
    Control inteligente de flujo para evitar baneo de WhatsApp
    
    Límites seguros:
    - 10 mensajes/minuto        (WhatsApp recomienda 5-10)
    - 100 mensajes/hora         (Máx 1 cada 36 segundos)
    - 300 mensajes/día          (Para cuentas con verificación)
    - 3 segundos enfriamiento   (Entre cada mensaje)
    """
    
    def __init__(self):
        self.mensajes_enviados = deque(maxlen=500)
        
        # ✅ LÍMITES SEGUROS
        self.LIMITE_POR_MINUTO = 10      # Máx 10 msg/min
        self.LIMITE_POR_HORA = 100       # Máx 100 msg/hora
        self.LIMITE_POR_DIA = 300        # Máx 300 msg/día
        
        # ✅ ENFRIAMIENTO ENTRE MENSAJES
        self.VENTANA_ENFRIAMIENTO = 3    # 3 segundos entre mensajes
        self.ultimo_envio = None
        
        # ✅ THREAD-SAFETY
        self._lock = threading.Lock()
        
        # ✅ ESTADÍSTICAS
        self.total_intentos = 0
        self.total_rechazados = 0
        self.ultima_fecha_reset = datetime.now().date()
    
    def puede_enviar(self) -> tuple[bool, str]:
        """
        Verifica si se puede enviar un mensaje sin violar límites
        
        Returns:
            (puede_enviar: bool, razon: str)
        """
        with self._lock:
            ahora = datetime.now()
            
            # ✅ RESET DIARIO A MEDIANOCHE
            if ahora.date() > self.ultima_fecha_reset:
                self.mensajes_enviados.clear()
                self.ultima_fecha_reset = ahora.date()
                print(f"🔄 Reset diario - Contador reseteado")
            
            # ✅ VERIFICAR ENFRIAMIENTO (3 segundos mínimo entre mensajes)
            if self.ultimo_envio:
                segundos_desde_ultimo = (ahora - self.ultimo_envio).total_seconds()
                if segundos_desde_ultimo < self.VENTANA_ENFRIAMIENTO:
                    diferencia = self.VENTANA_ENFRIAMIENTO - segundos_desde_ultimo
                    return False, f"Enfriamiento: espera {diferencia:.1f}s más"
            
            # ✅ LIMPIAR REGISTROS ANTIGUOS
            hace_un_minuto = ahora - timedelta(minutes=1)
            hace_una_hora = ahora - timedelta(hours=1)
            hace_un_dia = ahora - timedelta(days=1)
            
            while self.mensajes_enviados and self.mensajes_enviados[0] < hace_un_dia:
                self.mensajes_enviados.popleft()
            
            # ✅ CONTAR MENSAJES POR VENTANAS TEMPORALES
            msgs_ultimo_minuto = sum(1 for t in self.mensajes_enviados if t >= hace_un_minuto)
            msgs_ultima_hora = sum(1 for t in self.mensajes_enviados if t >= hace_una_hora)
            msgs_ultimo_dia = len(self.mensajes_enviados)
            
            # ✅ VERIFICAR LÍMITES (por orden de severidad)
            if msgs_ultimo_dia >= self.LIMITE_POR_DIA:
                return False, f"❌ LÍMITE DIARIO: {msgs_ultimo_dia}/{self.LIMITE_POR_DIA} msgs"
            
            if msgs_ultima_hora >= self.LIMITE_POR_HORA:
                minutos_espera = 60 - ((ahora - self.mensajes_enviados[len(self.mensajes_enviados) - self.LIMITE_POR_HORA]).total_seconds() // 60)
                return False, f"⚠️ LÍMITE HORARIO: {msgs_ultima_hora}/{self.LIMITE_POR_HORA} - Espera {int(minutos_espera)}min"
            
            if msgs_ultimo_minuto >= self.LIMITE_POR_MINUTO:
                return False, f"Límite por minuto: {msgs_ultimo_minuto}/{self.LIMITE_POR_MINUTO}"
            
            return True, "✅ OK"
    
    def registrar_envio(self):
        """Registra un mensaje enviado correctamente"""
        with self._lock:
            ahora = datetime.now()
            self.mensajes_enviados.append(ahora)
            self.ultimo_envio = ahora
            self.total_intentos += 1
            
            # Estadísticas
            msgs_hoy = len(self.mensajes_enviados)
            print(f"✅ WhatsApp enviado - Stats: {msgs_hoy}/300 msgs hoy")
    
    def rechazar_envio(self):
        """Registra un mensaje rechazado por rate limit"""
        self.total_rechazados += 1
    
    def esperar_si_necesario(self) -> bool:
        """
        Espera automáticamente si hay rate limit, reintentando
        
        Returns:
            True si logró enviar, False si se agotó el límite diario
        """
        max_intentos = 20  # Máx ~1 minuto esperando
        intentos = 0
        
        while intentos < max_intentos:
            puede, razon = self.puede_enviar()
            
            if puede:
                return True
            
            # Si es límite diario, no esperar más
            if "DIARIO" in razon:
                print(f"❌ {razon} - No se puede enviar más hoy")
                self.rechazar_envio()
                return False
            
            # Esperar y reintentar
            print(f"⏳ {razon} - Reintentando...")
            time.sleep(3)
            intentos += 1
        
        print(f"❌ Timeout esperando rate limit (intentos: {intentos})")
        self.rechazar_envio()
        return False
    
    def obtener_estadisticas(self) -> dict:
        """Retorna estadísticas del limitador"""
        with self._lock:
            ahora = datetime.now()
            hace_un_minuto = ahora - timedelta(minutes=1)
            hace_una_hora = ahora - timedelta(hours=1)
            
            msgs_minuto = sum(1 for t in self.mensajes_enviados if t >= hace_un_minuto)
            msgs_hora = sum(1 for t in self.mensajes_enviados if t >= hace_una_hora)
            msgs_dia = len(self.mensajes_enviados)
            
            return {
                "por_minuto": f"{msgs_minuto}/{self.LIMITE_POR_MINUTO}",
                "por_hora": f"{msgs_hora}/{self.LIMITE_POR_HORA}",
                "por_dia": f"{msgs_dia}/{self.LIMITE_POR_DIA}",
                "intentos_totales": self.total_intentos,
                "rechazados": self.total_rechazados,
                "tasa_exito": f"{((self.total_intentos - self.total_rechazados) / max(self.total_intentos, 1) * 100):.1f}%"
            }


# ✅ INSTANCIA GLOBAL (singleton)
waha_limiter = WAHARateLimiter()


def obtener_limiter() -> WAHARateLimiter:
    """Obtiene la instancia global del limitador"""
    return waha_limiter
