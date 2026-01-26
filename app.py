import os
import logging
from flask import Flask, request, jsonify
import requests
import google.generativeai as genai

# Configuración básica
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# 1. CONFIGURACIÓN DE CREDENCIALES
TOKEN_WHATSAPP = os.environ.get("WHATSAPP_TOKEN")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
API_KEY_GEMINI = os.environ.get("GEMINI_API_KEY")

# 2. CONFIGURAMOS GEMINI
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    
    # ¡AQUÍ ESTÁ EL CAMBIO! Usamos el modelo que apareció en tu lista
    # gemini-2.0-flash es rapidísimo y potente
    model = genai.GenerativeModel('gemini-2.0-flash') 
else:
    logging.error("¡FALTA LA GEMINI_API_KEY EN RENDER!")

# 3. RUTA PARA VERIFICACIÓN
@app.route("/webhook", methods=["GET"])
def verificar_token():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logging.info("WEBHOOK VERIFICADO CORRECTAMENTE")
        return challenge, 200
    else:
        return "Error de verificación", 403

# 4. RUTA PARA RECIBIR MENSAJES
@app.route("/webhook", methods=["POST"])
def recibir_mensajes():
    try:
        body = request.get_json()
        entry = body["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        if "messages" in value:
            mensaje = value["messages"][0]
            numero = mensaje["from"]
            texto_usuario = mensaje["text"]["body"]
            
            logging.info(f"📩 MENSAJE DE {numero}: {texto_usuario}")

            # --- MAGIA GEMINI ---
            try:
                # Le preguntamos al modelo 2.0
                response = model.generate_content(texto_usuario)
                respuesta_gemini = response.text
                logging.info(f"🤖 GEMINI 2.0 RESPONDE: {respuesta_gemini}")
                
                enviar_whatsapp(numero, respuesta_gemini)
                
            except Exception as e:
                logging.error(f"❌ ERROR CEREBRAL: {str(e)}")
                enviar_whatsapp(numero, "Tuve un pequeño error mental, pero sigo vivo. Intenta de nuevo.")
            # --------------------

        return jsonify({"status": "recibido"}), 200

    except Exception as e:
        return jsonify({"status": "evento_ignorado"}), 200

# 5. FUNCIÓN PARA ENVIAR
def enviar_whatsapp(numero, texto):
    # Tu ID de teléfono confirmado
    url = "https://graph.facebook.com/v21.0/939839529214459/messages"
    
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

    response = requests.post(url, headers=headers, json=data)
    if response.status_code != 200:
        logging.error(f"❌ ERROR AL ENVIAR: {response.text}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
