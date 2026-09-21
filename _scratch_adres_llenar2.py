# -*- coding: utf-8 -*-
"""
Reintento: el recaptcha es Enterprise INVISIBLE (accion LOGIN) + validacion contra
recaptcha.adres.gov.co, y termina en un __doPostBack EN LA MISMA PAGINA (no popup).
Sospecha: blockAds=True estaba bloqueando las llamadas de google recaptcha o de
recaptcha.adres.gov.co. Sesion nueva SIN blockAds, con logs de consola y de red.
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

        console_logs = []
        page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))
        page.on("pageerror", lambda exc: console_logs.append(f"[pageerror] {exc}"))

        failed_requests = []
        page.on("requestfailed", lambda req: failed_requests.append(
            f"{req.method} {req.url} -> {req.failure}"))

        recaptcha_responses = []
        def on_response(resp):
            u = resp.url
            if "recaptcha" in u:
                recaptcha_responses.append(f"{resp.status} {u}")
        page.on("response", on_response)

        page.goto("https://aplicaciones.adres.gov.co/BDUA_Internet/Pages/ConsultarAfiliadoWeb_2.aspx",
                   wait_until="domcontentloaded", timeout=45000)
        time.sleep(3)

        page.select_option("select#tipoDoc", "CC")
        page.fill("input#txtNumDoc", "1085043374")
        dump(page, "30_form_lleno")

        # click y esperar a que la pagina navegue (postback = full reload en ASP.NET WebForms)
        try:
            with page.expect_navigation(timeout=30000, wait_until="domcontentloaded"):
                page.click("input#btnConsultar")
            print("NAVEGO_TRAS_CLICK: True", flush=True)
        except Exception as e:
            print(f"NAVEGO_TRAS_CLICK: False ({e})", flush=True)

        time.sleep(4)
        dump(page, "31_resultado")

        print("=== CONSOLE LOGS ===", flush=True)
        for l in console_logs[-60:]:
            print(l, flush=True)
        print("=== FAILED REQUESTS ===", flush=True)
        for f in failed_requests:
            print(f, flush=True)
        print("=== RECAPTCHA RESPONSES ===", flush=True)
        for r_ in recaptcha_responses:
            print(r_, flush=True)

        recaptcha_val = page.eval_on_selector("input#recaptchaToken", "e => e.value") if page.query_selector("input#recaptchaToken") else None
        print("RECAPTCHA_TOKEN_FINAL_LEN:", len(recaptcha_val) if recaptcha_val else 0, flush=True)

        # buscar tabla de resultados si aparecio
        try:
            body_text = page.inner_text("body")
            print("=== BODY TEXT (primeros 2000 chars) ===", flush=True)
            print(body_text[:2000], flush=True)
        except Exception as e:
            print(f"(no se pudo leer body text: {e})", flush=True)

        browser.close()

    print("SESSION_ID_PARA_CONTINUAR:", session_id, flush=True)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
