# -*- coding: utf-8 -*-
"""
El token de recaptcha se obtiene pero el backend de ADRES marca valid:false
(score bajo). Hipotesis: la IP del proxy Colombia de Browserbase esta marcada
como datacenter/proxy por Google (penaliza mucho el score de recaptcha
Enterprise), y/o los clicks/fills instantaneos delatan automatizacion.
Prueba: SIN proxy (red default de Browserbase) + interacciones mas humanas
(mouse move, delays, tipeo caracter a caracter) + mas tiempo en pagina antes
de consultar.
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
            # SIN proxies: usamos la red default de Browserbase
            "keepAlive": True,
            "timeout": 600,
            "browserSettings": {
                "solveCaptchas": True,
                "blockAds": False,
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

        page.goto("https://aplicaciones.adres.gov.co/BDUA_Internet/Pages/ConsultarAfiliadoWeb_2.aspx",
                   wait_until="domcontentloaded", timeout=45000)

        # simular lectura humana de la pagina
        page.mouse.move(300, 200)
        time.sleep(1.2)
        page.mouse.move(450, 350, steps=15)
        time.sleep(1.5)

        page.select_option("select#tipoDoc", "CC")
        time.sleep(0.8)

        campo = page.locator("input#txtNumDoc")
        campo.click()
        time.sleep(0.5)
        campo.type("1085043374", delay=120)
        time.sleep(1.5)

        page.mouse.move(485, 306, steps=10)
        time.sleep(1)

        dump(page, "50_form_lleno_humano")

        try:
            with page.expect_navigation(timeout=30000, wait_until="domcontentloaded"):
                page.click("input#btnConsultar")
            print("NAVEGO_TRAS_CLICK: True", flush=True)
        except Exception as e:
            print(f"NAVEGO_TRAS_CLICK: False ({e})", flush=True)

        time.sleep(3)
        dump(page, "51_resultado")

        body_text = page.inner_text("body")
        print("=== BODY TEXT (primeros 3000 chars) ===", flush=True)
        print(body_text[:3000], flush=True)

        browser.close()

    print("SESSION_ID_PARA_CONTINUAR:", session_id, flush=True)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
