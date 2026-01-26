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

# --- 2. LA BIBLIA DE GLAMSTORE (TU INFO REAL) ---
INFO_MANUAL = """
NOMBRE: Glamstore Chile
UBICACIÓN FÍSICA: Santo Domingo 240, Puente Alto (Al interior de Sandro's Collection).
HORARIO: Lunes a Viernes 10:00 a 17:30 hrs | Sábados 10:00 a 14:30 hrs.
POLÍTICA: No tenemos sucursales en Malls. Hacemos envíos a todo Chile.
WEB: www.glamstorechile.cl
"""

# --- MEMORIA Y ROBOT ---
MEMORIA_CHATS = {} 

# Robot Anti-Siesta (5 min)
def despertar_al_bot():
    while True:
        time.sleep(300)
        try: requests.get(MI_PROPIA_URL)
        except: pass

hilo = threading.Thread(target=despertar_al_bot)
hilo.daemon = True
hilo.start()

@app.route("/")
def home(): return "🤖 GLAMBOT EDUCADO v16", 200

# --- 3. CARGA SHOPIFY ---
def cargar_informacion_tienda():
    return INFO_MANUAL # Usamos solo tu verdad para evitar confusiones

MEMORIA_TIENDA = cargar_informacion_tienda()

# --- 4. GEMINI LITE ---
model = None
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    try: model = genai.GenerativeModel('gemini-2.0-flash-lite')
    except: model = genai.GenerativeModel('gemini-1.5-flash')

# --- 5. FUNCIONES VENTAS (CON RESPALDO) ---
def consultar_productos(busqueda):
    if not SHOPIFY_TOKEN: return "Error credenciales."
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("/", "")
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    # Intento 1: Búsqueda específica
    params = {"title": busqueda, "status": "active", "limit": 5}
    # Si buscan cosas generales, traemos lo último sin filtrar por nombre
    if busqueda.lower() in ["perfume", "perfumes", "arabe", "catalogo", "todo", "que venden", "tienes"]:
         params = {"status": "active", "limit": 8}

    try:
        r = requests.get(f"https://{tienda_url}/admin/api/2024-01/products.json", headers=headers, params=params)
        prods = r.json().get("products", [])
        
        # Intento 2: Si no encontró nada específico, traemos "lo más nuevo" (Plan B)
        if not prods:
            r2 = requests.get(f"https://{tienda_url}/admin/api/2024-01/products.json", headers=headers, params={"status": "active", "limit": 5})
            prods = r2.json().get("products", [])
            if prods:
                txt = f"🔎 No encontré exactamente '{busqueda}', pero mira lo último que llegó:\n"
            else:
                return "Pucha, justo no me carga el inventario ahora, pero seguro está en la web www.glamstorechile.cl"
        else:
            txt = "📦 ACÁ TENGO ESTAS OPCIONES:\n"
            
        for p in prods:
            v = p['variants'][0]
            txt += f"✨ {p['title']} (${float(v['price']):,.0f})\n"
        return txt
    except: return "Error técnico buscando."

def crear_link_pago(nombre_producto):
    if not SHOPIFY_TOKEN: return "Error credenciales."
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("/", "")
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    r = requests.get(f"https://{tienda_url}/admin/api/2024-01/products.json", 
                     headers=headers, params={"title": nombre_producto, "status": "active", "limit": 1})
    products = r.json().get("products", [])
    
    if not products: return f"No logré encontrar el '{nombre_producto}' para hacer el link, pero búscalo en la web! 🌐"
        
    v = products[0]['variants'][0]
    payload = {"draft_order": {"line_items": [{"variant_id": v['id'], "quantity": 1}]}}
    
    r2 = requests.post(f"https://{tienda_url}/admin/api/2024-01/draft_orders.json", headers=headers, json=payload)
    if r2.status_code == 201:
        data = r2.json().get("draft_order", {})
        return f"✅ ¡Listo! Link para {products[0]['title']} (${float(v['price']):,.0f}):\n👉 {data.get('invoice_url')}"
    return "Error creando link."

# --- 6. WEBHOOK SEGURO ---
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
            
            # Contexto
            instruccion_contexto = ""
            if len(historial) == 0:
                instruccion_contexto = f"INICIO: Es el primer mensaje. Saluda a {nombre} con amabilidad."
            else:
                instruccion_contexto = "FLUIDEZ: Ya estamos hablando. NO SALUDES DE NUEVO. Ve directo al grano con amabilidad."

            texto_historial = "\n".join([f"- {h['rol']}: {h['txt']}" for h in historial])

            if model:
                # 1. Detector
                prompt_det = f"Historial: {texto_historial}\nCliente: '{texto}'\nAcción: VENDER:[prod], BUSCAR:[prod] o CHARLA."
                try: decision = model.generate_content(prompt_det).text.strip().split("\n")[0]
                except: decision = "CHARLA"

                info_extra = ""
                if "VENDER:" in decision: info_extra = crear_link_pago(decision.split(":")[1])
                elif "BUSCAR:" in decision: info_extra = consultar_productos(decision.split(":")[1])

                # 2. Generador ETICO Y AMABLE
                prompt_final = f"""
                Eres "GlamBot", el asistente de ventas de Glamstore Chile.
                
                TUS REGLAS DE ORO (INQUEBRANTABLES):
                1. JAMÁS uses groserías, insolencias o ironías. Eres 100% profesional y dulce.
                2. NUNCA digas "no tenemos" sin ofrecer una alternativa o invitar a ver la web.
                3. Respeta la info oficial de ubicación y horarios al pie de la letra.
                
                INFO OFICIAL:
                {MEMORIA_TIENDA}
                
                ESTADO CHARLA: {instruccion_contexto}
                
                CONTEXTO:
                Historial: {texto_historial}
                Cliente dijo: "{texto}"
                Datos del Sistema: {info_extra}
                
                INSTRUCCIONES DE RESPUESTA:
                - Responde la duda del cliente con emojis cálidos (✨, 💖, ✅).
                - Si el sistema te mostró productos, lístalos con precio.
                - Si el sistema NO mostró productos, di: "En este momento no me aparecen acá, pero en nuestra web www.glamstorechile.cl seguro lo encuentras ✨". NUNCA DIGAS QUE NO VENDEMOS PERFUMES.
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
