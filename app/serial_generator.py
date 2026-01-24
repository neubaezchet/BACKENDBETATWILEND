"""
Generador de seriales únicos para casos de incapacidad
NUEVO FORMATO: CEDULA_FECHA_INICIO_FECHA_FIN
Ejemplo: 1085043374_01_01_2026_02_02_2026
"""

from sqlalchemy.orm import Session
from app.database import Case
import re
from datetime import date

def generar_serial_unico(db: Session, cedula: str, fecha_inicio: date, fecha_fin: date) -> str:
    """
    Genera un serial único para una incapacidad
    
    NUEVO FORMATO: CEDULA_FECHA_INICIO_FECHA_FIN
    
    Ejemplo:
        cedula = "1085043374"
        fecha_inicio = "2026-01-01"
        fecha_fin = "2026-02-02"
        
        Serial → 1085043374_01_01_2026_02_02_2026
    
    Args:
        db: Sesión de base de datos
        cedula: Cédula del empleado
        fecha_inicio: Fecha de inicio de incapacidad (date)
        fecha_fin: Fecha de fin de incapacidad (date)
    
    Returns:
        Serial único (str)
    """
    
    # Formatear fechas: DD_MM_YYYY
    if isinstance(fecha_inicio, str):
        fecha_inicio = fecha_inicio.split('T')[0]  # Remover hora si existe
        fecha_inicio_parts = fecha_inicio.split('-')  # YYYY-MM-DD
        fecha_inicio_fmt = f"{fecha_inicio_parts[2]}_{fecha_inicio_parts[1]}_{fecha_inicio_parts[0]}"
    else:
        fecha_inicio_fmt = fecha_inicio.strftime('%d_%m_%Y')
    
    if isinstance(fecha_fin, str):
        fecha_fin = fecha_fin.split('T')[0]  # Remover hora si existe
        fecha_fin_parts = fecha_fin.split('-')  # YYYY-MM-DD
        fecha_fin_fmt = f"{fecha_fin_parts[2]}_{fecha_fin_parts[1]}_{fecha_fin_parts[0]}"
    else:
        fecha_fin_fmt = fecha_fin.strftime('%d_%m_%Y')
    
    # Construir serial: CEDULA_DD_MM_YYYY_DD_MM_YYYY
    serial = f"{cedula}_{fecha_inicio_fmt}_{fecha_fin_fmt}"
    
    # Verificar que no exista (por duplicación de fechas)
    existe = db.query(Case).filter(Case.serial == serial).first()
    if existe:
        # Si existe, agregar un sufijo incremental
        contador = 1
        while db.query(Case).filter(Case.serial == f"{serial}_v{contador}").first():
            contador += 1
        serial = f"{serial}_v{contador}"
    
    print(f"✅ Serial generado: {serial}")
    return serial

def validar_serial(serial: str) -> bool:
    """
    Valida que un serial tenga el formato correcto
    
    Formato esperado: CEDULA_DD_MM_YYYY_DD_MM_YYYY
    Ejemplo válido: 1085043374_01_01_2026_02_02_2026
    
    Args:
        serial: Serial a validar
    
    Returns:
        True si es válido, False si no
    """
    if not serial:
        return False
    
    # Patrón: números_DD_MM_YYYY_DD_MM_YYYY (opcional _v número para duplicados)
    patron = r'^\d{10}_\d{2}_\d{2}_\d{4}_\d{2}_\d{2}_\d{4}(_v\d+)?$'
    return bool(re.match(patron, serial))

# ==================== TESTS ====================

def test_generador_seriales():
    """Función de prueba para verificar el generador"""
    
    print("🧪 Probando generador de seriales...\n")
    
    # Test 1: Extraer iniciales
    tests_iniciales = [
        ("David Baeza", "DB"),
        ("Juan Carlos Pérez", "JCP"),
        ("María", "M"),
        ("José Luis De La Torre", "JLDLT"),
        ("", "XX"),
        ("123", "XX"),
    ]
    
    print("Test 1: Extracción de iniciales")
    for nombre, esperado in tests_iniciales:
        resultado = extraer_iniciales(nombre)
        estado = "✅" if resultado == esperado else "❌"
        print(f"  {estado} '{nombre}' → '{resultado}' (esperado: '{esperado}')")
    
    print("\nTest 2: Validación de seriales")
    tests_validacion = [
        ("DB10850433740", True),
        ("JCP12345670", True),
        ("M10", True),
        ("DB1085043374 0", False),  # Con espacio
        ("DB-10850433740", False),  # Con guion
        ("db10850433740", False),   # Minúsculas
        ("10850433740", False),     # Sin letras
        ("DBXX", False),            # Sin números
    ]
    
    for serial, esperado in tests_validacion:
        resultado = validar_serial(serial)
        estado = "✅" if resultado == esperado else "❌"
        print(f"  {estado} '{serial}' → {resultado} (esperado: {esperado})")
    
    print("\n✅ Tests completados")

if __name__ == "__main__":
    test_generador_seriales()