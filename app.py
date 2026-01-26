import os
import logging
from flask import Flask, request, jsonify
import requests
import google.generativeai as genai  # <-- IMPORTAMOS GEMINI

# Configuración básica
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# 1. CONFIGURACIÓN DE CREDENCIALES
TOKEN_WHATSAPP = os.environ.get("WHATSAPP_TOKEN")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
API_KEY_GEMINI = os.environ.get("GEMINI_API_KEY") # <-- TOMAMOS LA LLAVE DE RENDER

# 2. CONFIGURAMOS GEMINI
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    # Usamos el modelo rápido y bueno para chat
    model = genai.GenerativeModel('gemini-1.5-flash') 
else:
    logging.error("¡FALTA LA GEMINI_API_KEY EN RENDER!")

# 3. RUTA PARA VERIFICACIÓN (El saludo con Meta)
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

# 4. RUTA PARA RECIBIR MENSAJES (El Oído)
@app.route("/webhook", methods=["POST"])
def recibir_mensajes():
    try:
        body = request.get_json()
        entry = body["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        # Verificamos si es un mensaje real (y no un "visto")
        if "messages" in value:
            mensaje = value["messages"][0]
            numero = mensaje["from"]  # Quien envía
            texto_usuario = mensaje["text"]["body"]  # Qué dijo
            
            logging.info(f"📩 MENSAJE DE {numero}: {texto_usuario}")

            # --- AQUÍ OCURRE LA MAGIA DE GEMINI ---
            try:
                # Le preguntamos a Gemini
                response = model.generate_content(texto_usuario)
                respuesta_gemini = response.text
                logging.info(f"🤖 GEMINI RESPONDE: {respuesta_gemini}")
                
                # Enviamos la respuesta de Gemini a WhatsApp
                enviar_whatsapp(numero, respuesta_gemini)
                
            except Exception as e:
                logging.error(f"❌ ERROR CEREBRAL: {str(e)}")
                enviar_whatsapp(numero, "Tuve un error pensando... intenta de nuevo.")
            # ---------------------------------------

        return jsonify({"status": "recibido"}), 200

    except Exception as e:
        # Si llega algo que no es mensaje (como un status), lo ignoramos sin error
        return jsonify({"status": "evento_ignorado"}), 200

# 5. FUNCIÓN PARA ENVIAR (La Boca)
def enviar_whatsapp(numero, texto):
    url = "https://graph.facebook.com/v21.0/939839529214459/messages" # OJO: Revisa que este ID sea el tuyo
    # TRUCO: Mejor usa el ID dinámico si puedes, pero por ahora usa el que te funcionó en Postman
    # Si quieres asegurar, usa el ID de teléfono que usaste en Postman.
    
    # IMPORTANTE: Reemplaza este ID '569839692873155' por TU PHONE_NUMBER_ID real
    # Lo puedes sacar de tus logs anteriores donde dice "phone_number_id"
    
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
    if response.status_code == 200:
        logging.info("✅ MENSAJE ENVIADO")
    else:
        logging.error(f"❌ ERROR AL ENVIAR: {response.text}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
