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
# MODO_VACACIONES controlado por DB
# db.modo_vacaciones = True (Seteado en Database __init__)
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

@app.route("/admin/db")
def admin_db():
    try:
        # Forzar lectura de disco para evitar consistencia eventual entre workers
        products = db.get_productos_frescos()
        status = db.get_status()
        html = f"""
        <!DOCTYPE html>
        <html lang="es">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Admin GlamStore DB</title>
            <!-- Bootstrap 5 & DataTables CSS -->
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
            <link href="https://cdn.datatables.net/1.13.6/css/dataTables.bootstrap5.min.css" rel="stylesheet">
            <link href="https://cdn.datatables.net/responsive/2.5.0/css/responsive.bootstrap5.min.css" rel="stylesheet">
            <style>
                body {{ background-color: #f8f9fa; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 0.9rem; }}
                .container-fluid {{ max-width: 98%; margin-top: 20px; }}
                .card {{ border: none; shadow: 0 4px 6px rgba(0,0,0,0.1); border-radius: 12px; }}
                .header-area {{ background: linear-gradient(135deg, #d53369 0%, #daae51 100%); color: white; padding: 15px; border-radius: 12px 12px 0 0; }}
                .btn-sync {{ background-color: rgba(255,255,255,0.2); color: white; border: 1px solid white; backdrop-filter: blur(5px); padding: 5px 15px; font-size: 0.9rem; }}
                .btn-sync:hover {{ background-color: white; color: #d53369; }}
                table.dataTable thead th {{ background-color: #f1f1f1; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px; }}
                table.dataTable tbody td {{ vertical-align: middle; }}
                .badge-stock-low {{ background-color: #ffc107; color: #000; }}
                .badge-stock-out {{ background-color: #dc3545; color: white; }}
                .badge-stock-ok {{ background-color: #198754; color: white; }}
                .badge-stock-low {{ background-color: #ffc107; color: #000; }}
                .badge-stock-out {{ background-color: #dc3545; color: white; }}
                .badge-stock-ok {{ background-color: #198754; color: white; }}
            </style>
        </head>
        <body>
            <div class="container-fluid mb-5">
                <div class="card shadow">
                    <div class="header-area d-flex justify-content-between align-items-center">
                        <div>
                            <h2 class="mb-0">✨ GlamStore Inventory</h2>
                            <small>Total: {len(products)} productos | Sync: {status.get('sync_status')}</small>
                        </div>
                        <a href="/admin/force_sync" class="btn btn-sync fw-bold">🔄 Forzar Sincronización</a>
                    </div>
                    <div class="card-body bg-white">
                        <div class="alert alert-info py-2" role="alert">
                            <small>ℹ️ <strong>Tips:</strong> Puedes buscar por cualquier columna. Haz clic en los encabezados para ordenar.</small>
                        </div>
                        
                        <table id="productsTable" class="table table-striped table-hover dt-responsive nowrap" style="width:100%">
                            <thead>
                                <tr>
                                    <th>ID</th>
                                    <th>Título</th>
                                    <th>Categoría</th>
                                    <th>Precio</th>
                                    <th>Oferta</th>
                                    <th>Stock</th>
                                    <th>Tags</th>
                                    <th>Vendor</th>
                                </tr>
                            </thead>
                            <tbody>
                                {''.join([f"<tr><td><small class='text-muted'>{p.get('id')}</small></td><td class='fw-bold'>{p.get('title')}</td><td><span class='badge bg-secondary'>{p.get('category','')}</span></td><td>${int(float(p.get('price',0))):,}</td><td class='text-success'>{f'${int(float(p.get('compare_at_price',0))):,}' if p.get('compare_at_price') else '-'}</td><td>{p.get('stock')}</td><td><small>{p.get('tags','')[:50]}...</small></td><td><small>{p.get('vendor')}</small></td></tr>" for p in products])}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- Scripts -->
            <script src="https://code.jquery.com/jquery-3.7.0.min.js"></script>
            <script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>
            <script src="https://cdn.datatables.net/1.13.6/js/dataTables.bootstrap5.min.js"></script>
            <script src="https://cdn.datatables.net/responsive/2.5.0/js/dataTables.responsive.min.js"></script>
            <script src="https://cdn.datatables.net/responsive/2.5.0/js/responsive.bootstrap5.min.js"></script>
            <script>
                $(document).ready(function() {{
                    $('#productsTable').DataTable({{
                        responsive: true,
                        pageLength: 25,
                        language: {{
                            url: '//cdn.datatables.net/plug-ins/1.13.6/i18n/es-ES.json'
                        }},
                        order: [[1, 'asc']]
                    }});
                }});
            </script>
        </body>
        </html>
        """
        return html
    except Exception as e:
        return f"Error leyendo DB: {str(e)}", 500

@app.route("/admin/force_sync")
def admin_force_sync():
    import threading
    threading.Thread(target=db._actualizar_tabla_maestra).start()
    return "Sincronización iniciada en segundo plano. <a href='/admin/db'>Volver</a>"

@app.route("/debug/shopify")
def debug_shopify():
    try:
        if not db.shopify_token or not db.shopify_url:
            return jsonify({"error": "Missing Credentials"}), 500
            
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": db.shopify_token
        }
        
        # Query Completa de Prueba
        query = """
        {
          products(first: 3) {
            edges {
              node {
                id
                title
                category { name }
                variants(first: 1) {
                  edges {
                    node {
                      price
                      compareAtPrice
                    }
                  }
                }
              }
            }
          }
        }
        """
        
        response = requests.post(f"https://{db.shopify_url}/admin/api/2023-01/graphql.json", json={"query": query}, headers=headers)
        
        return jsonify({
            "status_code": response.status_code,
            "url": f"https://{db.shopify_url}/admin/api/2023-01/graphql.json",
            "response_headers": dict(response.headers),
            "response_body": response.json() if response.status_code == 200 else response.text
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
        if texto.startswith("!db") or texto.startswith("!comandos"):
             admin_numbers = os.environ.get("ADMIN_NUMBER", "").split(",")
             es_admin = any(admin.strip() in numero for admin in admin_numbers if admin.strip())
             
             if es_admin:
                 # --- COMANDO: !comandos ---
                 if "!comandos" in texto:
                     help_txt = """🛠️ *Panel de Admin GlamStore* 🛠️

1. *!db sync*
   🔄 Fuerza actualización inmediata con Shopify.
2. *!db email [correo]*
   📧 Envía la BDD completa en CSV a tu correo.
   (Si no pones correo, usa el por defecto).
3. *!comandos*
   📜 Muestra esta lista.
4. *!modo ventas*
   🟢 Activa ventas y links de pago.
5. *!modo vacaciones*
   🔴 Cierra ventas (Solo catálogo).
"""
                     enviar_whatsapp(numero, help_txt)
                     return jsonify({"status": "admin_cmd_help"}), 200

                 # --- COMANDO: !db sync ---
                 if "sync" in texto:
                     threading.Thread(target=db.force_sync).start()
                     enviar_whatsapp(numero, "⏳ *Sync Iniciado...* \n(Te avisaré si hay errores en el log, si no, asume éxito en 1 min).")
                     return jsonify({"status": "admin_cmd_sync"}), 200

                 # --- COMANDO: !db email ---
                 if "email" in texto:
                     # Render bloquea puertos SMTP (Email).
                     # Mejor opción: Dar link a la vista web de Admin.
                     msg = """📧 *Reporte de Base de Datos*
El servidor de Render bloquea el envío de correos por seguridad. 🔒

Pero tengo algo MEJOR:
📊 **Ver Tabla en Vivo:**
https://agente-glamstore.onrender.com/admin/db

(Desde ahí puedes ver todo el inventario actualizado al segundo)."""
                     enviar_whatsapp(numero, msg)
                     return jsonify({"status": "admin_cmd_email_redirect"}), 200

                 # --- COMANDO: !modo ventas ---
                 if "ventas" in texto and "modo" in texto:
                     db.modo_vacaciones = False
                     enviar_whatsapp(numero, "🟢 *¡MODO VENTAS ACTIVADO!* 💰\n✅ El bot ahora venderá y generará links de pago.\n✅ Mensajes de 'Vacaciones' desactivados.")
                     return jsonify({"status": "admin_cmd_sales_mode"}), 200

                 # --- COMANDO: !modo vacaciones ---
                 if "vacaciones" in texto and "modo" in texto:
                     db.modo_vacaciones = True
                     enviar_whatsapp(numero, "🔴 *¡MODO VACACIONES ACTIVADO!* 🌴\n⛔ Ventas pausadas. El bot solo mostrará el catálogo (Modo Revista).")
                     return jsonify({"status": "admin_cmd_vacation_mode"}), 200

             return jsonify({"status": "admin_cmd_ignored"}), 200

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
