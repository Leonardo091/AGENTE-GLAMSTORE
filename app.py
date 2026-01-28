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
            "mensaje": "Prompt Maestro Cargado. Bot listo para operar."
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
            
            # Solo saludamos si pasaron 2 horas o es nuevo
            debe_saludar = (ahora_ts - usuario['ultimo_msg'] > 7200) or (usuario['ultimo_msg'] == 0)
            # Y si el cliente explícitamente dijo hola, forzamos el saludo para ser educados
            if any(s in texto.lower() for s in ["hola", "buenas", "alo"]): debe_saludar = True
            
            usuario['ultimo_msg'] = ahora_ts
            historial_txt = "\n".join([f"- {h['rol']}: {h['txt']}" for h in usuario['historial']])

            if model:
                # 1. CLASIFICAR INTENCIÓN
                prompt_det = f"""
                Analiza el mensaje del cliente.
                Mensaje: "{texto}"
                Historial: {historial_txt}
                
                Opciones:
                - VENDER: El cliente pide un link de pago o dice "quiero comprar X".
                - BUSCAR: El cliente pregunta si tienen un producto específico (ej: "¿Tienen Lattafa?").
                - INFO: Pregunta horarios, ubicación, "¿qué venden?", "mayorista", envíos.
                - CHARLA: Saludos simples o conversación genérica.
                
                Responde SOLO UNA PALABRA.
                """
                try: decision = model.generate_content(prompt_det).text.strip().split()[0]
                except: decision = "CHARLA"

                info_sistema = ""

                # 2. BUSCAR DATA (Sin tocar el código, solo recolectar)
                if "VENDER" in decision:
                    link = db.crear_link_pago_seguro(texto)
                    if link == "NO_ENCONTRE_EXACTO": info_sistema = "DATA: Producto no encontrado exacto para link."
                    elif link == "ERROR_LINK": info_sistema = "DATA: Error técnico al generar link."
                    else: info_sistema = f"DATA: Link de pago generado: {link}"

                elif "BUSCAR" in decision:
                    res = db.buscar_producto_rapido(texto)
                    if res["tipo"] == "VACIO": 
                        info_sistema = "DATA: 0 Coincidencias encontradas en stock."
                    else:
                        items = ", ".join([f"{p['title']} (${p['price']:,.0f})" for p in res["items"]])
                        info_sistema = f"DATA: Tenemos en stock: {items}"

                # 3. PROMPT MAESTRO (AQUÍ ESTÁ LA SEGMENTACIÓN)
                # Definimos claramente los límites y respuestas tipo
                
                prompt_final = f"""
                Eres "GlamBot", el asistente virtual experto de Glamstore Chile.
                Tu tono es: Profesional, amable, directo y seguro.
                
                === TUS LÍMITES (SEGMENTACIÓN) ===
                1. UBICACIÓN: Santo Domingo 240, Puente Alto.
                2. HORARIO (ESTRICTO):
                   - Lunes a Viernes: 10:00 AM a 05:30 PM.
                   - Sábados: 10:00 AM a 02:30 PM.
                   - Domingos: CERRADO.
                3. LO QUE VENDEMOS: Maquillaje, Perfumes (Árabes y tradicionales), Cuidado Capilar y Skincare.
                4. LO QUE NO VENDEMOS: Ropa, Zapatillas, Repuestos, Comida.
                
                === TUS REGLAS DE RESPUESTA (PLAYBOOK) ===
                
                CASO 1: CLIENTE PREGUNTA "¿QUÉ VENDEN?" O "¿QUÉ TIENEN?"
                - NO saludes de nuevo.
                - Responde: "Nos especializamos en belleza. Tenemos una gran variedad de perfumes (incluyendo marcas árabes como Lattafa), maquillaje completo, y productos de cuidado capilar y facial."
                
                CASO 2: CLIENTE PREGUNTA POR "MAYORISTA"
                - Responde: "Actualmente nuestra atención es venta al detalle en este canal, pero te invitamos a visitarnos en tienda para ver opciones presenciales."
                
                CASO 3: EL CLIENTE SALUDA ("Hola")
                - Si es el primer mensaje, saluda y ofrece ayuda.
                - Si ya saludaste antes en el historial, NO repitas el saludo. Ve al grano.
                
                CASO 4: STOCK Y VENTAS
                - Información del sistema: "{info_sistema}"
                - Si la Data dice "0 Coincidencias": Di "Lo siento, actualmente no tenemos ese producto específico en stock." y ofrece ver otra cosa.
                - Si la Data tiene productos: Muéstralos con sus precios.
                - JAMÁS inventes productos que no salgan en la "Información del sistema".
                - JAMÁS inventes enlaces web falsos.
                
                === CONTEXTO ACTUAL ===
                Historial de chat:
                {historial_txt}
                
                Mensaje nuevo del Cliente: "{texto}"
                
                Respuesta de GlamBot:
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
