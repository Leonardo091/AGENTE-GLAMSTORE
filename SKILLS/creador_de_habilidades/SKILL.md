---
name: Creador de Habilidades Pro
description: Utilidad avanzada para generar skills estandarizadas con estructura profesional (scripts, assets, references).
---

# Creador de Habilidades (Versión Pro)

Esta habilidad guía al Agente para crear nuevas skills siguiendo el estándar profesional de Antigravity/Anthropic, pero adaptado totalmente al español y simplificado.

## Estructura de Directorios

Cada nueva habilidad debe crearse dentro de `skills/<nombre_snake_case>/` y seguir esta estructura:

```text
skills/mi_nueva_skill/
├── SKILL.md            (OBLIGATORIO: Instrucciones y Metadata)
├── scripts/            (OPCIONAL: Scripts Python/Bash ejecutables)
├── references/         (OPCIONAL: Documentación, guías, textos largos)
└── assets/             (OPCIONAL: Plantillas, imágenes, archivos estáticos)
```

## Definición de Componentes

### 1. SKILL.md (El Cerebro)
Es el único archivo que el Agente lee automáticamente para saber **cuándo** y **cómo** usar la skill.

**Formato Requerido:**
```markdown
---
name: Nombre De La Skill
description: Describe AQUÍ cuándo se debe activar esta skill. (Ej: "Úsala para analizar CSVs...").
---

# Título de la Skill

## Propósito
Explicación breve de qué problema resuelve.

## Instrucciones
Pasos claros y numerados que el Agente debe seguir.

## Uso de Recursos (Si aplica)
- Ejecuta `scripts/mi_script.py` para...
- Lee `references/guia.md` para entender...
```

### 2. scripts/ (La Fuerza)
Coloca aquí código que deba ejecutarse, no solo leerse.
*   *Ejemplo:* `scripts/auditar_seo.py`, `scripts/resize_image.py`.
*   *Ventaja:* Ahorra tokens y evita errores de sintaxis al re-escribir código.

### 3. references/ (El Conocimiento)
Documentación extensa que el Agente puede consultar *bajo demanda*.
*   *Ejemplo:* `references/api_docs.md`, `references/brand_guidelines.pdf`.

### 4. assets/ (Los Materiales)
Archivos que se usarán en el resultado final para el usuario.
*   *Ejemplo:* `assets/plantilla_email.html`, `assets/logo.png`.

## Proceso de Creación (Paso a Paso)

Cuando el usuario pida una nueva habilidad:

1.  **Analizar**: ¿Qué necesita? ¿Requiere scripts o es solo texto?
2.  **Estructurar**:
    *   Crea la carpeta `skills/<nombre_snake_case>`.
    *   Crea las subcarpetas necesarias (`scripts`, etc.).
3.  **Implementar**:
    *   Escribe los scripts en `scripts/`.
    *   Escribe el `SKILL.md` final apuntando a esos scripts.
4.  **Validar (Opcional)**:
    *   Verifica que el YAML del `SKILL.md` sea correcto.

## Ejemplo Real: "Analizador de SEO"

Si creas una skill de SEO, debería verse así:
*   `skills/analisis_seo/SKILL.md`: Instrucciones ("Ejecuta el script y resume el output").
*   `skills/analisis_seo/scripts/check_seo.py`: Código Python que hace el request y chequea tags.
*   `skills/analisis_seo/references/mejores_practicas.md`: Lista de checklist de Google.
