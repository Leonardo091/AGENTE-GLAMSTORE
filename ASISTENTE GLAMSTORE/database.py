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
from typing import List, Dict, Any, Optional, Tuple, Set, Union

# Configuración de logs compartida
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class GlamStoreDB:
    """
    Gestor de persistencia y sincronización de productos.
    Maneja la caché local (SQLite) y la integración con Shopify.
    """
    def __init__(self, db_path: str = "glamstore.db") -> None:
        self.db_path: str = db_path
        self.productos: List[Dict[str, Any]] = [] 

        self.identidad = "Cargando..."
        self.last_sync = None
        self.sync_status = "Iniciada"
        self.sync_error = None
        self.shopify_token = os.environ.get("SHOPIFY_TOKEN")
        self.shopify_url = os.environ.get("SHOPIFY_URL")
        
        # Palabras excluidas en búsquedas
        self.palabras_basura: Set[str] = {
            "hola", "buenos", "dias", "tardes", "busco", "venden", "tienen", 
            "quiero", "necesito", "comprar", "precio", "valor", "cuanto", 
            "vale", "cuesta", "ejemplo", "muestrame", "algun", "alguno", 
            "articulo", "producto", "dato", "puedes", "dar", "me", "das",
            "recomendar", "recomendarias", "para", "mi", "hija", "mama", "regalo",
            "glamstore", "tienda", "gracias", "favor", "por",
            "el", "la", "los", "las", "un", "una", "de", "del", "que", "en", "y", "o"
        }

        # CONFIGURACIÓN MODO VACACIONES (Hardcoded por seguridad)
        self.modo_vacaciones = True


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
    def total_items(self) -> int:
        # Auto-heal: Si un worker tiene memoria vacía pero la DB tiene datos
        if not self.productos:
            self._cargar_memoria_desde_sql()
        return len(self.productos)

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self) -> None:

        """Crea la tabla si no existe."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS productos (
                id INTEGER PRIMARY KEY,
                title TEXT,
                price REAL,
                compare_at_price REAL,
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
        
        # Migración simple: Check if column exists
        try:
            cursor.execute("SELECT compare_at_price FROM productos LIMIT 1")
        except sqlite3.OperationalError:
            logging.info("🔧 Migración: Agregando columna 'compare_at_price'...")
            cursor.execute("ALTER TABLE productos ADD COLUMN compare_at_price REAL")

        conn.commit()
        conn.close()

    def _cargar_memoria_desde_sql(self) -> None:
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

    def get_status(self) -> Dict[str, Any]:
        return {

            "total_productos": len(self.productos),
            "ultima_sincronizacion": str(self.last_sync) if self.last_sync else "Nunca",
            "estado_sincronizacion": self.sync_status
        }

    # --- SINCRONIZACIÓN ---

    def trigger_sync_if_stale(self, minutes: int = 30) -> None:
        """Si la última sync fue hace más de X minutos, inicia sync en background."""

        if not self.last_sync:
            self.force_sync()
            return
            
        delta = datetime.now() - self.last_sync
        if delta.total_seconds() > (minutes * 60):
            logging.info(f"⏰ Trigger Sync: Datos antiguos ({delta}), iniciando actualización...")
            threading.Thread(target=self._actualizar_tabla_maestra).start()

    def force_sync(self) -> None:
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
        graphql_url = f"https://{clean_url}/admin/api/2024-10/graphql.json"
        headers = {"X-Shopify-Access-Token": self.shopify_token, "Content-Type": "application/json"}
        
        logging.info("🔄 SQL Sync: Conectando a Shopify (GraphQL)...")
        
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            todos_valid_ids = []
            has_next_page = True
            end_cursor = None
            
            # --- MODO VACACIONES / REVISTA ---
            if getattr(self, "modo_vacaciones", False):
                 # MODO REVISTA: Sin filtros (Igual que la ruta debug que sí funcionó)
                 filtro_param = "" 
                 logging.warning("🌴 MODO VACACIONES: Sync GLOBAL (Sin filtros).")
            else:
                 # MODO NORMAL: Solo lo vendible
                 filtro_param = ', query: "status:active inventory_total:>0"'

            while has_next_page:
                # Construir Query con paginación
                cursor_param = f'"{end_cursor}"' if end_cursor else "null"
                # OJO: La coma ya va incluida en filtro_param si no está vacío
                query = f"""
                {{
                  products(first: 50, after: {cursor_param}{filtro_param}) {{
                    pageInfo {{ hasNextPage endCursor }}
                    edges {{
                      node {{
                        id
                        title
                        descriptionHtml
                        vendor
                        productType
                        handle
                        tags
                        publishedAt
                        category {{ name }}
                        collections(first: 10) {{ edges {{ node {{ title }} }} }}
                        variants(first: 1) {{
                          edges {{
                            node {{
                              id
                              price
                              compareAtPrice
                              inventoryQuantity
                              inventoryPolicy
                            }}
                          }}
                        }}
                        images(first: 5) {{ edges {{ node {{ url }} }} }}
                      }}
                    }}
                  }}
                }}
                """
                
                r = requests.post(graphql_url, headers=headers, json={"query": query}, timeout=30)
                
                if r.status_code != 200:
                    logging.error(f"❌ Shopify GraphQL Error: {r.status_code} {r.text}")
                    break
                
                data = r.json()
                if "errors" in data:
                    logging.error(f"❌ GraphQL Query Errors: {data['errors']}")
                    break
                    
                products_data = data.get("data", {}).get("products", {})
                edges = products_data.get("edges", [])
                
                for edge in edges:
                    node = edge["node"]
                    
                    # Validación básica de variantes
                    variants_edges = node.get("variants", {}).get("edges", [])
                    if not variants_edges: continue
                    v1_node = variants_edges[0]["node"]
                    
                    # 1. Filtro Stock (Solo si NO estamos en vacaciones)
                    qty = v1_node.get("inventoryQuantity", 0)
                    policy = v1_node.get("inventoryPolicy", "deny")
                    
                    if not getattr(self, "modo_vacaciones", False):
                        # Si la política es 'deny' (no vender sin stock) y cantidad <= 0, saltar
                        if policy == "deny" and qty <= 0:
                            continue

                    # ID: "gid://shopify/Product/123456" -> 123456
                    try:
                        p_id = int(node["id"].split("/")[-1])
                    except:
                        continue
                        
                    todos_valid_ids.append(p_id)

                    # Extraer data rica
                    title = node.get("title", "")
                    price = float(v1_node.get("price", 0))
                    
                    # CompareAtPrice (Precio Oferta)
                    compare_at = v1_node.get("compareAtPrice")
                    compare_at_price = float(compare_at) if compare_at else 0.0
                    
                    stock = qty
                    vendor = node.get("vendor", "")
                    
                    # CATEGORÍA: Prioridad Taxonomy > Product Type
                    cat_tax = node.get("category", {})
                    category = cat_tax.get("name") if cat_tax else node.get("productType", "")
                    
                    # TAGS: Mezclar tags + colecciones
                    raw_tags = node.get("tags", []) # Lista en GraphQL
                    
                    # Incluir colecciones como tags (hack útil)
                    col_edges = node.get("collections", {}).get("edges", [])
                    col_titles = [c["node"]["title"] for c in col_edges]
                    
                    # Excluir etiqueta prohibida
                    all_tags_set = set(raw_tags + col_titles)
                    tags_filtrados = [
                        t.strip() for t in all_tags_set 
                        if t.strip() != "Smart Products Filter Index - Do not delete"
                    ]
                    tags_str = ", ".join(tags_filtrados)
                    
                    body = node.get("descriptionHtml", "") or ""
                    handle = node.get("handle", "")
                    
                    # Imágenes
                    img_edges = node.get("images", {}).get("edges", [])
                    imgs = [i["node"]["url"] for i in img_edges]
                    imgs_json = json.dumps(imgs)

                    # Texto búsqueda
                    texto_sucio = f"{title} {vendor} {category} {tags_str}"
                    texto_limpio = self._normalizar(texto_sucio)
                    
                    # Variant ID
                    v_id_raw = v1_node["id"]
                    v_id = int(v_id_raw.split("/")[-1]) if "gid://" in v_id_raw else v_id_raw

                    # UPSERT en SQL
                    cursor.execute('''
                        INSERT OR REPLACE INTO productos 
                        (id, title, price, compare_at_price, stock, vendor, category, tags, body_html, handle, images_json, search_text, variant_id, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        p_id, title, price, compare_at_price, stock, vendor, category, tags_str, body, handle, imgs_json, 
                        texto_limpio, v_id, datetime.now()
                    ))
                
                conn.commit()
                
                # Paginación
                page_info = products_data.get("pageInfo", {})
                has_next_page = page_info.get("hasNextPage", False)
                end_cursor = page_info.get("endCursor")

            
            # --- LIMPIEZA DE PRODUCTOS ANTIGUOS ---
            if todos_valid_ids:
                placeholders = ','.join(['?'] * len(todos_valid_ids))
                sql_cleanup = f"DELETE FROM productos WHERE id NOT IN ({placeholders})"
                cursor.execute(sql_cleanup, todos_valid_ids)
                deleted_count = cursor.rowcount
                conn.commit()
                logging.info(f"🧹 Limpieza SQL: {deleted_count} productos eliminados.")
            else:
                logging.warning("⚠️ Sync devolvió 0 productos válidos. No se borró nada por seguridad.")

            
            # Al finalizar, recargar memoria
            conn.close()
            self._cargar_memoria_desde_sql()
            self.sync_status = "OK"
            self.sync_error = None
            logging.info(f"✅ SQL GraphQL Sync: Completada. Total activos: {len(todos_valid_ids)}")

        except Exception as e:
            self.sync_status = "Error"
            self.sync_error = str(e)
            logging.error(f"Error Sync GraphQL->SQL: {e}")
            if conn: conn.close()

    def _normalizar(self, texto: Optional[str]) -> str:
        if not texto: return ""

        try:
            text_str = str(texto).replace("?", " ").replace(",", " ")
            return unicodedata.normalize('NFKD', text_str).encode('ASCII', 'ignore').decode('utf-8').lower().strip()
        except:
            return str(texto).lower()

    # --- BÚSQUEDA ---
    # Se mantiene la lógica en memoria por velocidad, pero ahora usa la data rica de SQL
    def buscar_contextual(self, texto_usuario: str) -> Dict[str, Any]:
        if not self.productos: return {"tipo": "VACIO", "items": []}

        
        texto_limpio = self._normalizar(texto_usuario)
        palabras = texto_limpio.split()
        
        # Categorías hardcodeadas para match rápido
        # Mapeo de Intención -> Categoría REAL en Shopify
        # Esto asegura que si piden 'rimel', busquemos prioridad en 'Maquillaje'
        categorias_map = {
            "Maquillaje": ["maquillaje", "labial", "sombra", "rimel", "mascara", "delineador", "base", "polvo", "rubor", "corrector", "primer", "fijador"],
            "Skin Care": ["skin care", "skincare", "piel", "crema", "facial", "serum", "rostro", "mascarilla", "hidratante", "limpieza", "tonico"],
            "Productos Capilares": ["capilar", "cabello", "pelo", "shampoo", "acondicionador", "mascara", "tratamiento", "oleo", "peine", "cepillo"],
            "Perfumes": ["perfume", "fragancia", "colonia", "aroma", "body splash", "spray", "locion", "floral", "dulce", "citrico", "frutal", "amaderado", "oriental"],
            "Accesorios": ["accesorio", "bolso", "cosmetiquero", "espejo", "brocha", "esponja", "pinza", "elastico", "colet"]
        }
        
        import re
        # Extraer posibles precios del texto original (no normalizado para conservar numeros si _normalizar los borra, aunque _normalizar mantiene letras y numeros)
        # Buscamos números enteros entre 1000 y 1000000 (precios típicos CL)
        precios_encontrados = [int(n) for n in re.findall(r'\b\d{3,7}\b', texto_usuario) if 1000 <= int(n) <= 1000000]
        precio_objetivo = precios_encontrados[0] if precios_encontrados else None
        
        # Estrategia 1: Categoría
        for cat, sins in categorias_map.items():
            if any(s in texto_limpio for s in sins):
                # Filtrar en memoria por tag o categoria o texto
                candidatos = [p for p in self.productos if cat in self._normalizar(p['category']) or cat in self._normalizar(p['tags'])]
                # Si no hay match directo, buscar en search_text
                if not candidatos:
                    candidatos = [p for p in self.productos if any(s in p['search_text'] for s in sins)]
                
                # --- FILTRO DE PRECIO (NUEVO) ---
                if precio_objetivo and candidatos:
                    # Filtramos productos con precio exacto (+- delta pequeño opcional, por ahora exacto)
                    candidatos_precio = [p for p in candidatos if int(p['price']) == precio_objetivo]
                    if candidatos_precio:
                        candidatos = candidatos_precio # Priorizamos el filtro de precio
                    # Si no hay matches EXACTOS con ese precio en la categoría, ¿volvemos a mostrar todos? 
                    # Elite Decision: NO. Si usuario pide "perfumes de 3000" y no hay, mejor decir que no hay a mostrar de 5000 random.
                    # PERO, para no ser tan drásticos, podríamos mostrar los random avisando.
                    # Por ahora, comportamiento estricto: Si pide precio, filtramos.
                
                if candidatos:
                    import random
                    return {"tipo": "RECOMENDACION_REAL", "items": random.sample(candidatos, min(5, len(candidatos)))}

        # Estrategia 2: Keywords (o Búsqueda por precio puro si no hay categoría)
        # Si no hubo match de categoría pero HAY PRECIO, buscamos en TODOS los productos por precio
        if precio_objetivo and not keywords:
             candidatos_precio = [p for p in self.productos if int(p['price']) == precio_objetivo]
             if candidatos_precio:
                 # Ordenar alfabéticamente para variedad
                 candidatos_precio.sort(key=lambda x: x['title'])
                 return {"tipo": "EXACTO", "items": candidatos_precio[:5]}

        keywords = [w for w in palabras if w not in self.palabras_basura and len(w) > 2]
        if keywords:
            resultados = []
            for p in self.productos:
                score = 0
                for kw in keywords:
                    if kw in p['search_text']: score += 1
                
                # Boost por precio si está presente
                if precio_objetivo and int(p['price']) == precio_objetivo:
                    score += 5 # Super boost

                if score > 0: resultados.append((score, p))
            
            # Si filtramos por precio, el score boosteado los pondrá arriba
            resultados.sort(key=lambda x: x[0], reverse=True)
            
            # Si había precio target, filtramos el output final para asegurar coherencia
            if precio_objetivo:
                # Ver si los top results cumplen el precio
                filtrados_precio = [r for r in resultados if int(r[1]['price']) == precio_objetivo]
                if filtrados_precio:
                    resultados = filtrados_precio

            if resultados:
                return {"tipo": "EXACTO", "items": [r[1] for r in resultados[:5]]}
        
        # Fallback: Si solo escribió "3000" y keywords no detectó nada (porque solo tiene números)
        if precio_objetivo:
             candidatos_precio = [p for p in self.productos if int(p['price']) == precio_objetivo]
             import random
             if candidatos_precio:
                 return {"tipo": "EXACTO", "items": random.sample(candidatos_precio, min(5, len(candidatos_precio)))}

        return {"tipo": "VACIO", "items": []}
    
    def get_random_products(self, n: int = 1) -> List[Dict[str, Any]]:
        """Devuelve N productos aleatorios de la DB en memoria."""
        if not self.productos: return []
        import random
        return random.sample(self.productos, min(n, len(self.productos)))

    # --- EXPORTACIÓN ---
    def exportar_csv_str(self) -> str:
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
    def generar_checkout_especifico(self, ids: List[int], contexto_total: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:

        # ... (misma lógica de antes, solo que ahora contexto_total viene de self.productos que ya es rico)
        # Reutilizamos la lógica existente de draft orders api
        if not ids: return None
        items = []
        mapa = {int(p['id']): p for p in self.productos} # Mapa rápido ID->Prod
        
        for i in ids:
            if int(i) in mapa:
                items.append(mapa[int(i)])
        
        return self._crear_draft_order(items) if items else None

    def _crear_draft_order(self, items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:

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
