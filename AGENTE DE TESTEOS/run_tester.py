import argparse
import sys
import os
from colorama import init, Fore, Style
from dotenv import load_dotenv

# Inicializar colores
init(autoreset=True)

def main():
    parser = argparse.ArgumentParser(description="Agente de Testeos (QA Bot) - Auditoría de Proyectos")
    parser.add_argument("--target", type=str, required=True, help="Ruta relativa o absoluta al proyecto a testear")
    parser.add_argument("--mode", type=str, choices=["all", "static", "smoke", "simulation"], default="all", help="Modo de prueba")
    
    args = parser.parse_args()
    
    target_path = os.path.abspath(args.target)
    
    print(f"\n{Fore.CYAN}{Style.BRIGHT}🤖 AGENTE DE TESTEOS INICIADO")
    print(f"{Fore.CYAN}====================================")
    print(f"🎯 Objetivo: {Fore.YELLOW}{target_path}")
    print(f"🛠️  Modo:     {Fore.YELLOW}{args.mode}")
    print(f"{Fore.CYAN}====================================\n")

    if not os.path.exists(target_path):
        print(f"{Fore.RED}❌ Error: La ruta objetivo no existe: {target_path}")
        sys.exit(1)

    # Cargar suites
    from suites.static_checks import run_static_checks
    from suites.smoke import run_smoke_test
    from suites.conversation import run_simulation

    total_score = 0
    max_score = 0
    
    # 1. Static
    if args.mode in ["all", "static"]:
        s, i = run_static_checks(target_path)
        total_score += s
        max_score += 100
        print(f"   📝 Score Estático: {s}/100")
        if i: print(f"      Issues: {i}")

    # 2. Smoke (Server Up check)
    server_healthy = False
    if args.mode in ["all", "smoke", "simulation"]:
        # Necesitamos el server arriba para simulación también
        # app.py del target hardcodea el puerto 10000, así que debemos usar ese.
        target_port = 10000 
        s, i = run_smoke_test(target_path, port=target_port)
        if s == 100: server_healthy = True
        
        if args.mode in ["all", "smoke"]:
            total_score += s
            max_score += 100
            print(f"   📝 Score Smoke: {s}/100")
            if i: print(f"      Issues: {i}")

    # 3. Simulation
    if args.mode in ["all", "simulation"]:
        # Usamos la utilidad de smoke para levantar el server
        from suites.smoke import start_test_server, stop_test_server
        
        print(f"{Fore.MAGENTA}💬 [NIVEL 2] Simulación de Conversación...")
        
        # Levantar servidor
        # args: target, port. returns: proc, log_handle
        proc, log_handle = start_test_server(target_path, target_port)
        
        if proc:
            # Pasamos proc a la suite
            s, i = run_simulation(target_path, port=target_port, server_process=proc)
            
            # Matamos servidor y cerramos log
            stop_test_server(proc, log_handle)
            
            # --- MOSTRAR LOGS CAPTURADOS (CONVERSACIÓN) ---
            print(f"\n{Fore.YELLOW}📜 REGISTRO DE CONVERSACIÓN (Logs del Bot):")
            try:
                # Leemos el archivo generado
                with open("server.log", "r", encoding="utf-8", errors='replace') as f:
                    content = f.read()
                    
                for line in content.splitlines():
                    if ">>> BOT REPLIED:" in line:
                         clean_line = line.split(">>> BOT REPLIED:")[1].strip()
                         print(f"   🤖 Bot: {Fore.CYAN}{clean_line}")
                    elif "Warning" in line or "Error" in line:
                         pass 
                    # Opcional: Mostrar todo si es debug
                    # else: print(line) 
            except Exception as e:
                print(f"   (No se pudieron leer logs: {e})")

            total_score += s
            max_score += 100
            print(f"   📝 Score Simulación: {s}/100")
            if i: print(f"      Issues: {i}")
        else:
            print(f"   ❌ No se pudo iniciar servidor para simulación: {err}")
            max_score += 100 # Penalizar puntuación total
            
    final_avg = (total_score / max_score) * 100 if max_score > 0 else 0
    print(f"\n{Fore.GREEN if final_avg > 80 else Fore.RED}📊 REPORTE FINAL: {final_avg:.1f}/100")
    print(f"{Fore.CYAN}====================================")

if __name__ == "__main__":
    main()
