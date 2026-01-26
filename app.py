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

# --- 2. LA VERDAD ABSOLUTA (CONFIGURACIÓN MANUAL) ---
# SI SHOPIFY FALLA O LA IA INVENTA, ESCRIBE AQUÍ TU INFO REAL
INFO_MANUAL = """
NOMBRE: Glamstore Chile
UBICACIÓN: Santo Domingo 240 Puente alto, Al interior de Sandro's Collection, Santiago, Chile
HORARIO: Lunes a Viernes 10:00 a 17:30 hrs y Sabado de 10:00 a 14:30 hrs
POLITICA: No tenemos sucursales físicas en Malls por el momento, contamos con envios a todo Chile
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
def home(): return "🤖 GLAMBOT ACTIVO v14", 200

# --- 3. CARGA SHOPIFY MEJORADA (LEE DIRECCIÓN) ---
def cargar_informacion_tienda():
    if not SHOPIFY_TOKEN or not SHOPIFY_URL: return INFO_MANUAL
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("/", "")
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    info_construida = INFO_MANUAL + "\nDATOS DESDE SHOPIFY:\n"
    
    try:
        # 1. Intentamos leer datos de la tienda (Dirección real)
        res = requests.get(f"https://{tienda_url}/admin/api/2024-01/shop.json", headers=headers)
        if res.status_code == 200:
            shop = res.json().get('shop', {})
            direccion = shop.get('address1', 'Santiago')
            ciudad = shop.get('city', 'Chile')
            pais = shop.get('country_name', 'Chile')
            email = shop.get('email', '')
            
            info_construida += f"- Dirección registrada: {direccion}, {ciudad}, {pais}.\n"
            info_construida += f"- Contacto: {email}\n"
            logging.info("✅ DATOS DE TIENDA CARGADOS")
        else:
            info_construida += "(Usando info manual por error de conexión)\n"
            
    except Exception as e:
        logging.error(f"❌ Error cargando tienda: {e}")
        
    return info_construida

MEMORIA_TIENDA = cargar_informacion_tienda()

# --- 4. GEMINI LITE ---
model = None
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    try: model = genai.GenerativeModel('gemini-2.0-flash-lite')
    except: model = genai.GenerativeModel('gemini-1.5-flash')

# --- 5. FUNCIONES VENTAS ---
def consultar_productos(busqueda):
    if not SHOPIFY_TOKEN: return "Error credenciales."
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("/", "")
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    params = {"title": busqueda, "status": "active", "limit": 5}
    if busqueda.lower() in ["perfume", "perfumes", "arabe", "lista", "catalogo", "todo"]:
         params = {"status": "active", "limit": 5}

    try:
        r = requests.get(f"https://{tienda_url}/admin/api/2024-01/products.json", headers=headers, params=params)
        prods = r.json().get("products", [])
        if not prods: return "No encontré ese producto específico."
        
        txt = "📦 DISPONIBLE AHORA:\n"
        for p in prods:
            v = p['variants'][0]
            txt += f"▪️ {p['title']} (${float(v['price']):,.0f})\n"
        return txt
    except: return "Error buscando."

def crear_link_pago(nombre_producto):
    if not SHOPIFY_TOKEN: return "Error credenciales."
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("/", "")
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
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

# --- 6. WEBHOOK CON REGLAS DE ORO ---
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
            
            # --- LÓGICA ESTRICTA DE ESTADO ---
            instruccion_estado = ""
            if len(historial) == 0:
                instruccion_estado = "FASE 1 (INICIO): Saluda amable y corto."
            else:
                instruccion_estado = "FASE 2 (EN CURSO): PROHIBIDO SALUDAR. Responde DIRECTO al grano."

            texto_historial = "\n".join([f"- {h['rol']}: {h['txt']}" for h in historial])

            if model:
                # 1. Detector
                prompt_det = f"Historial: {texto_historial}\nCliente: '{texto}'\nAcción: VENDER:[prod], BUSCAR:[prod] o CHARLA."
                try: decision = model.generate_content(prompt_det).text.strip().split("\n")[0]
                except: decision = "CHARLA"

                info_extra = ""
                if "VENDER:" in decision: info_extra = crear_link_pago(decision.split(":")[1])
                elif "BUSCAR:" in decision: info_extra = consultar_productos(decision.split(":")[1])

                # 2. Generador BLINDADO CONTRA MENTIRAS
                prompt_final = f"""
                Eres GlamBot de Glamstore Chile.
                
                FUENTE DE LA VERDAD (Información oficial):
                {MEMORIA_TIENDA}
                (SI NO SALE AQUÍ, NO EXISTE. NO INVENTES SUCURSALES).
                
                ESTADO CONVERSACIÓN: {instruccion_estado}
                
                HISTORIAL:
                {texto_historial}
                
                CLIENTE DIJO: "{texto}"
                DATO EXTRA SISTEMA: {info_extra}
                
                INSTRUCCIONES:
                1. Si estás en FASE 2, NO DIGAS "Hola" ni "Buenos días".
                2. Si preguntan ubicación, usa SOLO la información de la FUENTE DE LA VERDAD. Si no sale dirección exacta, di que somos tienda online. NO INVENTES MALLS.
                3. Sé natural y chileno.
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
