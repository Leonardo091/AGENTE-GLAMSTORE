import os
import logging
import threading
import time
import requests
import random
from datetime import datetime, timedelta
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

# --- 2. DATOS FIJOS (SOLO UBICACIÓN, EL RESTO ES DINÁMICO) ---
# Solo dejamos fijo lo que NO cambia en Shopify (Ubicación y Políticas)
INFO_LOGISTICA = """
📍 UBICACIÓN: Santo Domingo 240, Puente Alto (Interior Sandro's Collection).
⚠️ NOTA: "Sandro's Collection" es solo el local donde estamos ubicados. NO vendemos su ropa.
⏰ HORARIOS: Lunes a Viernes 10:00-17:30 | Sábados 10:00-14:30.
💰 MAYORISTA: Contamos con precio detalle y precios mayoristas por volumen (surtido).
"""

# --- 3. MEMORIA & RELOJ ---
MEMORIA_USUARIOS = {} 

def despertar_al_bot():
    while True:
        time.sleep(300)
        try: requests.get(MI_PROPIA_URL)
        except: pass

hilo = threading.Thread(target=despertar_al_bot)
hilo.daemon = True
hilo.start()

def obtener_hora_chile():
    ahora_utc = datetime.utcnow()
    ahora_chile = ahora_utc - timedelta(hours=3) # Ajustar -4 en invierno
    return ahora_chile.strftime("%H:%M")

@app.route("/")
def home(): return "🤖 GLAMBOT DINÁMICO v24", 200

# --- 4. GEMINI ---
model = None
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    try: model = genai.GenerativeModel('gemini-2.0-flash-lite')
    except: model = genai.GenerativeModel('gemini-1.5-flash')

# --- 5. FUNCIONES SHOPIFY (EL CORAZÓN) ---

def escanear_identidad_tienda():
    """
    Saca una muestra de productos para que la IA sepa qué vendemos.
    No busca nada específico, solo 'olfatea' la tienda.
    """
    if not SHOPIFY_TOKEN: return "No hay conexión a Shopify."
    url = f"https://{SHOPIFY_URL.replace('https://','')}/admin/api/2024-01/products.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    try:
        # Traemos 10 productos recientes al azar para definir el rubro
        r = requests.get(url, headers=headers, params={"status": "active", "limit": 15})
        prods = r.json().get("products", [])
        if not prods: return "Tienda vacía."
        
        # Creamos un resumen para la IA
        nombres = [p['title'] for p in prods]
        ejemplos = ", ".join(nombres[:8]) # Tomamos los primeros 8 para no saturar
        return f"PRODUCTOS EN VITRINA (MUESTRA): {ejemplos}..."
    except: return "Error leyendo catálogo."

def buscar_producto_especifico(busqueda):
    if not SHOPIFY_TOKEN: return None
    url = f"https://{SHOPIFY_URL.replace('https://','')}/admin/api/2024-01/products.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    # 1. Búsqueda por nombre
    r = requests.get(url, headers=headers, params={"title": busqueda, "status": "active", "limit": 5})
    prods = r.json().get("products", [])
    
    if not prods:
        # 2. Si falla, búsqueda general (Shuffle)
        r2 = requests.get(url, headers=headers, params={"status": "active", "limit": 40})
        todos = r2.json().get("products", [])
        if not todos: return "NO_STOCK"
        prods = random.sample(todos, min(len(todos), 5))
        es_recomendacion = True
    else:
        es_recomendacion = False

    return {"items": prods, "es_recomendacion": es_recomendacion}

def crear_link_pago(nombre_producto):
    # (Misma lógica de carrito simple)
    if not SHOPIFY_TOKEN: return ""
    url_prod = f"https://{SHOPIFY_URL.replace('https://','')}/admin/api/2024-01/products.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    r = requests.get(url_prod, headers=headers, params={"title": nombre_producto, "status": "active", "limit": 1})
    prods = r.json().get("products", [])
    if not prods: return "NO_ENCONTRE_EXACTO"
    
    v = prods[0]['variants'][0]
    # Creamos Draft Order
    url_draft = f"https://{SHOPIFY_URL.replace('https://','')}/admin/api/2024-01/draft_orders.json"
    payload = {"draft_order": {"line_items": [{"variant_id": v['id'], "quantity": 1}]}}
    r2 = requests.post(url_draft, headers=headers, json=payload)
    if r2.status_code == 201:
        return f"✅ Link: {r2.json().get('draft_order', {}).get('invoice_url')}"
    return "Error link"

# --- 6. WEBHOOK INTELIGENTE ---
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

            # MEMORIA
            ahora_ts = time.time()
            if numero not in MEMORIA_USUARIOS:
                MEMORIA_USUARIOS[numero] = {'historial': deque(maxlen=10), 'ultimo_msg': 0}
            usuario = MEMORIA_USUARIOS[numero]
            
            # Saludo (2 horas)
            debe_saludar = (ahora_ts - usuario['ultimo_msg'] > 7200) or (usuario['ultimo_msg'] == 0)
            if any(s in texto.lower() for s in ["hola", "buenas"]): debe_saludar = True
            usuario['ultimo_msg'] = ahora_ts
            
            historial_txt = "\n".join([f"- {h['rol']}: {h['txt']}" for h in usuario['historial']])

            # --- IDENTIDAD DINÁMICA ---
            # Aquí ocurre la magia: El bot mira qué hay en la tienda para saber quién es
            contexto_productos = escanear_identidad_tienda()

            if model:
                # 1. CLASIFICACIÓN
                prompt_det = f"""
                Mensaje: "{texto}"
                Historial: {historial_txt}
                Clasifica:
                - VENDER_DIRECTO (Quiere link, pagar, comprar)
                - CONSULTAR_CATALOGO (Pregunta qué tienen, perfumes, buscar producto)
                - INFO_LOGISTICA (Ubicación, horario, mayorista)
                - CHARLA
                """
                try: decision = model.generate_content(prompt_det).text.strip().split()[0]
                except: decision = "CHARLA"

                info_sistema = ""

                # 2. DATOS
                if "VENDER_DIRECTO" in decision:
                    info_sistema = crear_link_pago(texto)
                    if "NO_ENCONTRE" in info_sistema: info_sistema = "Pide el nombre exacto del producto."

                elif "CONSULTAR_CATALOGO" in decision:
                    resultado = buscar_producto_especifico(texto)
                    if resultado == "NO_STOCK":
                        info_sistema = "No hay productos. Manda a la web."
                    else:
                        tipo_lista = "RESULTADOS EXACTOS" if not resultado['es_recomendacion'] else "RECOMENDACIONES (No exacto)"
                        txt_prods = "\n".join([f"- {p['title']} (${float(p['variants'][0]['price']):,.0f})" for p in resultado['items']])
                        info_sistema = f"{tipo_lista}:\n{txt_prods}"

                elif "INFO_LOGISTICA" in decision:
                    info_sistema = f"Hora actual: {obtener_hora_chile()}.\n{INFO_LOGISTICA}"

                # 3. GENERADOR DE RESPUESTA (AUTO-PERCEPCIÓN)
                instruccion_saludo = "Saluda formal (Usted)" if debe_saludar else "NO SALUDES"
                
                prompt_final = f"""
                Eres el Asistente Inteligente de Glamstore Chile.
                
                AUTO-ANÁLISIS DE IDENTIDAD (IMPORTANTE):
                Mira los productos que acabas de escanear en Shopify:
                [{contexto_productos}]
                
                INSTRUCCIONES:
                1. BASADO EN LA LISTA DE ARRIBA, define qué tipo de tienda eres. 
                   - Si ves perfumes -> Eres Perfumería.
                   - Si ves maquillaje -> Eres Tienda de Belleza.
                   - Si ves ambos -> Eres Tienda de Perfumería y Cosmética.
                   - NO DIGAS QUE VENDES ROPA (Aunque la dirección diga Sandro's Collection).
                
                2. Si el cliente pregunta "¿Qué venden?", responde basándote ÚNICAMENTE en los productos que ves en el escaneo de arriba.
                
                3. {instruccion_saludo}. Sé amable y usa emojis.
                
                INFO PARA RESPONDER AHORA:
                {info_sistema}
                
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
