"""
Publica en Browserbase el prompt versionado de una EPS.

    python -m app.agentes.sincronizar compensar                      # ver diferencias
    python -m app.agentes.sincronizar compensar --publicar           # crear el agente
    python -m app.agentes.sincronizar compensar --tipo reportes      # el de recobro

Browserbase no permite editar un agente (su API solo expone GET y DELETE sobre
/v1/agents/{agentId}), así que "actualizar" es crear uno nuevo y apuntar la
skill al nuevo agentId. El agente viejo se deja vivo a propósito: los runs en
curso siguen usándolo y sirve para volver atrás si el nuevo sale peor.
"""

import argparse
import difflib
import os
import sys

import httpx

BASE = "https://api.browserbase.com"


def _headers() -> dict:
    api_key = os.environ.get("BROWSERBASE_API_KEY")
    if not api_key:
        sys.exit("Falta BROWSERBASE_API_KEY en el entorno (.env)")
    return {"X-BB-API-Key": api_key, "Content-Type": "application/json"}


def _prompt_publicado(agent_id: str) -> str:
    r = httpx.get(f"{BASE}/v1/agents/{agent_id}", headers=_headers(), timeout=30)
    r.raise_for_status()
    d = r.json()
    return d.get("systemPrompt") or d.get("system_prompt") or ""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("eps_key", help="clave de la EPS (ej. compensar)")
    parser.add_argument("--publicar", action="store_true", help="crear el agente en Browserbase")
    parser.add_argument("--comparar-con", metavar="AGENT_ID",
                        help="agente ya publicado contra el cual mostrar el diff")
    parser.add_argument("--tipo", choices=["radicacion", "reportes"], default="radicacion",
                        help="radicacion (por defecto) o reportes (el que baja el recobro)")
    args = parser.parse_args()

    from app.agentes import AGENTES, AGENTES_REPORTES

    registro = AGENTES if args.tipo == "radicacion" else AGENTES_REPORTES
    campo_skill = "agent_id" if args.tipo == "radicacion" else "agent_id_reportes"

    modulo = registro.get(args.eps_key.lower())
    if not modulo:
        sys.exit(f"No hay prompt de {args.tipo} para '{args.eps_key}'. "
                 f"Disponibles: {', '.join(registro) or '(ninguno)'}")

    prompt = modulo.SYSTEM_PROMPT

    if args.comparar_con:
        actual = _prompt_publicado(args.comparar_con)
        diff = list(difflib.unified_diff(
            actual.splitlines(), prompt.splitlines(),
            fromfile=f"browserbase/{args.comparar_con}",
            tofile=f"repo/{args.eps_key}/{args.tipo}", lineterm="",
        ))
        print("\n".join(diff) if diff else "Sin diferencias: lo publicado es igual al repo.")
        if not args.publicar:
            return

    if not args.publicar:
        print(f"[{args.eps_key}/{args.tipo}] prompt de {len(prompt)} caracteres listo para publicar.")
        print("Agrega --publicar para crearlo en Browserbase.")
        return

    body = {
        "name": modulo.NOMBRE_AGENTE,
        "systemPrompt": prompt,
        "resultSchema": modulo.RESULT_SCHEMA,
    }
    r = httpx.post(f"{BASE}/v1/agents", headers=_headers(), json=body, timeout=30)
    r.raise_for_status()
    agent_id = r.json()["agentId"]

    print(f"Agente creado: {agent_id}")
    print("\nFalta activarlo (no requiere deploy):")
    print(f'  PUT /admin/radicacion/skills/{args.eps_key}   body: {{"{campo_skill}": "{agent_id}"}}')


if __name__ == "__main__":
    main()
