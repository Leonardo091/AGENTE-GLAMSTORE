import os
from colorama import Fore

def run_static_checks(target_path):
    print(f"{Fore.MAGENTA}🔎 [NIVEL 0] Ejecutando Análisis Estático...")
    
    score = 100
    issues = []

    # 1. Verificar existencia de archivos clave
    required_files = ['requirements.txt', '.env', 'app.py'] # Ajustable según tipo de proyecto
    
    for req in required_files:
        p = os.path.join(target_path, req)
        if os.path.exists(p):
            print(f"   ✅ Encontrado: {req}")
        else:
            print(f"   ❌ FALTANTE: {req}")
            issues.append(f"Falta archivo crítico: {req}")
            score -= 20

    # 2. Verificar existencia de .env (seguridad)
    env_path = os.path.join(target_path, '.env')
    if os.path.exists(env_path):
        # Leer si tiene keys vacías
        with open(env_path, 'r') as f:
            content = f.read()
            if "=" in content and not "KEY=" in content: # Heurística muy simple
                 print(f"   ✅ .env parece tener contenido")
            else:
                 print(f"   ⚠️ .env existe pero parece vacío o incompleto")
                 issues.append(".env posiblemente incompleto")
                 score -= 10
    
    return score, issues
