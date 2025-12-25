# verificar_emails_bd.py
from app.database import SessionLocal, Case, Employee, Company

db = SessionLocal()

print("=" * 60)
print("VERIFICACIÓN DE EMAILS EN BASE DE DATOS")
print("=" * 60)

# 1. Verificar empleados con correo
empleados_con_correo = db.query(Employee).filter(
    Employee.correo != None,
    Employee.correo != ''
).count()

empleados_sin_correo = db.query(Employee).filter(
    (Employee.correo == None) | (Employee.correo == '')
).count()

print(f"\n📊 EMPLEADOS:")
print(f"   ✅ Con correo: {empleados_con_correo}")
print(f"   ❌ Sin correo: {empleados_sin_correo}")

# Mostrar algunos ejemplos
empleados_ejemplo = db.query(Employee).filter(
    Employee.correo != None,
    Employee.correo != ''
).limit(5).all()

if empleados_ejemplo:
    print(f"\n   Ejemplos de empleados CON correo:")
    for emp in empleados_ejemplo:
        print(f"      - {emp.nombre}: {emp.correo}")
else:
    print(f"\n   ⚠️ NO HAY empleados con correo en BD")

# 2. Verificar empresas con email_copia
empresas_con_email = db.query(Company).filter(
    Company.email_copia != None,
    Company.email_copia != ''
).count()

empresas_sin_email = db.query(Company).filter(
    (Company.email_copia == None) | (Company.email_copia == '')
).count()

print(f"\n📊 EMPRESAS:")
print(f"   ✅ Con email_copia: {empresas_con_email}")
print(f"   ❌ Sin email_copia: {empresas_sin_email}")

# Mostrar algunos ejemplos
empresas_ejemplo = db.query(Company).filter(
    Company.email_copia != None,
    Company.email_copia != ''
).all()

if empresas_ejemplo:
    print(f"\n   Ejemplos de empresas CON email_copia:")
    for emp in empresas_ejemplo:
        print(f"      - {emp.nombre}: {emp.email_copia}")
else:
    print(f"\n   ⚠️ NO HAY empresas con email_copia en BD")

# 3. Verificar un caso específico
print(f"\n📊 VERIFICAR CASO ESPECÍFICO:")
caso = db.query(Case).filter(Case.serial.like("DB%")).first()

if caso:
    print(f"\n   Serial: {caso.serial}")
    print(f"   Email formulario: {caso.email_form}")
    
    if caso.empleado:
        print(f"\n   👤 Empleado:")
        print(f"      Nombre: {caso.empleado.nombre}")
        print(f"      Correo BD: {caso.empleado.correo or '❌ SIN CORREO'}")
    else:
        print(f"\n   ❌ Caso sin empleado asociado")
    
    if caso.empresa:
        print(f"\n   🏢 Empresa:")
        print(f"      Nombre: {caso.empresa.nombre}")
        print(f"      Email copia: {caso.empresa.email_copia or '❌ SIN EMAIL_COPIA'}")
    else:
        print(f"\n   ❌ Caso sin empresa asociada")
else:
    print(f"\n   ❌ No hay casos en la base de datos")

print("\n" + "=" * 60)

db.close()