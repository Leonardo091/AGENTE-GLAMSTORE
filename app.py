import os
import logging
import threading
import time
import requests
from flask import Flask, request, jsonify
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
MI_PROPIA_URL = "https://agente-glamstore.onrender.com" 

# --- MEMORIA Y ROBOT ---
MEMORIA_CHATS = {} 
MEMORIA_TIENDA = "Cargando..."

# Robot Anti-Siesta (Suave)
def despertar_al_bot():
    while True:
        time.sleep(600)
        try: requests.get(MI_PROPIA_URL)
        except: pass

hilo = threading.Thread(target=despertar_al_bot)
hilo.daemon = True
hilo.start()

@app.route("/")
def home(): return "🤖 GLAMBOT ACTIVO", 200

# --- 2. CARGA SHOPIFY ---
def cargar_informacion_tienda():
    if not SHOPIFY_TOKEN or not SHOPIFY_URL: return "Faltan credenciales"
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("/", "")
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    try:
        res = requests.get(f"https://{tienda_url}/admin/api/2024-01/shop.json", headers=headers)
        if res.status_code == 200: return "TIENDA ACTIVA"
    except: pass
    return "Error tienda"

MEMORIA_TIENDA = cargar_informacion_tienda()

# --- 3. GEMINI LITE ---
model = None
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    try:
        model = genai.GenerativeModel('gemini-2.0-flash-lite')
    except:
        model = genai.GenerativeModel('gemini-1.5-flash')

# --- 4. FUNCIONES VENTAS ---
def consultar_productos(busqueda):
    if not SHOPIFY_TOKEN: return "Error credenciales."
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("/", "")
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    params = {"title": busqueda, "status": "active", "limit": 5}
    if busqueda.lower() in ["perfume", "perfumes", "arabe", "lista", "catalogo"]:
         params = {"status": "active", "limit": 5}

    try:
        r = requests.get(f"https://{tienda_url}/admin/api/2024-01/products.json", headers=headers, params=params)
        prods = r.json().get("products", [])
        if not prods: return "No encontré ese producto específico en bodega."
        
        txt = "📦 ENCONTRÉ ESTO:\n"
        for p in prods:
            v = p['variants'][0]
            txt += f"▪️ {p['title']} (${float(v['price']):,.0f})\n"
        return txt
    except: return "Error buscando."

def crear_link_pago(nombre_producto):
    if not SHOPIFY_TOKEN: return "Error credenciales."
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("/", "")
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    # Busca 1 producto exacto
    r = requests.get(f"https://{tienda_url}/admin/api/2024-01/products.json", 
                     headers=headers, params={"title": nombre_producto, "status": "active", "limit": 1})
    products = r.json().get("products", [])
    
    if not products: return f"No encontré '{nombre_producto}'."
        
    v = products[0]['variants'][0]
    payload = {"draft_order": {"line_items": [{"variant_id": v['id'], "quantity": 1}]}}
    
    r2 = requests.post(f"https://{tienda_url}/admin/api/2024-01/draft_orders.json", headers=headers, json=payload)
    if r2.status_code == 201:
        data = r2.json().get("draft_order", {})
        return f"✅ Link para {products[0]['title']} (${float(v['price']):,.0f}):\n👉 {data.get('invoice_url')}"
    return "Error creando link."

# --- 5. WEBHOOK NATURAL ---
@app.route("/webhook", methods=["POST"])
def recibir_mensajes():
    try:
        body = request.get_json()
        entry = body["entry"][0]["changes"][0]["value"]

        if "messages" in entry:
            msg = entry["messages"][0]
            numero = msg["from"]
            texto = msg["text"]["body"]
            nombre = entry.get("contacts", [{}])[0].get("profile", {}).get("name", "Cliente")

            logging.info(f"📩 {nombre}: {texto}")

            if numero not in MEMORIA_CHATS:
                MEMORIA_CHATS[numero] = deque(maxlen=10)
            
            historial = list(MEMORIA_CHATS[numero])
            texto_historial = "\n".join([f"- {h['rol']}: {h['txt']}" for h in historial])

            if model:
                # 1. Detector de Intención
                prompt_det = f"Historial: {texto_historial}\nCliente dice: '{texto}'\nDefine acción: VENDER:[prod], BUSCAR:[prod] o CHARLA."
                try:
                    decision = model.generate_content(prompt_det).text.strip().split("\n")[0]
                except: decision = "CHARLA"

                info_extra = ""
                if "VENDER:" in decision: info_extra = crear_link_pago(decision.split(":")[1])
                elif "BUSCAR:" in decision: info_extra = consultar_productos(decision.split(":")[1])

                # 2. Generador de Respuesta NATURAL
                # Aquí le enseñamos LÓGICA DE CONVERSACIÓN, no prohibiciones.
                prompt_final = f"""
                Eres GlamBot de Glamstore Chile. Estás chateando por WhatsApp con {nombre}.
                
                HISTORIAL DE LA CHARLA:
                {texto_historial}
                
                LO QUE ACABA DE PASAR:
                {nombre} dijo: "{texto}"
                Información del sistema: {info_extra}
                
                INSTRUCCIONES DE FLUIDEZ (SENTIDO COMÚN):
                1. Revisa el historial de arriba.
                2. SI EL HISTORIAL ESTÁ VACÍO: Significa que la conversación recién empieza. Saluda amablemente.
                3. SI YA HAY MENSAJES PREVIOS: Significa que YA estamos hablando. NO saludes de nuevo. Continúa el hilo de forma natural, respondiendo directo a lo que preguntó ahora.
                4. Usa el nombre {nombre} para que se sienta cercano.
                5. Sé breve, como un chat de amigos.
                """
                
                try:
                    res = model.generate_content(prompt_final)
                    respuesta = res.text
                    
                    MEMORIA_CHATS[numero].append({"rol": nombre, "txt": texto})
                    MEMORIA_CHATS[numero].append({"rol": "Bot", "txt": respuesta})
                    
                    requests.post(
                        "https://graph.facebook.com/v21.0/939839529214459/messages",
                        headers={"Authorization": f"Bearer {TOKEN_WHATSAPP}", "Content-Type": "application/json"},
                        json={"messaging_product": "whatsapp", "to": numero, "type": "text", "text": {"body": respuesta}}
                    )
                except Exception as e:
                    logging.error(f"Error: {e}")

        return jsonify({"status": "ok"}), 200
    except: return jsonify({"status": "ok"}), 200

# VERIFICACIÓN
@app.route("/webhook", methods=["GET"])
def verificar():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge"), 200
    return "Error", 403

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
