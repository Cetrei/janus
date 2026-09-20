# Stack — Harnesses base: Hermes y OpenClaw

Distinción fundamental que quedó fijada tras discusión extensa: **harnesses base** son
infraestructura fija que Janus necesita para ser Janus (considerados desde el diseño,
siempre presentes, aunque desacoplados en código vía ABC) — no son candidatos que
compiten dinámicamente por una capacidad, a diferencia de los **spokes externos**
(Claude Desktop, Gemini Desktop, u otros modelos/asistentes que el usuario conecta y
desconecta libremente para sus tareas).

## 1. Hermes → extracción quirúrgica + refactor, no fork completo

**Decisión final, tras descartar dos alternativas más agresivas** (usar Hermes como
servicio externo consultado por capacidad; forkear el repo de Hermes completo 1:1):

Se extrae del código de Hermes (`NousResearch/hermes-agent`, MIT license, confirmado
compatible con fork/modificación/redistribución):

- El bucle de tool-calling y razonamiento del agente (ejecutar herramientas,
  interpretar resultados, iterar).
- El routing multi-proveedor de modelos (200+ modelos vía OpenRouter, Anthropic,
  OpenAI, DeepSeek, etc.).
- El sistema de skills como mecánica (cómo se guardan, cargan, relacionan a un
  dominio) — no necesariamente su learning loop automático completo si complica el
  control.

**Explícitamente NO se trae:**
- CLI de Hermes.
- Dashboard de Hermes.
- Sistema de mensajería/gateway de Hermes (los canales son territorio exclusivo de
  `channel-gateway`/OpenClaw, ver sección 3 de este documento).
- Voice mode de Hermes (TTS/STT propios) — la voz es territorio exclusivo de Janus
  (ver sección 3 de este documento). Nota técnica registrada durante la discusión: el
  `text_to_speech` de Hermes hoy solo acepta texto y ruta de salida, sin control de
  tono/emoción/ritmo — limitación real que refuerza por qué Janus no debe depender de
  ese subsistema para su propia capa de voz expresiva.
- Cualquier noción de sesión-por-chat o identidad de agente atada a plataforma de
  mensajería.

**Motivo del criterio de corte:** lo que Janus sabe que va a tocar recurrentemente
(identidad, config, forma de invocar el motor) se refactoriza ahora a esquema propio
(Pydantic + TOML); lo que se mantiene estable y ya está probado en producción por
terceros (algoritmo de tool-calling, parsing de function-calls, routing a proveedores)
se deja lo más intacto posible.

**Resultado:** vive en `libs/reasoning-engine/` como **librería interna** de Janus, no
como spoke externo ni como proceso separado. El Core de Traducción lo trata como
traduciría hacia cualquier spoke — solo que este "spoke" es código en el propio
monorepo, no un proceso externo.

## 2. OpenClaw → fork total, en `packages/channel-gateway-core/`

**Decisión final, con criterio explícitamente distinto al de Hermes:** OpenClaw se
forkea completo porque su rol es acotado y ya coincide 1:1 con lo que Janus necesita
(gateway de canales desacoplado de lógica de agente), sin partes muertas que compitan
con el diseño de Janus. OpenClaw nunca decide personalidad ni razona — solo transporta
— por lo que no hay riesgo de que su sesión/identidad interna choque con la capa de
identidad de agentes que Janus construye por su cuenta.

Refactor limitado únicamente a lo que Janus necesite tocar para integrarse (config,
forma de recibir instrucciones desde `core-gateway`), preservando el resto del
comportamiento de gateway multi-canal tal cual.

Corre como su propio proceso: `apps/channel-gateway/` (TypeScript), importando
`packages/channel-gateway-core/`.

## 3. División de responsabilidades — regla explícita, sin excepciones

Esta tabla es la regla operativa fijada tras corregir un malentendido en la discusión
(no confundir "quién soporta técnicamente algo" con "quién lo posee en Janus"):

| Responsabilidad | Dueño | Notas |
|---|---|---|
| Razonamiento/ejecución de tareas de código | `libs/reasoning-engine/` (ex-Hermes) | Nunca habla directo al usuario, nunca conoce canales ni voces. |
| Routing a proveedores de modelo | `libs/reasoning-engine/` (ex-Hermes) | Ya resuelto por el motor extraído; Janus decide qué agente usa qué configuración de routing. |
| Credenciales y conexión a canales (WhatsApp, Discord, Telegram, etc.) | `channel-gateway` (fork de OpenClaw) | Puro transporte: recibe texto/audio ya generado por Janus y lo entrega; recibe del canal y lo pasa a Janus. |
| Síntesis de voz (TTS) y reconocimiento (STT) | Janus (`core-gateway` + librería propia a definir) | Janus decide qué proveedor de TTS/STT invocar y con qué parámetros, incluso si ese proveedor es uno que Hermes también soporta (ElevenLabs, OpenAI TTS, NeuTTS) — la invocación es de Janus, no una feature activada dentro de Hermes. |
| Identidad/personalidad persistente por agente | Janus (sistema agéntico propio, ver `agents/01-modelo-de-agente.md`) | No existe hoy en el motor extraído de forma rica. |
| Qué agente responde en qué canal, con qué voz | Registro de Capacidades + Core de Traducción (`core-gateway`) | Ver `stack/07-descubrimiento-y-capacidades.md`. |
| GUI automation | `crates/gui-automation/` (Rust) + orquestación en `core-gateway` | Ver `stack/10-gui-automation-y-licencia.md`. |

**Flujo de referencia para un mensaje entrante** (ejemplo, WhatsApp, con síntesis de
voz activa para ese agente):

```
Usuario → channel-gateway (OpenClaw, recibe)
        → core-gateway: Core de Traducción
        → core-gateway: Registro de Capacidades decide qué agente/tarea aplica
        → libs/reasoning-engine (ex-Hermes) genera la respuesta de texto
        → core-gateway: Core de Traducción
        → Janus sintetiza voz (si el agente tiene voz activa)
        → channel-gateway (OpenClaw, entrega texto y/o audio)
```

## 4. Política de mantenimiento del fork frente a upstream

Resuelto tras evaluar explícitamente el valor real de seguir los cambios de
`NousResearch/hermes-agent`, dividido por área (no es parejo en toda la superficie del
proyecto):

- **Alto valor de seguir de cerca:** routing multi-proveedor de modelos (área de mayor
  tasa de cambio real — proveedores nuevos, APIs que cambian, modelos deprecados) y
  advisories de seguridad sobre el bucle de tool-calling/ejecución (superficie de
  ataque real: inyección de prompt que escala a ejecución arbitraria).
- **Bajo o nulo valor de seguir:** todo lo explícitamente no extraído (CLI, dashboard,
  mensajería, voice mode), y el sistema de skills en la medida en que Janus termine
  divergiendo de su diseño original (el learning loop automático completo no se trajo
  tal cual, ver sección 1).

**OpenClaw:** esta política se definió solo para Hermes. Para OpenClaw (licencia MIT según
su README, proyecto mantenido por una fundación, con versiones fechadas frecuentes)
el usuario confirmó **sin cadencia fija**: el upstream de OpenClaw no se revisa en
calendario, solo ante un disparador concreto (un CVE público contra el proyecto, o un
canal que deja de funcionar por un cambio de protocolo del lado de la plataforma
mensajera). Esto reemplaza la propuesta de revisión mensual de `specs/spec-14-channel-
gateway.md`, ahora confirmada en ese sentido: no calendario, sí disparador.

**Proceso fijado:** no merge automático ni seguimiento en tiempo real del repo
completo. Revisión periódica (cadencia mensual) filtrada a dos fuentes: el changelog/
releases de `hermes-agent` en busca de (a) nuevos proveedores de modelo soportados y
(b) advisories de seguridad. Cuando algo relevante aparece, se evalúa puntualmente si
aplica al fork ya refactorizado — típicamente portado a mano en vez de mergeado
directo, dado que la estructura ya diverge del original.

---

## Documentos relacionados
- `architecture/08-mapa-de-componentes-reales.md` — inventario original de spokes; sus
  secciones 1 y 3 reflejan esta decisión.
- `stack/02-monorepo.md` — dónde viven `libs/reasoning-engine/`,
  `packages/channel-gateway-core/` y `apps/channel-gateway/`.
- `stack/07-descubrimiento-y-capacidades.md` — cómo se conectan los harnesses base y
  por qué no hay arbitraje dinámico entre ellos.
- `agents/01-modelo-de-agente.md` — el modelo de agentes que corre sobre el motor
  extraído.
