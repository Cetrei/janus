# TODO — Janus

Arquitectura, tech-stack, modelo de agentes y las **18 specs de implementación**
(`docs/specs/`) están completos y cerrados, sin ninguna decisión pendiente (ver
`AGENT.md`). Este archivo lista solo lo que falta antes y durante la implementación.

Orden de trabajo: documentar todo → specs por componente → kanban → implementación.
Las dos primeras etapas están completas.

---

## 1. Specs de implementación — ESCRITAS

Todas en `docs/specs/` (índice, orden y dependencias en `docs/specs/README.md`).

| # | Spec | Estado |
|---|---|---|
| 1 | `proto/` + `libs/proto-py/` | Escrita |
| 2 | `libs/config/` | Escrita |
| 3 | `libs/persistence/` | Escrita |
| 4 | `libs/adapters/` (contratos) | Escrita |
| 5 | `libs/auth/` | Escrita |
| 6 | `libs/observability/` | Escrita |
| 7 | `libs/memory/` | Escrita |
| 8 | `crates/filesystem-mcp/` | Escrita, bloqueada por verificar licencia del upstream |
| 9 | `libs/capabilities/` | Escrita |
| 10 | `libs/reasoning-engine/` | Escrita, empieza con auditoría de extracción |
| 11 | `apps/core-gateway/` | Escrita |
| 12 | `crates/gui-automation/` | Escrita, empieza con spike de validación |
| 13 | `libs/voice/` (nueva, sin dueño antes) | Escrita, con compuerta de rendimiento en el Pi |
| 14 | `packages/channel-gateway-core/` + `apps/channel-gateway/` | Escrita, empieza con auditoría del fork |
| 15 | Adaptadores concretos de spoke, incluye `VisionAgentAdapter` híbrido | Escrita |
| 16 | `libs/platform/` (nueva, sin dueño antes) | Escrita |
| 17 | Absorción de Relay/`claude-toolkit`: pools de instancias y uso de cuota (nueva, sin dueño antes) | Escrita |
| 18 | `libs/biometrics/` (nueva, sin dueño antes) | Escrita, con compuerta de rendimiento en el Pi |

---

## 2. Trabajo previo a la implementación

- [ ] Verificar la licencia de `ssoj13/filesystem-mcp-rs` (bloqueante de la spec 08) y
      decidir base alternativa si no hay licencia compatible con MIT.
- [ ] Confirmar la licencia del commit de OpenClaw que se forkeará (el README indica
      MIT) y del de Hermes (MIT verificado en el README).
- [x] Escribir la spec de absorción de Relay/`claude-toolkit` (residual de la pregunta
      13 de `architecture/09`): resuelta como spec 17 (pools de instancias, disponibilidad
      manual, `UsageProbe`), no como spoke propio sino generalizada y multiplataforma
      en el núcleo, apoyada en la nueva spec 16 (`libs/platform/`).
- [x] Escribir la spec de biometría local (residual de la pregunta 14 de
      `architecture/09`): resuelta como spec 18 (`libs/biometrics/`), voz y cara,
      local por defecto con nube opt-in explícito.
- [x] Resolver el híbrido de GUI planteado por el usuario (árbol de accesibilidad vs.
      modelo de visión liviano): resuelto en la spec 15 (requisito 31bis,
      `VisionAgentAdapter`). Cuál de las dos estrategias se implementa primero queda
      diferido al resultado del spike de la spec 12, no fijado de antemano.
- [ ] Diferido a la implementación: medir `multilingual-e5-large` (CPU y CUDA) en la PC
      del usuario y recalibrar el umbral de deduplicación de memoria y los objetivos de
      latencia (specs 07 y 10).
- [ ] Diferido a la implementación: elegir y verificar el modelo de visión concreto de
      `VisionAgentAdapter` (spec 15, requisito 32bis-vision) y los modelos de biometría
      (spec 18); ninguno se fijó de memoria, se corre `bench`/`calibrate` en el hardware
      objetivo antes de comprometerlos.
- [ ] Crear kanban (GitHub Projects u otra herramienta) a partir de las specs ya
      escritas: cada spec se descompone en tareas concretas, no al revés. Las fases 0
      (auditorías y spikes de las specs 8, 10, 12 y 14) son tareas explícitas. El spike
      de la spec 12 decide además cuál estrategia de GUI de la spec 15 se implementa
      primero y el `max_alive` por defecto del pool de Claude Desktop (spec 17).
- [ ] Empezar implementación por la spec 1 (`proto/`) y la spec 16 (`libs/platform/`,
      prerrequisito); en paralelo pueden ir las specs 2, 3, 6, 8, 12 y 13.

---

## Notas

- **MVC**: se evaluó y no se adopta. Janus es un sistema de librerías y servicios por
  capas con puertos (`Protocol`) entre ellas y contratos ABC en las fronteras, y no
  tiene una interfaz de usuario propia dentro del alcance actual. Una GUI futura
  (`architecture/07`) será un cliente más del núcleo.
- Los ADRs se retiraron del flujo por decisión del usuario y quedaron archivados en
  `docs/_deprecated/adr/`. Las decisiones vigentes viven en `architecture/`, `stack/`,
  `agents/` y `specs/`.

---

## Próximo paso inmediato

No queda ninguna decisión de arquitectura abierta, incluidas las tres specs nuevas (16,
17, 18) y la extensión híbrida de la 15 cerradas el 2026-09-20. El siguiente paso es
armar el kanban desde las 18 specs (sección 2).
