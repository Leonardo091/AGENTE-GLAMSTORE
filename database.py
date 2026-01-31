import threading
import time
import requests
import unicodedata
import os
import logging
import sqlite3
import json
import csv
from datetime import datetime
from io import StringIO

# Configuración de logs compartida
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class GlamStoreDB:
    def __init__(self, db_path="glamstore.db"):
        self.db_path = db_path
        self.productos = [] 
        self.identidad = "Cargando..."
        self.last_sync = None
        self.sync_status = "Iniciada"
        self.sync_error = None
        self.shopify_token = os.environ.get("SHOPIFY_TOKEN")
        self.shopify_url = os.environ.get("SHOPIFY_URL")
        
        # Palabras excluidas en búsquedas
        self.palabras_basura = {
            "hola", "buenos", "dias", "tardes", "busco", "venden", "tienen", 
            "quiero", "necesito", "comprar", "precio", "valor", "cuanto", 
            "vale", "cuesta", "ejemplo", "muestrame", "algun", "alguno", 
            "articulo", "producto", "dato", "puedes", "dar", "me", "das",
            "recomendar", "recomendarias", "para", "mi", "hija", "mama", "regalo",
            "glamstore", "tienda", "gracias", "favor", "por",
            "el", "la", "los", "las", "un", "una", "de", "del", "que", "en", "y", "o"
        }

        # 1. INICIALIZAR SQLITE
        self._init_db()
        
        # 2. CARGA RÁPIDA (BOOT)
        self._cargar_memoria_desde_sql()

        # 3. INICIAR SYNC LOOP
        if self.shopify_token and self.shopify_url:
            hilo = threading.Thread(target=self._sincronizar_loop)
            hilo.daemon = True
            hilo.start()
        else:
            self.sync_status = "Error: Faltan Credenciales"
            logging.warning("⚠️ MODO SIN CONEXIÓN: Faltan credenciales de Shopify")

    @property
    def total_items(self):
        return len(self.productos)

    def _get_conn(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self):
        """Crea la tabla si no existe."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS productos (
                id INTEGER PRIMARY KEY,
                title TEXT,
                price REAL,
                stock INTEGER,
                vendor TEXT,
                category TEXT,
                tags TEXT,
                body_html TEXT,
                handle TEXT,
                images_json TEXT,
                search_text TEXT,
                variant_id INTEGER,
                updated_at TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()

    def _cargar_memoria_desde_sql(self):
        """Lee la DB local y llena self.productos para acceso rápido."""
        try:
            conn = self._get_conn()
            conn.row_factory = sqlite3.Row # Para acceder por nombre de columna
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM productos")
            rows = cursor.fetchall()
            
            nueva_lista = []
            for row in rows:
                p = dict(row)
                # Parsear JSON de imágenes si existe
                try:
                    p['images'] = json.loads(p['images_json']) if p['images_json'] else []
                except:
                    p['images'] = []
                # Compatibilidad hacia atrás: image_url principal
                p['image_url'] = p['images'][0] if p['images'] else ""
                
                nueva_lista.append(p)
            
            self.productos = nueva_lista
            self.last_sync = datetime.now() 
            logging.info(f"⚡ BOOT: {len(self.productos)} productos cargados desde SQL.")
            conn.close()
        except Exception as e:
            logging.error(f"Error cargando desde SQL: {e}")

    def get_status(self):
        return {
            "total_productos": len(self.productos),
            "ultima_sincronizacion": str(self.last_sync) if self.last_sync else "Nunca",
            "estado_sincronizacion": self.sync_status
        }

    # --- SINCRONIZACIÓN ---

    def trigger_sync_if_stale(self, minutes=30):
        """Si la última sync fue hace más de X minutos, inicia sync en background."""
        if not self.last_sync:
            self.force_sync()
            return
            
        delta = datetime.now() - self.last_sync
        if delta.total_seconds() > (minutes * 60):
            logging.info(f"⏰ Trigger Sync: Datos antiguos ({delta}), iniciando actualización...")
            threading.Thread(target=self._actualizar_tabla_maestra).start()

    def force_sync(self):
        """Forzar actualización inmediata en hilo aparte."""
        threading.Thread(target=self._actualizar_tabla_maestra).start()

    def _sincronizar_loop(self):
        """Loop principal de mantenimiento (cada 30 min)."""
        while True:
            try:
                self._actualizar_tabla_maestra()
            except Exception as e:
                logging.error(f"Error en loop sync: {e}")
            
            time.sleep(1800) # 30 minutos

    def _actualizar_tabla_maestra(self):
        self.sync_status = "Sincronizando..."
        clean_url = self.shopify_url.replace("https://", "").replace("/", "")
        url = f"https://{clean_url}/admin/api/2024-10/products.json"
        headers = {"X-Shopify-Access-Token": self.shopify_token, "Content-Type": "application/json"}
        params = {"status": "active", "limit": 250}
        
        nuevos_datos = []
        logging.info("🔄 SQL Sync: Conectando a Shopify...")

        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            pagina = 1
            while url:
                r = requests.get(url, headers=headers, params=params, timeout=20)
                if r.status_code != 200:
                    logging.error(f"❌ Shopify Error: {r.status_code}")
                    break
                
                items = r.json().get("products", [])
                for p in items:
                    if not p.get("variants"): continue
                    
                    # Datos principales
                    v1 = p["variants"][0]
                    # Filtro de stock: Si shopify maneja stock, es 'deny' y qty <= 0 -> Ignorar
                    if v1.get("inventory_management") == "shopify" and v1.get("inventory_policy") == "deny" and v1.get("inventory_quantity", 0) <= 0:
                        continue

                    # Extraer data rica
                    p_id = p["id"]
                    title = p["title"]
                    price = float(v1["price"])
                    stock = v1.get("inventory_quantity", 0)
                    vendor = p.get("vendor", "")
                    category = p.get("product_type", "")
                    tags = p.get("tags", "")
                    body = p.get("body_html", "") or ""
                    handle = p.get("handle", "")
                    
                    # Imágenes
                    imgs = [i["src"] for i in p.get("images", [])]
                    imgs_json = json.dumps(imgs)

                    # Texto búsqueda
                    texto_sucio = f"{title} {vendor} {category} {tags}"
                    texto_limpio = self._normalizar(texto_sucio)

                    # UPSERT en SQL
                    cursor.execute('''
                        INSERT OR REPLACE INTO productos 
                        (id, title, price, stock, vendor, category, tags, body_html, handle, images_json, search_text, variant_id, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        p_id, title, price, stock, vendor, category, tags, body, handle, imgs_json, 
                        texto_limpio, v1["id"], datetime.now()
                    ))
                
                conn.commit()
                
                 # Paginación
                if 'next' in r.links:
                    url = r.links['next']['url']
                    params = {}
                    pagina += 1
                else:
                    url = None
            
            # Al finalizar, recargar memoria
            conn.close()
            self._cargar_memoria_desde_sql()
            self.sync_status = "OK"
            self.sync_error = None
            logging.info("✅ SQL Sync: Completada exitosamente.")

        except Exception as e:
            self.sync_status = "Error"
            self.sync_error = str(e)
            logging.error(f"Error Sync Shopify->SQL: {e}")
            if conn: conn.close()

    def _normalizar(self, texto):
        if not texto: return ""
        try:
            text_str = str(texto).replace("?", " ").replace(",", " ")
            return unicodedata.normalize('NFKD', text_str).encode('ASCII', 'ignore').decode('utf-8').lower().strip()
        except:
            return str(texto).lower()

    # --- BÚSQUEDA ---
    # Se mantiene la lógica en memoria por velocidad, pero ahora usa la data rica de SQL
    def buscar_contextual(self, texto_usuario):
        if not self.productos: return {"tipo": "VACIO", "items": []}
        
        texto_limpio = self._normalizar(texto_usuario)
        palabras = texto_limpio.split()
        
        # Categorías hardcodeadas para match rápido
        categorias_map = {
            "perfume": ["perfume", "aroma", "fragancia", "eau de"],
            "labial": ["labial", "balsamo", "lip", "gloss"],
            "ojos": ["rimel", "mascara", "delineador", "sombra"],
            "rostro": ["crema", "facial", "base", "polvo", "serum"],
            "cabello": ["shampoo", "acondicionador", "mascara", "pelo"]
        }
        
        # Estrategia 1: Categoría
        for cat, sins in categorias_map.items():
            if any(s in texto_limpio for s in sins):
                # Filtrar en memoria por tag o categoria o texto
                candidatos = [p for p in self.productos if cat in self._normalizar(p['category']) or cat in self._normalizar(p['tags'])]
                # Si no hay match directo, buscar en search_text
                if not candidatos:
                    candidatos = [p for p in self.productos if any(s in p['search_text'] for s in sins)]
                
                if candidatos:
                    import random
                    return {"tipo": "RECOMENDACION_REAL", "items": random.sample(candidatos, min(5, len(candidatos)))}

        # Estrategia 2: Keywords
        keywords = [w for w in palabras if w not in self.palabras_basura and len(w) > 2]
        if keywords:
            resultados = []
            for p in self.productos:
                score = 0
                for kw in keywords:
                    if kw in p['search_text']: score += 1
                if score > 0: resultados.append((score, p))
            
            resultados.sort(key=lambda x: x[0], reverse=True)
            if resultados:
                return {"tipo": "EXACTO", "items": [r[1] for r in resultados[:5]]}
        
        return {"tipo": "VACIO", "items": []}

    # --- EXPORTACIÓN ---
    def exportar_csv_str(self):
        """Genera un String CSV con toda la base de datos."""
        output = StringIO()
        writer = csv.writer(output)
        
        # Headers
        writer.writerow(["ID", "Título", "Precio", "Stock", "Vendor", "Tags", "Handle", "Última Actualización"])
        
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM productos")
        
        for row in cursor.fetchall():
            # row es una tupla, mapeamos indices según CREATE TABLE
            # id(0), title(1), price(2), stock(3), vendor(4), category(5), tags(6), body(7), handle(8), images(9)...
            writer.writerow([
                row[0], row[1], row[2], row[3], row[4], row[6], row[8], row[12]
            ])
            
        conn.close()
        return output.getvalue()

    # --- CHECKOUT (Mantenido igual) ---
    def generar_checkout_especifico(self, ids, contexto_total):
        # ... (misma lógica de antes, solo que ahora contexto_total viene de self.productos que ya es rico)
        # Reutilizamos la lógica existente de draft orders api
        if not ids: return None
        items = []
        mapa = {int(p['id']): p for p in self.productos} # Mapa rápido ID->Prod
        
        for i in ids:
            if int(i) in mapa:
                items.append(mapa[int(i)])
        
        return self._crear_draft_order(items) if items else None

    def _crear_draft_order(self, items):
        # ... (Copia exacta de tu función anterior para no romper nada)
        # Solo agregaremos el trigger force_sync al final en caso de éxito
        clean_url = self.shopify_url.replace("https://", "").replace("/", "")
        headers = {"X-Shopify-Access-Token": self.shopify_token, "Content-Type": "application/json"}
        
        line_items = [{"variant_id": p['variant_id'], "quantity": 1} for p in items]
        total = sum(p['price'] for p in items)
        
        try:
            payload = {
                "draft_order": {
                    "line_items": line_items,
                    "note": "Bot Venta",
                    "tags": "whatsapp-bot"
                }
            }
            url = f"https://{clean_url}/admin/api/2024-10/draft_orders.json"
            r = requests.post(url, headers=headers, json=payload, timeout=10)
            
            if r.status_code == 201:
                # ÉXITO -> Trigger Sync para descontar stock
                self.force_sync()
                
                data = r.json().get("draft_order", {})
                return {
                    "url": data.get("invoice_url"),
                    "items": items,
                    "total": total
                }
        except Exception as e:
            logging.error(f"Error draft: {e}")
        return None

db = GlamStoreDB()
