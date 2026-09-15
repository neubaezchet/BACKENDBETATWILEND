import os, time, json
import httpx
from playwright.sync_api import sync_playwright

API_KEY = os.environ["BROWSERBASE_API_KEY"]
BASE = "https://api.browserbase.com"
HEADERS = {"X-BB-API-Key": API_KEY, "Content-Type": "application/json"}
PROXY_COLOMBIA = [{"type": "browserbase", "geolocation": {"country": "CO"}}]
CONTEXT_ID = "f6c4f0e8-8843-453f-8643-f680605b67cb"

def dump(page, tag):
    page.screenshot(path=f"_scratch_nuevaeps_{tag}.png", full_page=True)
    with open(f"_scratch_nuevaeps_{tag}.html", "w", encoding="utf-8") as f:
        f.write(page.content())
    print(f"--- {tag} --- title={page.title()!r} url={page.url}", flush=True)

def listar_links(page, tag):
    data = page.eval_on_selector_all(
        "a, [onclick], img[alt], input[type=submit], input[type=button]",
        """els => els.map(e => ({
            tag: e.tagName, id: e.id, text: (e.innerText||e.alt||e.value||'').trim(),
            href: (e.getAttribute('href')||'').slice(0,60), onclick: (e.getAttribute('onclick')||'').slice(0,80)
        })).filter(x => x.text || x.onclick)"""
    )
    print(f"=== links en {tag} ({len(data)}) ===", flush=True)
    for d in data:
        print(json.dumps(d, ensure_ascii=False), flush=True)

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
        if page.locator("#loginForm\\:tipoId").count() > 0:
            page.select_option("#loginForm\\:tipoId", value="3")
            page.fill("#loginForm\\:id", "1032407358")
            page.fill("#loginForm\\:clave", "Eliot1234")
            page.click("#loginForm\\:loginButton")
            time.sleep(4)

        page.click("#tabServicios")
        time.sleep(3)

        page.get_by_text("Empleador", exact=False).first.click()
        time.sleep(3)
        dump(page, "20_empleador")
        listar_links(page, "20_empleador")

        browser.close()

    with httpx.Client(timeout=30) as c:
        c.post(f"{BASE}/v1/sessions/{session_id}", headers=HEADERS, json={"status": "REQUEST_RELEASE"})
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
