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
                            # implementaciones concretas en spokes/<nombre> con
                            # extras opcionales (motor de razonamiento, puente de
                            # canales, OpenClaude, gRPC y MCP genericos, GUI,
                            # modelos por API). Ver specs 04 y 15.
  memory/                  # Categorizacion auto-extensible y busqueda semantica
                            # sobre sqlite-vec (agents/02). Spec 07.
  voice/                   # TTS y STT propios de Janus, proveedores
                            # intercambiables. Spec 13.
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
                            # MCP oficial), extendido con bulk_edits atomico y
                            # grep_files (regex) y lo que falte tras auditar el
                            # upstream (delete_path recursivo y edit_file con
                            # diff+dry-run ya existen alli, verificado en 2026-09;
                            # licencia por confirmar, spec 08). Sin indexación propia — la indexación
                            # vive en libs/reasoning-engine/ (ver
                            # agents/02-memoria.md sección 5). Reemplaza al MCP de
                            # filesystem oficial en toda referencia de stack/ y
                            # agents/.

packages/                  # TypeScript
  channel-gateway-core/    # Fork COMPLETO de OpenClaw (no extracción quirúrgica).
                            # Refactorizado únicamente donde Janus necesite
                            # tocarlo para integrarse (config, forma de recibir
                            # instrucciones de Janus), preservando el resto.
  proto-ts/                # Codigo TypeScript generado desde proto/ para
                            # channel-gateway (spec 14).

proto/                     # Agnóstico de lenguaje — fuente de verdad del modelo
                            # semántico.
  janus/
    v1/
      common.proto         # Payload, Artifact, ErrorInfo (spec 01).
      semantic.proto       # SemanticRequest, SemanticResponse, tipos base.
      task.proto            # Tareas y dependencias (architecture/05).
      capability.proto      # Registro de Capacidades (architecture/04).
      session.proto  channel.proto  spoke.proto  gateway.proto  # spec 01
  buf.yaml                 # Config de buf: lint + breaking change detection.
  buf.gen.yaml              # Config de generación: qué plugin genera qué, hacia
                            # dónde (libs/proto-py/, y futuros packages/*
                            # o crates/* si un SDK en otro lenguaje lo requiere).

config/
  janus.toml               # Config raíz: harnesses embebidos, spokes externos,
                            # puertos, políticas de fallo, políticas de selección.
                            # TOML, no YAML (ver stack/06-config-toml-pydantic.md).
  agents/<Nombre>/         # Un folder por agente con topologia obligatoria
                            # (agents/03 seccion 2.1). Ubicacion propuesta en spec 02.
  catalog/                 # Catalogo compartido de skills y comandos (spec 02).

docs/                       # Documentación: architecture/, stack/, agents/, specs/.
```

---

## 3. Workspaces: uno por ecosistema, todos en la raíz

Regla fijada por el usuario (2026-09-20): la estructura es de procesos independientes
(sección 1), y por eso todo el código se organiza con el mecanismo de workspaces nativo
de cada ecosistema, no con carpetas sueltas ni instalaciones por componente.

| Ecosistema | Herramienta | Archivo raíz | Miembros | Lockfile |
|---|---|---|---|---|
| Python | `uv` | `pyproject.toml` con `[tool.uv.workspace]` | `libs/*`, `apps/core-gateway` y `crates/gui-automation` (que se construye con maturin; a validar en el spike de la spec 12) | `uv.lock` |
| Rust | Cargo | `Cargo.toml` con `[workspace]` | `crates/*` | `Cargo.lock` |
| TypeScript | `bun` | `package.json` con `workspaces` | `packages/*` y `apps/channel-gateway` | `bun.lock` |

Reglas comunes:

* Un solo lockfile por ecosistema y dependencias compartidas declaradas una vez
  (`[workspace.dependencies]` en Cargo, `workspace = true` en `[tool.uv.sources]`,
  `workspace:*` en bun).
* Los workspaces no se mezclan entre sí. El puente entre lenguajes es `proto/` con `buf`
  (`stack/04`), salvo el caso de `crates/gui-automation`, que Cargo compila y uv instala
  como paquete Python.
* Los archivos raíz no llevan código. Cada miembro sigue siendo desplegable o probable por
  su cuenta.

Puntos abiertos de esta sección, todos en la fase 0 de sus specs:

* **Bun frente al fork de OpenClaw** (spec 14): OpenClaw es un workspace `pnpm` propio que
  exige Node 22. Bun es la decisión del usuario para el resto, pero hay que verificar que
  el fork instala, compila y arranca con bun, si el runtime del proceso sigue siendo Node
  o pasa a ser Bun, y cómo convive su workspace interno con el workspace raíz.
* **`crates/gui-automation` en dos workspaces** (spec 12): validar en el spike que un
  mismo directorio sea miembro de Cargo y de uv sin fricción.

---

## 4. Nombres de paquetes: prefijo `janus` en todo

Regla fijada por el usuario (2026-09-20): todos los paquetes, de cualquier lenguaje,
llevan el prefijo `janus`. Las carpetas no lo llevan (`libs/config/`, no
`libs/janus-config/`).

| Ecosistema | Carpeta | Nombre de paquete | Nombre de import | Ejemplo |
|---|---|---|---|---|
| Python (`libs/`, `apps/`) | `libs/config` | `janus-<corto>` | `janus_<corto>` | `janus-config`, `janus_config` |
| Rust (`crates/`) | `crates/filesystem-mcp` | `janus-<corto>` | `janus_<corto>` | `janus-filesystem-mcp` |
| TypeScript (`packages/`, `apps/`) | `packages/proto-ts` | `@janus/<corto>` | `@janus/<corto>` | `@janus/proto` |

Reglas:

* `<corto>` lo fija cada spec en su estructura de directorios. No tiene por qué igualar
  el nombre de la carpeta ni llevar sufijo de lenguaje: `libs/reasoning-engine` es
  `janus_reasoning`, `apps/core-gateway` es `janus_core`, `libs/proto-py` y
  `packages/proto-ts` son `janus_proto` y `@janus/proto`.
* Crates con binding PyO3: el paquete de Cargo es `janus-gui-automation` y el módulo de
  Python es `janus_gui`, tal como fija la spec 12.
* Los paquetes de TypeScript son internos: llevan `private: true` y no se publican en npm.
* Excepción dictada por la ruta de los `.proto`: el código generado vive en el namespace
  `janus.v1` (spec 01), con fachada `janus_proto`. Ese namespace tiene un riesgo de
  colisión con un paquete de PyPI, descrito en la spec 01 (Open Questions).

---

## Documentos relacionados
- `stack/01-contexto-y-lenguajes.md` — el contexto de despliegue que justifica un solo
  proceso para el núcleo.
- `stack/05-harnesses-hermes-openclaw.md` — qué contienen `libs/reasoning-engine/` y
  `packages/channel-gateway-core/`.
- `agents/08-impacto-en-monorepo-y-diferido.md` — qué responsabilidades nuevas gana cada
  pieza del layout por el modelo de agentes.
