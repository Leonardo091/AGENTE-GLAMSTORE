---
name: Tester de Archivos
description: Asistente para la verificación, validación y testing de código y archivos generados.
---

# Tester de Archivos

## Propósito
Esta habilidad guía al Agente en el proceso de verificar, validar y testear cualquier tipo de archivo o proyecto de software generado. Su objetivo es asegurar la calidad y funcionalidad independientemente del lenguaje o propósito del producto (sea GlamStore u otro futuro).

## Instrucciones de Uso

Úsala siempre que crees un nuevo componente, script o aplicación completa. No esperes a que el usuario lo pida.

### 1. Validación Estática (Linting/Sintaxis)
Antes de ejecutar nada, verifica que el código sea sintácticamente correcto.
- **Python**: Usa `python -m py_compile archivo.py` o revisa con herramientas de linting si están disponibles.
- **Node.js/JS**: Ejecuta `node --check archivo.js` para validar sintaxis.
- **JSON**: Verifica que el JSON sea válido (sin comas extra, cierres correctos).

### 2. Pruebas de Ejecución (Smoke Testing)
Ejecuta el archivo de la forma más simple posible para ver si "explota" al arrancar.
- ¿Importa las librerías correctamente?
- ¿Carga las variables de entorno?
- _Ejemplo_: `python app.py` (y matarlo tras unos segundos si es un servidor) o `node index.js`.

### 3. Creación de Tests Unitarios Rápidos
Si la lógica es compleja, crea un script temporal de prueba (`test_quick.py` o similar) en el mismo directorio (o en `tests/`).
- Importa la función clave.
- Pasa entradas conocidas y comprueba salidas esperadas.
- Usa `assert` para validar.

**Plantilla Python (test_quick.py):**
```python
from archivo_objetivo import funcion_a_probar

def test_caso_basico():
    resultado = funcion_a_probar("entrada")
    assert resultado == "esperado", f"Fallo: {resultado} != esperado"
    print("✅ Test básico pasado")

if __name__ == "__main__":
    test_caso_basico()
```

### 4. Verificación de Artefactos Salida
Si el código genera archivos (imágenes, CSVs, logs):
- Ejecuta el código.
- Usa `ls -l` o `list_dir` para ver si se creó el archivo.
- Usa `view_file` (head/tail) para inspeccionar el contenido generado.

### 5. Reporte
Informa al usuario:
- Qué pruebas realizaste.
- Resultados (Éxito/Fallo/Salida de error).
- Si falló, propón el arreglo inmediatamente.
