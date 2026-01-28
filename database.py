import threading
import time
import requests
import unicodedata
import os
import logging

logging.basicConfig(level=logging.INFO)

class GlamStoreDB:
    def __init__(self):
        self.productos = [] 
        self.total_items = 0
        self.identidad = "Cargando catálogo..."
        self.shopify_token = os.environ.get("SHOPIFY_TOKEN")
        self.shopify_url = os.environ.get("SHOPIFY_URL")
        
        # Palabras que el buscador va a IGNORAR para no confundirse
        self.palabras_basura = [
            "hola", "buenos", "dias", "tardes", "noches",
            "busco", "venden", "tienen", "quiero", "necesito", "comprar",
            "precio", "valor", "cuanto", "vale", "cuesta",
            "el", "la", "los", "las", "un", "una", "de", "del", "en", "que"
        ]
        
        hilo = threading.Thread(target=self._sincronizar_loop)
        hilo.daemon = True
        hilo.start()

    def _sincronizar_loop(self):
        while True:
            try: self._actualizar_tabla_maestra()
            except: pass
            time.sleep(600)

    def _actualizar_tabla_maestra(self):
        if not self.shopify_token: return
        clean_url = self.shopify_url.replace("https://", "").replace("/", "")
        url = f"https://{clean_url}/admin/api/2024-01/products.json"
        headers = {"X-Shopify-Access-Token": self.shopify_token, "Content-Type": "application/json"}
        params = {"status": "active", "limit": 250}
        
        nueva_tabla = []
        logging.info("🔄 Recopilando datos de Shopify...")
        
        while url:
            try:
                time.sleep(1) # Respiro
                r = requests.get(url, headers=headers, params=params, timeout=20)
                if r.status_code != 200: break
                
                data = r.json().get("products", [])
                for p in data:
                    try:
                        precio = float(p["variants"][0]["price"]) if p["variants"] else 0
                        # Normalizamos el texto de búsqueda
                        texto_sucio = f"{p['title']} {p.get('vendor','')} {p.get('tags','')}"
                        texto_limpio = self._normalizar(texto_sucio)
                        
                        nueva_tabla.append({
                            "id": p["id"],
                            "title": p["title"],
                            "price": precio,
                            "search_text": texto_limpio,
                            "variant_id": p["variants"][0]["id"] if p["variants"] else 0
                        })
                    except: pass

                if 'next' in r.links: url = r.links['next']['url']; params = {}
                else: url = None
            except: break
        
        if nueva_tabla:
            self.productos = nueva_tabla
            self.total_items = len(nueva_tabla)
            logging.info(f"✅ Tabla Maestra: {self.total_items} productos.")

    def _normalizar(self, texto):
        if not texto: return ""
        return unicodedata.normalize('NFKD', str(texto)).encode('ASCII', 'ignore').decode('utf-8').lower()

    def buscar_producto_rapido(self, consulta):
        """
        Buscador Inteligente:
        1. Limpia la consulta (quita 'venden', 'busco').
        2. Busca lo que queda.
        """
        consulta_limpia = self._normalizar(consulta)
        palabras = consulta_limpia.split()
        
        # FILTRO IMPORTANTE: Quitamos palabras basura
        palabras_clave = [p for p in palabras if p not in self.palabras_basura]
        
        # Si el cliente solo dijo "que venden" y borramos todo, devolvemos VACIO especial
        if not palabras_clave:
            return {"tipo": "VACIO", "motivo": "SOLO_STOPWORDS", "items": []}
            
        encontrados = []
        
        # 1. BÚSQUEDA EN RAM
        if self.productos:
            for p in self.productos:
                # Buscamos si TODAS las palabras clave (útiles) están en el producto
                coincidencias = 0
                for clave in palabras_clave:
                    if clave in p['search_text']:
                        coincidencias += 1
                
                if coincidencias == len(palabras_clave):
                    encontrados.append(p)
            
            if encontrados:
                return {"tipo": "EXACTO", "items": encontrados[:5]}

        return {"tipo": "VACIO", "items": []}

    def crear_link_pago_seguro(self, texto_usuario):
        # Usamos el mismo buscador inteligente para encontrar el producto
        res = self.buscar_producto_rapido(texto_usuario)
        if not res["items"]: return "NO_ENCONTRE_EXACTO"
        
        producto = res["items"][0]
        if not self.shopify_token: return "ERROR_CREDS"
        
        clean_url = self.shopify_url.replace("https://", "").replace("/", "")
        headers = {"X-Shopify-Access-Token": self.shopify_token, "Content-Type": "application/json"}
        
        try:
            payload = {"draft_order": {"line_items": [{"variant_id": producto['variant_id'], "quantity": 1}]}}
            r = requests.post(f"https://{clean_url}/admin/api/2024-01/draft_orders.json", headers=headers, json=payload)
            if r.status_code == 201: return r.json().get("draft_order", {}).get("invoice_url")
        except: pass
        return "ERROR_LINK"

db = GlamStoreDB()
