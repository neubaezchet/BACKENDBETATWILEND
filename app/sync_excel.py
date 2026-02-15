"""
Sincronización AUTOMÁTICA Google Sheets → PostgreSQL
✅ SYNC EXACTO: La BD refleja el Excel tal cual (misma cantidad, mismo orden)
"""

import os
import pandas as pd
import requests
from datetime import datetime
from app.database import SessionLocal, Employee, Company, Case
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
            print(f"✅ Excel descargado correctamente ({len(response.content)} bytes)")
            return LOCAL_CACHE_PATH
        else:
            print(f"❌ Error descargando Excel: HTTP {response.status_code}")
            if os.path.exists(LOCAL_CACHE_PATH):
                print(f"⚠️ Usando cache anterior")
                return LOCAL_CACHE_PATH
            return None
    except Exception as e:
        print(f"❌ Error descargando Excel: {e}")
        if os.path.exists(LOCAL_CACHE_PATH):
            print(f"⚠️ Usando cache anterior")
            return LOCAL_CACHE_PATH
        return None


def sincronizar_empleado_desde_excel(cedula: str):
    """Sincroniza UN empleado especifico (sync instantanea)"""
    db = SessionLocal()
    try:
        empleado_bd = db.query(Employee).filter(Employee.cedula == cedula).first()
        if empleado_bd:
            print(f"✅ Empleado {cedula} ya esta en BD")
            return empleado_bd
        
        excel_path = descargar_excel_desde_drive()
        if not excel_path:
            print(f"❌ No se pudo descargar el Excel")
            return None
        
        df = pd.read_excel(excel_path, sheet_name=0)
        try:
            cedula_int = int(cedula)
        except ValueError:
            print(f"❌ Cedula invalida: {cedula}")
            return None
        
        empleado_excel = df[df["cedula"] == cedula_int]
        if empleado_excel.empty:
            print(f"❌ Empleado {cedula} no encontrado en Excel")
            return None
        
        row = empleado_excel.iloc[0]
        empresa_nombre = row["empresa"]
        company = db.query(Company).filter(Company.nombre == empresa_nombre).first()
        if not company:
            company = Company(nombre=empresa_nombre, activa=True)
            db.add(company)
            db.commit()
            db.refresh(company)
        
        nuevo_empleado = Employee(
            cedula=str(row["cedula"]),
            nombre=row["nombre"],
            correo=row["correo"],
            telefono=str(row.get("telefono", "")) if pd.notna(row.get("telefono")) else None,
            company_id=company.id,
            eps=row.get("eps", None),
            jefe_nombre=row.get("jefe_nombre", None),
            jefe_email=row.get("jefe_email", None),
            jefe_cargo=row.get("jefe_cargo", None),
            area_trabajo=row.get("area_trabajo", None),
            cargo=row.get("cargo", None) if pd.notna(row.get("cargo", None)) else None,
            centro_costo=row.get("centro_costo", None) if pd.notna(row.get("centro_costo", None)) else None,
            fecha_ingreso=pd.to_datetime(row.get("fecha_ingreso")) if pd.notna(row.get("fecha_ingreso", None)) else None,
            tipo_contrato=row.get("tipo_contrato", None) if pd.notna(row.get("tipo_contrato", None)) else None,
            dias_kactus=int(row.get("dias_kactus")) if pd.notna(row.get("dias_kactus", None)) else None,
            ciudad=row.get("ciudad", None) if pd.notna(row.get("ciudad", None)) else None,
            activo=True
        )
        db.add(nuevo_empleado)
        db.commit()
        db.refresh(nuevo_empleado)
        print(f"✅ Empleado {cedula} sincronizado: {nuevo_empleado.nombre}")
        return nuevo_empleado
    except Exception as e:
        print(f"❌ Error sincronizando {cedula}: {e}")
        db.rollback()
        return None
    finally:
        db.close()


def sincronizar_excel_completo():
    """
    ✅ SYNC EXACTO POR POSICIÓN
    - Fila 1 Excel = ID 1 en BD
    - Fila 2 Excel = ID 2 en BD
    - Si editas Fila 3, actualiza ID 3 (NO crea ID 9)
    - Si Excel tiene 8 filas, BD tiene 8 empleados activos
    """
    db = SessionLocal()
    try:
        print(f"\n{'='*60}")
        print(f"🔄 SYNC EXACTO Excel → PostgreSQL - {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*60}\n")
        
        excel_path = descargar_excel_desde_drive()
        if not excel_path:
            print(f"❌ No se pudo descargar el Excel, sync cancelado\n")
            return
        
        # ========== PASO 1: SYNC EMPRESAS (HOJA 2) ==========
        print(f"📊 PASO 1: Sincronizando empresas (Hoja 2)...")
        empresas_actualizadas = 0
        
        try:
            df_empresas = None
            nombres_posibles = ['Hoja 2', 'Empresas', 'Sheet2', 'Hoja2']
            
            for nombre_hoja in nombres_posibles:
                try:
                    df_empresas = pd.read_excel(excel_path, sheet_name=nombre_hoja)
                    print(f"   ✅ Hoja encontrada: '{nombre_hoja}' ({len(df_empresas)} filas)")
                    break
                except:
                    continue
            
            if df_empresas is None:
                print(f"   ⚠️ No se encontró Hoja 2. Continuando sin emails de copia...\n")
            else:
                for _, row in df_empresas.iterrows():
                    try:
                        nombre_col = 'nombre' if 'nombre' in df_empresas.columns else 'empresa'
                        
                        if pd.isna(row.get(nombre_col)) or pd.isna(row.get('email_copia')):
                            continue
                        
                        empresa_nombre = str(row[nombre_col]).strip()
                        email_copia = str(row['email_copia']).strip()
                        
                        empresa = db.query(Company).filter(Company.nombre == empresa_nombre).first()
                        
                        if empresa:
                            if empresa.email_copia != email_copia:
                                empresa.email_copia = email_copia
                                empresa.contacto_email = email_copia
                                empresa.updated_at = datetime.now()
                                db.commit()
                                empresas_actualizadas += 1
                                print(f"   🔄 {empresa_nombre} → {email_copia}")
                        else:
                            nueva_empresa = Company(
                                nombre=empresa_nombre,
                                email_copia=email_copia,
                                contacto_email=email_copia,
                                activa=True
                            )
                            db.add(nueva_empresa)
                            db.commit()
                            empresas_actualizadas += 1
                            print(f"   ➕ {empresa_nombre} → {email_copia}")
                    
                    except Exception as e:
                        print(f"   ❌ Error en empresa: {e}")
                        db.rollback()
                
                if empresas_actualizadas > 0:
                    print(f"   ✅ {empresas_actualizadas} empresas actualizadas\n")
                else:
                    print(f"   ℹ️ Sin cambios en empresas\n")
        
        except Exception as e:
            print(f"   ❌ Error leyendo Hoja 2: {e}\n")
        
        # ========== PASO 2: SYNC EMPLEADOS EXACTO ==========
        print(f"📊 PASO 2: Sincronizando empleados (MODO EXACTO)...")
        
        df = pd.read_excel(excel_path, sheet_name=0)
        print(f"   📋 Excel tiene {len(df)} filas")
        
        # Obtener TODOS los empleados de BD ordenados por ID
        empleados_bd = db.query(Employee).order_by(Employee.id).all()
        print(f"   📋 BD tiene {len(empleados_bd)} empleados totales")
        
        # Crear lista de empleados activos en BD
        empleados_activos = [e for e in empleados_bd if e.activo]
        print(f"   📋 BD tiene {len(empleados_activos)} empleados activos")
        
        nuevos = actualizados = eliminados = 0
        
        # ✅ SINCRONIZACIÓN POSICIÓN POR POSICIÓN
        for idx, row in df.iterrows():
            try:
                if pd.isna(row.get("cedula")) or pd.isna(row.get("nombre")):
                    continue
                
                # Datos del Excel
                cedula = str(int(row["cedula"]))
                nombre = row["nombre"]
                correo = row.get("correo", "")
                telefono = str(row.get("telefono", "")) if pd.notna(row.get("telefono")) else None
                eps = row.get("eps", None)
                empresa_nombre = row["empresa"]
                
                jefe_nombre = row.get("jefe_nombre", None)
                jefe_email = row.get("jefe_email", None)
                jefe_cargo = row.get("jefe_cargo", None)
                area_trabajo = row.get("area_trabajo", None)
                
                # ✅ COLUMNAS KACTUS
                cargo = row.get("cargo", None) if pd.notna(row.get("cargo", None)) else None
                centro_costo = row.get("centro_costo", None) if pd.notna(row.get("centro_costo", None)) else None
                fecha_ingreso_raw = row.get("fecha_ingreso", None)
                fecha_ingreso = None
                if pd.notna(fecha_ingreso_raw):
                    try:
                        fecha_ingreso = pd.to_datetime(fecha_ingreso_raw)
                    except Exception:
                        fecha_ingreso = None
                tipo_contrato = row.get("tipo_contrato", None) if pd.notna(row.get("tipo_contrato", None)) else None
                dias_kactus_raw = row.get("dias_kactus", None)
                dias_kactus_emp = int(dias_kactus_raw) if pd.notna(dias_kactus_raw) else None
                ciudad = row.get("ciudad", None) if pd.notna(row.get("ciudad", None)) else None
                
                # Buscar o crear empresa
                company = db.query(Company).filter(Company.nombre == empresa_nombre).first()
                if not company:
                    company = Company(nombre=empresa_nombre, activa=True)
                    db.add(company)
                    db.commit()
                    db.refresh(company)
                
                # ✅ LÓGICA CLAVE: Buscar empleado en la MISMA POSICIÓN
                empleado = None
                
                # Si ya existe un empleado en esta posición (índice)
                if idx < len(empleados_activos):
                    empleado = empleados_activos[idx]
                
                if empleado:
                    # ✅ ACTUALIZAR el empleado existente en esta posición
                    empleado.cedula = cedula
                    empleado.nombre = nombre
                    empleado.correo = correo
                    empleado.telefono = telefono
                    empleado.company_id = company.id
                    empleado.eps = eps
                    empleado.jefe_nombre = jefe_nombre
                    empleado.jefe_email = jefe_email
                    empleado.jefe_cargo = jefe_cargo
                    empleado.area_trabajo = area_trabajo
                    empleado.cargo = cargo
                    empleado.centro_costo = centro_costo
                    empleado.fecha_ingreso = fecha_ingreso
                    empleado.tipo_contrato = tipo_contrato
                    empleado.dias_kactus = dias_kactus_emp
                    empleado.ciudad = ciudad
                    empleado.activo = True
                    empleado.updated_at = datetime.now()
                    db.commit()
                    actualizados += 1
                else:
                    # ✅ CREAR nuevo empleado (si Excel tiene más filas que BD)
                    nuevo_empleado = Employee(
                        cedula=cedula,
                        nombre=nombre,
                        correo=correo,
                        telefono=telefono,
                        company_id=company.id,
                        eps=eps,
                        jefe_nombre=jefe_nombre,
                        jefe_email=jefe_email,
                        jefe_cargo=jefe_cargo,
                        area_trabajo=area_trabajo,
                        cargo=cargo,
                        centro_costo=centro_costo,
                        fecha_ingreso=fecha_ingreso,
                        tipo_contrato=tipo_contrato,
                        dias_kactus=dias_kactus_emp,
                        ciudad=ciudad,
                        activo=True
                    )
                    db.add(nuevo_empleado)
                    db.commit()
                    nuevos += 1
            
            except Exception as e:
                print(f"   ❌ Error en fila {idx + 2}: {e}")
                db.rollback()
        
        # ✅ ELIMINAR empleados sobrantes (si BD tiene más que Excel)
        total_filas_excel = len(df)
        if len(empleados_activos) > total_filas_excel:
            print(f"   🗑️ BD tiene {len(empleados_activos) - total_filas_excel} empleados de más, eliminando...")
            for i in range(total_filas_excel, len(empleados_activos)):
                empleado_sobra = empleados_activos[i]
                empleado_sobra.activo = False
                empleado_sobra.updated_at = datetime.now()
                db.commit()
                eliminados += 1
        
        # RESUMEN
        print(f"\n{'='*60}")
        print(f"✅ SYNC COMPLETADO")
        print(f"   • Empresas actualizadas: {empresas_actualizadas}")
        print(f"   • Empleados nuevos: {nuevos}")
        print(f"   • Empleados actualizados: {actualizados}")
        print(f"   • Empleados eliminados: {eliminados}")
        print(f"   • Total activos en BD: {total_filas_excel}")
        print(f"{'='*60}\n")
        
        # ========== PASO 3: SYNC CASES_KACTUS (Hoja 3) ==========
        try:
            df_cases = pd.read_excel(excel_path, sheet_name=2)  # Hoja 3 = Cases_Kactus
            if len(df_cases) > 0:
                print(f"📊 PASO 3: Sincronizando Cases_Kactus ({len(df_cases)} filas)...")
                cases_actualizados = 0
                
                for _, row in df_cases.iterrows():
                    try:
                        cedula_raw = row.get("cedula")
                        fecha_inicio_raw = row.get("fecha_inicio")
                        
                        if pd.isna(cedula_raw) or pd.isna(fecha_inicio_raw):
                            continue
                        
                        cedula_case = str(int(cedula_raw))
                        fecha_inicio_case = pd.to_datetime(fecha_inicio_raw)
                        
                        # Buscar caso por cedula + fecha_inicio (±1 día de tolerancia)
                        from sqlalchemy import and_, func
                        caso = db.query(Case).filter(
                            Case.cedula == cedula_case,
                            func.date(Case.fecha_inicio) == fecha_inicio_case.date()
                        ).first()
                        
                        if caso:
                            # Actualizar campos Kactus
                            if pd.notna(row.get("numero_incapacidad")):
                                caso.numero_incapacidad = str(row["numero_incapacidad"])
                            if pd.notna(row.get("dias_kactus")):
                                caso.dias_kactus = int(row["dias_kactus"])
                            if pd.notna(row.get("codigo_cie10")):
                                caso.codigo_cie10 = str(row["codigo_cie10"])
                            if pd.notna(row.get("es_prorroga")):
                                val = str(row["es_prorroga"]).strip().upper()
                                caso.es_prorroga = val in ("SI", "SÍ", "YES", "TRUE", "1")
                            if pd.notna(row.get("medico_tratante")):
                                caso.medico_tratante = str(row["medico_tratante"])
                            if pd.notna(row.get("institucion_origen")):
                                caso.institucion_origen = str(row["institucion_origen"])
                            
                            caso.updated_at = datetime.now()
                            db.commit()
                            cases_actualizados += 1
                    except Exception as e:
                        print(f"   ❌ Error en case row: {e}")
                        db.rollback()
                
                print(f"   ✅ {cases_actualizados} casos actualizados con datos Kactus")
            else:
                print(f"   ℹ️ Hoja Cases_Kactus vacía o sin datos")
        except Exception as e:
            if "Worksheet index" in str(e) or "No sheet" in str(e):
                print(f"   ℹ️ Hoja 3 (Cases_Kactus) no existe aún, omitiendo...")
            else:
                print(f"   ⚠️ Error leyendo Cases_Kactus: {e}")
        
    except Exception as e:
        print(f"\n❌ ERROR GENERAL EN SYNC: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()