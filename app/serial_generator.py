"""
Generador de seriales únicos para casos de incapacidad
Formato: INICIALES + CEDULA + CONTADOR
Ejemplo: DB10850433740, DB10850433741, ...
"""

from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import Case
import re

def generar_serial_unico(db: Session, nombre: str, cedula: str) -> str:
    """
    Genera un serial único para una incapacidad
    
    Formato: INICIALES_NOMBRE + CEDULA + CONTADOR
    
    Ejemplo:
        nombre = "David Baeza"
        cedula = "1085043374"
        
        Primer caso  → DB10850433740
        Segundo caso → DB10850433741
        Tercer caso  → DB10850433742
    
    Args:
        db: Sesión de base de datos
        nombre: Nombre completo del empleado
        cedula: Cédula del empleado
    
    Returns:
        Serial único (str)
    """
    
    # Paso 1: Extraer iniciales del nombre
    iniciales = extraer_iniciales(nombre)
    
    # Paso 2: Construir prefijo base (iniciales + cedula)
    prefijo_base = f"{iniciales}{cedula}"
    
    # Paso 3: Buscar el último contador usado para esta persona
    # Buscar todos los casos que empiecen con este prefijo
    patron = f"{prefijo_base}%"
    casos_existentes = db.query(Case.serial).filter(
        Case.serial.like(patron)
    ).order_by(Case.serial.desc()).all()
    
    # Paso 4: Determinar el siguiente contador
    if not casos_existentes:
        # Primera incapacidad de esta persona
        contador = 0
    else:
        # Extraer el contador del último serial
        ultimo_serial = casos_existentes[0][0]
        try:
            # Extraer los dígitos al final del serial
            ultimo_contador = int(ultimo_serial.replace(prefijo_base, ''))
            contador = ultimo_contador + 1
        except (ValueError, AttributeError):
            # Si no se puede parsear, empezar desde 0
            contador = 0
    
    # Paso 5: Construir serial completo
    serial = f"{prefijo_base}{contador}"
    
    # Paso 6: Verificar que no exista (por si acaso)
    # Esto no debería pasar, pero es una medida de seguridad
    existe = db.query(Case).filter(Case.serial == serial).first()
    if existe:
        # Si por alguna razón ya existe, incrementar hasta encontrar uno libre
        while db.query(Case).filter(Case.serial == f"{prefijo_base}{contador}").first():
            contador += 1
        serial = f"{prefijo_base}{contador}"
    
    print(f"✅ Serial generado: {serial} (contador: {contador})")
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
        return "XX"  # Fallback si no hay nombre
    
    # Limpiar y separar el nombre
    nombre_limpio = re.sub(r'[^a-zA-ZáéíóúÁÉÍÓÚñÑ\s]', '', nombre_completo)
    palabras = nombre_limpio.strip().split()
    
    if not palabras:
        return "XX"
    
    # Extraer primera letra de cada palabra
    iniciales = ''.join([palabra[0].upper() for palabra in palabras if palabra])
    
    return iniciales if iniciales else "XX"

def validar_serial(serial: str) -> bool:
    """
    Valida que un serial tenga el formato correcto
    
    Formato esperado: LETRAS + NUMEROS
    Ejemplo válido: DB10850433740
    
    Args:
        serial: Serial a validar
    
    Returns:
        True si es válido, False si no
    """
    if not serial:
        return False
    
    # Debe empezar con al menos 1 letra
    # Debe tener al menos 1 número
    # No debe tener espacios ni caracteres especiales
    patron = r'^[A-Z]+\d+$'
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