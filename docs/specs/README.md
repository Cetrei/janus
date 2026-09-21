# Specs de implementación de Janus

Cada spec sigue el formato del comando `/spec` del rol Architect y está lista para pasarse a un Implementer. Todas se derivan de `architecture/`, `stack/` y `agents/`, que son la fuente de verdad; si una spec contradice esos documentos, se corrige la spec o se abre una decisión explícita.

Estado: **18 de 18 escritas** (2026-09-20). El kanban se construye a partir de ellas (`../../TODO.md`, sección 2).

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
| 15 | [spec-15-spoke-adapters.md](spec-15-spoke-adapters.md) | `libs/adapters/.../spokes/` | 4, 10, 11, 12, 14, 16, 17 | Adaptadores concretos, incluye el híbrido de visión para GUI. Entrega incremental. |
| 16 | [spec-16-platform.md](spec-16-platform.md) | `libs/platform/` | nada (stdlib; `psutil` opcional) | Aislamiento de diferencias Linux/Windows. Prerrequisito, se implementa junto a la 1. |
| 17 | [spec-17-instances-and-usage.md](spec-17-instances-and-usage.md) | pools de instancias, `Control.SetSpokeAvailability` | 4, 9, 11, 12, 15, 16 | Absorción generalizada y multiplataforma de Relay/`claude-toolkit`. |
| 18 | [spec-18-biometrics.md](spec-18-biometrics.md) | `libs/biometrics/` | 2, 11, 13, 16 | Verificación local de voz y cara, capa opcional de identidad. |

Paralelizable: las specs 2, 3, 6, 8, 12, 13 y 16 no dependen entre sí y pueden implementarse a la vez tras la 1. La 17 depende de la 15 (`GuiChatAdapterBase`/`ClaudeDesktopAdapter`) y de la 16. La 18 depende de la 13 (convenciones de proveedor y compuerta de rendimiento) y de la 16.

## Cambios respecto al orden original de `TODO.md`

* `proto/` pasa al primer lugar (antes era la sexta): los contratos de adaptador dependen de sus tipos.
* Se agregan dos specs que ningún ítem del TODO cubría y que quedaban sin dueño: la 13 (`libs/voice/`, residual de la pregunta 8 de `architecture/09`) y la 15 (adaptadores concretos de spoke). La 14 incorpora además el puente de canales hacia el núcleo.
* `libs/observability/` y `libs/auth/` pasan a ir antes de `apps/core-gateway/`, porque el núcleo las integra.
* Se agregan tres specs surgidas de un debate posterior al cierre inicial de las 15 (2026-09-20), todas residuales de preguntas ya marcadas RESUELTAS en `architecture/09`: la 16 (`libs/platform/`, aislamiento Linux/Windows, requerido porque Relay se absorbe multiplataforma), la 17 (absorción de Relay/`claude-toolkit`: pools de instancias, disponibilidad manual, sondeo de uso de cuota) y la 18 (`libs/biometrics/`, residual de la pregunta 14). La spec 15 se extiende con `VisionAgentAdapter`, híbrido con el árbol de accesibilidad de la spec 12.

## Decisiones tomadas en las specs que extienden a `docs/`

Estas decisiones no estaban fijadas en `architecture/`, `stack/` ni `agents/`. Las que están marcadas como **propuesta** necesitan confirmación del usuario antes de considerarse cerradas.

| Decisión | Spec | Estado |
|---|---|---|
| Ubicación de agentes: `config/agents/<Nombre>/`; catálogo compartido en `config/catalog/` | 02 | Confirmada |
| Paquetes con prefijo `janus` en todos los lenguajes (`janus_*` en Python, `janus-*` en Rust, `@janus/*` en TypeScript); Python 3.11 o superior | 02, 04 | Confirmada (ver `stack/02` sección 4) |
| Un workspace por ecosistema: `uv` (Python), Cargo (Rust) y bun (TypeScript), cada uno con su lockfile en la raíz | todas | Confirmada (ver `stack/02` sección 3). Bun frente al fork de OpenClaw, por validar en la fase 0 de la spec 14 |
| Runtimes por ecosistema: `uvicorn` (Python, superficies HTTP), Bun (TypeScript, runtime y gestor), Cargo (Rust) | 11, 14 | Confirmada (ver `stack/02` sección 3.1). Bun frente al fork de OpenClaw y al streaming gRPC, por validar en la fase 0 de la spec 14 |
| Paquete proto `janus_proto.v1` (directorio `proto/janus_proto/v1/`), sin namespace `janus`, que colisiona con un paquete de PyPI | 01 | Decidido en la spec |
| `DependencyFailurePolicy` eliminado de `task.proto` y de la tabla `tasks` (lo reemplaza `DependencyFailureTriage`, spec 11) | 01, 03 | Corrección de una inconsistencia con la pregunta 10 |
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
| Vigencia de la verificación por secreto compartido: `owner_reverify` con `never`, `per_message`, `per_session` o `ttl`, configurable por canal; el núcleo reinyecta la información en el prompt cuando vence | 02, 11 | Mecanismo confirmado; default `per_session` elegido por el Architect, revisable |
| Política de aprobación con cuatro valores: `ask_everytime`, `ask_once_per_session`, `allow_always`, `deny_always` | 02, 09 | Confirmada |
| `SessionHub` vive en `libs/reasoning-engine` | 10 | Decidido en la spec |
| Detección de GUI por árbol de accesibilidad AT-SPI; backends intercambiables (residual de la pregunta 11) | 12 | Enfoque confirmado; librerías concretas por validar en el spike |
| `libs/voice/` como librería propia; voz como capacidad del núcleo | 13 | Decidido en la spec |
| `channel-gateway` es cliente gRPC del núcleo; su `port` es solo el endpoint de salud | 14 | Decidido en la spec |
| Adaptadores concretos dentro de `libs/adapters` con extras opcionales | 15 | Decidido en la spec |
| Gemini Desktop diferido; su capacidad se cubre con `ApiModelAdapter` | 15 | Decidido en la spec |
| Relay/`claude-toolkit` no se conserva ni se porta: se absorbe generalizado y multiplataforma (pools de instancias, `UsageProbe`, disponibilidad manual) | 17 | Confirmada |
| Una sola librería `libs/platform/` en vez de ramas por sistema operativo repetidas en cada spec | 16 | Decidido en la spec |
| Todo proceso hijo se lanza por `Popen` en un hilo (`janus_platform.spawn`), nunca `asyncio.create_subprocess_exec`, por la exigencia de `Proactor` en Windows | 16 | Decidido en la spec |
| Biometría: modelos livianos sin LLM (YuNet, SFace, MiniFASNet, WeSpeaker), verificación uno a uno del dueño, local por defecto con nube opt-in explícito | 18 | Confirmada |
| GUI híbrida: se implementa primero la estrategia (accesibilidad o visión) que resulte más rápida de dejar funcionando según el spike de la spec 12; la otra queda para una actualización posterior | 15 | Confirmada |
| `CoreGateway` gana `request_approval`, `get_state` y `put_state` para que los adaptadores GUI y de visión persistan perfiles asistidos y pidan aprobación sin acoplarse a `ApprovalGateway` directamente | 4, 11 | Decidido en la spec, cierra un hueco entre las specs 04 y 12 |

## Correcciones detectadas al verificar tecnologías (septiembre de 2026)

* `filesystem-mcp-rs` ya trae `delete_path` recursivo, `copy_file` y `edit_file` con diff y dry run; el delta real del fork es menor de lo que dicen `stack/02` y `agents/03`. Su licencia no se pudo verificar y es bloqueante (spec 08).
* Kokoro por ONNX puede ser más lento que tiempo real en un Raspberry Pi; `agents/05` lo daba por viable. Se agrega una compuerta de rendimiento (spec 13).
* Claude Desktop tiene beta oficial en Linux desde el 30 de junio de 2026 (Ubuntu y Debian, x86_64 y arm64); Gemini Desktop está documentado solo para macOS y Windows. Afecta a la spec 12 y la 15.
* Raspberry Pi OS usa Wayland (`labwc`) por defecto; la automatización de GUI no puede asumir X11 (spec 12).
* Las remote plugins de `buf` exigen conexión con la BSR; de ahí el código generado commiteado (spec 01).
* `sqlite-vec` es pre v1 (0.1.x) y hubo problemas con wheels aarch64 en versiones previas (specs 03 y 07).
* Existe un paquete `janus` en PyPI (cola sync/async de aio-libs) cuyo módulo `janus` colisionaría con un namespace `janus` propio. Se evitó nombrando el paquete proto `janus_proto.v1` (spec 01).
* `intfloat/multilingual-e5-small` no figura en la lista integrada de modelos de `fastembed` (se registra con `TextEmbedding.add_custom_model`), y la spec 07 afirmaba lo contrario. `intfloat/multilingual-e5-large` (1024 dimensiones) sí figura, y `fastembed` corrigió su pooling (PR 445), así que hay que fijar una versión que lo incluya. La GPU exige el paquete aparte `fastembed-gpu` (specs 02 y 07).
* Biometría (septiembre de 2026): YuNet (detección de cara, ~232 KB, 6.22 ms p95 en CPU de Raspberry Pi) y SFace (embedding, ~38.7 MB, 99.20 ms p95 en la misma CPU) de OpenCV Zoo; MiniFASNetV2/V1SE (liveness, ~4 MB, menor a 10 ms) de Silent-Face-Anti-Spoofing; WeSpeaker ResNet34 en ONNX (verificación de hablante, EER menor a 1.1% en VoxCeleb1-O, pesos con licencia CC BY 4.0 que exige atribución). Ningún modelo de antifalsificación de voz ligero y verificado disponible; v1 de la spec 18 queda sin él y lo compensa con política (voz sola no autoriza control con más de una señal activa).

## Cómo usar estas specs

1. Elegir una spec cuyas dependencias ya estén implementadas.
2. Las specs 8, 10, 12 y 14 empiezan con una fase 0 (auditoría o spike). No se escribe código antes de aprobar su resultado.
3. Crear un checklist desde los requisitos funcionales y marcarlo al avanzar.
4. Levantar dudas antes de codificar. Las **Open Questions** de cada spec listan lo pendiente.
5. Al cerrar una spec, actualizar el estado en `../../TODO.md`.

## Convenciones transversales propuestas

El stack no las fija; se proponen para que las specs sean coherentes entre sí:

* Python 3.11 o superior, un workspace de `uv` con un solo `uv.lock`, `ruff`, `mypy` o `pyright`, `pytest` con `pytest-asyncio` e `import-linter` para los contratos de dependencia.
* Rust estable, un workspace de Cargo, `clippy -D warnings`, `cargo audit` y `cargo deny`.
* Bun como runtime y gestor de paquetes de TypeScript, con workspaces para `packages/` y `apps/channel-gateway` (Bun frente al fork de OpenClaw, por validar en la spec 14). Un paquete que necesite Node lo declara con `engines.node` y `.node-version` y lo lanza con `node`; para `channel-gateway` ese camino ya está aprobado.
* `uvicorn` como servidor de toda superficie HTTP de Python.
* Los estándares de código para contribuidores están en `CODING_STANDARDS.md` (raíz del repositorio). Nombres con la convención nativa de cada lenguaje (`snake_case` en Python y Rust, `camelCase` en TypeScript), coherente con estas specs.
* Todo objetivo numérico de rendimiento es una propuesta que se ajusta tras medir en el hardware objetivo.
* Ninguna spec usa MVC: el proyecto es un sistema de librerías y servicios por capas con puertos (`Protocol`) entre ellas, y esa estructura ya cubre la separación de responsabilidades que MVC buscaría. Ver la nota en `../../TODO.md`.
