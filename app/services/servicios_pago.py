# -*- coding: utf-8 -*-
"""
✅ Centro de Costos — inventario centralizado de servicios/APIs pagos y sus alertas.

NO consolida el pago real: cada proveedor (Google, Anthropic, Mistral, Meta,
Railway, CoreSoft...) sigue cobrando por su lado a la tarjeta configurada ahí.
Lo que centraliza este módulo es la VISIBILIDAD — un solo lugar con todos los
servicios, su costo, cuándo cobran, y alertas antes de que algo se venza, se
agote (créditos de una API medida) o suba de precio.

Se usa en dos momentos:
  1. Seed inicial (una sola vez, al arrancar) — precarga el inventario con los
     servicios ya detectados en el código (llaves de API presentes en env),
     para que no se quede ninguno por fuera. Costo/fecha quedan en blanco:
     eso solo lo sabe Sebastián.
  2. Tarea diaria (app/tasks/scheduler_tasks.py) — revisa cada servicio activo
     y envía alerta (correo + WhatsApp si ya está conectado) cuando:
       - Faltan <= umbral_alerta_dias para el próximo cobro.
       - Ya pasó la fecha de cobro y nadie la marcó como pagada (riesgo de
         suspensión).
       - Para servicios con tipo_verificacion soportado (hoy: CoreSoft), el
         crédito restante cae bajo umbral_alerta_credito_pct.

Fail-safe: un error en un servicio puntual (o en el envío de una alerta) no
detiene la revisión de los demás.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from app.database import SessionLocal, ServicioPago, ServicioPagoHistorial, ServicioPagoAlertaLog

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# SEED — servicios detectados en el código (llaves de API en variables de
# entorno) al momento de construir este módulo (2026-09-20). Si se agrega una
# integración nueva más adelante, agregarla aquí también para que el panel
# nunca se quede desactualizado.
# ─────────────────────────────────────────────────────────────────────────────

SEED_SERVICIOS = [
    {"nombre": "Google Workspace", "proveedor": "Google", "categoria": "comunicaciones",
     "notas": "Correo (Gmail), Drive y Sheets — base de todo el flujo de soportes."},
    {"nombre": "Anthropic Claude API", "proveedor": "Anthropic", "categoria": "desarrollo",
     "notas": "NO es para los bots del portal (eso lo hace Browserbase) — es el costo de Claude Code/API "
              "usado para el desarrollo de la plataforma. Gasto aparte, no operativo."},
    {"nombre": "Google Gemini API", "proveedor": "Google", "categoria": "ia",
     "notas": "Calificación IA, embeddings y generación de plano de incapacidades. Se paga aparte del Workspace."},
    {"nombre": "GLM (Zhipu AI)", "proveedor": "Zhipu AI", "categoria": "ia", "notas": ""},
    {"nombre": "Mistral OCR", "proveedor": "Mistral AI", "categoria": "ia",
     "notas": "OCR de soportes de incapacidad."},
    {"nombre": "Replicate", "proveedor": "Replicate", "categoria": "ia",
     "notas": "Modelo de upscaling HD (UltraSharp) del editor de PDF."},
    {"nombre": "Browserbase", "proveedor": "Browserbase", "categoria": "infraestructura",
     "tipo_verificacion": "browserbase_uso",
     "notas": "Radicación automática en portales EPS/ARL. Conectado recientemente."},
    {"nombre": "CoreSoft (ADRES/BDUA)", "proveedor": "CoreSoft Solutions", "categoria": "otros",
     "tipo_verificacion": "coresoft_creditos",
     "notas": "Verificación mensual de EPS. Plan Freelance, 500 créditos/mes."},
    {"nombre": "ICD API (CIE-10/11)", "proveedor": "WHO", "categoria": "otros",
     "notas": "Gratis — no se paga, confirmado. Se deja listado solo como referencia, sin seguimiento de costo."},
    {"nombre": "Railway", "proveedor": "Railway", "categoria": "infraestructura",
     "tipo_verificacion": "railway_uso",
     "notas": "Hosting del backend (FastAPI) y la base de datos."},
    {"nombre": "WhatsApp Business API", "proveedor": "Meta", "categoria": "comunicaciones",
     "estado": "pendiente", "notas": "Próximo a contratar."},
    {"nombre": "OneDrive", "proveedor": "Microsoft", "categoria": "almacenamiento",
     "estado": "pendiente", "notas": "Próximo a integrar como proveedor de storage alterno."},
    {"nombre": "Cloudflare Turnstile", "proveedor": "Cloudflare", "categoria": "otros",
     "notas": "Gratis — no se paga, confirmado (se usa junto con Browserbase). Se deja listado solo como referencia."},
]


def seed_servicios_pago_iniciales():
    """
    Precarga el inventario con los servicios detectados en el código, SOLO si
    todavía no existen (por nombre). Nunca sobrescribe un servicio que el
    usuario ya haya editado. Seguro de re-ejecutar en cada deploy.
    """
    db = SessionLocal()
    try:
        existentes = {n for (n,) in db.query(ServicioPago.nombre).all()}
        nuevos = 0
        for s in SEED_SERVICIOS:
            if s["nombre"] in existentes:
                continue
            db.add(ServicioPago(
                nombre=s["nombre"],
                proveedor=s.get("proveedor"),
                categoria=s.get("categoria", "otros"),
                tipo_verificacion=s.get("tipo_verificacion", "ninguna"),
                estado=s.get("estado", "activo"),
                notas=s.get("notas") or None,
            ))
            nuevos += 1
        if nuevos:
            db.commit()
            logger.info(f"✅ Centro de costos: {nuevos} servicio(s) precargado(s) en servicios_pago")
        else:
            logger.info("ℹ️ Centro de costos: servicios_pago ya tiene datos, no se precarga nada nuevo")
    except Exception as e:
        logger.error(f"❌ Error precargando servicios_pago: {e}")
    finally:
        db.close()


def registrar_historial_si_cambio(db, servicio: ServicioPago, campo: str, valor_anterior, valor_nuevo):
    """Guarda en servicios_pago_historial cuando costo_mensual o estado cambian de verdad."""
    if valor_anterior == valor_nuevo:
        return
    if valor_anterior is None and valor_nuevo is None:
        return
    db.add(ServicioPagoHistorial(
        servicio_id=servicio.id,
        campo=campo,
        valor_anterior=str(valor_anterior) if valor_anterior is not None else None,
        valor_nuevo=str(valor_nuevo) if valor_nuevo is not None else None,
    ))


def _ya_alertado(db, servicio_id: int, tipo: str, referencia_ciclo: str) -> bool:
    return db.query(ServicioPagoAlertaLog).filter(
        ServicioPagoAlertaLog.servicio_id == servicio_id,
        ServicioPagoAlertaLog.tipo == tipo,
        ServicioPagoAlertaLog.referencia_ciclo == referencia_ciclo,
    ).first() is not None


def _enviar_alerta(servicio: ServicioPago, asunto: str, cuerpo: str):
    """Envía por correo y, si ya hay WhatsApp Business conectado, también por WhatsApp. Fail-safe."""
    try:
        from app.email_service import enviar_email_simple
        destinatarios = (servicio.email_alertas or "gestiondeincapacidades@incapacidade.com").split(",")
        for correo in destinatarios:
            correo = correo.strip()
            if correo:
                enviar_email_simple(correo, asunto, cuerpo)
    except Exception as e:
        logger.warning(f"⚠️ No se pudo enviar alerta por correo de '{servicio.nombre}': {e}")

    if servicio.whatsapp_alertas:
        try:
            from app.email_service import _enviar_whatsapp
            _enviar_whatsapp(servicio.whatsapp_alertas, f"{asunto}\n\n{cuerpo}")
        except Exception as e:
            logger.warning(f"⚠️ No se pudo enviar alerta por WhatsApp de '{servicio.nombre}': {e}")


def _saldo_restante_pct(servicio: ServicioPago) -> Optional[float]:
    """
    Consulta el % de crédito/saldo restante para servicios con verificación
    programática soportada. Devuelve None si no aplica o si falla (fail-safe).
    Hoy solo CoreSoft está implementado — Browserbase/Railway no exponen un
    endpoint de saldo en la integración actual, se dejan preparados para el
    día que lo tengan.
    """
    if servicio.tipo_verificacion == "coresoft_creditos":
        try:
            from app.coresoft_client import consultar_creditos
            info = consultar_creditos()
            if not info:
                return None
            disponibles = info.get("disponibles")
            total = info.get("total") or info.get("plan_total")
            if disponibles is None or not total:
                return None
            return round(disponibles / total * 100, 1)
        except Exception as e:
            logger.warning(f"⚠️ No se pudo consultar crédito de CoreSoft: {e}")
            return None
    return None


def verificar_alertas_servicios():
    """
    Tarea diaria: revisa todos los servicios activos y dispara alertas de
    renovación próxima, cobro vencido sin confirmar, y crédito bajo (para los
    que sí tienen verificación programática). Nunca lanza excepción.
    """
    db = SessionLocal()
    hoy = date.today()
    ciclo = hoy.strftime("%Y-%m")
    resumen = {"revisados": 0, "alertas_enviadas": 0}

    try:
        servicios = db.query(ServicioPago).filter(
            ServicioPago.activo == True,  # noqa: E712
            ServicioPago.estado.in_(["activo", "en_riesgo"]),
        ).all()
        resumen["revisados"] = len(servicios)

        for s in servicios:
            try:
                # 1) Renovación próxima / vencida
                if s.fecha_proximo_cobro:
                    dias_restantes = (s.fecha_proximo_cobro - hoy).days
                    if 0 <= dias_restantes <= (s.umbral_alerta_dias or 5):
                        if not _ya_alertado(db, s.id, "renovacion_proxima", ciclo):
                            _enviar_alerta(
                                s,
                                f"💳 {s.nombre} se cobra en {dias_restantes} día(s)",
                                f"'{s.nombre}' ({s.proveedor or '—'}) tiene su próximo cobro el "
                                f"{s.fecha_proximo_cobro.strftime('%d/%m/%Y')}"
                                + (f" por {s.costo_mensual} {s.moneda}" if s.costo_mensual else "")
                                + ". Verifica que la tarjeta tenga fondos/esté vigente.",
                            )
                            db.add(ServicioPagoAlertaLog(servicio_id=s.id, tipo="renovacion_proxima", referencia_ciclo=ciclo))
                            resumen["alertas_enviadas"] += 1
                    elif dias_restantes < 0:
                        if not _ya_alertado(db, s.id, "vencido", ciclo):
                            _enviar_alerta(
                                s,
                                f"⚠️ {s.nombre} — fecha de cobro ya pasó sin confirmar",
                                f"'{s.nombre}' tenía fecha de cobro el {s.fecha_proximo_cobro.strftime('%d/%m/%Y')} "
                                f"y sigue como pendiente de confirmar. Si la tarjeta rechazó el cobro, "
                                f"el servicio puede suspenderse pronto.",
                            )
                            db.add(ServicioPagoAlertaLog(servicio_id=s.id, tipo="vencido", referencia_ciclo=ciclo))
                            resumen["alertas_enviadas"] += 1

                # 2) Crédito bajo (servicios medidos)
                pct = _saldo_restante_pct(s)
                if pct is not None and pct <= (s.umbral_alerta_credito_pct or 15):
                    if not _ya_alertado(db, s.id, "credito_bajo", ciclo):
                        _enviar_alerta(
                            s,
                            f"🔋 {s.nombre} — solo queda {pct}% de crédito",
                            f"'{s.nombre}' tiene apenas {pct}% del crédito/cupo disponible este mes. "
                            f"Revisa si necesitas ampliar el plan antes de que se agote.",
                        )
                        db.add(ServicioPagoAlertaLog(servicio_id=s.id, tipo="credito_bajo", referencia_ciclo=ciclo))
                        resumen["alertas_enviadas"] += 1

            except Exception as e:
                logger.warning(f"⚠️ Error revisando servicio '{s.nombre}': {e}")

        db.commit()
        logger.info(
            f"✅ Centro de costos: {resumen['revisados']} servicio(s) revisado(s), "
            f"{resumen['alertas_enviadas']} alerta(s) enviada(s)"
        )
        return resumen
    except Exception as e:
        logger.error(f"❌ Error en verificar_alertas_servicios: {e}")
        return resumen
    finally:
        db.close()
