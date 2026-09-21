# Stack — Contexto de despliegue y lenguajes

## 1. Contexto de despliegue (decide todo lo demás)

Janus es un sistema de **uso personal, para una sola persona, corriendo en un solo
host** (PC de escritorio o Raspberry Pi). No está planeado como servicio distribuido,
no requiere alta disponibilidad, no requiere escalado horizontal. Esta restricción es
la que justifica, a lo largo de todo el stack, elegir SQLite sobre Postgres, proceso
único sobre múltiples réplicas, y priorizar bajo consumo de RAM/CPU sobre capacidad de
escala.

---

## 2. Lenguaje y runtime por pieza

| Pieza | Lenguaje | Razón |
|---|---|---|
| `core-gateway` (Core de Traducción + Registro + Persistencia) | Python (asyncio), servido con `uvicorn` | Carga de trabajo I/O-bound (proxy/traductor entre spokes), no cómputo pesado. Ecosistema MCP y gRPC maduro en Python. |
| Motor de razonamiento (extracción de Hermes) | Python | Coincide con el lenguaje del núcleo; cero fricción de integración. |
| `channel-gateway` (fork de OpenClaw) | TypeScript sobre Bun | Lenguaje nativo del proyecto forkeado; no se reescribe. |
| GUI automation (pieza de bajo nivel) | Rust | Trabajo potencialmente pesado (captura de pantalla, inyección de eventos de OS); bindings nativos más naturales que en Python puro. Expuesto a Python vía `PyO3`/`maturin`. |
| Contratos de adaptador de spoke | Python, vía `abc` (Abstract Base Classes) | Decisión explícita del usuario: OOP con contratos formales, no duck typing. |

Todo el núcleo (Core de Traducción, Registro de Capacidades, Persistencia Transversal,
motor de razonamiento) corre como **un solo proceso asyncio**, no como microservicios
separados entre sí. `stack/02-monorepo.md` explica por qué esto no contradice la
filosofía de monorepo del proyecto.

---

## Documentos relacionados
- `stack/02-monorepo.md` — cómo se organiza el código dado este contexto.
- `stack/03-persistencia.md` — SQLite sobre Postgres, consecuencia directa de la
  sección 1.
- `architecture/02-arquitectura-estrella-y-contrato-de-integracion.md` — los tres
  componentes lógicos del núcleo que aquí corren en un solo proceso.
