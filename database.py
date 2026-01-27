import threading
import time
import requests
import os
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)

class GlamStoreDB:
    def __init__(self):
        self.productos = []
        self.total_items = 0
        self.identidad = "GlamStore Asistente (Modo Híbrido)"
        self.shopify_token = os.environ.get("SHOPIFY_TOKEN")
        self.shopify_url = os.environ.get("SHOPIFY_URL")
        
        # Iniciamos hilo silencioso
        hilo = threading.Thread(target=self._sincronizar_loop)
        hilo.daemon = True
        hilo.start()

    def _sincronizar_loop(self):
        while True:
            try: self._cargar_masivo()
            except: pass
            time.sleep(600) # Descansa 10 minutos entre cargas completas

    def _cargar_masivo(self):
        if not self.shopify_token or not self.shopify_url: return
        clean_url = self.shopify_url.replace("https://", "").replace("/", "")
        url = f"https://{clean_url}/admin/api/2024-01/products.json"
        headers = {"X-Shopify-Access-Token": self.shopify_token, "Content-Type": "application/json"}
        params = {"status": "active", "limit": 250}
        
        acumulado = []
        
        logging.info("⏳ DB: Iniciando carga suave en segundo plano...")
        
        while url:
            try:
                # --- AQUÍ ESTÁ EL TRUCO: PAUSA PARA RESPIRAR ---
                # Dormimos 2 segundos entre paginas para no saturar la CPU
                # y dejar que WhatsApp funcione fluido.
                time.sleep(2) 
                
                r = requests.get(url, headers=headers, params=params, timeout=20)
                if r.status_code != 200: break
                
                data = r.json().get("products", [])
                for p in data:
                    try:
                        price = float(p["variants"][0]["price"]) if p["variants"] else 0
                        acumulado.append({"id": p["id"], "title": p["title"], "price": price})
                    except: pass
                
                logging.info(f"📦 Bajados {len(data)} items... (Respirando)")

                if 'next' in r.links: 
                    url = r.links['next']['url']
                    params = {}
                else: 
                    url = None
            except: break
        
        if acumulado:
            self.productos = acumulado
            self.total_items = len(acumulado)
            self.identidad = f"Catálogo cargado: {self.total_items} productos."
            logging.info("✅ DB: Carga completa finalizada.")

    def buscar_producto_rapido(self, consulta):
        consulta = consulta.lower()
        
        # 1. RAM (Si ya cargó)
        if self.productos:
            encontrados = [p for p in self.productos if consulta in p['title'].lower()]
            if encontrados: return {"tipo": "EXACTO", "items": encontrados[:5]}

        # 2. SHOPIFY LIVE (Respaldo)
        return self._buscar_en_shopify_live(consulta)

    def _buscar_en_shopify_live(self, query):
        if not self.shopify_token: return {"tipo": "VACIO", "items": []}
        clean_url = self.shopify_url.replace("https://", "").replace("/", "")
        headers = {"X-Shopify-Access-Token": self.shopify_token, "Content-Type": "application/json"}
        
        try:
            # Timeout corto (5s) para no pegar el chat si Shopify está lento
            r = requests.get(f"https://{clean_url}/admin/api/2024-01/products.json", 
                             headers=headers, params={"title": query, "status": "active", "limit": 5}, timeout=5)
            if r.status_code == 200:
                data = r.json().get("products", [])
                items = []
                for p in data:
                    price = float(p["variants"][0]["price"]) if p["variants"] else 0
                    items.append({"title": p["title"], "price": price})
                if items: return {"tipo": "EXACTO", "items": items}
        except: pass
        
        return {"tipo": "VACIO", "items": []}

    def obtener_identidad(self):
        if self.total_items == 0: return "Tienda de Belleza (Modo Respaldo Activo)"
        return self.identidad

    def crear_link_pago_seguro(self, nombre_producto):
        if not self.shopify_token: return "ERROR_CREDS"
        clean_url = self.shopify_url.replace("https://", "").replace("/", "")
        headers = {"X-Shopify-Access-Token": self.shopify_token, "Content-Type": "application/json"}
        try:
            r = requests.get(f"https://{clean_url}/admin/api/2024-01/products.json", 
                            headers=headers, params={"title": nombre_producto, "status": "active", "limit": 1})
            prods = r.json().get("products", [])
            if not prods: return "NO_ENCONTRE_EXACTO"
            v = prods[0]['variants'][0]
            payload = {"draft_order": {"line_items": [{"variant_id": v['id'], "quantity": 1}]}}
            r2 = requests.post(f"https://{clean_url}/admin/api/2024-01/draft_orders.json", headers=headers, json=payload)
            if r2.status_code == 201: return r2.json().get("draft_order", {}).get("invoice_url")
        except: pass
        return "ERROR_LINK"

db = GlamStoreDB()
