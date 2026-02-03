import os
import sys
import time
import subprocess
import requests
from colorama import Fore

def start_test_server(target_path, port=5000):
    """Inicia el servidor en un subproceso y espera a que responda."""
    app_path = os.path.join(target_path, 'app.py')
    if not os.path.exists(app_path):
        return None, "app.py missing"
    
    cmd = [sys.executable, app_path]
    env = os.environ.copy()
    env['PORT'] = str(port)
    env['TEST_MODE'] = 'True' 
    
    try:
        # Usamos archivo físico para logs, más robusto que PIPE en Windows
        log_file = open("server.log", "w", encoding="utf-8")
        
        process = subprocess.Popen(
            cmd, 
            cwd=target_path,
            stdout=log_file,     # Directo al archivo
            stderr=subprocess.STDOUT, 
            env=env,
            bufsize=1
        )
        return process, log_file # Retornamos handle para cerrar despues
    except Exception as e:
        return None, str(e)

    # Esperar heartbeat
    server_url = f"http://127.0.0.1:{port}"
    for _ in range(10):
        try:
            r = requests.get(server_url, timeout=1)
            if r.status_code == 200:
                print(f"   ✅ Servidor respondió 200 OK (PID: {process.pid})")
                return process, log_file
        except:
            time.sleep(1)
            
    # Si falló
    process.terminate()
    log_file.close() # Cerrar si falló
    return None, "Timeout waiting for server"

def stop_test_server(process, log_file=None):
    if process:
        process.terminate()
        try:
            process.wait(timeout=2)
        except:
            process.kill()
    if log_file:
        try:
            log_file.close()
        except: 
            pass

def run_smoke_test(target_path, port=5000):
    print(f"{Fore.MAGENTA}🔥 [NIVEL 1] Ejecutando Smoke Test...")
    
    # Ahora retorna proceso y file_handle
    process, log_file_or_err = start_test_server(target_path, port)
    
    if not process:
        # Si process es None, log_file_or_err es el string de error
        print(f"   ❌ Fallo al iniciar servidor: {log_file_or_err}")
        return 0, [log_file_or_err]
    
    # Si proceso existe, log_file_or_err es el file handle
    log_handle = log_file_or_err
    
    # print(f"   ✅ Servidor respondió 200 OK (PID: {process.pid})") # Ya lo hace start_test_server
    
    stop_test_server(process, log_handle)
    return 100, []
