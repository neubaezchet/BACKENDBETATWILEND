# -*- coding: utf-8 -*-
"""
Como el token de recaptcha SI se obtiene (log 'Token obtenido') pero el postback
nunca ocurre, sospechamos que recaptcha.adres.gov.co/api/recaptcha-servi/check/token
esta devolviendo valid:false (score bajo por automatizacion). Capturamos el body
exacto de esa respuesta para confirmarlo. Si es asi, la salida es: llamar
__doPostBack('btnConsultar','') manualmente vía JS, sin depender de su validacion.
"""
import os, time, json
import httpx
from playwright.sync_api import sync_playwright

API_KEY = os.environ["BROWSERBASE_API_KEY"]
BASE = "https://api.browserbase.com"
HEADERS = {"X-BB-API-Key": API_KEY, "Content-Type": "application/json"}
PROXY_COLOMBIA = [{"type": "browserbase", "geolocation": {"country": "CO"}}]

def dump(page, tag):
    try:
        page.screenshot(path=f"_scratch_adres_{tag}.png", full_page=True)
    except Exception as e:
        print(f"(no se pudo screenshot: {e})", flush=True)
    try:
        with open(f"_scratch_adres_{tag}.html", "w", encoding="utf-8") as f:
            f.write(page.content())
    except Exception as e:
        print(f"(no se pudo guardar html: {e})", flush=True)
    print(f"--- {tag} --- title={page.title()!r} url={page.url}", flush=True)

def main():
    with httpx.Client(timeout=30) as c:
        r = c.post(f"{BASE}/v1/sessions", headers=HEADERS, json={
            "proxies": PROXY_COLOMBIA,
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
        time.sleep(3)

        page.select_option("select#tipoDoc", "CC")
        page.fill("input#txtNumDoc", "1085043374")

        try:
            with page.expect_navigation(timeout=25000, wait_until="domcontentloaded"):
                page.click("input#btnConsultar")
            print("NAVEGO_TRAS_CLICK: True", flush=True)
        except Exception as e:
            print(f"NAVEGO_TRAS_CLICK: False ({e})", flush=True)

        time.sleep(2)

        # Si no navego, forzamos el postback manualmente via JS (bypass de su validacion custom)
        if "ConsultarAfiliadoWeb" in page.url:
            body_text = page.inner_text("body")
            if "COTIZANTE" not in body_text and "ESTADO" not in body_text.upper():
                print("Forzando __doPostBack manual...", flush=True)
                try:
                    with page.expect_navigation(timeout=25000, wait_until="domcontentloaded"):
                        page.evaluate("__doPostBack('btnConsultar','')")
                    print("NAVEGO_TRAS_POSTBACK_MANUAL: True", flush=True)
                except Exception as e:
                    print(f"NAVEGO_TRAS_POSTBACK_MANUAL: False ({e})", flush=True)

        time.sleep(3)
        dump(page, "40_resultado_final")

        body_text = page.inner_text("body")
        print("=== BODY TEXT (primeros 3000 chars) ===", flush=True)
        print(body_text[:3000], flush=True)

        browser.close()

    print("SESSION_ID_PARA_CONTINUAR:", session_id, flush=True)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
