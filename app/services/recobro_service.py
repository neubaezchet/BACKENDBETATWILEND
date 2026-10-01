"""
RECOBRO — cruce de lo que radicamos contra lo que la EPS pagó.
==============================================================

Radicar es media tarea; la otra media es cobrar. Este servicio baja los
reportes del portal de la EPS, los acumula en `recobro_filas` y los cruza
contra `radicacion_cola` para responder la única pregunta que importa:
¿qué incapacidad ya radicada NO nos han pagado, y por qué?

Diseño (y el porqué de cada decisión):

1. **El bot baja el archivo; el backend lo parsea.** El agente solo navega y
   hace clic en "Generar archivo". Las cifras salen del Excel real, no de lo
   que un modelo alcanzó a leer en pantalla: un dígito alucinado en un recobro
   es plata perdida y nadie lo notaría.

2. **Se acumula, no se re-descarga.** Cada rango bajado queda en la BD para
   siempre. El histórico de una persona, de la empresa o de tres años atrás se
   responde con un SELECT, gratis. Solo se vuelve al portal por lo nuevo.
   El bot escribe una vez; la base responde infinitas veces.

3. **Ingesta idempotente.** La fila se identifica por su clave natural en el
   portal, con índice único en BD. Rangos que se solapan, un reintento, dos
   ciclos simultáneos: actualizan la fila, nunca la duplican. Por eso el
   incremental puede pedir días de más sin miedo — y debe hacerlo, porque las
   EPS cambian el estado de una incapacidad semanas después de radicada.

4. **Nada rompe el flujo principal.** Todo el ciclo va envuelto: si el portal
   cambia, si el archivo llega corrupto o si Browserbase falla, se registra el
   error en `recobro_sync` y la radicación diaria sigue intacta.
"""

import csv
import io
import json
import logging
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.database import (
    Case, CaseEvent, EmpresaBotConfig, EstadoCaso, RadicacionCola, RadicacionSkill,
    RecobroFila, RecobroSync, SessionLocal,
)
from app.services import browserbase_service as bb
from app.services.browserbase_service import BrowserbaseError
from app.services.motivos import clasificar_negacion

logger = logging.getLogger(__name__)

ORIGENES = ("radicadas", "pagadas")

# Días que se vuelven a pedir por detrás de lo ya cubierto. Una incapacidad
# radicada hoy puede aparecer como "pagada" dentro de 45 días: si solo
# pidiéramos lo nuevo, ese cambio de estado no se vería nunca.
DIAS_SOLAPE = 45

# Tope por consulta. Los portales rechazan rangos enormes y un archivo gigante
# es más frágil que tres pequeños.
MAX_DIAS_RANGO = 90


# ══════════════════════════════════════════════════════════════
#  Normalización de datos del portal
# ══════════════════════════════════════════════════════════════

def _norm(texto: Any) -> str:
    """minúsculas, sin tildes, sin signos — para comparar encabezados."""
    s = str(texto or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


# Encabezado del portal (normalizado) → campo nuestro. Las EPS renombran
# columnas sin avisar, por eso se aceptan varios alias por campo y la fila
# cruda se guarda completa en datos_crudos.
ALIAS_COLUMNAS: Dict[str, Tuple[str, ...]] = {
    "radicado": ("radicado", "numero_radicado", "nro_radicado", "no_radicado",
                 "numero_de_radicado", "radicacion"),
    "numero_incapacidad": ("numero_incapacidad", "nro_incapacidad", "no_incapacidad",
                           "numero_de_incapacidad", "incapacidad", "certificado"),
    "cedula": ("cedula", "documento", "numero_documento", "identificacion",
               "nro_documento", "documento_trabajador", "identificacion_trabajador"),
    "nombre_trabajador": ("nombre", "nombres", "trabajador", "nombre_trabajador",
                          "nombre_completo", "afiliado", "nombre_afiliado"),
    "fecha_inicio": ("fecha_inicio", "fecha_inicial", "fecha_de_inicio",
                     "fecha_inicio_incapacidad", "desde", "fecha_desde"),
    "fecha_fin": ("fecha_fin", "fecha_final", "fecha_de_fin",
                  "fecha_fin_incapacidad", "hasta", "fecha_hasta"),
    "dias": ("dias", "dias_incapacidad", "numero_dias", "total_dias", "cantidad_dias"),
    "diagnostico": ("diagnostico", "cie10", "codigo_diagnostico", "descripcion_diagnostico"),
    "motivo": ("motivo", "tipo_incapacidad", "motivo_incapacidad", "clase_incapacidad",
               "origen_incapacidad", "tipo"),
    "estado_portal": ("estado", "estado_incapacidad", "estado_solicitud", "situacion"),
    "motivo_rechazo": ("motivo_rechazo", "causal_rechazo", "observacion", "observaciones",
                       "motivo_devolucion", "causal_devolucion", "novedad"),
    "valor_reconocido": ("valor_reconocido", "valor_liquidado", "valor_a_pagar",
                         "valor_incapacidad", "valor"),
    "valor_pagado": ("valor_pagado", "valor_girado", "total_pagado", "pagado"),
    "fecha_pago": ("fecha_pago", "fecha_de_pago", "fecha_giro", "fecha_desembolso"),
}

_MAPA_ENCABEZADOS = {
    alias: campo for campo, aliases in ALIAS_COLUMNAS.items() for alias in aliases
}


def _mapear_encabezados(encabezados: List[Any]) -> Dict[int, str]:
    """Índice de columna → campo nuestro. Las que no reconocemos se ignoran
    aquí pero igual quedan en datos_crudos."""
    mapa = {}
    for i, h in enumerate(encabezados):
        campo = _MAPA_ENCABEZADOS.get(_norm(h))
        if campo and campo not in mapa.values():
            mapa[i] = campo
    return mapa


def _a_fecha(valor: Any) -> Optional[date]:
    """Fecha desde lo que sea que traiga el portal, sin reventar."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    s = str(valor).strip()[:19]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d",
                "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _a_numero(valor: Any) -> Optional[float]:
    """
    Dinero colombiano → float. Devuelve None si no es número.

    Lo delicado es el punto: en Colombia "$ 300.000" son trescientos mil, no
    trescientos. La regla es mirar el último grupo: si tiene exactamente 3
    dígitos el separador es de miles; si tiene 1 o 2, es decimal. Leer mal
    esto no revienta nada — simplemente el recobro reclama tres órdenes de
    magnitud menos de lo que la EPS debe.
    """
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    s = re.sub(r"[^\d,.\-]", "", str(valor))
    if not s:
        return None

    if "," in s and "." in s:
        # El separador decimal es el que aparece de último
        s = (s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".")
             else s.replace(",", ""))
    elif "," in s:
        s = s.replace(",", ".") if len(s.rsplit(",", 1)[-1]) <= 2 else s.replace(",", "")
    elif "." in s:
        # "300.000" → miles | "120450.50" → decimal | "1.234.567" → miles
        if s.count(".") > 1 or len(s.rsplit(".", 1)[-1]) == 3:
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def _a_entero(valor: Any) -> Optional[int]:
    n = _a_numero(valor)
    return int(n) if n is not None else None


def _solo_digitos(valor: Any) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def _clave_natural(fila: Dict[str, Any]) -> str:
    """
    Identidad de la fila dentro del portal, para la ingesta idempotente.

    Preferimos el radicado (lo asigna la EPS y no cambia). Si el reporte no lo
    trae, caemos a número de incapacidad, y si tampoco, a cédula+fechas: una
    misma persona no puede tener dos incapacidades que empiecen y terminen el
    mismo día, así que sigue identificando la fila sin duplicarla.
    """
    if fila.get("radicado"):
        return f"rad:{str(fila['radicado']).strip()}"
    if fila.get("numero_incapacidad"):
        return f"inc:{str(fila['numero_incapacidad']).strip()}"
    partes = [
        _solo_digitos(fila.get("cedula")),
        fila["fecha_inicio"].isoformat() if fila.get("fecha_inicio") else "",
        fila["fecha_fin"].isoformat() if fila.get("fecha_fin") else "",
    ]
    return "cf:" + "|".join(partes)


# ══════════════════════════════════════════════════════════════
#  Parseo del archivo descargado
# ══════════════════════════════════════════════════════════════

def parsear_archivo(contenido: bytes, nombre_archivo: str = "") -> List[Dict[str, Any]]:
    """
    Excel o CSV del portal → lista de filas normalizadas.

    Se usa openpyxl en crudo y NO pandas a propósito: pandas convierte las
    cédulas a float y '1010234567' termina siendo '1.010234567e9'. Aquí el
    texto se queda como texto.
    """
    nombre = (nombre_archivo or "").lower()
    if nombre.endswith((".csv", ".txt")) or (not nombre.endswith((".xlsx", ".xlsm", ".xls"))
                                             and not contenido[:2] == b"PK"):
        matriz = _leer_csv(contenido)
    else:
        matriz = _leer_xlsx(contenido)

    if not matriz:
        return []

    # El encabezado no siempre es la fila 1: los portales meten título y logo
    # arriba. Buscamos la primera fila que mapee al menos 3 columnas conocidas.
    idx_encabezado, mapa = -1, {}
    for i, fila in enumerate(matriz[:15]):
        candidato = _mapear_encabezados(fila)
        if len(candidato) >= 3:
            idx_encabezado, mapa = i, candidato
            break
    if idx_encabezado < 0:
        raise ValueError(
            "No se reconocieron las columnas del reporte. Encabezados vistos: "
            f"{[str(c)[:30] for c in (matriz[0] if matriz else [])][:12]}"
        )

    encabezados = [str(c or f"col_{j}") for j, c in enumerate(matriz[idx_encabezado])]
    filas: List[Dict[str, Any]] = []

    for cruda in matriz[idx_encabezado + 1:]:
        if not any(str(c or "").strip() for c in cruda):
            continue  # fila vacía o separador
        registro: Dict[str, Any] = {}
        for i, campo in mapa.items():
            registro[campo] = cruda[i] if i < len(cruda) else None

        registro["cedula"] = _solo_digitos(registro.get("cedula")) or None
        registro["fecha_inicio"] = _a_fecha(registro.get("fecha_inicio"))
        registro["fecha_fin"] = _a_fecha(registro.get("fecha_fin"))
        registro["fecha_pago"] = _a_fecha(registro.get("fecha_pago"))
        registro["dias"] = _a_entero(registro.get("dias"))
        registro["valor_reconocido"] = _a_numero(registro.get("valor_reconocido"))
        registro["valor_pagado"] = _a_numero(registro.get("valor_pagado"))
        for texto in ("radicado", "numero_incapacidad", "nombre_trabajador",
                      "diagnostico", "motivo", "estado_portal", "motivo_rechazo"):
            v = registro.get(texto)
            registro[texto] = str(v).strip()[:300] if v not in (None, "") else None

        # Sin ninguna forma de identificarla, la fila es basura (totales, pie de página)
        if not (registro.get("radicado") or registro.get("numero_incapacidad")
                or registro.get("cedula")):
            continue

        registro["_crudos"] = {
            h: (v.isoformat() if isinstance(v, (date, datetime)) else v)
            for h, v in zip(encabezados, cruda)
        }
        filas.append(registro)

    return filas


def _leer_xlsx(contenido: bytes) -> List[List[Any]]:
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    hoja = wb.active
    matriz = [list(fila) for fila in hoja.iter_rows(values_only=True)]
    wb.close()
    return matriz


def _leer_csv(contenido: bytes) -> List[List[Any]]:
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            texto = contenido.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        texto = contenido.decode("utf-8", errors="replace")
    muestra = texto[:4096]
    try:
        dialecto = csv.Sniffer().sniff(muestra, delimiters=";,|\t")
        delim = dialecto.delimiter
    except csv.Error:
        delim = ";" if muestra.count(";") > muestra.count(",") else ","
    return [fila for fila in csv.reader(io.StringIO(texto), delimiter=delim)]


# ══════════════════════════════════════════════════════════════
#  Ingesta idempotente
# ══════════════════════════════════════════════════════════════

CAMPOS_FILA = (
    "radicado", "numero_incapacidad", "cedula", "nombre_trabajador",
    "fecha_inicio", "fecha_fin", "dias", "diagnostico", "motivo",
    "estado_portal", "motivo_rechazo", "valor_reconocido", "valor_pagado",
    "fecha_pago",
)


def ingestar_filas(db: Session, empresa: str, eps_key: str, origen: str,
                   filas: List[Dict[str, Any]],
                   desde: Optional[date] = None,
                   hasta: Optional[date] = None) -> Dict[str, int]:
    """
    Inserta o actualiza las filas del reporte. Seguro de re-ejecutar: la misma
    descarga dos veces deja exactamente el mismo resultado.

    Un campo que el reporte nuevo trae vacío NO borra el valor guardado: el
    reporte de "pagadas" no repite el diagnóstico, y perderlo obligaría a
    volver a bajar el otro reporte.
    """
    nuevas = actualizadas = 0

    for fila in filas:
        clave = _clave_natural(fila)
        registro = db.query(RecobroFila).filter(
            RecobroFila.empresa == empresa,
            RecobroFila.eps_key == eps_key,
            RecobroFila.origen == origen,
            RecobroFila.clave_natural == clave,
        ).first()

        if not registro:
            registro = RecobroFila(
                empresa=empresa, eps_key=eps_key, origen=origen, clave_natural=clave,
            )
            db.add(registro)
            nuevas += 1
        else:
            actualizadas += 1

        for campo in CAMPOS_FILA:
            valor = fila.get(campo)
            if valor not in (None, ""):
                setattr(registro, campo, valor)

        crudos = dict(registro.datos_crudos or {})
        crudos.update(fila.get("_crudos") or {})
        registro.datos_crudos = crudos

        # El periodo se ensancha, no se reemplaza: la fila puede aparecer en
        # varios reportes y queremos saber el rango completo en que se la vio.
        if desde:
            registro.periodo_desde = min(registro.periodo_desde or desde, desde)
        if hasta:
            registro.periodo_hasta = max(registro.periodo_hasta or hasta, hasta)

        registro.actualizado_en = datetime.utcnow()

    db.flush()
    _enlazar_con_cola(db, empresa, eps_key, filas)
    # SessionLocal va con autoflush=False: sin este flush el SELECT de abajo no
    # vería los case_id que _enlazar_con_cola acaba de asignar y el cierre por
    # pago llegaría un ciclo tarde (un día más de recordatorios a alguien a
    # quien ya le pagaron).
    db.flush()
    cerrados = cerrar_casos_por_pago(db, empresa, eps_key)
    return {
        "nuevas": nuevas, "actualizadas": actualizadas, "total": len(filas),
        "casos_cerrados_por_pago": cerrados,
    }


# ══════════════════════════════════════════════════════════════
#  El pago de la EPS cierra el ciclo de recordatorios
# ══════════════════════════════════════════════════════════════

# Estados en los que todavía se le está pidiendo documentos al colaborador.
_ESTADOS_PIDIENDO = (
    EstadoCaso.INCOMPLETA, EstadoCaso.ILEGIBLE, EstadoCaso.INCOMPLETA_ILEGIBLE,
)

_PALABRAS_PAGO = ("pagad", "reconocid", "girad", "abonad", "liquidad", "aprobad")


def _es_pago(registro: RecobroFila) -> bool:
    """
    ¿La EPS reconoció y pagó esta incapacidad?

    Se exige evidencia positiva: plata, fecha de giro o un estado que lo diga.
    Aparecer en el reporte de "pagadas" no basta por sí solo — decirle a un
    trabajador "su soporte fue reconocido" y tener que retractarse después es
    peor que esperar un ciclo más.
    """
    if _es_rechazo(registro.estado_portal):
        return False
    if (registro.valor_pagado or 0) > 0:
        return True
    if registro.fecha_pago:
        return True
    return any(p in _norm(registro.estado_portal) for p in _PALABRAS_PAGO)


def cerrar_casos_por_pago(db: Session, empresa: str, eps_key: str) -> int:
    """
    Si la EPS ya pagó la incapacidad, se deja de pedirle soportes al colaborador.

    Regla de negocio: el objetivo del ciclo de recordatorios es completar los
    soportes para que la EPS pague. Si la EPS pagó —aun faltando un mínimo, aun
    habiendo entrado al portal incompleta— el objetivo ya se cumplió y seguir
    insistiéndole al trabajador es hostigarlo por algo que ya no hace falta.
    El caso sale de incompletas y se le avisa que su soporte fue reconocido.

    Si la EPS NO pagó o rechazó, esta función no toca nada: el ciclo de
    recordatorios sigue su curso hasta que complete, se retire o entre en causa.

    Devuelve cuántos casos se cerraron. Fail-safe: un caso que falle no detiene
    a los demás ni rompe la ingesta.
    """
    filas_pagas = db.query(RecobroFila).filter(
        RecobroFila.empresa == empresa,
        RecobroFila.eps_key == eps_key,
        RecobroFila.case_id.isnot(None),
    ).all()

    cerrados = 0
    for registro in filas_pagas:
        try:
            if not _es_pago(registro):
                continue

            caso = db.query(Case).filter(Case.id == registro.case_id).first()
            if not caso or caso.pago_eps_reconocido:
                continue

            estaba_pidiendo = caso.estado in _ESTADOS_PIDIENDO
            estado_antes = caso.estado.value if caso.estado else None

            caso.pago_eps_reconocido = True
            # La columna es TIMESTAMP y fecha_pago es date: se normaliza aquí para
            # no dejar que el driver decida.
            caso.pago_eps_en = (
                datetime.combine(registro.fecha_pago, datetime.min.time())
                if registro.fecha_pago else datetime.utcnow()
            )
            caso.pago_eps_valor = registro.valor_pagado
            caso.pago_eps_radicado = registro.radicado

            if estaba_pidiendo:
                # Sale de incompletas y se apaga el contador: si mañana alguien
                # lo vuelve a marcar incompleto, el scheduler igual lo salta por
                # pago_eps_reconocido (ver scheduler_recordatorios).
                caso.estado = EstadoCaso.COMPLETA
                caso.bloquea_nueva = False
                caso.recordatorio_enviado = False
                caso.recordatorios_count = 0

            db.add(CaseEvent(
                case_id=caso.id,
                accion="pago_eps_reconocido",
                actor="sistema/recobro",
                estado_anterior=(estado_antes if estaba_pidiendo else None),
                estado_nuevo=(EstadoCaso.COMPLETA.value if estaba_pidiendo else None),
                motivo=(
                    f"La EPS {eps_key} reconoció el pago"
                    + (f" (radicado {registro.radicado})" if registro.radicado else "")
                    + (f" por ${registro.valor_pagado:,.0f}" if registro.valor_pagado else "")
                ),
                metadata_json={
                    "origen_reporte": registro.origen,
                    "recobro_fila_id": registro.id,
                    "valor_pagado": registro.valor_pagado,
                    "fecha_pago": registro.fecha_pago.isoformat() if registro.fecha_pago else None,
                    "cerro_recordatorios": estaba_pidiendo,
                },
            ))
            db.flush()
            cerrados += 1

            if estaba_pidiendo:
                _avisar_pago_reconocido(caso, eps_key, registro)

        except Exception as e:
            logger.warning(
                f"[Recobro] No se pudo cerrar por pago el caso {registro.case_id}: {e}"
            )

    return cerrados


def _avisar_pago_reconocido(caso, eps_key: str, registro: RecobroFila) -> None:
    """
    Le avisa al colaborador que su soporte ya fue reconocido por la EPS, en vez
    de dejarlo con el último correo que recibió, que era un recordatorio.
    Fail-safe: si la notificación falla, el caso igual queda cerrado.
    """
    try:
        destino = caso.email_form or (caso.empleado.correo if caso.empleado else None)
        if not destino:
            return

        from app.notification_queue import notification_queue

        nombre = caso.empleado.nombre if caso.empleado else "Colaborador"
        empresa_nombre = caso.empresa.nombre if caso.empresa else ""
        valor = f" por ${registro.valor_pagado:,.0f}" if registro.valor_pagado else ""

        notification_queue.encolar_notificacion_estado(
            serial=caso.serial,
            tipo="pago_eps",
            email=destino,
            nombre_empleado=nombre,
            empresa=empresa_nombre,
            tipo_incapacidad=(caso.tipo.value if caso.tipo else ""),
            telefono=caso.telefono_form or "",
            drive_link=caso.drive_link or "",
            subject=f"Su incapacidad {caso.serial} fue reconocida por la EPS",
            template="completa",
            motivo=(
                f"Buenas noticias: la EPS {eps_key} reconoció y pagó su incapacidad"
                f"{valor}. No necesitamos que envíe más documentos para este caso."
            ),
        )
    except Exception as e:
        logger.warning(f"[Recobro] Aviso de pago no enviado para {caso.serial}: {e}")


def _enlazar_con_cola(db: Session, empresa: str, eps_key: str, filas: List[Dict[str, Any]]):
    """
    Amarra cada fila del portal con el ítem de cola que la originó.

    Se enlaza por radicado (exacto) y, si no hay, por cédula + fecha de inicio.
    Fail-safe: si no encuentra pareja, la fila queda sin enlazar y el cruce la
    reporta como "la EPS la tiene pero nosotros no" — que es justamente una de
    las cosas que hay que vigilar, no un error.
    """
    radicados = [f["radicado"] for f in filas if f.get("radicado")]
    if not radicados:
        return

    por_radicado = {
        (item.radicado or "").strip(): item
        for item in db.query(RadicacionCola).filter(
            RadicacionCola.empresa == empresa,
            RadicacionCola.eps_key == eps_key,
            RadicacionCola.radicado.in_(radicados[:500]),
        ).all()
    }
    if not por_radicado:
        return

    for fila in filas:
        item = por_radicado.get(str(fila.get("radicado") or "").strip())
        if not item:
            continue
        registro = db.query(RecobroFila).filter(
            RecobroFila.empresa == empresa,
            RecobroFila.eps_key == eps_key,
            RecobroFila.clave_natural == _clave_natural(fila),
        ).first()
        if registro and not registro.cola_id:
            registro.cola_id = item.id
            registro.case_id = item.case_id


# ══════════════════════════════════════════════════════════════
#  Estado de sincronización / rango incremental
# ══════════════════════════════════════════════════════════════

def _obtener_sync(db: Session, empresa: str, eps_key: str, origen: str) -> RecobroSync:
    sync = db.query(RecobroSync).filter(
        RecobroSync.empresa == empresa,
        RecobroSync.eps_key == eps_key,
        RecobroSync.origen == origen,
    ).first()
    if not sync:
        sync = RecobroSync(empresa=empresa, eps_key=eps_key, origen=origen)
        db.add(sync)
        db.flush()
    return sync


def rango_incremental(db: Session, empresa: str, eps_key: str, origen: str,
                      hasta: Optional[date] = None) -> Tuple[date, date]:
    """
    Qué rango pedirle al portal en el próximo run.

    Primera vez: los últimos 90 días (arrancar por 3 años de golpe es un
    archivo enorme y un run que se cae; el histórico viejo se llena después,
    rango por rango, con `recuperar_historico`).
    Después: desde lo ya cubierto menos el solape, hasta hoy. El solape es lo
    que hace que los cambios de estado tardíos entren solos.
    """
    hasta = hasta or date.today()
    sync = _obtener_sync(db, empresa, eps_key, origen)

    if not sync.cubierto_hasta:
        desde = hasta - timedelta(days=MAX_DIAS_RANGO)
    else:
        desde = sync.cubierto_hasta - timedelta(days=DIAS_SOLAPE)

    if (hasta - desde).days > MAX_DIAS_RANGO:
        desde = hasta - timedelta(days=MAX_DIAS_RANGO)
    if desde > hasta:
        desde = hasta
    return desde, hasta


# ══════════════════════════════════════════════════════════════
#  Lanzar el run de reportes
# ══════════════════════════════════════════════════════════════

def _bot_de(db: Session, empresa: str, eps_key: str) -> Optional[EmpresaBotConfig]:
    """Mismo criterio que usa el dispatcher para radicar: si el bot sirve para
    radicar en ese portal, sirve para leer sus reportes (misma credencial)."""
    from app.services.radicacion_dispatcher import _buscar_bot
    return _buscar_bot(db, empresa, eps_key)


async def lanzar_reporte(db: Session, empresa: str, eps_key: str, origen: str,
                         desde: Optional[date] = None,
                         hasta: Optional[date] = None) -> Dict[str, Any]:
    """
    Lanza el run que descarga un reporte. No espera a que termine: el ciclo
    `sincronizar_reportes` recoge el archivo cuando el run finaliza.
    """
    if origen not in ORIGENES:
        raise ValueError(f"origen inválido: {origen}. Use uno de {ORIGENES}")

    skill = db.query(RadicacionSkill).filter(RadicacionSkill.eps_key == eps_key).first()
    if not skill or not skill.agent_id_reportes:
        return {"ok": False, "error": f"'{eps_key}' no tiene agente de reportes registrado "
                                      f"(RadicacionSkill.agent_id_reportes)"}

    bot = _bot_de(db, empresa, eps_key)
    if not bot:
        return {"ok": False, "error": f"'{empresa}' no tiene bot activo para '{eps_key}'"}

    credenciales = bot.credenciales or {}
    usuario = credenciales.get("usuario") or credenciales.get("nit") or ""
    clave = credenciales.get("clave") or credenciales.get("password") or ""
    if not usuario or not clave:
        return {"ok": False, "error": f"Credenciales incompletas para '{empresa}'/'{eps_key}'"}

    if desde is None or hasta is None:
        desde, hasta = rango_incremental(db, empresa, eps_key, origen, hasta)

    sync = _obtener_sync(db, empresa, eps_key, origen)
    if sync.ultimo_estado == "en_curso" and sync.ultimo_run_id:
        # Evita lanzar dos runs del mismo reporte (y pagar dos veces por lo mismo)
        return {"ok": False, "error": "Ya hay un run en curso para este reporte",
                "run_id": sync.ultimo_run_id}

    from app.agentes import AGENTES_REPORTES
    modulo = AGENTES_REPORTES.get(eps_key)
    tarea = getattr(modulo, "TASK", None) or (
        "Descarga el reporte %reporte% de incapacidades para el rango %desde% a %hasta%."
    )
    result_schema = getattr(modulo, "RESULT_SCHEMA", None)

    variables = {
        # Las credenciales viajan como variables del run: nunca dentro del prompt.
        "usuario": {"value": str(usuario), "description": "NIT/usuario de la empresa en el portal"},
        "clave": {"value": str(clave), "description": "Clave del portal"},
        "reporte": {"value": origen, "description": "radicadas | pagadas"},
        "desde": {"value": desde.isoformat(), "description": "Fecha inicial YYYY-MM-DD"},
        "hasta": {"value": hasta.isoformat(), "description": "Fecha final YYYY-MM-DD"},
    }

    browser_settings: Dict[str, Any] = {"proxies": True, "solveCaptchas": True}
    if bot.browserbase_context_id:
        browser_settings["context"] = {"id": bot.browserbase_context_id, "persist": True}

    try:
        run = await bb.create_run(
            task=tarea, agent_id=skill.agent_id_reportes, variables=variables,
            result_schema=result_schema, browser_settings=browser_settings,
        )
    except BrowserbaseError as e:
        sync.ultimo_estado = "error"
        sync.ultimo_error = f"Error lanzando run: {e.detail}"
        db.commit()
        return {"ok": False, "error": sync.ultimo_error}

    sync.ultimo_run_id = run.get("runId")
    sync.ultimo_estado = "en_curso"
    sync.ultimo_error = None
    db.commit()

    logger.info(f"[Recobro] {empresa}/{eps_key}/{origen}: run {sync.ultimo_run_id} "
                f"({desde} → {hasta})")
    return {"ok": True, "run_id": sync.ultimo_run_id, "origen": origen,
            "desde": desde.isoformat(), "hasta": hasta.isoformat()}


# ══════════════════════════════════════════════════════════════
#  Recoger el archivo cuando el run termina
# ══════════════════════════════════════════════════════════════

async def sincronizar_reportes(db: Session) -> Dict[str, Any]:
    """
    Revisa los runs de reportes en curso; cuando terminan, baja el archivo,
    lo parsea y lo ingesta. Cada sync se procesa aislado: un portal que cambió
    no tumba la ingesta de las demás empresas.
    """
    pendientes = db.query(RecobroSync).filter(RecobroSync.ultimo_estado == "en_curso").all()
    procesados, aun_activos, errores = [], 0, []

    for sync in pendientes:
        try:
            resultado = await _procesar_sync(db, sync)
        except Exception as e:  # ninguna falla de una empresa afecta a las otras
            logger.exception(f"[Recobro] {sync.empresa}/{sync.eps_key}/{sync.origen}: {e}")
            sync.ultimo_estado = "error"
            sync.ultimo_error = f"{type(e).__name__}: {e}"[:1000]
            errores.append({"empresa": sync.empresa, "origen": sync.origen, "error": str(e)[:200]})
            continue

        if resultado is None:
            aun_activos += 1
        else:
            procesados.append(resultado)

    db.commit()
    return {"procesados": procesados, "aun_activos": aun_activos, "errores": errores}


async def _procesar_sync(db: Session, sync: RecobroSync) -> Optional[Dict[str, Any]]:
    """Devuelve None si el run sigue corriendo; el resumen si ya se ingestó."""
    if not sync.ultimo_run_id:
        sync.ultimo_estado = "error"
        sync.ultimo_error = "Sync en curso sin run_id"
        return {"empresa": sync.empresa, "origen": sync.origen, "ok": False,
                "error": sync.ultimo_error}

    try:
        run = await bb.get_run(sync.ultimo_run_id)
    except BrowserbaseError as e:
        if e.status_code == 404:
            sync.ultimo_estado = "error"
            sync.ultimo_error = "Run no encontrado en Browserbase"
            return {"empresa": sync.empresa, "origen": sync.origen, "ok": False,
                    "error": sync.ultimo_error}
        return None  # error transitorio: se reintenta en el siguiente ciclo

    estado = run.get("status")
    if estado in ("PENDING", "RUNNING"):
        return None

    resultado = run.get("result") or {}
    if isinstance(resultado.get("summary"), str):
        try:
            resultado = {**resultado, **json.loads(resultado["summary"])}
        except (ValueError, TypeError):
            pass

    observacion = resultado.get("observacion") or resultado.get("mensaje") or estado
    motivo_rechazo = resultado.get("motivo_rechazo") or ""
    sesion_id = run.get("sessionId")

    if estado != "COMPLETED" or not resultado.get("exito"):
        sync.ultimo_estado = "error"
        sync.ultimo_error = (f"{resultado.get('paso_fallido', estado)}: "
                             f"{motivo_rechazo or observacion}")[:1000]
        sync.ultimo_sync_en = datetime.utcnow()
        return {"empresa": sync.empresa, "origen": sync.origen, "ok": False,
                "error": sync.ultimo_error}

    desde, hasta = _rango_del_run(run, resultado)

    # El portal confirmó que no hay registros: es un resultado válido, y el
    # rango queda cubierto (si no, se volvería a pedir eternamente).
    descargas = (await bb.list_downloads(sesion_id)).get("downloads") if sesion_id else []
    if not descargas:
        if float(resultado.get("filas_estimadas") or 0) == 0:
            _cerrar_ok(sync, desde, hasta, filas=0, observacion=observacion)
            return {"empresa": sync.empresa, "origen": sync.origen, "ok": True,
                    "filas": 0, "nota": "el portal no reportó registros en el rango"}
        sync.ultimo_estado = "error"
        sync.ultimo_error = ("El agente reportó éxito pero no hay archivo descargado "
                             f"en la sesión. Portal dijo: {observacion}")[:1000]
        return {"empresa": sync.empresa, "origen": sync.origen, "ok": False,
                "error": sync.ultimo_error}

    # El más reciente: el agente descarga uno solo por run, pero si el portal
    # generó un archivo parcial antes, el bueno es el último.
    descarga = sorted(descargas, key=lambda d: d.get("createdAt") or "")[-1]
    contenido = await bb.get_download_bytes(descarga["id"])

    filas = parsear_archivo(contenido, descarga.get("filename", ""))
    resumen = ingestar_filas(db, sync.empresa, sync.eps_key, sync.origen, filas, desde, hasta)

    _cerrar_ok(sync, desde, hasta, filas=resumen["total"], observacion=observacion)

    logger.info(f"[Recobro] {sync.empresa}/{sync.eps_key}/{sync.origen}: "
                f"{resumen['nuevas']} nuevas, {resumen['actualizadas']} actualizadas "
                f"({desde} → {hasta})")
    return {"empresa": sync.empresa, "origen": sync.origen, "ok": True,
            "archivo": descarga.get("filename"), **resumen}


def _rango_del_run(run: Dict[str, Any], resultado: Dict[str, Any]) -> Tuple[Optional[date], Optional[date]]:
    """Rango realmente consultado. Se lee de las variables del run, que son lo
    que de verdad se le pidió al portal; `rango_confirmado` del agente sirve de
    respaldo si el run no las expone."""
    variables = run.get("variables") or {}

    def _v(clave):
        item = variables.get(clave)
        return item.get("value") if isinstance(item, dict) else item

    desde, hasta = _a_fecha(_v("desde")), _a_fecha(_v("hasta"))
    if desde and hasta:
        return desde, hasta

    fechas = re.findall(r"\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}",
                        str(resultado.get("rango_confirmado") or ""))
    if len(fechas) >= 2:
        return _a_fecha(fechas[0]), _a_fecha(fechas[-1])
    return desde, hasta


def _cerrar_ok(sync: RecobroSync, desde: Optional[date], hasta: Optional[date],
               filas: int, observacion: str):
    sync.ultimo_estado = "ok"
    sync.ultimo_error = None
    sync.ultimo_sync_en = datetime.utcnow()
    sync.filas_totales = (sync.filas_totales or 0) + filas
    if desde:
        sync.cubierto_desde = min(sync.cubierto_desde or desde, desde)
    if hasta:
        sync.cubierto_hasta = max(sync.cubierto_hasta or hasta, hasta)


async def ciclo_recobro(empresas_eps: Optional[List[Tuple[str, str]]] = None) -> Dict[str, Any]:
    """
    Un ciclo completo: recoger lo que terminó y pedir lo nuevo.
    Pensado para correr una vez al día desde el scheduler (los reportes de las
    EPS no cambian por minuto y cada run cuesta).
    """
    db = SessionLocal()
    try:
        recogido = await sincronizar_reportes(db)

        lanzados = []
        if empresas_eps is None:
            # Solo las combinaciones que tienen agente de reportes publicado:
            # lanzar runs para EPS sin agente sería quemar plata en errores.
            with_reportes = {
                s.eps_key for s in db.query(RadicacionSkill).filter(
                    RadicacionSkill.agent_id_reportes.isnot(None)
                ).all()
            }
            empresas_eps = [
                (b.nombre_empresa, b.bot_nombre)
                for b in db.query(EmpresaBotConfig).filter(
                    EmpresaBotConfig.estado == "activo",
                    EmpresaBotConfig.bot_nombre.in_(with_reportes or [""]),
                ).all()
            ]
        for empresa, eps_key in empresas_eps:
            for origen in ORIGENES:
                try:
                    lanzados.append(await lanzar_reporte(db, empresa, eps_key, origen))
                except Exception as e:
                    logger.warning(f"[Recobro] no se pudo lanzar {empresa}/{eps_key}/{origen}: {e}")
        return {"sincronizacion": recogido, "lanzados": lanzados}
    finally:
        db.close()


# ── Wrappers síncronos para APScheduler (mismo patrón que ciclo_dispatcher_sync) ──

def ciclo_recobro_sync():
    """Diario: pide a cada portal lo nuevo. Un run por empresa/EPS/reporte."""
    import asyncio
    try:
        resultado = asyncio.run(ciclo_recobro())
        lanzados = sum(1 for r in resultado["lanzados"] if r.get("ok"))
        logger.info(f"[Recobro] Ciclo diario: {lanzados} reporte(s) solicitado(s)")
    except Exception as e:
        logger.error(f"❌ Error en ciclo de recobro: {e}")


def ingestar_pendientes_sync():
    """
    Frecuente y barato: no lanza runs, solo recoge los que ya terminaron.
    Separado del ciclo diario para que un archivo descargado no espere 24 h
    a entrar a la base.
    """
    import asyncio

    async def _correr():
        db = SessionLocal()
        try:
            return await sincronizar_reportes(db)
        finally:
            db.close()

    try:
        resultado = asyncio.run(_correr())
        if resultado["procesados"] or resultado["errores"]:
            logger.info(f"[Recobro] Ingesta: {len(resultado['procesados'])} reporte(s), "
                        f"{len(resultado['errores'])} error(es)")
    except Exception as e:
        logger.error(f"❌ Error ingestando reportes de recobro: {e}")


# ══════════════════════════════════════════════════════════════
#  El cruce (para eso era todo lo anterior)
# ══════════════════════════════════════════════════════════════

def cruce(db: Session, empresa: str, eps_key: Optional[str] = None,
          desde: Optional[date] = None, hasta: Optional[date] = None,
          limite: int = 500, offset: int = 0) -> Dict[str, Any]:
    """
    Lo radicado contra lo pagado. Clasifica cada incapacidad en:

      pagada          → la EPS pagó todo lo que había reconocido
      pagada_parcial  → pagó menos de lo reconocido: queda un saldo que DEBE
      en_tramite      → radicada y reconocida, todavía sin pago
      negada_apelable → negada por un motivo que se puede controvertir
      negada_en_firme → negada por un motivo que no se va a revertir: se castiga
      sin_respuesta   → la radicamos y la EPS no la reporta (la que hay que reclamar)
      no_radicada     → la EPS la tiene pero no salió de nuestro sistema
                        (alguien radicó por fuera, o se nos perdió el registro)

    Una negación en texto libre no se puede sumar ni decidir, así que el motivo
    del portal pasa por `motivos.clasificar_negacion()` y queda con código
    (`motivo_codigo`). Eso es lo que permite decir "la EPS le negó $X por
    períodos descubiertos" en vez de "hay 40 rechazos", y separar lo que vale la
    pena apelar de lo que solo hay que castigar para dejar de perseguirlo.

    `totales["rechazada"]` se conserva como la suma de las dos negadas: había
    consumidores contando por esa llave.
    """
    q_cola = db.query(RadicacionCola).filter(
        RadicacionCola.empresa == empresa,
        RadicacionCola.estado == "exitosa",
    )
    q_filas = db.query(RecobroFila).filter(RecobroFila.empresa == empresa)

    if eps_key:
        q_cola = q_cola.filter(RadicacionCola.eps_key == eps_key)
        q_filas = q_filas.filter(RecobroFila.eps_key == eps_key)
    if desde:
        q_cola = q_cola.filter(RadicacionCola.creado_en >= datetime.combine(desde, datetime.min.time()))
        q_filas = q_filas.filter(RecobroFila.fecha_inicio >= desde)
    if hasta:
        q_cola = q_cola.filter(RadicacionCola.creado_en <= datetime.combine(hasta, datetime.max.time()))
        q_filas = q_filas.filter(RecobroFila.fecha_inicio <= hasta)

    filas = q_filas.all()
    pagadas = {_clave_cruce(f): f for f in filas if f.origen == "pagadas"}
    radicadas = {_clave_cruce(f): f for f in filas if f.origen == "radicadas"}

    resultado, vistas = [], set()
    totales = {"pagada": 0, "pagada_parcial": 0, "en_tramite": 0, "negada_apelable": 0,
               "negada_en_firme": 0, "sin_respuesta": 0, "no_radicada": 0}
    valor_pagado = valor_pendiente = valor_debido = 0.0
    valor_apelable = valor_castigado = 0.0
    por_motivo: Dict[str, Dict[str, Any]] = {}

    for item in q_cola.order_by(RadicacionCola.creado_en.desc()).limit(limite).offset(offset).all():
        clave = f"rad:{(item.radicado or '').strip()}" if item.radicado else f"cola:{item.id}"
        vistas.add(clave)
        fila_pago = pagadas.get(clave)
        fila_rad = radicadas.get(clave)
        motivo_codigo = accion = saldo = None

        if fila_pago:
            pagado = fila_pago.valor_pagado or 0.0
            valor_pagado += pagado
            # Lo reconocido manda sobre lo girado: si la EPS reconoció más de lo
            # que pagó, esa diferencia es cartera viva y hay que reclamarla. Sin
            # esto una incapacidad pagada a medias se veía igual que una pagada
            # completa y el saldo se perdía en silencio.
            reconocido = (fila_rad.valor_reconocido if fila_rad else None) or 0.0
            if reconocido - pagado > _TOLERANCIA_PESOS:
                situacion, motivo = "pagada_parcial", "La EPS reconoció más de lo que giró"
                saldo = round(reconocido - pagado, 2)
                valor_debido += saldo
            else:
                situacion, motivo = "pagada", None
        elif fila_rad and _es_rechazo(fila_rad.estado_portal):
            motivo = fila_rad.motivo_rechazo or fila_rad.estado_portal
            neg = clasificar_negacion(motivo)
            motivo_codigo, accion = neg.get("codigo"), neg.get("accion")
            en_firme = neg.get("apelable") is False
            situacion = "negada_en_firme" if en_firme else "negada_apelable"
            pendiente = fila_rad.valor_reconocido or 0.0
            if en_firme:
                valor_castigado += pendiente
            else:
                valor_apelable += pendiente
            registro = por_motivo.setdefault(
                motivo_codigo, {"codigo": motivo_codigo, "nombre": neg.get("nombre"),
                                "apelable": neg.get("apelable"), "accion": neg.get("accion"),
                                "casos": 0, "valor": 0.0})
            registro["casos"] += 1
            registro["valor"] += pendiente
        elif fila_rad:
            situacion, motivo = "en_tramite", fila_rad.estado_portal
            valor_pendiente += fila_rad.valor_reconocido or 0.0
        else:
            situacion, motivo = "sin_respuesta", "La EPS no reporta esta incapacidad"

        totales[situacion] += 1
        resultado.append({
            "cola_id": item.id, "serial_caso": item.serial_caso, "eps": item.eps_key,
            "radicado": item.radicado, "cedula": (item.datos_ocr or {}).get("cedula"),
            "tipo_incapacidad": item.tipo_incapacidad,
            "radicado_en": item.procesado_en.isoformat() if item.procesado_en else None,
            "situacion": situacion, "motivo": motivo,
            "motivo_codigo": motivo_codigo, "accion": accion,
            "estado_portal": (fila_pago or fila_rad).estado_portal if (fila_pago or fila_rad) else None,
            "valor_pagado": fila_pago.valor_pagado if fila_pago else None,
            "valor_reconocido": (fila_rad.valor_reconocido if fila_rad else None),
            "saldo_debido": saldo,
            "fecha_pago": fila_pago.fecha_pago.isoformat() if fila_pago and fila_pago.fecha_pago else None,
        })

    # Lo que la EPS tiene y nosotros no: plata que sí entró pero sin trazabilidad,
    # o incapacidades radicadas por fuera del sistema.
    for clave, fila in {**radicadas, **pagadas}.items():
        if clave in vistas or fila.cola_id:
            continue
        totales["no_radicada"] += 1
        resultado.append({
            "cola_id": None, "serial_caso": None, "eps": fila.eps_key,
            "radicado": fila.radicado, "cedula": fila.cedula,
            "nombre_trabajador": fila.nombre_trabajador,
            "tipo_incapacidad": fila.motivo,
            "radicado_en": fila.fecha_inicio.isoformat() if fila.fecha_inicio else None,
            "situacion": "no_radicada",
            "motivo": "La EPS la reporta pero no salió de este sistema",
            # Mismas llaves que los ítems de arriba: la tabla del admin itera una
            # sola lista y un ítem con menos campos la rompe.
            "motivo_codigo": None, "accion": None, "saldo_debido": None,
            "estado_portal": fila.estado_portal,
            "valor_pagado": fila.valor_pagado, "valor_reconocido": fila.valor_reconocido,
            "fecha_pago": fila.fecha_pago.isoformat() if fila.fecha_pago else None,
        })

    totales["rechazada"] = totales["negada_apelable"] + totales["negada_en_firme"]

    return {
        "empresa": empresa, "eps": eps_key,
        "desde": desde.isoformat() if desde else None,
        "hasta": hasta.isoformat() if hasta else None,
        "totales": totales,
        "valor_pagado": round(valor_pagado, 2),
        "valor_pendiente": round(valor_pendiente, 2),
        # Las tres cifras que pide una empresa: cuánto le deben de lo ya
        # reconocido, cuánto hay negado con pelea posible y cuánto hay que dar
        # por perdido para dejar de gastar analistas persiguiéndolo.
        "valor_debido": round(valor_debido, 2),
        "valor_negado_apelable": round(valor_apelable, 2),
        "valor_castigado": round(valor_castigado, 2),
        "negaciones": sorted(
            [{**m, "valor": round(m["valor"], 2)} for m in por_motivo.values()],
            key=lambda m: m["valor"], reverse=True),
        "items": resultado,
        "cobertura": _cobertura(db, empresa, eps_key),
    }


def _clave_cruce(fila: RecobroFila) -> str:
    """Clave para emparejar con la cola: siempre por radicado cuando existe."""
    if fila.radicado:
        return f"rad:{fila.radicado.strip()}"
    if fila.cola_id:
        return f"cola:{fila.cola_id}"
    return fila.clave_natural


_PALABRAS_RECHAZO = ("rechaz", "devuel", "negad", "anulad", "no aprob", "glosa")

# Los portales redondean distinto a como liquidamos nosotros. Una diferencia de
# unos pesos no es una deuda: es ruido contable, y marcarla como saldo llenaría
# el reporte de falsos positivos.
_TOLERANCIA_PESOS = 100.0


def _es_rechazo(estado_portal: Optional[str]) -> bool:
    texto = _norm(estado_portal)
    return any(p.replace(" ", "_") in texto for p in _PALABRAS_RECHAZO)


def _cobertura(db: Session, empresa: str, eps_key: Optional[str]) -> List[Dict[str, Any]]:
    """Hasta qué fecha está descargado cada reporte — para que el cruce nunca
    se lea como si fuera completo cuando no lo es."""
    q = db.query(RecobroSync).filter(RecobroSync.empresa == empresa)
    if eps_key:
        q = q.filter(RecobroSync.eps_key == eps_key)
    return [{
        "eps": s.eps_key, "origen": s.origen,
        "desde": s.cubierto_desde.isoformat() if s.cubierto_desde else None,
        "hasta": s.cubierto_hasta.isoformat() if s.cubierto_hasta else None,
        "estado": s.ultimo_estado, "error": s.ultimo_error,
        "ultimo_sync": s.ultimo_sync_en.isoformat() if s.ultimo_sync_en else None,
    } for s in q.all()]


def historico_persona(db: Session, empresa: str, cedula: str,
                      eps_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Trazabilidad de una persona: todas sus incapacidades ordenadas por fecha,
    con los huecos entre una y la siguiente.

    Sale de la base, no del portal: es instantáneo, gratis, y sirve igual para
    una reclamación, una prórroga o una auditoría. Solo hay que volver al
    portal cuando se necesite el certificado oficial firmado por la EPS.
    """
    cedula = _solo_digitos(cedula)
    q = db.query(RecobroFila).filter(
        RecobroFila.empresa == empresa,
        RecobroFila.cedula == cedula,
    )
    if eps_key:
        q = q.filter(RecobroFila.eps_key == eps_key)

    # Una misma incapacidad aparece en los dos reportes con columnas distintas:
    # "radicadas" trae fecha fin, días y diagnóstico; "pagadas" trae el giro.
    # Se combinan campo por campo en vez de quedarse con una sola fila, porque
    # elegir "la de pagadas" borraba los días y la fecha fin del histórico.
    unificadas: Dict[str, Dict[str, Any]] = {}
    for fila in q.all():
        clave = _clave_cruce(fila)
        destino = unificadas.setdefault(clave, {})
        for campo in CAMPOS_FILA:
            valor = getattr(fila, campo, None)
            # Gana el primero que traiga dato; entre dos con dato, el de
            # "pagadas" para lo económico (es el reporte definitivo del giro).
            if valor in (None, ""):
                continue
            if destino.get(campo) in (None, "") or (
                fila.origen == "pagadas"
                and campo in ("valor_pagado", "fecha_pago", "estado_portal")
            ):
                destino[campo] = valor

    filas = sorted(unificadas.values(), key=lambda f: f.get("fecha_inicio") or date.min)

    items, anterior_fin, dias_totales = [], None, 0
    for fila in filas:
        inicio, fin = fila.get("fecha_inicio"), fila.get("fecha_fin")
        hueco = (inicio - anterior_fin).days - 1 if (anterior_fin and inicio) else None
        dias_totales += fila.get("dias") or 0
        items.append({
            "radicado": fila.get("radicado"),
            "numero_incapacidad": fila.get("numero_incapacidad"),
            "fecha_inicio": inicio.isoformat() if inicio else None,
            "fecha_fin": fin.isoformat() if fin else None,
            "dias": fila.get("dias"), "diagnostico": fila.get("diagnostico"),
            "motivo": fila.get("motivo"), "estado_portal": fila.get("estado_portal"),
            "motivo_rechazo": fila.get("motivo_rechazo"),
            "valor_pagado": fila.get("valor_pagado"),
            "valor_reconocido": fila.get("valor_reconocido"),
            "fecha_pago": fila["fecha_pago"].isoformat() if fila.get("fecha_pago") else None,
            # Días sin incapacidad entre esta y la anterior. 0 = continuidad
            # (prórroga); negativo = traslape, que la EPS rechaza.
            "dias_hueco_anterior": hueco,
        })
        if fin and (anterior_fin is None or fin > anterior_fin):
            anterior_fin = fin

    return {
        "empresa": empresa, "cedula": cedula,
        "nombre": next((f.get("nombre_trabajador") for f in filas
                        if f.get("nombre_trabajador")), None),
        "total_incapacidades": len(items), "dias_totales": dias_totales,
        "items": items,
        "cobertura": _cobertura(db, empresa, eps_key),
    }
