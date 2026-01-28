import os
import logging
import time
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import google.generativeai as genai
from collections import deque
from database import db 

# Logs limpios
logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.basicConfig(level=logging.INFO, format='%(message)s')
app = Flask(__name__)

# Credenciales
TOKEN_WHATSAPP = os.environ.get("WHATSAPP_TOKEN")
API_KEY_GEMINI = os.environ.get("GEMINI_API_KEY")

# Memoria de corto plazo
MEMORIA_USUARIOS = {}

# --- UTILIDADES ---
def despertar_render():
    while True:
        time.sleep(300)
        try: requests.get("https://agente-glamstore.onrender.com")
        except: pass

import threading
hilo_ping = threading.Thread(target=despertar_render)
hilo_ping.daemon = True
hilo_ping.start()

# --- CONFIGURACIÓN IA ---
model = None
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    # Usamos flash-lite si existe, sino el flash normal
    try: model = genai.GenerativeModel('gemini-2.0-flash-lite')
    except: model = genai.GenerativeModel('gemini-1.5-flash')

# --- RUTA PRINCIPAL ---
@app.route("/")
def home():
    estado = "🟢 OPERATIVO" if db.total_items > 0 else "⚠️ CARGANDO INVENTARIO"
    return jsonify({
        "status": estado, 
        "productos_en_ram": db.total_items, 
        "mensaje": "Sistema Elite v4.0 Activo."
    }), 200

# --- CEREBRO DEL CHATBOT ---
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

            # Gestión de Sesión
            ahora_ts = time.time()
            if numero not in MEMORIA_USUARIOS:
                MEMORIA_USUARIOS[numero] = {'historial': deque(maxlen=6), 'ultimo_msg': 0}
            usuario = MEMORIA_USUARIOS[numero]
            
            # Contexto Histórico
            historial_txt = "\n".join([f"User: {h['txt']}\nBot: {h['resp']}" for h in usuario['historial']])

            if model:
                # --- PASO 1: LA IA DECIDE LA ESTRATEGIA (ROUTER) ---
                prompt_router = f"""
                Actúa como el cerebro de un eCommerce de Belleza.
                Cliente: "{texto}"
                Historial reciente: {historial_txt}
                
                Analiza la intención y clasifica en UNA de estas categorías:
                
                1. RECOMENDAR: El cliente pide "ejemplos", "qué venden", "dame un artículo", "muéstrame algo".
                2. BUSCAR_ESPECIFICO: El cliente pide un producto concreto (ej: "tienes yara", "busco rimel").
                3. GENERAR_LINK: El cliente dice explícitamente "quiero comprar esto", "dame el link", "lo llevo".
                4. INFO_TIENDA: Horarios, ubicación, envíos, "tienen mayorista".
                5. QUEJA_O_CHARLA: Saludos, "hablas feo", "no entiendo", quejas sobre el bot.
                
                Responde SOLO la categoría.
                """
                try: 
                    intencion = model.generate_content(prompt_router).text.strip().upper()
                except: 
                    intencion = "CHARLA"
                
                logging.info(f"🧠 Intención detectada: {intencion}")

                # --- PASO 2: RECOLECCIÓN DE DATOS (SEGÚN INTENCIÓN) ---
                contexto_data = ""
                
                if "RECOMENDAR" in intencion:
                    # Sacamos 5 productos al azar para vitrinear
                    items = db.obtener_recomendados(5)
                    lista = ", ".join([f"{p['title']} (${p['price']:,.0f})" for p in items])
                    contexto_data = f"DATA DEL SISTEMA: Aquí tienes algunos productos destacados de nuestro stock: {lista}"
                
                elif "BUSCAR_ESPECIFICO" in intencion:
                    res = db.buscar_inteligente(texto)
                    if res["tipo"] == "VACIO":
                        contexto_data = "DATA DEL SISTEMA: No encontré coincidencias exactas en el inventario."
                    else:
                        lista = ", ".join([f"{p['title']} (${p['price']:,.0f})" for p in res["items"]])
                        contexto_data = f"DATA DEL SISTEMA: Encontré esto en stock: {lista}"
                
                elif "GENERAR_LINK" in intencion:
                    checkout = db.generar_checkout(texto)
                    if checkout:
                        contexto_data = f"DATA DEL SISTEMA: Link generado exitosamente para '{checkout['nombre']}': {checkout['url']}"
                    else:
                        contexto_data = "DATA DEL SISTEMA: Error. No pude identificar qué producto quiere pagar. Pide el nombre exacto."
                
                elif "INFO_TIENDA" in intencion:
                    contexto_data = """
                    DATA DEL SISTEMA: 
                    - Dirección: Santo Domingo 240, Puente Alto.
                    - Horario: Lun-Vie 10:00 AM - 05:30 PM | Sáb 10:00 AM - 02:30 PM.
                    - Mayorista: Solo presencial en tienda. Por aquí solo venta al detalle con link.
                    - Envíos: Sí, a todo Chile.
                    """

                # --- PASO 3: GENERACIÓN DE RESPUESTA FINAL (EL COPYWRITER) ---
                prompt_final = f"""
                Eres "GlamBot", un vendedor experto, empático y profesional de Glamstore Chile.
                
                TU OBJETIVO: Vender y fidelizar.
                TU PERSONALIDAD: Amable, paciente, usa emojis moderados ✨. JAMÁS suenes como un robot tonto ("No entiendo").
                
                INFORMACIÓN TÉCNICA (DATA):
                {contexto_data}
                
                INSTRUCCIONES CLAVE POR CASO:
                - Si el cliente se queja ("hablas feo", "tonto"): Pide disculpas con elegancia y di que estás aprendiendo para atenderle mejor.
                - Si preguntan "¿Qué venden?" o "Dame un ejemplo": Usa la lista de productos destacados que te pasé en la DATA.
                - Si preguntan por Mayorista: Di amable que por WhatsApp es solo detalle, pero que vaya a la tienda para precios mayoristas.
                - Si la DATA dice "No encontré": Ofrece ayuda para buscar otra cosa similar.
                - Si preguntan "Puedo comprar por acá": DI QUE SÍ. Generamos links de pago seguros.
                
                Chat previo:
                {historial_txt}
                
                Cliente dice: "{texto}"
                Respuesta de GlamBot:
                """
                
                try:
                    resp_final = model.generate_content(prompt_final).text.strip()
                    # Limpieza final por si acaso
                    resp_final = resp_final.replace("Bot:", "").replace("GlamBot:", "").replace("Respuesta:", "")
                    
                    # Guardamos en memoria
                    usuario['historial'].append({"txt": texto, "resp": resp_final})
                    
                    # Enviamos
                    requests.post(
                        "https://graph.facebook.com/v21.0/939839529214459/messages",
                        headers={"Authorization": f"Bearer {TOKEN_WHATSAPP}", "Content-Type": "application/json"},
                        json={"messaging_product": "whatsapp", "to": numero, "type": "text", "text": {"body": resp_final}}
                    )
                except Exception as e: logging.error(f"Error Gen: {e}")

        return jsonify({"status": "ok"}), 200
    except: return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
