import os
import logging
import time
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import google.generativeai as genai
from collections import deque

# Importamos la base de datos
from database import db 

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# Credenciales
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

# --- RUTA HOME (MODO JSON ULTRALIGERO) ---
# Esto soluciona el problema de que la página no cargue
@app.route("/")
def home():
    try:
        total = db.total_items
        identidad = db.obtener_identidad()
        hora = obtener_hora_chile()
        
        # Muestra pequeña de 5 productos
        muestra = []
        for p in db.productos[:5]:
            muestra.append({
                "producto": p['title'],
                "precio": p['price']
            })
            
        return jsonify({
            "estado": "ONLINE 🟢",
            "hora_servidor": hora,
            "total_productos_ram": total,
            "identidad": identidad,
            "ejemplo_catalogo": muestra
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Configuración Gemini
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

            # Memoria Chat
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
                Acción: VENDER, BUSCAR, INFO, CHARLA.
                """
                try: decision = model.generate_content(prompt_det).text.strip().split()[0]
                except: decision = "CHARLA"

                info_sistema = ""

                # 2. EJECUTAR
                if "VENDER" in decision:
                    link = db.crear_link_pago_seguro(texto)
                    if link == "NO_ENCONTRE_EXACTO": info_sistema = "No encontré el nombre exacto."
                    elif link == "ERROR_LINK": info_sistema = "Error técnico link."
                    else: info_sistema = f"✅ Link: {link}"

                elif "BUSCAR" in decision:
                    res = db.buscar_producto_rapido(texto)
                    if res["tipo"] == "VACIO": info_sistema = "Sin coincidencias."
                    else:
                        titulo = "ENCONTRÉ:" if res["tipo"] == "EXACTO" else "RECOMIENDO:"
                        items = ""
                        for p in res["items"]:
                            # Precio ya viene limpio desde database.py
                            items += f"\n🔹 {p['title']} (${p['price']:,.0f})"
                        info_sistema = f"{titulo}{items}"

                elif "INFO" in decision:
                    info_sistema = f"""
                    Hora: {obtener_hora_chile()}.
                    Dirección: Santo Domingo 240, Puente Alto.
                    Horario: Lun-Vie hasta 17:30, Sab hasta 14:30.
                    """

                # 3. RESPONDER
                saludo = "Saluda formal (Usted)" if debe_saludar else "NO SALUDES"
                identidad = db.obtener_identidad()
                
                prompt_final = f"""
                Eres GlamBot.
                
                VITRINA: {identidad}
                
                REGLAS FORMATO:
                1. NUNCA escribas "Bot:" ni uses comillas.
                
                REGLAS NEGOCIO:
                1. NO VENDEMOS ROPA.
                2. {saludo}.
                
                DATA SISTEMA: {info_sistema}
                
                Chat: {historial_txt}
                Cliente: "{texto}"
                """
                
                try:
                    res = model.generate_content(prompt_final)
                    respuesta = res.text
                    
                    # Limpieza final (La Aspiradora)
                    respuesta = respuesta.replace("Bot:", "").replace("GlamBot:", "").strip()
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
