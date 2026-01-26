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

# --- 2. LA VERDAD ABSOLUTA ---
INFO_TIENDA = """
📍 UBICACIÓN: Santo Domingo 240, Puente Alto (Interior Sandro's Collection).
⏰ HORARIOS: Lunes a Viernes 10:00-17:30 | Sábados 10:00-14:30.
🚛 ENVÍOS: A todo Chile.
🌐 WEB: www.glamstorechile.cl
"""

# --- MEMORIA Y ROBOT ---
MEMORIA_CHATS = {} 

def despertar_al_bot():
    while True:
        time.sleep(300)
        try: requests.get(MI_PROPIA_URL)
        except: pass

hilo = threading.Thread(target=despertar_al_bot)
hilo.daemon = True
hilo.start()

@app.route("/")
def home(): return "🤖 GLAMBOT v18 LISTO", 200

# --- 3. CONFIGURACIÓN GEMINI ---
model = None
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    try: model = genai.GenerativeModel('gemini-2.0-flash-lite')
    except: model = genai.GenerativeModel('gemini-1.5-flash')

# --- 4. FUNCIONES VENTAS ---
def consultar_productos(busqueda):
    if not SHOPIFY_TOKEN: return ""
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("/", "")
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    params = {"title": busqueda, "status": "active", "limit": 5}
    if busqueda.lower() in ["todo", "catalogo", "perfumes", "perfume", "algo", "que venden"]:
        params = {"status": "active", "limit": 6}

    try:
        r = requests.get(f"https://{tienda_url}/admin/api/2024-01/products.json", headers=headers, params=params)
        prods = r.json().get("products", [])
        
        if not prods: return "NO_HAY_STOCK" 
            
        txt = "📦 ENCONTRÉ ESTO:\n"
        for p in prods:
            v = p['variants'][0]
            txt += f"✨ {p['title']} (${float(v['price']):,.0f})\n"
        return txt
    except: return ""

def crear_link_pago(nombre_producto):
    if not SHOPIFY_TOKEN: return ""
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("/", "")
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    r = requests.get(f"https://{tienda_url}/admin/api/2024-01/products.json", 
                     headers=headers, params={"title": nombre_producto, "status": "active", "limit": 1})
    products = r.json().get("products", [])
    
    if not products: return "NO_ENCONTRE_PRODUCTO_EXACTO"
        
    v = products[0]['variants'][0]
    payload = {"draft_order": {"line_items": [{"variant_id": v['id'], "quantity": 1}]}}
    r2 = requests.post(f"https://{tienda_url}/admin/api/2024-01/draft_orders.json", headers=headers, json=payload)
    if r2.status_code == 201:
        data = r2.json().get("draft_order", {})
        return f"✅ Link: {data.get('invoice_url')}"
    return ""

# --- 5. WEBHOOK LÓGICO ---
@app.route("/webhook", methods=["POST"])
def recibir_mensajes():
    try:
        body = request.get_json()
        entry = body["entry"][0]["changes"][0]["value"]

        if "messages" in entry:
            msg = entry["messages"][0]
            numero = msg["from"]
            texto = msg["text"]["body"]
            nombre = entry.get("contacts", [{}])[0].get("profile", {}).get("name", "amig@")

            logging.info(f"📩 {nombre}: {texto}")

            if numero not in MEMORIA_CHATS:
                MEMORIA_CHATS[numero] = deque(maxlen=10)
            
            historial = list(MEMORIA_CHATS[numero])
            texto_historial = "\n".join([f"- {h['rol']}: {h['txt']}" for h in historial])

            if model:
                # PASO 1: Detector de Intención (SIMPLE)
                prompt_det = f"""
                Analiza el mensaje: "{texto}"
                Responde UNA SOLA PALABRA:
                - TIENDA (Si pregunta ubicación, horario, dónde están, envío)
                - PRODUCTO (Si pregunta por stock, precio, catálogo, perfumes)
                - COMPRAR (Si dice "quiero ese", "dame link")
                - OTRO (Saludos, gracias, charla)
                """
                try: decision = model.generate_content(prompt_det).text.strip().upper()
                except: decision = "OTRO"

                logging.info(f"🧠 CEREBRO DECIDIÓ: {decision}")

                # PASO 2: Ejecutar Acción (LÓGICA BLINDADA)
                info_sistema = ""
                
                if "TIENDA" in decision:
                    # SI ES TIENDA, LE DAMOS LA DIRECCIÓN Y BLOQUEAMOS SHOPIFY
                    info_sistema = f"El cliente pregunta por la tienda. USA ESTA INFO: {INFO_TIENDA}"
                
                elif "PRODUCTO" in decision:
                    res_shopify = consultar_productos(texto)
                    if res_shopify == "NO_HAY_STOCK":
                        info_sistema = "No se encontraron productos específicos. Invita a ver la web."
                    else:
                        info_sistema = res_shopify
                
                elif "COMPRAR" in decision:
                     # Intentamos adivinar qué producto quiere comprar del texto o historial
                     info_sistema = crear_link_pago(texto) 
                     if "NO_ENCONTRE" in info_sistema:
                         info_sistema = "No pude generar el link automático. Pide el nombre exacto."

                # PASO 3: Generar Respuesta (SIN CONFUSIONES)
                instruccion_saludo = "NO SALUDES DE NUEVO (se directo)" if len(historial) > 0 else "Saluda amable"

                prompt_final = f"""
                Actúa como GlamBot (Asistente de Glamstore Chile).
                
                CONTEXTO:
                - Cliente: {nombre}
                - Estado: {instruccion_saludo}
                
                INFO DEL SISTEMA (LO QUE SABES):
                {info_sistema}
                
                INSTRUCCIONES FINALES:
                1. Responde SOLO al mensaje del cliente. NO digas "Entendido" ni "Perfecto".
                2. Si la Info del Sistema tiene la dirección, dásela clara.
                3. Si la Info del Sistema tiene productos, muéstralos.
                4. Sé amable, usa emojis, pero NO REPITAS SALUDOS si ya hay historial.
                
                ÚLTIMOS MENSAJES:
                {texto_historial}
                Cliente: "{texto}"
                
                TU RESPUESTA:
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
