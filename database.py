import threading
import time
import requests
import unicodedata
import os
import logging
import random

# Configuración de Logs Profesional
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

class GlamStoreDB:
    def __init__(self):
        self.productos = [] 
        self.total_items = 0
        self.identidad = "Cargando catálogo..."
        self.shopify_token = os.environ.get("SHOPIFY_TOKEN")
        self.shopify_url = os.environ.get("SHOPIFY_URL")
        
        # Stopwords: Palabras que el buscador debe ignorar para no confundirse
        self.palabras_basura = [
            "hola", "buenos", "dias", "tardes", "busco", "venden", "tienen", 
            "quiero", "necesito", "comprar", "precio", "valor", "cuanto", 
            "vale", "cuesta", "ejemplo", "muestrame", "algun", "alguno", 
            "articulo", "producto", "dato", "puedes", "dar", "me", "das"
        ]
        
        # Iniciamos el trabajador en segundo plano
        hilo = threading.Thread(target=self._sincronizar_loop)
        hilo.daemon = True
        hilo.start()

    def _sincronizar_loop(self):
        while True:
            try: self._actualizar_tabla_maestra()
            except Exception as e: logging.error(f"⚠️ Error Sync: {e}")
            time.sleep(600) # 10 minutos

    def _actualizar_tabla_maestra(self):
        if not self.shopify_token: return
        
        clean_url = self.shopify_url.replace("https://", "").replace("/", "")
        url = f"https://{clean_url}/admin/api/2024-01/products.json"
        headers = {"X-Shopify-Access-Token": self.shopify_token, "Content-Type": "application/json"}
        params = {"status": "active", "limit": 250}
        
        nueva_tabla = []
        logging.info("🔄 DB: Iniciando sincronización...")
        
        while url:
            try:
                time.sleep(0.5) # Pequeña pausa para estabilidad
                r = requests.get(url, headers=headers, params=params, timeout=15)
                if r.status_code != 200: break
                
                data = r.json().get("products", [])
                for p in data:
                    try:
                        precio = float(p["variants"][0]["price"]) if p["variants"] else 0
                        # Creamos un texto de búsqueda enriquecido
                        texto_sucio = f"{p['title']} {p.get('vendor','')} {p.get('product_type','')} {p.get('tags','')}"
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
            logging.info(f"✅ DB: Sincronizada con {self.total_items} productos.")

    def _normalizar(self, texto):
        if not texto: return ""
        return unicodedata.normalize('NFKD', str(texto)).encode('ASCII', 'ignore').decode('utf-8').lower()

    # --- FUNCIONES DE ÉLITE ---

    def obtener_recomendados(self, cantidad=5):
        """Devuelve productos al azar para cuando el cliente pide 'ejemplos'"""
        if not self.productos: return []
        return random.sample(self.productos, min(cantidad, len(self.productos)))

    def buscar_inteligente(self, consulta):
        """Buscador que limpia la basura y busca coincidencias flexibles"""
        consulta_limpia = self._normalizar(consulta)
        palabras = consulta_limpia.split()
        
        # Filtramos palabras inútiles
        keywords = [p for p in palabras if p not in self.palabras_basura]
        
        if not keywords: 
            return {"tipo": "VACIO", "motivo": "NO_KEYWORDS", "items": []}
            
        encontrados = []
        # Buscamos en RAM
        if self.productos:
            for p in self.productos:
                coincidencias = 0
                for kw in keywords:
                    if kw in p['search_text']: coincidencias += 1
                
                # Si coincide al menos con todas las palabras clave buscadas
                if coincidencias >= len(keywords):
                    encontrados.append(p)
            
            if encontrados:
                return {"tipo": "EXACTO", "items": encontrados[:5]}

        return {"tipo": "VACIO", "motivo": "SIN_STOCK", "items": []}

    def generar_checkout(self, texto_usuario):
        # Intentamos encontrar el producto para vender
        res = self.buscar_inteligente(texto_usuario)
        if not res["items"]: return None
        
        # Tomamos el primero
        producto = res["items"][0]
        
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
