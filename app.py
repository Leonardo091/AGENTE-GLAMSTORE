import os
import logging
from flask import Flask, request, jsonify
import requests
import google.generativeai as genai
from collections import deque

# Configuración de logs
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# --- 1. CREDENCIALES ---
TOKEN_WHATSAPP = os.environ.get("WHATSAPP_TOKEN")
VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN")
API_KEY_GEMINI = os.environ.get("GEMINI_API_KEY")
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN")
SHOPIFY_URL = os.environ.get("SHOPIFY_URL")

# --- MEMORIA DE ELEFANTE ---
# Cada número de teléfono tiene su propio historial. NO SE MEZCLAN.
# maxlen=12 significa que recuerda los últimos 12 mensajes (bastante charla).
MEMORIA_CHATS = {} 

MEMORIA_TIENDA = "Cargando..."

# --- 2. CARGA DE DATOS SHOPIFY ---
def cargar_informacion_tienda():
    if not SHOPIFY_TOKEN or not SHOPIFY_URL: return "⚠️ Faltan credenciales."
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("http://", "").replace("/", "")
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    info = "DATOS GLAMSTORE:\n"
    try:
        res = requests.get(f"https://{tienda_url}/admin/api/2024-01/shop.json", headers=headers)
        if res.status_code == 200:
            shop = res.json().get('shop', {})
            info += f"Web: {shop.get('domain')}\nEmail: {shop.get('email')}\nMoneda: {shop.get('currency')}\n"
            logging.info(f"✅ CONECTADO A SHOPIFY: {tienda_url}")
        else:
            logging.error(f"❌ ERROR SHOPIFY: {res.status_code}")
            info += "(Error conexión tienda)\n"
    except Exception as e:
        logging.error(f"❌ ERROR CRÍTICO: {e}")
    return info

MEMORIA_TIENDA = cargar_informacion_tienda()

# --- 3. CONFIGURACIÓN GEMINI (MODO LITE) ---
model = None
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    try:
        logging.info("🚀 INICIANDO CEREBRO PERSONALIZADO...")
        model = genai.GenerativeModel('gemini-2.0-flash-lite')
    except:
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
        except:
            model = None

# --- 4. FUNCIONES DE TIENDA ---
def consultar_productos(busqueda):
    if not SHOPIFY_TOKEN: return "Error credenciales."
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("/", "")
    url = f"https://{tienda_url}/admin/api/2024-01/products.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    params = {"title": busqueda, "status": "active", "limit": 5}
    if busqueda.lower() in ["perfume", "perfumes", "arabe", "arabes", "catalogo"]:
         params = {"status": "active", "limit": 5}

    try:
        r = requests.get(url, headers=headers, params=params)
        if r.status_code == 200:
            prods = r.json().get("products", [])
            if not prods: return "No encontré productos exactos, pero tenemos más en la web."
            
            txt = "📦 OPCIONES DISPONIBLES:\n"
            for p in prods:
                v = p['variants'][0]
                price = int(float(v['price']))
                txt += f"🔹 {p['title']} a ${price:,.0f}\n"
            return txt
    except: return "Error buscando."
    return ""

def crear_link_pago(nombre_producto):
    if not SHOPIFY_TOKEN: return "Error credenciales."
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("/", "")
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}

    url_search = f"https://{tienda_url}/admin/api/2024-01/products.json"
    params = {"title": nombre_producto, "status": "active", "limit": 1}
    
    try:
        r_search = requests.get(url_search, headers=headers, params=params)
        products = r_search.json().get("products", [])
        
        if not products: return f"No encontré '{nombre_producto}' para generar link."
            
        variant_id = products[0]['variants'][0]['id']
        product_title = products[0]['title']
        price = int(float(products[0]['variants'][0]['price']))

        url_create = f"https://{tienda_url}/admin/api/2024-01/draft_orders.json"
        payload = {
            "draft_order": {
                "line_items": [{"variant_id": variant_id, "quantity": 1}],
                "use_customer_default_address": False
            }
        }
        
        r_create = requests.post(url_create, headers=headers, json=payload)
        
        if r_create.status_code == 201:
            data = r_create.json().get("draft_order", {})
            url_pago = data.get("invoice_url")
            return f"✅ ¡Listo! Aquí está el link para el {product_title} (${price:,.0f}):\n👉 {url_pago}"
        else:
            return "Error al crear link."

    except Exception as e:
        return f"Error técnico: {e}"

# --- 5. WEBHOOK PERSONALIZADO ---
@app.route("/webhook", methods=["POST"])
def recibir_mensajes():
    try:
        body = request.get_json()
        entry = body["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        if "messages" in value:
            # DATOS DEL CLIENTE
            mensaje = value["messages"][0]
            numero = mensaje["from"]
            texto = mensaje["text"]["body"]
            
            # INTENTAMOS SACAR EL NOMBRE DEL PERFIL DE WHATSAPP
            nombre_cliente = "Cliente"
            try:
                contactos = value.get("contacts", [])
                if contactos:
                    nombre_cliente = contactos[0]["profile"]["name"]
            except:
                nombre_cliente = "Cliente"

            logging.info(f"📩 MENSAJE DE {nombre_cliente} ({numero}): {texto}")

            # 1. GESTIÓN DE MEMORIA (AISLADA POR NÚMERO)
            if numero not in MEMORIA_CHATS:
                MEMORIA_CHATS[numero] = deque(maxlen=12) # Recuerda los últimos 12 mensajes
            
            historial = list(MEMORIA_CHATS[numero])
            texto_historial = "\n".join([f"- {h['rol']}: {h['txt']}" for h in historial])

            if model:
                # 2. DETECCIÓN INTELIGENTE
                prompt_det = f"""
                HISTORIAL CON {nombre_cliente}:
                {texto_historial}
                
                MENSAJE ACTUAL: "{texto}"
                
                TAREA:
                1. Identifica qué quiere {nombre_cliente}.
                2. Si dice "quiero ese", mira el historial para saber cuál es "ese".
                
                RESPONDE SOLO:
                - VENDER: [Producto]
                - BUSCAR: [Producto]
                - CHARLA
                """
                
                try:
                    decision_raw = model.generate_content(prompt_det).text.strip()
                    decision = decision_raw.split("\n")[0]
                    logging.info(f"🧠 INTENCIÓN ({nombre_cliente}): {decision}")
                except: decision = "CHARLA"
                
                info_extra = ""
                producto_buscado = ""
                
                if "VENDER:" in decision:
                    producto_buscado = decision.split("VENDER:")[1].strip()
                    info_extra = crear_link_pago(producto_buscado)
                elif "BUSCAR:" in decision:
                    producto_buscado = decision.split("BUSCAR:")[1].strip()
                    info_extra = consultar_productos(producto_buscado)
                else:
                    info_extra = MEMORIA_TIENDA

                # 3. RESPUESTA PERSONALIZADA
                prompt_final = f"""
                Eres "GlamBot", asistente de Glamstore Chile.
                Estás hablando con: {nombre_cliente}.
                
                HISTORIAL PREVIO:
                {texto_historial}
                
                SITUACIÓN ACTUAL:
                {nombre_cliente} dice: "{texto}"
                Info Sistema: {info_extra}
                
                INSTRUCCIONES CLAVE:
                1. PERSONALIZA: Usa el nombre "{nombre_cliente}" si es natural hacerlo.
                2. MEMORIA: Si antes hablaron de un perfume (ej: Yara), y ahora pregunta "¿cuánto vale?", asume que habla del Yara.
                3. NO REPITAS SALUDOS: Si ya se saludaron en el historial, responde directo.
                4. VENTA: Si hay link de pago, entrégalo con entusiasmo.
                """
                
                try:
                    res = model.generate_content(prompt_final)
                    respuesta = res.text
                    
                    # Guardamos en la memoria DE ESTE NÚMERO
                    MEMORIA_CHATS[numero].append({"rol": nombre_cliente, "txt": texto})
                    MEMORIA_CHATS[numero].append({"rol": "Bot", "txt": respuesta})
                    
                    enviar_whatsapp(numero, respuesta)
                except Exception as e:
                    logging.error(f"❌ ERROR RESPUESTA: {e}")
                    enviar_whatsapp(numero, "Dame un segundito...")

        return jsonify({"status": "ok"}), 200
    except: return jsonify({"status": "ok"}), 200

# VERIFICACIÓN
@app.route("/webhook", methods=["GET"])
def verificar():
    verify_token_env = os.environ.get("META_VERIFY_TOKEN")
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    if mode == "subscribe" and token == verify_token_env: return request.args.get("hub.challenge"), 200
    return "Error", 403

def enviar_whatsapp(num, txt):
    url = "https://graph.facebook.com/v21.0/939839529214459/messages"
    headers = {"Authorization": f"Bearer {TOKEN_WHATSAPP}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": num, "type": "text", "text": {"body": txt}}
    requests.post(url, headers=headers, json=data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
