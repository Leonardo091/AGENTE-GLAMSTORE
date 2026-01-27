import os
import logging
import threading
import time
import requests
import random
from datetime import datetime, timedelta # IMPORTANTE: Para la hora
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

# --- 2. LA VERDAD ABSOLUTA (NO MODIFICAR) ---

# Texto Mayorista (Tu redacción exacta)
TEXTO_MAYORISTA_FIJO = """
Mire, contamos con un servicio de precio al detalle, pero si usted está buscando comprar por volumen, 
podemos ofrecerle precios mayoristas dependiendo de los artículos que quiera consultar y de sus respectivas cantidades (puede ser surtido igualmente).
"""

# Info Tienda
DIRECCION = "Santo Domingo 240, Puente Alto (Interior Sandro's Collection)"
HORARIOS_TXT = "Lunes a Viernes 10:00-17:30 | Sábados 10:00-14:30"
WEB = "www.glamstorechile.cl"

# --- 3. LÓGICA DE TIEMPO REAL (HORA CHILE) ---
def obtener_estado_tienda():
    # Ajuste manual UTC-3 (Horario Verano Chile)
    # Si cambia la hora en invierno, cambiar a -4
    ahora_utc = datetime.utcnow()
    ahora_chile = ahora_utc - timedelta(hours=3) 
    
    dia = ahora_chile.weekday() # 0=Lunes, 6=Domingo
    hora = ahora_chile.hour
    minuto = ahora_chile.minute
    
    hora_str = f"{hora:02d}:{minuto:02d}"
    
    esta_abierto = False
    
    # Lógica Lunes a Viernes (10:00 a 17:30)
    if 0 <= dia <= 4: 
        if 10 <= hora < 17: esta_abierto = True
        elif hora == 17 and minuto <= 30: esta_abierto = True
    
    # Lógica Sábado (10:00 a 14:30)
    elif dia == 5:
        if 10 <= hora < 14: esta_abierto = True
        elif hora == 14 and minuto <= 30: esta_abierto = True
            
    estado = "ABIERTO ✅" if esta_abierto else "CERRADO 🌙"
    return estado, hora_str

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
def home(): return "🤖 GLAMBOT v23 ANTI-ALUCINACION", 200

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
    
    es_general = any(x in busqueda.lower() for x in ["perfume", "catalogo", "todo", "lista", "productos"])
    params = {"status": "active", "limit": 50} if es_general else {"title": busqueda, "status": "active", "limit": 20}
    
    try:
        r = requests.get(url, headers=headers, params=params)
        prods = r.json().get("products", [])
        if not prods: return "NO_HAY_STOCK"
        
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
            estado_tienda, hora_actual = obtener_estado_tienda() # <--- HORA CHILENA REAL
            
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
                - CARRITO_AGREGAR: (Comprar producto específico)
                - CARRITO_PAGAR: (Pide link, total)
                - PREGUNTA_TIENDA: (Ubicación, horario, si está abierto)
                - PREGUNTA_PRODUCTO: (Stock, catalogo)
                - PREGUNTA_MAYORISTA: (Precios por mayor, por volumen)
                - CHARLA: (Saludos)
                """
                try: decision = model.generate_content(prompt_det).text.strip().split(":")[0]
                except: decision = "CHARLA"

                info_sistema = ""
                
                # 2. ACCIONES
                if "CARRITO_AGREGAR" in decision:
                    info_sistema = f"Busca producto en Shopify."
                    prod = buscar_producto_shopify(texto)
                    if prod:
                        usuario['carrito'].append(prod)
                        info_sistema = f"✅ AGREGADO: {prod['title']}. Total items: {len(usuario['carrito'])}. Pregunta si quiere algo más."
                    else:
                        info_sistema = "❌ No encontré ese producto exacto."

                elif "CARRITO_PAGAR" in decision:
                    if usuario['carrito']:
                        link = crear_carrito_shopify(usuario['carrito'])
                        info_sistema = f"✅ LINK CREADO: {link}."
                        usuario['carrito'] = []
                    else:
                        info_sistema = "El carrito está vacío."

                elif "PREGUNTA_PRODUCTO" in decision:
                    info_sistema = consultar_catalogo(texto)

                elif "PREGUNTA_MAYORISTA" in decision:
                    # FORZAMOS EL TEXTO EXACTO
                    info_sistema = f"RESPONDE EXACTAMENTE ESTO: {TEXTO_MAYORISTA_FIJO}"

                elif "PREGUNTA_TIENDA" in decision:
                    info_sistema = f"""
                    DATOS REALES:
                    - Hora Actual Chile: {hora_actual}
                    - Estado Tienda: {estado_tienda}
                    - Dirección: {DIRECCION}
                    - Horario: {HORARIOS_TXT}
                    """

                # 3. GENERADOR DE RESPUESTA (REGLAS ANTI-ALUCINACIÓN)
                instruccion_saludo = "Saluda formal (Usted)" if debe_saludar else "NO SALUDES"
                
                prompt_final = f"""
                Eres GlamBot de Glamstore Chile.
                
                IDENTIDAD (LEER ATENTAMENTE):
                1. SOMOS UNA PERFUMERÍA Y TIENDA DE BELLEZA.
                2. NO VENDEMOS ROPA, NI PRENDAS, NI POLERAS. (Si el cliente pregunta, aclara que "Sandro's Collection" es solo el nombre del local donde estamos, pero nosotros vendemos perfumes).
                3. SÍ VENDEMOS POR WHATSAPP.
                
                SITUACIÓN ACTUAL:
                - Hora Chile: {hora_actual}. Estado: {estado_tienda}.
                - Si dice CERRADO y el cliente pregunta si puede ir, dile que NO vaya al local, pero que compre en la web.
                
                INFO SISTEMA: {info_sistema}
                
                INSTRUCCIONES:
                1. {instruccion_saludo}.
                2. Si el sistema te dio el TEXTO MAYORISTA, úsalo tal cual. NO INVENTES REGLAS DE "6 PRENDAS". ESO ES MENTIRA.
                3. Sé amable y usa emojis.
                
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
