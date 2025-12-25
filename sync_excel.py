"""
Sincronización AUTOMÁTICA desde Google Sheets
Ahora incluye emails de copia por empresa (Hoja 2)
"""

import os
import pandas as pd
import requests
from datetime import datetime
from app.database import SessionLocal, Employee, Company
from io import BytesIO

GOOGLE_DRIVE_FILE_ID = "1POt2ytSN61XbSpXUSUPyHdOVy2g7CRas"
EXCEL_DOWNLOAD_URL = f"https://docs.google.com/spreadsheets/d/{GOOGLE_DRIVE_FILE_ID}/export?format=xlsx"
LOCAL_CACHE_PATH = "/tmp/base_empleados_cache.xlsx"

def descargar_excel_desde_drive():
    """Descarga el Excel desde Google Drive"""
    try:
        print(f"📥 Descargando Excel desde Google Sheets...")
        response = requests.get(EXCEL_DOWNLOAD_URL, timeout=30)
        
        if response.status_code == 200:
            with open(LOCAL_CACHE_PATH, 'wb') as f:
                f.write(response.content)
            print(f"✅ Excel descargado ({len(response.content)} bytes)")
            return LOCAL_CACHE_PATH
        else:
            print(f"❌ Error descargando Excel: HTTP {response.status_code}")
            if os.path.exists(LOCAL_CACHE_PATH):
                print(f"⚠️ Usando cache anterior")
                return LOCAL_CACHE_PATH
            return None
    except Exception as e:
        print(f"❌ Error: {e}")
        if os.path.exists(LOCAL_CACHE_PATH):
            print(f"⚠️ Usando cache anterior")
            return LOCAL_CACHE_PATH
        return None


def sincronizar_empleado_desde_excel(cedula: str):
    """Sincroniza UN empleado específico (sync instantánea)"""
    db = SessionLocal()
    try:
        empleado_bd = db.query(Employee).filter(Employee.cedula == cedula).first()
        if empleado_bd:
            print(f"✅ Empleado {cedula} ya está en BD")
            return empleado_bd
        
        excel_path = descargar_excel_desde_drive()
        if not excel_path:
            print(f"❌ No se pudo descargar el Excel")
            return None
        
        # ✅ Leer Hoja 1: Empleados
        df = pd.read_excel(excel_path, sheet_name=0)  # Primera hoja
        
        try:
            cedula_int = int(cedula)
        except ValueError:
            print(f"❌ Cédula inválida: {cedula}")
            return None
        
        empleado_excel = df[df["cedula"] == cedula_int]
        if empleado_excel.empty:
            print(f"❌ Empleado {cedula} no encontrado")
            return None
        
        row = empleado_excel.iloc[0]
        empresa_nombre = row["empresa"]
        
        # Buscar o crear empresa
        company = db.query(Company).filter(Company.nombre == empresa_nombre).first()
        if not company:
            company = Company(nombre=empresa_nombre, activa=True)
            db.add(company)
            db.commit()
            db.refresh(company)
            print(f"✅ Empresa creada: {empresa_nombre}")
        
        nuevo_empleado = Employee(
            cedula=str(row["cedula"]),
            nombre=row["nombre"],
            correo=row["correo"],
            telefono=str(row.get("telefono", "")) if pd.notna(row.get("telefono")) else None,
            company_id=company.id,
            eps=row.get("eps", None),
            activo=True
        )
        db.add(nuevo_empleado)
        db.commit()
        db.refresh(nuevo_empleado)
        print(f"✅ Empleado {cedula} sincronizado: {nuevo_empleado.nombre}")
        return nuevo_empleado
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
        return None
    finally:
        db.close()


def sincronizar_excel_completo():
    """
    Sincroniza TODO el Excel a PostgreSQL
    Ahora incluye Hoja 2: Emails de copia por empresa
    """
    db = SessionLocal()
    try:
        print(f"🔄 Iniciando sync Google Sheets a PostgreSQL...")
        excel_path = descargar_excel_desde_drive()
        if not excel_path:
            print(f"❌ No se pudo descargar el Excel")
            return
        
        # ========== HOJA 1: EMPLEADOS ==========
        print(f"\n📊 Procesando Hoja 1: Empleados...")
        df_empleados = pd.read_excel(excel_path, sheet_name=0)  # Primera hoja
        print(f"📊 Empleados en Excel: {len(df_empleados)} filas")
        
        cedulas_excel = set(str(int(row["cedula"])) for _, row in df_empleados.iterrows() if pd.notna(row["cedula"]))
        empleados_bd = db.query(Employee).all()
        cedulas_bd = {emp.cedula for emp in empleados_bd}
        nuevos = actualizados = desactivados = 0
        
        for _, row in df_empleados.iterrows():
            try:
                if pd.isna(row.get("cedula")) or pd.isna(row.get("nombre")):
                    continue
                
                cedula = str(int(row["cedula"]))
                nombre = row["nombre"]
                correo = row.get("correo", "")
                telefono = str(row.get("telefono", "")) if pd.notna(row.get("telefono")) else None
                eps = row.get("eps", None)
                empresa_nombre = row["empresa"]
                
                company = db.query(Company).filter(Company.nombre == empresa_nombre).first()
                if not company:
                    company = Company(nombre=empresa_nombre, activa=True)
                    db.add(company)
                    db.commit()
                    db.refresh(company)
                
                empleado = db.query(Employee).filter(Employee.cedula == cedula).first()
                if not empleado:
                    nuevo_empleado = Employee(
                        cedula=cedula,
                        nombre=nombre,
                        correo=correo,
                        telefono=telefono,
                        company_id=company.id,
                        eps=eps,
                        activo=True
                    )
                    db.add(nuevo_empleado)
                    db.commit()
                    nuevos += 1
                else:
                    cambios = False
                    if empleado.nombre != nombre: empleado.nombre = nombre; cambios = True
                    if empleado.correo != correo: empleado.correo = correo; cambios = True
                    if empleado.telefono != telefono: empleado.telefono = telefono; cambios = True
                    if empleado.eps != eps: empleado.eps = eps; cambios = True
                    if empleado.company_id != company.id: empleado.company_id = company.id; cambios = True
                    if not empleado.activo: empleado.activo = True; cambios = True
                    if cambios:
                        db.commit()
                        actualizados += 1
            except Exception as e:
                print(f"❌ Error en fila {row.get('cedula', 'N/A')}: {e}")
                db.rollback()
        
        # Desactivar empleados que ya no están en Excel
        for empleado in empleados_bd:
            if empleado.cedula not in cedulas_excel and empleado.activo:
                empleado.activo = False
                db.commit()
                desactivados += 1
        
        print(f"✅ Empleados: {nuevos} nuevos, {actualizados} actualizados, {desactivados} desactivados")
        
        # ========== HOJA 2: EMAILS DE COPIA ==========
        print(f"\n📊 Procesando Hoja 2: Emails de Copia...")
        
        try:
            df_emails = pd.read_excel(excel_path, sheet_name=1)  # Segunda hoja
            print(f"📊 Empresas con emails: {len(df_emails)} filas")
            
            emails_actualizados = 0
            
            for _, row in df_emails.iterrows():
                try:
                    if pd.isna(row.get("empresa")):
                        continue
                    
                    empresa_nombre = row["empresa"]
                    email_copia = str(row.get("email_copia", "")) if pd.notna(row.get("email_copia")) else None
                    
                    company = db.query(Company).filter(Company.nombre == empresa_nombre).first()
                    
                    if company:
                        if company.email_copia != email_copia:
                            company.email_copia = email_copia
                            db.commit()
                            emails_actualizados += 1
                            print(f"  ✅ {empresa_nombre}: {email_copia}")
                    else:
                        # Crear empresa si no existe
                        new_company = Company(
                            nombre=empresa_nombre,
                            email_copia=email_copia,
                            activa=True
                        )
                        db.add(new_company)
                        db.commit()
                        print(f"  ✅ {empresa_nombre} creada con emails: {email_copia}")
                
                except Exception as e:
                    print(f"  ❌ Error en empresa {row.get('empresa', 'N/A')}: {e}")
                    db.rollback()
            
            print(f"✅ Emails de copia: {emails_actualizados} actualizados")
        
        except Exception as e:
            print(f"⚠️ No se pudo leer Hoja 2 (Emails_Copia): {e}")
            print(f"   Si no existe, crea una segunda hoja con columnas: empresa | email_copia")
        
        print("\n✅ Sync completado\n")
        
    except Exception as e:
        print(f"❌ Error en sync: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()