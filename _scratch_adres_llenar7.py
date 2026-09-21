# -*- coding: utf-8 -*-
"""
5 intentos previos (proxy CO, sin proxy, proxy US, timing humano, navegacion
organica) dieron siempre valid:false. Eso apunta a una senal de fingerprint
(navigator.webdriver, WebGL software fallback, etc.), no a IP/comportamiento.
Probamos parches de stealth manuales via add_init_script (gratis, sin plan
Enterprise) para esconder esas senales ANTES de que corra el JS de recaptcha
Enterprise, tanto en la pagina top como en el iframe.
"""
import os, time, json
import httpx
from playwright.sync_api import sync_playwright

API_KEY = os.environ["BROWSERBASE_API_KEY"]
BASE = "https://api.browserbase.com"
HEADERS = {"X-BB-API-Key": API_KEY, "Content-Type": "application/json"}
PROXY_COLOMBIA = [{"type": "browserbase", "geolocation": {"country": "CO"}}]

STEALTH_JS = r"""
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', {
  get: () => [1,2,3,4,5].map(() => ({ name: 'Chrome PDF Plugin' }))
});
Object.defineProperty(navigator, 'languages', { get: () => ['es-CO','es','en-US','en'] });
Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
window.chrome = window.chrome || { runtime: {} };
const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
if (originalQuery) {
  window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
      Promise.resolve({ state: Notification.permission }) :
      originalQuery(parameters)
  );
}
try {
  const getParameter = WebGLRenderingContext.prototype.getParameter;
  WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) { return 'Google Inc. (NVIDIA)'; }
    if (parameter === 37446) { return 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)'; }
    return getParameter.apply(this, [parameter]);
  };
} catch (e) {}
delete navigator.__proto__.webdriver;
"""

def dump(page, tag):
    try:
        page.screenshot(path=f"_scratch_adres_{tag}.png", full_page=True)
    except Exception as e:
        print(f"(no se pudo screenshot: {e})", flush=True)
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
        context.add_init_script(STEALTH_JS)
        page = context.pages[0] if context.pages else context.new_page()

        def on_response(resp):
            if "check/token" in resp.url:
                try:
                    print("CHECK_TOKEN_STATUS:", resp.status, flush=True)
                    print("CHECK_TOKEN_BODY:", resp.text(), flush=True)
                except Exception as e:
                    print(f"(no se pudo leer body: {e})", flush=True)
        page.on("response", on_response)
        page.on("console", lambda msg: print(f"[console:{msg.type}] {msg.text}", flush=True) if "fallback" in msg.text.lower() or "webgl" in msg.text.lower() else None)

        page.goto("https://aplicaciones.adres.gov.co/BDUA_Internet/Pages/ConsultarAfiliadoWeb_2.aspx",
                   wait_until="domcontentloaded", timeout=45000)
        time.sleep(3)

        webdriver_val = page.evaluate("navigator.webdriver")
        print("NAVIGATOR_WEBDRIVER:", webdriver_val, flush=True)

        page.mouse.move(300, 200, steps=10)
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
        dump(page, "80_form_lleno_stealthmanual")

        popup = None
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
            dump(popup, "81_popup_resultado")
            print("POPUP_URL:", popup.url, flush=True)
            body = popup.inner_text("body")
            print("=== POPUP BODY (3000 chars) ===", flush=True)
            print(body[:3000], flush=True)
        else:
            dump(page, "81_mismapagina_resultado")
            body = page.inner_text("body")
            print("=== PAGE BODY (3000 chars) ===", flush=True)
            print(body[:3000], flush=True)

        browser.close()

    print("SESSION_ID_PARA_CONTINUAR:", session_id, flush=True)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
