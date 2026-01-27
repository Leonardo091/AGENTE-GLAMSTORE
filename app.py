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

@app.route("/")
def home():
    try:
        total = db.total_items
        identidad = db.obtener_identidad()
        hora = obtener_hora_chile()
        
        muestra = []
        # Try/Except por si la lista está vacía o algo falla
        try:
            for p in db.productos[:5]:
                muestra.append({"producto": p['title'], "precio": p['price']})
        except: pass
            
        return jsonify({
            "estado": "ONLINE 🟢",
            "hora": hora,
            "productos_cargados": total,
            "identidad_sistema": identidad,
            "muestra": muestra
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
                    if link == "NO_ENCONTRE_EXACTO": info_sistema = "No encontré el nombre exacto."
                    elif link == "ERROR_LINK": info_sistema = "Error técnico link."
                    else: info_sistema = f"✅ Link: {link}"

                elif "BUSCAR" in decision:
                    res = db.buscar_producto_rapido(texto)
                    if res["tipo"] == "VACIO": 
                        # MENTIRA PIADOSA: Si la DB está en 0, no decimos "vacío", decimos que no encontramos coincidencia
                        info_sistema = "No encontré coincidencias exactas en el catálogo actual."
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

                # 3. RESPONDER (PROMPT ANTIBOT-FEO)
                saludo = "Saluda formal (Usted)" if debe_saludar else "NO SALUDES"
                identidad = db.obtener_identidad()
                
                prompt_final = f"""
                Eres GlamBot, asistente de la tienda Glamstore Chile.
                
                CONTEXTO TIENDA:
                {identidad}
                
                INFORMACIÓN RELEVANTE PARA EL CLIENTE:
                {info_sistema}
                
                INSTRUCCIONES DE TONO (ESTRICTO):
                1. JAMÁS empieces con frases como "Cargando datos...", "Procesando...", "Según la información...".
                2. JAMÁS escribas "Bot:" o uses comillas.
                3. Responde DIRECTAMENTE a la pregunta.
                4. NO VENDEMOS ROPA.
                5. {saludo}.
                
                Chat previo:
                {historial_txt}
                Cliente: "{texto}"
                """
                
                try:
                    res = model.generate_content(prompt_final)
                    respuesta = res.text
                    
                    # Limpieza final
                    respuesta = respuesta.replace("Bot:", "").replace("GlamBot:", "").strip()
                    respuesta = respuesta.replace("Cargando datos...", "") # Filtro de emergencia
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
