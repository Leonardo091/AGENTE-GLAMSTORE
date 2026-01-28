import threading
import time
import requests
import unicodedata
import os
import logging
import random

# Logs limpios
logging.basicConfig(level=logging.INFO, format='%(message)s')

class GlamStoreDB:
    def __init__(self):
        self.productos = [] 
        self.total_items = 0
        self.identidad = "Cargando..."
        self.shopify_token = os.environ.get("SHOPIFY_TOKEN")
        self.shopify_url = os.environ.get("SHOPIFY_URL")
        
        # Palabras que NO sirven para buscar producto específico
        self.palabras_basura = [
            "hola", "buenos", "dias", "tardes", "busco", "venden", "tienen", 
            "quiero", "necesito", "comprar", "precio", "valor", "cuanto", 
            "vale", "cuesta", "ejemplo", "muestrame", "algun", "alguno", 
            "articulo", "producto", "dato", "puedes", "dar", "me", "das",
            "recomendar", "recomendarias", "para", "mi", "hija", "mama", "regalo"
        ]
        
        # Trabajador en segundo plano
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
        logging.info("🔄 DB: Sincronizando inventario...")
        
        while url:
            try:
                time.sleep(0.5)
                r = requests.get(url, headers=headers, params=params, timeout=15)
                if r.status_code != 200: break
                
                data = r.json().get("products", [])
                for p in data:
                    try:
                        precio = float(p["variants"][0]["price"]) if p["variants"] else 0
                        texto_sucio = f"{p['title']} {p.get('vendor','')} {p.get('product_type','')} {p.get('tags','')}"
                        texto_limpio = self._normalizar(texto_sucio)
                        
                        nueva_tabla.append({
                            "id": p["id"],
                            "title": p["title"],
                            "price": precio,
                            "search_text": texto_limpio,
                            "category_text": texto_limpio, # Para búsquedas amplias
                            "variant_id": p["variants"][0]["id"] if p["variants"] else 0
                        })
                    except: pass

                if 'next' in r.links: url = r.links['next']['url']; params = {}
                else: url = None
            except: break
        
        if nueva_tabla:
            self.productos = nueva_tabla
            self.total_items = len(nueva_tabla)
            logging.info(f"✅ DB: Inventario listo con {self.total_items} productos.")

    def _normalizar(self, texto):
        if not texto: return ""
        return unicodedata.normalize('NFKD', str(texto)).encode('ASCII', 'ignore').decode('utf-8').lower()

    # --- FUNCIONES DE BÚSQUEDA ELITE ---

    def buscar_contextual(self, texto_usuario):
        """
        Esta es la clave. Si el usuario pide "perfume", sacamos perfumes REALES del stock.
        """
        texto_limpio = self._normalizar(texto_usuario)
        palabras = texto_limpio.split()
        
        # 1. Detectar intención de categoría
        categorias_clave = ["perfume", "colonia", "aroma", "labial", "rimel", "crema", "shampoo", "capilar", "maquillaje"]
        categoria_detectada = None
        
        for cat in categorias_clave:
            if cat in texto_limpio:
                categoria_detectada = cat
                break
        
        resultados = []
        
        # Si detectamos categoría, filtramos el stock por eso
        if categoria_detectada and self.productos:
            candidatos = [p for p in self.productos if categoria_detectada in p['search_text']]
            # Tomamos 5 al azar para dar variedad
            if candidatos:
                resultados = random.sample(candidatos, min(5, len(candidatos)))
                return {"tipo": "RECOMENDACION_REAL", "items": resultados}

        # Si no es categoría, buscamos palabras específicas (marca o nombre)
        keywords = [p for p in palabras if p not in self.palabras_basura]
        if keywords and self.productos:
            for p in self.productos:
                matches = 0
                for kw in keywords:
                    if kw in p['search_text']: matches += 1
                if matches >= len(keywords):
                    resultados.append(p)
            
            if resultados:
                return {"tipo": "EXACTO", "items": resultados[:5]}
        
        return {"tipo": "VACIO", "items": []}

    def generar_checkout(self, texto_usuario):
        # Buscamos el producto más probable
        res = self.buscar_contextual(texto_usuario)
        if not res["items"]: return None
        
        producto = res["items"][0] # El mejor candidato
        
        clean_url = self.shopify_url.replace("https://", "").replace("/", "")
        headers = {"X-Shopify-Access-Token": self.shopify_token, "Content-Type": "application/json"}
        
        try:
            payload = {"draft_order": {"line_items": [{"variant_id": producto['variant_id'], "quantity": 1}]}}
            r = requests.post(f"https://{clean_url}/admin/api/2024-01/draft_orders.json", headers=headers, json=payload)
            if r.status_code == 201: 
                return {"url": r.json().get("draft_order", {}).get("invoice_url"), "nombre": producto['title']}
        except: pass
        return None

db = GlamStoreDB()
