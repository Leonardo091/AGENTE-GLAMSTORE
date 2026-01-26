import os
import logging
from flask import Flask, request, jsonify
import requests
import google.generativeai as genai

# Configuración básica
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# 1. CREDENCIALES
TOKEN_WHATSAPP = os.environ.get("WHATSAPP_TOKEN")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
API_KEY_GEMINI = os.environ.get("GEMINI_API_KEY")

# 2. CONFIGURACIÓN "AUTO-PILOTO" DE GEMINI
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    
    try:
        logging.info("🔍 DETECTANDO CEREBRO AUTOMÁTICAMENTE...")
        
        # Listamos todos los modelos que sirven para generar texto
        modelos_disponibles = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # Definimos nuestros favoritos en orden (del más rápido al más seguro)
        favoritos = [
            'models/gemini-1.5-flash',
            'models/gemini-1.5-flash-latest',
            'models/gemini-1.0-pro',
            'models/gemini-pro',
            'models/gemini-flash-latest' # El alias que vimos en tus logs
        ]
        
        modelo_elegido = None
        
        # Buscamos si alguno de los favoritos está en tu lista
        for fav in favoritos:
            if fav in modelos_disponibles:
                modelo_elegido = fav
                break
        
        # Si no encontramos ninguno favorito, usamos el PRIMERO que haya (el comodín)
        if not modelo_elegido and modelos_disponibles:
            modelo_elegido = modelos_disponibles[0]
            
        if modelo_elegido:
            logging.info(f"✅ CEREBRO CONECTADO: {modelo_elegido}")
            model = genai.GenerativeModel(modelo_elegido)
        else:
            logging.error("❌ NO SE ENCONTRARON MODELOS DISPONIBLES EN TU CUENTA")
            model = None

    except Exception as e:
        logging.error(f"⚠️ FALLÓ EL AUTO-PILOTO: {e}")
        # Intento desesperado final
        model = genai.GenerativeModel('gemini-1.5-flash')
else:
    logging.error("¡FALTA LA GEMINI_API_KEY EN RENDER!")

# 3. VERIFICACIÓN WEBHOOK
@app.route("/webhook", methods=["GET"])
def verificar_token():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Error", 403

# 4. RECIBIR MENSAJES
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

            try:
                if model:
                    # Usamos el modelo que el auto-piloto eligió
                    response = model.generate_content(texto_usuario)
                    respuesta = response.text
                else:
                    respuesta = "Estoy sin cerebro (Error de API Key)."

                logging.info(f"🤖 RESPUESTA: {respuesta}")
                enviar_whatsapp(numero, respuesta)
                
            except Exception as e:
                logging.error(f"❌ ERROR GENERANDO RESPUESTA: {str(e)}")
                enviar_whatsapp(numero, "Tuve un error procesando tu mensaje. Intenta de nuevo.")

        return jsonify({"status": "ok"}), 200
    except:
        return jsonify({"status": "ignored"}), 200

# 5. ENVIAR WHATSAPP
def enviar_whatsapp(numero, texto):
    url = "https://graph.facebook.com/v21.0/939839529214459/messages"
    headers = { "Authorization": f"Bearer {TOKEN_WHATSAPP}", "Content-Type": "application/json" }
    data = { "messaging_product": "whatsapp", "to": numero, "type": "text", "text": {"body": texto} }
    requests.post(url, headers=headers, json=data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
