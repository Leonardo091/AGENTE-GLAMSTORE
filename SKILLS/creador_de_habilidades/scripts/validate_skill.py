
import os
import sys

def parse_frontmatter(content):
    """
    Parsea manualmente el frontmatter YAML básico sin dependencias externas.
    Retorna un diccionario con las claves encontradas.
    """
    input_lines = content.splitlines()
    if not input_lines or input_lines[0].strip() != "---":
        return None
    
    frontmatter = {}
    for line in input_lines[1:]:
        line = line.strip()
        if line == "---":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            frontmatter[key.strip()] = value.strip()
            
    return frontmatter

def validate_skill(skill_path):
    print(f"🔍 Validando skill en: {skill_path}")
    
    # 1. Verificar SKILL.md
    skill_md = os.path.join(skill_path, "SKILL.md")
    if not os.path.exists(skill_md):
        print("❌ Error: Falta el archivo SKILL.md obligatorio.")
        return False

    # 2. Verificar Estructura de Carpetas Sugerida
    for folder in ["scripts", "references", "assets"]:
        path = os.path.join(skill_path, folder)
        if os.path.exists(path) and not os.path.isdir(path):
             print(f"⚠️ Advertencia: '{folder}' debería ser una carpeta.")

    # 3. Leer Frontmatter
    try:
        with open(skill_md, 'r', encoding='utf-8') as f:
            content = f.read()
        
        data = parse_frontmatter(content)
        
        if data is None:
            print("❌ Error: SKILL.md debe empezar con YAML frontmatter (---).")
            return False
            
        if "name" not in data or "description" not in data:
            print("❌ Error: Faltan campos 'name' o 'description' en el YAML.")
            return False
            
        print(f"✅ Skill '{data['name']}' válida y lista para usar.")
        return True
        
    except Exception as e:
        print(f"❌ Error leyendo SKILL.md: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python validate_skill.py <ruta_de_la_skill>")
    else:
        validate_skill(sys.argv[1])
