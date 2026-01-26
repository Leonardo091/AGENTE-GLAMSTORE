import os
import logging
from flask import Flask, request, jsonify
import requests
import google.generativeai as genai

# Configuración de logs
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# --- 1. CREDENCIALES (ADAPTADAS A TUS VARIABLES DE RENDER) ---
# Usamos los nombres exactos que tienes en tu imagen
TOKEN_WHATSAPP = os.environ.get("WHATSAPP_TOKEN")
# OJO: Aquí cambié el código para que lea TU variable
VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN") 
API_KEY_GEMINI = os.environ.get("GEMINI_API_KEY")
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN")
SHOPIFY_URL = os.environ.get("SHOPIFY_URL")

MEMORIA_TIENDA = "Cargando..."

# --- 2. CARGA DE DATOS INICIAL ---
def cargar_informacion_tienda():
    if not SHOPIFY_TOKEN or not SHOPIFY_URL: return "⚠️ Faltan credenciales en Render."
    
    # Limpiamos la URL para que quede solo el dominio (ej: tienda.myshopify.com)
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("http://", "").replace("/", "")
    
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    info = "DATOS GLAMSTORE:\n"
    
    try:
        # Probamos conexión leyendo datos de la tienda
        res = requests.get(f"https://{tienda_url}/admin/api/2024-01/shop.json", headers=headers)
        
        if res.status_code == 200:
            shop = res.json().get('shop', {})
            info += f"Web: {shop.get('domain')}\nEmail: {shop.get('email')}\nMoneda: {shop.get('currency')}\n"
            logging.info("✅ CONEXIÓN EXITOSA CON SHOPIFY")
        else:
            logging.error(f"❌ ERROR CONECTANDO A SHOPIFY: {res.status_code}")
            logging.error(f"MIRA ESTO: {res.text}")
            info += "(Error de conexión con la tienda, revisa la URL en Render)\n"
            
    except Exception as e:
        logging.error(f"❌ ERROR CRÍTICO: {e}")
        pass
    return info

# Ejecutamos la carga al iniciar
MEMORIA_TIENDA = cargar_informacion_tienda()

# --- 3. CONFIGURACIÓN GEMINI ---
model = None
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    try:
        # Buscamos modelo disponible
        modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        favs = ['models/gemini-1.5-flash', 'models/gemini-pro', 'models/gemini-1.5-pro-latest']
        elegido = next((f for f in favs if f in modelos), modelos[0] if modelos else None)
        model = genai.GenerativeModel(elegido)
        logging.info(f"🧠 CEREBRO ACTIVO: {elegido}")
    except:
        logging.error("❌ NO SE PUDO INICIAR GEMINI")
        model = None

# --- 4. FUNCIONES DE TIENDA (Búsqueda y Pedidos) ---
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

    # 1. Buscar producto
    url_search = f"https://{tienda_url}/admin/api/2024-01/products.json"
    params = {"title": nombre_producto, "status": "active", "limit": 1}
    
    try:
        r_search = requests.get(url_search, headers=headers, params=params)
        products = r_search.json().get("products", [])
        
        if not products: return f"No encontré el producto '{nombre_producto}' para generar el link."
            
        variant_id = products[0]['variants'][0]['id']
        product_title = products[0]['title']

        # 2. Crear Draft Order
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
            
            return f"✅ PEDIDO {numero} GENERADO\nProducto: {product_title}\nTotal: ${total:,.0f}\n\nLINK PAGO: {url_pago}"
        else:
            return f"Error creando pedido: {r_create.status_code}"

    except Exception as e:
        return f"Error técnico: {e}"

# --- 5. WEBHOOK Y LÓGICA ---
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
                except: decision = "NULL"
                
                info_extra = ""
                if decision.startswith("VENDER:"):
                    info_extra = crear_link_pago(decision.replace("VENDER:", "").strip())
                elif decision.startswith("BUSCAR:"):
                    info_extra = consultar_productos(decision.replace("BUSCAR:", "").strip())
                else:
                    info_extra = MEMORIA_TIENDA

                # Respuesta final
                prompt_final = f"""
                Eres el equipo de Glamstore Chile.
                INFO DEL SISTEMA: {info_extra}
                CLIENTE DIJO: "{texto}"
                
                Instrucciones:
                - Si hay un LINK DE PAGO, entrégalo claro.
                - Si es info de producto, dásela.
                - Sé amable y breve.
                """
                res = model.generate_content(prompt_final)
                enviar_whatsapp(numero, res.text)

        return jsonify({"status": "ok"}), 200
    except: return jsonify({"status": "ok"}), 200

# VERIFICACIÓN DE TOKEN (Usando META_VERIFY_TOKEN)
@app.route("/webhook", methods=["GET"])
def verificar():
    # AQUÍ ES DONDE LEEMOS TU VARIABLE EXACTA
    verify_token_env = os.environ.get("META_VERIFY_TOKEN")
    
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    
    if mode == "subscribe" and token == verify_token_env:
        return challenge, 200
    return "Error verificación", 403

def enviar_whatsapp(num, txt):
    url = "https://graph.facebook.com/v21.0/939839529214459/messages"
    headers = {"Authorization": f"Bearer {TOKEN_WHATSAPP}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": num, "type": "text", "text": {"body": txt}}
    requests.post(url, headers=headers, json=data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
