# -*- coding: utf-8 -*-
import os, time
from playwright.sync_api import sync_playwright

API_KEY = os.environ["BROWSERBASE_API_KEY"]
SESSION_ID = "08568126-ad1b-443c-8c74-f4ab090abb9b"

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
        assert fp is not None
        fp.bring_to_front()
        time.sleep(1)
        cancelar_btn = fp.get_by_role("button", name="CANCELAR")
        if cancelar_btn.count() > 0:
            cancelar_btn.click()
            time.sleep(2)
        fp.screenshot(path="_scratch_nuevaeps_82_dialogo_cerrado.png", full_page=True)
        browser.close()
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
