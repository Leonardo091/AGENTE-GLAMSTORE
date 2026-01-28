import os
import logging
import time
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import google.generativeai as genai
from collections import deque
from database import db 

# Configuración de Logs
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)

app = Flask(__name__)

# Cargar variables de entorno
TOKEN_WHATSAPP = os.environ.get("WHATSAPP_TOKEN")
API_KEY_GEMINI = os.environ.get("GEMINI_API_KEY")
VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "glamstore_verify_token") # ACTUALIZADO: Coincide con tu Render

# Configurar Gemini
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    model = genai.GenerativeModel('gemini-2.0-flash')
else:
    logging.error("❌ NO SE ENCONTRÓ GEMINI_API_KEY")
    model = None

MEMORIA_USUARIOS = {}

# Keep-alive para Render (Opcional, mejor usar un cron externo si es posible)
def despertar_render():
    while True:
        time.sleep(300) # Cada 5 minutos
        try:
            # Reemplaza con tu URL real si la sabes, o usa localhost para evitar errores locales
            render_url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:10000")
            requests.get(render_url)
            logging.info("⏰ Ping keep-alive enviado")
        except Exception as e:
            logging.debug(f"Ping fallido (normal en local): {e}")

import threading
hilo_ping = threading.Thread(target=despertar_render)
hilo_ping.daemon = True
hilo_ping.start()

@app.route("/")
def home():
    return jsonify({
        "status": "ONLINE", 
        "productos_cargados": db.total_items, 
        "mensaje": "El cerebro de GlamStore está activo 💅"
    }), 200

@app.route("/debug/inventory")
def debug_inventory():
    """Endpoint para verificar el estado interno del inventario."""
    estado = db.get_status()
    # Si quieres protegerlo levemente:
    token = request.args.get("token")
    # if token != "tu_secreto": return "Acceso denegado", 403
    
    return jsonify(estado), 200

# Endpoint de Verificación (Requerido por Meta)
# Endpoint ÚNICO (Como estaba antes)
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    # 1. VERIFICACIÓN (GET) - Meta siempre hace esto primero
    if request.method == "GET":
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return request.args.get("hub.challenge")
        return "Error de validacion", 403

    # 2. MENSAJES (POST)
    try:
        body = request.get_json()
        logging.info(f"📨 WEBHOOK RECIBIDO: {body}")
        
        if not body or "entry" not in body:
            return jsonify({"status": "ignored"}), 200

        entry = body["entry"][0]["changes"][0]["value"]

        if "messages" in entry:
            msg = entry["messages"][0]
            numero = msg["from"]
            texto = msg.get("text", {}).get("body", "")
            nombre = entry.get("contacts", [{}])[0].get("profile", {}).get("name", "Cliente")
            
            # Gestión de memoria
            if numero not in MEMORIA_USUARIOS:
                MEMORIA_USUARIOS[numero] = {'historial': deque(maxlen=6), 'ultimo_msg': time.time()}
            usuario = MEMORIA_USUARIOS[numero]
            
            historial_txt = "\n".join([f"User: {h['txt']}\nBot: {h['resp']}" for h in usuario['historial']])

            if model:
                procesar_inteligencia_artificial(numero, nombre, texto, historial_txt, usuario)
            
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logging.error(f"🔥 ERROR: {e}")
        return jsonify({"status": "error"}), 500



def procesar_inteligencia_artificial(numero, nombre, texto, historial_txt, usuario):
    try:
        # 1. INTENCIÓN
        prompt_router = f"""
        Actúa como un clasificador de intenciones para una tienda de maquillaje y belleza llamada "GlamStore".
        Analiza el siguiente mensaje del cliente: "{texto}"
        
        Categorías posibles:
        1. CATALOGO: Preguntan qué venden, piden recomendaciones, buscan un tipo de producto (labial, rimel, perfume).
        2. COMPRAR: Quieren comprar algo específico, piden precio de un producto exacto, o piden link de pago.
        3. SOPORTE: Preguntan envío, horario, ubicación, reclamos.
        4. CHARLA: Saludos, agradecimientos, mensajes casuales.
        
        Historial reciente:
        {historial_txt}
        
        Responde SOLO con una de las palabras: CATALOGO, COMPRAR, SOPORTE, CHARLA.
        """
        try:
            intencion_raw = model.generate_content(prompt_router).text.strip().upper()
            # Limpiar por si el modelo responde algo como "La categoría es CATALOGO"
            if "CATALOGO" in intencion_raw: intencion = "CATALOGO"
            elif "COMPRAR" in intencion_raw: intencion = "COMPRAR"
            elif "SOPORTE" in intencion_raw: intencion = "SOPORTE"
            else: intencion = "CHARLA"
        except Exception as e:
            logging.error(f"Error clasificando intención: {e}")
            intencion = "CHARLA"

        logging.info(f"🧠 Intención detectada: {intencion}")

        # 2. DATA MINING (Buscar información relevante)
        contexto_data = ""
        link_pago = None
        
        if intencion in ["CATALOGO", "COMPRAR"]:
            # Buscamos en la base de datos
            res = db.buscar_contextual(texto)
            
            if res["tipo"] == "VACIO":
                contexto_data = "INVENTARIO: No encontré productos similares en el stock actual."
            elif res["tipo"] == "RECOMENDACION_REAL":
                lista = "\n".join([f"- {p['title']} (${p['price']:,.0f})" for p in res["items"]])
                contexto_data = f"INVENTARIO RECOMENDADO:\n{lista}"
            else: # EXACTO
                lista = "\n".join([f"- {p['title']} (${p['price']:,.0f})" for p in res["items"]])
                contexto_data = f"PRODUCTO ENCONTRADO:\n{lista}"
                
            if intencion == "COMPRAR" and res["items"]:
                # Intentamos generar link solo si hay intención de compra clara
                datos_link = db.generar_checkout(texto)
                if datos_link:
                    link_pago = datos_link['url']
                    contexto_data += f"\n\nLINK DE PAGO YA GENERADO: {link_pago}"

        elif intencion == "SOPORTE":
            contexto_data = """
            INFO TIENDA GLAMSTORE:
            - 📍 Ubicación Exacta: Santo Domingo 240, Puente Alto (Interior "Sandros Collections").
            - ⏰ Horario: Lun-Vie 10:00 a 18:00 hrs | Sáb 10:00 a 15:00 hrs.
            - 📞 Contacto: +56 9 7207 9712 | glamstorechile2019@gmail.com
            - 🚚 Envíos: A todo Chile (Starken/Chilexpress).
            """

        # 3. GENERACIÓN DE RESPUESTA (Prompt Búnker)
        prompt_final = f"""
        Eres "GlamBot", la asesora experta de GlamStore Chile.
        Tu tono es: Amable, chic, profesional y útil. Usas emojis con moderación (💅, ✨, 💄).
        
        === DATOS DEL SISTEMA (TU VERDAD ABSOLUTA) ===
        {contexto_data}
        
        === INSTRUCCIONES ===
        1. Responde al cliente {nombre} basándote SOLO en los "DATOS DEL SISTEMA".
        2. Si te preguntan por un producto y NO está en la lista de arriba, di amablemente que no queda stock por ahora. ¡No inventes productos!
        3. Si tienes una lista de productos, ofrécelos con sus precios.
        4. Si se generó un LINK DE PAGO en los datos, entrégaselo al cliente diciendo "Aquí tienes tu link directo:".
        5. Sé concisa. Respuestas de máximo 3-4 líneas a menos que sea una lista.
        
        Chat previo:
        {historial_txt}
        User: "{texto}"
        Bot:
        """
        
        resp_final = model.generate_content(prompt_final).text.strip()
        # Limpieza final
        resp_final = resp_final.replace("Bot:", "").replace("GlamBot:", "").strip()
        
        # Guardar en memoria
        usuario['historial'].append({"txt": texto, "resp": resp_final})
        
        enviar_whatsapp(numero, resp_final)

    except Exception as e:
        logging.error(f"Error procesando IA: {e}")
        # Opcional: Enviar mensaje de error al usuario o fallar silenciosamente seguro

def enviar_whatsapp(numero, texto):
    if not TOKEN_WHATSAPP:
        logging.warning("⚠️ No se envió mensaje porque no hay WHATSAPP_TOKEN")
        return

    url = "https://graph.facebook.com/v21.0/556942767500127/messages" 
    
    # ID de número de teléfono (Phone Number ID) - ACTUALIZADO
    PHONE_NUMBER_ID = os.environ.get("META_PHONE_ID", "939839529214459") 
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    
    headers = {
        "Authorization": f"Bearer {TOKEN_WHATSAPP}", 
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp", 
        "to": numero, 
        "type": "text", 
        "text": {"body": texto}
    }
    
    try:
        r = requests.post(url, headers=headers, json=data)
        if r.status_code not in [200, 201]:
            logging.error(f"Error enviando a WhatsApp: {r.text}")
        else:
            logging.info(f"📤 Respuesta enviada a {numero}")
    except Exception as e:
        logging.error(f"Error request WhatsApp: {e}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
