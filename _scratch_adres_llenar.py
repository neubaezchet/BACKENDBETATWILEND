# -*- coding: utf-8 -*-
"""
Continua en la MISMA sesion (250aacba-7143-4d15-b965-044312d82c8f, keepAlive=True)
sobre la pagina directa del formulario ADRES (ya cargada ahi).
Llena CC 1085043374, intenta resolver/verificar el recaptcha, click Consultar,
y observa si abre popup o navega en la misma pestana. Captura el resultado.
"""
import os, time, json
import httpx
from playwright.sync_api import sync_playwright

API_KEY = os.environ["BROWSERBASE_API_KEY"]
BASE = "https://api.browserbase.com"
HEADERS = {"X-BB-API-Key": API_KEY, "Content-Type": "application/json"}
SESSION_ID = "250aacba-7143-4d15-b965-044312d82c8f"

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
        s = c.get(f"{BASE}/v1/sessions/{SESSION_ID}", headers=HEADERS)
        s.raise_for_status()
        info = s.json()
        connect_url = info["connectUrl"]
        print("STATUS:", info.get("status"), flush=True)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(connect_url)
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()
        print("URL_ACTUAL:", page.url, flush=True)

        # si por lo que sea no estamos en el form, navegar de nuevo
        if "ConsultarAfiliadoWeb" not in page.url:
            page.goto("https://aplicaciones.adres.gov.co/BDUA_Internet/Pages/ConsultarAfiliadoWeb_2.aspx",
                       wait_until="domcontentloaded", timeout=45000)
            time.sleep(2)

        # buscar iframes de recaptcha
        frames_info = [{"name": f.name, "url": f.url} for f in page.frames]
        print("FRAMES:", json.dumps(frames_info, ensure_ascii=False), flush=True)

        # tipoDoc ya viene en "CC" por defecto, solo llenamos numero
        page.select_option("select#tipoDoc", "CC")
        page.fill("input#txtNumDoc", "1085043374")
        dump(page, "20_form_lleno")

        recaptcha_val_antes = page.eval_on_selector("input#recaptchaToken", "e => e.value")
        print("RECAPTCHA_TOKEN_ANTES:", repr(recaptcha_val_antes), flush=True)

        # esperar un poco por si browserbase resuelve el captcha en segundo plano
        time.sleep(5)
        recaptcha_val_despues = page.eval_on_selector("input#recaptchaToken", "e => e.value")
        print("RECAPTCHA_TOKEN_DESPUES_ESPERA:", repr(recaptcha_val_despues), flush=True)

        # preparar escucha de popup ANTES de hacer click
        popup = None
        try:
            with context.expect_page(timeout=8000) as popup_info:
                page.click("input#btnConsultar")
            popup = popup_info.value
            print("SE_ABRIO_POPUP: True", flush=True)
        except Exception as e:
            print(f"SE_ABRIO_POPUP: False ({e})", flush=True)

        time.sleep(4)

        if popup:
            popup.wait_for_load_state("domcontentloaded", timeout=20000)
            dump(popup, "21_popup_resultado")
            print("POPUP_URL:", popup.url, flush=True)
        else:
            dump(page, "21_mismapagina_resultado")

        browser.close()

    print("SESSION_ID_PARA_CONTINUAR:", SESSION_ID, flush=True)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
