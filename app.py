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

# --- 2. DATOS DE RESPALDO (EL PLAN B) ---
# Si Shopify falla, el bot usará esto en vez de decir "no sé quién soy".
IDENTIDAD_BACKUP = """
SOMOS UNA TIENDA DE: Perfumería (Árabe y de diseñador), Maquillaje y productos de belleza capilar.
NO VENDEMOS ROPA (Sandro's Collection es solo el local vecino).
"""

INFO_LOGISTICA = """
📍 UBICACIÓN: Santo Domingo 240, Puente Alto (Interior Sandro's Collection).
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
    ahora_chile = ahora_utc - timedelta(hours=3) 
    return ahora_chile.strftime("%H:%M")

@app.route("/")
def home(): return "🤖 GLAMBOT HÍBRIDO v25", 200

# --- 4. GEMINI ---
model = None
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    try: model = genai.GenerativeModel('gemini-2.0-flash-lite')
    except: model = genai.GenerativeModel('gemini-1.5-flash')

# --- 5. FUNCIONES SHOPIFY (CON RED DE SEGURIDAD) ---

def escanear_identidad_tienda():
    """
    Intenta leer Shopify. Si falla, devuelve la IDENTIDAD_BACKUP.
    """
    if not SHOPIFY_TOKEN: 
        logging.error("❌ ERROR: Faltan credenciales de Shopify.")
        return IDENTIDAD_BACKUP
        
    url = f"https://{SHOPIFY_URL.replace('https://','')}/admin/api/2024-01/products.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    try:
        r = requests.get(url, headers=headers, params={"status": "active", "limit": 10})
        if r.status_code != 200:
            logging.error(f"❌ ERROR SHOPIFY: {r.status_code} - {r.text}")
            return IDENTIDAD_BACKUP # Falló la API -> Usamos respaldo
            
        prods = r.json().get("products", [])
        if not prods: 
            logging.warning("⚠️ ALERTA: Shopify devolvió 0 productos.")
            return IDENTIDAD_BACKUP # Lista vacía -> Usamos respaldo
        
        # Si todo sale bien, construimos la identidad dinámica
        nombres = [p['title'] for p in prods]
        ejemplos = ", ".join(nombres)
        return f"ESTO VEMOS EN VITRINA HOY: {ejemplos}..."
        
    except Exception as e:
        logging.error(f"❌ ERROR CRÍTICO CONEXIÓN: {e}")
        return IDENTIDAD_BACKUP

def buscar_producto_especifico(busqueda):
    if not SHOPIFY_TOKEN: return None
    url = f"https://{SHOPIFY_URL.replace('https://','')}/admin/api/2024-01/products.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    try:
        r = requests.get(url, headers=headers, params={"title": busqueda, "status": "active", "limit": 5})
        prods = r.json().get("products", [])
        
        if not prods:
            r2 = requests.get(url, headers=headers, params={"status": "active", "limit": 30})
            todos = r2.json().get("products", [])
            if not todos: return "NO_STOCK"
            prods = random.sample(todos, min(len(todos), 5))
            es_recomendacion = True
        else:
            es_recomendacion = False

        return {"items": prods, "es_recomendacion": es_recomendacion}
    except: return "NO_STOCK"

def crear_link_pago(nombre_producto):
    if not SHOPIFY_TOKEN: return ""
    url_prod = f"https://{SHOPIFY_URL.replace('https://','')}/admin/api/2024-01/products.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    
    try:
        r = requests.get(url_prod, headers=headers, params={"title": nombre_producto, "status": "active", "limit": 1})
        prods = r.json().get("products", [])
        if not prods: return "NO_ENCONTRE_EXACTO"
        
        v = prods[0]['variants'][0]
        url_draft = f"https://{SHOPIFY_URL.replace('https://','')}/admin/api/2024-01/draft_orders.json"
        payload = {"draft_order": {"line_items": [{"variant_id": v['id'], "quantity": 1}]}}
        r2 = requests.post(url_draft, headers=headers, json=payload)
        if r2.status_code == 201:
            return f"✅ Link: {r2.json().get('draft_order', {}).get('invoice_url')}"
    except: pass
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
            
            debe_saludar = (ahora_ts - usuario['ultimo_msg'] > 7200) or (usuario['ultimo_msg'] == 0)
            if any(s in texto.lower() for s in ["hola", "buenas"]): debe_saludar = True
            usuario['ultimo_msg'] = ahora_ts
            
            historial_txt = "\n".join([f"- {h['rol']}: {h['txt']}" for h in usuario['historial']])

            # --- IDENTIDAD ROBUSTA (AQUÍ ESTÁ EL ARREGLO) ---
            # Si el escaneo falla, usará el backup automáticamente.
            contexto_productos = escanear_identidad_tienda()

            if model:
                # 1. CLASIFICACIÓN
                prompt_det = f"""
                Mensaje: "{texto}"
                Historial: {historial_txt}
                Clasifica:
                - VENDER_DIRECTO (Quiere link, pagar)
                - CONSULTAR_CATALOGO (Pregunta qué tienen, perfumes)
                - INFO_LOGISTICA (Ubicación, horario)
                - CHARLA
                """
                try: decision = model.generate_content(prompt_det).text.strip().split()[0]
                except: decision = "CHARLA"

                info_sistema = ""

                # 2. DATOS
                if "VENDER_DIRECTO" in decision:
                    info_sistema = crear_link_pago(texto)
                    if "NO_ENCONTRE" in info_sistema: info_sistema = "Pide el nombre exacto."

                elif "CONSULTAR_CATALOGO" in decision:
                    resultado = buscar_producto_especifico(texto)
                    if resultado == "NO_STOCK":
                        info_sistema = "No hay productos disponibles por ahora. Sugiere ver la web."
                    else:
                        tipo = "RESULTADOS" if not resultado['es_recomendacion'] else "RECOMENDACIONES"
                        txt_prods = "\n".join([f"- {p['title']} (${float(p['variants'][0]['price']):,.0f})" for p in resultado['items']])
                        info_sistema = f"{tipo}:\n{txt_prods}"

                elif "INFO_LOGISTICA" in decision:
                    info_sistema = f"Hora: {obtener_hora_chile()}.\n{INFO_LOGISTICA}"

                # 3. GENERADOR (CON MORDAZA ANTI-ERRORES)
                instruccion_saludo = "Saluda formal (Usted)" if debe_saludar else "NO SALUDES"
                
                prompt_final = f"""
                Eres el Asistente de Glamstore Chile.
                
                TU IDENTIDAD (Lo que vendemos):
                {contexto_productos}
                
                REGLAS DE ORO:
                1. JAMÁS digas "el escaneo está vacío" ni menciones errores técnicos. Si no sabes qué vendemos, asume que somos Perfumería y Belleza.
                2. NO VENDEMOS ROPA.
                3. {instruccion_saludo}.
                
                INFO RESPUESTA:
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
