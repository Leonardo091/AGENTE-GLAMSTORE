import os
from dotenv import load_dotenv
load_dotenv()
import logging
import time
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import google.generativeai as genai
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from collections import deque
from database import db 

# Configuración de Logs
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)

app = Flask(__name__)

# Cargar variables de entorno
TOKEN_WHATSAPP = os.environ.get("WHATSAPP_TOKEN")
API_KEY_GEMINI = os.environ.get("GEMINI_API_KEY")
VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "glamstore_verify_token") # ACTUALIZADO: Coincide con tu Render

# Configurar Gemini
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    model = genai.GenerativeModel('gemini-2.0-flash')
else:
    logging.error("❌ NO SE ENCONTRÓ GEMINI_API_KEY")
    model = None

MEMORIA_USUARIOS = {}

# Keep-alive para Render (Opcional, mejor usar un cron externo si es posible)
def despertar_render():
    while True:
        time.sleep(300) # Cada 5 minutos
        try:
            # Reemplaza con tu URL real si la sabes, o usa localhost para evitar errores locales
            render_url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:10000")
            requests.get(render_url)
            logging.info("⏰ Ping keep-alive enviado")
        except Exception as e:
            logging.debug(f"Ping fallido (normal en local): {e}")

import threading
hilo_ping = threading.Thread(target=despertar_render)
hilo_ping.daemon = True
hilo_ping.start()

@app.route("/")
def home():
    return jsonify({
        "status": "ONLINE", 
        "productos_cargados": db.total_items, 
        "mensaje": "El cerebro de GlamStore está activo 💅",
        "debug_pid": os.getpid(),
        "debug_db_id": id(db)
    }), 200

@app.route("/debug/inventory", methods=["GET"])
def debug_inventory():
    """Endpoint para verificar el estado interno del inventario."""
    estado = db.get_status()
    # Si quieres protegerlo levemente:
    token = request.args.get("token")
    # if token != "tu_secreto": return "Acceso denegado", 403
    
    return jsonify(estado), 200

@app.route("/debug/config", methods=["GET"])
def debug_config():
    """Muestra qué está viendo el servidor en las variables de entorno (OJO: Muestra datos semi-sensibles)"""
    token = os.environ.get("SHOPIFY_TOKEN", "")
    url = os.environ.get("SHOPIFY_URL", "")
    return jsonify({
        "SHOPIFY_URL_RAW": f"'{url}'", # Comillas para ver espacios
        "SHOPIFY_TOKEN_MASKED": f"'{token[:5]}...{token[-4:]}'" if len(token) > 10 else "SHORT/EMPTY"
    })

@app.route("/debug/force_sync", methods=["GET"])
def debug_force_sync():
    """Fuerza la sincronización síncrona y devuelve el resultado."""
    try:
        db._actualizar_tabla_maestra() 
        return jsonify(db.get_status())
    except Exception as e:
        return jsonify({"error": str(e), "status": "failed"}), 500

@app.route("/debug/search", methods=["GET"])
def debug_search():
    """Endpoint para probar la búsqueda en tiempo real."""
    query = request.args.get("q", "")
    if not query:
        return "Falta parámetro 'q'", 400
    
    # Realizar búsqueda
    resultado = db.buscar_contextual(query)
    
    return jsonify({
        "query": query,
        "query_normalizada": db._normalizar(query),
        "resultado": resultado
    }), 200

@app.route("/admin/db")
def admin_db_view():
    """Vista HTML simple para ver la base de datos."""
    # Seguridad básica: Solo local o si tiene clave (opcional)
    # Por ahora abierta para facilidad de uso del usuario
    
    html = """
    <html>
    <head>
        <title>GlamBot DB Admin</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="p-4">
        <h2>📂 Base de Datos GlamBot</h2>
        <p>Total Productos: <b>{{total}}</b> | Última Sync: <b>{{last_sync}}</b></p>
        <table class="table table-striped table-hover">
            <thead class="table-dark">
                <tr><th>ID</th><th>Título</th><th>Categoría</th><th>Precio</th><th>Stock</th><th>Tags</th><th>Handle</th></tr>
            </thead>
            <tbody>
    """
    
    # Inyectar filas
    lista_prods = sorted(db.productos, key=lambda x: x['title'])
    rows = ""
    for p in lista_prods:
        rows += f"""
        <tr>
            <td>{p['id']}</td>
            <td>{p['title']}</td>
            <td><span class="badge bg-info text-dark">{p.get('category', '')}</span></td>
            <td>${p['price']:,.0f}</td>
            <td>{p.get('stock', '?')}</td>
            <td><small>{p.get('tags', '')}</small></td>
            <td><a href="https://glamstorechile.cl/products/{p.get('handle','')}" target="_blank">Link</a></td>
        </tr>
        """
    
    html += rows
    html += """
            </tbody>
        </table>
    </body>
    </html>
    """
    
    status = db.get_status()
    html = html.replace("{{total}}", str(status['total_productos']))
    html = html.replace("{{last_sync}}", str(status['ultima_sincronizacion']))
    
    return html

# Endpoint de Verificación (Requerido por Meta)
# Endpoint ÚNICO (Como estaba antes)
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    # 1. VERIFICACIÓN (GET) - Meta siempre hace esto primero
    if request.method == "GET":
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return request.args.get("hub.challenge")
        return "Error de validacion", 403

    # 2. MENSAJES (POST)
    try:
        body = request.get_json()
        logging.info(f"📨 WEBHOOK RECIBIDO: {body}")
        
        if not body or "entry" not in body:
            return jsonify({"status": "ignored"}), 200

        entry = body["entry"][0]["changes"][0]["value"]

        if "messages" in entry:
            msg = entry["messages"][0]
            numero = msg["from"]
            texto = msg.get("text", {}).get("body", "")
            nombre = entry.get("contacts", [{}])[0].get("profile", {}).get("name", "Cliente")
            
            # --- COMANDOS DE ADMINISTRADOR (!db) ---
            # Solo permitidos para el número configurado en .env
            admin_number = os.environ.get("ADMIN_NUMBER", "").replace("+", "").strip()
            sender_norm = numero.replace("+", "").strip()
            
            if texto.startswith("!db") and admin_number and sender_norm == admin_number:
                logging.info(f"🛡️ COMANDO ADMIN RECIBIDO de {nombre}: {texto}")
                
                try:
                    if "status" in texto:
                        st = db.get_status()
                        resp = f"📊 *ESTADO DB*\nProductos: {st['total_productos']}\nÚltima Sync: {st['ultima_sincronizacion']}\nEstado: {st['estado_sincronizacion']}"
                        enviar_whatsapp(numero, resp)
                        
                    elif "sync" in texto:
                        enviar_whatsapp(numero, "⏳ Forzando sincronización... (Esto puede tomar unos segundos)")
                        db.force_sync()
                        # Esperar un poco para dar feedback (hacky pero útil)
                        time.sleep(3)
                        st = db.get_status()
                        enviar_whatsapp(numero, f"✅ Sync iniciada/completada.\nEstado: {st['estado_sincronizacion']}\nTotal: {st['total_productos']}")
                        
                    elif "email" in texto:
                        enviar_whatsapp(numero, "📧 Generando reporte CSV y enviando... (Esto puede tardar unos segundos)")
                        
                        def tarea_email():
                            try:
                                csv_data = db.exportar_csv_str()
                                if enviar_reporte_email(csv_data):
                                    enviar_whatsapp(numero, "✅ Correo enviado exitosamente.")
                                else:
                                    enviar_whatsapp(numero, "❌ Error enviando correo. Revisa logs.")
                            except Exception as e:
                                logging.error(f"Error hilo email: {e}")
                                enviar_whatsapp(numero, "❌ Error interno generando reporte.")

                        threading.Thread(target=tarea_email).start()
                        return jsonify({"status": "command_executed_async"}), 200
                    
                    elif "buscar" in texto:
                        q = texto.replace("!db buscar", "").strip()
                        res = db.buscar_contextual(q)
                        txt = f"🔍 *Resultados Raw ({len(res['items'])}):*\n"
                        for p in res['items']:
                            txt += f"ID: {p['id']} | {p['title']} | Stock: {p.get('stock','?')} | Tags: {p.get('tags','')}\n\n"
                        enviar_whatsapp(numero, txt[:1000]) # Limitar largo

                    return jsonify({"status": "command_executed"}), 200
                except Exception as e:
                    logging.error(f"Error comando admin: {e}")
                    enviar_whatsapp(numero, f"❌ Error ejecutando comando: {str(e)}")
                    return jsonify({"status": "error"}), 200

            # Contexto (Reply)
            msg_context_id = msg.get("context", {}).get("id")

            # Gestión de memoria
            if numero not in MEMORIA_USUARIOS:
                MEMORIA_USUARIOS[numero] = {
                    'historial': deque(maxlen=6), 
                    'ultimo_msg': time.time(),
                    'msg_map': {} # Para rastrear IDs de mensajes -> productos
                }
            usuario = MEMORIA_USUARIOS[numero]
            
            historial_txt = "\n".join([f"User: {h['txt']}\nBot: {h['resp']}" for h in usuario['historial']])

            if model:
                # --- AUTO-SYNC: GARANTIZAR DATOS FRESCOS (Background) ---
                # Si los datos tienen más de 30 min de antigüedad, disparamos sync en hilo aparte
                # para no bloquear la respuesta al usuario.
                db.trigger_sync_if_stale(minutes=30)
                
                # Si el cerebro está vacío, NO bloqueamos. Verificamos si ya está sincronizando.
                if db.total_items == 0:
                    logging.warning(f"⚠️ Cerebro vacío (items=0). Status: {db.sync_status}. Intentando recarga rápida SQL...")
                    db._cargar_memoria_desde_sql()
                    
                    # Si sigue vacío después de recargar, entonces sí respondemos warming up
                    if db.total_items == 0:
                        if db.sync_status != "Sincronizando...":
                            logging.warning("🧠 Cerebro sigue vacío tras reload. Forzando sync en background...")
                            db.force_sync()
                        
                        enviar_whatsapp(numero, "🛠️ Estoy despertando y ordenando mis productos... Dame 1 minuto y pregúntame de nuevo, por favor. 🙏")
                        return jsonify({"status": "warming_up"}), 200

                procesar_inteligencia_artificial(numero, nombre, texto, historial_txt, usuario, msg_context_id)
            
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logging.error(f"🔥 ERROR: {e}")
        return jsonify({"status": "error"}), 500


def _segmentar_precios(items):
    """Obtiene PRECIOS EXACTOS únicos para mostrar variedad real sin aproximar."""
    precios = set()
    for p in items:
        try:
            # Usar valor exacto (entero).
            precio = int(p['price'])
            precios.add(precio)
        except:
            continue
    
    if not precios: return ""
    
    # Ordenar menor a mayor
    valores_unicos = sorted(list(precios))
    
    # Formato "$500, $750, $1.000, $12.990"
    txt_valores = ", ".join([f"${v:,.0f}".replace(",", ".") for v in valores_unicos])
    return f"Valores: {txt_valores}"

def procesar_inteligencia_artificial(numero, nombre, texto, historial_txt, usuario, msg_context_id=None):
    try:
        # --- ESTRATEGIA RETRIEVAL-FIRST ---
        
        # 0. CHECK CONTEXTO (REPLY)
        producto_foco = None
        if msg_context_id and 'msg_map' in usuario:
            # Buscar si el mensaje respondido corresponde a un producto enviado
            if msg_context_id in usuario['msg_map']:
                producto_foco = usuario['msg_map'][msg_context_id]
                logging.info(f"📍 Contexto detectado: Usuario responde a producto ID {producto_foco['id']} ({producto_foco['title']})")
        
        contexto_data = ""
        link_pago = None
        intencion = None # Se define dinámicamente
        mostrar_imagenes = True # Por defecto sí, salvo que estemos en resumen

        # 1. Buscamos PRIMERO en la base de datos (prioridad a productos)
        # --- FILTRO ANTICIPADO PARA PREGUNTAS DE SOPORTE ---
        # Si preguntan "dónde venden", "cuándo atienden", "qué venden", NO buscar productos semánticamente con "venden".
        keywords_soporte = ["donde", "dónde", "ubicacion", "ubicación", "calle", "lugar", "horario", "hora", "cuando", "cuándo", "telefono", "celular", "que venden", "qué venden", "mayorista"]
        es_soporte = any(k in texto.lower() for k in keywords_soporte)
        
        if es_soporte and not producto_foco:
             logging.info("ℹ️ Detectada pregunta de soporte/info. Omitiendo búsqueda de productos y forzando SOPORTE.")
             res = {"items": [], "tipo": "VACIO"}
             intencion = "SOPORTE" # FORZAR SOPORTE DURO
             
             # Pre-llenar contexto básico para asegurar que el prompt tenga info
             contexto_data = """
                INFO TIENDA GLAMSTORE:
                - 📍 Ubicación Exacta: Santo Domingo 240, Puente Alto (Interior "Sandros Collections").
                - ⏰ Horario: Lun-Vie 10:00 a 17:30 hrs | Sáb 10:00 a 14:30 hrs.
                - 📞 Contacto: +56 9 7207 9712 | glamstorechile2019@gmail.com
                - 🚚 Envíos: SOLO POR STARKEN (Por pagar).
                - 💼 Mayorista: "Hola, para compras mayoristas por favor escríbenos directo al +56972079712 y te enviamos el catálogo especial". (SOLO DAR ESTO SI PIDEN MAYORISTA).
                """
        else:
            logging.info(f"🔎 Buscando productos para: '{texto}'...")
            res = db.buscar_contextual(texto)
        

        # Si hay un producto foco (Reply), lo inyectamos como "lo encontrado" si la búsqueda normal falló o es ambigua
        # Ojo: Si el usuario responde a una foto diciendo "tienen en rojo?", deberíamos combinar.
        # Por ahora simplificamos: Si responde a un producto, ESE es el tema.
        if producto_foco:
            # Sobreescribimos comportamiento si es intención de compra clara sobre "este"
            keywords_referencia = ["este", "ese", "quiero", "llevo", "dame", "precio", "cuanto", "comprar"]
            if any(k in texto.lower() for k in keywords_referencia):
                logging.info("🎯 Usando producto foco por Reply.")
                res["items"] = [producto_foco]
                res["tipo"] = "EXACTO" # Simulamos que lo encontró
            
            # También lo agregamos al contexto visual para que el selector funcione si menciona otros
            usuario['contexto_productos'] = [producto_foco]

        if res["tipo"] != "VACIO":
            # ¡HAY PRODUCTOS! -> Forzamos intención CATALOGO
            logging.info(f"✅ Productos encontrados ({len(res['items'])}). Forzando intención CATALOGO.")
            intencion = "CATALOGO"
            
            # GUARDAR CONTEXTO PARA COMPRA RÁPIDA ("Quiero estos")
            usuario['contexto_productos'] = res['items']
            
            if res["tipo"] == "RECOMENDACION_REAL":
                # CLUSTERING DE PRECIOS (> 4 productos)
                if len(res["items"]) > 4:
                     # Generamos solo resumen de precios
                     resumen_precios = _segmentar_precios(res["items"])
                     contexto_data = f"""
                     INVENTARIO ENCONTRADO (RESUMEN):
                     {resumen_precios}
                     
                     INSTRUCCION CLAVE: NO muestres lista de productos aún. Dile al cliente los precios que tenemos y pregúntale cuál presupuesto prefiere o qué valor busca.
                     """
                     logging.info("📊 Aplicando clustering de precios (>4 items).")
                     mostrar_imagenes = False # NO enviar imágenes en fase de resumen
                else:
                    # Incluimos data rica en el contexto (Tags, Vendor)
                    lista = "\n".join([f"- {p['title']} (${p['price']:,.0f}) [Stock:{p.get('stock','')}] {{Tags:{p.get('tags','')}}}" for p in res["items"]])
                    contexto_data = f"INVENTARIO RECOMENDADO:\n{lista}"
            else: # EXACTO
                # En exacto, damos la descripción recortada también
                lista = ""
                for p in res["items"]:
                    desc_corta = p.get('body_html', '')[:150].replace("\n", " ") + "..."
                    lista += f"- {p['title']} (${p['price']:,.0f})\n  📝 Desc: {desc_corta}\n  🏷️ Tags: {p.get('tags','')}\n"
                
                contexto_data = f"PRODUCTO ENCONTRADO:\n{lista}"

            # Verificamos si quiere comprar explícitamente (SOLO INTENCION FIRME)
            keywords_compra = ["comprar este", "llevo esto", "generame el link", "dame el link", "link de pago", "pagar ahora"]
            
            # Si detectamos intención de compra o pregunta de precio sobre estos productos
            if any(k in texto.lower() for k in keywords_compra):
                # INTELIGENCIA: SELECCIONAR QUÉ PRODUCTO QUIERE
                # Si hay varios productos, preguntamos a Gemini cuál elegir
                items_a_checkout = res['items']
                
                # SI HAY FOCO POR REPLY, saltamos la duda
                if producto_foco:
                     items_a_checkout = [producto_foco]
                elif len(res['items']) > 1:
                    try:
                        prompt_selector = f"""
                        Eres un experto en entender pedidos de compra.
                        El usuario dijo: "{texto}"
                        
                        Productos disponibles en pantalla:
                        {json.dumps([{'id': p['id'], 'title': p['title'], 'handle': p.get('handle', '')} for p in res['items']], ensure_ascii=False)}
                        
                        Tu tarea: Identifica los ID de los productos que el usuario quiere comprar.
                        - Si quiere todo, responde: ["TODOS"]
                        - Si quiere uno o más específicos, responde una lista JSON con sus IDs: [12345, 67890]
                        - IMPORTANTE: Si pide CANTIDAD (ej: "quiero 2 del primero"), REPITE el ID en la lista tantas veces como pida. Ej: [12345, 12345].
                        - Si dice "este" o "ese" y NO especificó nombre (y hay varios productos), es AMBIGUO. Responde: ["AMBIGUO"]
                        - Si solo está preguntando precios y no quiere link aún, responde: []
                        - Si no se entiende, responde: []
                        
                        Responde SOLO EL JSON.
                        """
                        # Usamos el modelo para decidir
                        selector_resp = model.generate_content(prompt_selector).text.strip()
                        # Limpiar markdown si lo pone
                        selector_resp = selector_resp.replace("```json", "").replace("```", "").strip()
                        
                        seleccion = json.loads(selector_resp)
                        
                        if "AMBIGUO" in seleccion:
                            # Caso ambiguo: No generamos link, dejamos que el flujo normal pregunte
                            logging.info("🤔 Selección ambigua. Pidiendo aclaración.")
                            contexto_data = "Por favor, dime explícitamente cuál producto quieres (nombre o precio) para generarte el link correcto. 😅"
                            intencion = "CHARLA" # Para que no fuerce compra
                            items_a_checkout = [] # Reset
                        elif "TODOS" not in seleccion and seleccion:
                            # Filtrar solo los seleccionados
                            items_a_checkout = [p for p in res['items'] if p['id'] in seleccion]
                            # Expandir duplicados para handlear cantidades
                            items_expandidos = []
                            for id_sel in seleccion:
                                for p in res['items']:
                                    if p['id'] == id_sel:
                                        items_expandidos.append(p)
                                        break
                            if items_expandidos:
                                items_a_checkout = items_expandidos

                    except Exception as e:
                        logging.error(f"Error en selector inteligente: {e}")
                        # Fallback seguro: Preferible no hacer nada a cobrar mal
                        items_a_checkout = res['items'] 

                # Generamos link SOLO si hay items seleccionados y no fue ambiguo
                if items_a_checkout and intencion != "CHARLA":
                    datos_link = db.generar_checkout_especifico([p['id'] for p in items_a_checkout], res['items'])
                    
                    if datos_link:
                        link_pago = datos_link['url']
                        
                        # Generar Resumen
                        resumen_txt = "📝 *Resumen del Pedido:*\n"
                        for p in datos_link['items']:
                            resumen_txt += f"• {p['title']} (${p['price']:,.0f})\n"
                        resumen_txt += f"💰 **Total: ${datos_link['total']:,.0f}**"
                        
                        contexto_data += f"\n\n{resumen_txt}\n🔗 LINK DE PAGO: {link_pago}"
                        intencion = "COMPRAR" # Refinamos
        
        else:
            # NO hay productos nuevos. PERO... ¿Quiere comprar los anteriores del contexto?
            keywords_compra_fuerte = ["comprar", "quiero", "llevo", "dame", "esos", "los 4", "todos", "interesa"]
            if any(k in texto.lower() for k in keywords_compra_fuerte) and usuario.get('contexto_productos'):
                logging.info(f"🛒 Intención de compra detectada sobre CONTEXTO MEMORIA ({len(usuario['contexto_productos'])} productos)")
                
                # --- LOGICA SMART SELECTOR (REPETIDA PARA CONTEXTO) ---
                items_ctx = usuario['contexto_productos']
                items_a_checkout = items_ctx
                
                try:
                    prompt_selector = f"""
                    Usuario: "{texto}"
                    Items en vista: {json.dumps([{'id': p['id'], 'title': p['title']} for p in items_ctx], ensure_ascii=False)}
                    Devuelve JSON con IDs a comprar (repite si pide cantidad) o ["TODOS"] o ["AMBIGUO"] si no es claro cual.
                    """
                    selector_resp = model.generate_content(prompt_selector).text.strip().replace("```json", "").replace("```", "").strip()
                    seleccion = json.loads(selector_resp)
                    
                    if "AMBIGUO" in seleccion:
                        logging.info("🤔 Selección contexto ambigua.")
                        contexto_data = "¡Claro! Pero tengo varios productos en mente. ¿Cuál de ellos prefieres? 👇"
                        intencion = "CHARLA"
                        items_a_checkout = []
                    elif "TODOS" not in seleccion and seleccion:
                        items_a_checkout = []
                        for id_sel in seleccion:
                             for p in items_ctx:
                                 if p['id'] == id_sel:
                                     items_a_checkout.append(p)
                                     break
                except:
                    pass # Fallback a todos
                
                if items_a_checkout and intencion != "CHARLA":
                    datos_link = db.generar_checkout_especifico([p['id'] for p in items_a_checkout], items_ctx)
                    
                    if datos_link:
                        link_pago = datos_link['url']
                        
                        # Resumen
                        resumen_txt = "📝 *Resumen de lo que viste:*\n"
                        for p in datos_link['items']:
                            resumen_txt += f"• {p['title']} (${p['price']:,.0f})\n"
                        resumen_txt += f"💰 **Total: ${datos_link['total']:,.0f}**"
                        
                        contexto_data = f"{resumen_txt}\n🔗 LINK DE PAGO: {link_pago}"
                        intencion = "COMPRAR"
            else:
                # NO hay productos y no es compra de contexto -> Usamos LLM normal
                # SOLO sobrescribimos si no traemos ya una intención (como SOPORTE) que definió su propio contexto
                if not intencion:
                    contexto_data = "INVENTARIO: No encontré productos similares a esa búsqueda específica."
            
            # 2. CLASIFICACIÓN DE INTENCIÓN (Solo si no hubo productos ni compra contextual)
            if not intencion:
                prompt_router = f"""
            Actúa como un clasificador de intenciones para una tienda de maquillaje y belleza llamada "GlamStore".
            Analiza el siguiente mensaje del cliente: "{texto}"
            
            Categorías posibles:
            1. SOPORTE: Preguntan envío, horario, ubicación, reclamos.
            2. CHARLA: Saludos, agradecimientos, mensajes casuales, o preguntas de productos que NO tenemos.
            3. CATALOGO: Preguntas generales de inventario (aunque ya sabemos que no hay stock).
            
            Historial reciente:
            {historial_txt}
            
            Responde SOLO con una de las palabras: SOPORTE, CHARLA, CATALOGO.
            """
            try:
                intencion_raw = model.generate_content(prompt_router).text.strip().upper()
                if "SOPORTE" in intencion_raw: intencion = "SOPORTE"
                elif "CATALOGO" in intencion_raw: intencion = "CATALOGO"
                else: intencion = "CHARLA"
            except Exception as e:
                logging.error(f"Error clasificando intención: {e}")
                intencion = "CHARLA"

            if intencion == "SOPORTE":
                contexto_data = """
                INFO TIENDA GLAMSTORE:
                - 📍 Ubicación Exacta: Santo Domingo 240, Puente Alto (Interior "Sandros Collections").
                - ⏰ Horario: Lun-Vie 10:00 a 17:30 hrs | Sáb 10:00 a 14:30 hrs.
                - 📞 Contacto: +56 9 7207 9712 | glamstorechile2019@gmail.com
                - 🚚 Envíos: SOLO POR STARKEN (Por pagar).
                """

        logging.info(f"🧠 Intención Final: {intencion}")

        # 3. GENERACIÓN DE RESPUESTA (Prompt Búnker)
        if len(usuario['historial']) == 0:
            instruccion_saludo = '6. IMPORTANTE: Saluda con "Hola" o "Bienvenido/a".'
        else:
            instruccion_saludo = '6. IMPORTANTE: NO saludes de nuevo. NO digas "Hola" ni "Bienvenido". RESPONDE DIRECTO.'

        prompt_final = f"""
        Eres parte del equipo de GlamstoreChile. 
        TU MISIÓN: Ser una asesora de ventas EXPERTA y CONSULTIVA. 
        NO VENDAS DE INMEDIATO. TU OBJETIVO ES AYUDAR A ELEGIR, NO SOLO FACTURAR.
        SI PREGUNTAN QUÉ VENDEMOS: Menciona siempre Maquillaje, Perfumes, Skin Care, Capilar y Accesorios.
        
        ESTILO VISUAL: Usa emojis ✨💄💅 de forma moderada.
        LENGUAJE: Español estándar, neutro y profesional. "Nosotros". Cero adjetivos exagerados (no digas "increíble", "premium", "barato"). Solo datos y valores.
        
        === DATOS DEL SISTEMA (TU VERDAD ABSOLUTA) ===
        {contexto_data}
        
        === FLUJO DE VENTA OBLIGATORIO ===
        1. OMITIR LINK: JAMÁS generes, inventes ni muestres un link de pago. Eso lo hace el sistema automáticamente si el usuario confirma compra explícita. TÚ SOLO CHARLAS Y MUESTRAS PRODUCTOS.
        
        2. ANTE PREGUNTAS GENERALES ("Quiero perfumes", "Qué maquillaje tienes"):
           - SI EL SISTEMA TE DA UN RESUMEN DE PRECIOS: Lista los precios o rangos disponibles de forma natural (ej: "$2.000, $5.000 y $15.000").
           - NO MUESTRES LISTAS DE PRODUCTOS AUN. Espera que el usuario filtre por precio.
        
        3. ANTE FILTRO DE PRECIO ("Menos de 10.000", "Los de 5.000"):
           - Ahí recién muestra los productos que coinciden con su filtro.
           - Formato de lista: 
             * ✨ [Nombre] - $[Precio]
             🔗 [URL]
           - PREGUNTA DE CIERRE: "¿Te gustaría agregar alguno a tu pedido?".
        
        4. CIERRE DE VENTA:
           - Si el usuario dice "Quiero el X", "Agrega este": Confirma "Agregado".
           - SOLO cuando diga "Link" o "Pagar": Diles: "Perfecto. Te genero el link.".
        
        === OPCIONES DE COMPRA ===
        1. Página Web: www.glamstorechile.cl (24/7).
        2. Aquí mismo (Glambot): Link de pago seguro y rápido.
        3. Tienda Física: Santo Domingo 240, Puente Alto (Interior "Sandros Collections").
        
        === SOPORTE ===
        - Si preguntan DÓNDE/UBICACIÓN: Da la dirección exacta. NO inventes productos.
        - Si preguntan HORARIO/CUANDO:
           - Lun-Vie: 10:00 a 17:30 hrs
           - Sáb: 10:00 a 14:30 hrs
        - Si preguntan MAYORISTA: Da el mensaje de contacto directo del sistema: "Hola, para compras mayoristas por favor escríbenos directo al +56972079712 para brindarte una atención más personalizada."
        - ENVÍOS: Solo "STARKEN (Por pagar)".
        
        {instruccion_saludo}
        
        Chat previo:
        {historial_txt}
        User: "{texto}"
        Bot:
        """
        
        resp_final = model.generate_content(prompt_final).text.strip()
        # Limpieza final
        resp_final = resp_final.replace("Bot:", "").replace("GlamBot:", "").strip()
        
        # --- ALERTA DE LEAD MAYORISTA ---
        # Si el bot entregó los datos de contacto mayorista, avisamos al admin
        if "7207 9712" in resp_final or "glamstorechile2019" in resp_final:
            try:
                logging.info("🚨 DETECTADO LEAD MAYORISTA - Enviando alerta...")
                msg_alerta = f"🚨 *LEAD MAYORISTA DETECTADO*\nCliente: {nombre}\nTel: {numero}\nEstá interesado en comprar por mayor."
                # Número admin hardcodeado según solicitud
                enviar_whatsapp("56968123761", msg_alerta)
            except Exception as e:
                logging.error(f"Error enviando alerta mayorista: {e}")
        
        # Guardar en memoria
        usuario['historial'].append({"txt": texto, "resp": resp_final})
        
        enviar_whatsapp(numero, resp_final)
        
        # --- ENVIAR IMAGEN DE TODOS LOS PRODUCTOS (VISUAL) ---
        if intencion == "CATALOGO" and res["items"] and mostrar_imagenes:
            # Enviamos imagen de cada producto (Máximo 5 para no saturar)
            for p in res["items"][:5]:
                if p.get("image_url"):
                    logging.info(f"📸 Enviando imagen de: {p['title']}")
                    # Capturamos respuesta para guardar ID
                    caption_txt = f"📸 {p['title']} - ${p['price']:,.0f}".replace(",", ".")
                    resp_api = enviar_imagen_whatsapp(numero, p["image_url"], caption_txt)
                    
                    if resp_api:
                        try:
                            # Estructura típica: {'messaging_product': 'whatsapp', 'contacts': [...], 'messages': [{'id': 'wamid.HBg...'}]}
                            wamid = resp_api.get('messages', [{}])[0].get('id')
                            if wamid:
                                if 'msg_map' not in usuario:
                                    usuario['msg_map'] = {}
                                usuario['msg_map'][wamid] = p
                                logging.info(f"💾 Guardado contexto msg {wamid} -> Product {p['id']}")
                        except Exception as e:
                            logging.error(f"Error guardando contexto msg: {e}")


    except Exception as e:
        msg_error = str(e)
        logging.error(f"Error procesando IA: {msg_error}")
        
        # Manejo específico de error de cuota (429)
        if "429" in msg_error or "Resource exhausted" in msg_error:
            mensaje_espera = "¡Ups! Estoy recibiendo muchísimos mensajes ahora mismo 🤯. Dame unos segundos y pregúntame de nuevo, por favor ✨."
            enviar_whatsapp(numero, mensaje_espera)
        else:
            # Error genérico (opcionalmente no respondemos nada o un mensaje genérico)
            pass

def enviar_whatsapp(numero, texto):
    if not TOKEN_WHATSAPP:
        logging.warning("⚠️ No se envió mensaje porque no hay WHATSAPP_TOKEN")
        return

    url = "https://graph.facebook.com/v21.0/556942767500127/messages" 
    
    # ID de número de teléfono (Phone Number ID) - ACTUALIZADO
    PHONE_NUMBER_ID = os.environ.get("META_PHONE_ID", "939839529214459") 
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    
    headers = {
        "Authorization": f"Bearer {TOKEN_WHATSAPP}", 
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp", 
        "to": numero, 
        "type": "text", 
        "text": {"body": texto}
    }
    
    try:
        r = requests.post(url, headers=headers, json=data)
        if r.status_code not in [200, 201]:
            logging.error(f"Error enviando a WhatsApp: {r.text}")
            return None
        else:
            logging.info(f"📤 Respuesta enviada a {numero}")
            return r.json()
    except Exception as e:
        logging.error(f"Error request WhatsApp: {e}")
        return None

def enviar_imagen_whatsapp(numero, media_url, caption=""):
    """Envía una imagen por WhatsApp y retorna la respuesta API (para obtener ID)"""
    if not TOKEN_WHATSAPP: return None

    url = f"https://graph.facebook.com/v21.0/{os.environ.get('META_PHONE_ID', '939839529214459')}/messages"
    headers = {"Authorization": f"Bearer {TOKEN_WHATSAPP}", "Content-Type": "application/json"}
    
    data = {
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "image",
        "image": {"link": media_url, "caption": caption}
    }
    
    try:
        r = requests.post(url, headers=headers, json=data)
        if r.status_code not in [200, 201]:
            logging.error(f"Error enviando imagen: {r.text}")
            return None
        else:
            return r.json()
    except Exception as e:
        logging.error(f"Error env imagen: {e}")
        return None

def enviar_reporte_email(csv_content):
    """Envía el CSV por correo usando SMTP de Gmail."""
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASSWORD")
    destinatario = smtp_user # Nos lo enviamos a nosotros mismos

    if not smtp_user or not smtp_pass:
        logging.error("❌ Faltan credenciales SMTP (SMTP_USER / SMTP_PASSWORD)")
        return False

    try:
        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = destinatario
        msg['Subject'] = f"📊 Reporte DB GlamBot - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        body = "Adjunto encontrarás el reporte completo de la base de datos de productos."
        msg.attach(MIMEText(body, 'plain'))

        # Adjunto
        part = MIMEApplication(csv_content.encode('utf-8'), Name="productos.csv")
        part['Content-Disposition'] = 'attachment; filename="productos.csv"'
        msg.attach(part)

        # Enviar
        # Cambiamos a puerto 587 (STARTTLS) que es más amigable con firewalls cloud
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        
        logging.info(f"📧 Email enviado a {destinatario}")
        return True
    except Exception as e:
        logging.error(f"❌ Error enviando email: {e}")
        return False

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
