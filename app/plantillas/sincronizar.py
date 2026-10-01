"""
Publica en Meta las plantillas definidas en `app/plantillas/whatsapp.py`.

    python -m app.plantillas.sincronizar estado       # qué hay en Meta vs. repo
    python -m app.plantillas.sincronizar publicar     # crea las que faltan
    python -m app.plantillas.sincronizar publicar --solo incapacidad_radicada
    python -m app.plantillas.sincronizar borrar incapacidad_radicada

Mismo patrón que `app/agentes/sincronizar.py`: el repo es la fuente y Meta el
destino. La API de plantillas **no permite editar el texto de una plantilla ya
aprobada** — para cambiarlo hay que borrarla y volverla a crear, y eso la manda
otra vez a revisión. Por eso `publicar` nunca pisa lo que ya existe: dice qué
está distinto y deja la decisión en manos de quien corre el comando.

Requiere en el entorno (las mismas que ya usa el bot):
    WHATSAPP_API_TOKEN, WHATSAPP_WABA_ID
"""

import argparse
import json
import os
import sys
from typing import Dict, List, Optional

import requests

from app.plantillas.whatsapp import IDIOMA, PLANTILLAS, payload_para_crear

API_VERSION = os.environ.get("WHATSAPP_API_VERSION", "v26.0")
BASE = f"https://graph.facebook.com/{API_VERSION}"
TOKEN = os.environ.get("WHATSAPP_API_TOKEN")
WABA_ID = os.environ.get("WHATSAPP_WABA_ID") or os.environ.get(
    "WHATSAPP_BUSINESS_ACCOUNT_ID"
)
TIMEOUT = 30


def _exigir_entorno() -> None:
    faltan = [n for n, v in (("WHATSAPP_API_TOKEN", TOKEN),
                             ("WHATSAPP_WABA_ID", WABA_ID)) if not v]
    if faltan:
        print(f"❌ Faltan variables de entorno: {', '.join(faltan)}")
        sys.exit(1)


def _headers() -> dict:
    return {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _error_de(resp: requests.Response) -> str:
    """Saca el mensaje real de Meta; el status code solo no dice nada útil."""
    try:
        err = resp.json().get("error", {})
        partes = [err.get("message", "")]
        if err.get("error_user_msg"):
            partes.append(err["error_user_msg"])
        if err.get("code"):
            partes.append(f"(code {err['code']})")
        return " ".join(p for p in partes if p) or resp.text[:200]
    except Exception:
        return resp.text[:200]


def listar_en_meta() -> List[dict]:
    """Todas las plantillas de la WABA, siguiendo la paginación de Meta."""
    plantillas: List[dict] = []
    url: Optional[str] = f"{BASE}/{WABA_ID}/message_templates"
    params: Optional[dict] = {"limit": 100,
                              "fields": "name,status,category,language,quality_score"}
    while url:
        resp = requests.get(url, headers=_headers(), params=params, timeout=TIMEOUT)
        if resp.status_code != 200:
            print(f"❌ No se pudieron listar las plantillas: {_error_de(resp)}")
            sys.exit(1)
        datos = resp.json()
        plantillas.extend(datos.get("data", []))
        # El `next` ya trae el cursor dentro de la URL: reenviar params lo rompe.
        url = datos.get("paging", {}).get("next")
        params = None
    return plantillas


def _indice_por_nombre(remotas: List[dict]) -> Dict[str, dict]:
    return {p["name"]: p for p in remotas if p.get("language") == IDIOMA}


def cmd_estado() -> None:
    remotas = _indice_por_nombre(listar_en_meta())
    print(f"\nWABA {WABA_ID} · idioma '{IDIOMA}' · API {API_VERSION}\n")
    print(f"  {'PLANTILLA':35s} {'EN META':22s} CATEGORÍA")
    print("  " + "─" * 70)
    for nombre in PLANTILLAS:
        r = remotas.get(nombre)
        estado = r["status"] if r else "— no existe —"
        categoria = r.get("category", "") if r else PLANTILLAS[nombre]["categoria"]
        print(f"  {nombre:35s} {estado:22s} {categoria}")

    huerfanas = [n for n in remotas if n not in PLANTILLAS]
    if huerfanas:
        print("\n  Existen en Meta y no en el repo (¿creadas a mano?):")
        for n in huerfanas:
            print(f"    · {n}  [{remotas[n]['status']}]")
    print()


def cmd_publicar(solo: Optional[str]) -> None:
    remotas = _indice_por_nombre(listar_en_meta())
    objetivo = [solo] if solo else list(PLANTILLAS)

    if solo and solo not in PLANTILLAS:
        print(f"❌ '{solo}' no está definida en app/plantillas/whatsapp.py")
        sys.exit(1)

    creadas, omitidas, fallidas = 0, 0, 0
    for nombre in objetivo:
        if nombre in remotas:
            print(f"  ⏭️  {nombre}: ya existe en Meta [{remotas[nombre]['status']}] — "
                  f"no se toca (para cambiar el texto hay que borrarla y recrearla)")
            omitidas += 1
            continue

        resp = requests.post(
            f"{BASE}/{WABA_ID}/message_templates",
            headers=_headers(),
            json=payload_para_crear(nombre),
            timeout=TIMEOUT,
        )
        if resp.status_code in (200, 201):
            cuerpo = resp.json()
            print(f"  ✅ {nombre}: creada [{cuerpo.get('status', 'PENDING')}] "
                  f"id={cuerpo.get('id')}")
            creadas += 1
        else:
            print(f"  ❌ {nombre}: {_error_de(resp)}")
            fallidas += 1

    print(f"\n  creadas={creadas}  ya existían={omitidas}  fallidas={fallidas}")
    if creadas:
        print("\n  Meta las revisa en minutos u horas. Quedan en PENDING y no se "
              "pueden enviar hasta que pasen a APPROVED:")
        print("  python -m app.plantillas.sincronizar estado")


def cmd_borrar(nombre: str) -> None:
    resp = requests.delete(
        f"{BASE}/{WABA_ID}/message_templates",
        headers=_headers(),
        params={"name": nombre},
        timeout=TIMEOUT,
    )
    if resp.status_code == 200:
        print(f"✅ '{nombre}' borrada de Meta.")
        print("   Si la vuelves a crear entra otra vez a revisión.")
    else:
        print(f"❌ No se pudo borrar '{nombre}': {_error_de(resp)}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publica en Meta las plantillas de WhatsApp del repo."
    )
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("estado", help="compara el repo contra lo que hay en Meta")
    p_pub = sub.add_parser("publicar", help="crea en Meta las que falten")
    p_pub.add_argument("--solo", help="publicar una sola plantilla por nombre")
    p_del = sub.add_parser("borrar", help="borra una plantilla en Meta")
    p_del.add_argument("nombre")

    args = parser.parse_args()
    _exigir_entorno()

    if args.comando == "estado":
        cmd_estado()
    elif args.comando == "publicar":
        cmd_publicar(args.solo)
    elif args.comando == "borrar":
        cmd_borrar(args.nombre)


if __name__ == "__main__":
    main()
