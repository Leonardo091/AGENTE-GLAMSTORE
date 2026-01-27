import threading
import time
import requests
import os
import logging
from datetime import datetime, timedelta

# Logs detallados para ver dónde se queda pegado
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] DIAGNOSTICO: %(message)s')

class GlamStoreDB:
    def __init__(self):
        self.productos = []
        self.total_items = 0
        self.identidad = "Modo Diagnóstico (Esperando conexión...)"
        
        # 1. VERIFICAMOS CREDENCIALES AL ARRANCAR
        self.token = os.environ.get("SHOPIFY_TOKEN")
        self.url_tienda = os.environ.get("SHOPIFY_URL")
        
        if not self.token:
            logging.error("⛔ FATAL: No existe la variable SHOPIFY_TOKEN en Render.")
        if not self.url_tienda:
            logging.error("⛔ FATAL: No existe la variable SHOPIFY_URL en Render.")

        # Arrancamos hilo
        hilo = threading.Thread(target=self._test_carga)
        hilo.daemon = True
        hilo.start()

    def _test_carga(self):
        """Intenta cargar SOLO 10 productos para probar conexión"""
        time.sleep(5) # Esperamos 5 seg a que Flask arranque para no chocar
        
        logging.info("🚀 INICIANDO PRUEBA DE CONEXIÓN A SHOPIFY...")
        
        if not self.token or not self.url_tienda:
            logging.error("❌ Cancelando: Faltan datos.")
            return

        # Limpiamos URL
        clean_url = self.url_tienda.replace("https://", "").replace("/", "")
        url = f"https://{clean_url}/admin/api/2024-01/products.json"
        
        logging.info(f"📡 Intentando conectar a: {url}")
        
        headers = {"X-Shopify-Access-Token": self.token, "Content-Type": "application/json"}
        # PEDIMOS SOLO 10 PRODUCTOS
        params = {"status": "active", "limit": 10} 
        
        try:
            r = requests.get(url, headers=headers, params=params, timeout=15)
            
            if r.status_code == 200:
                data = r.json().get("products", [])
                cantidad = len(data)
                logging.info(f"✅ CONEXIÓN EXITOSA. Shopify respondió con {cantidad} productos.")
                
                # Guardamos esos 10
                temp_list = []
                for p in data:
                    try:
                        prec = float(p["variants"][0]["price"])
                        temp_list.append({"title": p["title"], "price": prec, "id": p["id"]})
                    except: pass
                
                self.productos = temp_list
                self.total_items = len(temp_list)
                self.identidad = "PRUEBA EXITOSA: Conexión establecida."
                logging.info("🎉 BASE DE DATOS CARGADA CON MUESTRA DE 10 ITEMS.")
                
            elif r.status_code == 401:
                logging.error("❌ ERROR 401: El Token es inválido (Revisa SHOPIFY_TOKEN).")
            elif r.status_code == 403:
                logging.error("❌ ERROR 403: Falta permiso 'read_products' (Reinstalar App en Shopify).")
            elif r.status_code == 404:
                logging.error("❌ ERROR 404: La URL de la tienda está mal escrita.")
            else:
                logging.error(f"❌ ERROR DESCONOCIDO: Código {r.status_code}")
                
        except Exception as e:
            logging.error(f"❌ ERROR DE RED CRÍTICO: {e}")

    # Funciones dummy para que app.py no falle
    def buscar_producto_rapido(self, q): return {"tipo": "VACIO", "items": []}
    def obtener_identidad(self): return self.identidad
    def crear_link_pago_seguro(self, n): return "Modo Prueba"

db = GlamStoreDB()
