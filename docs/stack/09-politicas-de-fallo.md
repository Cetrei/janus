# Stack — Políticas de fallo

Catálogo rico predefinido, diseñado para escalar a custom.

Estilo de nomenclatura tomado explícitamente de Docker (`restart: on-failure`,
`restart: always`, `restart: never`) por ser un vocabulario ya conocido y fácil de
razonar. Declaradas en `config/janus.toml`, con default global y override por
harness/spoke.

## 1. Alcance de v1: catálogo rico, sin motor de reglas custom

Resuelto explícitamente: se descartó construir un motor de reglas con lenguaje propio
o código custom ejecutable por el usuario (evaluado y pospuesto por complejidad no
justificada aún — riesgo de sandboxing, validación de código arbitrario). En su lugar,
v1 ofrece un **catálogo ampliado de políticas predefinidas, combinables**, declaradas
por nombre:

```toml
[harnesses.channel-gateway]
retry_policy = "exponential-backoff"
max_retries = 5
backoff_base_ms = 500
circuit_breaker_threshold = 3      # abre el circuito tras N fallos seguidos
circuit_breaker_cooldown_s = 300   # tiempo antes de reintentar tras abrir circuito
```

## 2. Diseño interno: ABC `FailurePolicy`, para no cerrar la puerta a custom después

La clave de diseño, fijada explícitamente aunque no se implemente custom todavía: toda
política de fallo, incluso las predefinidas de v1, se invoca siempre a través de una
misma interfaz — nunca inline en el código que maneja reintentos:

```python
class FailurePolicy(ABC):
    @abstractmethod
    def should_retry(self, failure_history: list[FailureEvent]) -> RetryDecision: ...

class OnFailurePolicy(FailurePolicy): ...
class ExponentialBackoffPolicy(FailurePolicy): ...
class CircuitBreakerPolicy(FailurePolicy): ...
```

Hoy el catálogo de implementaciones es **cerrado** (solo las que Janus mismo
implementa); no existe mecanismo de carga de políticas custom desde afuera. El día que
se decida soportarlo, la extensión es agregar una nueva implementación de
`FailurePolicy` (posiblemente cargada dinámicamente desde un archivo que el usuario
provea) — no hace falta rediseñar el mecanismo de resolución de política, el
ensamblado de toolset, ni la estructura central de `libs/capabilities/`. Esto es lo
único que se fija ahora para que el diseño escale sin comprometer nada de la
implementación actual.

Vive en `libs/capabilities/` (Registro de Capacidades), coherente con el resto de la
lógica de resolución/selección ya definida ahí.

---

## Documentos relacionados
- `stack/07-descubrimiento-y-capacidades.md` — la asignación fija entre harnesses base
  y el Registro de Capacidades, donde vive `FailurePolicy`.
- `stack/06-config-toml-pydantic.md` — el formato y la validación de la configuración
  donde se declaran estas políticas.
