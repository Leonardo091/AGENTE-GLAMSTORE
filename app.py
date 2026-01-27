import os
import requests
from flask import Flask, jsonify

app = Flask(__name__)

# --- CONFIGURACIÓN ---
TOKEN = os.environ.get("SHOPIFY_TOKEN")
URL_TIENDA = os.environ.get("SHOPIFY_URL")

@app.route("/")
def home():
    # 1. VERIFICAMOS CREDENCIALES
    if not TOKEN:
        return jsonify({"estado": "ERROR ❌", "motivo": "Falta variable SHOPIFY_TOKEN en Render"}), 500
    if not URL_TIENDA:
        return jsonify({"estado": "ERROR ❌", "motivo": "Falta variable SHOPIFY_URL en Render"}), 500

    # 2. INTENTAMOS CONECTAR (Solo 1 producto, 5 seg timeout)
    try:
        clean_url = URL_TIENDA.replace("https://", "").replace("http://", "")
        if "/" in clean_url: clean_url = clean_url.split("/")[0]
        
        target_url = f"https://{clean_url}/admin/api/2024-01/products.json"
        headers = {
            "X-Shopify-Access-Token": TOKEN,
            "Content-Type": "application/json"
        }
        
        # Hacemos la petición AQUÍ Y AHORA
        response = requests.get(target_url, headers=headers, params={"limit": 1}, timeout=10)
        
        if response.status_code == 200:
            data = response.json().get("products", [])
            nombre = data[0]['title'] if data else "Ninguno"
            return jsonify({
                "estado": "ÉXITO TOTAL ✅",
                "mensaje": "¡Conexión Perfecta!",
                "tienda": clean_url,
                "producto_ejemplo": nombre,
                "nota": "Si ves esto, las credenciales están perfectas."
            }), 200
            
        elif response.status_code == 401:
            return jsonify({"estado": "ERROR 401 ⛔", "motivo": "Token Rechazado (Verifica SHOPIFY_TOKEN)"}), 401
        elif response.status_code == 403:
            return jsonify({"estado": "ERROR 403 🛡️", "motivo": "Permisos Faltantes (Falta 'read_products' en Shopify)"}), 403
        elif response.status_code == 404:
            return jsonify({"estado": "ERROR 404 🔍", "motivo": "Tienda no encontrada (Verifica SHOPIFY_URL)"}), 404
        else:
            return jsonify({"estado": f"ERROR {response.status_code} ⚠️", "resp": response.text}), 500

    except Exception as e:
        return jsonify({"estado": "CRASH TÉCNICO 💥", "error": str(e)}), 500

# Webhook dummy para que no falle WhatsApp mientras probamos
@app.route("/webhook", methods=["POST"])
def webhook(): return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
