import threading
import time
import requests
import random
import os
import logging
from datetime import datetime, timedelta

# Configuración de logs
logging.basicConfig(level=logging.INFO)

class GlamStoreDB:
    def __init__(self):
        self.productos = []
        self.total_items = 0
        self.identidad = "Cargando..."
        self.ultimo_update = "Nunca"
        # Credenciales
        self.shopify_token = os.environ.get("SHOPIFY_TOKEN")
        self.shopify_url = os.environ.get("SHOPIFY_URL")
        
        # Arrancamos el trabajador silencioso
        hilo = threading.Thread(target=self._sincronizar_loop)
        hilo.daemon = True
        hilo.start()

    def _sincronizar_loop(self):
        """Actualiza el stock cada 5 min"""
        while True:
            self._cargar_desde_shopify()
            time.sleep(300)

    def _cargar_desde_shopify(self):
        if not self.shopify_token or not self.shopify_url:
            logging.error("❌ DB: Faltan credenciales.")
            return
        
        clean_url = self.shopify_url.replace("https://", "").replace("/", "")
        url = f"https://{clean_url}/admin/api/2024-01/products.json"
        headers = {"X-Shopify-Access-Token": self.shopify_token, "Content-Type": "application/json"}
        
        try:
            logging.info("⏳ DB: Actualizando catálogo...")
            r = requests.get(url, headers=headers, params={"status": "active", "limit": 250}, timeout=20)
            
            if r.status_code == 200:
                self.productos = r.json().get("products", [])
                self.total_items = len(self.productos)
                # Hora Chile
                self.ultimo_update = (datetime.utcnow() - timedelta(hours=3)).strftime("%H:%M")
                
                if self.productos:
                    nombres = [p['title'] for p in self.productos[:8]]
                    ejemplos = ", ".join(nombres)
                    self.identidad = f"En vitrina: {ejemplos}..."
                else:
                    self.identidad = "Catálogo vacío."
                
                logging.info(f"✅ DB: Actualizado. {self.total_items} productos.")
            else:
                logging.error(f"❌ DB: Error Shopify {r.status_code}")
        except Exception as e:
            logging.error(f"❌ DB: Error conexión: {e}")

    # --- FUNCIONES PÚBLICAS ---

    def buscar_producto_rapido(self, consulta):
        """Busca en RAM"""
        if not self.productos: return {"tipo": "VACIO", "items": []}
        
        consulta = consulta.lower()
        encontrados = []
        
        for p in self.productos:
            full_text = f"{p['title']} {p.get('tags','')} {p.get('product_type','')}".lower()
            if consulta in full_text:
                encontrados.append(p)
        
        if not encontrados:
            return {"tipo": "RECOMENDACION", "items": random.sample(self.productos, min(5, len(self.productos)))}
            
        return {"tipo": "EXACTO", "items": encontrados[:5]}

    def obtener_identidad(self):
        return self.identidad

    def crear_link_pago_seguro(self, nombre_producto):
        """Va a Shopify en vivo"""
        if not self.shopify_token: return "ERROR_CREDS"
        
        clean_url = self.shopify_url.replace("https://", "").replace("/", "")
        headers = {"X-Shopify-Access-Token": self.shopify_token, "Content-Type": "application/json"}
        
        r = requests.get(f"https://{clean_url}/admin/api/2024-01/products.json", 
                         headers=headers, params={"title": nombre_producto, "status": "active", "limit": 1})
        prods = r.json().get("products", [])
        if not prods: return "NO_ENCONTRE_EXACTO"
        
        v = prods[0]['variants'][0]
        payload = {"draft_order": {"line_items": [{"variant_id": v['id'], "quantity": 1}]}}
        r2 = requests.post(f"https://{clean_url}/admin/api/2024-01/draft_orders.json", headers=headers, json=payload)
        
        if r2.status_code == 201:
            return r2.json().get("draft_order", {}).get("invoice_url")
        return "ERROR_LINK"

# INSTANCIA GLOBAL (Esto permite importarla)
db = GlamStoreDB()
