# Stack — Seguridad y observabilidad

## 1. Seguridad: tokens scopeados

Decisión explícita: no se asume que "es localhost" sea suficiente. MCP no define
autenticación en su especificación base (queda a criterio de quien implementa el
transporte), por lo que Janus implementa su propio sistema, siguiendo el patrón
estándar de la industria (API keys scopeadas, al estilo Stripe/GitHub PATs):

- Cada token tiene: `id`, secreto (hasheado en almacenamiento, nunca en texto plano),
  `scopes` (permisos/capacidades que puede invocar), expiración opcional.
- **Token default**: usado por los propios componentes internos de Janus (harnesses
  base), con scope total.
- Los spokes externos deben presentar un token propio, generado por el usuario, al
  registrarse.
- Verificación en cada request entrante al Core de Traducción, antes de tocar el
  Registro de Capacidades.

Vive en `libs/auth/` (validación + hashing); la tabla de tokens vive en SQLite (es
estado real y mutable del sistema, no config declarada a mano).

## 2. Logs y observabilidad

Decisión explícita: logs centralizados, con el mismo criterio que config (una sola
fuente, consumida por todas las partes sin que sepan el detalle de implementación).

- **`structlog`** para logging estructurado (JSON lines) — estándar de facto en Python
  para esto.
- **Rotación** en disco vía `RotatingFileHandler` (por tamaño) o `TimedRotatingFileHandler`
  (por tiempo).
- **Ring buffer en memoria** de tamaño acotado (`collections.deque(maxlen=N)`) que
  alimenta un stream en vivo.
- **Publicación vía Redis pub/sub**, para que cualquier cliente (una futura GUI, ver
  `architecture/07-superficie-para-gui-futura.md`) se suscriba al stream de logs sin
  acoplarse directamente al proceso de `core-gateway`.

Vive en `libs/observability/`.

---

## Documentos relacionados
- `stack/07-descubrimiento-y-capacidades.md` — el registro de spokes externos que
  exige el token de la sección 1.
- `stack/03-persistencia.md` — Redis como capa efímera y SQLite como almacén de la tabla
  de tokens.
- `architecture/07-superficie-para-gui-futura.md` — consumidor futuro del stream de
  observabilidad.
