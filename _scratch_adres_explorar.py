# -*- coding: utf-8 -*-
"""
Exploracion del flujo de consulta de EPS en ADRES (https://www.adres.gov.co/consulte-su-eps)
para el caso CC 1085043374. Objetivo: entender por que la consulta abre una
ventana/pestana emergente y no se logra capturar, y mapear los selectores reales.
NO hace nada mas que consultar informacion publica.
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
            "input, select, button, a",
            """els => els.map(e => ({
                tag: e.tagName, type: e.type||'', id: e.id||'', name: e.getAttribute('name')||'',
                text: (e.innerText||e.value||'').slice(0,50).trim()
            }))"""
        )
        print(f"=== elementos en {tag} ({len(data)}) ===", flush=True)
        for d in data:
            if d['tag'] in ('INPUT','SELECT','BUTTON') or d['text']:
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

        page.goto("https://www.adres.gov.co/consulte-su-eps", wait_until="domcontentloaded", timeout=45000)
        time.sleep(3)
        dump(page, "01_home")
        listar_inputs(page, "01_home")

        browser.close()

    print("SESSION_ID_PARA_CONTINUAR:", session_id, flush=True)
    print("DONE_EXPLORACION_INICIAL", flush=True)

if __name__ == "__main__":
    main()
