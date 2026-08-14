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
            receta = evt.get("client_payload") or {}

    if not receta:
        print("No se recibieron datos de receta en client_payload. Finalizando.", flush=True)
        return

    nro_receta = receta.get("nro_receta", "R-0000")
    campo_nombre = receta.get("campo", "")
    lotes = receta.get("lotes") or []
    lote_id = None
    lote_nombre = ""
    if lotes:
        lote_id = str(lotes[0].get("id_mda") or lotes[0].get("lote_id") or "")
        lote_nombre = lotes[0].get("lote", "")
    if not lote_id:
        lote_id = str(receta.get("lote_id") or "5771")

    forma = str(receta.get("forma_aplicacion") or "12") # 12 = Terrestre
    prop = str(receta.get("propiedad_aplicacion") or "ARRENDATARIO")
    
    prods = receta.get("productos") or []
    if not prods:
        prods = [{"id_mda": "7541", "dosis": "2.0", "diagnostico_id": "9"}]

    print(f"==================================================", flush=True)
    print(f"Emisión Automática MDA: Receta {nro_receta}", flush=True)
    print(f"Campo: {campo_nombre} | Lote: {lote_nombre} (ID MDA: {lote_id})", flush=True)
    print(f"Productos: {len(prods)} fitosanitarios", flush=True)
    print(f"==================================================", flush=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # 1. Login
        print("[1/5] Autenticando en MDA...", flush=True)
        await page.goto(f"{BASE}/login", wait_until="networkidle")
        await page.fill("#inputEmail", EMAIL)
        await page.fill("#inputPassword", CLAVE)
        await page.click("button[type='submit']")
        await page.wait_for_load_state("networkidle")

        # 2. Asistente Nueva Receta
        print("[2/5] Ingresando al asistente de receta de aplicación...", flush=True)
        await page.goto(f"{BASE}/sigirao/recetaAplicacion/new", wait_until="networkidle")
        if await page.locator("#cuit").count() > 0:
            await page.fill("#cuit", CUIT_PROD)
            await page.click("#botonEnviar")
            await page.wait_for_load_state("networkidle")

        btn = page.locator("form[action*='recetaAplicacion/new'] button, form[action*='recetaAplicacion/new'] input[type='submit']")
        if await btn.count() > 0:
            await btn.first.click()
            await page.wait_for_load_state("networkidle")

        # 3. Lote y Forma
        print(f"[3/5] Seleccionando Lote Oficial MDA (ID: {lote_id})...", flush=True)
        lote_sel = page.locator("select[name='receta_aplicacion[lotePrecargado]']")
        await lote_sel.wait_for(state="visible", timeout=20000)
        try:
            await lote_sel.select_option(value=lote_id)
        except Exception as el:
            print(f"Aviso al seleccionar lote {lote_id}: {el}, seleccionando index 1", flush=True)
            await lote_sel.select_option(index=1)
        await lote_sel.dispatch_event("change")
        await asyncio.sleep(1)

        await page.locator("select[name='receta_aplicacion[formaAplicacion]']").select_option(value=forma)
        await page.locator("select[name='receta_aplicacion[propiedadAplicacion]']").select_option(value=prop)
        await page.click("a[href='#next']")
        await asyncio.sleep(1.5)

        # 4. Cultivo
        print("[4/5] Cargando cultivo y productos fitosanitarios...", flush=True)
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

        # 5. Tratamiento / Productos
        for i, prod in enumerate(prods):
            if i > 0:
                btn_p = page.locator("#agregarProductoAgroquimicoTratamiento, #agregarSustancia, a.botonAgregarRowProductoEnTratamiento")
                await btn_p.first.click()
                await asyncio.sleep(1)

            psel = page.locator("select[name^='receta_aplicacion[tratamiento][sustancias]'][name$='[productoAgroquimico]']").nth(i)
            p_id = str(prod.get("id_mda") or prod.get("producto_id") or "7541")
            try:
                await psel.select_option(value=p_id)
            except:
                await psel.select_option(index=1)
            await psel.dispatch_event("change")

            d_val = str(prod.get("dosis") or "2.0")
            dinp = page.locator("input[name^='receta_aplicacion[tratamiento][sustancias]'][name$='[dosisHectarea]']").nth(i)
            await dinp.fill(d_val)

            dsel = page.locator("select[name^='receta_aplicacion[tratamiento][sustancias]'][name$='[diagnostico]']").nth(i)
            if await dsel.count() > 0:
                diag_id = str(prod.get("diagnostico_id") or "9")
                try:
                    await dsel.select_option(value=diag_id)
                except:
                    await dsel.select_option(index=1)

        await page.fill("#receta_aplicacion_tiempoCarencia", "14")
        await page.select_option("#receta_aplicacion_unidadTiempoCarencia", value="días")
        await page.fill("#receta_aplicacion_tiempoReingresoLote", "24")
        await page.select_option("#receta_aplicacion_unidadTiempoReingresoLote", value="horas")

        # 6. Guardar en MDA
        print("[5/5] Guardando borrador oficial en MDA SIGIRAO...", flush=True)
        await page.click("#guardarBorrador")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(4)

        msg = await page.locator(".alert, .flash-message, .alert-success").all_inner_texts()
        print(f"✅ Resultado MDA: {msg}", flush=True)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(emitir())
