# Documentación de Janus

El tech-stack (`stack/`) se deriva de la arquitectura (`architecture/`), y esta última es
la fuente de verdad. El modelo de agentes (`agents/`) extiende ambos.

Estado y trabajo pendiente: `../TODO.md`.

## `architecture/` — arquitectura pura

- `00-vision-y-alcance.md` — qué es Janus, alcance y criterios de éxito.
- `01-conceptos-y-vocabulario.md` — vocabulario y los dos principios (estrella pura, no-reinvención).
- `02-arquitectura-estrella-y-contrato-de-integracion.md` — forma del sistema y contrato de integración.
- `03-contrato-de-spoke.md` — contrato del adaptador por tipo de spoke.
- `04-modelo-de-capacidades-y-enrutamiento.md` — registro y delegación de capacidades.
- `05-modelo-de-roles-y-tareas.md` — roles, tareas y multi-agente paralelo.
- `06-modelo-de-persistencia-y-estado.md` — qué pertenece a Janus de forma transversal.
- `07-superficie-para-gui-futura.md` — observabilidad y control externo.
- `08-mapa-de-componentes-reales.md` — inventario de componentes concretos.
- `09-preguntas-abiertas.md` — estado de cada pregunta abierta.
- `10-automatizacion-de-interfaz-grafica.md` — spokes controlados por GUI.

## `stack/` — decisiones de implementación

- `01-contexto-y-lenguajes.md` — contexto de despliegue y lenguaje por pieza.
- `02-monorepo.md` — filosofía y layout del monorepo.
- `03-persistencia.md` — SQLite, `aiosqlite`, migraciones, Redis.
- `04-modelo-semantico-proto.md` — Protocol Buffers y `buf`.
- `05-harnesses-hermes-openclaw.md` — Hermes extraído, OpenClaw forkeado, división de responsabilidades.
- `06-config-toml-pydantic.md` — configuración.
- `07-descubrimiento-y-capacidades.md` — descubrimiento de spokes y Registro de Capacidades.
- `08-seguridad-y-observabilidad.md` — tokens scopeados, logs.
- `09-politicas-de-fallo.md` — catálogo de políticas y `FailurePolicy`.
- `10-gui-automation-y-licencia.md` — automatización de GUI (Rust + Python) y licencia MIT.

## `agents/` — modelo de agentes

- `01-modelo-de-agente.md` — qué es un agente, `AgentCore`/`AgentPersona`.
- `02-memoria.md` — memoria de dos niveles e indexación de identidad.
- `03-skills-y-config.md` — skills compartidos, topología de carpetas, validación, hot-reload.
- `04-orquestacion-y-sesiones.md` — orquestación exclusiva de Janus, sesiones por tarea, identidad visual.
- `05-voz.md` — proveedores de TTS/STT.
- `06-cambio-dinamico-de-modelo.md` — cambio de proveedor de modelo vía tool call.
- `07-concurrencia.md` — cola FIFO por carriles, Janus exento.
- `08-impacto-en-monorepo-y-diferido.md` — piezas que ganan responsabilidades y puntos diferidos a `/spec`.
