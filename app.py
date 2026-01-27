import os
import logging
import time
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import google.generativeai as genai
from collections import deque
from database import db 

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

TOKEN_WHATSAPP = os.environ.get("WHATSAPP_TOKEN")
VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN")
API_KEY_GEMINI = os.environ.get("GEMINI_API_KEY")

MEMORIA_USUARIOS = {}

def obtener_hora_chile():
    return (datetime.utcnow() - timedelta(hours=3)).strftime("%H:%M")

def despertar_render():
    while True:
        time.sleep(300)
        try: requests.get("https://agente-glamstore.onrender.com")
        except: pass

import threading
hilo_ping = threading.Thread(target=despertar_render)
hilo_ping.daemon = True
hilo_ping.start()

# --- WEB PANEL (SIMPLE Y RÁPIDO) ---
@app.route("/")
def home():
    try:
        # Probamos conexión rápida para ver si el híbrido funciona
        estado_ram = "CARGADA ✅" if db.total_items > 0 else "VACÍA (Usando Modo Respaldo) ⚠️"
        
        return jsonify({
            "estado_sistema": "ONLINE 🟢",
            "hora": obtener_hora_chile(),
            "memoria_ram": f"{db.total_items} productos",
            "estado_actual": estado_ram,
            "identidad": db.obtener_identidad(),
            "nota": "Si la memoria está vacía, no te preocupes, el bot busca directo en Shopify."
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- GEMINI ---
model = None
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    try: model = genai.GenerativeModel('gemini-2.0-flash-lite')
    except: model = genai.GenerativeModel('gemini-1.5-flash')

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

            # Memoria
            ahora_ts = time.time()
            if numero not in MEMORIA_USUARIOS:
                MEMORIA_USUARIOS[numero] = {'historial': deque(maxlen=8), 'ultimo_msg': 0}
            usuario = MEMORIA_USUARIOS[numero]
            
            debe_saludar = (ahora_ts - usuario['ultimo_msg'] > 7200) or (usuario['ultimo_msg'] == 0)
            if any(s in texto.lower() for s in ["hola", "buenas"]): debe_saludar = True
            usuario['ultimo_msg'] = ahora_ts
            
            historial_txt = "\n".join([f"- {h['rol']}: {h['txt']}" for h in usuario['historial']])

            if model:
                # 1. CLASIFICAR
                prompt_det = f"""
                Mensaje: "{texto}"
                Historial: {historial_txt}
                Responde SOLO UNA PALABRA: VENDER, BUSCAR, INFO, CHARLA.
                """
                try: decision = model.generate_content(prompt_det).text.strip().split()[0]
                except: decision = "CHARLA"

                info_sistema = ""

                # 2. EJECUTAR (USANDO DB HÍBRIDA)
                if "VENDER" in decision:
                    link = db.crear_link_pago_seguro(texto)
                    if link == "NO_ENCONTRE_EXACTO": info_sistema = "No encontré el nombre exacto."
                    elif link == "ERROR_LINK": info_sistema = "Error técnico link."
                    else: info_sistema = f"✅ Link: {link}"

                elif "BUSCAR" in decision:
                    res = db.buscar_producto_rapido(texto)
                    if res["tipo"] == "VACIO": 
                        info_sistema = "No encontré coincidencias."
                    else:
                        titulo = "ENCONTRÉ:" if res["tipo"] == "EXACTO" else "RECOMIENDO:"
                        items = ""
                        for p in res["items"]:
                            items += f"\n🔹 {p['title']} (${p['price']:,.0f})"
                        info_sistema = f"{titulo}{items}"

                elif "INFO" in decision:
                    info_sistema = f"""
                    Ubicación: Santo Domingo 240, Puente Alto.
                    Horario: Lun-Vie 10:00-19:00, Sab 10:00-14:00.
                    """

                # 3. RESPONDER
                saludo = "Saluda formal (Usted)" if debe_saludar else "NO SALUDES"
                identidad = db.obtener_identidad()
                
                prompt_final = f"""
                Eres GlamBot.
                
                VITRINA: {identidad}
                
                REGLAS:
                1. NO digas "Cargando datos".
                2. NO uses comillas.
                3. {saludo}.
                
                DATA SISTEMA: {info_sistema}
                
                Chat: {historial_txt}
                Cliente: "{texto}"
                """
                
                try:
                    res = model.generate_content(prompt_final)
                    respuesta = res.text.replace("Bot:", "").replace("GlamBot:", "").strip()
                    if respuesta.startswith('"') and respuesta.endswith('"'):
                        respuesta = respuesta[1:-1]
                    
                    usuario['historial'].append({"rol": nombre, "txt": texto})
                    usuario['historial'].append({"rol": "Bot", "txt": respuesta})
                    
                    requests.post(
                        "https://graph.facebook.com/v21.0/939839529214459/messages",
                        headers={"Authorization": f"Bearer {TOKEN_WHATSAPP}", "Content-Type": "application/json"},
                        json={"messaging_product": "whatsapp", "to": numero, "type": "text", "text": {"body": respuesta}}
                    )
                except Exception as e:
                    logging.error(f"Error Gen: {e}")

        return jsonify({"status": "ok"}), 200
    except: return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
