# Stack — Monorepo

## 1. Filosofía de monorepo: `apps/` vs código por lenguaje

Regla fijada explícitamente por el usuario, sin excepciones:

- **`apps/`** — todo lo que ocupa un tipo de hosting: un proceso desplegable con ciclo
  de vida propio, que escala horizontalmente si hace falta.
- **Código reutilizable por lenguaje, con la convención propia de cada ecosistema**,
  como carpetas de primer nivel (nunca anidadas bajo un genérico `libs/<lenguaje>/`):
  - `libs/` — Python.
  - `crates/` — Rust (convención Cargo).
  - `packages/` — TypeScript/Node (convención de workspaces).
- **`proto/`** — agnóstico de lenguaje, para el modelo semántico compartido
  (`stack/04-modelo-semantico-proto.md`). No es código de ningún lenguaje específico,
  por eso no vive bajo `libs/`, `crates/` ni `packages/`.

Regla de decisión ya no es "microservicios porque sí": es **microservicios solo donde
el código necesita ser un proceso independiente**; todo lo demás (lógica reutilizable
sin necesidad de proceso propio) va como librería importada, sin servidor, sin red de
por medio, sin costo de latencia. Esto se decidió explícitamente tras marcar la
tensión de que "microservicios" no debía significar fragmentar artificialmente las
tres piezas lógicas del núcleo (`architecture/02`) en tres procesos separados.

---

## 2. Layout completo del monorepo

```
apps/
  core-gateway/            # Python — proceso único: servidor MCP + cliente MCP +
                            # cliente gRPC + orquestador. Importa libs/ como
                            # dependencias internas, sin red de por medio.
  channel-gateway/         # TypeScript — proceso que corre el fork de OpenClaw.
                            # Importa packages/channel-gateway-core.

libs/                      # Python
  reasoning-engine/        # Extracción quirúrgica + refactor del motor de Hermes:
                            # bucle de tool-calling, parsing de function-calls,
                            # routing multi-proveedor de modelos, e indexación
                            # híbrida (BM25 + vectorial, estilo qmd de Hermes) usada
                            # tanto para identidad de agente como para proyectos del
                            # usuario y pre-selección de tools (ver
                            # agents/02-memoria.md sección 5 y
                            # agents/04-orquestacion-y-sesiones.md sección 2). NO
                            # incluye CLI, dashboard, ni sistema de mensajería de
                            # Hermes.
  capabilities/            # Registro de Capacidades. Importado directo por
                            # core-gateway, sin servidor propio.
  persistence/             # Persistencia Transversal: acceso a SQLite vía
                            # aiosqlite, migraciones .sql versionadas.
  adapters/                # Contratos ABC (SpokeAdapter y variantes) +
                            # implementaciones concretas (HermesAdapter si aplica
                            # como spoke externo, OpenClawAdapter, adaptadores de
                            # spokes externos plug-and-play).
  config/                  # Esquema Pydantic + parser TOML. Expone config
                            # validada a cualquier apps/* sin que el consumidor
                            # sepa cómo está guardada en disco.
  auth/                    # Sistema de tokens scopeados: hashing, verificación,
                            # generación.
  observability/           # structlog, rotación de logs, ring buffer en memoria,
                            # publicación a Redis pub/sub.
  proto-py/                # Código Python generado por `buf generate` desde
                            # proto/. Es contrato compartido, no lógica de
                            # core-gateway, por eso vive en libs/ propio aunque
                            # hoy solo core-gateway lo consuma.

crates/                    # Rust
  gui-automation/          # Captura de pantalla, inyección de eventos de OS,
                            # posible OCR/visión. Expuesto a Python vía PyO3.
                            # Abstrae por SO (Linux vía X11/Wayland es la
                            # prioridad real dado el target de Raspberry Pi).
  filesystem-mcp/          # Fork de filesystem-mcp-rs (port en Rust del filesystem
                            # MCP oficial), extendido con delete_path recursivo,
                            # bulk_edits, grep_files (regex) y edit_file con
                            # diff+dry-run. Sin indexación propia — la indexación
                            # vive en libs/reasoning-engine/ (ver
                            # agents/02-memoria.md sección 5). Reemplaza al MCP de
                            # filesystem oficial en toda referencia de stack/ y
                            # agents/.

packages/                  # TypeScript
  channel-gateway-core/    # Fork COMPLETO de OpenClaw (no extracción quirúrgica).
                            # Refactorizado únicamente donde Janus necesite
                            # tocarlo para integrarse (config, forma de recibir
                            # instrucciones de Janus), preservando el resto.

proto/                     # Agnóstico de lenguaje — fuente de verdad del modelo
                            # semántico.
  janus/
    v1/
      semantic.proto       # SemanticRequest, SemanticResponse, tipos base.
      task.proto            # Tareas y dependencias (architecture/05).
      capability.proto      # Registro de Capacidades (architecture/04).
  buf.yaml                 # Config de buf: lint + breaking change detection.
  buf.gen.yaml              # Config de generación: qué plugin genera qué, hacia
                            # dónde (libs/proto-py/, y futuros packages/*
                            # o crates/* si un SDK en otro lenguaje lo requiere).

config/
  janus.toml               # Config raíz: harnesses embebidos, spokes externos,
                            # puertos, políticas de fallo, políticas de selección.
                            # TOML, no YAML (ver stack/06-config-toml-pydantic.md).

docs/                       # Documentación: architecture/, stack/, agents/.
```

---

## Documentos relacionados
- `stack/01-contexto-y-lenguajes.md` — el contexto de despliegue que justifica un solo
  proceso para el núcleo.
- `stack/05-harnesses-hermes-openclaw.md` — qué contienen `libs/reasoning-engine/` y
  `packages/channel-gateway-core/`.
- `agents/08-impacto-en-monorepo-y-diferido.md` — qué responsabilidades nuevas gana cada
  pieza del layout por el modelo de agentes.
