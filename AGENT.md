# AGENT.md: Janus

Índice para que una sesión nueva continúe sin releer todo. Mantener al día cuando se tomen decisiones importantes.

## Qué es
Sistema operativo personal de agentes (estrella pura: ningún spoke habla con otro, todo pasa por Janus). Uso personal, un solo host (PC o Raspberry Pi). Licencia MIT, copyright Joanfer.

## Estado (2026-09-20)
Documentación completa. Arquitectura, stack y modelo de agentes cerrados. **15 specs de implementación escritas** en `docs/specs/`. Todas las decisiones propuestas por las specs quedaron confirmadas (2026-09-20). Antes de implementar hay que resolver la colisión entre el namespace `janus` del código generado de protobuf y el paquete `janus` de PyPI (spec 01, Open Questions). Siguiente paso: armar el kanban desde las specs. No hay código todavía.

## Mapa
* `TODO.md`: lista viva. Decisiones pendientes de confirmar (sección 2), estado de las specs (sección 3) y trabajo previo a implementar (sección 4).
* `docs/README.md`: índice de la documentación.
* `docs/architecture/`: arquitectura pura, fuente de verdad. Preguntas abiertas en `09-preguntas-abiertas.md`.
* `docs/stack/`: decisiones de implementación (lenguajes, monorepo, persistencia, proto, harnesses, config, seguridad).
* `docs/agents/`: modelo de agentes (memoria, skills, orquestación, voz, concurrencia).
* `docs/specs/`: una spec por componente. Índice, orden y tabla de decisiones propuestas en `docs/specs/README.md`.
* `docs/_deprecated/`: material archivado (ADRs retirados por decisión del usuario). No se usa.

## Decisiones vigentes clave
* Núcleo: un solo proceso Python asyncio (`apps/core-gateway`). Harnesses base: Hermes extraído a `libs/reasoning-engine`, OpenClaw forkeado en `packages/channel-gateway-core`.
* Contratos: ABC en Python, modelo semántico en protobuf con `buf`, código generado commiteado.
* Persistencia: SQLite sin ORM (`aiosqlite`), migraciones `.sql`, `sqlite-vec` para memoria. Redis solo para lo efímero.
* MVC evaluado y descartado: el proyecto es una arquitectura por capas con puertos.
* Monorepo con un workspace por ecosistema (`uv`, Cargo, bun), cada uno con su lockfile en la raíz, y prefijo `janus` en todos los paquetes (`janus_*`, `janus-*`, `@janus/*`). Detalle en `docs/stack/02-monorepo.md` secciones 3 y 4.

## Preguntas abiertas que las specs no resuelven
Ninguna. Las cuatro residuales de `architecture/09` (5 OpenClaude, 9 multi-usuario, 12
GUI de fábrica, 13 Relay) se cerraron en la sesión del 2026-09-20; ver el propio
documento y TODO.md sección 2bis para el detalle. Quedan solo residuales de
implementación derivados de esas respuestas (spec de reemplazo de Relay aún sin
escribir; diseño de concurrencia interna de Janus en spec 11).

## Bloqueos y fases 0
* Spec 08: verificar la licencia de `ssoj13/filesystem-mcp-rs` antes de forkear.
* Specs 10, 12 y 14 empiezan con auditoría o spike; no escribir código antes de aprobar su resultado.
* Spec 13: medir Kokoro en el Raspberry Pi (`bench`) antes de comprometer la voz local.

## Última sesión (2026-09-20)
Se corrigió spec 09: el residual de la pregunta 1 de `architecture/09` no era un enum
cerrado (`fallback`/`block`/`ask`) sino dos piezas separadas — una `FallbackChain`
declarativa de N pasos que el usuario define, y un `FailureTriageAdvisor` que es un
juicio de Janus en runtime sobre si seguir la cadena o escalar al usuario, no una tabla
fija. Se cerraron las cuatro preguntas que quedaban abiertas en `architecture/09`:
política de seguimiento de OpenClaw (sin cadencia fija, solo ante disparador), OpenClaude
(nunca se extiende, solo consumo como spoke), multi-usuario (redefinida como
concurrencia interna de Janus por canales, no multi-tenencia), alcance de GUI de fábrica
(genérico más adaptadores adicionales a definir) y futuro de Relay (se rehace su función
desde cero como spoke propio de Janus, portable, reemplazando a `claude-toolkit`).
Quedan dos residuales de implementación nuevos: la spec del spoke que reemplaza a Relay
(sin número aún) y el diseño de concurrencia interna de Janus en spec 11.

## Segunda ronda de la sesión (2026-09-20): decisiones de las specs confirmadas
Se cerraron seis decisiones propuestas por las specs:
* **Captura de memoria (spec 07)**: solo explícita. Janus y sus subagentes guardan con
  `remember` por decisión propia o pedido del usuario; no hay captura automática ni como
  opción (se eliminó el hook `on_task_completed` y `memory.auto_capture`).
* **Identidad de remitente (specs 02, 11, 14)**: identificador por plataforma por defecto,
  más un secreto compartido opcional en un `.md` libre que el agente valida llamando a
  `mark_sender_verified`. El núcleo evalúa la vigencia antes de cada llamada a Janus
  (`owner_reverify`: `never`, `per_message`, `per_session` o `ttl`, default `per_session`)
  y, si la verificación falta o venció, inyecta en el prompt el estado, el `.md` y la
  instrucción de comprobar la identidad (spec 11, requisito 26bis). Se agregaron
  `owner_reverify`, `owner_reverify_ttl` y `owner_challenge_file` a la config por canal
  (spec 02). El default `per_session` lo eligió el Architect y es revisable.
* **Approval (specs 02, 09, `agents/06`)**: cuatro valores, `ask_everytime`,
  `ask_once_per_session`, `allow_always`, `deny_always`.
* **Cascada por dependencia fallida y detección de GUI**: ya estaban resueltas en las
  specs 11 y 12 y en `architecture/09`; solo faltaba marcarlas en `TODO.md`.
* **Embeddings (specs 02, 03, 07)**: el modelo es configurable y el default se elige para
  la PC del usuario (32 GB de RAM, 6 GB de VRAM), no para el Pi. Default:
  `intfloat/multilingual-e5-large` (1024 dimensiones, CPU); perfil Pi:
  `intfloat/multilingual-e5-small` (384). El modelo concreto lo eligió el Architect bajo la
  restricción del usuario y es revisable.
* **Consecuencia estructural en la spec 03**: la tabla vectorial ya no tiene dimensión fija
  en una migración. Se crea por dimensión (`memory_vec_<dim>`) con
  `Database.ensure_vec_table(dim)` desde una plantilla `.sql.tmpl`; el cambio de modelo
  re embebe y descarta la tabla anterior solo si todo salió bien.
* **Corrección verificada**: `multilingual-e5-small` no está en la lista integrada de
  `fastembed` (requiere `add_custom_model`); `multilingual-e5-large` sí.

## Tercera ronda de la sesión (2026-09-20): estructura del monorepo
* **Workspaces (`stack/02` sección 3)**: un workspace por ecosistema, `uv` (Python),
  Cargo (Rust) y bun (TypeScript), cada uno con su lockfile en la raíz. Puntos por
  validar en fases 0: bun frente al fork de OpenClaw, que es un workspace `pnpm` propio
  con Node 22 (spec 14, requisito 4bis), y `crates/gui-automation` como miembro de Cargo
  y de uv a la vez (spec 12).
* **Nombres (`stack/02` sección 4)**: prefijo `janus` en todo. Python `janus-<corto>` e
  import `janus_<corto>`; Rust `janus-<corto>`; TypeScript `@janus/<corto>`, con
  `private: true`. Las carpetas no llevan prefijo. Python mínimo 3.11.
* **Hallazgo**: el paquete `janus` de PyPI (cola sync/async de aio-libs) colisiona con el
  namespace `janus` del código generado de protobuf. Se decide antes de generar código
  (spec 01, Open Questions).
* **`uvicorn`**: el usuario lo mencionó como parte del stack; ninguna spec lo nombraba.
  Queda como verificación de la spec 11 (servidor ASGI del transporte HTTP de MCP).
* **Pendiente detectado, sin corregir**: la spec 01 (`task.proto`) y la spec 03 (columna
  `tasks.on_dependency_failure`) todavía definen el enum estático `DependencyFailurePolicy`
  que la pregunta 10 ya reemplazó por `DependencyFailureTriage` (spec 11).
