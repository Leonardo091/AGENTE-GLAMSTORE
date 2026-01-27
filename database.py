# database.py - MODO DUMMY (VACÍO)
class GlamStoreDB:
    def __init__(self):
        self.productos = []
        self.total_items = 0
        self.identidad = "Modo Directo desde App.py"
        
    def buscar_producto_rapido(self, q): return {"tipo": "VACIO", "items": []}
    def obtener_identidad(self): return self.identidad
    def crear_link_pago_seguro(self, n): return "Link Prueba"

db = GlamStoreDB()
