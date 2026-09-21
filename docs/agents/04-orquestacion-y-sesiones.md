# Agentes — Orquestación y sesiones

## 1. Orquestación: tool exclusiva de Janus, por ensamblado de toolset

Toda capacidad de un agente —incluida la de delegar trabajo a otro agente— se modela
como una **tool**, de forma independiente del modelo subyacente (mismo patrón de
function-calling ya heredado del motor de razonamiento extraído,
`stack/05-harnesses-hermes-openclaw.md`, sección 1). La tool de orquestación
(`delegate_to_agent` o equivalente) existe en el sistema, pero **el Core de Traducción
es responsable de ensamblar el toolset de cada agente antes de instanciarlo**, y esa
tool se incluye únicamente en el toolset de Janus.

Un subagente (Implementer, Debugger, cualquier otro) **no tiene la tool de
orquestación en su lista de herramientas disponibles** — no es un permiso que se le
niegue en runtime ante un intento de uso, es una capacidad que directamente no existe
en su espacio de herramientas. Esto es deliberadamente más robusto que un chequeo de
permisos: elimina la superficie de ataque de que un subagente comprometido (por
ejemplo, vía prompt injection) intente invocar la tool de orquestación, porque la tool
ni siquiera está declarada en su contexto.

## 2. Ensamblado de toolset por agente — responsabilidad central

Esta es una responsabilidad nueva y explícita del Core de Traducción
(`apps/core-gateway/`, extendiendo lo ya definido en `stack/02-monorepo.md`): antes de
instanciar cualquier `AgentCore`, se construye su toolset específico a partir de:

- El catálogo compartido de skills/comandos (`agents/03-skills-y-config.md`, sección 1),
  filtrado según lo habilitado en la config de ese agente.
- La tool de memoria (`agents/02-memoria.md`, sección 4), disponible para todo agente.
- La tool de orquestación, incluida únicamente para Janus.
- Cualquier tool adicional específica de la especialidad del agente (p. ej. terminal/
  ejecución de código para Implementer).

Esto vive como lógica de `libs/reasoning-engine/` en coordinación con
`libs/capabilities/` (Registro de Capacidades).

## 3. Comunicación bidireccional entre Janus y subagentes: sesiones por tarea

Cada agente (Janus incluido) expone un canal de comunicación bidireccional
implementado como **sesión de chat**, reutilizando tal cual el mecanismo de
persistencia de sesión que ya trae el motor de razonamiento extraído
(`libs/reasoning-engine/`, ex-Hermes) — no se construye un sistema de mensajería
interno nuevo (no-reinvención).

**Modelo de sesión:**

- **Una sesión es por tarea, no por agente en general.** Un agente (p. ej. Implementer)
  puede tener múltiples sesiones simultáneas si tiene múltiples tareas activas — esto
  coincide 1:1 con los slots de concurrencia definidos en
  `agents/07-concurrencia.md`: cada slot ocupado de un tipo de agente es, en la
  práctica, una sesión activa de ese tipo.
- **Participante por defecto: Janus.** Toda sesión entre Janus y un subagente nace con
  Janus como único participante del lado de Janus — es, en esencia, un chat 1:1
  Janus↔subagente donde Janus manda instrucciones/tareas y el subagente responde.
- **El canal externo (`channel-gateway`) por defecto solo conecta con la sesión de
  Janus.** El usuario habla con Janus; Janus resume, sintetizando hitos relevantes (no
  cada paso intermedio), lo que los subagentes están haciendo en sus propias sesiones.
  El usuario puede consultarle a Janus el estado de cualquier subagente en cualquier
  momento — es una consulta normal a Janus, vía su tool de estado/observabilidad
  (conectada a `architecture/07-superficie-para-gui-futura.md`), no un mecanismo
  especial.
- **Modo avanzado — suscripción del usuario a una sesión puntual.** El usuario puede
  suscribirse a la sesión de una tarea específica de un subagente (no a "todo lo que
  ese agente haga en el futuro"). Suscribirse no crea una sesión nueva ni reinicia la
  existente: agrega al usuario como participante adicional de la sesión Janus↔subagente
  que ya está corriendo. Una vez suscripto, el usuario ve esa sesión en el canal
  externo (con la identidad visual que corresponda según el modo fijado — bot propio o
  prefijo compartido sobre el bot de Janus, ver sección 4) y **puede escribirle
  directamente al subagente**, sin pasar por Janus. Esto no le da al subagente la tool
  de orquestación (la sección 1 no cambia) — solo habilita que el usuario participe
  directamente de una conversación que ya existía.

**Ciclo de vida de la sesión — cierre por conteo de oyentes:**

- Una sesión no se cierra mientras tenga al menos un **oyente externo** (el usuario,
  suscripto vía canal o interfaz). Janus es participante permanente de toda sesión de
  subagente, pero **no cuenta para el umbral de cierre** — si contara, ninguna sesión
  cerraría nunca, porque Janus nunca se retira de una sesión que él mismo abrió.
- El cierre ocurre cuando el conteo de oyentes externos llega a 0 — esto es adicional
  a "la tarea terminó": una tarea completada con el usuario todavía suscripto no se
  cierra hasta que el usuario se desuscriba o cierre la vista, incluso si el subagente
  ya entregó el resultado.
- **Multiplicidad total, en ambos lados:** Janus puede tener N sesiones abiertas
  simultáneamente (una por subagente/tarea activa); el usuario también puede tener N
  suscripciones activas a la vez, accesibles tanto vía interfaz futura
  (`architecture/07-superficie-para-gui-futura.md`) como vía cualquier canal externo
  conectado (`channel-gateway`).

Esto agrega una responsabilidad concreta, nueva respecto a `stack/`, a
`libs/reasoning-engine/` (o a una pieza dedicada, a decidir en `/spec`): **gestión de
sesiones multi-participante con suscripción/desuscripción dinámica** — extensión sobre
la sesión persistente simple que el motor extraído ya resuelve de fábrica.

## 4. Identidad visual en canal: Janus por defecto, multi-bot opcional

Verificado técnicamente contra la documentación de OpenClaw (base de
`channel-gateway`): **es posible** que cada agente tenga identidad visual propia
(nombre y avatar distintos) en un mismo servidor/grupo, vía dos mecanismos:

1. **Un bot por agente (multi-token)** — cada agente registra su propia aplicación de
   bot (Discord, Telegram, etc.), con su propio token, nombre y avatar reales. Es el
   camino documentado y usado en producción por terceros, pero implica **trabajo
   manual externo por cada agente** (registrar la aplicación en la plataforma
   correspondiente) y tiene bugs activos conocidos y reportados en el proyecto base
   (confusión de identidad entre bots por enrutamiento incorrecto, filtrado que
   impide que los bots se vean entre sí) — no es una feature sin fricción.
2. **Webhooks con username/avatar por mensaje** — un único bot, identidad custom por
   mensaje vía webhook. Más liviano (no requiere N aplicaciones registradas), pero es
   una capacidad en desarrollo sobre el proyecto base, no un camino maduro todavía.

**Decisión de diseño:** el comportamiento por defecto es el descrito en la sección 3 —
Janus es la única identidad visual presente en el canal; los subagentes nunca postean
mensajes propios sin que el usuario se haya suscripto explícitamente a su sesión.
Cuando el usuario se suscribe (modo avanzado), la identidad visual del subagente en ese
canal se rige por un campo de configuración en `AgentPersona`:

```
channel_identity: "own_bot" | "shared_with_prefix"
```

- `"own_bot"` — el agente tiene su propio bot registrado (mecanismo 1), asumiendo el
  usuario el costo de registro y los matices de estabilidad conocidos arriba.
- `"shared_with_prefix"` — el agente escribe sobre el bot de Janus, distinguido por un
  prefijo de texto (p. ej. `[Implementer]: ...`), sin necesidad de registro adicional.
  Este es razonable como default del modo avanzado, dado el menor costo operativo.

---

## Documentos relacionados
- `architecture/07-superficie-para-gui-futura.md` — la tool de estado/observabilidad de
  Janus y la interfaz futura desde la que el usuario se suscribe a sesiones.
- `stack/05-harnesses-hermes-openclaw.md` — el motor extraído (function-calling,
  sesión persistente) y `channel-gateway` (OpenClaw), base de la sección 4.
- `stack/02-monorepo.md` — `apps/core-gateway/`, `libs/reasoning-engine/` y
  `libs/capabilities/`.
- `agents/01-modelo-de-agente.md` — Janus como agente líder; `AgentPersona`, donde vive
  `channel_identity`.
- `agents/02-memoria.md` — la tool de memoria incluida en el toolset de todo agente.
- `agents/03-skills-y-config.md` — el catálogo compartido que se filtra en el ensamblado
  de toolset.
- `agents/07-concurrencia.md` — los slots de concurrencia que coinciden 1:1 con las
  sesiones activas.
