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
            
            # RETRY INTELIGENTE:
            # Si no tenemos productos (por error o arranque), reintentamos rápido (30s)
            # Si ya tenemos productos (éxito), esperamos 10 min
            if self.total_items == 0:
                logging.info("⚠️ DB: Inventario vacío. Reintentando sincronización en 30 segundos...")
                time.sleep(30)
            else:
                time.sleep(300) # 5 minutos 

    def _actualizar_tabla_maestra(self):
        clean_url = self.shopify_url.replace("https://", "").replace("/", "")
        # API versionada (actualizada a una reciente estable)
        url = f"https://{clean_url}/admin/api/2024-10/products.json"
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
                # No romper el bucle, solo reintentar en 10 min
                break
        
        if nueva_tabla:
            self.productos = nueva_tabla
            self.total_items = len(nueva_tabla)
            self.last_sync = datetime.now()
            self.sync_status = "OK"
            self.sync_error = None
            logging.info(f"✅ DB: Inventario actualizado. {self.total_items} productos listos. [INSTANCIA ID: {id(self)}]")
            
            # --- MUESTRA ALEATORIA DE CONTROL ---
            try:
                import random
                p_sample = random.choice(self.productos)
                logging.info(f"🎲 CONTROL DE CALIDAD: Muestra aleatoria -> '{p_sample['title']}' (${p_sample['price']:,.0f}) [ID: {p_sample['id']}]")
            except Exception:
                pass
            # ------------------------------------
        else:
            # Si nueva_tabla está vacía pero NO hubo error (e.g. filtro de status), puede ser correcto.
            # Pero si hubo error de conexión, no borramos lo antiguo.
            if self.sync_error:
                 logging.warning("⚠️ DB: Hubo error en sincronización. Manteniendo caché anterior.")
            else:
                # Si realmente no descargó nada y no hubo error, borramos o mantenemos? 
                # Mejor mantener por seguridad si ya había algo
                if self.productos:
                     logging.warning("⚠️ DB: Shopify devolvió 0 productos. ¿Error de credenciales o tienda vacía? Manteniendo caché por seguridad.")
                else:
                    self.sync_status = "Alerta: Inventario Vacio (Credenciales OK, pero 0 items)"
                    logging.warning("⚠️ DB: Tienda vacía o filtro incorrecto.")

    def _normalizar(self, texto):
        if not texto: return ""
        try:
            # Normalización unicode, eliminación de tildes y minúsculas
            text_str = str(texto)
            # Reemplazar puntuación por espacios para evitar "shampoos?" -> "shampoos?"
            text_str = text_str.replace("?", " ").replace("!", " ").replace(".", " ").replace(",", " ")
            return unicodedata.normalize('NFKD', text_str).encode('ASCII', 'ignore').decode('utf-8').lower().strip()
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

    def generar_checkout(self, texto_usuario, productos_contexto=None):
        """
        LEGACY: Genera checkout intentando adivinar. 
        Mantenido por compatibilidad, pero idealmente usar generar_checkout_especifico.
        """
        if not self.shopify_token or not self.shopify_url:
            return None

        items_a_comprar = []

        # CASO 1: Vienen productos del contexto (Memoria)
        if productos_contexto:
            items_a_comprar = productos_contexto
        else:
            # CASO 2: Buscamos en el texto del usuario
            res = self.buscar_contextual(texto_usuario)
            if res["items"]:
                # Asumimos que quiere el primer resultado si busca por texto
                items_a_comprar = [res["items"][0]]

        if not items_a_comprar:
            return None
            
        return self._crear_draft_order(items_a_comprar)

    def generar_checkout_especifico(self, ids_seleccionados, contexto_total):
        """
        Genera checkout SOLAMENTE con los IDs especificados.
        """
        if not ids_seleccionados: return None
        
        # Filtrar del contexto los que coincidan con los IDs
        items_finales = []
        for p in contexto_total:
            # Convertimos a string por si acaso vienen tipos mixtos
            if str(p['id']) in [str(x) for x in ids_seleccionados]:
                items_finales.append(p)
                
        if not items_finales:
            return None
            
        return self._crear_draft_order(items_finales)

    def _crear_draft_order(self, items):
        """Función interna reutilizable para crear la orden en Shopify"""
        clean_url = self.shopify_url.replace("https://", "").replace("/", "")
        headers = {
            "X-Shopify-Access-Token": self.shopify_token, 
            "Content-Type": "application/json"
        }
        
        # Construir line_items
        line_items = []
        nombres_productos = []
        total_aprox = 0
        
        for p in items:
            line_items.append({
                "variant_id": p['variant_id'], 
                "quantity": 1
            })
            nombres_productos.append(p['title'])
            total_aprox += p['price']
            
        # Crear la orden borrador (Draft Order)
        try:
            payload = {
                "draft_order": {
                    "line_items": line_items,
                    "note": "Pedido generado vía GlamBot (WhatsApp AI) 🤖",
                    "tags": "whatsapp-bot"
                }
            }
            
            url = f"https://{clean_url}/admin/api/2024-10/draft_orders.json"
            r = requests.post(url, headers=headers, json=payload, timeout=10)
            
            if r.status_code == 201: 
                data = r.json().get("draft_order", {})
                return {
                    "url": data.get("invoice_url"), # URL de pago directo
                    "nombre": ", ".join(nombres_productos),
                    "total": total_aprox,
                    "items": items # Retornamos los items para hacer el resumen
                }
            else:
                logging.error(f"Error creando orden Shopify: {r.text}")
                
        except Exception as e:
            logging.error(f"Excepción generando checkout: {e}")
            
        return None

db = GlamStoreDB()
