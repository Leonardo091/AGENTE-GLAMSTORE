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

# --- 3. CONFIGURACIÓN GEMINI (MODO LITE) ---
model = None
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    try:
        # Usamos la estrategia Lite que vimos que es ilimitada
        logging.info("🚀 INICIANDO CEREBRO...")
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
    
    # Truco: Si busca "perfume" (muy genérico), traemos cualquiera. 
    # Si es específico, usamos el término.
    params = {"title": busqueda, "status": "active", "limit": 5}
    if busqueda.lower() in ["perfume", "perfumes", "arabe", "arabes"]:
         # Si es muy genérico, quitamos el filtro de título para traer los últimos agregados
         params = {"status": "active", "limit": 5}

    try:
        r = requests.get(url, headers=headers, params=params)
        if r.status_code == 200:
            prods = r.json().get("products", [])
            if not prods: return "No encontré productos exactos, pero tenemos muchas opciones en la web."
            
            txt = "📦 ESTO ENCONTRÉ EN BODEGA:\n"
            for p in prods:
                v = p['variants'][0]
                price = int(float(v['price']))
                txt += f"▪️ {p['title']} ➡️ ${price:,.0f}\n"
            return txt
    except: return "Error buscando en bodega."
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
        
        if not products: return f"No encontré '{nombre_producto}' para crear el pedido."
            
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
            numero = data.get("name", "#Draft")
            url_pago = data.get("invoice_url")
            return f"✅ PEDIDO {numero} LISTO\n💎 {product_title}\n💰 Valor: ${price:,.0f}\n👇 PAGAR AQUÍ:\n{url_pago}"
        else:
            return "Error al generar el link."

    except Exception as e:
        return f"Error técnico: {e}"

# --- 5. WEBHOOK INTELIGENTE ---
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
                # 1. DETECTOR MEJORADO (CORRIGE ORTOGRAFÍA)
                prompt_det = f"""
                Analiza el mensaje: "{texto}"
                
                Tu tarea es identificar qué busca el usuario en Shopify.
                
                REGLAS:
                1. Si escribe mal una marca, CORRÍGELA (Ej: "Mason" -> "Maison").
                2. Si dice "muestrame uno" o "cuales tienes", asume que quiere ver "perfumes".
                3. Si pide comprar, usa VENDER.
                4. Si pide ver/precio/info, usa BUSCAR.
                
                Responde SOLO el formato: ACCIÓN: PRODUCTO
                Ejemplos:
                - "tienes mason?" -> BUSCAR: Maison Alhambra
                - "quiero el asad" -> VENDER: Asad
                - "cuales hay?" -> BUSCAR: perfumes
                - "hola" -> NULL
                """
                
                try:
                    decision_raw = model.generate_content(prompt_det).text.strip()
                    # Limpieza extra por si Gemini se pone hablador
                    decision = decision_raw.split("\n")[0] 
                    logging.info(f"🧠 INTENCIÓN CORREGIDA: {decision}")
                except: decision = "NULL"
                
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

                # 2. RESPUESTA DE VENDEDOR (NO DE PÁGINA WEB)
                prompt_final = f"""
                Eres el vendedor estrella de Glamstore Chile.
                
                CONTEXTO:
                Cliente dijo: "{texto}"
                Intención detectada: "{decision}"
                Información del sistema:
                {info_extra}
                
                INSTRUCCIONES:
                1. Si el sistema trajo una lista de productos ("ESTO ENCONTRÉ..."), ¡NOMBRALOS!
                   No digas "revisa la web". Di: "Mira, tengo el X, el Y y el Z".
                2. Si el cliente buscó algo mal escrito (ej: Mason), asume que quería decir lo correcto y ofrécele lo que encontraste.
                3. Si el sistema dice "No encontré productos exactos", ofrece ayuda o sugiere marcas populares (Lattafa, Maison).
                4. Sé corto, simpático y usa emojis.
                """
                
                try:
                    res = model.generate_content(prompt_final)
                    enviar_whatsapp(numero, res.text)
                except:
                    enviar_whatsapp(numero, "¡Ups! Me marié un poco. ¿Me repites el nombre del perfume?")

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
