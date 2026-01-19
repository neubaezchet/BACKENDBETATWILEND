"""
Generador de Seriales V3 - Super Simplificado
IncaNeurobaeza - 2025

FORMATO: CEDULA DD MM YYYY DD MM YYYY
Ejemplo: 1085043374 01 01 2025 20 01 2025
Sin fecha_fin: 1085043374 01 01 2025
"""

from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import Case
import re

def generar_serial_unico(db: Session, nombre: str, cedula: str, fecha_inicio: date = None, fecha_fin: date = None) -> str:
    """
    Genera un serial único para una incapacidad o certificado
    
    Formato V3:
    - Con fecha_fin: CEDULA DD MM YYYY DD MM YYYY (ej: 1085043374 01 01 2025 20 01 2025)
    - Sin fecha_fin: CEDULA DD MM YYYY (ej: 1085043374 01 01 2025)
    SIEMPRE usa fechas, si no se proporcionan usa la fecha actual
    """

    # Si no hay fecha_inicio, usar fecha actual
    if not fecha_inicio:
        fecha_inicio = date.today()

    # Formatear fecha_inicio en formato DD MM YYYY (espacios)
    fecha_ini_str = fecha_inicio.strftime("%d %m %Y")
    
    # Si no hay fecha_fin, NO duplicar
    if not fecha_fin:
        fecha_fin_str = None
    else:
        fecha_fin_str = fecha_fin.strftime("%d %m %Y")

    # Construir serial V3: documento + fechas con espacios
    if fecha_fin_str:
        serial = f"{cedula} {fecha_ini_str} {fecha_fin_str}"
    else:
        serial = f"{cedula} {fecha_ini_str}"

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
    - V3: CEDULA DD MM YYYY DD MM YYYY (1085043374 01 01 2025 20 01 2025)
    - V3 sin fecha_fin: CEDULA DD MM YYYY (1085043374 01 01 2025)
    - Tradicional: LETRAS + NUMEROS (DB10850433740)
    
    Args:
        serial: Serial a validar
    
    Returns:
        True si es válido, False si no
    """
    if not serial:
        return False
    
    # Patrón V3 con espacios: cedula + espacios + DD MM YYYY + espacios + DD MM YYYY
    patron_v3_completo = r'^\d{7,11}\s+\d{2}\s+\d{2}\s+\d{4}\s+\d{2}\s+\d{2}\s+\d{4}(-\d+)?$'
    
    # Patrón V3 sin fecha_fin: cedula + espacios + DD MM YYYY
    patron_v3_simple = r'^\d{7,11}\s+\d{2}\s+\d{2}\s+\d{4}(-\d+)?$'
    
    # Patrón tradicional: LETRAS + NUMEROS
    patron_tradicional = r'^[A-Z]+\d+$'
    
    return bool(re.match(patron_v3_completo, serial) or 
                re.match(patron_v3_simple, serial) or 
                re.match(patron_tradicional, serial))

def validar_serial_certificado(serial: str) -> dict:
    """
    Valida y extrae información de un serial de certificado V3
    
    Formatos soportados:
    - Con fecha_fin: CEDULA DD MM YYYY DD MM YYYY
    - Sin fecha_fin: CEDULA DD MM YYYY
    
    Returns:
        dict con: {
            'valido': bool,
            'cedula': str,
            'fecha_inicio': date,
            'fecha_fin': date (o None si no existe)
        }
    """
    
    try:
        partes = serial.split()
        
        if len(partes) < 4:  # Al menos: cedula + DD + MM + YYYY
            return {'valido': False}
        
        cedula = partes[0]
        
        # Extraer primera fecha: DD MM YYYY
        dia_ini = int(partes[1])
        mes_ini = int(partes[2])
        ano_ini = int(partes[3])
        
        from datetime import datetime
        fecha_inicio = datetime(ano_ini, mes_ini, dia_ini).date()
        
        # Si hay más partes, extraer fecha_fin: DD MM YYYY
        fecha_fin = None
        if len(partes) >= 8:  # cedula + DD + MM + YYYY + DD + MM + YYYY
            dia_fin = int(partes[4])
            mes_fin = int(partes[5])
            ano_fin = int(partes[6])
            fecha_fin = datetime(ano_fin, mes_fin, dia_fin).date()
        
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
        # Formato V3 con espacios
        ("1085043374 01 01 2025 20 01 2025", True),
        ("1095043375 15 03 2025 15 03 2025", True),
        ("1085043374 01 01 2025", True),  # Sin fecha_fin
        ("1085043374 01 01 2025-1", True),  # Con sufijo
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
    info = validar_serial_certificado("1085043374 01 01 2025 20 01 2025")
    print(f"  Válido: {info['valido']}")
    print(f"  Cédula: {info.get('cedula', 'N/A')}")
    print(f"  Fecha inicio: {info.get('fecha_inicio', 'N/A')}")
    print(f"  Fecha fin: {info.get('fecha_fin', 'N/A')}")
    
    print("\n✅ Tests completados")

if __name__ == "__main__":
    test_generador_seriales()