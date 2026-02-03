---
name: Creador de Habilidades
description: Utilidad para generar nuevas habilidades (skills) en el workspace de forma estandarizada y en español.
---

# Creador de Habilidades

Esta habilidad contiene las instrucciones y plantillas necesarias para que el Agente cree nuevas habilidades en el workspace.

## Estructura de una Habilidad

Cada nueva habilidad debe seguir esta estructura de directorios:
`skills/<nombre_en_snake_case>/`

Dentro de esa carpeta, debe existir OBLIGATORIAMENTE un archivo `SKILL.md`.

## Formato de SKILL.md

El archivo `SKILL.md` debe tener:
1.  **YAML Frontmatter**: Al inicio del archivo.
    ```yaml
    ---
    name: Nombre Legible de la Habilidad
    description: Descripción corta de una línea.
    ---
    ```
2.  **Instrucciones**: Contenido en Markdown explicando al Agente cómo usar la habilidad.

## Proceso de Creación

Para crear una nueva habilidad solicitada por el usuario:

1.  **Identificar el Nombre**: Deriva un nombre corto y descriptivo en `snake_case` para la carpeta (ej. `analisis_de_datos`).
2.  **Identificar el Propósito**: Redacta una descripción clara y un conjunto de instrucciones.
3.  **Generar el Archivo**:
    Crea el archivo `skills/<nombre_carpeta>/SKILL.md` con el contenido apropiado.
4.  **Idioma**: Asegúrate de que todas las instrucciones dentro del nuevo `SKILL.md` estén en **Español**.
5.  **Extras**: Si la habilidad necesita scripts (Python, JS, etc.), crea una subcarpeta `scripts/` y coloca ahí los archivos.

## Ejemplo de Plantilla (Output esperado)

```markdown
---
name: Ejemplo De Habilidad
description: Esta es una habilidad de ejemplo.
---
# Ejemplo De Habilidad

## Propósito
Esta habilidad sirve para demostrar el formato correcto.

## Instrucciones
1. Haz X.
2. Haz Y.
```
