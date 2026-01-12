"""
Generador de Seriales V3 - Super Simplificado
IncaNeurobaeza - 2025

FORMATO: CEDULA-YYYYMMDD-YYYYMMDD
Ejemplo: 1085043374-20250115-20250120
"""

from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import Case
import re

def generar_serial_unico(db: Session, nombre: str, cedula: str, fecha_inicio: date = None, fecha_fin: date = None) -> str:
    """
    Genera un serial único para una incapacidad o certificado
    
    Genera un serial único en formato V3: CEDULA-YYYYMMDD-YYYYMMDD
    SIEMPRE usa fechas, si no se proporcionan usa la fecha actual
    """

    # Si no hay fecha_inicio, usar fecha actual
    if not fecha_inicio:
        fecha_inicio = date.today()

    # Si no hay fecha_fin, usar la misma fecha_inicio
    if not fecha_fin:
        fecha_fin = fecha_inicio

    # Formatear fechas
    fecha_ini_str = fecha_inicio.strftime("%Y%m%d")
    fecha_fin_str = fecha_fin.strftime("%Y%m%d")

    # Construir serial V3
    serial = f"{cedula}-{fecha_ini_str}-{fecha_fin_str}"

    # Verificar duplicado
    existe = db.query(Case).filter(Case.serial == serial).first()
    if existe:
        print(f"⚠️ Serial {serial} ya existe")
        contador = 1
        while db.query(Case).filter(Case.serial == f"{serial}-{contador}").first():
            contador += 1
        serial = f"{serial}-{contador}"
        print(f"   Usando: {serial}")

    print(f"✅ Serial V3 generado: {serial}")
    return serial

def extraer_iniciales(nombre_completo: str) -> str:
    """
    Extrae las iniciales del nombre completo
    
    Ejemplos:
        "David Baeza" → "DB"
        "Juan Carlos Pérez" → "JCP"
        "María" → "M"
        "José Luis De La Torre" → "JLDLT"
    
    Args:
        nombre_completo: Nombre completo del empleado
    
    Returns:
        Iniciales en mayúsculas (str)
    """
    if not nombre_completo:
        return "XX"
    
    nombre_limpio = re.sub(r'[^a-zA-ZáéíóúÁÉÍÓÚñÑ\s]', '', nombre_completo)
    palabras = nombre_limpio.strip().split()
    
    if not palabras:
        return "XX"
    
    iniciales = ''.join([palabra[0].upper() for palabra in palabras if palabra])
    
    return iniciales if iniciales else "XX"

def validar_serial(serial: str) -> bool:
    """
    Valida que un serial tenga el formato correcto
    
    Formatos válidos:
    - Tradicional: LETRAS + NUMEROS (DB10850433740)
    - V3: CEDULA-YYYYMMDD-YYYYMMDD (1085043374-20250115-20250120)
    
    Args:
        serial: Serial a validar
    
    Returns:
        True si es válido, False si no
    """
    if not serial:
        return False
    
    # Patrón V3: 10-11 dígitos, guion, 8 dígitos, guion, 8 dígitos
    patron_v3 = r'^\d{7,11}-\d{8}-\d{8}(-\d+)?$'
    
    # Patrón tradicional: LETRAS + NUMEROS
    patron_tradicional = r'^[A-Z]+\d+$'
    
    return bool(re.match(patron_v3, serial) or re.match(patron_tradicional, serial))

def validar_serial_certificado(serial: str) -> dict:
    """
    Valida y extrae información de un serial de certificado V3
    
    Returns:
        dict con: {
            'valido': bool,
            'cedula': str,
            'fecha_inicio': date,
            'fecha_fin': date
        }
    """
    
    try:
        partes = serial.split('-')
        
        if len(partes) < 3:
            return {'valido': False}
        
        cedula, fecha_ini_str, fecha_fin_str = partes[0], partes[1], partes[2]
        
        from datetime import datetime
        fecha_inicio = datetime.strptime(fecha_ini_str, "%Y%m%d").date()
        fecha_fin = datetime.strptime(fecha_fin_str, "%Y%m%d").date()
        
        return {
            'valido': True,
            'cedula': cedula,
            'fecha_inicio': fecha_inicio,
            'fecha_fin': fecha_fin
        }
    
    except Exception as e:
        print(f"❌ Error validando serial {serial}: {e}")
        return {'valido': False}

def verificar_serial_duplicado(db: Session, serial: str) -> bool:
    """
    Verifica si ya existe un caso con ese serial
    
    Returns:
        True si existe, False si no
    """
    existe = db.query(Case).filter(Case.serial == serial).first()
    return bool(existe)

def buscar_casos_por_cedula_fecha(
    db: Session,
    cedula: str,
    fecha_inicio: date = None,
    fecha_fin: date = None
) -> list:
    """
    Busca casos por cédula y rango de fechas
    """
    
    query = db.query(Case).filter(Case.cedula == cedula)
    
    if fecha_inicio:
        query = query.filter(Case.fecha_inicio >= fecha_inicio)
    
    if fecha_fin:
        query = query.filter(Case.fecha_fin <= fecha_fin)
    
    return query.all()

def generar_serial_automatico(
    db: Session,
    cedula: str,
    tipo: str,
    nombre: str = "DESCONOCIDO",
    fecha_inicio: date = None,
    fecha_fin: date = None
) -> str:
    """
    Generador automático - SIEMPRE usa formato V3 con fechas

    Ahora todos los tipos usan `generar_serial_unico` en formato V3.
    Si `fecha_inicio` o `fecha_fin` no se proporcionan, `generar_serial_unico`
    usará la fecha actual y hará que `fecha_fin` sea igual a `fecha_inicio`.
    """

    return generar_serial_unico(db, nombre, cedula, fecha_inicio, fecha_fin)

# ==================== TESTS ====================

def test_generador_seriales():
    """Función de prueba para verificar el generador"""
    
    print("🧪 Probando generador de seriales V3...\n")
    
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
        # Formato V3
        ("1085043374-20250115-20250120", True),
        ("1095043375-20250115-20250115", True),
        ("1085043374-20250115-20250120-1", True),  # Con sufijo
        # Formato tradicional
        ("DB10850433740", True),
        ("JCP12345670", True),
        ("M10", True),
        # Inválidos
        ("DB1085043374 0", False),
        ("DB-10850433740", False),
        ("db10850433740", False),
        ("10850433740", False),
        ("DBXX", False),
    ]
    
    for serial, esperado in tests_validacion:
        resultado = validar_serial(serial)
        estado = "✅" if resultado == esperado else "❌"
        print(f"  {estado} '{serial}' → {resultado} (esperado: {esperado})")
    
    print("\nTest 3: Validación de serial V3")
    info = validar_serial_certificado("1085043374-20250115-20250120")
    print(f"  Válido: {info['valido']}")
    print(f"  Cédula: {info.get('cedula', 'N/A')}")
    print(f"  Fecha inicio: {info.get('fecha_inicio', 'N/A')}")
    print(f"  Fecha fin: {info.get('fecha_fin', 'N/A')}")
    
    print("\n✅ Tests completados")

if __name__ == "__main__":
    test_generador_seriales()