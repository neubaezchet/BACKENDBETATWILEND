# -*- coding: utf-8 -*-
"""
El clic en RADICAR abrio un modal de confirmacion nativo del portal:
"Esta seguro que desea continuar con el proceso?" (CANCELAR/ACEPTAR).
Este script da clic en ACEPTAR -- el paso verdaderamente final e irreversible --
y captura el resultado.
"""
import os, time
from playwright.sync_api import sync_playwright

API_KEY = os.environ["BROWSERBASE_API_KEY"]
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
        fp = None
        for pg in context.pages:
            if "transcripcionIncapacidades" in pg.url or "FormularioTranscripcion" in pg.url:
                fp = pg
                break
        assert fp is not None, "No se encontro la pestana del formulario"
        fp.bring_to_front()
        time.sleep(1)

        aceptar_btn = fp.get_by_role("button", name="ACEPTAR")
        assert aceptar_btn.count() > 0, "No aparece el boton ACEPTAR del modal"
        print(">>> HACIENDO CLIC EN ACEPTAR (confirmacion final del modal) <<<", flush=True)
        aceptar_btn.click()
        time.sleep(6)
        dump(fp, "80_despues_aceptar")

        try:
            body_text = fp.locator("body").inner_text()
        except Exception as e:
            body_text = f"(error leyendo body: {e})"
        with open("_scratch_nuevaeps_radicado_final_texto.txt", "w", encoding="utf-8") as f:
            f.write(body_text)
        print("TEXTO_PAGINA_DESPUES_DE_ACEPTAR (primeros 3000 chars):", flush=True)
        print(body_text[:3000], flush=True)

        time.sleep(3)
        dump(fp, "81_estado_final_confirmado")

        browser.close()
    print("DONE_ACEPTADO", flush=True)

if __name__ == "__main__":
    main()
