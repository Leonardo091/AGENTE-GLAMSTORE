import unittest
from unittest.mock import MagicMock
import logging
from database import GlamStoreDB

# Configurar logging para ver lo que pasa
logging.basicConfig(level=logging.INFO)

class TestGlamStoreLogic(unittest.TestCase):
    def setUp(self):
        self.db = GlamStoreDB()
        # Simulamos que NO hay conexión para que no intente correr el thread
        self.db.shopify_token = None
        
        # Inyectamos datos de prueba manualmente (Simulando lo que haría _actualizar_tabla_maestra)
        # Producto 1: Perfume
        p1 = {
            "id": 12345,
            "title": "Perfume Maison Alhambra",
            "price": 29990.0,
            "search_text": self.db._normalizar("Perfume Maison Alhambra VendorX ProductType Tag1"),
            "variant_id": 111
        }
        # Producto 2: Shampoo
        p2 = {
            "id": 67890,
            "title": "Shampoo de Argan",
            "price": 15990.0,
            "search_text": self.db._normalizar("Shampoo de Argan VendorY Cabello Tratamiento"),
            "variant_id": 222
        }
        
        self.db.productos = [p1, p2]
        self.db.total_items = 2
        logging.info(f"DB Cargada con: {[p['title'] for p in self.db.productos]}")

    def test_busqueda_perfume(self):
        logging.info("--- Test: Buscar 'perfume' ---")
        res = self.db.buscar_contextual("Hola, tienen perfumes?")
        logging.info(f"Resultado: {res}")
        self.assertNotEqual(res['tipo'], "VACIO")
        self.assertTrue(any("Perfume" in p['title'] for p in res['items']))

    def test_busqueda_shampoo_plural(self):
        logging.info("--- Test: Buscar 'shampoos' (Plural) ---")
        # El usuario dijo "Tienen shampoos ?"
        res = self.db.buscar_contextual("Tienen shampoos ?")
        logging.info(f"Resultado: {res}")
        
        # Esto es lo que sospecho que falla si la normalización o stemming no es buena
        # Si falla, veremos failure aquí.
        if res['tipo'] == "VACIO":
            logging.warning("FALLÓ: No encontró 'shampoos'")
        
        self.assertNotEqual(res['tipo'], "VACIO", "Debería encontrar shampoo aunque se busque en plural")

    def test_busqueda_maison_alhambra(self):
        logging.info("--- Test: Buscar 'maison alhambra' ---")
        res = self.db.buscar_contextual("Quiero comprar un perfume maison alhambra")
        logging.info(f"Resultado: {res}")
        self.assertNotEqual(res['tipo'], "VACIO")
        self.assertTrue(any("Maison" in p['title'] for p in res['items']))

    def test_busqueda_marca_plural(self):
        logging.info("--- Test: Buscar 'Alhambras' (Marca Plural) ---")
        # 'Alhambra' NO está en categorias.
        # Si busco "Alhambras", va a ir a keywords.
        # "Alhambras" no está en "Perfume Maison Alhambra" (substring match falla)
        res = self.db.buscar_contextual("Quiero comprar Alhambras")
        logging.info(f"Resultado: {res}")
        self.assertNotEqual(res['tipo'], "VACIO", "Debería encontrar 'Alhambra' buscando 'Alhambras'")

    def test_busqueda_vacia(self):
        logging.info("--- Test: Buscar algo que no existe ---")
        res = self.db.buscar_contextual("Venden pan?")
        self.assertEqual(res['tipo'], "VACIO")

    def test_caso_usuario_fotos(self):
        """
        Prueba basada en las capturas de pantalla del usuario.
        Productos reales:
        1. Maison Alhambra Glacier Ultra Edp 30ml
        2. Lattafa Mayar Desodorante Spray 200 ml Mujer
        """
        self.db.productos = [
            {
                'id': 101, 
                'title': "Maison Alhambra Glacier Ultra Edp 30ml", 
                'price': 15000, 
                'search_text': "maison alhambra glacier ultra edp 30ml hombre perfume"
            },
            {
                'id': 102, 
                'title': "Lattafa Mayar Desodorante Spray 200 Ml Mujer", 
                'price': 12000, 
                'search_text': "lattafa mayar desodorante spray 200 ml mujer desodorantes"
            }
        ]
        
        # Caso 1: "Tienen el glacier ultra edp 30 ml ?"
        query1 = "Tienen el glacier ultra edp 30 ml ?"
        res1 = self.db.buscar_contextual(query1)
        print(f"\nBusqueda Foto 1 ('{query1}'): {res1['tipo']}")
        found1 = any("Glacier Ultra" in p['title'] for p in res1['items'])
        self.assertTrue(found1, "Debería encontrar Glacier Ultra")

        # Caso 2: "Y el Lattafa Mayar Desodorante Spray 200 Ml Mujer"
        query2 = "Y el Lattafa Mayar Desodorante Spray 200 Ml Mujer"
        res2 = self.db.buscar_contextual(query2)
        print(f"Busqueda Foto 2 ('{query2}'): {res2['tipo']}")
        found2 = any("Lattafa Mayar" in p['title'] for p in res2['items'])
        self.assertTrue(found2, "Debería encontrar Lattafa Mayar")

        # Caso 3: "Hola busco perfumes" (Debería activar categoría o keyword)
        query3 = "Hola busco perfumes"
        res3 = self.db.buscar_contextual(query3)
        print(f"Busqueda Foto 3 ('{query3}'): {res3['tipo']}")
        self.assertNotEqual(res3['tipo'], "VACIO")

if __name__ == '__main__':
    unittest.main()
