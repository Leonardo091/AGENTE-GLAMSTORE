# Protocolos de Seguridad (CSO)

## 1. Infraestructura & Disponibilidad
- **Rate Limiting (Anti-Spam):** Prevenir saturación (100 msgs/seg).
- **Circuit Breakers:** Si Shopify o Gemini fallan, el sistema debe degradarse suavemente (Fail-Safe).

## 2. Protección Financiera (Cost Control)
- **Token Economy:** Prevenir loops infinitos de gasto en API.
- **Short-Circuits:** Responder saludos simples SIN gastar IA (Regla de "Hola").

## 3. Privacidad & Datos (PII)
- **Sanitización:** Limpiar logs de datos sensibles (Tarjetas, Direcciones).
- **Access Control:** Solo Admins (Leo/Rocío) tienen llaves maestras.

## 4. Vigilancia
- **Log Watch:** Revisión de logs en busca de errores 500 repetidos.
- **Chaos Testing:** Intentar romper el bot a propósito para encontrar grietas.
