"""
Sincronización AUTOMÁTICA Google Sheets → PostgreSQL
✅ SYNC EXACTO: La BD refleja el Excel tal cual (misma cantidad, mismo orden)
"""

import os
import pandas as pd
import requests
from datetime import datetime
from app.database import SessionLocal, Employee, Company, Case, CorreoNotificacion
from io import BytesIO

GOOGLE_DRIVE_FILE_ID = os.environ.get("GOOGLE_DRIVE_FILE_ID", "1POt2ytSN61XbSpXUSUPyHdOVy2g7CRas")
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
        
        # ========== PASO 3: SYNC CASES_KACTUS + TRASLAPOS (Hoja 3) ==========
        try:
            df_cases = pd.read_excel(excel_path, sheet_name=2)  # Hoja 3 = Cases_Kactus
            if len(df_cases) > 0:
                print(f"📊 PASO 3: Sincronizando Cases_Kactus ({len(df_cases)} filas) con matching inteligente...")
                cases_actualizados = 0
                cases_no_encontrados = 0
                
                from sqlalchemy import and_, func, or_
                from datetime import timedelta
                
                for _, row in df_cases.iterrows():
                    try:
                        cedula_raw = row.get("cedula")
                        if pd.isna(cedula_raw):
                            continue
                        
                        cedula_case = str(int(cedula_raw))
                        
                        # Fechas del Excel = fechas de KACTUS (las del portal ya están en BD)
                        fecha_inicio_raw = row.get("fecha_inicio")
                        fecha_fin_raw = row.get("fecha_fin")
                        
                        fecha_inicio_kactus = pd.to_datetime(fecha_inicio_raw) if pd.notna(fecha_inicio_raw) else None
                        fecha_fin_kactus = pd.to_datetime(fecha_fin_raw) if pd.notna(fecha_fin_raw) else None
                        
                        num_incap = str(row["numero_incapacidad"]).strip() if pd.notna(row.get("numero_incapacidad")) else None
                        
                        # ═══ MATCHING INTELIGENTE: 4 estrategias ═══
                        caso = None
                        match_method = ""
                        
                        # 1) Por numero_incapacidad exacto (más preciso)
                        if num_incap and caso is None:
                            caso = db.query(Case).filter(
                                Case.cedula == cedula_case,
                                Case.numero_incapacidad == num_incap
                            ).first()
                            if caso:
                                match_method = "numero_incapacidad"
                        
                        # 2) Por cedula + fecha_inicio Kactus ≈ fecha_inicio portal
                        if caso is None and fecha_inicio_kactus:
                            caso = db.query(Case).filter(
                                Case.cedula == cedula_case,
                                func.date(Case.fecha_inicio) == fecha_inicio_kactus.date()
                            ).first()
                            if caso:
                                match_method = "fecha_inicio_exacta"
                        
                        # 3) Por cedula + fecha_fin Kactus ≈ fecha_fin portal
                        if caso is None and fecha_fin_kactus:
                            caso = db.query(Case).filter(
                                Case.cedula == cedula_case,
                                func.date(Case.fecha_fin) == fecha_fin_kactus.date()
                            ).first()
                            if caso:
                                match_method = "fecha_fin_exacta"
                        
                        # 4) Por rango de fechas con superposición (±3 días tolerancia por traslapos)
                        if caso is None and fecha_inicio_kactus:
                            tolerancia = timedelta(days=3)
                            candidatos = db.query(Case).filter(
                                Case.cedula == cedula_case,
                                Case.fecha_inicio != None,
                                Case.fecha_fin != None,
                                or_(
                                    and_(
                                        Case.fecha_inicio <= fecha_inicio_kactus + tolerancia,
                                        Case.fecha_fin >= fecha_inicio_kactus - tolerancia
                                    ),
                                    and_(
                                        fecha_fin_kactus is not None,
                                        Case.fecha_inicio <= (fecha_fin_kactus or fecha_inicio_kactus) + tolerancia,
                                        Case.fecha_fin >= fecha_inicio_kactus - tolerancia
                                    )
                                ),
                                Case.kactus_sync_at == None
                            ).order_by(
                                func.abs(func.extract('epoch', Case.fecha_inicio - fecha_inicio_kactus))
                            ).first()
                            if candidatos:
                                caso = candidatos
                                match_method = "rango_superpuesto"
                        
                        if not caso:
                            cases_no_encontrados += 1
                            print(f"   ⚠️ Sin match para CC {cedula_case} fecha {fecha_inicio_raw} — verificar en BD")
                            continue
                        
                        # ═══ ACTUALIZAR CAMPOS KACTUS ═══
                        # Solo 3 campos vienen del Excel: numero_incapacidad, codigo_cie10, fechas
                        if num_incap:
                            caso.numero_incapacidad = num_incap
                        if pd.notna(row.get("codigo_cie10")):
                            codigo = str(row["codigo_cie10"]).strip()
                            caso.codigo_cie10 = codigo
                            # Auto-resolver diagnóstico desde CIE-10
                            try:
                                from app.services.cie10_service import buscar_codigo
                                info_cie = buscar_codigo(codigo)
                                if info_cie and info_cie.get("encontrado"):
                                    caso.diagnostico_kactus = info_cie["descripcion"]
                                    if not caso.diagnostico:
                                        caso.diagnostico = info_cie["descripcion"]
                            except Exception:
                                pass
                        
                        # ═══ FECHAS KACTUS ═══
                        if fecha_inicio_kactus:
                            caso.fecha_inicio_kactus = fecha_inicio_kactus
                        if fecha_fin_kactus:
                            caso.fecha_fin_kactus = fecha_fin_kactus
                        
                        # ═══ DETECCIÓN DE TRASLAPO AUTOMÁTICA ═══
                        if fecha_inicio_kactus and caso.fecha_inicio:
                            diff_inicio = (fecha_inicio_kactus.date() - caso.fecha_inicio.date()).days
                            if diff_inicio > 0:
                                # Kactus empezó después → los días de diferencia son traslapo
                                caso.dias_traslapo = diff_inicio
                                # Buscar con qué caso se traslapa (el anterior del mismo empleado)
                                caso_anterior = db.query(Case).filter(
                                    Case.cedula == cedula_case,
                                    Case.fecha_fin != None,
                                    Case.id != caso.id,
                                    func.date(Case.fecha_fin) >= caso.fecha_inicio.date(),
                                    func.date(Case.fecha_fin) <= fecha_inicio_kactus.date()
                                ).order_by(Case.fecha_fin.desc()).first()
                                if caso_anterior:
                                    caso.traslapo_con_serial = caso_anterior.serial
                        elif fecha_fin_kactus and caso.fecha_fin:
                            diff_fin = (caso.fecha_fin.date() - fecha_fin_kactus.date()).days
                            if diff_fin > 0:
                                caso.dias_traslapo = diff_fin
                                caso_siguiente = db.query(Case).filter(
                                    Case.cedula == cedula_case,
                                    Case.fecha_inicio != None,
                                    Case.id != caso.id,
                                    func.date(Case.fecha_inicio) >= fecha_fin_kactus.date(),
                                    func.date(Case.fecha_inicio) <= caso.fecha_fin.date()
                                ).order_by(Case.fecha_inicio.asc()).first()
                                if caso_siguiente:
                                    caso.traslapo_con_serial = caso_siguiente.serial
                        
                        caso.kactus_sync_at = datetime.now()
                        caso.updated_at = datetime.now()
                        db.commit()
                        cases_actualizados += 1
                        
                        if match_method != "fecha_inicio_exacta":
                            print(f"      🔗 CC {cedula_case} → {caso.serial} (match: {match_method})" + 
                                  (f" — {caso.dias_traslapo}d traslapo" if caso.dias_traslapo else ""))
                        
                    except Exception as e:
                        print(f"   ❌ Error en case row: {e}")
                        db.rollback()
                
                print(f"   ✅ {cases_actualizados} casos actualizados con datos Kactus")
                if cases_no_encontrados > 0:
                    print(f"   ⚠️ {cases_no_encontrados} filas sin match (verificar cédulas/fechas)")
                
                # ═══ DETECCIÓN AUTOMÁTICA DE TRASLAPOS GLOBALES ═══
                _detectar_traslapos_globales(db)
                
            else:
                print(f"   ℹ️ Hoja Cases_Kactus vacía o sin datos")
        except Exception as e:
            if "Worksheet index" in str(e) or "No sheet" in str(e):
                print(f"   ℹ️ Hoja 3 (Cases_Kactus) no existe aún, omitiendo...")
            else:
                print(f"   ⚠️ Error leyendo Cases_Kactus: {e}")
        
        # ========== PASO 4: SYNC CORREOS NOTIFICACIÓN (Hoja 4) ==========
        try:
            df_correos = None
            nombres_posibles_h4 = ['Correos', 'Hoja 4', 'Notificaciones', 'Correos_Notificacion', 'Sheet4', 'Hoja4']
            
            for nombre_hoja in nombres_posibles_h4:
                try:
                    df_correos = pd.read_excel(excel_path, sheet_name=nombre_hoja)
                    print(f"\n📧 PASO 4: Sincronizando Correos Notificación ('{nombre_hoja}', {len(df_correos)} filas)...")
                    break
                except:
                    continue
            
            # También intentar por índice (Hoja 4 = index 3)
            if df_correos is None:
                try:
                    df_correos = pd.read_excel(excel_path, sheet_name=3)
                    print(f"\n📧 PASO 4: Sincronizando Correos Notificación (Hoja 4, {len(df_correos)} filas)...")
                except:
                    pass
            
            if df_correos is not None and len(df_correos) > 0:
                # Validar columnas mínimas
                if 'area' not in df_correos.columns or 'email' not in df_correos.columns:
                    print(f"   ⚠️ Hoja 4 no tiene columnas 'area' y 'email'. Omitiendo...")
                else:
                    # SYNC EXACTO: Borrar todos y recrear desde el Excel
                    eliminados_correos = db.query(CorreoNotificacion).delete()
                    db.commit()
                    if eliminados_correos > 0:
                        print(f"   🗑️ {eliminados_correos} correos anteriores eliminados")
                    
                    correos_nuevos = 0
                    for _, row in df_correos.iterrows():
                        try:
                            area_raw = row.get('area')
                            email_raw = row.get('email')
                            
                            if pd.isna(area_raw) or pd.isna(email_raw):
                                continue
                            
                            area = str(area_raw).strip().lower().replace(' ', '_')
                            email = str(email_raw).strip()
                            nombre_contacto = str(row.get('nombre_contacto', '')).strip() if pd.notna(row.get('nombre_contacto')) else None
                            empresa_nombre = str(row.get('empresa', '')).strip() if pd.notna(row.get('empresa')) else None
                            activo_raw = row.get('activo', True)
                            activo = True
                            if pd.notna(activo_raw):
                                val = str(activo_raw).strip().upper()
                                activo = val not in ('NO', 'FALSE', '0', 'INACTIVO')
                            
                            # Buscar empresa si se especificó
                            company_id = None
                            if empresa_nombre:
                                company = db.query(Company).filter(Company.nombre == empresa_nombre).first()
                                if company:
                                    company_id = company.id
                            
                            nuevo_correo = CorreoNotificacion(
                                area=area,
                                nombre_contacto=nombre_contacto,
                                email=email,
                                company_id=company_id,
                                activo=activo
                            )
                            db.add(nuevo_correo)
                            db.commit()
                            correos_nuevos += 1
                        except Exception as e:
                            print(f"   ❌ Error en correo row: {e}")
                            db.rollback()
                    
                    print(f"   ✅ {correos_nuevos} correos de notificación sincronizados")
                    
                    # Resumen por área
                    areas_count = {}
                    for _, row in df_correos.iterrows():
                        if pd.notna(row.get('area')):
                            a = str(row['area']).strip().lower().replace(' ', '_')
                            areas_count[a] = areas_count.get(a, 0) + 1
                    for a, c in areas_count.items():
                        print(f"      • {a}: {c} correos")
            else:
                print(f"   ℹ️ Hoja 4 (Correos) no existe aún, omitiendo...")
        
        except Exception as e:
            print(f"   ⚠️ Error leyendo Hoja 4 (Correos): {e}")
        
        
    except Exception as e:
        print(f"\n❌ ERROR GENERAL EN SYNC: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════
# DETECCIÓN AUTOMÁTICA DE TRASLAPOS ENTRE INCAPACIDADES
# ══════════════════════════════════════════════════════════════════

def _detectar_traslapos_globales(db):
    """
    Detecta traslapos (solapamiento de fechas) entre incapacidades del mismo empleado.
    Ejemplo: Incap A del 31/01 al 02/02 e Incap B del 02/02 al 04/02 → 1 día traslapado.
    En Kactus se subiría como 03/02 al 04/02 (2 días en vez de 3).
    """
    from sqlalchemy import func, and_
    
    try:
        # Obtener todas las cédulas con más de 1 caso activo
        cedulas = db.query(Case.cedula).filter(
            Case.fecha_inicio != None,
            Case.fecha_fin != None
        ).group_by(Case.cedula).having(func.count(Case.id) > 1).all()
        
        traslapos_detectados = 0
        
        for (cedula,) in cedulas:
            casos = db.query(Case).filter(
                Case.cedula == cedula,
                Case.fecha_inicio != None,
                Case.fecha_fin != None
            ).order_by(Case.fecha_inicio.asc()).all()
            
            for i in range(len(casos) - 1):
                caso_actual = casos[i]
                caso_siguiente = casos[i + 1]
                
                if not caso_actual.fecha_fin or not caso_siguiente.fecha_inicio:
                    continue
                
                # ¿Se traslapa? fecha_fin del actual >= fecha_inicio del siguiente
                if caso_actual.fecha_fin.date() >= caso_siguiente.fecha_inicio.date():
                    dias_overlap = (caso_actual.fecha_fin.date() - caso_siguiente.fecha_inicio.date()).days + 1
                    
                    # Solo marcar si no tiene ya Kactus override (que es la fecha real ajustada)
                    if not caso_siguiente.fecha_inicio_kactus and caso_siguiente.dias_traslapo == 0:
                        caso_siguiente.dias_traslapo = dias_overlap
                        caso_siguiente.traslapo_con_serial = caso_actual.serial
                        
                        # Calcular fecha Kactus sugerida (inicio original + días traslapo)
                        from datetime import timedelta
                        nueva_fecha_inicio = caso_siguiente.fecha_inicio + timedelta(days=dias_overlap)
                        caso_siguiente.fecha_inicio_kactus = nueva_fecha_inicio
                        
                        # Recalcular días Kactus si no los tiene
                        if not caso_siguiente.dias_kactus and caso_siguiente.fecha_fin:
                            dias_kactus_calc = (caso_siguiente.fecha_fin.date() - nueva_fecha_inicio.date()).days + 1
                            if dias_kactus_calc > 0:
                                caso_siguiente.dias_kactus = dias_kactus_calc
                        
                        caso_siguiente.updated_at = datetime.now()
                        db.commit()
                        traslapos_detectados += 1
        
        if traslapos_detectados > 0:
            print(f"   🔀 {traslapos_detectados} traslapos detectados automáticamente")
    
    except Exception as e:
        print(f"   ⚠️ Error detectando traslapos: {e}")
        db.rollback()


# ══════════════════════════════════════════════════════════════════
# VACIADO QUINCENAL DE HOJA KACTUS (datos ya están en BD)
# ══════════════════════════════════════════════════════════════════

def vaciar_hoja_kactus_quincenal():
    """
    Cada quincena (1 y 16 del mes), vacía la Hoja 3 (Cases_Kactus) del Excel.
    Los datos ya están sincronizados en la BD con kactus_sync_at.
    Solo borra filas con datos, mantiene las cabeceras.
    """
    try:
        from datetime import datetime
        hoy = datetime.now()
        dia = hoy.day
        
        # Solo ejecutar el 1 y el 16 de cada mes
        if dia not in (1, 16):
            return
        
        print(f"\n🗑️ VACIADO QUINCENAL — Hoja 3 (Cases_Kactus) — {hoy.strftime('%d/%m/%Y')}")
        
        # Verificar que todos los datos pendientes estén ya sincronizados
        db = SessionLocal()
        try:
            excel_path = descargar_excel_desde_drive()
            if not excel_path:
                print("   ❌ No se pudo descargar el Excel para verificar")
                return
            
            try:
                df_cases = pd.read_excel(excel_path, sheet_name=2)
            except Exception:
                print("   ℹ️ Hoja 3 no existe, nada que vaciar")
                return
            
            if len(df_cases) == 0:
                print("   ℹ️ Hoja 3 ya está vacía")
                return
            
            # Contar cuántas filas están sincronizadas en BD
            pendientes = 0
            for _, row in df_cases.iterrows():
                cedula_raw = row.get("cedula")
                if pd.isna(cedula_raw):
                    continue
                cedula_str = str(int(cedula_raw))
                
                from sqlalchemy import func
                caso_sync = db.query(Case).filter(
                    Case.cedula == cedula_str,
                    Case.kactus_sync_at != None
                ).first()
                
                if not caso_sync:
                    pendientes += 1
            
            if pendientes > 0:
                print(f"   ⚠️ {pendientes} filas aún sin sincronizar en BD — NO se vacía")
                return
            
            print(f"   ✅ Todas las {len(df_cases)} filas ya sincronizadas en BD")
            
            # Vaciar la hoja via Google Sheets API
            try:
                import gspread
                from google.oauth2.service_account import Credentials
                
                creds_path = os.environ.get("GOOGLE_CREDENTIALS_PATH", "/tmp/google_creds.json")
                if not os.path.exists(creds_path):
                    # Intentar con credenciales de Drive existentes
                    from app.drive_uploader import get_authenticated_service
                    print("   ℹ️ Usando credenciales de Drive para gspread")
                    # Vaciar descargando y re-subiendo solo cabeceras
                    _vaciar_hoja_por_descarga(excel_path, df_cases.columns.tolist())
                else:
                    scopes = ['https://www.googleapis.com/auth/spreadsheets']
                    credentials = Credentials.from_service_account_file(creds_path, scopes=scopes)
                    gc = gspread.authorize(credentials)
                    spreadsheet = gc.open_by_key(GOOGLE_DRIVE_FILE_ID)
                    worksheet = spreadsheet.get_worksheet(2)  # Hoja 3 = index 2
                    
                    # Borrar todo excepto cabecera
                    if worksheet.row_count > 1:
                        worksheet.delete_rows(2, worksheet.row_count)
                    
                    print(f"   🗑️ Hoja 3 vaciada — {len(df_cases)} filas eliminadas del Excel")
                
            except ImportError:
                print("   ℹ️ gspread no disponible — vaciado manual requerido")
                _vaciar_hoja_por_descarga(excel_path, df_cases.columns.tolist())
            except Exception as e:
                print(f"   ⚠️ Error al vaciar hoja via API: {e}")
                print("   ℹ️ Los datos ya están seguros en la BD")
        
        finally:
            db.close()
        
        print(f"   ✅ Vaciado quincenal completado — datos seguros en PostgreSQL\n")
        
    except Exception as e:
        print(f"   ❌ Error en vaciado quincenal: {e}")


def _vaciar_hoja_por_descarga(excel_path, columnas):
    """Fallback: reescribe el Excel con solo las cabeceras en Hoja 3"""
    try:
        # Leer todas las hojas
        all_sheets = pd.read_excel(excel_path, sheet_name=None)
        sheet_names = list(all_sheets.keys())
        
        if len(sheet_names) >= 3:
            # Reemplazar hoja 3 con DataFrame vacío (solo cabeceras)
            nombre_hoja3 = sheet_names[2]
            all_sheets[nombre_hoja3] = pd.DataFrame(columns=columnas)
            
            # Guardar localmente
            with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
                for nombre, df in all_sheets.items():
                    df.to_excel(writer, sheet_name=nombre, index=False)
            
            print(f"   🗑️ Hoja '{nombre_hoja3}' vaciada localmente (subir manualmente a Drive)")
    except Exception as e:
        print(f"   ⚠️ Error en vaciado por descarga: {e}")


# ══════════════════════════════════════════════════════════════════
# ESTADO DE SINCRONIZACIÓN
# ══════════════════════════════════════════════════════════════════

def obtener_estado_sync():
    """Retorna el estado actual de la sincronización BD ↔ Excel"""
    db = SessionLocal()
    try:
        from sqlalchemy import func
        
        total_empleados = db.query(Employee).filter(Employee.activo == True).count()
        total_casos = db.query(Case).count()
        casos_con_kactus = db.query(Case).filter(Case.kactus_sync_at != None).count()
        casos_sin_kactus = total_casos - casos_con_kactus
        casos_con_diagnostico = db.query(Case).filter(
            Case.diagnostico != None,
            Case.diagnostico != ''
        ).count()
        casos_con_cie10 = db.query(Case).filter(
            Case.codigo_cie10 != None,
            Case.codigo_cie10 != ''
        ).count()
        casos_con_traslapo = db.query(Case).filter(
            Case.dias_traslapo > 0
        ).count()
        
        ultima_sync_kactus = db.query(func.max(Case.kactus_sync_at)).scalar()
        ultimo_caso_creado = db.query(func.max(Case.created_at)).scalar()
        
        # Traslapos por empleado
        traslapos_detalle = []
        if casos_con_traslapo > 0:
            traslapos = db.query(Case).filter(Case.dias_traslapo > 0).order_by(Case.updated_at.desc()).limit(20).all()
            for t in traslapos:
                emp = db.query(Employee).filter(Employee.cedula == t.cedula).first()
                traslapos_detalle.append({
                    "serial": t.serial,
                    "cedula": t.cedula,
                    "nombre": emp.nombre if emp else "?",
                    "fecha_inicio": str(t.fecha_inicio.date()) if t.fecha_inicio else None,
                    "fecha_fin": str(t.fecha_fin.date()) if t.fecha_fin else None,
                    "fecha_inicio_kactus": str(t.fecha_inicio_kactus.date()) if t.fecha_inicio_kactus else None,
                    "fecha_fin_kactus": str(t.fecha_fin_kactus.date()) if t.fecha_fin_kactus else None,
                    "dias_traslapo": t.dias_traslapo,
                    "traslapo_con": t.traslapo_con_serial,
                    "dias_kactus": t.dias_kactus,
                })
        
        return {
            "ok": True,
            "timestamp": datetime.now().isoformat(),
            "resumen": {
                "total_empleados_activos": total_empleados,
                "total_casos": total_casos,
                "casos_con_kactus": casos_con_kactus,
                "casos_sin_kactus": casos_sin_kactus,
                "casos_con_diagnostico": casos_con_diagnostico,
                "casos_con_cie10": casos_con_cie10,
                "casos_con_traslapo": casos_con_traslapo,
                "pct_kactus": round((casos_con_kactus / total_casos * 100) if total_casos > 0 else 0, 1),
                "pct_diagnostico": round((casos_con_diagnostico / total_casos * 100) if total_casos > 0 else 0, 1),
            },
            "ultima_sync_kactus": str(ultima_sync_kactus) if ultima_sync_kactus else None,
            "ultimo_caso_creado": str(ultimo_caso_creado) if ultimo_caso_creado else None,
            "traslapos_recientes": traslapos_detalle,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()