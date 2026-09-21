# AGENT.md: Janus

Índice para que una sesión nueva continúe sin releer todo. Mantener al día cuando se tomen decisiones importantes.

## Qué es
Sistema operativo personal de agentes (estrella pura: ningún spoke habla con otro, todo pasa por Janus). Uso personal, un solo host (PC o Raspberry Pi). Licencia MIT, copyright Joanfer.

## Estado (2026-09-20)
Documentación y arquitectura completas y cerradas, sin ninguna decisión pendiente. **18 specs de implementación escritas** en `docs/specs/` (índice y tabla de decisiones en `docs/specs/README.md`). Las tres últimas (16 `libs/platform/`, 17 absorción de Relay, 18 `libs/biometrics/`) y la extensión de la 15 con `VisionAgentAdapter` surgieron de un debate posterior al cierre inicial de las 15 originales, todo residual de preguntas ya RESUELTAS en `architecture/09`. No hay código todavía. Ver `TODO.md` para lo único que falta antes y durante la implementación (verificaciones de licencia, spikes de fase 0, y armar el kanban).

## Mapa
* `TODO.md`: lo que falta antes y durante la implementación (estado de las specs y trabajo previo).
* `docs/README.md`: índice de la documentación.
* `docs/architecture/`: arquitectura pura, fuente de verdad. `09-preguntas-abiertas.md` documenta el historial de decisiones (todas RESUELTAS).
* `docs/stack/`: decisiones de implementación (lenguajes, monorepo, persistencia, proto, harnesses, config, seguridad).
* `docs/agents/`: modelo de agentes (memoria, skills, orquestación, voz, concurrencia).
* `docs/specs/`: una spec por componente. Índice, orden y tabla de decisiones propuestas en `docs/specs/README.md`.
* `docs/_deprecated/`: material archivado (ADRs retirados por decisión del usuario). No se usa.
* `CODING_STANDARDS.md`: estándares de código para contribuidores, en inglés. Nombres con la convención nativa de cada lenguaje (`snake_case` en Python y Rust, `camelCase` en TypeScript).

## Decisiones vigentes clave
* Núcleo: un solo proceso Python asyncio (`apps/core-gateway`). Harnesses base: Hermes extraído a `libs/reasoning-engine`, OpenClaw forkeado en `packages/channel-gateway-core`.
* Contratos: ABC en Python, modelo semántico en protobuf con `buf`, código generado commiteado (`janus_proto.v1`, spec 01).
* Persistencia: SQLite sin ORM (`aiosqlite`), migraciones `.sql`, `sqlite-vec` para memoria. Redis solo para lo efímero. Modelo de embeddings default `intfloat/multilingual-e5-large` (Pi: `multilingual-e5-small`).
* MVC evaluado y descartado: el proyecto es una arquitectura por capas con puertos.
* Monorepo con un workspace por ecosistema (`uv`, Cargo, bun), cada uno con su lockfile en la raíz, y prefijo `janus` en todos los paquetes (`janus_*`, `janus-*`, `@janus/*`). Detalle en `docs/stack/02-monorepo.md` secciones 3 y 4.
* Concurrencia interna de Janus: un `AgentRuntime` por `SESSION_KIND_JANUS_MAIN`, aviso selectivo a Janus vía `task_finalize` (regla en código, no juicio de Janus) para no gastar tokens de más, checklist de subtareas en tiempo real sin costo de turno, comunicación entre subagentes siempre mediada por Janus (`request_delegation`). Detalle completo: `docs/specs/spec-11-core-gateway.md`, requisitos 22 y 22bis.
* Aprobación (`ApprovalGateway`): cuatro valores (`ask_everytime`, `ask_once_per_session`, `allow_always`, `deny_always`), reusados también para GUI automation por tipo de acción (spec 12, requisito 22bis).

## Decisiones vigentes clave (continuación)
* Relay (`claude-toolkit`) no se conserva ni se porta: se absorbe de forma generalizada y multiplataforma (Linux y Windows) dentro del núcleo (`PoolCoordinator`, `Control.SetSpokeAvailability`) y `libs/platform`. `libs/platform` concentra toda diferencia Linux/Windows (rutas privadas, locks, procesos, señales) para que el resto del monorepo no tenga ramas por plataforma repetidas (spec 16, spec 17).
* GUI es híbrida por decisión explícita del usuario: entre el árbol de accesibilidad (`REALTIME`, sin modelo) y un adaptador de visión liviano (`VisionAgentAdapter`, con modelo), se implementa primero el que resulte más rápido de dejar funcionando según el spike de la spec 12; el otro queda para una actualización posterior (spec 15, requisito 31bis).
* Biometría (voz y cara) como señal opcional de identidad, local por defecto y configurable a proveedor de nube solo con reconocimiento explícito del usuario (`allow_remote` + `remote_ack`). Modelos livianos sin LLM: YuNet, SFace, MiniFASNet (cara), WeSpeaker ResNet34 (voz). Sin antifalsificación de voz en v1 (spec 18).
* `CoreGateway` (puerto que ve cada adaptador) tiene cuatro métodos más los cuatro originales: `request_approval` (delega en `ApprovalGateway` según política por tipo de acción) y `get_state`/`put_state` (JSON por adaptador en `preferences`, usado hoy por el perfil `ASSISTED` de GUI) (spec 04 requisito 23, spec 11 requisito 32bis).

## Bloqueos y fases 0
* Spec 08: verificar la licencia de `ssoj13/filesystem-mcp-rs` antes de forkear.
* Specs 10, 12 y 14 empiezan con auditoría o spike; no escribir código antes de aprobar su resultado. El spike de la spec 12 decide además cuál estrategia de GUI (accesibilidad o visión) se implementa primero.
* Spec 13: medir Kokoro en el Raspberry Pi (`bench`) antes de comprometer la voz local.
* Spec 18: sin modelos fijados de memoria; correr `bench` y `calibrate` en el hardware objetivo (PC y Raspberry Pi) antes de fijar umbrales de decisión biométrica.
* Spec 17: la comprobación del spike de la spec 12 sobre si Claude Desktop admite varias instancias con `--user-data-dir` distintos decide el valor por defecto de `max_alive` de su pool.
