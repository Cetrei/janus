# TODO — Janus

Arquitectura, tech-stack, modelo de agentes y las **15 specs de implementación**
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
| 15 | Adaptadores concretos de spoke (nueva, sin dueño antes) | Escrita |

---

## 2. Trabajo previo a la implementación

- [ ] Verificar la licencia de `ssoj13/filesystem-mcp-rs` (bloqueante de la spec 08) y
      decidir base alternativa si no hay licencia compatible con MIT.
- [ ] Confirmar la licencia del commit de OpenClaw que se forkeará (el README indica
      MIT) y del de Hermes (MIT verificado en el README).
- [ ] Escribir la spec del spoke propio que reemplaza a Relay/`claude-toolkit`
      (residual de la pregunta 13 de `architecture/09`): función de Relay rehecha,
      dinámica y multiplataforma, orquestando múltiples perfiles/instancias de un
      mismo harness. Sin dueño aún; se agrega como spec 16 o se incorpora a la 15, a
      decidir al planificar el kanban.
- [ ] Diferido a la implementación: medir `multilingual-e5-large` (CPU y CUDA) en la PC
      del usuario y recalibrar el umbral de deduplicación de memoria y los objetivos de
      latencia (specs 07 y 10).
- [ ] Crear kanban (GitHub Projects u otra herramienta) a partir de las specs ya
      escritas: cada spec se descompone en tareas concretas, no al revés. Las fases 0
      (auditorías y spikes de las specs 8, 10, 12 y 14) son tareas explícitas.
- [ ] Empezar implementación por la spec 1 (`proto/`); en paralelo pueden ir las specs
      2, 3, 6, 8, 12 y 13.

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

No queda ninguna decisión de arquitectura abierta. El siguiente paso es armar el kanban
desde las specs (sección 2).
