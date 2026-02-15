
import os
import shutil

def main():
    user_home = os.path.expanduser("~")
    local_skill_path = os.path.join(os.getcwd(), "skills", "creador_de_habilidades")
    global_skill_path = os.path.join(user_home, ".antigravity_skills", "creador_de_habilidades")

    print(f"Sincronizando desde: {local_skill_path}")
    print(f"Hacia global: {global_skill_path}")

    if os.path.exists(global_skill_path):
        shutil.rmtree(global_skill_path)
    
    try:
        shutil.copytree(local_skill_path, global_skill_path)
        print("✅ Skill Global actualizada a versión Pro.")
    except Exception as e:
        print(f"❌ Error actualizando global: {e}")

if __name__ == "__main__":
    main()
