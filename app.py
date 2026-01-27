import os
import logging
import threading
import time
import requests
import random  # <--- ¡IMPORTANTE! Para el barajado
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
🌐 WEB OFICIAL: www.glamstorechile.cl
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
def home(): return "🤖 GLAMBOT DINÁMICO v20", 200

# --- 3. CONFIGURACIÓN GEMINI ---
model = None
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    try: model = genai.GenerativeModel('gemini-2.0-flash-lite')
    except: model = genai.GenerativeModel('gemini-1.5-flash')

# --- 4. FUNCIONES VENTAS (AHORA DINÁMICAS 🎲) ---
def consultar_productos(busqueda):
    if not SHOPIFY_TOKEN: return ""
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("/", "")
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    # 1. Detectamos si es búsqueda GENERAL o ESPECÍFICA
    palabras_clave_generales = ["todo", "catalogo", "perfumes", "perfume", "algo", "que venden", "tienes", "variedad", "muestrame", "lista"]
    es_busqueda_general = any(p in busqueda.lower() for p in palabras_clave_generales)
    
    # URL de colección por defecto (Cámbiala si tienes una url especifica tipo /collections/perfumes)
    link_coleccion = "www.glamstorechile.cl" 

    if es_busqueda_general:
        # TRUCO: Traemos 50 productos (un lote grande)
        params = {"status": "active", "limit": 50}
        intro_txt = "🎲 Acá te elegí algunas opciones variadas de nuestro catálogo:\n"
    else:
        # Búsqueda específica (por nombre o marca)
        params = {"title": busqueda, "status": "active", "limit": 20} # Traemos 20 para tener variedad si hay muchos
        intro_txt = f"📦 Encontré estas opciones para '{busqueda}':\n"

    try:
        r = requests.get(f"https://{tienda_url}/admin/api/2024-01/products.json", headers=headers, params=params)
        prods = r.json().get("products", [])
        
        if not prods:
            if not es_busqueda_general:
                # Si no encontró lo específico, hacemos un "Shuffle" de lo general como Plan B
                r_fallback = requests.get(f"https://{tienda_url}/admin/api/2024-01/products.json", headers=headers, params={"status": "active", "limit": 30})
                prods = r_fallback.json().get("products", [])
                intro_txt = f"🔎 No vi el '{busqueda}' exacto ahora, pero mira estas joyas:\n"
            
            if not prods: return "NO_HAY_STOCK" 

        # --- AQUÍ OCURRE LA MAGIA DEL DINAMISMO 🎲 ---
        cantidad_a_mostrar = 5
        if len(prods) > cantidad_a_mostrar:
            # Seleccionamos 5 al azar del lote grande
            seleccionados = random.sample(prods, cantidad_a_mostrar)
        else:
            seleccionados = prods
            
        txt = intro_txt
        for p in seleccionados:
            v = p['variants'][0]
            precio = float(v['price'])
            txt += f"✨ {p['title']} ➡️ ${precio:,.0f}\n"
        
        # Agregamos el link maestro al final
        txt += f"\n🔗 Mira la colección completa aquí: {link_coleccion}"
        return txt

    except Exception as e: 
        logging.error(f"Error API: {e}")
        return ""

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
        return f"✅ Link generado para {products[0]['title']} (${float(v['price']):,.0f}):\n👉 {data.get('invoice_url')}"
    return ""

# --- 5. WEBHOOK INTELIGENTE ---
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
                # Detector
                prompt_det = f"""
                Analiza: "{texto}"
                Historial: {texto_historial}
                Clasifica: TIENDA, PRODUCTO, COMPRAR, OTRO.
                """
                try: decision = model.generate_content(prompt_det).text.strip().upper()
                except: decision = "OTRO"

                logging.info(f"🧠 INTENCIÓN: {decision}")

                info_sistema = ""
                
                if "TIENDA" in decision:
                    info_sistema = f"USA ESTA INFO EXACTA: {INFO_TIENDA}"
                
                elif "PRODUCTO" in decision:
                    res_shopify = consultar_productos(texto)
                    if res_shopify == "NO_HAY_STOCK":
                        info_sistema = "Dile que revise la web: www.glamstorechile.cl"
                    else:
                        info_sistema = res_shopify
                
                elif "COMPRAR" in decision:
                     info_sistema = crear_link_pago(texto) 
                     if "NO_ENCONTRE" in info_sistema:
                         info_sistema = "No pude hacer el link. Pide el nombre exacto."

                # Generador
                instruccion_saludo = "NO SALUDES (ya estamos hablando)" if len(historial) > 0 else "Saluda amable"

                prompt_final = f"""
                Eres GlamBot.
                
                CONTEXTO:
                - Cliente: {nombre}
                - Tono: {instruccion_saludo}. Amable, chileno relajado.
                
                INFO SISTEMA:
                {info_sistema}
                
                INSTRUCCIONES:
                1. Si el sistema te dio una lista de productos "barajados/variados", preséntalos como una selección especial para él/ella.
                2. Si pregunta ubicación, da la oficial de Puente Alto.
                3. NUNCA inventes links.
                
                Historial:
                {texto_historial}
                Cliente: "{texto}"
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
