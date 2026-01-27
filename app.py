import os
import logging
import threading
import time
import requests
import random
from datetime import datetime, timedelta # <--- IMPORTANTE PARA LA HORA
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

# --- 2. DATOS FIJOS (SIN CORCHETES PARA QUE NO SE CONFUNDA) ---
DIRECCION_REAL = "Santo Domingo 240, Puente Alto (Interior Sandro's Collection)"
HORARIOS_REAL = "Lunes a Viernes 10:00 a 17:30 y Sábados 10:00 a 14:30"
WEB_REAL = "www.glamstorechile.cl"
MAYORISTA_TEXTO = "Contamos con precio detalle y precios mayoristas por volumen (surtido)."

# --- 3. FUNCIÓN DE HORA CHILENA 🇨🇱 ---
def obtener_estado_tienda():
    # Calculamos hora Chile (UTC-3 aprox por horario verano, ajusta si cambia)
    ahora_utc = datetime.utcnow()
    ahora_chile = ahora_utc - timedelta(hours=3) 
    
    dia = ahora_chile.weekday() # 0=Lunes, 6=Domingo
    hora = ahora_chile.hour
    minuto = ahora_chile.minute
    hora_actual_str = f"{hora}:{minuto:02d}"
    
    esta_abierto = False
    
    # Lógica Horario
    if 0 <= dia <= 4: # Lunes a Viernes
        if 10 <= hora < 17 or (hora == 17 and minuto <= 30):
            esta_abierto = True
    elif dia == 5: # Sábado
        if 10 <= hora < 14 or (hora == 14 and minuto <= 30):
            esta_abierto = True
            
    estado = "ABIERTO AHORA ✅" if esta_abierto else "CERRADO AHORA 🌙"
    return estado, hora_actual_str

# --- 4. MEMORIA ---
MEMORIA_USUARIOS = {} 

def despertar_al_bot():
    while True:
        time.sleep(300)
        try: requests.get(MI_PROPIA_URL)
        except: pass

hilo = threading.Thread(target=despertar_al_bot)
hilo.daemon = True
hilo.start()

@app.route("/")
def home(): return "🤖 GLAMBOT v23 CON RELOJ", 200

# --- 5. GEMINI ---
model = None
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    try: model = genai.GenerativeModel('gemini-2.0-flash-lite')
    except: model = genai.GenerativeModel('gemini-1.5-flash')

# --- 6. FUNCIONES SHOPIFY ---
def buscar_producto_shopify(nombre):
    if not SHOPIFY_TOKEN: return None
    url = f"https://{SHOPIFY_URL.replace('https://','')}/admin/api/2024-01/products.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    r = requests.get(url, headers=headers, params={"title": nombre, "status": "active", "limit": 1})
    prods = r.json().get("products", [])
    if not prods: return None
    v = prods[0]['variants'][0]
    return {"id": v['id'], "title": prods[0]['title'], "price": float(v['price'])}

def crear_carrito_shopify(items):
    if not SHOPIFY_TOKEN or not items: return None
    url = f"https://{SHOPIFY_URL.replace('https://','')}/admin/api/2024-01/draft_orders.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    payload = {"draft_order": {"line_items": [{"variant_id": i['id'], "quantity": 1} for i in items]}}
    r = requests.post(url, headers=headers, json=payload)
    if r.status_code == 201: return r.json().get("draft_order", {}).get("invoice_url")
    return None

def consultar_catalogo(busqueda):
    if not SHOPIFY_TOKEN: return ""
    url = f"https://{SHOPIFY_URL.replace('https://','')}/admin/api/2024-01/products.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    es_general = any(x in busqueda.lower() for x in ["perfume", "catalogo", "todo", "lista"])
    params = {"status": "active", "limit": 50} if es_general else {"title": busqueda, "status": "active", "limit": 20}
    
    try:
        r = requests.get(url, headers=headers, params=params)
        prods = r.json().get("products", [])
        if not prods: return "NO_HAY_STOCK"
        
        # Shuffle
        seleccion = random.sample(prods, min(len(prods), 5))
        txt = "📦 OPCIONES:\n"
        for p in seleccion:
            v = p['variants'][0]
            txt += f"▪️ {p['title']} (${float(v['price']):,.0f})\n"
        return txt
    except: return ""

# --- 7. WEBHOOK ---
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

            # MEMORIA & HORA
            ahora_ts = time.time()
            estado_tienda, hora_actual = obtener_estado_tienda() # <--- HORA REAL
            
            if numero not in MEMORIA_USUARIOS:
                MEMORIA_USUARIOS[numero] = {'historial': deque(maxlen=10), 'ultimo_msg': 0, 'carrito': []}
            
            usuario = MEMORIA_USUARIOS[numero]
            
            # Saludo inteligente (2 horas)
            debe_saludar = False
            if (ahora_ts - usuario['ultimo_msg'] > 7200 and usuario['ultimo_msg'] != 0) or usuario['ultimo_msg'] == 0:
                debe_saludar = True
                usuario['carrito'] = [] 
            if any(s in texto.lower() for s in ["hola", "buenas", "alo"]): debe_saludar = True
            
            usuario['ultimo_msg'] = ahora_ts
            historial_txt = "\n".join([f"- {h['rol']}: {h['txt']}" for h in usuario['historial']])

            if model:
                # 1. CLASIFICADOR
                prompt_det = f"""
                Mensaje: "{texto}"
                Historial: {historial_txt}
                Clasifica en UNO:
                - CARRITO_AGREGAR: (Si quiere comprar producto específico)
                - CARRITO_PAGAR: (Si pide link, total, pagar)
                - PREGUNTA_TIENDA: (Ubicación, horario, si está abierto)
                - PREGUNTA_PRODUCTO: (Stock, catalogo)
                - CHARLA: (Saludos)
                """
                try: decision = model.generate_content(prompt_det).text.strip().split(":")[0]
                except: decision = "CHARLA"

                info_sistema = ""
                
                # 2. ACCIONES
                if "CARRITO_AGREGAR" in decision:
                    # Intentamos sacar el nombre del producto del texto
                    info_sistema = f"Busca el producto en Shopify. Si existe, agrégalo mentalmente."
                    prod = buscar_producto_shopify(texto) # Búsqueda simple
                    if prod:
                        usuario['carrito'].append(prod)
                        info_sistema = f"✅ AGREGADO: {prod['title']}. Total items: {len(usuario['carrito'])}. PREGUNTA SI QUIERE ALGO MÁS."
                    else:
                        info_sistema = "❌ No encontré ese producto exacto. Pide el nombre bien escrito."

                elif "CARRITO_PAGAR" in decision:
                    if usuario['carrito']:
                        link = crear_carrito_shopify(usuario['carrito'])
                        info_sistema = f"✅ LINK CREADO: {link}. Entrégalo al cliente."
                        usuario['carrito'] = []
                    else:
                        info_sistema = "El carrito está vacío."

                elif "PREGUNTA_PRODUCTO" in decision:
                    info_sistema = consultar_catalogo(texto)

                elif "PREGUNTA_TIENDA" in decision:
                    # AQUÍ LE PASAMOS LA HORA REAL AL CEREBRO
                    info_sistema = f"""
                    DATOS REALES:
                    - Estado Actual Tienda: {estado_tienda} (Son las {hora_actual}).
                    - Dirección: {DIRECCION_REAL}.
                    - Horario Fijo: {HORARIOS_REAL}.
                    - Web: {WEB_REAL}.
                    """

                # 3. GENERADOR DE RESPUESTA
                instruccion_saludo = "Saluda formal" if debe_saludar else "NO SALUDES"
                
                prompt_final = f"""
                Eres GlamBot.
                
                SITUACIÓN ACTUAL:
                - Hora en Chile: {hora_actual}
                - Estado Tienda: {estado_tienda} (Si dice CERRADO, avisa que no pueden ir al local ahora, pero sí comprar web).
                
                INFO SISTEMA: {info_sistema}
                
                TUS REGLAS:
                1. {instruccion_saludo}.
                2. SÍ VENDEMOS POR WHATSAPP. Si el cliente quiere comprar, toma el pedido. JAMÁS digas que no gestionamos pedidos.
                3. Si preguntan dirección, da la de Puente Alto ({DIRECCION_REAL}). NO USES CORCHETES [].
                4. Sé amable (Usted).
                
                Historial: {historial_txt}
                Cliente: "{texto}"
                """
                
                try:
                    res = model.generate_content(prompt_final)
                    respuesta = res.text
                    
                    usuario['historial'].append({"rol": nombre, "txt": texto})
                    usuario['historial'].append({"rol": "Bot", "txt": respuesta})
                    
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
