import os
import logging
from flask import Flask, request, jsonify
import requests
import google.generativeai as genai

# Configuración de logs
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# --- 1. CREDENCIALES ---
TOKEN_WHATSAPP = os.environ.get("WHATSAPP_TOKEN")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
API_KEY_GEMINI = os.environ.get("GEMINI_API_KEY")

# Credenciales de Shopify (Las nuevas)
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN")
SHOPIFY_URL = os.environ.get("SHOPIFY_URL") # Ejemplo: glamstore.myshopify.com

# --- 2. CONFIGURACIÓN CEREBRO (AUTO-PILOTO) ---
modelo_elegido = None
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    try:
        logging.info("🔍 DETECTANDO CEREBRO AUTOMÁTICAMENTE...")
        modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # Lista de preferencia (del más rápido al más seguro)
        favoritos = ['models/gemini-1.5-flash', 'models/gemini-1.5-flash-latest', 'models/gemini-flash-latest']
        
        for fav in favoritos:
            if fav in modelos:
                modelo_elegido = fav
                break
        if not modelo_elegido and modelos: modelo_elegido = modelos[0]
        
        logging.info(f"✅ CEREBRO CONECTADO: {modelo_elegido}")
        model = genai.GenerativeModel(modelo_elegido)
    except Exception as e:
        logging.error(f"⚠️ ERROR GEMINI: {e}")
        model = None

# --- 3. FUNCIÓN: BUSCAR EN SHOPIFY ---
def consultar_shopify(producto_busqueda):
    if not SHOPIFY_TOKEN or not SHOPIFY_URL:
        return "Error: Faltan credenciales de Shopify en Render."

    logging.info(f"🛒 BUSCANDO EN SHOPIFY: {producto_busqueda}")
    
    # Limpiamos la URL por si acaso
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("/", "")
    
    url = f"https://{tienda_url}/admin/api/2024-01/products.json"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json"
    }
    params = {
        "title": producto_busqueda,
        "status": "active",
        "limit": 3 # Traemos máximo 3 coincidencias
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            productos = response.json().get("products", [])
            if not productos:
                return "No encontré productos con ese nombre en la tienda."
            
            # Formateamos la info para que Gemini la entienda
            texto_info = "Encontré estos productos en el inventario:\n"
            for p in productos:
                titulo = p['title']
                # Sacamos precio y stock de la primera variante
                variante = p['variants'][0] 
                precio = variante['price']
                stock = variante['inventory_quantity']
                texto_info += f"- {titulo}: Precio ${precio} CLP | Stock: {stock} unidades\n"
            
            return texto_info
        else:
            logging.error(f"❌ ERROR SHOPIFY: {response.status_code} - {response.text}")
            return "Error consultando la base de datos de la tienda."
    except Exception as e:
        logging.error(f"❌ ERROR CONEXIÓN SHOPIFY: {e}")
        return "Error de conexión con la tienda."

# --- 4. RUTA RECIBIR MENSAJES ---
@app.route("/webhook", methods=["POST"])
def recibir_mensajes():
    try:
        body = request.get_json()
        entry = body["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        if "messages" in value:
            mensaje = value["messages"][0]
            numero = mensaje["from"]
            texto_usuario = mensaje["text"]["body"]
            
            logging.info(f"📩 MENSAJE DE {numero}: {texto_usuario}")

            if model:
                # PASO 1: Le preguntamos a Gemini si hay que buscar un producto
                # Usamos un prompt rápido para extraer el producto
                prompt_detector = f"""
                Analiza la frase del cliente: "{texto_usuario}"
                Si menciona un producto o categoría para comprar/cotizar, responde SOLO con el nombre clave del producto para buscarlo.
                Si es un saludo o no pide producto, responde: NULL
                """
                try:
                    res_detector = model.generate_content(prompt_detector)
                    termino_busqueda = res_detector.text.strip()
                except:
                    termino_busqueda = "NULL"
                
                info_tienda = ""
                # PASO 2: Si hay producto, vamos a Shopify
                if termino_busqueda != "NULL" and len(termino_busqueda) > 2:
                    info_tienda = consultar_shopify(termino_busqueda)
                    logging.info(f"📦 DATOS SHOPIFY: {info_tienda}")

                # PASO 3: Generamos la respuesta final
                prompt_final = f"""
                Eres el vendedor experto de 'Glamstore Chile'. 
                Actúa amable, chileno y servicial.
                
                PREGUNTA DEL CLIENTE: "{texto_usuario}"
                
                INFORMACIÓN DE INVENTARIO (Úsala si sirve):
                {info_tienda}
                
                Instrucciones:
                - Si hay info de inventario, DASELA al cliente (precios y stock).
                - Si no hay stock, ofrece ayuda.
                - Si es solo un saludo, saluda de vuelta.
                """
                
                res_final = model.generate_content(prompt_final)
                respuesta = res_final.text
                
                enviar_whatsapp(numero, respuesta)

            else:
                enviar_whatsapp(numero, "Estoy reiniciando mis sistemas... intenta en 1 minuto.")

        return jsonify({"status": "ok"}), 200
    except:
        return jsonify({"status": "ignored"}), 200

# --- 5. VERIFICACIÓN Y ENVÍO ---
@app.route("/webhook", methods=["GET"])
def verificar_token():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN: return challenge, 200
    return "Error", 403

def enviar_whatsapp(numero, texto):
    url = "https://graph.facebook.com/v21.0/939839529214459/messages"
    headers = { "Authorization": f"Bearer {TOKEN_WHATSAPP}", "Content-Type": "application/json" }
    data = { "messaging_product": "whatsapp", "to": numero, "type": "text", "text": {"body": texto} }
    requests.post(url, headers=headers, json=data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
