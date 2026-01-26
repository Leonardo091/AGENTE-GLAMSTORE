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
VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN")
API_KEY_GEMINI = os.environ.get("GEMINI_API_KEY")
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN")
SHOPIFY_URL = os.environ.get("SHOPIFY_URL")

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

# --- 3. CONFIGURACIÓN GEMINI (MANUAL Y FORZADA) ---
model = None
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    try:
        # ¡AQUÍ ESTÁ EL CAMBIO!
        # Nada de buscar listas. Le ponemos el nombre EXACTO del modelo gratuito robusto.
        logging.info("🔒 FORZANDO MODELO: gemini-1.5-flash")
        model = genai.GenerativeModel('gemini-1.5-flash')
        
    except Exception as e:
        logging.error(f"❌ ERROR GEMINI: {e}")
        model = None

# --- 4. FUNCIONES DE TIENDA ---
def consultar_productos(busqueda):
    if not SHOPIFY_TOKEN: return "Error credenciales."
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("/", "")
    url = f"https://{tienda_url}/admin/api/2024-01/products.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    params = {"title": busqueda, "status": "active", "limit": 4}
    try:
        r = requests.get(url, headers=headers, params=params)
        if r.status_code == 200:
            prods = r.json().get("products", [])
            if not prods: return "No encontré productos con ese nombre."
            txt = "📦 DISPONIBLE:\n"
            for p in prods:
                v = p['variants'][0]
                txt += f"- {p['title']} | ${v['price']}\n"
            return txt
    except: return "Error buscando."
    return ""

def crear_link_pago(nombre_producto):
    if not SHOPIFY_TOKEN: return "Error de credenciales."
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("/", "")
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}

    url_search = f"https://{tienda_url}/admin/api/2024-01/products.json"
    params = {"title": nombre_producto, "status": "active", "limit": 1}
    
    try:
        r_search = requests.get(url_search, headers=headers, params=params)
        products = r_search.json().get("products", [])
        
        if not products: return f"No encontré '{nombre_producto}' para crear el pedido."
            
        variant_id = products[0]['variants'][0]['id']
        product_title = products[0]['title']

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
            numero = data.get("name", "#Draft")
            url_pago = data.get("invoice_url")
            total = float(data.get("total_price", 0))
            return f"✅ PEDIDO {numero} GENERADO\nProducto: {product_title}\nTotal: ${total:,.0f}\nLINK PAGO: {url_pago}"
        else:
            return f"Error creando pedido: {r_create.status_code}"

    except Exception as e:
        return f"Error técnico: {e}"

# --- 5. WEBHOOK ---
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
            texto = mensaje["text"]["body"]
            
            logging.info(f"📩 MENSAJE: {texto}")

            if model:
                # Detector de intención
                prompt_det = f"""
                Analiza: "{texto}"
                Responde SOLO:
                - VENDER: [Producto] (Si quiere comprar/link/pedido)
                - BUSCAR: [Producto] (Si pide precio/info)
                - NULL (Saludos/Otros)
                """
                try:
                    decision = model.generate_content(prompt_det).text.strip()
                    logging.info(f"🧠 INTENCIÓN: {decision}")
                except: decision = "NULL"
                
                info_extra = ""
                if decision.startswith("VENDER:"):
                    info_extra = crear_link_pago(decision.replace("VENDER:", "").strip())
                elif decision.startswith("BUSCAR:"):
                    info_extra = consultar_productos(decision.replace("BUSCAR:", "").strip())
                else:
                    info_extra = MEMORIA_TIENDA

                prompt_final = f"""
                Eres el equipo de Glamstore Chile.
                INFO DEL SISTEMA: {info_extra}
                CLIENTE DIJO: "{texto}"
                
                Instrucciones:
                - Si hay un LINK DE PAGO, entrégalo claro.
                - Si es info de producto, dásela.
                - Sé amable y breve.
                """
                
                try:
                    res = model.generate_content(prompt_final)
                    enviar_whatsapp(numero, res.text)
                except Exception as e:
                    logging.error(f"❌ ERROR GEMINI RESPUESTA: {e}")
                    enviar_whatsapp(numero, "Estoy reiniciando mis neuronas. Dame 1 minuto.")

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
