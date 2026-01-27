import threading
import time
import requests
import random
import os
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)

class GlamStoreDB:
    def __init__(self):
        self.productos = []
        self.total_items = 0
        self.identidad = "Cargando..."
        self.ultimo_update = "Nunca"
        self.shopify_token = os.environ.get("SHOPIFY_TOKEN")
        self.shopify_url = os.environ.get("SHOPIFY_URL")
        
        # Arrancamos el trabajador
        hilo = threading.Thread(target=self._sincronizar_loop)
        hilo.daemon = True
        hilo.start()

    def _sincronizar_loop(self):
        while True:
            self._cargar_desde_shopify()
            time.sleep(600) # 10 minutos

    def _cargar_desde_shopify(self):
        if not self.shopify_token or not self.shopify_url:
            logging.error("❌ DB: Faltan credenciales.")
            return
        
        clean_url = self.shopify_url.replace("https://", "").replace("/", "")
        url = f"https://{clean_url}/admin/api/2024-01/products.json"
        headers = {"X-Shopify-Access-Token": self.shopify_token, "Content-Type": "application/json"}
        params = {"status": "active", "limit": 250}
        
        acumulado_lite = [] # Aquí guardaremos solo lo importante
        
        try:
            logging.info("⏳ DB: Iniciando descarga masiva OPTIMIZADA...")
            
            while url:
                r = requests.get(url, headers=headers, params=params, timeout=20)
                if r.status_code != 200: break
                
                raw_data = r.json().get("products", [])
                
                # --- LA DIETA (OPTIMIZACIÓN DE RAM) ---
                for p in raw_data:
                    try:
                        # Solo guardamos lo vital. El resto a la basura.
                        item_lite = {
                            "id": p["id"],
                            "title": p["title"],
                            "tags": p.get("tags", ""),
                            # Guardamos el precio listo para no calcularlo cada vez
                            "price": float(p["variants"][0]["price"]),
                            "variant_id": p["variants"][0]["id"]
                        }
                        acumulado_lite.append(item_lite)
                    except: pass # Si un producto está roto, lo saltamos

                logging.info(f"📦 Procesados {len(acumulado_lite)} productos (Modo Liviano)...")

                if 'next' in r.links:
                    url = r.links['next']['url']
                    params = {}
                else:
                    url = None

            # Guardamos la lista liviana
            self.productos = acumulado_lite
            self.total_items = len(self.productos)
            self.ultimo_update = (datetime.utcnow() - timedelta(hours=3)).strftime("%H:%M")
            
            if self.productos:
                # Actualizamos identidad
                nombres = [p['title'] for p in self.productos[:10]]
                self.identidad = f"Vitrina: {', '.join(nombres)}..."
            
            logging.info(f"✅ DB: CARGA TOTAL EXITOSA. {self.total_items} productos en memoria (Optimizado).")

        except Exception as e:
            logging.error(f"❌ DB: Error conexión: {e}")

    # --- FUNCIONES PÚBLICAS (ADAPTADAS A LA VERSIÓN LITE) ---

    def buscar_producto_rapido(self, consulta):
        if not self.productos: return {"tipo": "VACIO", "items": []}
        
        consulta = consulta.lower()
        encontrados = []
        
        for p in self.productos:
            # Buscamos solo en título y tags (es más rápido)
            full_text = f"{p['title']} {p['tags']}".lower()
            if consulta in full_text:
                encontrados.append(p)
        
        if not encontrados:
            return {"tipo": "RECOMENDACION", "items": random.sample(self.productos, min(5, len(self.productos)))}
            
        return {"tipo": "EXACTO", "items": encontrados[:5]}

    def obtener_identidad(self):
        return self.identidad

    def crear_link_pago_seguro(self, nombre_producto):
        # Esta función sigue yendo a Shopify en vivo por seguridad
        # No cambia porque usa requests, no la memoria RAM
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

db = GlamStoreDB()
