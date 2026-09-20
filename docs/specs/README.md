# Specs de implementación de Janus

Cada spec sigue el formato del comando `/spec` del rol Architect y está lista para pasarse a un Implementer. Todas se derivan de `architecture/`, `stack/` y `agents/`, que son la fuente de verdad; si una spec contradice esos documentos, se corrige la spec o se abre una decisión explícita.

Estado: **15 de 15 escritas** (2026-09-19). El kanban se construye a partir de ellas (`../../TODO.md`, sección 3).

## Orden de implementación

El orden va de lo más fundacional a lo más periférico y respeta las dependencias (`proto/` primero, porque los contratos de adaptador dependen de sus tipos).

| # | Spec | Componente | Depende de | Notas |
|---|---|---|---|---|
| 1 | [spec-01-proto.md](spec-01-proto.md) | `proto/`, `libs/proto-py/` | nada | Fuente de verdad del modelo semántico y de los servicios gRPC. |
| 2 | [spec-02-config.md](spec-02-config.md) | `libs/config/` | nada | `janus.toml`, agentes, `requires_restart`, topología de carpetas. |
| 3 | [spec-03-persistence.md](spec-03-persistence.md) | `libs/persistence/` | nada | SQLite, migraciones, esquema de cola y sesiones. |
| 4 | [spec-04-adapters.md](spec-04-adapters.md) | `libs/adapters/` (contratos) | 1 | ABC de adaptador, ciclo de vida, kit de pruebas. |
| 5 | [spec-05-auth.md](spec-05-auth.md) | `libs/auth/` | 3 | Tokens scopeados. |
| 6 | [spec-06-observability.md](spec-06-observability.md) | `libs/observability/` | nada | Logs, ring buffer, Redis, eventos de estado. |
| 7 | [spec-07-memory.md](spec-07-memory.md) | `libs/memory/` | 3 | Memoria de dos niveles con `sqlite-vec`. |
| 8 | [spec-08-filesystem-mcp.md](spec-08-filesystem-mcp.md) | `crates/filesystem-mcp/` | nada | Fork en Rust y skill de uso. Bloqueado por verificar licencia. |
| 9 | [spec-09-capabilities.md](spec-09-capabilities.md) | `libs/capabilities/` | 1, 3 | Registro, selección, `FailurePolicy`, cola, cambio de proveedor. |
| 10 | [spec-10-reasoning-engine.md](spec-10-reasoning-engine.md) | `libs/reasoning-engine/` | 2, 3, 7 | Extracción de Hermes, toolset, sesiones, indexación. Empieza con auditoría. |
| 11 | [spec-11-core-gateway.md](spec-11-core-gateway.md) | `apps/core-gateway/` | 1 a 7, 9, 10 | Orquestador central y superficie de control. |
| 12 | [spec-12-gui-automation.md](spec-12-gui-automation.md) | `crates/gui-automation/` | nada | Rust más PyO3. Empieza con un spike de validación. |
| 13 | [spec-13-voice.md](spec-13-voice.md) | `libs/voice/` | 2 | TTS y STT propios. Tiene compuerta de rendimiento en el Pi. |
| 14 | [spec-14-channel-gateway.md](spec-14-channel-gateway.md) | `packages/channel-gateway-core/`, `apps/channel-gateway/` | 1 | Fork de OpenClaw. Empieza con auditoría. |
| 15 | [spec-15-spoke-adapters.md](spec-15-spoke-adapters.md) | `libs/adapters/.../spokes/` | 4, 10, 11, 12, 14 | Adaptadores concretos. Entrega incremental. |

Paralelizable: las specs 2, 3, 6, 8, 12 y 13 no dependen entre sí y pueden implementarse a la vez tras la 1.

## Cambios respecto al orden original de `TODO.md`

* `proto/` pasa al primer lugar (antes era la sexta): los contratos de adaptador dependen de sus tipos.
* Se agregan dos specs que ningún ítem del TODO cubría y que quedaban sin dueño: la 13 (`libs/voice/`, residual de la pregunta 8 de `architecture/09`) y la 15 (adaptadores concretos de spoke). La 14 incorpora además el puente de canales hacia el núcleo.
* `libs/observability/` y `libs/auth/` pasan a ir antes de `apps/core-gateway/`, porque el núcleo las integra.

## Decisiones tomadas en las specs que extienden a `docs/`

Estas decisiones no estaban fijadas en `architecture/`, `stack/` ni `agents/`. Las que están marcadas como **propuesta** necesitan confirmación del usuario antes de considerarse cerradas.

| Decisión | Spec | Estado |
|---|---|---|
| Ubicación de agentes: `config/agents/<Nombre>/`; catálogo compartido en `config/catalog/` | 02 | Propuesta (resuelve 1.6 del TODO) |
| Paquetes Python con espacio plano `janus_*`; Python 3.11 o superior | 02, 04 | Propuesta |
| Extensión de `proto/` con 5 archivos más (`common`, `session`, `channel`, `spoke`, `gateway`) | 01 | Decidido en la spec |
| Código generado de protobuf commiteado al repo (las remote plugins de buf requieren red) | 01 | Decidido en la spec |
| Tokens: `jns_<id>.<secret>`, SHA 256 con sal (no KDF lento) | 05 | Decidido en la spec |
| Modelo de embeddings configurable (`memory.embedding_model`); default `intfloat/multilingual-e5-large` (1024 dimensiones, CPU) para la PC del usuario; perfil `intfloat/multilingual-e5-small` (384) para el Pi | 02, 03, 07 | Configurabilidad confirmada; default elegido por el Architect bajo la restricción de 32 GB de RAM y 6 GB de VRAM, revisable |
| Tabla vectorial por dimensión (`memory_vec_<dim>`) creada desde una plantilla SQL, en vez de dimensión fija en una migración | 03 | Decidido en la spec (consecuencia de que el modelo sea configurable) |
| Captura de memoria explícita y nada más, sin captura automática ni como opción (residual de la pregunta 2) | 07 | Confirmada |
| Orden salud → política → rol solo para desempate; fallo se maneja con `FallbackChain` declarativa (N pasos del usuario) más `FailureTriageAdvisor` (juicio de Janus, no tabla fija) (residual de la pregunta 1) | 09 | Confirmada |
| Cambio de proveedor: override en `preferences`, no reescribir `agent.toml` | 09 | Decidido en la spec |
| Cascada de dependencias fallidas decidida por Janus en runtime (`DependencyFailureTriage`), no un enum estático (pregunta 10) | 11 | Confirmada |
| Identidad de remitente en capas: pairing del gateway, `identity.owner` por plataforma, secreto compartido en `.md` validado por el agente y biometría local opcional (residual de la pregunta 3) | 02, 11, 14 | Confirmada |
| Política de aprobación con cuatro valores: `ask_everytime`, `ask_once_per_session`, `allow_always`, `deny_always` | 02, 09 | Confirmada |
| `SessionHub` vive en `libs/reasoning-engine` | 10 | Decidido en la spec |
| Detección de GUI por árbol de accesibilidad AT-SPI; backends intercambiables (residual de la pregunta 11) | 12 | Enfoque confirmado; librerías concretas por validar en el spike |
| `libs/voice/` como librería propia; voz como capacidad del núcleo | 13 | Decidido en la spec |
| `channel-gateway` es cliente gRPC del núcleo; su `port` es solo el endpoint de salud | 14 | Decidido en la spec |
| Adaptadores concretos dentro de `libs/adapters` con extras opcionales | 15 | Decidido en la spec |
| Gemini Desktop diferido; su capacidad se cubre con `ApiModelAdapter` | 15 | Decidido en la spec |

## Correcciones detectadas al verificar tecnologías (septiembre de 2026)

* `filesystem-mcp-rs` ya trae `delete_path` recursivo, `copy_file` y `edit_file` con diff y dry run; el delta real del fork es menor de lo que dicen `stack/02` y `agents/03`. Su licencia no se pudo verificar y es bloqueante (spec 08).
* Kokoro por ONNX puede ser más lento que tiempo real en un Raspberry Pi; `agents/05` lo daba por viable. Se agrega una compuerta de rendimiento (spec 13).
* Claude Desktop tiene beta oficial en Linux desde el 30 de junio de 2026 (Ubuntu y Debian, x86_64 y arm64); Gemini Desktop está documentado solo para macOS y Windows. Afecta a la spec 12 y la 15.
* Raspberry Pi OS usa Wayland (`labwc`) por defecto; la automatización de GUI no puede asumir X11 (spec 12).
* Las remote plugins de `buf` exigen conexión con la BSR; de ahí el código generado commiteado (spec 01).
* `sqlite-vec` es pre v1 (0.1.x) y hubo problemas con wheels aarch64 en versiones previas (specs 03 y 07).
* `intfloat/multilingual-e5-small` no figura en la lista integrada de modelos de `fastembed` (se registra con `TextEmbedding.add_custom_model`), y la spec 07 afirmaba lo contrario. `intfloat/multilingual-e5-large` (1024 dimensiones) sí figura, y `fastembed` corrigió su pooling (PR 445), así que hay que fijar una versión que lo incluya. La GPU exige el paquete aparte `fastembed-gpu` (specs 02 y 07).

## Cómo usar estas specs

1. Elegir una spec cuyas dependencias ya estén implementadas.
2. Las specs 8, 10, 12 y 14 empiezan con una fase 0 (auditoría o spike). No se escribe código antes de aprobar su resultado.
3. Crear un checklist desde los requisitos funcionales y marcarlo al avanzar.
4. Levantar dudas antes de codificar. Las **Open Questions** de cada spec listan lo pendiente.
5. Al cerrar una spec, actualizar el estado en `../../TODO.md`.

## Convenciones transversales propuestas

El stack no las fija; se proponen para que las specs sean coherentes entre sí:

* Python 3.11 o superior, un workspace de `uv`, `ruff`, `mypy` o `pyright`, `pytest` con `pytest-asyncio` e `import-linter` para los contratos de dependencia.
* Rust estable con `clippy -D warnings`, `cargo audit` y `cargo deny`.
* Node 22 o superior con `pnpm` para `packages/` y `apps/channel-gateway`.
* Todo objetivo numérico de rendimiento es una propuesta que se ajusta tras medir en el hardware objetivo.
* Ninguna spec usa MVC: el proyecto es un sistema de librerías y servicios por capas con puertos (`Protocol`) entre ellas, y esa estructura ya cubre la separación de responsabilidades que MVC buscaría. Ver la nota en `../../TODO.md`.
