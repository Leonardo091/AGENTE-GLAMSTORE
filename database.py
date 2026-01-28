import threading
import time
import requests
import unicodedata
import os
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)

class GlamStoreDB:
    def __init__(self):
        self.productos = [] # ESTA ES TU TABLA EXCEL (ELEMENTO 3), PERO EN RAM
        self.total_items = 0
        self.identidad = "Cargando catálogo..."
        self.shopify_token = os.environ.get("SHOPIFY_TOKEN")
        self.shopify_url = os.environ.get("SHOPIFY_URL")
        
        # Elemento 2: El recolector automático
        hilo = threading.Thread(target=self._sincronizar_loop)
        hilo.daemon = True
        hilo.start()

    def _sincronizar_loop(self):
        """Mantiene la tabla actualizada 24/7"""
        while True:
            try: self._actualizar_tabla_maestra()
            except Exception as e: logging.error(f"⚠️ Error actualizando tabla: {e}")
            time.sleep(600) # Actualiza cada 10 min

    def _actualizar_tabla_maestra(self):
        if not self.shopify_token: return

        clean_url = self.shopify_url.replace("https://", "").replace("/", "")
        url = f"https://{clean_url}/admin/api/2024-01/products.json"
        headers = {"X-Shopify-Access-Token": self.shopify_token, "Content-Type": "application/json"}
        params = {"status": "active", "limit": 250}
        
        nueva_tabla = []
        logging.info("🔄 Elemento 2: Recopilando datos de Shopify...")
        
        while url:
            try:
                # Pausa para no saturar (Respiración)
                time.sleep(1)
                r = requests.get(url, headers=headers, params=params, timeout=20)
                if r.status_code != 200: break
                
                data = r.json().get("products", [])
                
                # LLENADO DE LA TABLA (ELEMENTO 3)
                for p in data:
                    try:
                        # Guardamos solo lo útil para no llenar la memoria basura
                        precio = float(p["variants"][0]["price"]) if p["variants"] else 0
                        
                        # TRUCO: Creamos un "Campo de Búsqueda" con todo el texto junto
                        # Ejemplo: "perfume lattafa yara arabe mujer 20000"
                        texto_busqueda = f"{p['title']} {p.get('vendor','')} {p.get('product_type','')}"
                        texto_busqueda = self._normalizar(texto_busqueda)
                        
                        fila = {
                            "id": p["id"],
                            "title": p["title"], # Nombre bonito
                            "price": precio,
                            "search_text": texto_busqueda, # Texto sucio para buscar
                            "variant_id": p["variants"][0]["id"] if p["variants"] else 0
                        }
                        nueva_tabla.append(fila)
                    except: pass

                if 'next' in r.links: 
                    url = r.links['next']['url']
                    params = {}
                else: url = None
            except: break
        
        if nueva_tabla:
            self.productos = nueva_tabla
            self.total_items = len(nueva_tabla)
            logging.info(f"✅ Tabla Maestra Actualizada: {self.total_items} productos listos.")

    # --- HERRAMIENTAS DE BÚSQUEDA (EL CEREBRO) ---

    def _normalizar(self, texto):
        """Quita acentos y mayúsculas para buscar fácil (Ej: 'Crema' = 'crema')"""
        if not texto: return ""
        return unicodedata.normalize('NFKD', str(texto)).encode('ASCII', 'ignore').decode('utf-8').lower()

    def buscar_producto_rapido(self, consulta):
        """
        Buscador Tipo Google:
        Si buscas 'perfume yara', busca productos que tengan 'perfume' Y 'yara'.
        """
        consulta_limpia = self._normalizar(consulta)
        palabras_clave = consulta_limpia.split() # Separa ["perfume", "yara"]
        
        encontrados = []
        
        # 1. BÚSQUEDA EN RAM (TABLA MAESTRA)
        if self.productos:
            for p in self.productos:
                # Verificamos si TODAS las palabras clave están en el producto
                # Así si pones "Mason", encontrará "Maison" si somos flexibles, 
                # pero por ahora buscaremos coincidencias parciales.
                coincidencias = 0
                for palabra in palabras_clave:
                    if palabra in p['search_text']:
                        coincidencias += 1
                
                # Si encontró todas las palabras (o la mayoría), es un match
                if coincidencias == len(palabras_clave):
                    encontrados.append(p)
            
            if encontrados:
                return {"tipo": "EXACTO", "items": encontrados[:5]}

        # 2. PLAN B: Si no encontró nada en RAM, o RAM está vacía...
        # Intentamos buscar en Shopify directo pero solo con la primera palabra clave importante
        # para tener suerte.
        keyword_principal = palabras_clave[-1] if palabras_clave else consulta
        return self._buscar_en_shopify_live(keyword_principal)

    def _buscar_en_shopify_live(self, query):
        if not self.shopify_token: return {"tipo": "VACIO", "items": []}
        clean_url = self.shopify_url.replace("https://", "").replace("/", "")
        headers = {"X-Shopify-Access-Token": self.shopify_token, "Content-Type": "application/json"}
        
        try:
            r = requests.get(f"https://{clean_url}/admin/api/2024-01/products.json", 
                             headers=headers, params={"title": query, "status": "active", "limit": 5}, timeout=5)
            if r.status_code == 200:
                data = r.json().get("products", [])
                items = [{"title": p["title"], "price": float(p["variants"][0]["price"])} for p in data]
                if items: return {"tipo": "EXACTO", "items": items}
        except: pass
        
        return {"tipo": "VACIO", "items": []}

    def crear_link_pago_seguro(self, texto_usuario):
        # Buscamos primero el producto exacto
        res = self.buscar_producto_rapido(texto_usuario)
        if not res["items"]: return "NO_ENCONTRE_EXACTO"
        
        producto_elegido = res["items"][0] # Tomamos el mejor candidato
        
        # Generamos link (Lógica estándar)
        if not self.shopify_token: return "ERROR_CREDS"
        clean_url = self.shopify_url.replace("https://", "").replace("/", "")
        headers = {"X-Shopify-Access-Token": self.shopify_token, "Content-Type": "application/json"}
        
        try:
            # Usamos el ID de variante que ya tenemos en la tabla
            variant_id = producto_elegido.get("variant_id")
            if not variant_id: return "ERROR_LINK"
            
            payload = {"draft_order": {"line_items": [{"variant_id": variant_id, "quantity": 1}]}}
            r = requests.post(f"https://{clean_url}/admin/api/2024-01/draft_orders.json", headers=headers, json=payload)
            if r.status_code == 201: return r.json().get("draft_order", {}).get("invoice_url")
        except: pass
        return "ERROR_LINK"

db = GlamStoreDB()
