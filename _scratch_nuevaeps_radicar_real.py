# -*- coding: utf-8 -*-
"""
Radicacion REAL del caso CC 6010345 (Manufacturas Eliot / Patprimo) en Nueva EPS.
Llena todo el formulario y adjunta el soporte real, pero SE DETIENE antes de
hacer clic en RADICAR (accion irreversible) hasta confirmacion del usuario.
"""
import os, time, json
import httpx
from playwright.sync_api import sync_playwright

API_KEY = os.environ["BROWSERBASE_API_KEY"]
BASE = "https://api.browserbase.com"
HEADERS = {"X-BB-API-Key": API_KEY, "Content-Type": "application/json"}
PROXY_COLOMBIA = [{"type": "browserbase", "geolocation": {"country": "CO"}}]
CONTEXT_ID = "f6c4f0e8-8843-453f-8643-f680605b67cb"
PDF_PATH = os.path.abspath("_scratch_soporte_6010345.pdf")

CELULAR = "3183878871"
CORREO = "incapacidades@patprimo.com.co"

def dump(page, tag):
    page.screenshot(path=f"_scratch_nuevaeps_{tag}.png", full_page=True)
    with open(f"_scratch_nuevaeps_{tag}.html", "w", encoding="utf-8") as f:
        f.write(page.content())
    print(f"--- {tag} --- title={page.title()!r} url={page.url}", flush=True)

def main():
    assert os.path.exists(PDF_PATH), f"No existe el PDF: {PDF_PATH}"

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
        if page.locator("#loginForm\\:tipoId").count() > 0:
            print("Logueando...", flush=True)
            page.select_option("#loginForm\\:tipoId", value="3")
            page.fill("#loginForm\\:id", "1032407358")
            page.fill("#loginForm\\:clave", "Eliot1234")
            page.click("#loginForm\\:loginButton")
            time.sleep(4)

        page.click("#tabServicios")
        time.sleep(3)
        page.get_by_text("Empleador", exact=False).first.click()
        time.sleep(3)
        page.click("[onclick*=\"showOption('option70')\"]")
        time.sleep(1)
        with context.expect_page(timeout=20000) as new_page_info:
            page.get_by_text("Transcripción Incapacidades", exact=False).first.click()
        fp = new_page_info.value
        fp.wait_for_load_state("domcontentloaded", timeout=30000)
        time.sleep(3)
        print("FORM URL:", fp.url, flush=True)

        fp.select_option("select[formcontrolname='tipoDoc']", value="CC")
        fp.fill("input[formcontrolname='documento']", "6010345")
        fp.fill("input[formcontrolname='fechaInicio']", "2026-08-28")
        fp.get_by_role("button", name="BUSCAR").click()
        time.sleep(4)

        nombre = fp.locator("input[formcontrolname='nombre']").input_value()
        print("TRABAJADOR ENCONTRADO:", nombre, flush=True)
        assert "CARO ROMERO" in nombre.upper(), f"Nombre inesperado: {nombre}"

        fp.fill("input[formcontrolname='celular']", CELULAR)
        fp.fill("input[formcontrolname='correo']", CORREO)
        time.sleep(1)
        dump(fp, "60_datos_contacto")

        fp.set_input_files("input[formcontrolname='adjunto']", PDF_PATH)
        time.sleep(1)
        dump(fp, "61_archivo_seleccionado")

        fp.get_by_role("button", name="Cargar").click()
        time.sleep(4)
        dump(fp, "62_despues_cargar")

        # Marcar "ACEPTO" (checkbox de terminos)
        fp.locator("input[formcontrolname='terminosAceptados']").check()
        time.sleep(1)
        dump(fp, "63_listo_para_radicar")

        radicar_btn = fp.get_by_role("button", name="RADICAR")
        habilitado = radicar_btn.is_enabled()
        print("BOTON RADICAR HABILITADO:", habilitado, flush=True)
        print("PAUSA DE SEGURIDAD: NO se hizo clic en RADICAR. Esperando confirmacion humana.", flush=True)
        print("SESSION SIGUE VIVA (keepAlive) para que el usuario revise en LIVE_VIEW antes de continuar.", flush=True)

        # OJO: browser.close() aqui NO cierra la sesion de Browserbase (keepAlive:true),
        # solo desconecta esta conexion CDP. La sesion queda disponible para reconectar.
        browser.close()

    print("SESSION_ID_PARA_CONTINUAR:", session_id, flush=True)
    print("DONE_SIN_RADICAR", flush=True)

if __name__ == "__main__":
    main()
