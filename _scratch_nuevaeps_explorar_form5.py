# -*- coding: utf-8 -*-
"""
Continua la exploracion: llega al formulario real de Transcripcion (Angular,
consultasportalw.nuevaeps.com.co), llena tipo doc/numero/fecha, click Buscar,
y vuelca lo que aparece despues (para mapear celular/correo/adjuntar/radicar).
NO adjunta nada ni envia nada todavia.
"""
import os, time, json
import httpx
from playwright.sync_api import sync_playwright

API_KEY = os.environ["BROWSERBASE_API_KEY"]
BASE = "https://api.browserbase.com"
HEADERS = {"X-BB-API-Key": API_KEY, "Content-Type": "application/json"}
PROXY_COLOMBIA = [{"type": "browserbase", "geolocation": {"country": "CO"}}]
CONTEXT_ID = "f6c4f0e8-8843-453f-8643-f680605b67cb"

def dump(page, tag):
    page.screenshot(path=f"_scratch_nuevaeps_{tag}.png", full_page=True)
    with open(f"_scratch_nuevaeps_{tag}.html", "w", encoding="utf-8") as f:
        f.write(page.content())
    print(f"--- {tag} --- title={page.title()!r} url={page.url}", flush=True)

def listar_inputs(page, tag):
    data = page.eval_on_selector_all(
        "input, select, textarea, button",
        """els => els.map(e => ({
            tag: e.tagName, type: e.type||'', formcontrolname: e.getAttribute('formcontrolname')||'',
            text: (e.innerText||e.value||'').slice(0,40).trim()
        }))"""
    )
    print(f"=== inputs en {tag} ({len(data)}) ===", flush=True)
    for d in data:
        print(json.dumps(d, ensure_ascii=False), flush=True)

def main():
    with httpx.Client(timeout=30) as c:
        r = c.post(f"{BASE}/v1/sessions", headers=HEADERS, json={
            "proxies": PROXY_COLOMBIA,
            "keepAlive": True,
            "timeout": 900,
            "browserSettings": {
                "context": {"id": CONTEXT_ID, "persist": True},
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

        page.goto("https://portal.nuevaeps.com.co/Portal/home.jspx", wait_until="domcontentloaded", timeout=45000)
        time.sleep(2)
        if page.locator("#loginForm\\:tipoId").count() > 0:
            page.select_option("#loginForm\\:tipoId", value="3")
            page.fill("#loginForm\\:id", "1032407358")
            page.fill("#loginForm\\:clave", "Eliot1234")
            page.click("#loginForm\\:loginButton")
            time.sleep(4)

        page.click("#tabServicios")
        time.sleep(3)
        page.get_by_text("Empleador", exact=False).first.click()
        time.sleep(3)
        page.click("[onclick*=\"showOption('option70')\"]")
        time.sleep(1)
        with context.expect_page(timeout=20000) as new_page_info:
            page.get_by_text("Transcripción Incapacidades", exact=False).first.click()
        form_page = new_page_info.value
        form_page.wait_for_load_state("domcontentloaded", timeout=30000)
        time.sleep(3)
        print("FORM URL:", form_page.url, flush=True)

        form_page.select_option("select[formcontrolname='tipoDoc']", value="CC")
        form_page.fill("input[formcontrolname='documento']", "6010345")
        form_page.fill("input[formcontrolname='fechaInicio']", "2026-08-28")
        time.sleep(1)
        dump(form_page, "50_antes_buscar")

        form_page.get_by_role("button", name="BUSCAR").click()
        time.sleep(4)
        dump(form_page, "51_despues_buscar")
        listar_inputs(form_page, "51_despues_buscar")

        browser.close()

    with httpx.Client(timeout=30) as c:
        c.post(f"{BASE}/v1/sessions/{session_id}", headers=HEADERS, json={"status": "REQUEST_RELEASE"})
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
