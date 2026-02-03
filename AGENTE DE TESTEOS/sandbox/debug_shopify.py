import os
import requests
import json
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Cargar credenciales desde entorno (o hardcodear temporalmente para probar si os.environ falla)
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN")
SHOPIFY_URL = os.environ.get("SHOPIFY_URL")

logging.info(f"Token presente: {'SÍ' if SHOPIFY_TOKEN else 'NO'}")
logging.info(f"URL presente: {'SÍ' if SHOPIFY_URL else 'NO'}")

if SHOPIFY_URL:
    logging.info(f"URL: {SHOPIFY_URL}")

def test_shopify_connection():
    if not SHOPIFY_TOKEN or not SHOPIFY_URL:
        logging.error("❌ Faltan credenciales de Shopify.")
        return

    clean_url = SHOPIFY_URL.replace("https://", "").replace("/", "")
    url = f"https://{clean_url}/admin/api/2024-01/products.json"
    
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN, 
        "Content-Type": "application/json"
    }
    
    params = {"status": "active", "limit": 10} # Probamos con 10 productos
    
    logging.info(f"Intentando conectar a: {url}")
    
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        
        logging.info(f"Status Code: {r.status_code}")
        
        if r.status_code == 200:
            data = r.json()
            products = data.get("products", [])
            logging.info(f"✅ Conexión EXITOSA. Se obtuvieron {len(products)} productos de muestra.")
            
            for p in products:
                logging.info(f" - {p['title']} (ID: {p['id']})")
                if p.get("variants"):
                    logging.info(f"   Precio: {p['variants'][0]['price']}")
        else:
            logging.error(f"❌ Error en la respuesta: {r.text}")
            
    except Exception as e:
        logging.error(f"❌ Excepción conectando: {e}")

if __name__ == "__main__":
    test_shopify_connection()
