import os
import logging
from flask import Flask, request, jsonify
import requests
import google.generativeai as genai

# Configuración de logs
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# --- 1. CREDENCIALES (Se cargan desde Render) ---
TOKEN_WHATSAPP = os.environ.get("WHATSAPP_TOKEN")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
API_KEY_GEMINI = os.environ.get("GEMINI_API_KEY")
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN")
SHOPIFY_URL = os.environ.get("SHOPIFY_URL")

# --- 2. CONFIGURACIÓN CEREBRO (AUTO-PILOTO) ---
# Este bloque busca el mejor modelo disponible en tu cuenta automáticamente
modelo_elegido = None
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    try:
        logging.info("🔍 DETECTANDO CEREBRO AUTOMÁTICAMENTE...")
        modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # Preferencias: Flash (rápido) -> Pro (potente)
        favoritos = ['models/gemini-1.5-flash', 'models/gemini-1.5-flash-latest', 'models/gemini-flash-latest', 'models/gemini-pro']
        
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
        return "Error: Faltan credenciales de Shopify."

    logging.info(f"🛒 BUSCANDO EN SHOPIFY: {producto_busqueda}")
    
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("/", "")
    url = f"https://{tienda_url}/admin/api/2024-01/products.json"
    
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json"
    }
    
    # Aumentamos el límite a 5 para dar más opciones
    params = {
        "title": producto_busqueda,
        "status": "active",
        "limit": 5 
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            productos = response.json().get("products", [])
            if not productos:
                return "No se encontraron coincidencias exactas en el catálogo."
            
            # Formateamos la info para que Gemini la lea clarito
            texto_info = "📦 INVENTARIO ENCONTRADO:\n"
            for p in productos:
                titulo = p['title']
                variante = p['variants'][0] 
                precio = variante['price']
                stock = variante['inventory_quantity']
                # Le pasamos el ID o URL si quisieras después, por ahora solo info básica
                texto_info += f"- {titulo} | Precio: ${precio} CLP | Disponibles: {stock}\n"
            
            return texto_info
        else:
            return "Error consultando la base de datos."
    except Exception as e:
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
                # PASO 1: DETECTAR INTENCIÓN Y TÉRMINO DE BÚSQUEDA
                # Aquí le enseñamos a entender "similares"
                prompt_detector = f"""
                Analiza el mensaje del cliente: "{texto_usuario}"
                
                Tu tarea es extraer UNA palabra clave para buscar en el inventario de Shopify.
                1. Si pide un producto específico (ej: "Sauvage"), usa ese nombre.
                2. Si pide "algo como X" o "similar a X", usa "X" como búsqueda (para encontrar inspiraciones).
                3. Si pide una familia (ej: "algo dulce", "árabe"), usa esa palabra clave.
                4. Si es solo saludo o charla, responde: NULL
                
                Responde SOLO con la palabra clave.
                """
                try:
                    res_detector = model.generate_content(prompt_detector)
                    termino_busqueda = res_detector.text.strip()
                except:
                    termino_busqueda = "NULL"
                
                info_tienda = ""
                # PASO 2: BUSCAR EN SHOPIFY (Si hay término)
                if termino_busqueda != "NULL" and len(termino_busqueda) > 2:
                    info_tienda = consultar_shopify(termino_busqueda)
                    logging.info(f"📦 INFO OBTENIDA: {info_tienda}")

                # PASO 3: GENERAR RESPUESTA FINAL (NUEVA PERSONALIDAD)
                prompt_final = f"""
                Actúa como el EQUIPO DE ATENCIÓN AL CLIENTE de "Glamstore Chile".
                Tu tono debe ser: Profesional, amable, correcto y servicial.
                
                INSTRUCCIONES CLAVE:
                - Habla en plural ("Nosotros", "Le recomendamos").
                - NO uses jergas chilenas (como "cachai", "bacán"), habla un español neutro y educado.
                - SIEMPRE entiende si el usuario usa jergas, pero tú responde formalmente.
                - Sé conciso y directo.
                
                CONTEXTO:
                Mensaje del Cliente: "{texto_usuario}"
                Datos del Inventario (Shopify):
                {info_tienda}
                
                DIRECTRICES DE RESPUESTA:
                - Si hay inventario: Ofrece los productos con sus precios exactos.
                - Si no hay stock o no se encontró: Ofrece buscar otra cosa amablemente.
                - Si es un saludo: Preséntate como el equipo de Glamstore.
                """
                
                res_final = model.generate_content(prompt_final)
                respuesta = res_final.text
                
                enviar_whatsapp(numero, respuesta)

            else:
                enviar_whatsapp(numero, "Estamos actualizando nuestros sistemas. Por favor intente en un momento.")

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
