import os
import logging
import threading
import time
import requests
import random
import re
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

# --- 2. CONFIGURACIÓN DEL NEGOCIO ---
TEXTO_MAYORISTA = """
Mire, contamos con un servicio de precio al detalle, pero si usted está buscando comprar por volumen, 
podemos ofrecerle precios mayoristas dependiendo de los artículos que quiera consultar y de sus respectivas cantidades (puede ser surtido igualmente).
"""

# INFO TIENDA (IMPORTANTE: Sin corchetes raros para que no falle)
INFO_TIENDA = f"""
📍 UBICACIÓN: Santo Domingo 240, Puente Alto (Interior Sandro's Collection).
⏰ HORARIOS: Lunes a Viernes 10:00-17:30 | Sábados 10:00-14:30.
🚛 ENVÍOS: A todo Chile.
🌐 WEB: www.glamstorechile.cl
💰 MAYORISTA: {TEXTO_MAYORISTA}
"""

LINKS_COLECCIONES = {
    "perfume": "https://www.glamstorechile.cl/collections/perfumeria",
    "maquillaje": "https://www.glamstorechile.cl/collections/maquillaje",
    "capilar": "https://www.glamstorechile.cl/collections/capilar",
    "general": "https://www.glamstorechile.cl/collections/all"
}

# --- 3. MEMORIA DE USUARIOS Y CARRITO 🛒 ---
# Estructura: { 'numero': { 'historial': deque, 'ultimo_msg': time, 'carrito': [] } }
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
def home(): return "🤖 GLAMBOT VENDEDOR v22 ONLINE", 200

# --- 4. CONFIGURACIÓN GEMINI ---
model = None
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    try: model = genai.GenerativeModel('gemini-2.0-flash-lite')
    except: model = genai.GenerativeModel('gemini-1.5-flash')

# --- 5. FUNCIONES SHOPIFY AVANZADAS ---

def buscar_producto_shopify(nombre):
    """Busca un producto y devuelve su ID variante, titulo y precio"""
    if not SHOPIFY_TOKEN: return None
    url = f"https://{SHOPIFY_URL.replace('https://','')}/admin/api/2024-01/products.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    # Intento 1: Búsqueda exacta
    r = requests.get(url, headers=headers, params={"title": nombre, "status": "active", "limit": 1})
    prods = r.json().get("products", [])
    
    if not prods: return None
    
    p = prods[0]
    v = p['variants'][0]
    return {"id": v['id'], "title": p['title'], "price": float(v['price'])}

def crear_carrito_shopify(items_carrito):
    """Crea un Draft Order con múltiples items"""
    if not SHOPIFY_TOKEN or not items_carrito: return None
    url = f"https://{SHOPIFY_URL.replace('https://','')}/admin/api/2024-01/draft_orders.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    line_items = [{"variant_id": item['id'], "quantity": 1} for item in items_carrito]
    
    payload = {
        "draft_order": {
            "line_items": line_items,
            "use_customer_default_address": False
        }
    }
    
    r = requests.post(url, headers=headers, json=payload)
    if r.status_code == 201:
        return r.json().get("draft_order", {}).get("invoice_url")
    return None

def consultar_catalogo_random(busqueda):
    if not SHOPIFY_TOKEN: return ""
    url = f"https://{SHOPIFY_URL.replace('https://','')}/admin/api/2024-01/products.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    es_general = any(x in busqueda.lower() for x in ["todo", "catalogo", "perfumes", "lista", "que tiene"])
    
    if es_general:
        params = {"status": "active", "limit": 50}
        intro = "Aquí tiene una selección variada de nuestro catálogo:\n"
    else:
        params = {"title": busqueda, "status": "active", "limit": 20}
        intro = f"He encontrado estas opciones para '{busqueda}':\n"

    try:
        r = requests.get(url, headers=headers, params=params)
        prods = r.json().get("products", [])
        
        if not prods and not es_general:
             # Fallback
             r2 = requests.get(url, headers=headers, params={"status": "active", "limit": 30})
             prods = r2.json().get("products", [])
             intro = f"No encontré '{busqueda}' exacto, pero mire estas novedades:\n"
        
        if not prods: return "NO_HAY_STOCK"

        seleccion = random.sample(prods, min(len(prods), 5))
        txt = intro
        for p in seleccion:
            v = p['variants'][0]
            txt += f"🔹 {p['title']} - ${float(v['price']):,.0f}\n"
        
        return txt
    except: return ""

# --- 6. WEBHOOK CEREBRAL ---
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

            # GESTIÓN MEMORIA Y CARRITO
            ahora = time.time()
            if numero not in MEMORIA_USUARIOS:
                MEMORIA_USUARIOS[numero] = {'historial': deque(maxlen=10), 'ultimo_msg': 0, 'carrito': []}
            
            usuario = MEMORIA_USUARIOS[numero]
            
            # Lógica de Saludo (2 horas)
            debe_saludar = False
            if (ahora - usuario['ultimo_msg'] > 7200 and usuario['ultimo_msg'] != 0) or usuario['ultimo_msg'] == 0:
                debe_saludar = True
                usuario['carrito'] = [] # Reiniciamos carrito si pasó mucho tiempo
            
            if any(s in texto.lower() for s in ["hola", "buenas"]): debe_saludar = True
            
            usuario['ultimo_msg'] = ahora
            historial_txt = "\n".join([f"- {h['rol']}: {h['txt']}" for h in usuario['historial']])

            # --- CEREBRO DE INTENCIÓN ---
            if model:
                # Paso 1: Entender qué quiere hacer
                prompt_det = f"""
                Analiza el mensaje: "{texto}"
                Historial: {historial_txt}
                
                Clasifica en UNA categoría:
                - AGREGAR_CARRITO: [Nombre Producto] (Si dice "quiero el asad", "anota un yara", "me llevo ese")
                - CERRAR_VENTA (Si dice "eso seria", "cuanto es", "manda link", "como pago")
                - CONSULTA_PRODUCTO (Si pregunta "tienes asad?", "que perfumes hay?")
                - INFO_TIENDA (Ubicación, horario, mayorista)
                - OTRO (Saludos, charla)
                """
                try: 
                    decision_raw = model.generate_content(prompt_det).text.strip()
                    decision = decision_raw.split(":")[0].strip()
                    producto_detectado = decision_raw.split(":")[1].strip() if ":" in decision_raw else ""
                except: 
                    decision = "OTRO"
                    producto_detectado = ""

                logging.info(f"🧠 DECISIÓN: {decision} | PROD: {producto_detectado}")

                info_sistema = ""
                
                # --- EJECUCIÓN DE ACCIONES ---
                
                if decision == "AGREGAR_CARRITO":
                    prod_data = buscar_producto_shopify(producto_detectado)
                    if prod_data:
                        usuario['carrito'].append(prod_data)
                        total_parcial = sum(p['price'] for p in usuario['carrito'])
                        info_sistema = f"✅ PRODUCTO AGREGADO: {prod_data['title']}. Total parcial: ${total_parcial:,.0f}. PREGUNTA AL CLIENTE SI QUIERE ALGO MÁS O SUGIERE UN COMPLEMENTO."
                    else:
                        info_sistema = f"❌ No encontré el producto '{producto_detectado}' en Shopify. Pide el nombre más exacto."

                elif decision == "CERRAR_VENTA":
                    if usuario['carrito']:
                        link = crear_carrito_shopify(usuario['carrito'])
                        if link:
                            items_txt = ", ".join([p['title'] for p in usuario['carrito']])
                            info_sistema = f"✅ LINK GENERADO EXITOSAMENTE. Items: {items_txt}. Link: {link}"
                            usuario['carrito'] = [] # Limpiamos carrito tras generar link
                        else:
                            info_sistema = "Error técnico generando el link."
                    else:
                        info_sistema = "El carrito está vacío. Pregunta qué desea llevar primero."

                elif decision == "CONSULTA_PRODUCTO":
                    info_sistema = consultar_catalogo_random(texto)
                    if info_sistema == "NO_HAY_STOCK": info_sistema = "No hay stock exacto. Sugiere ver la web."

                elif decision == "INFO_TIENDA":
                    info_sistema = f"USA ESTA INFO: {INFO_TIENDA}"

                # Paso 2: Generar Respuesta
                instruccion_saludo = "Saluda formalmente" if debe_saludar else "NO SALUDES. Ve al grano."
                
                prompt_final = f"""
                Eres el Vendedor Estrella de Glamstore Chile.
                
                PERSONALIDAD:
                - Formal pero cálido (Usted).
                - PROACTIVO: Siempre intenta vender más (Cross-selling).
                - Si agregó algo al carrito, sugiere otro producto relacionado ("¿Le gustaría agregar...?")
                
                ESTADO:
                - Instrucción Saludo: {instruccion_saludo}
                - Carrito Actual: {len(usuario['carrito'])} productos.
                
                INFO SISTEMA: {info_sistema}
                
                INSTRUCCIONES:
                1. Si Info Sistema tiene un LINK DE PAGO, entrégalo diciendo: "Aquí tiene su pedido listo para pago seguro".
                2. Si Info Sistema dice "PRODUCTO AGREGADO", confirma y ofrece algo más.
                3. NUNCA digas "[Dirección]". Usa los datos reales de abajo.
                
                DATOS REALES:
                {INFO_TIENDA}
                
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
                    logging.error(f"Error Gen: {e}")

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
