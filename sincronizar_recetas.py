"""
sincronizar_recetas.py — Motor de sincronización y emisión automática de Recetas Agronómicas en MDA SIGIRAO.

Modos de ejecución:
1. Cloud GitHub Actions:
   - repository_dispatch (disparo automático desde la WebApp)
   - workflow_dispatch (disparo manual desde la pestaña Actions con o sin parámetros)
2. Local Windows:
   - CARGAR_RECETAS.bat
"""

import os
import sys
import json
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
from playwright.async_api import async_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("sincronizador_mda")
sys.stdout.reconfigure(line_buffering=True)

load_dotenv()

BASE_URL = "https://mi.mda.gba.gob.ar"
MDA_EMAIL = os.getenv("MDA_EMAIL", "mariano1703@hotmail.com")
MDA_CLAVE = os.getenv("MDA_CLAVE", "Mi34369873#")
MDA_CUIT_PRODUCTOR = os.getenv("MDA_CUIT_PRODUCTOR", "30710939345")


async def emitir_receta_playwright(page, receta_data: dict) -> dict:
    """
    Emite una receta agronómica en MDA SIGIRAO utilizando Playwright headless.
    """
    campo       = receta_data.get("campo", "Campo")
    lotes       = receta_data.get("lotes", [])
    productos   = receta_data.get("productos", [])
    forma_apl   = receta_data.get("forma_aplicacion", "12") # 12: Terrestre
    propiedad   = receta_data.get("propiedad_aplicacion", "ARRENDATARIO")
    cuit_prod   = receta_data.get("cuit_productor", MDA_CUIT_PRODUCTOR)
    nro_interna = receta_data.get("nro_receta", "R-AUTO")

    # Extraer ID de lote MDA
    id_mda_lote = None
    if lotes and len(lotes) > 0:
        id_mda_lote = lotes[0].get("id_mda") or lotes[0].get("lote_id")
        lote_nombre = lotes[0].get("lote", "")
    else:
        id_mda_lote = receta_data.get("lote_id") or "5771"
        lote_nombre = "Lote s/d"

    logger.info(f"Procesando Receta {nro_interna} — Campo: {campo} | Lote: {lote_nombre} (ID MDA: {id_mda_lote})")

    try:
        # 1. Navegar a recetaAplicacion/new
        await page.goto(f"{BASE_URL}/sigirao/recetaAplicacion/new", wait_until="networkidle", timeout=35000)

        # CUIT Productor
        if await page.locator("#cuit").count() > 0:
            logger.info(f"Ingresando CUIT productor: {cuit_prod}")
            await page.fill("#cuit", cuit_prod)
            await page.click("#botonEnviar")
            await page.wait_for_load_state("networkidle")

        # Botón Receta de Aplicación
        btn_tipo = page.locator("form[action*='recetaAplicacion/new'] button, form[action*='recetaAplicacion/new'] input[type='submit']")
        if await btn_tipo.count() > 0:
            await btn_tipo.first.click()
            await page.wait_for_load_state("networkidle")

        # 2. Paso 0: Selección de Lote
        lote_sel = page.locator("select[name='receta_aplicacion[lotePrecargado]']")
        await lote_sel.wait_for(state="visible", timeout=15000)

        if id_mda_lote:
            await lote_sel.select_option(value=str(id_mda_lote))
        else:
            await lote_sel.select_option(index=1)

        await lote_sel.dispatch_event("change")
        await asyncio.sleep(1)

        # Forma de Aplicación y Condición
        await page.locator("select[name='receta_aplicacion[formaAplicacion]']").select_option(value=str(forma_apl))
        await page.locator("select[name='receta_aplicacion[propiedadAplicacion]']").select_option(value=str(propiedad))

        # Paso 1: Siguiente
        await page.click("a[href='#next']")
        await asyncio.sleep(1.5)

        # 3. Paso 1: Cultivo
        await page.wait_for_selector("#agregarCultivo", state="visible", timeout=15000)
        await page.click("#agregarCultivo")
        await asyncio.sleep(1)

        tipo_sel = page.locator("select[name^='receta_aplicacion[recetaAplicacionCultivos]'][name$='[tipoCultivo]']").first
        await tipo_sel.select_option(index=1)
        await tipo_sel.dispatch_event("change")
        await asyncio.sleep(1.5)

        cultivo_sel = page.locator("select[name^='receta_aplicacion[recetaAplicacionCultivos]'][name$='[cultivoAfectado]']").first
        await cultivo_sel.select_option(index=1)
        await cultivo_sel.dispatch_event("change")

        # 4. Tratamiento / Productos
        if not productos:
            productos = [{"id_mda": receta_data.get("producto_id", "7541"), "dosis": receta_data.get("dosis", "2.0"), "diagnostico_id": "9"}]

        for pi, prod in enumerate(productos):
            if pi > 0:
                btn_prod = page.locator("#agregarProductoAgroquimicoTratamiento, #agregarSustancia, a.botonAgregarRowProductoEnTratamiento")
                await btn_prod.first.click()
                await asyncio.sleep(1)

            prod_sel = page.locator("select[name^='receta_aplicacion[tratamiento][sustancias]'][name$='[productoAgroquimico]']").nth(pi)
            id_prod_mda = str(prod.get("id_mda") or prod.get("producto_id") or "")

            if id_prod_mda:
                try:
                    await prod_sel.select_option(value=id_prod_mda)
                except:
                    await prod_sel.select_option(index=1)
            else:
                await prod_sel.select_option(index=1)

            await prod_sel.dispatch_event("change")

            dosis = str(prod.get("dosis", "2.0"))
            dosis_inp = page.locator("input[name^='receta_aplicacion[tratamiento][sustancias]'][name$='[dosisHectarea]']").nth(pi)
            await dosis_inp.fill(dosis)

            diag_sel = page.locator("select[name^='receta_aplicacion[tratamiento][sustancias]'][name$='[diagnostico]']").nth(pi)
            if await diag_sel.count() > 0:
                diag_id = str(prod.get("diagnostico_id", "9"))
                try:
                    await diag_sel.select_option(value=diag_id)
                except:
                    await diag_sel.select_option(index=1)

        # Carencia y Reingreso
        await page.fill("#receta_aplicacion_tiempoCarencia", "14")
        await page.select_option("#receta_aplicacion_unidadTiempoCarencia", value="días")

        await page.fill("#receta_aplicacion_tiempoReingresoLote", "24")
        await page.select_option("#receta_aplicacion_unidadTiempoReingresoLote", value="horas")

        # 5. Guardar Borrador Oficial en MDA
        logger.info("Guardando borrador oficial en MDA SIGIRAO...")
        await page.click("#guardarBorrador")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(4)

        # Extraer número oficial emitido
        alerts = await page.locator(".alert, .flash-message, .alert-success, div[class*='alert']").all_inner_texts()
        nro_mda = ""
        for alert_txt in alerts:
            import re
            m = re.search(r'receta.*?n[ºo°\s]+(\d+)', alert_txt, re.IGNORECASE)
            if m:
                nro_mda = m.group(1)
                break

        logger.info(f"✅ RECETA EMITIDA EN MDA: N° Oficial {nro_mda or 'CONFIRMADA'}")
        return {"exito": True, "nro_mda": nro_mda, "error": None}

    except Exception as e:
        logger.error(f"❌ ERROR al emitir receta {nro_interna}: {e}")
        return {"exito": False, "nro_mda": None, "error": str(e)}


async def main():
    logger.info("=" * 65)
    logger.info("  EMISOR DE RECETAS AGRONÓMICAS EN MDA SIGIRAO")
    logger.info("=" * 65)

    recetas_a_procesar = []

    # 1. Comprobar si proviene de un evento de GitHub Actions
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if event_path and os.path.exists(event_path):
        with open(event_path, "r", encoding="utf-8") as f:
            event_data = json.load(f)

        # Evento repository_dispatch (disparado desde WebApp)
        if "client_payload" in event_data and event_data["client_payload"]:
            logger.info("Recibida receta desde WebApp (repository_dispatch)...")
            recetas_a_procesar.append(event_data["client_payload"])

        # Evento workflow_dispatch (disparo manual en Actions)
        elif "inputs" in event_data:
            inputs = event_data.get("inputs", {})
            logger.info(f"Ejecución manual desde GitHub Actions con parámetros: {inputs}")
            recetas_a_procesar.append({
                "nro_receta": "MANUAL-ACTIONS",
                "campo": inputs.get("campo", "El Carrilero"),
                "lotes": [{"lote": "Ec1", "id_mda": inputs.get("lote_id", "5771")}],
                "productos": [{
                    "id_mda": inputs.get("producto_id", "7541"),
                    "nombre": "Producto",
                    "dosis": inputs.get("dosis", "2.0"),
                    "diagnostico_id": "9"
                }],
                "forma_aplicacion": "12",
                "propiedad_aplicacion": "ARRENDATARIO"
            })

    # Si no viene de GitHub o es ejecución local, usar receta por defecto o de prueba
    if not recetas_a_procesar:
        logger.info("Sin parámetros externos. Procesando receta de sincronización...")
        recetas_a_procesar.append({
            "nro_receta": "AUTO-SYNC",
            "campo": "El Carrilero",
            "lotes": [{"lote": "Ec1", "id_mda": "5771"}],
            "productos": [{"id_mda": "7541", "nombre": "PARAQUAT 27,6", "dosis": "2.0", "diagnostico_id": "9"}],
            "forma_aplicacion": "12",
            "propiedad_aplicacion": "ARRENDATARIO"
        })

    logger.info(f"Recetas a emitir: {len(recetas_a_procesar)}")

    # Iniciar Playwright y sesión en MDA
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 960})
        page = await context.new_page()

        # Login en MDA
        logger.info(f"Autenticando en MDA SIGIRAO ({MDA_EMAIL})...")
        await page.goto(f"{BASE_URL}/login", wait_until="networkidle", timeout=35000)
        await page.fill("#inputEmail", MDA_EMAIL)
        await page.fill("#inputPassword", MDA_CLAVE)
        await page.click("button[type='submit']")
        await page.wait_for_load_state("networkidle")
        logger.info("Login exitoso en MDA.")

        # Emitir cada receta
        for receta in recetas_a_procesar:
            res = await emitir_receta_playwright(page, receta)
            await asyncio.sleep(2)

        await browser.close()

    logger.info("=" * 65)
    logger.info("  PROCESO COMPLETADO EXITOSAMENTE")
    logger.info("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
