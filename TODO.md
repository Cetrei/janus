# TODO — Janus

El kanban ya existe: GitHub Issues del repo, un épico por spec (20 specs, 20 épicos), cada uno con sus sub-issues. No hay TODO propio que mantener acá, este archivo es solo un puntero para no buscar a ciegas.

## Dónde está el trabajo

- Épicos: label `epico`, uno por spec (`spec:01-...` a `spec:20-...`).
- Prioridad: labels `prioridad:P1` / `P2` / etc.
- Dentro de cada épico, empezar por sub-issues sin dependencias bloqueantes (sección "Depende de" del cuerpo).

## Hito M1 "Home Loop" (decisión del Architect, 2026-09-30)

Primera versión útil sin esperar al núcleo de Janus (specs 2 a 11): luz al llegar, registro de quién entra y sale, comandos de voz para luces. Home Assistant ejecuta las acciones y la voz local (Assist); `libs/presence` aporta el reconocimiento y emite eventos. Detalle y requisitos 40 a 46 en `libs/presence/SPEC.md`, sección "Ampliación 2026-09-30".

Orden:
1. `libs/presence`: el runner, el log JSONL, la página de revisión, `ha_sink.py`, el subcomando `visits`, el stream en vivo y los roles con vocabulario están hechos y confirmados por ejecución (617 passed, `ruff` limpio, 2026-10-01). No quedan pendientes de código en este punto.
2. Ajustar los umbrales con la cámara real desde la página de revisión (son obligatorios en el TOML del runner).
3. Automatización en Home Assistant que escucha el evento `janus_presence` (luz al llegar, con condición de sol). El ejemplo está en el README de `libs/presence` y filtra por `label`; el rol queda como mejora porque no está en el camino crítico. Solo luces, clima y medios; nada de cerraduras ni alarma.
4. Aceptación: llegar frente a la cámara enciende la luz y `events.jsonl` muestra la visita abierta y cerrada.

## Núcleo de Janus (después de M1, en paralelo si hay tiempo)

- Spec 01 (`proto/`): #44 y #45 escritos (2026-09-30), pendiente correr `buf lint` y `buf generate` desde `proto/` sobre los seis `.proto` nuevos (revisados a mano, sin hallazgos) y hacer commit de `proto/` y `libs/proto-py/src/`; #46 (`libs/proto-py` con fachada, helpers, `capability_ids` y tests) escrito el 2026-10-01 y confirmado por ejecución (`pytest` y `ruff` limpios). CI en `.github/workflows/proto.yml` escrito, sin ejecutar. Falta `buf lint` sobre los ocho `.proto` y el commit de `proto/`, `libs/proto-py/` y `.github/`.
- Rol desde la página de revisión (decidido por el Architect, 2026-10-01, requisito 48 de `libs/presence/SPEC.md`): la ruta `/role`, `ReviewBackend.set_role` y el formulario ya están escritos con sus tests (sin ejecutar). El vocabulario `presence.roles` ya se aplica en `set_role` y la página lo muestra como `<select>` (escrito el 2026-10-01, sin ejecutar). Las personas ESTABLISHED no aparecen en la página y eso queda fuera de M1.
- Specs 16, 2, 3, 6, 8, 12, 13: independientes entre sí, pueden ir a la vez tras la 01.
- Spec 20 (IoT) se implementa sobre `McpClientAdapter` apuntando al MCP Server de Home Assistant (decisión 2026-09-29, ver `AGENT.md`).

Ver `AGENT.md` para el estado general y `docs/specs/README.md` para el índice de specs con dependencias.
