import os
import logging
import threading
import time
import requests
import random
import re # Para limpiar descripciones HTML
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

# --- 2. CONFIGURACIÓN DEL NEGOCIO (TU VERDAD) ---

# POLÍTICA DE MAYORISTA (TEXTUAL COMO LO PEDISTE)
TEXTO_MAYORISTA = """
Mire, contamos con un servicio de precio al detalle, pero si usted está buscando comprar por volumen, 
podemos ofrecerle precios mayoristas dependiendo de los artículos que quiera consultar y de sus respectivas cantidades (puede ser surtido igualmente).
"""

# INFO GENERAL
INFO_TIENDA = f"""
📍 UBICACIÓN: Santo Domingo 240, Puente Alto (Interior Sandro's Collection).
⏰ HORARIOS: Lunes a Viernes 10:00-17:30 | Sábados 10:00-14:30.
🚛 ENVÍOS: A todo Chile.
🌐 WEB OFICIAL: www.glamstorechile.cl
💰 SOBRE VENTAS AL POR MAYOR: {TEXTO_MAYORISTA}
"""

# DICCIONARIO DE LINKS DE COLECCIONES (PARA QUE SEA MÁS PRO)
# Si el cliente pide una categoría, el bot buscará aquí el link directo.
LINKS_COLECCIONES = {
    "perfume": "https://www.glamstorechile.cl/collections/perfumeria",
    "perfumes": "https://www.glamstorechile.cl/collections/perfumeria",
    "arabe": "https://www.glamstorechile.cl/collections/perfumes-arabes",
    "maquillaje": "https://www.glamstorechile.cl/collections/maquillaje",
    "capilar": "https://www.glamstorechile.cl/collections/capilar",
    "general": "https://www.glamstorechile.cl/collections/all"
}

# --- 3. MEMORIA AVANZADA (CON CRONÓMETRO) ---
# Estructura: { 'numero': { 'historial': deque, 'ultimo_msg': timestamp } }
MEMORIA_USUARIOS = {} 

def despertar_al_bot():
    while True:
        time.sleep(300) # Cada 5 min
        try: requests.get(MI_PROPIA_URL)
        except: pass

hilo = threading.Thread(target=despertar_al_bot)
hilo.daemon = True
hilo.start()

@app.route("/")
def home(): return "🤖 GLAMBOT FORMAL v21 ONLINE", 200

# --- 4. CONFIGURACIÓN GEMINI ---
model = None
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    try: model = genai.GenerativeModel('gemini-2.0-flash-lite')
    except: model = genai.GenerativeModel('gemini-1.5-flash')

# --- 5. FUNCIONES SHOPIFY PROFUNDAS ---
def limpiar_html(texto_html):
    # Quita las etiquetas <p>, <br> para que se lea bien en WhatsApp
    clean = re.compile('<.*?>')
    return re.sub(clean, '', texto_html)

def consultar_productos(busqueda):
    if not SHOPIFY_TOKEN: return ""
    tienda_url = SHOPIFY_URL.replace("https://", "").replace("/", "")
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    # 1. Detectar si es categoría general
    busqueda_lower = busqueda.lower()
    es_general = any(x in busqueda_lower for x in ["todo", "catalogo", "perfumes", "perfume", "lista", "que tiene", "productos"])
    
    # Determinar Link de Colección
    link_extra = LINKS_COLECCIONES.get("general")
    for key, url in LINKS_COLECCIONES.items():
        if key in busqueda_lower:
            link_extra = url
            break

    # 2. Estrategia de Búsqueda
    if es_general:
        # Traemos 50 productos para barajar
        params = {"status": "active", "limit": 50}
        intro_txt = "Aquí le presento una selección de nuestros productos disponibles:\n"
    else:
        # Búsqueda específica
        params = {"title": busqueda, "status": "active", "limit": 20}
        intro_txt = f"He encontrado estas opciones relacionadas con '{busqueda}':\n"

    try:
        r = requests.get(f"https://{tienda_url}/admin/api/2024-01/products.json", headers=headers, params=params)
        prods = r.json().get("products", [])
        
        if not prods:
            if not es_general:
                # Fallback: Shuffle general
                r2 = requests.get(f"https://{tienda_url}/admin/api/2024-01/products.json", headers=headers, params={"status": "active", "limit": 40})
                prods = r2.json().get("products", [])
                intro_txt = f"Disculpe, no encontré stock exacto para '{busqueda}', pero mire estas novedades:\n"
            
            if not prods: return "NO_HAY_STOCK"

        # 3. Barajado y Selección (Shuffle)
        cantidad = 5
        seleccionados = random.sample(prods, min(len(prods), cantidad))
        
        txt = intro_txt
        for p in seleccionados:
            v = p['variants'][0]
            precio = float(v['price'])
            # Agregamos un fragmento de la descripción si existe, pero corto
            desc = p.get('body_html', '')
            if desc:
                desc_limpia = limpiar_html(desc)[:50] + "..." # Solo los primeros 50 caracteres
            else:
                desc_limpia = ""
                
            txt += f"🔹 {p['title']}\n   Valor: ${precio:,.0f}\n"
        
        txt += f"\n📌 Puede ver la colección completa y detalles aquí: {link_extra}"
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
    
    if not products: return "NO_ENCONTRE_EXACTO"
    
    v = products[0]['variants'][0]
    payload = {"draft_order": {"line_items": [{"variant_id": v['id'], "quantity": 1}]}}
    r2 = requests.post(f"https://{tienda_url}/admin/api/2024-01/draft_orders.json", headers=headers, json=payload)
    if r2.status_code == 201:
        data = r2.json().get("draft_order", {})
        return f"✅ He generado su link de pago para {products[0]['title']} (${float(v['price']):,.0f}):\n👉 {data.get('invoice_url')}"
    return ""

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
            nombre_cliente = entry.get("contacts", [{}])[0].get("profile", {}).get("name", "Cliente")

            logging.info(f"📩 {nombre_cliente}: {texto}")

            # --- LÓGICA DE MEMORIA TEMPORAL (2 HORAS) ---
            ahora = time.time()
            tiempo_limite = 7200 # 2 horas en segundos

            if numero not in MEMORIA_USUARIOS:
                MEMORIA_USUARIOS[numero] = {'historial': deque(maxlen=10), 'ultimo_msg': 0}
            
            usuario = MEMORIA_USUARIOS[numero]
            tiempo_pasado = ahora - usuario['ultimo_msg']
            
            # Decidimos si saludamos o no
            debe_saludar = False
            
            # CASO A: Pasaron más de 2 horas -> Reseteamos saludo
            if tiempo_pasado > tiempo_limite and usuario['ultimo_msg'] != 0:
                debe_saludar = True
                usuario['historial'].clear() # Limpiamos historial viejo para no confundir
            
            # CASO B: Es la primera vez -> Saludamos
            elif usuario['ultimo_msg'] == 0:
                debe_saludar = True

            # CASO C: El cliente dice "Hola" explícitamente -> Saludamos por educación
            saludos_cliente = ["hola", "buenas", "buenos dias", "holii", "alo"]
            if any(s in texto.lower() for s in saludos_cliente):
                debe_saludar = True

            # Actualizamos la hora del último mensaje
            usuario['ultimo_msg'] = ahora
            
            # Generamos el contexto para el Prompt
            historial_txt = "\n".join([f"- {h['rol']}: {h['txt']}" for h in usuario['historial']])

            if model:
                # 1. Detector de Intención
                prompt_det = f"""
                Analiza: "{texto}"
                Historial: {historial_txt}
                Clasifica: TIENDA, PRODUCTO, COMPRAR, MAYORISTA, OTRO.
                """
                try: decision = model.generate_content(prompt_det).text.strip().upper()
                except: decision = "OTRO"

                info_sistema = ""
                
                if "TIENDA" in decision:
                    info_sistema = f"USA ESTA INFO: {INFO_TIENDA}"
                elif "MAYORISTA" in decision:
                    info_sistema = f"USA TEXTUALMENTE ESTA POLÍTICA: {TEXTO_MAYORISTA}"
                elif "PRODUCTO" in decision:
                    res_shopify = consultar_productos(texto)
                    if res_shopify == "NO_HAY_STOCK":
                        info_sistema = "Indica que pueden revisar el catálogo completo en www.glamstorechile.cl"
                    else:
                        info_sistema = res_shopify
                elif "COMPRAR" in decision:
                     info_sistema = crear_link_pago(texto) 
                     if "NO_ENCONTRE" in info_sistema:
                         info_sistema = "Solicita amablemente el nombre exacto del producto."

                # 2. Generador con PERSONALIDAD FORMAL (NIVEL 2)
                instruccion_saludo = ""
                if debe_saludar:
                    instruccion_saludo = f"Saluda formalmente pero con calidez a {nombre_cliente}. (Ej: Hola {nombre_cliente}, bienvenido/a...)"
                else:
                    instruccion_saludo = "NO SALUDES. Continúa la conversación directamente. Trata de USTED."

                prompt_final = f"""
                Eres el Asistente Virtual de Glamstore Chile.
                
                PERSONALIDAD:
                - Tono: Formal, respetuoso, servicial (Nivel 2/10).
                - Trato: Siempre de "USTED".
                - Objetivo: Resolver dudas con eficiencia y amabilidad.
                
                INSTRUCCIONES CLAVE:
                1. {instruccion_saludo}
                2. Si preguntan por mayorista, usa la política definida.
                3. Si muestras productos, invita a ver detalles en el link.
                
                INFO SISTEMA: {info_sistema}
                
                HISTORIAL:
                {historial_txt}
                CLIENTE DIJO: "{texto}"
                """
                
                try:
                    res = model.generate_content(prompt_final)
                    respuesta = res.text
                    
                    # Guardamos en historial
                    usuario['historial'].append({"rol": nombre_cliente, "txt": texto})
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
