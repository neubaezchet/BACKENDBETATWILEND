"""
Paso 1 de "guardar el flujo como Compensar" para Nueva EPS:
- Reusa el Context ya creado para el bot Nueva EPS.
- Abre una sesión directa con PROXY_COLOMBIA + ese context, keep_alive, solveCaptchas.
- Imprime el link de live view INMEDIATO para que el usuario lo vea en vivo.
- Hace login real (Playwright) con las credenciales reales, selectores confirmados
  en el HTML real del portal (loginForm:id / loginForm:clave / loginForm:loginButton).
- Al final persiste el context (cookies) y libera la sesión.
"""
import os, sys, time
import httpx
from playwright.sync_api import sync_playwright

API_KEY = os.environ["BROWSERBASE_API_KEY"]
BASE = "https://api.browserbase.com"
HEADERS = {"X-BB-API-Key": API_KEY, "Content-Type": "application/json"}
PROXY_COLOMBIA = [{"type": "browserbase", "geolocation": {"country": "CO"}}]

CONTEXT_ID = "f6c4f0e8-8843-453f-8643-f680605b67cb"  # ya creado para el bot Nueva EPS
USUARIO = "1032407358"
CLAVE = "Eliot1234"

def main():
    with httpx.Client(timeout=30) as c:
        r2 = c.post(f"{BASE}/v1/sessions", headers=HEADERS, json={
            "proxies": PROXY_COLOMBIA,
            "keepAlive": True,
            "timeout": 900,
            "browserSettings": {
                "context": {"id": CONTEXT_ID, "persist": True},
                "solveCaptchas": True,
                "blockAds": True,
            },
        })
        r2.raise_for_status()
        session = r2.json()
        session_id = session["id"]
        connect_url = session["connectUrl"]
        print("SESSION_ID:", session_id, flush=True)

        r3 = c.get(f"{BASE}/v1/sessions/{session_id}/debug", headers=HEADERS)
        live_url = r3.json().get("debuggerFullscreenUrl")
        print("LIVE_VIEW:", live_url, flush=True)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(connect_url)
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()

        target = "https://portal.nuevaeps.com.co/Portal/home.jspx"
        print(f"Navegando a {target} ...", flush=True)
        page.goto(target, wait_until="domcontentloaded", timeout=45000)
        time.sleep(2)
        print("TITLE tras cargar:", page.title(), flush=True)

        page.select_option("#loginForm\\:tipoId", value="3")  # 3 = CC
        page.fill("#loginForm\\:id", USUARIO)
        page.fill("#loginForm\\:clave", CLAVE)
        time.sleep(1)
        page.screenshot(path="_scratch_nuevaeps_before_submit.png", full_page=True)

        page.click("#loginForm\\:loginButton")
        time.sleep(5)
        print("TITLE_POST_LOGIN:", page.title(), flush=True)
        print("URL_POST_LOGIN:", page.url, flush=True)
        page.screenshot(path="_scratch_nuevaeps_after_login.png", full_page=True)
        body_snip = page.inner_text("body")[:800]
        print("BODY_POST_LOGIN:", body_snip, flush=True)

        browser.close()

    # Liberar sesión (persist ya guardó cookies en el context)
    with httpx.Client(timeout=30) as c:
        c.post(f"{BASE}/v1/sessions/{session_id}", headers=HEADERS, json={"status": "REQUEST_RELEASE"})
    print("CONTEXT_GUARDADO:", CONTEXT_ID, flush=True)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
