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

# --- 2. LA BIBLIA DE GLAMSTORE (TU VERDAD) ---
INFO_TIENDA = """
NOMBRE: Glamstore Chile
UBICACIÓN FÍSICA: Santo Domingo 240, Puente Alto (Interior Sandro's Collection).
HORARIOS: Lunes-Viernes 10:00-17:30 | Sábados 10:00-14:30.
WEB: www.glamstorechile.cl
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
def home(): return "🤖 GLAMBOT v17 OK", 200

# --- 3. CONFIGURACIÓN GEMINI ---
model = None
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    try: model = genai.GenerativeModel('gemini-2.0-flash-lite')
    except: model = genai.GenerativeModel('gemini-1.5-flash')

# --- 4. FUNCIONES VENTAS ---
def consultar_productos(busqueda):
    if not SHOPIFY_TOKEN: return "Error técnico."
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("/", "")
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    # Si es búsqueda general, traemos lo nuevo
    params = {"title": busqueda, "status": "active", "limit": 5}
    if busqueda.lower() in ["todo", "catalogo", "perfumes", "perfume", "algo", "que tienes"]:
        params = {"status": "active", "limit": 6}

    try:
        r = requests.get(f"https://{tienda_url}/admin/api/2024-01/products.json", headers=headers, params=params)
        prods = r.json().get("products", [])
        
        if not prods: return "NOT_FOUND" # Señal clave para el bot
            
        txt = "📦 DISPONIBLE:\n"
        for p in prods:
            v = p['variants'][0]
            txt += f"✨ {p['title']} (${float(v['price']):,.0f})\n"
        return txt
    except: return "ERROR_API"

def crear_link_pago(nombre_producto):
    if not SHOPIFY_TOKEN: return "Error credenciales."
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("/", "")
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    r = requests.get(f"https://{tienda_url}/admin/api/2024-01/products.json", 
                     headers=headers, params={"title": nombre_producto, "status": "active", "limit": 1})
    products = r.json().get("products", [])
    
    if not products: return "NOT_FOUND_LINK"
        
    v = products[0]['variants'][0]
    payload = {"draft_order": {"line_items": [{"variant_id": v['id'], "quantity": 1}]}}
    r2 = requests.post(f"https://{tienda_url}/admin/api/2024-01/draft_orders.json", headers=headers, json=payload)
    if r2.status_code == 201:
        data = r2.json().get("draft_order", {})
        return f"✅ Link generado para {products[0]['title']} (${float(v['price']):,.0f}):\n👉 {data.get('invoice_url')}"
    return "Error creando link."

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
            nombre = entry.get("contacts", [{}])[0].get("profile", {}).get("name", "Cliente")

            logging.info(f"📩 {nombre}: {texto}")

            if numero not in MEMORIA_CHATS:
                MEMORIA_CHATS[numero] = deque(maxlen=10)
            
            historial = list(MEMORIA_CHATS[numero])
            texto_historial = "\n".join([f"- {h['rol']}: {h['txt']}" for h in historial])

            if model:
                # 1. Detector de Intención
                # Ahora distingue entre BUSCAR PRODUCTO y PREGUNTAR UBICACIÓN
                prompt_det = f"""
                Analiza: "{texto}"
                Historial reciente: {texto_historial}
                
                Clasifica en UNA categoría:
                - VENDER: [Nombre Producto] (Solo si quiere comprar/pagar)
                - BUSCAR: [Nombre Producto] (Solo si pregunta por stock, precios, marcas, perfumes)
                - INFO_TIENDA (Si pregunta ubicación, horario, envíos, o si es real)
                - CHARLA (Saludos, gracias, otros)
                """
                try: decision = model.generate_content(prompt_det).text.strip().split("\n")[0]
                except: decision = "CHARLA"

                logging.info(f"🧠 INTENCIÓN: {decision}")

                info_extra = ""
                # SOLO buscamos en Shopify si la intención es de PRODUCTO
                if "VENDER:" in decision: 
                    info_extra = crear_link_pago(decision.split(":")[1])
                elif "BUSCAR:" in decision: 
                    info_extra = consultar_productos(decision.split(":")[1])
                
                # Definir saludo dinámicamente
                instruccion_saludo = ""
                if len(historial) == 0:
                    instruccion_saludo = f"Saluda a {nombre} amablemente."
                else:
                    instruccion_saludo = "NO SALUDES (ya estamos hablando). Responde directo."

                # 2. Generador de Respuesta
                prompt_final = f"""
                Eres "GlamBot", asistente de Glamstore Chile.
                
                DATOS OFICIALES TIENDA:
                {INFO_TIENDA}
                
                SITUACIÓN:
                - Estado Conversación: {instruccion_saludo}
                - Intención Cliente: {decision}
                - Info Sistema (Shopify): {info_extra}
                
                INSTRUCCIONES CLAVE:
                1. REGLA DE ORO: Sé amable y educado. CERO insolencia.
                2. SI PREGUNTA UBICACIÓN: Da la dirección de Puente Alto. NO menciones que "no aparecen productos acá", eso confunde.
                3. SI PREGUNTA PRODUCTOS:
                   - Si Info Sistema trae productos: Muéstralos con precio.
                   - Si Info Sistema dice "NOT_FOUND": Di "No me aparece ese específico acá, pero revisa nuestra web ✨".
                4. NO repitas "Hola" si la instrucción dice NO SALUDES.
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
