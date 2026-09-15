"""
Reusa el context ya logueado, navega el menu real (Servicios en linea >
Empleadores > Incapacidades > Transcripcion Incapacidades) y vuelca el HTML
de esa pagina para sacar los selectores reales, SIN llenar ni enviar nada.
"""
import os, time
import httpx
from playwright.sync_api import sync_playwright

API_KEY = os.environ["BROWSERBASE_API_KEY"]
BASE = "https://api.browserbase.com"
HEADERS = {"X-BB-API-Key": API_KEY, "Content-Type": "application/json"}
PROXY_COLOMBIA = [{"type": "browserbase", "geolocation": {"country": "CO"}}]
CONTEXT_ID = "f6c4f0e8-8843-453f-8643-f680605b67cb"

def dump(page, tag):
    page.screenshot(path=f"_scratch_nuevaeps_{tag}.png", full_page=True)
    html = page.content()
    with open(f"_scratch_nuevaeps_{tag}.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"--- {tag} --- title={page.title()!r} url={page.url}", flush=True)

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
        dump(page, "01_home")

        # Si aparece login (context no sirvio), lo hacemos de nuevo
        if page.locator("#loginForm\\:tipoId").count() > 0:
            print("Sesion no persistio, logueando de nuevo...", flush=True)
            page.select_option("#loginForm\\:tipoId", value="3")
            page.fill("#loginForm\\:id", "1032407358")
            page.fill("#loginForm\\:clave", "Eliot1234")
            page.click("#loginForm\\:loginButton")
            time.sleep(4)
            dump(page, "01b_post_login")

        # Buscar y hacer clic en "Servicios en línea"
        candidatos = page.get_by_text("Servicios en línea", exact=False)
        print("candidatos Servicios en linea:", candidatos.count(), flush=True)
        if candidatos.count() > 0:
            candidatos.first.click()
            time.sleep(3)
        dump(page, "02_servicios_en_linea")

        candidatos = page.get_by_text("Empleadores", exact=False)
        print("candidatos Empleadores:", candidatos.count(), flush=True)
        if candidatos.count() > 0:
            candidatos.first.click()
            time.sleep(3)
        dump(page, "03_empleadores")

        candidatos = page.get_by_text("Incapacidades", exact=False)
        print("candidatos Incapacidades:", candidatos.count(), flush=True)
        if candidatos.count() > 0:
            candidatos.first.click()
            time.sleep(2)
        dump(page, "04_incapacidades_menu")

        candidatos = page.get_by_text("Transcripción Incapacidades", exact=False)
        print("candidatos Transcripcion:", candidatos.count(), flush=True)
        if candidatos.count() > 0:
            candidatos.first.click()
            time.sleep(3)
        dump(page, "05_transcripcion_incapacidades")

        browser.close()

    with httpx.Client(timeout=30) as c:
        c.post(f"{BASE}/v1/sessions/{session_id}", headers=HEADERS, json={"status": "REQUEST_RELEASE"})
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
