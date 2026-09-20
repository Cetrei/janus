# Stack — Descubrimiento de spokes y Registro de Capacidades

## 1. Descubrimiento de spokes: dos mecanismos, según el tipo

### 1.1 Harnesses base (Hermes extraído, OpenClaw forkeado): conectados por Janus mismo

Janus los necesita para ser Janus — no esperan a anunciarse, Janus los arranca/importa
directamente. Configurados en `config/janus.toml` bajo secciones propias:

```toml
[harnesses.reasoning-engine]
# configuración del motor de razonamiento extraído

[harnesses.channel-gateway]
port = 8090
timeout_ms = 5000
retry_policy = "on-failure"
max_retries = 3
```

Aclaración de las specs: `channel-gateway` es cliente gRPC del núcleo y su `port` es el
endpoint HTTP de salud en loopback (`specs/spec-14-channel-gateway.md`). El núcleo es
quien arranca y supervisa ese proceso (`specs/spec-11-core-gateway.md`).

### 1.2 Spokes externos: se presentan ante Janus vía endpoint de registro

Un spoke externo (Claude Desktop, Gemini Desktop, u otro que el usuario decida
conectar) declara quién es y qué capacidades ofrece contra un endpoint expuesto por el
Core de Traducción (`POST /register` o su equivalente en MCP/gRPC, según el transporte
del spoke). Esta conexión activa es estado dinámico:

- Si necesita sobrevivir un reinicio de Janus: SQLite.
- Si es puramente efímera para la sesión actual: Redis.

Los spokes externos requieren, además, presentar un token propio al registrarse
(`stack/08-seguridad-y-observabilidad.md`, sección 1) — a diferencia de los harnesses
base, que usan el token default interno.

### 1.3 Redundancia entre harnesses base: asignación fija, no arbitraje dinámico

Fijado explícitamente: si dos harnesses base pudieran técnicamente ofrecer la misma
capacidad (ejemplo hipotético discutido: conectividad de canal), **no existe
arbitraje dinámico entre harnesses base**. La asignación es una decisión de diseño
humana, declarada una vez en `config/janus.toml` (un dueño único y explícito por
capacidad de harness base). Qué pasa si ese dueño falla se resuelve con política de
fallo/reintento (`stack/09-politicas-de-fallo.md`), nunca con competencia en runtime.
Esto es consistente con que los harnesses base sean infraestructura fija y conocida de
antemano, sin ambigüedad por diseño.

---

## 2. Registro de Capacidades: alcance acotado a spokes externos

Corrección explícita respecto al planteo original de
`architecture/04-modelo-de-capacidades-y-enrutamiento.md`: la resolución de capacidad
con política de selección (qué hacer si más de un candidato puede resolver la misma
solicitud) **aplica únicamente a spokes externos** — fuentes de inteligencia
intercambiables que el usuario conecta para sus tareas. Los harnesses base nunca
compiten entre sí (sección 1.3); no son candidatos en el sentido del doc 04.

Vive en `libs/capabilities/`, importado directo por `core-gateway`, sin servidor
propio ni red de por medio (justificado por ser un solo host, un solo proceso).

La política de selección entre spokes externos candidatos se declara en
`config/janus.toml` (prioridad explícita por spoke, o una policy nombrada), nunca
hardcodeada ni improvisada en runtime.

---

## Documentos relacionados
- `architecture/03-contrato-de-spoke.md` — el contrato que `libs/adapters/` implementa
  vía ABC.
- `architecture/04-modelo-de-capacidades-y-enrutamiento.md` — base conceptual de
  `libs/capabilities/`.
- `stack/05-harnesses-hermes-openclaw.md` — qué son los harnesses base.
- `stack/08-seguridad-y-observabilidad.md` — el token que presentan los spokes externos.
- `agents/07-concurrencia.md` y `agents/06-cambio-dinamico-de-modelo.md` — responsabilidades
  que el modelo de agentes suma a `libs/capabilities/`.
