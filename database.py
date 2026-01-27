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
        
        # Intentamos cargar la RAM en segundo plano, pero sin estrés
        hilo = threading.Thread(target=self._sincronizar_loop)
        hilo.daemon = True
        hilo.start()

    def _sincronizar_loop(self):
        """Intenta llenar la memoria RAM. Si falla, no importa, usaremos Plan B."""
        while True:
            try:
                self._cargar_masivo()
            except Exception as e:
                logging.error(f"⚠️ Error en carga background: {e}")
            time.sleep(600) # Reintentar cada 10 min

    def _cargar_masivo(self):
        if not self.shopify_token or not self.shopify_url: return

        clean_url = self.shopify_url.replace("https://", "").replace("/", "")
        url = f"https://{clean_url}/admin/api/2024-01/products.json"
        headers = {"X-Shopify-Access-Token": self.shopify_token, "Content-Type": "application/json"}
        params = {"status": "active", "limit": 250}
        
        acumulado = []
        logging.info("⏳ DB: Iniciando carga de memoria RAM...")
        
        while url:
            r = requests.get(url, headers=headers, params=params, timeout=30)
            if r.status_code != 200: break
            
            data = r.json().get("products", [])
            for p in data:
                try:
                    price = float(p["variants"][0]["price"]) if p["variants"] else 0
                    acumulado.append({
                        "id": p["id"],
                        "title": p["title"],
                        "price": price,
                        "variant_id": p["variants"][0]["id"] if p["variants"] else 0
                    })
                except: pass
            
            if 'next' in r.links:
                url = r.links['next']['url']
                params = {}
            else:
                url = None
        
        if acumulado:
            self.productos = acumulado
            self.total_items = len(acumulado)
            nombres = [p['title'] for p in self.productos[:5]]
            self.identidad = f"Vitrina: {', '.join(nombres)}..."
            logging.info(f"✅ DB: Memoria RAM lista con {self.total_items} productos.")

    # --- AQUÍ ESTÁ LA MAGIA DEL MODO HÍBRIDO ---

    def buscar_producto_rapido(self, consulta):
        """
        Si hay datos en RAM, busca ahí (Rápido).
        Si NO hay datos en RAM, busca en Shopify en vivo (Seguro).
        """
        # PLAN A: RAM
        if self.productos:
            consulta = consulta.lower()
            encontrados = [p for p in self.productos if consulta in p['title'].lower()]
            if encontrados:
                return {"tipo": "EXACTO", "items": encontrados[:5]}
            return {"tipo": "VACIO", "items": []} # Si buscó en RAM y no halló, es que no hay.

        # PLAN B: SHOPIFY EN VIVO (Respaldo)
        logging.info(f"🔄 RAM vacía. Buscando '{consulta}' directo en Shopify...")
        return self._buscar_en_shopify_live(consulta)

    def _buscar_en_shopify_live(self, query):
        if not self.shopify_token: return {"tipo": "VACIO", "items": []}
        
        clean_url = self.shopify_url.replace("https://", "").replace("/", "")
        headers = {"X-Shopify-Access-Token": self.shopify_token, "Content-Type": "application/json"}
        # Buscamos directo en la API
        url = f"https://{clean_url}/admin/api/2024-01/products.json"
        params = {"title": query, "status": "active", "limit": 5}
        
        try:
            r = requests.get(url, headers=headers, params=params, timeout=10)
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
        # Si la RAM está vacía, damos una identidad genérica pero útil
        if self.total_items == 0:
            return "Tienda de Belleza y Maquillaje (Catálogo Online)"
        return self.identidad

    def crear_link_pago_seguro(self, nombre_producto):
        # Esta función siempre ha sido directa, así que funciona perfecto
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
            
            if r2.status_code == 201:
                return r2.json().get("draft_order", {}).get("invoice_url")
        except: pass
        return "ERROR_LINK"

db = GlamStoreDB()
