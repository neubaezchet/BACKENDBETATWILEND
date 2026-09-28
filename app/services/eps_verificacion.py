# -*- coding: utf-8 -*-
"""
✅ Verificación de EPS de empleados activos vía CoreSoft (BDUA/ADRES).

Se usa en dos momentos:
  1. Barrido mensual de TODAS las empresas — ver
     app/tasks/scheduler_tasks.py → tarea_actualizar_eps_mensual.
  2. Primer barrido de UNA empresa nueva al activarse — enganchado en el
     flujo de onboarding/activación de tenant.

Fail-safe: un error verificando a un empleado puntual no detiene a los demás.
Respeta el tope de costo por ciclo (créditos disponibles en CoreSoft) y el
límite de consultas/minuto del plan.
"""

import time
import logging
from datetime import datetime
from typing import Optional

from app.database import SessionLocal, Employee
from app.coresoft_client import consultar_eps, consultar_creditos, CORESOFT_CONSULTAS_POR_MINUTO

logger = logging.getLogger(__name__)

# Cuántos días vale una verificación antes de considerarla vieja. El cron corre
# una vez al mes, así que 35 días cubre el ciclo completo sin volver a gastar
# créditos por un dato que acabamos de confirmar.
DIAS_FRESCURA_EPS = 35


def _aplicar_resultado(empleado, resultado: dict) -> bool:
    """
    Escribe en el empleado lo que devolvió CoreSoft. Devuelve True si la EPS
    cambió. Única función que toca estas columnas: la usan el barrido mensual y
    la consulta en vivo previa a radicar, para que no se separen con el tiempo.
    """
    eps_nueva = (resultado.get("eps") or "").strip()
    eps_actual = (empleado.eps or "").strip()
    cambio = bool(eps_nueva) and eps_nueva != eps_actual

    if cambio:
        empleado.eps_anterior = empleado.eps
        empleado.eps = eps_nueva
        empleado.eps_actualizado_en = datetime.utcnow()
        logger.info(
            f"   🔄 {empleado.cedula} ({empleado.nombre}): "
            f"'{empleado.eps_anterior}' → '{eps_nueva}'"
        )

    # Sello de frescura: se pone siempre que CoreSoft respondió, cambie o no.
    empleado.eps_verificado_en = datetime.utcnow()

    # Datos informativos: se refrescan siempre, cambie o no la EPS
    empleado.eps_regimen = (resultado.get("regimen") or "").strip() or None
    empleado.eps_estado = (resultado.get("estado") or "").strip() or None
    empleado.eps_tipo_afiliado = (resultado.get("tipo_afiliado") or "").strip() or None
    fecha_str = resultado.get("fecha_afiliacion")
    if fecha_str:
        try:
            empleado.eps_fecha_afiliacion = datetime.strptime(fecha_str, "%d/%m/%Y").date()
        except Exception:
            pass

    return cambio


def eps_esta_fresca(empleado) -> bool:
    """True si CoreSoft confirmó la EPS de este empleado hace poco."""
    sello = getattr(empleado, "eps_verificado_en", None)
    if not sello:
        return False
    return (datetime.utcnow() - sello).days <= DIAS_FRESCURA_EPS


def resolver_eps_para_radicacion(db, empleado, eps_documento: str = "") -> tuple:
    """
    Resuelve a qué EPS hay que radicar. Devuelve (eps, fuente).

    El campo EPS lo manda CoreSoft (ADRES/BDUA), que es el registro oficial de
    afiliación — no el texto impreso en el soporte, que puede venir de una IPS
    que copió una EPS vieja, ni la EPS de nuestra BD, que envejece.

    Orden:
      1. `coresoft`        — verificación fresca en BD (≤ DIAS_FRESCURA_EPS días).
      2. `coresoft_vivo`   — consulta en vivo (1 sola, 2 créditos) si está vieja
                             o nunca se hizo; se persiste para no repetirla.
      3. `base_datos`      — si CoreSoft no responde, lo que ya había.
      4. `documento`       — último recurso: lo que dice el soporte.

    Fail-safe: nunca lanza excepción. Si CoreSoft está caído la radicación
    sigue con el dato viejo en vez de detenerse.
    """
    eps_documento = (eps_documento or "").strip()

    if empleado is None:
        return (eps_documento, "documento") if eps_documento else ("", "sin_dato")

    if eps_esta_fresca(empleado) and (empleado.eps or "").strip():
        return empleado.eps.strip(), "coresoft"

    try:
        resultado = consultar_eps(empleado.cedula)
        if resultado and resultado.get("afiliado") and resultado.get("eps"):
            _aplicar_resultado(empleado, resultado)
            db.commit()
            return (empleado.eps or "").strip(), "coresoft_vivo"
        if resultado is not None:
            # Respondió pero la persona no aparece afiliada: dato válido y
            # accionable (probablemente retirado o en otro régimen).
            empleado.eps_verificado_en = datetime.utcnow()
            db.commit()
            logger.info(f"ℹ️ CoreSoft: {empleado.cedula} sin afiliación activa en BDUA")
    except Exception as e:
        logger.warning(f"⚠️ No se pudo resolver EPS con CoreSoft para {empleado.cedula}: {e}")
        try:
            db.rollback()
        except Exception:
            pass

    if (empleado.eps or "").strip():
        return empleado.eps.strip(), "base_datos"
    return (eps_documento, "documento") if eps_documento else ("", "sin_dato")


def verificar_eps_empleados(company_id: Optional[int] = None) -> dict:
    """
    Verifica la EPS de los empleados activos contra CoreSoft y actualiza
    employees.eps SOLO si cambió, guardando el valor anterior en eps_anterior
    y la fecha de detección en eps_actualizado_en.

    company_id=None → recorre empleados activos de TODAS las empresas (uso: cron mensual).
    company_id=<id> → recorre solo esa empresa (uso: primer barrido al activar un tenant).

    Devuelve un resumen: {total, verificados, actualizados, sin_cambio, fallidos}.
    Nunca lanza excepción.
    """
    db = SessionLocal()
    resumen = {"total": 0, "verificados": 0, "actualizados": 0, "sin_cambio": 0, "fallidos": 0}
    etiqueta = f"company_id={company_id}" if company_id is not None else "todas las empresas"

    try:
        query = db.query(Employee).filter(Employee.activo == True)  # noqa: E712
        if company_id is not None:
            query = query.filter(Employee.company_id == company_id)
        empleados = query.all()

        total = len(empleados)
        resumen["total"] = total
        if total == 0:
            logger.info(f"ℹ️ No hay empleados activos para verificar EPS ({etiqueta})")
            return resumen

        # Tope de costo por ciclo: no gastar más créditos de los disponibles
        creditos = consultar_creditos()
        limite = total
        if creditos is not None:
            disponibles = creditos.get("disponibles", 0) or 0
            costo_total = total * 2
            if costo_total > disponibles:
                limite = disponibles // 2
                logger.warning(
                    f"⚠️ Créditos CoreSoft insuficientes ({etiqueta}): se necesitan {costo_total} "
                    f"para {total} empleados, hay {disponibles} disponibles. "
                    f"Se verificarán solo los primeros {limite}."
                )
        else:
            logger.warning(f"⚠️ No se pudo consultar créditos disponibles en CoreSoft ({etiqueta}); se continúa igual")

        pausa_seg = 60.0 / CORESOFT_CONSULTAS_POR_MINUTO + 0.2  # margen de seguridad bajo el límite/min

        for i, empleado in enumerate(empleados[:limite]):
            try:
                resultado = consultar_eps(empleado.cedula)
                resumen["verificados"] += 1

                if resultado is None:
                    resumen["fallidos"] += 1
                elif resultado.get("afiliado") and resultado.get("eps"):
                    if _aplicar_resultado(empleado, resultado):
                        resumen["actualizados"] += 1
                    else:
                        resumen["sin_cambio"] += 1
                else:
                    resumen["sin_cambio"] += 1
            except Exception as e:
                resumen["fallidos"] += 1
                logger.warning(f"⚠️ Error verificando EPS de {empleado.cedula}: {e}")

            if (i + 1) % 25 == 0:
                db.commit()
            if i < limite - 1:
                time.sleep(pausa_seg)

        db.commit()

        sin_verificar = total - limite
        logger.info(
            f"✅ Verificación de EPS completada ({etiqueta}): {limite}/{total} verificados "
            f"({resumen['actualizados']} actualizados, {resumen['sin_cambio']} sin cambio, {resumen['fallidos']} fallidos)"
            + (f" — {sin_verificar} sin verificar por créditos insuficientes" if sin_verificar > 0 else "")
        )
        return resumen
    except Exception as e:
        logger.error(f"❌ Error en verificar_eps_empleados ({etiqueta}): {e}")
        return resumen
    finally:
        db.close()


def primer_barrido_empresa(company_id: int) -> dict:
    """
    Primer barrido de EPS al activar una empresa nueva (onboarding completo o
    conversión de demo → cliente real). Se llama vía BackgroundTasks para no
    bloquear la respuesta del endpoint de activación.

    Antes de verificar, intenta sincronizar los empleados desde su Google
    Sheet (si ya está configurado) para no depender de esperar hasta 30 min
    al cron periódico de sync — así el primer barrido sí tiene empleados que
    revisar apenas la empresa queda activa. Fail-safe: si el sync de Excel
    falla, igual corre la verificación con lo que ya exista en BD.
    """
    try:
        from app.database import SessionLocal as _SessionLocal, TenantConfig
        db = _SessionLocal()
        try:
            config = db.query(TenantConfig).filter(TenantConfig.company_id == company_id).first()
            sheet_id = config.google_sheets_id if config else None
        finally:
            db.close()

        if sheet_id:
            try:
                from app.sync_excel import sincronizar_excel_completo
                logger.info(f"🔄 Primer barrido: sincronizando empleados desde Excel (company_id={company_id})...")
                sincronizar_excel_completo(sheet_id=sheet_id, company_id=company_id)
            except Exception as e:
                logger.warning(f"⚠️ Primer barrido: sync de Excel falló (company_id={company_id}): {e}")
        else:
            logger.info(
                f"ℹ️ Primer barrido (company_id={company_id}): sin Google Sheet configurado todavía, "
                f"se usa lo que ya exista en BD"
            )
    except Exception as e:
        logger.warning(f"⚠️ Primer barrido: error preparando sync de empleados (company_id={company_id}): {e}")

    logger.info(f"🔄 Primer barrido de EPS — company_id={company_id}")
    return verificar_eps_empleados(company_id=company_id)
