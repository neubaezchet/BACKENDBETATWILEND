# -*- coding: utf-8 -*-
"""
Reconecta a la sesion YA VIVA (keepAlive) donde el formulario de Nueva EPS
quedo completamente lleno y listo (CC 6010345 / ANGEL MARIA CARO ROMERO),
y da el clic final en RADICAR. Captura screenshot antes y despues, y el
mensaje de confirmacion / numero de radicado que muestre el portal.
"""
import os, time, json
import httpx
from playwright.sync_api import sync_playwright

API_KEY = os.environ["BROWSERBASE_API_KEY"]
BASE = "https://api.browserbase.com"
HEADERS = {"X-BB-API-Key": API_KEY, "Content-Type": "application/json"}
SESSION_ID = "08568126-ad1b-443c-8c74-f4ab090abb9b"

def dump(page, tag):
    page.screenshot(path=f"_scratch_nuevaeps_{tag}.png", full_page=True)
    with open(f"_scratch_nuevaeps_{tag}.html", "w", encoding="utf-8") as f:
        f.write(page.content())
    print(f"--- {tag} --- title={page.title()!r} url={page.url}", flush=True)

def main():
    connect_url = f"wss://connect.browserbase.com?apiKey={API_KEY}&sessionId={SESSION_ID}"

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(connect_url)
        context = browser.contexts[0]
        print("PAGINAS ABIERTAS:", [pg.url for pg in context.pages], flush=True)

        fp = None
        for pg in context.pages:
            if "transcripcionIncapacidades" in pg.url or "FormularioTranscripcion" in pg.url:
                fp = pg
                break
        assert fp is not None, "No se encontro la pestana del formulario abierta"

        fp.bring_to_front()
        time.sleep(1)
        dump(fp, "70_antes_de_radicar_confirmado")

        radicar_btn = fp.get_by_role("button", name="RADICAR")
        assert radicar_btn.is_enabled(), "Boton RADICAR no esta habilitado"

        print(">>> HACIENDO CLIC EN RADICAR <<<", flush=True)
        radicar_btn.click()
        time.sleep(5)
        dump(fp, "71_despues_de_radicar")

        # Intentar capturar mensaje de confirmacion / numero de radicado
        try:
            body_text = fp.locator("body").inner_text()
        except Exception as e:
            body_text = f"(error leyendo body: {e})"

        with open("_scratch_nuevaeps_radicado_texto.txt", "w", encoding="utf-8") as f:
            f.write(body_text)

        print("TEXTO_PAGINA_DESPUES_DE_RADICAR (primeros 2000 chars):", flush=True)
        print(body_text[:2000], flush=True)

        # Esperar un poco mas por si aparece un modal/toast async
        time.sleep(3)
        dump(fp, "72_estado_final")

        browser.close()

    print("DONE_RADICADO", flush=True)

if __name__ == "__main__":
    main()
