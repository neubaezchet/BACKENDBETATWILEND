"""Test completo del sistema híbrido LOCAL + OMS"""
import sys, asyncio
sys.path.insert(0, '.')

from app.services.oms_icd_service import validar_correlacion_oms_local
from app.services.cie10_service import son_correlacionados, son_correlacionados_auditoria


async def test_oms_local():
    print("=" * 65)
    print("TEST 1: validar_correlacion_oms_local (MinSalud + CIE-11)")
    print("=" * 65)
    
    casos = [
        ("A09", "K52", "Gastroenteritis vs Colitis"),
        ("M54", "M51", "Dorsalgia vs Hernia discal"),
        ("J00", "J18", "Resfriado vs Neumonía"),
        ("S72", "M54", "Fractura fémur vs Dorsalgia"),
        ("E11", "H36", "Diabetes T2 vs Retinopatía"),
        ("I10", "I25", "Hipertensión vs Cardiopatía isquémica"),
        ("F32", "F41", "Depresión vs Ansiedad"),
    ]
    
    for cod1, cod2, desc in casos:
        r = await validar_correlacion_oms_local(cod1, cod2)
        corr = r.get("correlacionados_oms", False)
        conf = r.get("confianza_oms", 0)
        nivel = r.get("nivel_oms", "?")
        razon = r.get("razon_oms", "")[:90]
        emoji = "✅" if corr else "❌"
        print(f"  {emoji} {cod1} vs {cod2} ({desc}): {conf}% [{nivel}]")
        print(f"     {razon}")
    print()


def test_hibrido_sync():
    print("=" * 65)
    print("TEST 2: son_correlacionados() con integración OMS")
    print("=" * 65)
    
    casos = [
        ("A09", "K52", "Gastroenteritis vs Colitis"),
        ("M54", "M51", "Dorsalgia vs Hernia discal"),
        ("J00", "J18", "Resfriado vs Neumonía"),
        ("S72", "M54", "Fractura fémur vs Dorsalgia"),
        ("I10", "I25", "Hipertensión vs Cardiopatía isquémica"),
    ]
    
    for cod1, cod2, desc in casos:
        r = son_correlacionados(cod1, cod2)
        corr = r.get("correlacionados", False)
        asert = r.get("asertividad", 0)
        conf = r.get("confianza", "?")
        fuente = r.get("fuente", "?")
        oms = r.get("validacion_oms", {})
        oms_validado = oms.get("validado", False) if isinstance(oms, dict) else False
        emoji = "✅" if corr else "❌"
        print(f"  {emoji} {cod1} vs {cod2} ({desc})")
        print(f"     Asertividad: {asert}% | Confianza: {conf} | Fuente: {fuente}")
        print(f"     OMS validado: {oms_validado}")
        if isinstance(oms, dict) and oms.get("razon_oms"):
            print(f"     OMS dice: {str(oms.get('razon_oms', ''))[:80]}")
    print()


async def test_auditoria():
    print("=" * 65)
    print("TEST 3: son_correlacionados_auditoria() — versión completa")
    print("=" * 65)
    
    casos = [
        ("A09", "K52", 5, "Gastroenteritis→Colitis, 5 días"),
        ("M54", "M51", 10, "Dorsalgia→Hernia, 10 días"),
        ("J00", "E11", 3, "Resfriado→Diabetes, 3 días (NO corr)"),
        ("F32", "F41", 15, "Depresión→Ansiedad, 15 días"),
    ]
    
    for cod1, cod2, dias, desc in casos:
        r = await son_correlacionados_auditoria(cod1, cod2, dias_entre=dias)
        corr = r.get("correlacionados", False)
        asert = r.get("asertividad", 0)
        fuente = r.get("fuente", "?")
        oms = r.get("validacion_oms", {})
        cita = oms.get("cita_legal_oms", "") if isinstance(oms, dict) else ""
        conflicto = oms.get("conflicto", False) if isinstance(oms, dict) else False
        emoji = "✅" if corr else "❌"
        print(f"  {emoji} {desc}")
        print(f"     Asertividad: {asert}% | Fuente: {fuente}")
        if cita:
            print(f"     Cita legal: {cita[:100]}...")
        if conflicto:
            print(f"     ⚠️ CONFLICTO LOCAL↔OMS")
    print()


async def main():
    await test_oms_local()
    test_hibrido_sync()
    await test_auditoria()
    print("🎯 TODOS LOS TESTS COMPLETADOS")


if __name__ == "__main__":
    asyncio.run(main())
