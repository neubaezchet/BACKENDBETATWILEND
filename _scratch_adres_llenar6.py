# -*- coding: utf-8 -*-
"""
Intento sin gastos extra (sin Enterprise, sin proxy externo de pago).
Variables nuevas vs. los 4 intentos anteriores (todos con valid:false):
1. Navegamos por el flujo ORGANICO real: home adres.gov.co -> /consulte-su-eps
   -> interactuar DENTRO del iframe (no saltar directo a la URL de la subapp,
   que deja sin referrer / sin historial de navegacion, algo que el scoring de
   reCAPTCHA Enterprise SI pondera).
2. Viewport realista explicito (1920x1080) en vez del default.
3. proxies=True (proxy residencial incluido de Browserbase, sin geolocation
   forzada) - el pool CO especifico puede ser mas chico/reusado que el pool
   general.
4. Mucho mas tiempo de "lectura humana" antes de tocar el formulario.
"""
import os, time, json
import httpx
from playwright.sync_api import sync_playwright

API_KEY = os.environ["BROWSERBASE_API_KEY"]
BASE = "https://api.browserbase.com"
HEADERS = {"X-BB-API-Key": API_KEY, "Content-Type": "application/json"}

def dump(page, tag):
    try:
        page.screenshot(path=f"_scratch_adres_{tag}.png", full_page=True)
    except Exception as e:
        print(f"(no se pudo screenshot: {e})", flush=True)
    print(f"--- {tag} --- title={page.title()!r} url={page.url}", flush=True)

def main():
    with httpx.Client(timeout=30) as c:
        r = c.post(f"{BASE}/v1/sessions", headers=HEADERS, json={
            "proxies": True,
            "keepAlive": True,
            "timeout": 600,
            "browserSettings": {
                "solveCaptchas": True,
                "blockAds": False,
                "viewport": {"width": 1920, "height": 1080},
            },
        })
        r.raise_for_status()
        session = r.json()
        session_id = session["id"]
        connect_url = session["connectUrl"]
        print("SESSION_ID:", session_id, flush=True)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(connect_url)
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()

        def on_response(resp):
            if "check/token" in resp.url:
                try:
                    print("CHECK_TOKEN_STATUS:", resp.status, flush=True)
                    print("CHECK_TOKEN_BODY:", resp.text(), flush=True)
                except Exception as e:
                    print(f"(no se pudo leer body: {e})", flush=True)
        page.on("response", on_response)
        page.on("pageerror", lambda exc: print(f"[pageerror] {exc}", flush=True))

        # 1. Home real
        page.goto("https://www.adres.gov.co/", wait_until="domcontentloaded", timeout=45000)
        time.sleep(4)
        page.mouse.move(400, 300, steps=10)
        time.sleep(2)
        page.mouse.wheel(0, 300)
        time.sleep(2)

        # 2. Pagina publica con el iframe
        page.goto("https://www.adres.gov.co/consulte-su-eps", wait_until="domcontentloaded", timeout=45000)
        time.sleep(5)
        page.mouse.move(500, 400, steps=12)
        time.sleep(2)
        dump(page, "70_pagina_publica")

        frame = None
        for f in page.frames:
            if "ConsultarAfiliadoWeb" in f.url:
                frame = f
                break
        print("IFRAME_ENCONTRADO:", bool(frame), frame.url if frame else None, flush=True)

        if not frame:
            print("No se encontro el iframe, abortando", flush=True)
            browser.close()
            return

        frame.select_option("select#tipoDoc", "CC")
        time.sleep(1.2)
        campo = frame.locator("input#txtNumDoc")
        campo.click()
        time.sleep(0.8)
        campo.type("1085043374", delay=140)
        time.sleep(2.5)
        dump(page, "71_form_lleno_organico")

        popup = None
        try:
            with context.expect_page(timeout=15000) as popup_info:
                frame.click("input#btnConsultar")
            popup = popup_info.value
            print("SE_ABRIO_POPUP: True", flush=True)
        except Exception as e:
            print(f"SE_ABRIO_POPUP: False ({e})", flush=True)

        time.sleep(3)

        if popup:
            popup.wait_for_load_state("domcontentloaded", timeout=25000)
            dump(popup, "72_popup_resultado")
            print("POPUP_URL:", popup.url, flush=True)
            body = popup.inner_text("body")
            print("=== POPUP BODY (3000 chars) ===", flush=True)
            print(body[:3000], flush=True)
        else:
            dump(page, "72_mismapagina_resultado")
            body = frame.locator("body").inner_text()
            print("=== IFRAME BODY (3000 chars) ===", flush=True)
            print(body[:3000], flush=True)

        browser.close()

    print("SESSION_ID_PARA_CONTINUAR:", session_id, flush=True)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
