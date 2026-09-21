# -*- coding: utf-8 -*-
"""
El log de consola mostraba 'fallback a software WebGL' -> senal clasica de
automatizacion que recaptcha Enterprise penaliza (valid:false en las 4 pruebas
anteriores). Browserbase tiene browserSettings.advancedStealth (Advanced Browser
Stealth Mode) justamente para esto. Reintentamos con advancedStealth=True,
proxy Colombia, y capturando el popup con context.expect_page() (confirmado por
el usuario: ADRES abre una VENTANA NUEVA a RespuestaConsulta.aspx?to=... cuando
el envio es exitoso).
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
                "advancedStealth": True,
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

        page.goto("https://aplicaciones.adres.gov.co/BDUA_Internet/Pages/ConsultarAfiliadoWeb_2.aspx",
                   wait_until="domcontentloaded", timeout=45000)

        page.mouse.move(300, 200)
        time.sleep(1.2)
        page.mouse.move(450, 350, steps=15)
        time.sleep(1.5)

        page.select_option("select#tipoDoc", "CC")
        time.sleep(0.8)
        campo = page.locator("input#txtNumDoc")
        campo.click()
        time.sleep(0.5)
        campo.type("1085043374", delay=110)
        time.sleep(1.5)
        page.mouse.move(485, 306, steps=10)
        time.sleep(1)
        dump(page, "60_form_lleno_stealth")

        popup = None
        navego_misma_pagina = False
        try:
            with context.expect_page(timeout=15000) as popup_info:
                page.click("input#btnConsultar")
            popup = popup_info.value
            print("SE_ABRIO_POPUP: True", flush=True)
        except Exception as e:
            print(f"SE_ABRIO_POPUP: False ({e})", flush=True)

        time.sleep(3)

        if popup:
            popup.wait_for_load_state("domcontentloaded", timeout=25000)
            dump(popup, "61_popup_resultado")
            print("POPUP_URL:", popup.url, flush=True)
            body = popup.inner_text("body")
            print("=== POPUP BODY (3000 chars) ===", flush=True)
            print(body[:3000], flush=True)
        else:
            dump(page, "61_mismapagina_resultado")
            body = page.inner_text("body")
            print("=== PAGE BODY (3000 chars) ===", flush=True)
            print(body[:3000], flush=True)

        browser.close()

    print("SESSION_ID_PARA_CONTINUAR:", session_id, flush=True)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
