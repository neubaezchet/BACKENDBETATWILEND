#!/usr/bin/env python3
"""
🔍 DEBUG: Revisar qué emails se están enviando en CC
Verifica: 1) emails_empleado en BD, 2) emails en directorio de empresa
"""

import os
import sys
sys.path.insert(0, '/home/user/app')  # Ajusta la ruta según tu setup local

from app.database import SessionLocal, Employee, CorreoNotificacion, Company

def debug_emails():
    db = SessionLocal()
    
    print("\n" + "="*90)
    print("🔍 DEBUG: Emails para CC en notificaciones")
    print("="*90 + "\n")
    
    # 1. Revisar empleados con cédula 1085043374
    print("1️⃣ Buscando empleado con cédula 1085043374...")
    empleado = db.query(Employee).filter(Employee.cedula == "1085043374").first()
    
    if empleado:
        print(f"   ✅ Empleado encontrado: {empleado.nombre}")
        print(f"      - Correo: {empleado.correo or '❌ VACÍO'}")
        print(f"      - Empresa: {empleado.empresa.nombre if empleado.empresa else '❌ SIN EMPRESA'}")
        print(f"      - Company ID: {empleado.company_id}")
        
        if empleado.empresa:
            print(f"\n2️⃣ Buscando emails en directorio para empresa: {empleado.empresa.nombre}")
            correos = db.query(CorreoNotificacion).filter(
                CorreoNotificacion.area == 'empresas',
                CorreoNotificacion.activo == True,
                CorreoNotificacion.company_id == empleado.company_id
            ).all()
            
            if correos:
                print(f"   ✅ Encontrados {len(correos)} emails:")
                for c in correos:
                    print(f"      - {c.email} (activo: {c.activo})")
            else:
                print(f"   ❌ NO hay emails en directorio para esta empresa")
                print(f"      (Buscando con company_id={empleado.company_id})")
                
                # Verificar si hay emails generales (sin company_id específico)
                correos_generales = db.query(CorreoNotificacion).filter(
                    CorreoNotificacion.area == 'empresas',
                    CorreoNotificacion.activo == True,
                    CorreoNotificacion.company_id == None
                ).all()
                
                if correos_generales:
                    print(f"\n   ℹ️ Pero hay {len(correos_generales)} emails GENERALES (sin empresa específica):")
                    for c in correos_generales:
                        print(f"      - {c.email}")
    else:
        print(f"   ❌ Empleado NO encontrado")
    
    # 3. Mostrar todos los emails en directorio
    print(f"\n3️⃣ TODOS los emails en tabla correos_notificacion:")
    todos_correos = db.query(CorreoNotificacion).filter(
        CorreoNotificacion.area == 'empresas',
        CorreoNotificacion.activo == True
    ).all()
    
    if todos_correos:
        for c in todos_correos:
            company_name = c.company.nombre if c.company else "GENERAL"
            print(f"   - {c.email} → {company_name}")
    else:
        print(f"   ❌ NO hay emails en directorio de empresas")
    
    # 4. Mostrar tabla de empresas
    print(f"\n4️⃣ Empresas en BD:")
    empresas = db.query(Company).all()
    for emp in empresas:
        print(f"   - [{emp.id}] {emp.nombre} (email_copia: {emp.email_copia or 'vacío'})")
    
    print("\n" + "="*90)
    print("💡 SOLUCIÓN:")
    print("="*90)
    print("""
1. Si correo del empleado está VACÍO:
   - Edita la BD y agrega email en tabla employees para cedula=1085043374
   - UPDATE employees SET correo = 'correo@empresa.com' WHERE cedula = '1085043374'

2. Si directorio está VACÍO:
   - Agrega emails en tabla correos_notificacion:
   - INSERT INTO correos_notificacion (email, area, company_id, activo)
     VALUES ('cc@empresa.com', 'empresas', 14, true)
   
3. O en BD, agrega email_copia en tabla companies:
   - UPDATE companies SET email_copia = 'cc@empresa.com' WHERE id = 14
    """)
    print("="*90 + "\n")
    
    db.close()

if __name__ == "__main__":
    debug_emails()
