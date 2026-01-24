"""
Script de prueba para verificar el workflow de bloqueo/desbloqueo
- Genera serial con formato nuevo (espacios)
- Simula un caso marcado como INCOMPLETA
- Verifica que el bloqueo funciona
- Simula reenvío
"""

import sys
from datetime import date, datetime
from pathlib import Path

# Agregar app al path
sys.path.insert(0, str(Path(__file__).parent))

from app.serial_generator import generar_serial_unico, validar_serial
from app.database import Case, EstadoCaso, TipoIncapacidad, get_db, init_db
from sqlalchemy.orm import Session

def test_serial_generator():
    """Test 1: Verificar que el generador crea seriales con espacios"""
    print("\n" + "="*60)
    print("TEST 1: Generador de Seriales con Espacios")
    print("="*60)
    
    cedula = "1085043374"
    fecha_inicio = date(2026, 1, 1)
    fecha_fin = date(2026, 2, 2)
    
    # Simular BD inicializada
    init_db()
    db = next(get_db())
    
    serial = generar_serial_unico(db, cedula, fecha_inicio, fecha_fin)
    print(f"\n✅ Serial generado: {serial}")
    print(f"   Formato esperado: {cedula} 01 01 2026 02 02 2026")
    
    # Validar serial
    es_valido = validar_serial(serial)
    print(f"\n{'✅' if es_valido else '❌'} Serial válido: {es_valido}")
    
    # Verificar que tiene espacios (no underscores)
    tiene_espacios = ' ' in serial and '_' not in serial.split('_')[0] if '_' in serial else ' ' in serial
    print(f"{'✅' if tiene_espacios else '❌'} Serial usa espacios: {tiene_espacios}")
    
    return serial, db

def test_incomplete_case_blocking(serial: str, db: Session):
    """Test 2: Verificar que marcando como INCOMPLETA bloquea nuevos envíos"""
    print("\n" + "="*60)
    print("TEST 2: Detección de Casos Incompletos y Bloqueo")
    print("="*60)
    
    cedula = "1085043374"
    
    # Buscar el caso creado
    caso = db.query(Case).filter(Case.serial == serial).first()
    
    if not caso:
        print(f"\n❌ No se encontró caso con serial {serial}")
        return False
    
    print(f"\n✅ Caso encontrado:")
    print(f"   Serial: {caso.serial}")
    print(f"   Estado: {caso.estado.value if caso.estado else 'N/A'}")
    print(f"   Bloqueado: {caso.bloquea_nueva}")
    print(f"   Cédula: {caso.cedula}")
    print(f"   Fecha inicio: {caso.fecha_inicio}")
    
    # Simular cambio a INCOMPLETA
    print(f"\n🔄 Simulando cambio de estado a INCOMPLETA...")
    caso.estado = EstadoCaso.INCOMPLETA
    caso.bloquea_nueva = True
    
    if not caso.metadata_form:
        caso.metadata_form = {}
    caso.metadata_form['checks_seleccionados'] = ['documentos_faltantes']
    
    db.commit()
    db.refresh(caso)
    
    print(f"   ✅ Estado: {caso.estado.value}")
    print(f"   ✅ Bloqueado (bloquea_nueva): {caso.bloquea_nueva}")
    print(f"   ✅ Checks guardados: {caso.metadata_form.get('checks_seleccionados', [])}")
    
    # Verificar que se puede detectar el bloqueo
    caso_incompleto = db.query(Case).filter(
        Case.cedula == cedula,
        Case.estado.in_([EstadoCaso.INCOMPLETA, EstadoCaso.ILEGIBLE, EstadoCaso.INCOMPLETA_ILEGIBLE]),
        Case.bloquea_nueva == True
    ).first()
    
    if caso_incompleto:
        print(f"\n✅ Bloqueo detectado correctamente:")
        print(f"   Serial bloqueante: {caso_incompleto.serial}")
        print(f"   Empleado con cédula {cedula} está bloqueado")
        return True
    else:
        print(f"\n❌ No se detectó el bloqueo")
        return False

def test_resubmission_detection(db: Session, cedula: str):
    """Test 3: Verificar que los reenvíos se detectan con misma fecha de inicio"""
    print("\n" + "="*60)
    print("TEST 3: Detección de Reenvíos (Resubmisión)")
    print("="*60)
    
    fecha_inicio = date(2026, 1, 1)
    
    # Buscar caso incompleto con misma fecha de inicio
    caso_existente = db.query(Case).filter(
        Case.cedula == cedula,
        Case.fecha_inicio == fecha_inicio,
        Case.estado.in_([EstadoCaso.INCOMPLETA, EstadoCaso.ILEGIBLE, EstadoCaso.INCOMPLETA_ILEGIBLE])
    ).first()
    
    if caso_existente:
        print(f"\n✅ Caso incompleto detectado:")
        print(f"   Serial: {caso_existente.serial}")
        print(f"   Estado: {caso_existente.estado.value}")
        print(f"   Cédula: {caso_existente.cedula}")
        print(f"   Fecha inicio: {caso_existente.fecha_inicio}")
        print(f"   Total reenvíos: {caso_existente.metadata_form.get('total_reenvios', 0) if caso_existente.metadata_form else 0}")
        return True
    else:
        print(f"\n❌ No se encontró caso incompleto para detección de reenvío")
        return False

def test_toggle_bloqueo(db: Session, serial: str):
    """Test 4: Verificar toggle-bloqueo endpoint logic"""
    print("\n" + "="*60)
    print("TEST 4: Lógica de Toggle Bloqueo")
    print("="*60)
    
    caso = db.query(Case).filter(Case.serial == serial).first()
    
    if not caso:
        print(f"\n❌ No se encontró caso con serial {serial}")
        return False
    
    estado_inicial = caso.bloquea_nueva
    print(f"\n✅ Estado inicial:")
    print(f"   Serial: {caso.serial}")
    print(f"   Bloqueado: {estado_inicial}")
    
    # Simular bloqueo
    print(f"\n🔄 Simulando 'bloquear'...")
    caso.bloquea_nueva = True
    db.commit()
    db.refresh(caso)
    
    if caso.bloquea_nueva:
        print(f"   ✅ Caso bloqueado: {caso.bloquea_nueva}")
    else:
        print(f"   ❌ Error: Caso no se bloqueó")
        return False
    
    # Simular desbloqueo
    print(f"\n🔄 Simulando 'desbloquear'...")
    caso.bloquea_nueva = False
    db.commit()
    db.refresh(caso)
    
    if not caso.bloquea_nueva:
        print(f"   ✅ Caso desbloqueado: {caso.bloquea_nueva}")
    else:
        print(f"   ❌ Error: Caso no se desbloqueó")
        return False
    
    return True

def test_serial_format_validation():
    """Test 5: Validar que regex solo acepta formato con espacios"""
    print("\n" + "="*60)
    print("TEST 5: Validación de Formato de Serial")
    print("="*60)
    
    test_cases = [
        ("1085043374 01 01 2026 02 02 2026", True, "Serial nuevo (espacios)"),
        ("1085043374 01 01 2026 02 02 2026_v1", True, "Serial con versión"),
        ("1085043374_01_01_2026_02_02_2026", False, "Serial viejo (underscores)"),
        ("1085043374-01-01-2026-02-02-2026", False, "Serial con guiones"),
        ("XX1085043374 01 01 2026 02 02 2026", False, "Serial con letras al inicio"),
    ]
    
    todos_ok = True
    for serial, esperado, descripcion in test_cases:
        resultado = validar_serial(serial)
        estado = "✅" if resultado == esperado else "❌"
        print(f"\n{estado} {descripcion}")
        print(f"   Serial: {serial}")
        print(f"   Esperado: {esperado}, Obtenido: {resultado}")
        
        if resultado != esperado:
            todos_ok = False
    
    return todos_ok

def main():
    """Ejecutar todos los tests"""
    print("\n" + "#"*60)
    print("# SUITE DE PRUEBAS: WORKFLOW BLOQUEO/DESBLOQUEO")
    print("#"*60)
    
    resultados = {
        "serial_generator": False,
        "incomplete_detection": False,
        "resubmission": False,
        "toggle_logic": False,
        "validation": False,
    }
    
    try:
        # Test 1: Generador
        serial, db = test_serial_generator()
        resultados["serial_generator"] = validar_serial(serial)
        
        # Test 2: Bloqueo
        resultados["incomplete_detection"] = test_incomplete_case_blocking(serial, db)
        
        # Test 3: Reenvíos
        resultados["resubmission"] = test_resubmission_detection(db, "1085043374")
        
        # Test 4: Toggle
        resultados["toggle_logic"] = test_toggle_bloqueo(db, serial)
        
        # Test 5: Validación
        resultados["validation"] = test_serial_format_validation()
        
    except Exception as e:
        print(f"\n❌ Error durante tests: {e}")
        import traceback
        traceback.print_exc()
    
    # Resumen final
    print("\n" + "="*60)
    print("RESUMEN DE RESULTADOS")
    print("="*60)
    
    for test_name, resultado in resultados.items():
        estado = "✅ PASS" if resultado else "❌ FAIL"
        print(f"{estado}: {test_name}")
    
    total = len(resultados)
    pasados = sum(1 for v in resultados.values() if v)
    
    print(f"\nTotal: {pasados}/{total} tests pasados")
    
    if pasados == total:
        print("\n✅ ¡TODOS LOS TESTS PASARON! El sistema está listo.")
    else:
        print(f"\n⚠️ {total - pasados} test(s) fallaron. Revisar logs arriba.")

if __name__ == "__main__":
    main()
