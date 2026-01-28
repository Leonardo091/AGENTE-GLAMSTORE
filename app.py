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
        estado = "🟢 TABLA LISTA" if db.total_items > 0 else "⚠️ ESPERANDO DATOS"
        return jsonify({"estado": estado, "total": db.total_items, "msg": "Filtro de palabras basura activo."}), 200
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
                # 1. CLASIFICACIÓN MEJORADA (Con Ejemplos para que no sea tonto)
                prompt_det = f"""
                Clasifica la intención del mensaje.
                Mensaje: "{texto}"
                Historial: {historial_txt}
                
                EJEMPLOS:
                - "Quiero comprar el perfume yara", "mándame el link de pago" -> VENDER
                - "¿Tienen perfumes?", "¿Qué venden?", "Precio del yara" -> INFO_PRODUCTO
                - "Horario", "Ubicación", "Mayorista" -> INFO_TIENDA
                - "Hola", "Gracias" -> CHARLA
                
                Responde SOLO UNA PALABRA: VENDER, INFO_PRODUCTO, INFO_TIENDA, CHARLA.
                """
                try: decision = model.generate_content(prompt_det).text.strip().split()[0]
                except: decision = "CHARLA"

                info_sistema = ""

                # 2. LÓGICA DE DATOS
                if "VENDER" in decision:
                    link = db.crear_link_pago_seguro(texto)
                    if "ERROR" in link or "NO_ENCONTRE" in link: 
                        # Si falló el link, cambiamos estrategia a búsqueda normal
                        info_sistema = "DATA: No pude generar link directo. Recomienda buscar el nombre exacto."
                    else: info_sistema = f"DATA: Link generado: {link}"

                elif "INFO_PRODUCTO" in decision:
                    res = db.buscar_producto_rapido(texto)
                    
                    if res.get("motivo") == "SOLO_STOPWORDS":
                        # Caso: "¿Qué venden?" -> El buscador borró todo y quedó vacío.
                        info_sistema = "DATA_GENERAL: El cliente pregunta por catálogo general. Menciona Maquillaje, Perfumes (Árabes y tradicionales), Capilar."
                    elif res["tipo"] == "VACIO":
                        info_sistema = "DATA: 0 coincidencias en stock."
                    else:
                        items = ", ".join([f"{p['title']} (${p['price']:,.0f})" for p in res["items"]])
                        info_sistema = f"DATA: Encontrados: {items}"

                elif "INFO_TIENDA" in decision:
                    info_sistema = "DATA: Ubicación: Santo Domingo 240, Puente Alto. Horario: Lun-Vie 10:00-17:30, Sab 10:00-14:30."

                # 3. PROMPT MAESTRO (EL PUENTE)
                prompt_final = f"""
                Eres "GlamBot", asistente de Glamstore Chile.
                
                === INFORMACIÓN DEL SISTEMA (DATA REAL) ===
                {info_sistema}
                
                === TUS REGLAS ===
                1. SI LA DATA MUESTRA PRODUCTOS: Ofrécelos con sus precios.
                2. SI LA DATA ES "0 COINCIDENCIAS": Di "Busqué en inventario y no encontré [Producto]. ¿Te interesa ver otra cosa?".
                3. SI LA DATA ES GENERAL (¿Qué venden?): Di "Tenemos una gran variedad de Perfumes (Árabes y Tradicionales), Maquillaje y Cuidado Capilar.".
                4. HORARIO: Lun-Vie 10:00 AM - 05:30 PM | Sab 10:00 AM - 02:30 PM.
                5. NO inventes links.
                6. { "Saluda cortésmente." if debe_saludar else "Ve directo al punto." }
                
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
