# TODO — Janus

El kanban ya existe: GitHub Issues del repo, un épico por spec (20 specs, 20 épicos), cada uno con sus sub-issues. No hay TODO propio que mantener acá, este archivo es solo un puntero para no buscar a ciegas.

## Dónde está el trabajo

- Épicos: label `epico`, uno por spec (`spec:01-...` a `spec:20-...`).
- Prioridad: labels `prioridad:P1` / `P2` / etc.
- Dentro de cada épico, empezar por sub-issues sin dependencias bloqueantes (sección "Depende de" del cuerpo).

## Hito M1 "Home Loop" (decisión del Architect, 2026-09-30)

Primera versión útil sin esperar al núcleo de Janus (specs 2 a 11): luz al llegar, registro de quién entra y sale, comandos de voz para luces. Home Assistant ejecuta las acciones y la voz local (Assist); `libs/presence` aporta el reconocimiento y emite eventos. Detalle y requisitos 40 a 46 en `libs/presence/SPEC.md`, sección "Ampliación 2026-09-30".

Orden:
1. `libs/presence`: el runner, el log JSONL y la página de revisión ya existen. Falta correr `pytest` sobre `ha_sink.py` (sección `[home_assistant]`, escrita 2026-09-30) y agregar el subcomando `visits`.
2. Ajustar los umbrales con la cámara real desde la página de revisión (son obligatorios en el TOML del runner).
3. Automatización en Home Assistant que escucha el evento `janus_presence` (luz al llegar, con condición de sol o iluminancia). Solo luces, clima y medios; nada de cerraduras ni alarma.
4. Aceptación: llegar frente a la cámara enciende la luz y `events.jsonl` muestra la visita abierta y cerrada.

## Núcleo de Janus (después de M1, en paralelo si hay tiempo)

- Spec 01 (`proto/`): #44 y #45 escritos (2026-09-30), pendiente verificar `buf lint` y regenerar; falta #46 (`libs/proto-py` con fachada, helpers y `capability_ids`).
- Specs 16, 2, 3, 6, 8, 12, 13: independientes entre sí, pueden ir a la vez tras la 01.
- Spec 20 (IoT) se implementa sobre `McpClientAdapter` apuntando al MCP Server de Home Assistant (decisión 2026-09-29, ver `AGENT.md`).

Ver `AGENT.md` para el estado general y `docs/specs/README.md` para el índice de specs con dependencias.
