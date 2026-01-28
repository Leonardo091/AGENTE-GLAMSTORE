import os
import logging
import time
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import google.generativeai as genai
from collections import deque
from database import db 

logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.basicConfig(level=logging.INFO, format='%(message)s')
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
    return jsonify({
        "status": "ONLINE", 
        "productos": db.total_items, 
        "mode": "STRICT_INVENTORY"
    }), 200

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
                MEMORIA_USUARIOS[numero] = {'historial': deque(maxlen=6), 'ultimo_msg': 0}
            usuario = MEMORIA_USUARIOS[numero]
            
            historial_txt = "\n".join([f"User: {h['txt']}\nBot: {h['resp']}" for h in usuario['historial']])

            if model:
                # 1. INTENCIÓN
                prompt_router = f"""
                Clasifica mensaje: "{texto}"
                Historial: {historial_txt}
                
                1. CATALOGO: Piden "que venden", "tienes perfumes", "recomiendame algo", "busco labial".
                2. COMPRAR: "quiero el link", "lo compro", "dame precio del [producto exacto]".
                3. TIENDA: Ubicación, horarios, envíos.
                4. CHARLA: Saludos, quejas, "gracias".
                
                Responde SOLO la categoría.
                """
                try: intencion = model.generate_content(prompt_router).text.strip().upper()
                except: intencion = "CHARLA"

                # 2. DATA MINING (LO MÁS IMPORTANTE)
                contexto_data = ""
                
                if "CATALOGO" in intencion or "COMPRAR" in intencion:
                    # Aquí el DB busca "perfume" y devuelve 5 perfumes REALES
                    res = db.buscar_contextual(texto)
                    
                    if res["tipo"] == "VACIO":
                        contexto_data = "INVENTARIO: No se encontraron coincidencias en la bodega."
                    elif res["tipo"] == "RECOMENDACION_REAL":
                        lista = "\n".join([f"- {p['title']} (${p['price']:,.0f})" for p in res["items"]])
                        contexto_data = f"INVENTARIO DISPONIBLE (SOLO OFRECE ESTO):\n{lista}"
                    else: # EXACTO
                        lista = "\n".join([f"- {p['title']} (${p['price']:,.0f})" for p in res["items"]])
                        contexto_data = f"PRODUCTO ENCONTRADO:\n{lista}"
                        
                    if "COMPRAR" in intencion and res["items"]:
                        link = db.generar_checkout(texto)
                        if link: contexto_data += f"\n\nLINK DE PAGO GENERADO: {link['url']}"

                elif "TIENDA" in intencion:
                    contexto_data = """
                    INFO TIENDA:
                    - Dirección: Santo Domingo 240, Puente Alto.
                    - Horario: Lun-Vie 10:00 AM - 05:30 PM | Sáb 10:00 AM - 02:30 PM.
                    - Envíos a todo Chile.
                    """

                # 3. PROMPT "BÚNKER" (ANTI-ALUCINACIÓN)
                prompt_final = f"""
                Eres "GlamBot", el vendedor digital de Glamstore.
                
                === TU CEREBRO (IMPORTANTE) ===
                Solo conoces lo que está en la sección "DATOS DEL SISTEMA" abajo.
                Tienes PROHIBIDO usar conocimiento externo.
                Si te piden "Carolina Herrera" y NO está en la lista de abajo, DI QUE NO LO TIENES.
                
                === DATOS DEL SISTEMA (TU ÚNICA VERDAD) ===
                {contexto_data}
                
                === REGLAS ===
                1. Si el cliente pide una recomendación, elige UNO de la lista de "INVENTARIO DISPONIBLE" y véndelo bien.
                2. JAMÁS inventes productos. Si la lista está vacía, di: "Lo siento, no tengo stock de eso ahora."
                3. JAMÁS escribas "[Insertar foto]" o "[Insertar precio]". Eso está prohibido.
                4. Si generaste un link, entrégalo.
                5. Sé amable y profesional.
                
                Chat previo:
                {historial_txt}
                User: "{texto}"
                Bot:
                """
                
                try:
                    resp_final = model.generate_content(prompt_final).text.strip()
                    # Limpieza agresiva
                    resp_final = resp_final.replace("Bot:", "").replace("[Insertar", "").strip()
                    
                    usuario['historial'].append({"txt": texto, "resp": resp_final})
                    
                    requests.post(
                        "https://graph.facebook.com/v21.0/939839529214459/messages",
                        headers={"Authorization": f"Bearer {TOKEN_WHATSAPP}", "Content-Type": "application/json"},
                        json={"messaging_product": "whatsapp", "to": numero, "type": "text", "text": {"body": resp_final}}
                    )
                except Exception as e: logging.error(f"Error Gen: {e}")

        return jsonify({"status": "ok"}), 200
    except: return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
