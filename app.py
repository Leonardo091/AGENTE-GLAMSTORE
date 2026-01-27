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

@app.route("/")
def home():
    try:
        estado = "🟢 CONECTADO" if db.total_items > 0 else "⚠️ MODO RESPALDO (Directo a Shopify)"
        return jsonify({
            "estado": estado, 
            "productos_ram": db.total_items, 
            "mensaje": "El bot solo venderá lo que encuentre aquí."
        }), 200
    except Exception as e: return jsonify({"error": str(e)}), 500

# Gemini
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

                # 2. EJECUTAR
                if "VENDER" in decision:
                    link = db.crear_link_pago_seguro(texto)
                    if link == "NO_ENCONTRE_EXACTO": info_sistema = "❌ PRODUCTO NO ENCONTRADO EN SISTEMA."
                    elif link == "ERROR_LINK": info_sistema = "Error técnico al generar link."
                    else: info_sistema = f"✅ Link generado: {link}"

                elif "BUSCAR" in decision:
                    res = db.buscar_producto_rapido(texto)
                    if res["tipo"] == "VACIO": 
                        # ESTO ES CLAVE: Le decimos explícitamente que NO HAY.
                        info_sistema = "RESULTADO DE BÚSQUEDA: 0 COINCIDENCIAS. NO TENEMOS ESTE PRODUCTO."
                    else:
                        titulo = "EN STOCK:" if res["tipo"] == "EXACTO" else "RECOMENDACIONES STOCK:"
                        items = ""
                        for p in res["items"]:
                            items += f"\n🔹 {p['title']} (${p['price']:,.0f})"
                        info_sistema = f"{titulo}{items}"

                elif "INFO" in decision:
                    info_sistema = "Ubicación: Santo Domingo 240, Puente Alto. Horario: Lun-Vie 10-19, Sab 10-14."

                # 3. RESPONDER (CON CANDADO)
                saludo = "Saluda formal (Usted)" if debe_saludar else "NO SALUDES"
                
                prompt_final = f"""
                Eres GlamBot, vendedor honesto de Glamstore.
                
                TU INVENTARIO REAL (LO ÚNICO QUE EXISTE):
                {info_sistema}
                
                REGLAS SUPREMAS (LEER CON ATENCIÓN):
                1. SI LA DATA DICE "0 COINCIDENCIAS" O "NO TENEMOS", DEBES DECIR: "Lo siento, actualmente no trabajamos ese producto" y sugerir que pregunten por otra cosa.
                2. JAMÁS inventes que tenemos una marca si no aparece en la lista de arriba.
                3. JAMÁS inventes links tipo [Enlace...]. Si no tienes el link real, no lo mandes.
                4. Solo vende lo que ves en "TU INVENTARIO REAL". El resto NO EXISTE para ti.
                5. {saludo}.
                
                Chat: {historial_txt}
                Cliente: "{texto}"
                """
                
                try:
                    res = model.generate_content(prompt_final)
                    respuesta = res.text.replace("Bot:", "").replace("GlamBot:", "").strip()
                    if respuesta.startswith('"') and respuesta.endswith('"'): respuesta = respuesta[1:-1]
                    
                    usuario['historial'].append({"rol": nombre, "txt": texto})
                    usuario['historial'].append({"rol": "Bot", "txt": respuesta})
                    
                    requests.post(
                        "https://graph.facebook.com/v21.0/939839529214459/messages",
                        headers={"Authorization": f"Bearer {TOKEN_WHATSAPP}", "Content-Type": "application/json"},
                        json={"messaging_product": "whatsapp", "to": numero, "type": "text", "text": {"body": respuesta}}
                    )
                except Exception as e: logging.error(f"Error Gen: {e}")

        return jsonify({"status": "ok"}), 200
    except: return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
