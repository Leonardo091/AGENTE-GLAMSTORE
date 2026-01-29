import os
import logging
import time
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import google.generativeai as genai
import json
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
            
            # Gestión de memoria
            if numero not in MEMORIA_USUARIOS:
                MEMORIA_USUARIOS[numero] = {'historial': deque(maxlen=6), 'ultimo_msg': time.time()}
            usuario = MEMORIA_USUARIOS[numero]
            
            historial_txt = "\n".join([f"User: {h['txt']}\nBot: {h['resp']}" for h in usuario['historial']])

            if model:
                # --- AUTO-SYNC: GARANTIZAR DATOS FRESCOS ---
                # Si el cerebro está vacío O la información es muy vieja (>20min), recargamos
                necesita_recarga = False
                msg_reason = ""
                
                if db.total_items == 0:
                    necesita_recarga = True
                    msg_reason = "Cerebro vacío"
                elif db.last_sync and (datetime.now() - db.last_sync) > timedelta(minutes=20):
                    necesita_recarga = True
                    msg_reason = "Datos antiguos"
                
                if necesita_recarga:
                    logging.info(f"🧠 {msg_reason} al recibir mensaje. Ejecutando sincronización síncrona...")
                    db._actualizar_tabla_maestra()

                procesar_inteligencia_artificial(numero, nombre, texto, historial_txt, usuario)
            
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logging.error(f"🔥 ERROR: {e}")
        return jsonify({"status": "error"}), 500



def procesar_inteligencia_artificial(numero, nombre, texto, historial_txt, usuario):
    try:
        # --- ESTRATEGIA RETRIEVAL-FIRST ---
        # 1. Buscamos PRIMERO en la base de datos (prioridad a productos)
        logging.info(f"🔎 Buscando productos para: '{texto}'...")
        res = db.buscar_contextual(texto)
        
        contexto_data = ""
        link_pago = None
        intencion = None # Se define dinámicamente

        if res["tipo"] != "VACIO":
            # ¡HAY PRODUCTOS! -> Forzamos intención CATALOGO
            logging.info(f"✅ Productos encontrados ({len(res['items'])}). Forzando intención CATALOGO.")
            intencion = "CATALOGO"
            
            # GUARDAR CONTEXTO PARA COMPRA RÁPIDA ("Quiero estos")
            usuario['contexto_productos'] = res['items']
            
            if res["tipo"] == "RECOMENDACION_REAL":
                lista = "\n".join([f"- {p['title']} (${p['price']:,.0f})" for p in res["items"]])
                contexto_data = f"INVENTARIO RECOMENDADO:\n{lista}"
            else: # EXACTO
                lista = "\n".join([f"- {p['title']} (${p['price']:,.0f})" for p in res["items"]])
                contexto_data = f"PRODUCTO ENCONTRADO:\n{lista}"

            # Verificamos si quiere comprar explícitamente
            keywords_compra = ["comprar", "quiero", "llevo", "dame", "precio", "cuanto", "me interesa"]
            
            # Si detectamos intención de compra o pregunta de precio sobre estos productos
            if any(k in texto.lower() for k in keywords_compra):
                # INTELIGENCIA: SELECCIONAR QUÉ PRODUCTO QUIERE
                # Si hay varios productos, preguntamos a Gemini cuál elegir
                items_a_checkout = res['items']
                
                if len(res['items']) > 1:
                    try:
                        prompt_selector = f"""
                        Eres un experto en entender pedidos de compra.
                        El usuario dijo: "{texto}"
                        
                        Productos disponibles en pantalla:
                        {json.dumps([{'id': p['id'], 'title': p['title']} for p in res['items']], ensure_ascii=False)}
                        
                        Tu tarea: Identifica los ID de los productos que el usuario quiere comprar.
                        - Si quiere todo, responde: ["TODOS"]
                        - Si quiere todo, responde: ["TODOS"]
                        - Si quiere uno o más específicos, responde una lista JSON con sus IDs: [12345, 67890]
                        - IMPORTANTE: Si pide CANTIDAD (ej: "quiero 2 del primero"), REPITE el ID en la lista tantas veces como pida. Ej: [12345, 12345].
                        - Si solo está preguntando precios y no quiere link aún, responde: []
                        - Si no se entiende, responde: []
                        
                        Responde SOLO EL JSON.
                        """
                        # Usamos el modelo para decidir
                        selector_resp = model.generate_content(prompt_selector).text.strip()
                        # Limpiar markdown si lo pone
                        selector_resp = selector_resp.replace("```json", "").replace("```", "").strip()
                        
                        seleccion = json.loads(selector_resp)
                        
                        if "TODOS" not in seleccion and seleccion:
                            # Filtrar solo los seleccionados
                            items_a_checkout = [p for p in res['items'] if p['id'] in seleccion]
                            
                    except Exception as e:
                        logging.error(f"Error en selector inteligente: {e}")
                        # Si falla, por defecto NO generamos link masivo, mejor dejar que el usuario especifique o
                        # usar el comportamiento anterior (pero el usuario reportó que era molesto).
                        # Vamos a asumir que "TODOS" es el fallback si falla la IA, pero lo ideal es ser precavido.
                        items_a_checkout = res['items'] 

                # Generamos link SOLO con los seleccionados
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
                
                # (Aquí podríamos llamar al LLMSelector igual que arriba si quisiéramos ser muy precisos en "dame el segundo")
                # Por simplicidad y ahorro de tokens en render, si dice "quiero esos", asumimos todos SALVO que especifique.
                # Si dice "quiero el perfume" y había 5 cosas, vendría bien el selector.
                # Implementemos el selector simplificado aquí también:
                
                try:
                    prompt_selector = f"""
                    Usuario: "{texto}"
                    Items en vista: {json.dumps([{'id': p['id'], 'title': p['title']} for p in items_ctx], ensure_ascii=False)}
                    Devuelve JSON con IDs a comprar o ["TODOS"].
                    """
                    selector_resp = model.generate_content(prompt_selector).text.strip().replace("```json", "").replace("```", "").strip()
                    seleccion = json.loads(selector_resp)
                    
                    if "TODOS" not in seleccion and seleccion:
                        items_a_checkout = [p for p in items_ctx if p['id'] in seleccion]
                except:
                    pass # Fallback a todos
                
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
                - ⏰ Horario: Lun-Vie 10:00 a 18:00 hrs | Sáb 10:00 a 15:00 hrs.
                - 📞 Contacto: +56 9 7207 9712 | glamstorechile2019@gmail.com
                - 🚚 Envíos: A todo Chile (Starken/Chilexpress).
                """

        logging.info(f"🧠 Intención Final: {intencion}")

        # 3. GENERACIÓN DE RESPUESTA (Prompt Búnker)
        # 3. GENERACIÓN DE RESPUESTA (Prompt Búnker)
        instruccion_saludo = ""
        # Solo saludamos si el historial es muy corto (inicio de conversación)
        instruccion_saludo = '6. IMPORTANTE: Usa lenguaje de género NEUTRO. Di "Hola" o "Bienvenid@" (con @).'

        prompt_final = f"""
        Eres parte del equipo de GlamstoreChile (NO digas que eres un bot/IA).
        Tu tono es: Amable, profesional y útil.
        AUDIENCIA: Atendemos a todo público (Hombres, Mujeres, Niños). No asumas género femenino por defecto.
        
        === CÓMO COMPRAR (TUS OPCIONES) ===
        1. Web: www.glamstorechile.cl
        2. Local Físico: Santo Domingo 240, Puente Alto (Interior "Sandros Collections"). ¡Sí se puede comprar ahí!
        3. Aquí en el Chat: Tú generas los links de pago directo.
        4. Mayorista: (Solo dar contacto si lo piden explícitamente).
        
        === DATOS DEL SISTEMA (TU VERDAD ABSOLUTA) ===
        {contexto_data}
        
        === INSTRUCCIONES ===
        1. Responde al cliente {nombre} basándote SOLO en los "DATOS DEL SISTEMA".
        2. Si HAY productos: ¡LÍSTALOS DIRECTAMENTE! Di "Tengo estos para ti:" y pon la lista. ⛔ PROHIBIDO PREGUNTAR "¿Te gustaría verlos?". ¡MUÉSTRALOS!
        3. Si NO hay productos: SOLO di que no hay stock SI el usuario preguntó por un producto. Si solo saluda o conversa, NO hables de stock.
        4. Si hay LINK DE PAGO: Entrégalo diciendo "Aquí tienes tu link directo:".
        5. Sé concisa (máximo 3-4 líneas).
        {instruccion_saludo}
        7. ENVÍOS: Solo menciona "STARKEN". Si preguntan por otros, di que solo trabajamos con Starken por seguridad y rapidez.
        8. CONTACTO: Si piden teléfono/dirección SOLO entrégalos si su intención es "COMPRA MAYORISTA". Si es minorista, di que todo es 100% online y autogestionado por aquí.
        9. STOCK: Si te preguntan por algo que no está en la lista que ves, di que no queda stock. No inventes.
        
        Chat previo:
        {historial_txt}
        User: "{texto}"
        Bot:
        """
        
        resp_final = model.generate_content(prompt_final).text.strip()
        # Limpieza final
        resp_final = resp_final.replace("Bot:", "").replace("GlamBot:", "").strip()
        
        # Guardar en memoria
        usuario['historial'].append({"txt": texto, "resp": resp_final})
        
        enviar_whatsapp(numero, resp_final)

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
        else:
            logging.info(f"📤 Respuesta enviada a {numero}")
    except Exception as e:
        logging.error(f"Error request WhatsApp: {e}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
