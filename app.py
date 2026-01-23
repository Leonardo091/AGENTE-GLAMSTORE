import os
import requests
import traceback
import json  # Agregamos esto para imprimir bonito
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

META_TOKEN = os.getenv("META_TOKEN")
META_PHONE_ID = os.getenv("META_PHONE_ID")
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN")

print("🐸 EL BOT SAPO ESTÁ LISTO. ESPERANDO DATOS...")

@app.route("/webhook", methods=["GET"])
def verificar_token():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == META_VERIFY_TOKEN:
        print("✅ WEBHOOK VERIFICADO")
        return challenge, 200
    return "Error", 403

@app.route("/webhook", methods=["POST"])
def recibir_mensaje():
    data = request.json
    
    # --- AQUÍ ESTÁ LA MAGIA: IMPRIMIR TODO LO QUE LLEGA ---
    print("\n📦 PAQUETE RECIBIDO DE FACEBOOK:")
    print(json.dumps(data, indent=2)) # Esto imprime el JSON completo
    print("-" * 30)
    # ------------------------------------------------------

    try:
        if "entry" in data:
            entry = data["entry"][0]["changes"][0]["value"]
            
            if "messages" in entry:
                mensaje = entry["messages"][0]
                numero = mensaje["from"]
                texto = mensaje["text"]["body"]
                print(f"📩 MENSAJE DETECTADO: {texto}")
                
                # Intentar responder
                enviar_whatsapp(numero, f"🦜 Recibí tu mensaje: {texto}")
            else:
                print("⚠️ Llegó un evento, pero NO es un mensaje de texto (probablemente es un estado 'read' o 'sent').")

    except Exception as e:
        print(f"🔥 ERROR PROCESANDO: {e}")
        traceback.print_exc()

    return jsonify({"status": "success"}), 200

def enviar_whatsapp(numero, texto):
    url = f"https://graph.facebook.com/v21.0/{META_PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {META_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": numero, "type": "text", "text": {"body": texto}}
    requests.post(url, json=data, headers=headers)

if __name__ == "__main__":
    app.run(port=5000)