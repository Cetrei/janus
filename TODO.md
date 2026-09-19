# TODO — Janus

Estado del proyecto: arquitectura pura (docs 00-10) + tech-stack (doc 11) cerrados.
Este archivo es la lista viva de lo que falta antes de poder implementar. Se actualiza
a medida que cada punto se resuelve (vía `/discuss`, `/adr` o `/spec`).

Orden de trabajo acordado: **documentar todo → ADRs de las decisiones grandes → specs
por componente → kanban (GitHub Projects u otra app) → implementación.**

---

## 1. Discusiones de arquitectura pendientes (`/discuss`)

### 1.1 Sistema agéntico completo de Janus — LA MÁS GRANDE, prioridad primera
Candidato a `docs/12-modelo-de-agentes-de-janus.md`. Incluye, sin resolver todavía:
- Cómo se definen skills, comandos y reglas de comportamiento propias de Janus (más
  allá de lo heredado del motor de razonamiento extraído de Hermes).
- Personalidades y voces por agente: cómo se configuran, cómo se persisten, qué motor
  de TTS/STT usa Janus y con qué parámetros de expresividad (Hermes tiene una
  limitación real conocida acá — ver doc 11 sección 6.1 — que Janus no debe heredar).
- Agentes personalizables por el usuario: qué puede personalizar, cómo se declara.
- Cambio dinámico de modelo/proveedor por agente, configurado globalmente.
- Cómo interactúa esto con el Registro de Capacidades (doc 04) y con el motor de
  razonamiento extraído (`libs/reasoning-engine/`).

### 1.2 Multi-avatar / multi-identidad-visible en un mismo canal
¿Puede `channel-gateway` (fork de OpenClaw) sostener varios bots con nombre y avatar
propios posteando en un mismo grupo de Discord/WhatsApp, o el tope real es un solo bot
con prefijo de texto por agente? No verificado técnicamente todavía. Bloquea parte del
diseño de la sección 1.1 (si las personalidades tienen o no identidad visual propia).

### 1.3 Motor de reglas para políticas de fallo extensibles
Más allá de las políticas declarativas estilo Docker ya fijadas (doc 11 sección 12):
¿se construye un motor de reglas/callbacks registrables para que el usuario defina
políticas de fallo custom por componente? Decisión de diseño del Core de Traducción.

### 1.4 Descubrimiento y arbitraje — flecos menores
- Confirmar el nombre final del archivo de config (se usó `config/janus.toml` como
  supuesto de trabajo, nunca confirmado explícitamente).
- Licencia del propio código de Janus (abierto o privado).

---

## 2. ADRs pendientes de redactar (`/adr`)

Decisiones ya tomadas en `/discuss` que necesitan quedar registradas como Architecture
Decision Record, con el porqué y las alternativas descartadas, para trazabilidad
futura:

- [ ] **ADR — Python + `abc` como lenguaje y mecanismo de contrato del núcleo**
      (vs Go, vs TypeScript/Bun)
- [ ] **ADR — Monorepo poliglota por convención de lenguaje**
      (`apps/` + `libs/`/`crates/`/`packages/`/`proto/`, sin anidar por lenguaje
      genérico)
- [ ] **ADR — Un solo proceso asyncio para el núcleo, no microservicios internos**
      (Core de Traducción + Registro + Persistencia en el mismo runtime)
- [ ] **ADR — SQLite + `aiosqlite` sin ORM, en vez de Postgres**
      (contexto: un solo host, un solo usuario, un solo escritor)
- [ ] **ADR — Migraciones como archivos `.sql` versionados con runner propio**
      (vs Alembic/yoyo-migrations)
- [ ] **ADR — Redis como capa efímera, nunca fuente de verdad**
- [ ] **ADR — Protocol Buffers + `buf` como modelo semántico único**
      (vs dataclasses a mano por lenguaje)
- [ ] **ADR — Hermes: extracción quirúrgica + refactor, no servicio externo ni fork
      completo** (la decisión más grande de esta ronda; documentar las tres opciones
      evaluadas de doc 11 sección "dilema" y por qué se descartaron A y B)
- [ ] **ADR — OpenClaw: fork completo, no extracción quirúrgica**
      (criterio de corte opuesto al de Hermes, y por qué)
- [ ] **ADR — División de responsabilidades voz/canales/razonamiento**
      (Janus posee voz e identidad; channel-gateway solo transporta; reasoning-engine
      solo razona — ninguno de los tres se solapa)
- [ ] **ADR — TOML + Pydantic para configuración, en vez de YAML**
- [ ] **ADR — Harnesses base vs spokes externos: sin arbitraje dinámico entre
      harnesses base** (asignación fija declarada por el usuario, nunca competencia
      en runtime)
- [ ] **ADR — Sistema de tokens scopeados propio, en vez de asumir confianza por
      localhost**
- [ ] **ADR — GUI automation dividida Rust (bajo nivel) + Python (orquestación)**

---

## 3. Specs de implementación pendientes (`/spec`)

Se generan después de cerrar los puntos 1 y 2. Orden sugerido (de más fundacional a
más periférico):

1. `libs/adapters/` — contratos ABC (`SpokeAdapter` y variantes)
2. `libs/config/` — esquema Pydantic + parser TOML
3. `libs/persistence/` — acceso SQLite vía `aiosqlite`, runner de migraciones
4. `proto/` + generación `buf` → `libs/proto-py/`
5. `apps/core-gateway/` — Core de Traducción + Registro de Capacidades (orquestador
   central)
6. `libs/auth/` — tokens scopeados
7. `libs/observability/` — logging estructurado + ring buffer + Redis pub/sub
8. `libs/reasoning-engine/` — extracción y refactor del motor de Hermes
9. `packages/channel-gateway-core/` + `apps/channel-gateway/` — fork de OpenClaw
10. `crates/gui-automation/` — automatización de GUI en Rust + binding PyO3
11. Sistema agéntico de Janus (depende de que 1.1 esté resuelto)

---

## 4. Después de las specs

- [ ] Crear kanban (GitHub Projects u otra herramienta) a partir de las specs ya
      escritas — cada spec se descompone en tareas concretas del kanban, no al revés.
- [ ] Empezar implementación.

---

## Próximo paso inmediato

Arrancar `/discuss` del punto **1.1 (sistema agéntico completo de Janus)** — es la
pieza más grande y la que más condiciona el resto (1.2, parte de las specs de
`reasoning-engine` y `channel-gateway`, y varios ADRs).
