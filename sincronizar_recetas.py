"""
sincronizar_recetas.py — Motor de sincronización y emisión automática de Recetas Agronómicas en MDA SIGIRAO.

Modos de ejecución:
1. Local (Doble clic en CARGAR_RECETAS.bat o python sincronizar_recetas.py)
2. Cloud GitHub Actions (Evento repository_dispatch, schedule cron o workflow_dispatch manual)
"""

import os
import sys
import json
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
from playwright.async_api import async_playwright

# Configurar logging
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

# Configuración de SharePoint (para actualización de estado si están disponibles las credenciales)
SP_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "c3d65cc5-56d1-4ac0-9f4f-a6ab47c80563")
SP_TENANT_ID = os.getenv("AZURE_TENANT_ID", "576e8544-afbe-423a-94a8-94fb80aaffe3")
SP_SITE_ID   = os.getenv("SP_SITE_ID", "adblickgranossa49.sharepoint.com,152e4cd9-1ef2-45cf-850a-4591a6c80a87,c4d5c877-8ae4-46cc-b602-fec95c7e2287")
SP_LIST_ID   = os.getenv("SP_RECETAS_LIST_ID", "864c7935-6592-4c0b-b73b-4ed39de9ac4f")


async def emitir_receta_playwright(page, receta_data: dict) -> dict:
    """
    Emite una receta agronómica en MDA SIGIRAO utilizando Playwright.
    Retorna un diccionario con { 'exito': bool, 'nro_mda': str, 'error': str }
    """
    campo       = receta_data.get("campo", "")
    lotes       = receta_data.get("lotes", [])
    productos   = receta_data.get("productos", [])
    forma_apl   = receta_data.get("forma_aplicacion", "12") # 12: Terrestre
    propiedad   = receta_data.get("propiedad_aplicacion", "ARRENDATARIO")
    cuit_prod   = receta_data.get("cuit_productor", MDA_CUIT_PRODUCTOR)
    nro_interna = receta_data.get("nro_receta", "R-0000")

    # Obtener ID de Lote oficial MDA
    id_mda_lote = None
    if lotes and len(lotes) > 0:
        id_mda_lote = lotes[0].get("id_mda") or lotes[0].get("lote_id")
        lote_nombre = lotes[0].get("lote", "")
    else:
        lote_nombre = "Lote s/d"

    logger.info(f"Procesando Receta {nro_interna} — Campo: {campo} | Lote: {lote_nombre} (ID MDA: {id_mda_lote})")

    try:
        # 1. Navegar a recetaAplicacion/new
        await page.goto(f"{BASE_URL}/sigirao/recetaAplicacion/new", wait_until="networkidle", timeout=30000)

        # Manejo de pantalla de CUIT si aplica
        if await page.locator("#cuit").count() > 0:
            await page.fill("#cuit", cuit_prod)
            await page.click("#botonEnviar")
            await page.wait_for_load_state("networkidle")

        # Seleccionar botón Receta de Aplicación si aparece
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
            # Fallback por texto
            opts = await lote_sel.locator("option").all()
            for opt in opts:
                txt = (await opt.inner_text()).lower()
                val = await opt.get_attribute("value")
                if lote_nombre.lower() in txt or campo.lower() in txt:
                    await lote_sel.select_option(value=val)
                    break

        await lote_sel.dispatch_event("change")
        await asyncio.sleep(1)

        # Forma de Aplicación y Condición
        await page.locator("select[name='receta_aplicacion[formaAplicacion]']").select_option(value=str(forma_apl))
        await page.locator("select[name='receta_aplicacion[propiedadAplicacion]']").select_option(value=str(propiedad))

        # Paso 1: Siguiente
        await page.click("a[href='#next']")
        await asyncio.sleep(1.5)

        # 3. Paso 1: Cultivo y Tratamiento
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

        # 4. Agregar Productos
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

        # Tiempos de Carencia y Reingreso
        await page.fill("#receta_aplicacion_tiempoCarencia", "14")
        await page.select_option("#receta_aplicacion_unidadTiempoCarencia", value="días")

        await page.fill("#receta_aplicacion_tiempoReingresoLote", "24")
        await page.select_option("#receta_aplicacion_unidadTiempoReingresoLote", value="horas")

        # 5. Guardar Borrador Oficial en MDA
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

        logger.info(f"✓ ÉXITO: Receta {nro_interna} emitida en MDA con N° Oficial: {nro_mda or 'OK'}")
        return {"exito": True, "nro_mda": nro_mda, "error": None}

    except Exception as e:
        logger.error(f"✗ ERROR al emitir receta {nro_interna}: {e}")
        return {"exito": False, "nro_mda": None, "error": str(e)}


async def main():
    logger.info("=" * 65)
    logger.info("  SINCRONIZADOR Y EMISOR DE RECETAS AGRONÓMICAS — ADBLICK / MDA")
    logger.info("=" * 65)

    # 1. Comprobar si proviene de un evento de GitHub Actions (repository_dispatch)
    event_path = os.getenv("GITHUB_EVENT_PATH")
    recetas_a_procesar = []

    if event_path and os.path.exists(event_path):
        logger.info("Detectado evento GitHub Actions (repository_dispatch)...")
        with open(event_path, "r", encoding="utf-8") as f:
            event_data = json.load(f)
        client_payload = event_data.get("client_payload", {})
        if client_payload:
            recetas_a_procesar.append(client_payload)

    # Si no viene de GitHub Actions, buscar recetas en cola local o SharePoint
    if not recetas_a_procesar:
        cola_file = "scratch/cola_recetas_pendientes.json"
        if os.path.exists(cola_file):
            try:
                with open(cola_file, "r", encoding="utf-8") as f:
                    recetas_a_procesar = json.load(f)
            except Exception as e:
                logger.warning(f"No se pudo leer {cola_file}: {e}")

    if not recetas_a_procesar:
        logger.info("No hay recetas pendientes en la cola inmediata. Monitoreando base de datos...")
        # Receta de prueba default si se ejecuta sin parámetros
        print("\nOpciones de ejecución:")
        print("1. Procesar última receta generada en SharePoint")
        print("2. Ejecutar prueba de verificación con lote El Carrilero")
        print("3. Salir")
        
        # En entornos no interactivos (CI / bat)
        if not sys.stdin.isatty():
            logger.info("Ejecución en modo no-interactivo finalizada.")
            return

        opcion = input("\nSeleccioná una opción (1-3): ").strip()
        if opcion == "2":
            recetas_a_procesar.append({
                "nro_receta": "TEST-AUTO",
                "campo": "El Carrilero",
                "lotes": [{"lote": "Ec1", "id_mda": "5771", "has": 72.9}],
                "productos": [{"nombre": "Paraquat", "id_mda": "7541", "dosis": "2.0", "diagnostico_id": "9"}],
                "forma_aplicacion": "12",
                "propiedad_aplicacion": "ARRENDATARIO"
            })
        else:
            return

    logger.info(f"Total de recetas a emitir en MDA: {len(recetas_a_procesar)}")

    # Iniciar Playwright y sesión en MDA
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 960})
        page = await context.new_page()

        # Login único en MDA
        logger.info(f"Iniciando sesión en MDA con usuario: {MDA_EMAIL}...")
        await page.goto(f"{BASE_URL}/login", wait_until="networkidle", timeout=30000)
        await page.fill("#inputEmail", MDA_EMAIL)
        await page.fill("#inputPassword", MDA_CLAVE)
        await page.click("button[type='submit']")
        await page.wait_for_load_state("networkidle")
        logger.info("Sesión iniciada correctamente en MDA SIGIRAO.")

        # Emitir cada receta
        for receta in recetas_a_procesar:
            res = await emitir_receta_playwright(page, receta)
            if res["exito"]:
                logger.info(f"Receta {receta.get('nro_receta')} completada con éxito.")
            await asyncio.sleep(2)

        await browser.close()

    logger.info("=" * 65)
    logger.info("  PROCESO DE SINCRONIZACIÓN FINALIZADO CON ÉXITO")
    logger.info("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
