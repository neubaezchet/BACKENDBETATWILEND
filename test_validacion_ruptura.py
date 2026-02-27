"""
SCRIPT DE PRUEBA: Validación de Ruptura de Prorrogas
======================================================
Prueba rápida del sistema OMS + LOCAL sin ejecutar servidor FastAPI.

Uso:
    python test_validacion_ruptura.py
"""

import sys
import json
from pathlib import Path

# Agregar app al path
sys.path.insert(0, str(Path(__file__).parent / "BACKENDBETATWILEND"))

def test_validacion_ruptura():
    """Ejecuta pruebas del sistema de validación de ruptura de prorrogas"""
    
    from app.services.prorroga_detector import _validar_ruptura_prorroga
    
    print("=" * 70)
    print("🔬 PRUEBAS: VALIDACIÓN RUPTURA DE PRORROGAS (OMS + LOCAL)")
    print("=" * 70)
    
    # Test cases
    casos_prueba = [
        {
            "nombre": "✅ PRÓRROGA PERMITIDA - Mismo bloque OMS",
            "codigo_a": "A00",
            "codigo_b": "A05",
            "dias": 15,
            "esperado": True
        },
        {
            "nombre": "❌ PRÓRROGA RECHAZADA - Exclusión OMS (embarazo vs trauma)",
            "codigo_a": "O80",
            "codigo_b": "S72",
            "dias": 20,
            "esperado": False
        },
        {
            "nombre": "⚠️ PRÓRROGA CON VALIDACIÓN LOCAL",
            "codigo_a": "F10",
            "codigo_b": "F20",
            "dias": 25,
            "esperado": False  # Bloqueada por LOCAL
        },
        {
            "nombre": "✅ PRÓRROGA PERMITIDA - Mapping CIE-11",
            "codigo_a": "K21",
            "codigo_b": "K26",
            "dias": 10,
            "esperado": True
        },
        {
            "nombre": "✅ PRÓRROGA PERMITIDA - Mismo capítulo OMS",
            "codigo_a": "J00",
            "codigo_b": "J09",
            "dias": 12,
            "esperado": True
        },
        {
            "nombre": "❌ PRÓRROGA RECHAZADA - Sin relación jerárquica OMS",
            "codigo_a": "A00",
            "codigo_b": "Z00",
            "dias": 20,
            "esperado": False
        }
    ]
    
    resultados = []
    total = len(casos_prueba)
    pasadas = 0
    
    for idx, caso in enumerate(casos_prueba, 1):
        print(f"\n[{idx}/{total}] {caso['nombre']}")
        print(f"       {caso['codigo_a']} → {caso['codigo_b']} ({caso['dias']} días)")
        
        try:
            validacion = _validar_ruptura_prorroga(
                caso["codigo_a"],
                caso["codigo_b"],
                caso["dias"]
            )
            
            resultado_obtenido = validacion["puede_ser_prorroga"]
            esperado = caso["esperado"]
            
            # Verificar resultado
            if resultado_obtenido == esperado:
                print(f"       ✅ PASÓ - puede_ser_prorroga={resultado_obtenido}")
                pasadas += 1
                status = "PASÓ"
            else:
                print(f"       ❌ FALLÓ - esperado {esperado}, obtenido {resultado_obtenido}")
                status = "FALLÓ"
            
            # Mostrar detalles
            print(f"       Fuente: {validacion['fuente']}")
            if validacion.get('confianza_oms') is not None:
                print(f"       Confianza OMS: {validacion['confianza_oms']}%")
            if validacion.get('razon_ruptura'):
                print(f"       Razón: {validacion['razon_ruptura'][:80]}...")
            
            resultados.append({
                "caso": caso["nombre"],
                "status": status,
                "validacion": validacion
            })
        
        except Exception as e:
            print(f"       ⚠️ ERROR: {str(e)}")
            resultados.append({
                "caso": caso["nombre"],
                "status": "ERROR",
                "error": str(e)
            })
    
    # Resumen
    print("\n" + "=" * 70)
    print(f"📊 RESUMEN: {pasadas}/{total} pruebas pasadas")
    print("=" * 70)
    
    for resultado in resultados:
        icono = "✅" if resultado["status"] == "PASÓ" else "❌"
        print(f"{icono} {resultado['status']}: {resultado['caso'][:60]}...")
    
    print("\n✨ Pruebas completadas")


if __name__ == "__main__":
    try:
        test_validacion_ruptura()
    except ImportError as e:
        print(f"❌ Error de importación: {e}")
        print("   Asegúrate de estar en el directorio correcto")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error inesperado: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
