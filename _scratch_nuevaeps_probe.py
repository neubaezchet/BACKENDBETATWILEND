"""
Prueba diagnóstica: sesión directa de Browserbase con proxy geolocalizado
en Colombia (el mismo PROXY_COLOMBIA que usa /bots/{id}/sesion/login en
producción), navegando al portal transaccional real de Nueva EPS para
confirmar si el bloqueo por geolocalización que vimos con TinyFish también
aplica aquí, o si el proxy colombiano de Browserbase lo evita.

No usa Agents (esos solo soportan proxies:true, US-biased) — usa una
sesión cruda + Playwright, igual que el flujo de login manual real.
"""
import os
import sys
import json
import time
import httpx
from playwright.sync_api import sync_playwright

API_KEY = os.environ["BROWSERBASE_API_KEY"]
BASE = "https://api.browserbase.com"
HEADERS = {"X-BB-API-Key": API_KEY, "Content-Type": "application/json"}
PROXY_COLOMBIA = [{"type": "browserbase", "geolocation": {"country": "CO"}}]

def main():
    with httpx.Client(timeout=30) as c:
        r = c.post(f"{BASE}/v1/sessions", headers=HEADERS, json={"proxies": PROXY_COLOMBIA})
        if r.status_code >= 400:
            print("ERROR creando sesión:", r.status_code, r.text)
            sys.exit(1)
        session = r.json()
        session_id = session["id"]
        connect_url = session["connectUrl"]
        print("SESSION_ID:", session_id)

        r2 = c.get(f"{BASE}/v1/sessions/{session_id}/debug", headers=HEADERS)
        debug = r2.json()
        live_url = debug.get("debuggerFullscreenUrl")
        print("LIVE_VIEW:", live_url)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(connect_url)
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()
        target = "https://portal.nuevaeps.com.co/Portal/home.jspx"
        print(f"Navegando a {target} ...")
        page.goto(target, wait_until="domcontentloaded", timeout=45000)
        time.sleep(3)
        title = page.title()
        body_text = page.inner_text("body")[:800]
        print("TITLE:", title)
        print("BODY_SNIPPET:", body_text)
        page.screenshot(path="_scratch_nuevaeps_probe.png", full_page=False)
        browser.close()

    # liberar sesión
    with httpx.Client(timeout=30) as c:
        c.post(f"{BASE}/v1/sessions/{session_id}", headers=HEADERS, json={"status": "REQUEST_RELEASE"})
    print("DONE")

if __name__ == "__main__":
    main()
