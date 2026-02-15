---
name: Tester de Archivos
description: Asistente para verificación, validación (linting/syntax) y smoke testing de código generado.
---

# Tester de Archivos

## Propósito
Asegurar la calidad del código antes de entregarlo. "Si compila, no significa que funcione".

## Instrucciones
1.  **Linting**: Verifica la sintaxis antes de ejecutar.
2.  **Smoke Test**: Ejecuta el código brevemente para ver si "explota" al inicio.
3.  **Unit Test**: Si es complejo, crea un test rápido usando la plantilla.
4.  **Verificar Salida**: Confirma que los archivos generados existan y tengan contenido.

## Uso de Recursos
- **Checklist**: Sigue `references/checklist_testing.md`.
- **Plantilla**: Usa `assets/templates/test_quick.py` para tests rápidos.
