import os
from dotenv import load_dotenv
load_dotenv()
import logging
import time
import requests
import threading
from datetime import datetime
from flask import Flask, request, jsonify
from collections import deque
from database import db 
from typing import List, Dict, Any, Optional

# --- SERVICIOS (Arquitectura Elite) ---
from services.whatsapp_service import enviar_whatsapp, descargar_media_meta, check_rate_limit, enviar_reporte_email
from services.ai_service import procesar_inteligencia_artificial

# Configuración de Logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# --- CONFIGURACION GLOBAL ---
MODO_VACACIONES = True
db.modo_vacaciones = MODO_VACACIONES
VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "glamstore_verify_token")

# --- MEMORIA ESTADO ---
processed_message_ids = deque(maxlen=100)
MEMORIA_USUARIOS = {}

# --- RUTAS DE MANTENIMIENTO ---
@app.route("/")
def home():
    return "🚀 GlamBot AI Active (Elite Architecture)"

@app.route("/debug/force_sync")
def debug_force_sync():
    try:
        db._actualizar_tabla_maestra() 
        return jsonify(db.get_status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/debug/search")
def debug_search():
    query = request.args.get("q", "")
    if not query: return "Falta 'q'", 400
    resultado = db.buscar_contextual(query)
    return jsonify({"q": query, "res": resultado}), 200

# --- WEBHOOK PRINCIPAL ---
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    # 1. VERIFICACIÓN (GET)
    if request.method == "GET":
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return request.args.get("hub.challenge")
        return "Error validacion", 403

    # 2. PROCESAMIENTO (POST)
    try:
        body = request.get_json()
        if not body or "entry" not in body:
            return jsonify({"status": "ignored"}), 200

        entry = body["entry"][0]["changes"][0]["value"]
        if "messages" not in entry:
            return jsonify({"status": "ok"}), 200 # Eventos de estado (sent, delivered)

        msg = entry["messages"][0]
        numero = msg["from"]
        
        # A) Rate Limiting (Delegate to Service)
        if not check_rate_limit(numero):
            logging.warning(f"⛔ Rate Limit {numero}")
            return jsonify({"status": "rate_limited"}), 200
        
        # B) Deduplicación
        message_id = msg.get("id")
        if message_id and message_id in processed_message_ids:
            return jsonify({"status": "ignored_duplicate"}), 200
        if message_id: processed_message_ids.append(message_id)

        # C) Extracción Info
        msg_type = msg.get("type")
        texto = ""
        imagen_bytes = None
        audio_bytes = None

        if msg_type == "text":
            texto = msg.get("text", {}).get("body", "")
        elif msg_type == "image":
            texto = msg.get("image", {}).get("caption", "") or "Busco esto"
            media_id = msg.get("image", {}).get("id")
            imagen_bytes = descargar_media_meta(media_id)
        elif msg_type == "audio":
            media_id = msg.get("audio", {}).get("id")
            logging.info(f"🎤 Audio recibido ID: {media_id}. Descargando...")
            audio_bytes = descargar_media_meta(media_id)
            texto = "[AUDIO RECIBIDO]" # Placeholder log
        
        nombre = entry.get("contacts", [{}])[0].get("profile", {}).get("name", "Cliente")

        # D) Comandos Admin (Simplified logic call)
        # (Aquí podríamos mover lógica Admin a un admin_service, pero por ahora lo dejamos simple o invocamos DB directo)
        if texto.startswith("!db") and os.environ.get("ADMIN_NUMBER") in numero:
             # ... Logic admin rapida ...
             if "sync" in texto:
                 threading.Thread(target=db.force_sync).start()
                 enviar_whatsapp(numero, "⏳ Sync Background Iniciada.")
             return jsonify({"status": "admin_cmd"}), 200

        # E) Gestión Memoria Usuario
        if numero not in MEMORIA_USUARIOS:
            MEMORIA_USUARIOS[numero] = {'historial': deque(maxlen=6), 'msg_map': {}}
        usuario = MEMORIA_USUARIOS[numero]
        historial_txt = "\n".join([f"U: {h['txt']}\nB: {h['resp']}" for h in usuario['historial']])
        msg_context_id = msg.get("context", {}).get("id")

        # F) INVOCAR CEREBRO IA (Service Call)
        # Auto-sync check
        db.trigger_sync_if_stale(minutes=30)
        
        threading.Thread(target=procesar_inteligencia_artificial, args=(
            numero, nombre, texto, historial_txt, usuario, msg_context_id, imagen_bytes, audio_bytes
        )).start()
        
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        logging.error(f"🔥 Error Webhook Controller: {e}")
        return jsonify({"status": "error"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
