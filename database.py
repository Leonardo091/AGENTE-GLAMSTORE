import threading
import time
import requests
import unicodedata
import os
import logging
import random
from datetime import datetime

# Configuración de logs compartida
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class GlamStoreDB:
    def __init__(self):
        self.productos = [] 
        self.total_items = 0
        self.identidad = "Cargando..."
        self.last_sync = None
        self.sync_status = "Iniciada"
        self.sync_error = None
        self.shopify_token = os.environ.get("SHOPIFY_TOKEN")
        self.shopify_url = os.environ.get("SHOPIFY_URL")
        
        # Palabras que NO sirven para buscar producto específico (stopwords)
        self.palabras_basura = {
            "hola", "buenos", "dias", "tardes", "busco", "venden", "tienen", 
            "quiero", "necesito", "comprar", "precio", "valor", "cuanto", 
            "vale", "cuesta", "ejemplo", "muestrame", "algun", "alguno", 
            "articulo", "producto", "dato", "puedes", "dar", "me", "das",
            "recomendar", "recomendarias", "para", "mi", "hija", "mama", "regalo",
            "glamstore", "tienda", "gracias", "favor", "por"
        }
        
        # Iniciar sincronización en segundo plano solo si hay credenciales
        if self.shopify_token and self.shopify_url:
            hilo = threading.Thread(target=self._sincronizar_loop)
            hilo.daemon = True
            hilo.start()
        else:
            self.sync_status = "Error: Faltan Credenciales"
            logging.warning("⚠️ MODO SIN CONEXIÓN: Faltan credenciales de Shopify (SHOPIFY_TOKEN / SHOPIFY_URL)")

    def get_status(self):
        """Retorna el estado actual de la base de datos para debug."""
        return {
            "total_productos": self.total_items,
            "ultima_sincronizacion": str(self.last_sync) if self.last_sync else "Nunca",
            "estado_sincronizacion": self.sync_status,
            "error_reciente": self.sync_error,
            "url_configurada": bool(self.shopify_url),
            "token_configurado": bool(self.shopify_token)
        }

    def _sincronizar_loop(self):
        """Mantiene el inventario actualizado cada 10 minutos."""
        while True:
            try:
                self._actualizar_tabla_maestra()
            except Exception as e:
                logging.error(f"Error crítico en loop de sincronización: {e}")
            time.sleep(600) 

    def _actualizar_tabla_maestra(self):
        clean_url = self.shopify_url.replace("https://", "").replace("/", "")
        # API versionada (actualizada a una reciente estable)
        url = f"https://{clean_url}/admin/api/2024-01/products.json"
        headers = {
            "X-Shopify-Access-Token": self.shopify_token, 
            "Content-Type": "application/json"
        }
        params = {"status": "active", "limit": 250}
        
        nueva_tabla = []
        logging.info("🔄 DB: Iniciando sincronización de inventario con Shopify...")
        
        pagina = 1
        while url:
            try:
                # Respetar rate limits de Shopify
                time.sleep(0.5)
                
                logging.info(f"   - Descargando página {pagina}...")
                r = requests.get(url, headers=headers, params=params, timeout=20)
                
                if r.status_code != 200:
                    logging.error(f"❌ Error Shopify {r.status_code}: {r.text}")
                    break
                
                data = r.json().get("products", [])
                for p in data:
                    try:
                        # Solo procesamos si tiene variantes
                        if not p.get("variants"): continue

                        # Precio de la primera variante (precio base)
                        precio = float(p["variants"][0]["price"])
                        
                        # Construir texto de búsqueda enriquecido
                        parts = [
                            p.get('title', ''),
                            p.get('vendor', ''),
                            p.get('product_type', ''),
                            p.get('tags', '')
                        ]
                        # Unir y limpiar
                        texto_sucio = " ".join([str(x) for x in parts if x])
                        texto_limpio = self._normalizar(texto_sucio)
                        
                        nueva_tabla.append({
                            "id": p["id"],
                            "title": p["title"],
                            "price": precio,
                            "search_text": texto_limpio,
                            "variant_id": p["variants"][0]["id"]
                        })
                    except Exception as e:
                        logging.warning(f"Error procesando producto {p.get('id')}: {e}")

                # Paginación (Link header)
                if 'next' in r.links:
                    url = r.links['next']['url']
                    params = {} # Los params ya vienen en la URL de 'next'
                    pagina += 1
                else:
                    url = None
                    
            except Exception as e:
                self.sync_status = "Error en conexión"
                self.sync_error = str(e)
                logging.error(f"Error de conexión con Shopify: {e}")
                break
        
        if nueva_tabla:
            self.productos = nueva_tabla
            self.total_items = len(nueva_tabla)
            self.last_sync = datetime.now()
            self.sync_status = "OK"
            self.sync_error = None
            logging.info(f"✅ DB: Inventario actualizado. {self.total_items} productos listos.")
        else:
            if not self.productos:
                self.sync_status = "Alerta: Inventario Vacio"
            logging.warning("⚠️ DB: No se descargaron productos (o la lista estaba vacía). Manteniendo caché anterior.")

    def _normalizar(self, texto):
        if not texto: return ""
        try:
            # Normalización unicode, eliminación de tildes y minúsculas
            text_str = str(texto)
            return unicodedata.normalize('NFKD', text_str).encode('ASCII', 'ignore').decode('utf-8').lower()
        except:
            return str(texto).lower()

    # --- FUNCIONES DE BÚSQUEDA ELITE ---

    def buscar_contextual(self, texto_usuario):
        """
        Busca productos basados en categorías o palabras clave del usuario.
        Retorna una estructura estandarizada.
        """
        if not self.productos:
            return {"tipo": "VACIO", "items": []}

        texto_limpio = self._normalizar(texto_usuario)
        palabras = texto_limpio.split()
        
        # 1. Definición de Categorías Clave (Expandible)
        categorias_map = {
            "perfume": ["perfume", "aroma", "fragancia", "eau de", "toilette"],
            "labial": ["labial", "balsamo", "lip", "gloss", "boca"],
            "ojos": ["rimel", "mascara", "pestaña", "delineador", "sombra"],
            "rostro": ["crema", "facial", "base", "polvo", "rubor", "serum", "maquillaje"],
            "cabello": ["shampoo", "acondicionador", "mascara", "capilar", "pelo", "tratamiento", "aceite", "argan"],
            "accesorios": ["llavero", "monedero", "cosmetiquero", "cintillo", "accesorio", "bolso"]
        }
        
        categoria_detectada = None
        
        # Detectar si el usuario menciona alguna categoría conocida
        for cat_key, sinonimos in categorias_map.items():
            if any(s in texto_limpio for s in sinonimos):
                categoria_detectada = cat_key
                break
        
        resultados = []
        
        # ESTRATEGIA A: Filtrado por Categoría
        if categoria_detectada:
            # Buscar productos que contengan palabras de esa categoría o sus sinónimos
            sinonimos_cat = categorias_map[categoria_detectada]
            candidatos = []
            for p in self.productos:
                # Chequeamos si el producto encaja en la categoría detectada
                if any(s in p['search_text'] for s in sinonimos_cat):
                    candidatos.append(p)
            
            if candidatos:
                # Retornar una selección aleatoria para variedad (marketing)
                resultados = random.sample(candidatos, min(5, len(candidatos)))
                return {"tipo": "RECOMENDACION_REAL", "items": resultados}

        # ESTRATEGIA B: Búsqueda por Palabras Clave (Búsqueda "Sucia")
        # Filtramos palabras comunes (stopwords) y generamos variantes
        keywords = []
        for p in palabras:
            if p in self.palabras_basura or len(p) <= 2:
                continue
            keywords.append(p)
            # Intento básico de singularización para español/inglés
            if p.endswith('s') and len(p) > 3:
                keywords.append(p[:-1]) # "perfumes" -> "perfume"
            if p.endswith('es') and len(p) > 4:
                keywords.append(p[:-2]) # "balsamos" -> "balsamo" (aunque normalizar quita tildes, esto ayuda)
        
        # Eliminar duplicados
        keywords = list(set(keywords))
        
        if keywords:
            scored_results = []
            for p in self.productos:
                matches = 0
                for kw in keywords:
                    if kw in p['search_text']:
                        matches += 1
                
                # Sistema de puntaje simple: Más palabras coincidentes = mejor
                if matches > 0:
                    scored_results.append((matches, p))
            
            # Ordenar por relevancia (mayor matches primero)
            scored_results.sort(key=lambda x: x[0], reverse=True)
            
            if scored_results:
                # Tomar los top 5
                resultados = [x[1] for x in scored_results[:5]]
                return {"tipo": "EXACTO", "items": resultados}
        
        return {"tipo": "VACIO", "items": []}

    def generar_checkout(self, texto_usuario):
        """Genera un Draft Order en Shopify y retorna el link de pago."""
        if not self.shopify_token or not self.shopify_url:
            return None

        # Reutilizamos la búsqueda para encontrar QUÉ quiere comprar
        res = self.buscar_contextual(texto_usuario)
        if not res["items"]: 
            return None
        
        # Asumimos que quiere el primer resultado (el más relevante)
        producto = res["items"][0] 
        
        clean_url = self.shopify_url.replace("https://", "").replace("/", "")
        headers = {
            "X-Shopify-Access-Token": self.shopify_token, 
            "Content-Type": "application/json"
        }
        
        # Crear la orden borrador (Draft Order)
        try:
            payload = {
                "draft_order": {
                    "line_items": [
                        {
                            "variant_id": producto['variant_id'], 
                            "quantity": 1
                        }
                    ],
                    "note": "Pedido generado vía GlamBot (WhatsApp AI) 🤖",
                    "tags": "whatsapp-bot"
                }
            }
            
            url = f"https://{clean_url}/admin/api/2024-01/draft_orders.json"
            r = requests.post(url, headers=headers, json=payload, timeout=10)
            
            if r.status_code == 201: 
                data = r.json().get("draft_order", {})
                return {
                    "url": data.get("invoice_url"), # URL de pago directo
                    "nombre": producto['title']
                }
            else:
                logging.error(f"Error creando orden Shopify: {r.text}")
                
        except Exception as e:
            logging.error(f"Excepción generando checkout: {e}")
            
        return None

db = GlamStoreDB()
