import os
import logging
from flask import Flask, request, jsonify
import requests
import google.generativeai as genai

# Configuración básica de logs
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# 1. CONFIGURACIÓN DE CREDENCIALES
TOKEN_WHATSAPP = os.environ.get("WHATSAPP_TOKEN")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
API_KEY_GEMINI = os.environ.get("GEMINI_API_KEY")

# 2. CONFIGURAMOS GEMINI Y DIAGNÓSTICO
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    
    # --- BLOQUE DE DIAGNÓSTICO (Para ver qué cerebros tienes) ---
    try:
        logging.info("🔍 DIAGNÓSTICO: Buscando modelos disponibles en tu llave...")
        modelos_disponibles = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                modelos_disponibles.append(m.name)
                logging.info(f"🧠 CEREBRO ENCONTRADO: {m.name}")
        
        if not modelos_disponibles:
            logging.error("❌ ALERTA: Tu llave es válida, pero NO TIENE modelos activados. Crea una nueva en un proyecto nuevo.")
    except Exception as e:
        logging.error(f"❌ ERROR CRÍTICO al listar modelos: {e}")
    # -----------------------------------------------------------

    # Intentamos usar el modelo Flash (es el más rápido y actual)
    # Si falla, miraremos los logs del diagnóstico para cambiar este nombre
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
                # Mensaje de error amigable para ti mientras probamos
                enviar_whatsapp(numero, "Estoy teniendo problemas con mi cerebro (API Key). Revisa los logs de Render.")
            # ---------------------------------------

        return jsonify({"status": "recibido"}), 200

    except Exception as e:
        # Si llega algo que no es mensaje (como un status), lo ignoramos sin error
        return jsonify({"status": "evento_ignorado"}), 200

# 5. FUNCIÓN PARA ENVIAR (La Boca)
def enviar_whatsapp(numero, texto):
    # Usamos tu ID de teléfono confirmado
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
    if response.status_code == 200:
        logging.info("✅ MENSAJE ENVIADO")
    else:
        logging.error(f"❌ ERROR AL ENVIAR A WHATSAPP: {response.text}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
