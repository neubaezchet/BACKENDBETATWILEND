# -*- coding: utf-8 -*-
"""
El formulario real vive en un iframe: https://aplicaciones.adres.gov.co/BDUA_Internet/Pages/ConsultarAfiliadoWeb_2.aspx
Navegamos directo ahi (evita el iframe), llenamos CC 1085043374, y vemos que pasa al Consultar
(el usuario dice que abre una pestana nueva).
"""
import os, time, json
import httpx
from playwright.sync_api import sync_playwright

API_KEY = os.environ["BROWSERBASE_API_KEY"]
BASE = "https://api.browserbase.com"
HEADERS = {"X-BB-API-Key": API_KEY, "Content-Type": "application/json"}
PROXY_COLOMBIA = [{"type": "browserbase", "geolocation": {"country": "CO"}}]

def dump(page, tag):
    page.screenshot(path=f"_scratch_adres_{tag}.png", full_page=True)
    try:
        with open(f"_scratch_adres_{tag}.html", "w", encoding="utf-8") as f:
            f.write(page.content())
    except Exception as e:
        print(f"(no se pudo guardar html: {e})", flush=True)
    print(f"--- {tag} --- title={page.title()!r} url={page.url}", flush=True)

def listar_inputs(page, tag):
    try:
        data = page.eval_on_selector_all(
            "input, select, button",
            """els => els.map(e => ({
                tag: e.tagName, type: e.type||'', id: e.id||'', name: e.getAttribute('name')||'',
                value: (e.value||'').slice(0,30)
            }))"""
        )
        print(f"=== elementos en {tag} ({len(data)}) ===", flush=True)
        for d in data:
            print(json.dumps(d, ensure_ascii=False), flush=True)
    except Exception as e:
        print(f"(error listando inputs: {e})", flush=True)

def main():
    with httpx.Client(timeout=30) as c:
        r = c.post(f"{BASE}/v1/sessions", headers=HEADERS, json={
            "proxies": PROXY_COLOMBIA,
            "keepAlive": True,
            "timeout": 600,
            "browserSettings": {
                "solveCaptchas": True,
                "blockAds": True,
            },
        })
        r.raise_for_status()
        session = r.json()
        session_id = session["id"]
        connect_url = session["connectUrl"]
        print("SESSION_ID:", session_id, flush=True)
        live = c.get(f"{BASE}/v1/sessions/{session_id}/debug", headers=HEADERS).json()
        print("LIVE_VIEW:", live.get("debuggerFullscreenUrl"), flush=True)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(connect_url)
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()

        page.goto("https://aplicaciones.adres.gov.co/BDUA_Internet/Pages/ConsultarAfiliadoWeb_2.aspx",
                   wait_until="domcontentloaded", timeout=45000)
        time.sleep(3)
        dump(page, "10_form_directo")
        listar_inputs(page, "10_form_directo")

        browser.close()

    print("SESSION_ID_PARA_CONTINUAR:", session_id, flush=True)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
