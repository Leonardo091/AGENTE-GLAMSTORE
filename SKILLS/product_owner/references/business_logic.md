# Lógica de Negocio y Principios (Business Owner)

## 1. Business Continuity First (La Caja NO Para)
- **Regla de Oro:** Ningún deploy debe romper la capacidad de vender.
- **Acción:** Antes de cambios críticos (`checkout`, `database`), simular mentalmente fallas.
- **Reflejo:** Implementar *Fallbacks* y *Circuit Breakers* (`MODO_VACACIONES`).

## 2. Reputación de Marca > Excepción de Software
- Un error 500 es malo, una respuesta grosera es fatal.
- **Acción:** Blindar respuestas. Si falla, fallar con elegancia ("Estamos ordenando la bodega").

## 3. Anticipación de Escenarios (The "What If" Game)
- **Checklist Mental:**
    - ¿Qué pasa si el stock llega a 0?
    - ¿Qué pasa si la API de Shopify se cae?
    - ¿Qué pasa si es feriado?

## 4. Protocolos
### Protocolo "Sync & Verify"
- Verificar flujos clave tras cada cambio:
    1.  Saludo ("Hola")
    2.  Búsqueda ("Tienen labiales?")
    3.  Intención de Compra ("Quiero comprar") -> **CRÍTICO**

### Protocolo "Red Button"
- Mecanismos para desactivar features complejas: `MODO_MANTENIMIENTO`, `MODO_VACACIONES`.
