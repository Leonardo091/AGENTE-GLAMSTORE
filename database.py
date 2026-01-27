import threading
import time
import requests
import os
import logging
from datetime import datetime

# Configuración de logs
logging.basicConfig(level=logging.INFO)

class GlamStoreDB:
    def __init__(self):
        self.productos = []
        self.total_items = 0
        # Mensaje inicial
        self.identidad = "⏳ INICIANDO DIAGNÓSTICO... (Espera 10 seg)"
        
        self.token = os.environ.get("SHOPIFY_TOKEN")
        self.url_tienda = os.environ.get("SHOPIFY_URL")
        
        # Arrancamos el test
        hilo = threading.Thread(target=self._test_carga)
        hilo.daemon = True
        hilo.start()

    def _test_carga(self):
        time.sleep(3) # Espera breve
        
        try:
            # 1. VERIFICACIÓN DE VARIABLES
            if not self.token:
                self.identidad = "❌ ERROR: Faltan Credenciales (SHOPIFY_TOKEN vacío)"
                return
            if not self.url_tienda:
                self.identidad = "❌ ERROR: Faltan Credenciales (SHOPIFY_URL vacío)"
                return

            # 2. LIMPIEZA DE URL (A prueba de balas)
            # Quitamos https, barras y la palabra 'admin' si se coló
            clean_url = self.url_tienda.replace("https://", "").replace("http://", "")
            if "/" in clean_url:
                clean_url = clean_url.split("/")[0]
            
            self.identidad = f"📡 CONECTANDO A: {clean_url}..."
            
            url = f"https://{clean_url}/admin/api/2024-01/products.json"
            headers = {"X-Shopify-Access-Token": self.token, "Content-Type": "application/json"}
            params = {"status": "active", "limit": 10} 
            
            # 3. LLAMADA A SHOPIFY
            r = requests.get(url, headers=headers, params=params, timeout=15)
            
            if r.status_code == 200:
                data = r.json().get("products", [])
                
                # Guardamos muestra
                temp_list = []
                for p in data:
                    try:
                        prec = float(p["variants"][0]["price"])
                        temp_list.append({"title": p["title"], "price": prec, "id": p["id"]})
                    except: pass
                
                self.productos = temp_list
                self.total_items = len(temp_list)
                # MENSAJE DE ÉXITO
                self.identidad = f"✅ ÉXITO: Conectado a {clean_url}. (Muestra de 10 items)"
                
            elif r.status_code == 401:
                self.identidad = "❌ ERROR 401: Token Inválido (Revisa SHOPIFY_TOKEN en Render)"
            elif r.status_code == 403:
                self.identidad = "❌ ERROR 403: Permisos (Falta 'read_products' en Shopify)"
            elif r.status_code == 404:
                self.identidad = f"❌ ERROR 404: Tienda no encontrada (Revisa URL: {clean_url})"
            else:
                self.identidad = f"❌ ERROR DESCONOCIDO: Código {r.status_code}"

        except Exception as e:
            # AQUÍ ATRAPAMOS EL ERROR TÉCNICO
            self.identidad = f"❌ CRASH TÉCNICO: {str(e)}"

    # Funciones dummy para que no falle app.py
    def buscar_producto_rapido(self, q): return {"tipo": "VACIO", "items": []}
    def obtener_identidad(self): return self.identidad
    def crear_link_pago_seguro(self, n): return "Link de Prueba"

db = GlamStoreDB()
