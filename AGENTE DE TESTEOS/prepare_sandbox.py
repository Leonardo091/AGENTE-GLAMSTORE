import os
import shutil
import logging

def prepare_sandbox(source_path, sandbox_path):
    print(f"📦 Creando sandbox desde: {source_path}")
    print(f"➡️  Destino: {sandbox_path}")
    
    # 1. Copiar archivos
    if os.path.exists(sandbox_path):
        shutil.rmtree(sandbox_path)
    
    # Ignorar carpetas pesadas o inútiles
    shutil.copytree(source_path, sandbox_path, ignore=shutil.ignore_patterns('__pycache__', '.git', 'venv', 'node_modules'))
    
    # 2. Instrumentar app.py
    app_py_path = os.path.join(sandbox_path, "app.py")
    
    with open(app_py_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Inyectar MockModel y flag TEST_MODE
    patch_code = """
TEST_MODE = os.environ.get("TEST_MODE") == "True"

# --- MOCK PARA TESTING (INJECTED BY SANDBOX) ---
class MockModel:
    def generate_content(self, prompt):
        p = prompt.lower()
        class Resp: pass
        r = Resp()
        
        # 1. Router (Intenciones)
        if "clasificador" in p:
            # Analizamos el texto entre comillas en: Analiza el siguiente mensaje del cliente: "{texto}"
            # O mas facil, buscamos palabras clave globales
            if "horario" in p or "donde" in p: r.text = "SOPORTE"
            elif "precio" in p or "quiero" in p or "link" in p: r.text = "CATALOGO"
            else: r.text = "CHARLA"
            return r
            
        # 2. Selector (Productos)
        if "selector" in p:
            if "todos" in p: r.text = '["TODOS"]'
            elif "ambiguo" in p: r.text = '["AMBIGUO"]'
            else: r.text = '[12345]'
            return r

        # 3. Respuesta Final (Chat)
        # Extraemos lo ultimo dicho por el usuario para decidir
        last_user_input = p.split("user:")[-1] if "user:" in p else p
        
        if "horario" in last_user_input: 
            r.text = "Bot: Nuestro horario es Lunes a Viernes 10:00-17:30."
        elif "link" in last_user_input or "pago" in last_user_input: 
            r.text = "Bot: ¡Claro! Aquí tienes tu link de pago seguro: https://sandbox-check.out/pay 💳"
        elif "precio" in last_user_input or "perfume" in last_user_input: 
            r.text = "Bot: Tenemos precio oferta $10.000 para ese perfume. ¿Te lo envuelvo? 🎁"
        else: 
            r.text = "Bot: Hola! Soy tu asistente virtual de prueba."
        return r

"""
    # Insertar después de la carga de variables
    if "VERIFY_TOKEN =" in content:
        content = content.replace('VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "glamstore_verify_token") # ACTUALIZADO: Coincide con tu Render', 
                                  'VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "glamstore_verify_token")\n' + patch_code)
    
    # Reemplazar inicialización de modelo
    init_code_original = """# Configurar Gemini
if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    model = genai.GenerativeModel('gemini-2.0-flash')"""

    init_code_patched = """# Configurar Gemini
if TEST_MODE:
    logging.warning("⚠️ SANDBOX: Usando MockModel")
    model = MockModel()
elif API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    model = genai.GenerativeModel('gemini-2.0-flash')"""

    content = content.replace(init_code_original, init_code_patched)
    
    # Inyectar Logging Hook
    if 'enviar_whatsapp(numero, resp_final)' in content:
        hook_code = """
        # --- LOGGING INJECTED ---
        try:
            print(f">>> BOT REPLIED: {resp_final.encode('ascii', 'replace').decode('ascii')}", flush=True)
        except:
            print(f">>> BOT REPLIED: [Content Error]", flush=True)
            
        enviar_whatsapp(numero, resp_final)"""
        
        content = content.replace('enviar_whatsapp(numero, resp_final)', hook_code, 1)

    # Disable Warming Up check
    if 'if db.total_items == 0:' in content:
        content = content.replace('if db.total_items == 0:', 'if db.total_items == 0 and not TEST_MODE:')

    with open(app_py_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    print("✅ Sandbox preparado e instrumentado.")

if __name__ == "__main__":
    # Ajustar rutas relativas según ejecución
    base = os.getcwd()
    # Asumiendo ejecución desde AGENTE DE TESTEOS
    prepare_sandbox(os.path.abspath("../ASISTENTE GLAMSTORE"), os.path.abspath("./sandbox"))
