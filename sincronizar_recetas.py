import os, sys, json, asyncio
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()
sys.stdout.reconfigure(line_buffering=True)

BASE = "https://mi.mda.gba.gob.ar"
EMAIL = os.getenv("MDA_EMAIL", "mariano1703@hotmail.com").strip()
CLAVE = os.getenv("MDA_CLAVE", "Mi34369873#").strip()
CUIT_PROD = os.getenv("MDA_CUIT_PRODUCTOR", "30710939345").strip()

async def emitir():
    receta = {}
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if event_path and os.path.exists(event_path):
        with open(event_path, "r", encoding="utf-8") as f:
            evt = json.load(f)
            receta = evt.get("client_payload") or evt.get("inputs") or {}

    lote_id = str(receta.get("lote_id") or (receta.get("lotes") and receta["lotes"][0].get("id_mda")) or "5771")
    forma = str(receta.get("forma_aplicacion") or "12")
    prop = str(receta.get("propiedad_aplicacion") or "ARRENDATARIO")
    
    prods = receta.get("productos") or []
    prod_id = str(prods[0].get("id_mda") if prods else receta.get("producto_id") or "7541")
    dosis = str(prods[0].get("dosis") if prods else receta.get("dosis") or "2.0")

    print(f"Emisión MDA -> Lote: {lote_id} | Prod: {prod_id} ({dosis} L/ha)", flush=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.goto(f"{BASE}/login", wait_until="networkidle")
        await page.fill("#inputEmail", EMAIL)
        await page.fill("#inputPassword", CLAVE)
        await page.click("button[type='submit']")
        await page.wait_for_load_state("networkidle")

        await page.goto(f"{BASE}/sigirao/recetaAplicacion/new", wait_until="networkidle")
        if await page.locator("#cuit").count() > 0:
            await page.fill("#cuit", CUIT_PROD)
            await page.click("#botonEnviar")
            await page.wait_for_load_state("networkidle")

        btn = page.locator("form[action*='recetaAplicacion/new'] button, form[action*='recetaAplicacion/new'] input[type='submit']")
        if await btn.count() > 0:
            await btn.first.click()
            await page.wait_for_load_state("networkidle")

        lote_sel = page.locator("select[name='receta_aplicacion[lotePrecargado]']")
        await lote_sel.wait_for(state="visible", timeout=20000)
        await lote_sel.select_option(value=lote_id)
        await lote_sel.dispatch_event("change")
        await asyncio.sleep(1)

        await page.locator("select[name='receta_aplicacion[formaAplicacion]']").select_option(value=forma)
        await page.locator("select[name='receta_aplicacion[propiedadAplicacion]']").select_option(value=prop)
        await page.click("a[href='#next']")
        await asyncio.sleep(1.5)

        await page.wait_for_selector("#agregarCultivo", state="visible", timeout=20000)
        await page.click("#agregarCultivo")
        await asyncio.sleep(1)
        tipo = page.locator("select[name^='receta_aplicacion[recetaAplicacionCultivos]'][name$='[tipoCultivo]']").first
        await tipo.select_option(index=1)
        await tipo.dispatch_event("change")
        await asyncio.sleep(1.5)
        cult = page.locator("select[name^='receta_aplicacion[recetaAplicacionCultivos]'][name$='[cultivoAfectado]']").first
        await cult.select_option(index=1)
        await cult.dispatch_event("change")

        btn_p = page.locator("#agregarProductoAgroquimicoTratamiento, #agregarSustancia, a.botonAgregarRowProductoEnTratamiento")
        await btn_p.first.click()
        await asyncio.sleep(1)
        psel = page.locator("select[name^='receta_aplicacion[tratamiento][sustancias]'][name$='[productoAgroquimico]']").first
        try:
            await psel.select_option(value=prod_id)
        except:
            await psel.select_option(index=1)
        await psel.dispatch_event("change")

        dinp = page.locator("input[name^='receta_aplicacion[tratamiento][sustancias]'][name$='[dosisHectarea]']").first
        await dinp.fill(dosis)

        dsel = page.locator("select[name^='receta_aplicacion[tratamiento][sustancias]'][name$='[diagnostico]']").first
        if await dsel.count() > 0:
            await dsel.select_option(index=1)

        await page.fill("#receta_aplicacion_tiempoCarencia", "14")
        await page.select_option("#receta_aplicacion_unidadTiempoCarencia", value="días")
        await page.fill("#receta_aplicacion_tiempoReingresoLote", "24")
        await page.select_option("#receta_aplicacion_unidadTiempoReingresoLote", value="horas")

        await page.click("#guardarBorrador")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(4)

        msg = await page.locator(".alert, .flash-message, .alert-success").all_inner_texts()
        print(f"Resultado MDA: {msg}", flush=True)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(emitir())
