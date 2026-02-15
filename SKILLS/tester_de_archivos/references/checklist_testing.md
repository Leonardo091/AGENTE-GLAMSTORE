# Checklist de Testing

## 1. Validación Estática (Linting/Sintaxis)
- **Python**: `python -m py_compile archivo.py`
- **Node.js/JS**: `node --check archivo.js`
- **JSON**: Verificar sintaxis correcta.

## 2. Pruebas de Ejecución (Smoke Testing)
- ¿Importa las librerías correctamente?
- ¿Carga las variables de entorno?
- _Ejemplo_: `python app.py` (y matarlo tras unos segundos).

## 3. Pruebas Unitarias
- Crear script temporal usando la plantilla en `assets/templates/test_quick.py`.

## 4. Verificación de Salida
- Si genera archivos (imágenes, CSVs): `ls -l` para confirmar creación.
- Inspeccionar contenido con `view_file` (head/tail).
