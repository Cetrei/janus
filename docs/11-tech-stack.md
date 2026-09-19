# 11 — Tech Stack

## Estado del documento
Primer documento de implementación real de Janus. A diferencia de los documentos 00-10
(arquitectura pura, cero decisiones de lenguaje/framework), este documento fija
lenguaje, runtime, librerías, formato de persistencia, estructura de monorepo y el rol
concreto de cada componente base. Toda decisión aquí fue discutida y confirmada
explícitamente; nada queda a interpretación. Donde algo sigue abierto, se declara así
sin ambigüedad en la sección 14.

Este documento no reemplaza a los documentos 00-10: la arquitectura pura sigue siendo
la fuente de verdad conceptual. Este documento es su encarnación técnica.

---

## 1. Contexto de despliegue (decide todo lo demás)

Janus es un sistema de **uso personal, para una sola persona, corriendo en un solo
host** (PC de escritorio o Raspberry Pi). No está planeado como servicio distribuido,
no requiere alta disponibilidad, no requiere escalado horizontal. Esta restricción es
la que justifica, a lo largo de todo el documento, elegir SQLite sobre Postgres,
proceso único sobre múltiples réplicas, y priorizar bajo consumo de RAM/CPU sobre
capacidad de escala.

---

## 2. Lenguaje y runtime por pieza

| Pieza | Lenguaje | Razón |
|---|---|---|
| `core-gateway` (Core de Traducción + Registro + Persistencia) | Python (asyncio) | Carga de trabajo I/O-bound (proxy/traductor entre spokes), no cómputo pesado. Ecosistema MCP y gRPC maduro en Python. |
| Motor de razonamiento (extracción de Hermes) | Python | Coincide con el lenguaje del núcleo; cero fricción de integración. |
| `channel-gateway` (fork de OpenClaw) | TypeScript | Lenguaje nativo del proyecto forkeado; no se reescribe. |
| GUI automation (pieza de bajo nivel) | Rust | Trabajo potencialmente pesado (captura de pantalla, inyección de eventos de OS); bindings nativos más naturales que en Python puro. Expuesto a Python vía `PyO3`/`maturin`. |
| Contratos de adaptador de spoke | Python, vía `abc` (Abstract Base Classes) | Decisión explícita del usuario: OOP con contratos formales, no duck typing. |

Todo el núcleo (Core de Traducción, Registro de Capacidades, Persistencia Transversal,
motor de razonamiento) corre como **un solo proceso asyncio**, no como microservicios
separados entre sí. La sección 3 explica por qué esto no contradice la filosofía de
monorepo del proyecto.

---

## 3. Filosofía de monorepo: `apps/` vs código por lenguaje

Regla fijada explícitamente por el usuario, sin excepciones:

- **`apps/`** — todo lo que ocupa un tipo de hosting: un proceso desplegable con ciclo
  de vida propio, que escala horizontalmente si hace falta.
- **Código reutilizable por lenguaje, con la convención propia de cada ecosistema**,
  como carpetas de primer nivel (nunca anidadas bajo un genérico `libs/<lenguaje>/`):
  - `libs/` — Python.
  - `crates/` — Rust (convención Cargo).
  - `packages/` — TypeScript/Node (convención de workspaces).
- **`proto/`** — agnóstico de lenguaje, para el modelo semántico compartido (sección 5).
  No es código de ningún lenguaje específico, por eso no vive bajo `libs/`, `crates/`
  ni `packages/`.

Regla de decisión ya no es "microservicios porque sí": es **microservicios solo donde
el código necesita ser un proceso independiente**; todo lo demás (lógica reutilizable
sin necesidad de proceso propio) va como librería importada, sin servidor, sin red de
por medio, sin costo de latencia. Esto se decidió explícitamente tras marcar la
tensión de que "microservicios" no debía significar fragmentar artificialmente las
tres piezas lógicas del núcleo (doc 02) en tres procesos separados.

### Layout completo del monorepo

```
apps/
  core-gateway/            # Python — proceso único: servidor MCP + cliente MCP +
                            # cliente gRPC + orquestador. Importa libs/ como
                            # dependencias internas, sin red de por medio.
  channel-gateway/         # TypeScript — proceso que corre el fork de OpenClaw.
                            # Importa packages/channel-gateway-core.

libs/                      # Python
  reasoning-engine/        # Extracción quirúrgica + refactor del motor de Hermes:
                            # bucle de tool-calling, parsing de function-calls,
                            # routing multi-proveedor de modelos. NO incluye CLI,
                            # dashboard, ni sistema de mensajería de Hermes.
  capabilities/            # Registro de Capacidades. Importado directo por
                            # core-gateway, sin servidor propio.
  persistence/             # Persistencia Transversal: acceso a SQLite vía
                            # aiosqlite, migraciones .sql versionadas.
  adapters/                # Contratos ABC (SpokeAdapter y variantes) +
                            # implementaciones concretas (HermesAdapter si aplica
                            # como spoke externo, OpenClawAdapter, adaptadores de
                            # spokes externos plug-and-play).
  config/                  # Esquema Pydantic + parser TOML. Expone config
                            # validada a cualquier apps/* sin que el consumidor
                            # sepa cómo está guardada en disco.
  auth/                    # Sistema de tokens scopeados: hashing, verificación,
                            # generación.
  observability/           # structlog, rotación de logs, ring buffer en memoria,
                            # publicación a Redis pub/sub.
  proto-py/                # Código Python generado por `buf generate` desde
                            # proto/. Es contrato compartido, no lógica de
                            # core-gateway, por eso vive en libs/ propio aunque
                            # hoy solo core-gateway lo consuma.

crates/                    # Rust
  gui-automation/          # Captura de pantalla, inyección de eventos de OS,
                            # posible OCR/visión. Expuesto a Python vía PyO3.
                            # Abstrae por SO (Linux vía X11/Wayland es la
                            # prioridad real dado el target de Raspberry Pi).

packages/                  # TypeScript
  channel-gateway-core/    # Fork COMPLETO de OpenClaw (no extracción quirúrgica).
                            # Refactorizado únicamente donde Janus necesite
                            # tocarlo para integrarse (config, forma de recibir
                            # instrucciones de Janus), preservando el resto.

proto/                     # Agnóstico de lenguaje — fuente de verdad del modelo
                            # semántico.
  janus/
    v1/
      semantic.proto       # SemanticRequest, SemanticResponse, tipos base.
      task.proto            # Tareas y dependencias (doc 05).
      capability.proto      # Registro de Capacidades (doc 04).
  buf.yaml                 # Config de buf: lint + breaking change detection.
  buf.gen.yaml              # Config de generación: qué plugin genera qué, hacia
                            # dónde (libs/proto-py/, y futuros packages/*
                            # o crates/* si un SDK en otro lenguaje lo requiere).

config/
  janus.toml               # Config raíz: harnesses embebidos, spokes externos,
                            # puertos, políticas de fallo, políticas de selección.
                            # TOML, no YAML (ver sección 7).

docs/                       # Este árbol de documentos (00-11 y los que sigan).
```

---

## 4. Persistencia

### 4.1 Motor: SQLite, no Postgres

Decisión fijada explícitamente tras comparar ambos: para una persona, un solo host, un
solo proceso escritor, SQLite gasta menos recursos y es estrictamente más simple que
Postgres, sin perder nada que Janus vaya a necesitar. Postgres exigiría un proceso
servidor aparte con RAM base propia (administración de usuarios, conexiones, backups)
que no se justifica en un Raspberry Pi para una sola persona. El límite real de SQLite
(un solo escritor concurrente) nunca se toca porque `core-gateway` es, por diseño, el
único proceso que escribe.

### 4.2 Acceso: sin ORM, control total

Decisión explícita del usuario: **SQL crudo vía `aiosqlite`** (driver async, se
integra directo al event loop de `core-gateway` sin bloquear), sin SQLAlchemy, sin
SQLModel, sin query builder. Cada query vive como una función Python explícita en
`libs/persistence/`, con el SQL visible directamente en el código — nada de
abstracción intermedia que traduzca objetos a SQL por el desarrollador.

### 4.3 Migraciones: archivos `.sql` versionados, no strings hardcodeados

Requisito explícito del usuario: nunca un string de SQL embebido sueltamente en código
Python. Cada cambio de esquema vive en su propio archivo `.sql` numerado:

```
libs/persistence/migrations/
  0001_init.sql
  0002_tasks.sql
  0003_capabilities.sql
  ...
```

Runner de migraciones: minimalista y propio (dado el requisito de "control total"), en
vez de una dependencia externa como Alembic o yoyo-migrations — lee los archivos en
orden, lleva registro de cuáles ya se aplicaron, sin imponer ningún ORM.

### 4.4 Estructuras de datos y complejidad algorítmica

Distinción explícita que quedó fijada: la complejidad algorítmica (O(1), O(log n),
O(n log n)) que el usuario pidió **no la provee el motor SQL en sí** — SQLite modela un
grafo dirigido (p. ej. dependencias de tareas del doc 05) como una tabla de aristas
(`task_id`, `depends_on_id`) con índice B-tree, dando búsquedas O(log n). La
complejidad real de recorrido de grafos (topological sort, detección de ciclos) se
controla en la capa de lógica, no en SQL:

- El subconjunto de grafo relevante se carga a memoria como estructura real (dict de
  adyacencia) al arrancar o al tocar una tarea.
- Los algoritmos de grafo (Kahn's algorithm o DFS) corren en memoria, en Python puro
  para v1 — esto sí es O(V+E) real.
- SQLite es la capa de persistencia/respaldo de ese grafo, nunca el motor de cómputo.
- Optimización futura, explícitamente no prematura: si el grafo real demuestra ser
  cuello de botella, se extrae ese cálculo a un `crate` de Rust vía `PyO3`, no antes.

### 4.5 Redis: capa rápida efímera

Redis complementa a SQLite, no lo reemplaza. Usos fijados:

- Canal pub/sub para la superficie de observabilidad push (doc 07).
- Stream en memoria de logs hacia una futura interfaz (ver sección 11).
- Estado efímero: sesiones activas en curso, locks.
- Estado de conexión de spokes externos registrados dinámicamente (ver sección 8),
  cuando ese estado no necesita sobrevivir a un reinicio del sistema.

No es almacén de verdad — todo lo que debe sobrevivir reinicios y ser fuente de verdad
va a SQLite.

---

## 5. Modelo semántico: Protocol Buffers como fuente de verdad única

### 5.1 Por qué protobuf y no dataclasses a mano

Discutido explícitamente: el modelo semántico interno de Janus (lo que el Core de
Traducción usa para representar una solicitud/respuesta independiente de cualquier
spoke) no se ancla a MCP ni a ningún protocolo externo — sería una dependencia
conceptual hacia un spoke particular, violando el principio de que Janus no se adapta
a lo existente, sino que ofrece su propio modelo y facilita que otros se adapten a él
(vía SDK).

Protocol Buffers se eligió como formato de esa fuente de verdad porque:

- Ya está en el stack por necesidad de gRPC (comunicación con harnesses/spokes que
  hablan gRPC).
- Permite generar código para múltiples lenguajes (Python, TypeScript, Rust) desde una
  única definición, sin riesgo de que los SDKs se desincronicen entre sí — el riesgo
  real de mantener "una fuente de verdad a mano por lenguaje".

### 5.2 Herramienta: `buf`

`buf` gestiona lint y detección de breaking changes sobre los `.proto`, y genera el
código hacia cada consumidor (hoy: `libs/proto-py/`; en el futuro, cualquier SDK en
otro lenguaje que Janus decida ofrecer a integradores externos).

### 5.3 Ubicación: `proto/`, no dentro de ningún `libs/`/`crates/`/`packages/`

Un `.proto` no es código de ningún lenguaje de programación — es un lenguaje de
definición de esquema neutral (IDL). Meterlo dentro de una carpeta que por convención
implica un ecosistema de lenguaje específico (Cargo, npm) rompería esa convención. Por
eso `proto/` vive en la raíz del monorepo, como el resto de convenciones ya fijadas.

---

## 6. Harnesses base: Hermes y OpenClaw

Distinción fundamental que quedó fijada tras discusión extensa: **harnesses base** son
infraestructura fija que Janus necesita para ser Janus (considerados desde el diseño,
siempre presentes, aunque desacoplados en código vía ABC) — no son candidatos que
compiten dinámicamente por una capacidad, a diferencia de los **spokes externos**
(Claude Desktop, Gemini Desktop, u otros modelos/asistentes que el usuario conecta y
desconecta libremente para sus tareas).

### 6.1 Hermes → extracción quirúrgica + refactor, no fork completo

**Decisión final, tras descartar dos alternativas más agresivas** (usar Hermes como
servicio externo consultado por capacidad; forkear el repo de Hermes completo 1:1):

Se extrae del código de Hermes (`NousResearch/hermes-agent`, MIT license, confirmado
compatible con fork/modificación/redistribución):

- El bucle de tool-calling y razonamiento del agente (ejecutar herramientas,
  interpretar resultados, iterar).
- El routing multi-proveedor de modelos (200+ modelos vía OpenRouter, Anthropic,
  OpenAI, DeepSeek, etc.).
- El sistema de skills como mecánica (cómo se guardan, cargan, relacionan a un
  dominio) — no necesariamente su learning loop automático completo si complica el
  control.

**Explícitamente NO se trae:**
- CLI de Hermes.
- Dashboard de Hermes.
- Sistema de mensajería/gateway de Hermes (los canales son territorio exclusivo de
  `channel-gateway`/OpenClaw, ver sección 6.3).
- Voice mode de Hermes (TTS/STT propios) — la voz es territorio exclusivo de Janus
  (ver sección 6.3). Nota técnica registrada durante la discusión: el `text_to_speech`
  de Hermes hoy solo acepta texto y ruta de salida, sin control de tono/emoción/ritmo
  — limitación real que refuerza por qué Janus no debe depender de ese subsistema para
  su propia capa de voz expresiva.
- Cualquier noción de sesión-por-chat o identidad de agente atada a plataforma de
  mensajería.

**Motivo del criterio de corte:** lo que Janus sabe que va a tocar recurrentemente
(identidad, config, forma de invocar el motor) se refactoriza ahora a esquema propio
(Pydantic + TOML); lo que se mantiene estable y ya está probado en producción por
terceros (algoritmo de tool-calling, parsing de function-calls, routing a proveedores)
se deja lo más intacto posible.

**Resultado:** vive en `libs/reasoning-engine/` como **librería interna** de Janus, no
como spoke externo ni como proceso separado. El Core de Traducción lo trata como
traduciría hacia cualquier spoke — solo que este "spoke" es código en el propio
monorepo, no un proceso externo.

### 6.2 OpenClaw → fork total, en `packages/channel-gateway-core/`

**Decisión final, con criterio explícitamente distinto al de Hermes:** OpenClaw se
forkea completo porque su rol es acotado y ya coincide 1:1 con lo que Janus necesita
(gateway de canales desacoplado de lógica de agente), sin partes muertas que compitan
con el diseño de Janus. OpenClaw nunca decide personalidad ni razona — solo transporta
— por lo que no hay riesgo de que su sesión/identidad interna choque con la capa de
identidad de agentes que Janus construye por su cuenta.

Refactor limitado únicamente a lo que Janus necesite tocar para integrarse (config,
forma de recibir instrucciones desde `core-gateway`), preservando el resto del
comportamiento de gateway multi-canal tal cual.

Corre como su propio proceso: `apps/channel-gateway/` (TypeScript), importando
`packages/channel-gateway-core/`.

### 6.3 División de responsabilidades — regla explícita, sin excepciones

Esta tabla es la regla operativa fijada tras corregir un malentendido en la discusión
(no confundir "quién soporta técnicamente algo" con "quién lo posee en Janus"):

| Responsabilidad | Dueño | Notas |
|---|---|---|
| Razonamiento/ejecución de tareas de código | `libs/reasoning-engine/` (ex-Hermes) | Nunca habla directo al usuario, nunca conoce canales ni voces. |
| Routing a proveedores de modelo | `libs/reasoning-engine/` (ex-Hermes) | Ya resuelto por el motor extraído; Janus decide qué agente usa qué configuración de routing. |
| Credenciales y conexión a canales (WhatsApp, Discord, Telegram, etc.) | `channel-gateway` (fork de OpenClaw) | Puro transporte: recibe texto/audio ya generado por Janus y lo entrega; recibe del canal y lo pasa a Janus. |
| Síntesis de voz (TTS) y reconocimiento (STT) | Janus (`core-gateway` + librería propia a definir) | Janus decide qué proveedor de TTS/STT invocar y con qué parámetros, incluso si ese proveedor es uno que Hermes también soporta (ElevenLabs, OpenAI TTS, NeuTTS) — la invocación es de Janus, no una feature activada dentro de Hermes. |
| Identidad/personalidad persistente por agente | Janus (sistema agéntico propio, ver sección 14) | No existe hoy en el motor extraído de forma rica. |
| Qué agente responde en qué canal, con qué voz | Registro de Capacidades + Core de Traducción (`core-gateway`) | Ver sección 9. |
| GUI automation | `crates/gui-automation/` (Rust) + orquestación en `core-gateway` | Ver sección 13. |

**Flujo de referencia para un mensaje entrante** (ejemplo, WhatsApp, con síntesis de
voz activa para ese agente):

```
Usuario → channel-gateway (OpenClaw, recibe)
        → core-gateway: Core de Traducción
        → core-gateway: Registro de Capacidades decide qué agente/tarea aplica
        → libs/reasoning-engine (ex-Hermes) genera la respuesta de texto
        → core-gateway: Core de Traducción
        → Janus sintetiza voz (si el agente tiene voz activa)
        → channel-gateway (OpenClaw, entrega texto y/o audio)
```

### 6.4 Política de mantenimiento del fork frente a upstream

Resuelto tras evaluar explícitamente el valor real de seguir los cambios de
`NousResearch/hermes-agent`, dividido por área (no es parejo en toda la superficie del
proyecto):

- **Alto valor de seguir de cerca:** routing multi-proveedor de modelos (área de mayor
  tasa de cambio real — proveedores nuevos, APIs que cambian, modelos deprecados) y
  advisories de seguridad sobre el bucle de tool-calling/ejecución (superficie de
  ataque real: inyección de prompt que escala a ejecución arbitraria).
- **Bajo o nulo valor de seguir:** todo lo explícitamente no extraído (CLI, dashboard,
  mensajería, voice mode), y el sistema de skills en la medida en que Janus termine
  divergiendo de su diseño original (el learning loop automático completo no se trajo
  tal cual, ver 6.1).

**Proceso fijado:** no merge automático ni seguimiento en tiempo real del repo
completo. Revisión periódica (cadencia mensual) filtrada a dos fuentes: el changelog/
releases de `hermes-agent` en busca de (a) nuevos proveedores de modelo soportados y
(b) advisories de seguridad. Cuando algo relevante aparece, se evalúa puntualmente si
aplica al fork ya refactorizado — típicamente portado a mano en vez de mergeado
directo, dado que la estructura ya diverge del original.

---

## 7. Configuración: TOML + Pydantic

### 7.1 Formato: TOML, no YAML

Decisión explícita tras comparar: TOML es más estricto y menos propenso a errores de
parseo silenciosos que YAML (se evita, p. ej., el problema histórico de YAML
interpretando `no` como booleano). TOML además es consistente con el ecosistema que
Janus ya usa (Rust/Cargo, `pyproject.toml` de Python).

### 7.2 Validación: Pydantic

Equivalente directo, en Python, al patrón "Zod" mencionado durante la discusión:
esquema tipado que valida el TOML cargado, con fallos tempranos y mensajes claros ante
config inválida.

### 7.3 Filosofía: config es lo que el usuario declara; SQLite es lo que el sistema genera

Distinción explícita: los harnesses base (qué existen, en qué puerto, qué política de
fallo) son **configuración declarada por el usuario** — nunca estado que el sistema
descubre y persiste solo. Mezclar ambos hubiera sido un error. El estado dinámico que
el sistema sí genera (spokes externos registrados en runtime, tokens emitidos) va a
SQLite/Redis, no a `config/janus.toml`.

### 7.4 Ubicación y consumo

`libs/config/` expone la config validada a cualquier `apps/*` que la necesite, sin que
el consumidor sepa si por debajo es TOML, YAML o cualquier otro formato — cumpliendo
el requisito explícito de "que todas las partes puedan manipularlo sin saber cómo está
guardado".

### 7.5 Filosofía general: el usuario tiene el control sobre todo

Principio explícito que atraviesa config, puertos, y políticas: nada crítico queda
hardcodeado si el usuario puede querer editarlo. Puertos de harnesses, políticas de
fallo, y (a futuro) políticas de selección son todos editables vía `config/janus.toml`.

---

## 8. Descubrimiento de spokes: dos mecanismos, según el tipo

### 8.1 Harnesses base (Hermes extraído, OpenClaw forkeado): conectados por Janus mismo

Janus los necesita para ser Janus — no esperan a anunciarse, Janus los arranca/importa
directamente. Configurados en `config/janus.toml` bajo secciones propias:

```toml
[harnesses.reasoning-engine]
# configuración del motor de razonamiento extraído

[harnesses.channel-gateway]
port = 8090
timeout_ms = 5000
retry_policy = "on-failure"
max_retries = 3
```

### 8.2 Spokes externos: se presentan ante Janus vía endpoint de registro

Un spoke externo (Claude Desktop, Gemini Desktop, u otro que el usuario decida
conectar) declara quién es y qué capacidades ofrece contra un endpoint expuesto por el
Core de Traducción (`POST /register` o su equivalente en MCP/gRPC, según el transporte
del spoke). Esta conexión activa es estado dinámico:

- Si necesita sobrevivir un reinicio de Janus: SQLite.
- Si es puramente efímera para la sesión actual: Redis.

Los spokes externos requieren, además, presentar un token propio al registrarse (ver
sección 10) — a diferencia de los harnesses base, que usan el token default interno.

### 8.3 Redundancia entre harnesses base: asignación fija, no arbitraje dinámico

Fijado explícitamente: si dos harnesses base pudieran técnicamente ofrecer la misma
capacidad (ejemplo hipotético discutido: conectividad de canal), **no existe
arbitraje dinámico entre harnesses base**. La asignación es una decisión de diseño
humana, declarada una vez en `config/janus.toml` (un dueño único y explícito por
capacidad de harness base). Qué pasa si ese dueño falla se resuelve con política de
fallo/reintento (sección 12), nunca con competencia en runtime. Esto es consistente
con que los harnesses base sean infraestructura fija y conocida de antemano, sin
ambigüedad por diseño.

---

## 9. Registro de Capacidades: alcance acotado a spokes externos

Corrección explícita respecto al planteo original del doc 04: la resolución de
capacidad con política de selección (qué hacer si más de un candidato puede resolver
la misma solicitud) **aplica únicamente a spokes externos** — fuentes de inteligencia
intercambiables que el usuario conecta para sus tareas. Los harnesses base nunca
compiten entre sí (ver 8.3); no son candidatos en el sentido del doc 04.

Vive en `libs/capabilities/`, importado directo por `core-gateway`, sin servidor
propio ni red de por medio (justificado por ser un solo host, un solo proceso).

La política de selección entre spokes externos candidatos se declara en
`config/janus.toml` (prioridad explícita por spoke, o una policy nombrada), nunca
hardcodeada ni improvisada en runtime.

---

## 10. Seguridad: tokens scopeados

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

---

## 11. Logs y observabilidad

Decisión explícita: logs centralizados, con el mismo criterio que config (una sola
fuente, consumida por todas las partes sin que sepan el detalle de implementación).

- **`structlog`** para logging estructurado (JSON lines) — estándar de facto en Python
  para esto.
- **Rotación** en disco vía `RotatingFileHandler` (por tamaño) o `TimedRotatingFileHandler`
  (por tiempo).
- **Ring buffer en memoria** de tamaño acotado (`collections.deque(maxlen=N)`) que
  alimenta un stream en vivo.
- **Publicación vía Redis pub/sub**, para que cualquier cliente (una futura GUI, ver
  doc 07) se suscriba al stream de logs sin acoplarse directamente al proceso de
  `core-gateway`.

Vive en `libs/observability/`.

---

## 12. Políticas de fallo: catálogo rico predefinido, diseñado para escalar a custom

Estilo de nomenclatura tomado explícitamente de Docker (`restart: on-failure`,
`restart: always`, `restart: never`) por ser un vocabulario ya conocido y fácil de
razonar. Declaradas en `config/janus.toml`, con default global y override por
harness/spoke.

### 12.1 Alcance de v1: catálogo rico, sin motor de reglas custom

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

### 12.2 Diseño interno: ABC `FailurePolicy`, para no cerrar la puerta a custom después

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

## 13. Automatización de interfaz gráfica (doc 10)

Decisión explícita: dividido entre Rust y Python, no resuelto enteramente en un solo
lenguaje.

- **`crates/gui-automation/` (Rust)**: trabajo pesado de bajo nivel — captura de
  pantalla, inyección de eventos de input a nivel de OS, posiblemente OCR/visión si
  hace falta. Expuesto como extensión nativa a Python vía `PyO3`/`maturin`.
- **`core-gateway` (Python)**: orquesta la lógica de alto nivel — qué acción tomar,
  cuándo, en respuesta a qué tarea — llamando a la extensión Rust.
- **Multiplataforma real**: como el target incluye Raspberry Pi (Linux), el crate
  necesita abstraer por sistema operativo; Linux vía X11/Wayland es la prioridad real,
  no un caso secundario.

El detalle fino de esta pieza (qué biblioteca exacta de Rust, cómo se abstrae por SO)
queda explícitamente diferido a la fase de `/spec` de este componente específico, por
ser relativamente aislado del resto del núcleo.

---

## 14. Explícitamente diferido (no decidido en este documento)

Estos puntos surgieron durante la discusión de tech-stack pero se marcaron
explícitamente como fuera de alcance de este documento, para no contaminar el stack ya
maduro con decisiones apresuradas:

1. **Sistema agéntico completo de Janus** — RESUELTO, ver `docs/12-modelo-de-agentes-
   de-janus.md`.
2. **Multi-avatar/multi-identidad-visible en un mismo canal** — RESUELTO, ver doc 12,
   secciones 4.3 y 4.4.
3. **Motor de reglas para políticas de fallo extensibles/ejecutables** — RESUELTO en
   cuanto a alcance de v1 y diseño escalable, ver sección 12 de este documento (ABC
   `FailurePolicy`, catálogo cerrado por ahora).
4. **Licencia del propio código de Janus** (abierto o privado) — MIT de Hermes lo
   permite en cualquier caso, pero la elección en sí no se tomó en esta sesión.
5. **Nombre final del archivo de config** — se usó `config/janus.toml` a lo largo de
   este documento por consistencia con la decisión de formato (sección 7), pero no se
   confirmó explícitamente ese nombre de archivo contra el usuario.

El punto de mantenimiento del fork de Hermes frente a upstream, que figuraba aquí
como diferido, también quedó resuelto: ver sección 6.4.

---

## 15. Documentos relacionados

- `00-vision-y-alcance.md` — visión general, alcance funcional.
- `02-arquitectura-estrella-y-contrato-de-integracion.md` — Principios Arquitectónicos
  #1 (estrella pura) y #2 (no-reinvención) que este stack implementa.
- `03-contrato-de-spoke.md` — contrato que `libs/adapters/` implementa vía ABC.
- `04-modelo-de-capacidades-y-enrutamiento.md` — base conceptual de `libs/capabilities/`,
  con el alcance acotado fijado en la sección 9 de este documento.
- `05-modelo-de-roles-y-tareas.md` — base conceptual del grafo de dependencias de
  tareas descrito en la sección 4.4.
- `06-modelo-de-persistencia-y-estado.md` — base conceptual de `libs/persistence/`.
- `07-superficie-para-gui-futura.md` — consumidor futuro del stream de observabilidad
  de la sección 11.
- `08-mapa-de-componentes-reales.md` — inventario original de spokes; este documento
  concreta el tratamiento real de Hermes y OpenClaw dentro de ese mapa.
- `09-preguntas-abiertas.md` — preguntas de arquitectura pura; la sección 14 de este
  documento es su equivalente a nivel de stack.
- `10-automatizacion-de-interfaz-grafica.md` — base conceptual de la sección 13.
