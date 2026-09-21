# 09 — Preguntas Abiertas

## Estado del documento
Este documento existe para que ninguna ambigüedad quede oculta por omisión. Cada
entrada lleva un estado explícito:

- **ABIERTA** — decisión genuinamente no tomada aún.
- **PARCIALMENTE RESUELTA** — la decisión principal se tomó en otro documento, pero
  queda un residual explícito, descrito en la entrada.
- **RESUELTA** — se decidió en otro documento; la entrada se conserva solo como registro
  de dónde, para no reabrirla por error.

Ninguna entrada ABIERTA debe interpretarse como resuelta implícitamente por otro
documento. Las referencias `stack/` y `agents/` apuntan a las carpetas hermanas de
`architecture/` dentro de `docs/`.

---

## 1. Política de prioridad entre criterios de selección de spoke — RESUELTA
**Origen:** `04-modelo-de-capacidades-y-enrutamiento.md`, sección 3.

Cuando más de un spoke sirve la misma capacidad, se identificaron tres criterios de
selección posibles (preferencia explícita del usuario, disponibilidad/cuota, contexto
del rol/tarea), pero no se decidió el orden de prioridad entre ellos cuando entran en
conflicto — por ejemplo, si el usuario fijó una preferencia explícita pero ese spoke no
tiene cuota disponible en este momento, ¿se cae automáticamente a otro spoke, o se
bloquea la tarea hasta que el usuario decida? Tampoco se decidió si esta prioridad es
global o configurable por capacidad/rol.

**Resuelto:** la política de selección entre spokes externos se declara en
`config/janus.toml` (prioridad explícita por spoke, o una policy nombrada), nunca
hardcodeada (`stack/07-descubrimiento-y-capacidades.md`, sección 2). Entre harnesses
base no hay selección dinámica: la asignación es fija (misma referencia, sección 1.3).
Para el caso del cambio de proveedor de modelo, caer a otro proveedor es una tool call
sujeta a una política de aprobación configurable con cuatro valores confirmados por el
usuario (`ask_everytime`, `ask_once_per_session`, `allow_always` y `deny_always`), global
con override por agente (`agents/06-cambio-dinamico-de-modelo.md`).

**Residual cerrado:** el orden de prioridad entre los tres criterios para capacidades
que no son cambio de proveedor de modelo. Confirmado por el usuario
(`specs/spec-09-capabilities.md`): salud, luego política del usuario, luego sugerencia de
rol, y ese orden sirve solo para desempatar candidatos de salud equivalente. Qué hacer
ante un fallo no lo decide un enum (`fallback` | `block` | `ask`) sino el mecanismo que
sigue.

**Precisión del usuario sobre el mecanismo de fallback:** son dos cosas separadas.

1. La *cadena de fallback* es una política declarativa que el propio usuario define en
   la configuración del agente: reglas dinámicas encadenables del tipo "usar Gemini; si
   falla, usar Claude; si falla, lo que OpenRouter permita; si falla, esperar". No es un
   valor único (`fallback` | `block` | `ask`) sino una secuencia ordenada de N reglas que
   el usuario puede editar.
2. El *juicio de si un fallo amerita seguir esa cadena o directamente avisar al
   usuario* no debe ser una regla precodificada ni parte de la cadena declarativa: es
   una decisión de Janus (el agente orquestador) en runtime, evaluando si el fallo es
   de un tipo mitigable por reintento/cambio de candidato o si necesita anunciarse.
   Esto separa "qué alternativas hay y en qué orden" (declarado por el usuario) de
   "cuándo vale la pena intentarlas vs cortar y avisar" (criterio de Janus, no una
   tabla estática).

Esto cambia el diseño propuesto en la spec 09: `on_preferred_unavailable` como enum
cerrado no alcanza para cubrir cadenas de N pasos, y el criterio de escalar a aviso no
debe vivir como un valor fijo del enum sino como una evaluación del propio Janus. Ver
spec 09 para el ajuste concreto.

## 2. Mecanismo concreto de captura y consulta de memoria de largo plazo — RESUELTA
**Origen:** `06-modelo-de-persistencia-y-estado.md`, sección 2.4.

Se estableció que la memoria de largo plazo pertenece a la persistencia transversal del
núcleo, pero no se decidió cómo se decide qué información entra a esa memoria (captura
automática vs. explícita), ni cómo se pondera su relevancia al consultarla en sesiones
futuras. Esto es intencionalmente dejado fuera de la arquitectura pura porque toca
decisiones de implementación (posible uso de embeddings, ventanas de resumen, etc.).

**Resuelto:** memoria de dos niveles (agente y global), por categorías auto-extensibles
con `profile` como única semilla de fábrica, recuperada por similitud semántica sobre
`sqlite-vec` mediante una tool dedicada (`recall_memory`); la relevancia es la
similitud entre la consulta y la entrada (`agents/02-memoria.md`).

**Residual cerrado por el usuario (2026-09-20):** la captura es explícita y nada más.
Janus es un agente: guarda recuerdos cuando lo decide o cuando el usuario se lo pide, y
sus subagentes hacen lo mismo, mediante la tool `remember`. No existe captura automática
de infraestructura, ni siquiera como opción configurable
(`specs/spec-07-memory.md`, requisito 18).

**Modelo de embeddings, también cerrado:** es configurable en el sistema
(`memory.embedding_model`) y su default se elige para el hardware del usuario (PC con
32 GB de RAM y 6 GB de VRAM), no para el Raspberry Pi; el Pi usa un perfil más chico. La
dimensión del índice vectorial se deriva del modelo (`specs/spec-03-persistence.md`,
requisito 20bis).

## 3. Mecanismo de autenticación/autorización para control externo — RESUELTA A NIVEL DE ARQUITECTURA, DETALLE DIFERIDO A `/spec`
**Origen:** `07-superficie-para-gui-futura.md`, sección 4.

Se estableció qué debe ser controlable desde afuera del núcleo, pero no cómo se
garantiza que solo el usuario legítimo (u otros actores autorizados) puedan ejercer ese
control — especialmente relevante una vez que existan canales de mensajería y voz que
también pueden emitir comandos de control, no solo consultas.

**Resuelto:** sistema propio de tokens scopeados (id, secreto hasheado, scopes,
expiración opcional), con un token default interno de scope total para los harnesses
base y tokens generados por el usuario para los spokes externos, verificados en cada
request entrante al Core de Traducción (`stack/08-seguridad-y-observabilidad.md`,
sección 1).

**Resolución del residual, según el usuario:** la revalidación del núcleo (segunda
capa, sobre el pairing/allowlist ya provisto por `channel-gateway`) combina hasta tres
señales, todas configurables de forma independiente por canal:

1. **Identificador por plataforma** (número de WhatsApp, user ID de Discord, etc.):
   el default de menor fricción, comparación mecánica simple contra `identity.owner`.
2. **Desafío redactable en `.md`**: un texto libre (pregunta, frase clave, lo que sea)
   que el usuario escribe una vez y que se incrusta en el contexto del agente para esa
   sesión. El agente puntúa la respuesta del remitente contra ese desafío con su
   propio juicio (no comparación exacta de string) y llama a una tool
   (`mark_sender_verified` o equivalente) cuando decide que la identidad quedó
   validada. Hasta ese momento el remitente cuenta como no verificado aunque el canal
   ya lo tenga en su lista de permitidos.
3. **Biometría local** (ver pregunta 14 de este documento, nueva): reconocimiento de
   voz y/o cara corriendo en hardware del hogar, como tercera señal.

Las tres son composables por canal: un canal puede usar solo una, dos, las tres, o
ninguna (degradando a confiar en el pairing del gateway). La vigencia de una
verificación exitosa por desafío `.md` también es configurable por canal/ámbito
(`owner_reverify`: `never`, `per_message`, `per_session` o `ttl` con una duración) —
ejemplo dado por el usuario: desde la PC (interacción directa) nunca se pide (`never`),
desde WhatsApp se pide una vez por chat nuevo (`per_session`), desde un speaker de la casa
se pide siempre (`per_message`). Cuando se llama a Janus y el sistema detecta que la
verificación venció, inyecta esa información en el prompt del turno (spec 11, requisito
26bis).

**Confirmado por el usuario (2026-09-20)** (`specs/spec-11-core-gateway.md` y
`specs/spec-14-channel-gateway.md`): verificación en capas, con el emparejamiento y la
lista de permitidos del gateway más una revalidación en el núcleo. La forma concreta de
`identity.owner` es una mezcla: por defecto el identificador por plataforma (señal 1,
comparación mecánica), y opcionalmente un secreto compartido que el usuario decide y
escribe libremente en un `.md` (señal 2). Ese secreto se incrusta en el contexto del
agente hasta que este decide que la identidad quedó validada y lo marca llamando a una
tool. Los campos de configuración por canal (`owner_reverify`, `owner_challenge_file`)
ya están en `specs/spec-02-config.md`, y el mecanismo de vigencia y de reinyección al
prompt está en `specs/spec-11-core-gateway.md`, requisito 26bis. Queda como trabajo de
diseño la integración con la biometría de la pregunta 14.

## 4. Gobernanza y licencia de Hermes — RESUELTA
**Origen:** `08-mapa-de-componentes-reales.md`, sección 1.

Se identificó a Hermes como spoke candidato fuerte para capacidades de canal/gateway y
orquestación, pero no se verificó en profundidad su licencia ni gobernanza del
proyecto. Queda pendiente determinar si esto condiciona la decisión de incluirlo en el
conjunto de spokes soportados "de fábrica" (documento 00, sección 4) frente a dejarlo
como una integración de referencia opcional.

**Resolución:** licencia MIT confirmada, compatible con fork, modificación y
redistribución. Se incluye de fábrica como harness base, por extracción quirúrgica hacia
`libs/reasoning-engine/`. La gobernanza del upstream se cubre con una política de
revisión mensual filtrada a nuevos proveedores de modelo y advisories de seguridad
(`stack/05-harnesses-hermes-openclaw.md`, secciones 1 y 4).

## 5. Procedencia de OpenClaude y su efecto en decisiones de extensión propia — RESUELTA
**Origen:** `08-mapa-de-componentes-reales.md`, sección 2.

Se documentó que OpenClaude deriva del código base de Claude Code (no liberado
oficialmente por Anthropic), consumido por Janus únicamente como spoke externo vía su
servidor gRPC. Estaba abierto si en algún momento se consideraría extender directamente
ese código base en lugar de solo consumirlo como spoke.

**Resolución:** cerrada por decisión del usuario. Janus nunca tocará ni extenderá ese
código base. El único modelo de integración válido, ahora y a futuro, es consumo como
spoke externo vía protocolo (gRPC), sin excepción. No hay implicación legal que evaluar
porque no hay escenario en el que se contemple lo contrario.

## 6. Mecanismo de integración con Claude Desktop y Gemini Desktop — RESUELTA A NIVEL DE ARQUITECTURA
**Origen:** `08-mapa-de-componentes-reales.md`, secciones 5 y 6.

Esta pregunta quedó resuelta a nivel de arquitectura: ambos se clasifican como spoke
tipo 2.4 (documento 03) y se operan mediante el mecanismo de control de ventana + mapa
de elementos interactuables descrito en `10-automatizacion-de-interfaz-grafica.md`. Lo
que permanece abierto, y se traslada a las preguntas 11 y 12 de este documento, es la
elección de tecnología concreta para implementar ese mecanismo y el alcance exacto de
qué aplicaciones adicionales se soportarán de fábrica.

## 7. Selección entre Hermes y OpenClaw cuando ambos están disponibles como spoke de canal — RESUELTA
**Origen:** `08-mapa-de-componentes-reales.md`, sección 3.

Ambos cubren un tipo de spoke muy similar (canal/gateway multi-canal con agentes
aislados). No se decidió si el sistema debe recomendar soportar solo uno de fábrica, o
ambos simultáneamente con asignación de canales distintos por configuración del
usuario, ni qué criterio debería guiar esa elección si el usuario no expresa una
preferencia.

**Resolución:** no hay selección que hacer. Los canales son territorio exclusivo de
`channel-gateway` (fork de OpenClaw); el gateway multi-canal de Hermes no se extrae. Y
entre harnesses base no existe arbitraje dinámico: cada capacidad de harness base tiene
un único dueño declarado en `config/janus.toml`
(`stack/05-harnesses-hermes-openclaw.md`, sección 3, y
`stack/07-descubrimiento-y-capacidades.md`, sección 1.3).

## 8. Alcance exacto del pipeline STT↔TTS propio — PARCIALMENTE RESUELTA
**Origen:** `00-vision-y-alcance.md`, sección 4.

Se estableció que Janus debe construir un pipeline de voz propio (potencialmente
usando frameworks como Whisper/Kokoro u otros) *solo si* ningún spoke soportado
resuelve esto de forma completa (Principio Arquitectónico #2). No se ha hecho aún el
relevamiento explícito de si alguno de los spokes candidatos (particularmente Hermes,
que se menciona con soporte de voz) ya cubre esto satisfactoriamente, lo cual
determinaría si este pipeline propio es necesario en absoluto o en qué medida.

**Resuelto:** la voz es territorio de Janus, no de Hermes (el voice mode de Hermes no se
extrae; `stack/05-harnesses-hermes-openclaw.md`, sección 3). Defaults de fábrica: Kokoro
para TTS y Whisper (o `faster-whisper`) para STT, con proveedor intercambiable por
agente mediante `voice_provider` en `AgentPersona` (`agents/05-voz.md`).

**Residual resuelto por las specs:** el código propio de voz vive en `libs/voice/`
(`specs/spec-13-voice.md`), invocado por el núcleo como capacidad propia. Queda abierta
la conversación dúplex en tiempo real, fuera del alcance de la primera versión.

## 9. Modelo de multi-tenencia / multi-usuario — RESUELTA (redefinida como multi-sesión de un único dueño; residual de concurrencia interna cerrado 2026-09-20)
**No se había discutido en ningún documento anterior.**

Toda la arquitectura descrita asume un único usuario dueño del sistema. La pregunta
original planteaba si Janus debía contemplar, a nivel de diseño futuro, más de un
usuario compartiendo una misma instancia (con sesiones, preferencias y memoria
aisladas entre sí).

**Aclaración del usuario:** el caso real que le importa no es multi-tenencia (varios
dueños aislados entre sí) sino **multi-sesión concurrente de un mismo dueño por
distintos canales** — ejemplo dado: el usuario le pide a Janus por voz desde la cocina
que prenda una luz mientras Janus está a mitad de una tarea de código pedida por texto.
Esto es un caso distinto al de multi-tenencia y no requiere aislar memoria ni
preferencias entre "usuarios", porque sigue siendo un único dueño.

**Resolución:**
- Multi-tenencia real (múltiples dueños) se descarta como objetivo de diseño. Janus
  sigue siendo mono-usuario a nivel de identidad, persistencia y memoria.
- El caso de múltiples solicitudes concurrentes del mismo usuario por canales
  distintos **sí es un requisito confirmado**: Janus debe poder atender solicitudes
  concurrentes sin serializarlas (no basta con que las tareas delegadas a subagentes
  corran en paralelo, como ya cubre `agents/07-concurrencia.md`; Janus mismo, como
  agente líder que conversa directamente con el usuario, debe poder procesar más de
  una conversación/solicitud propia a la vez).

**Residual cerrado 2026-09-20:** `agents/07` fija que Janus está exento de todo tope de
concurrencia y nunca hace cola, pero asumía implícitamente que Janus procesa una
interacción conversacional a la vez. El diseño concreto quedó confirmado en
`specs/spec-11-core-gateway.md`, requisitos 22 y 22bis: un `AgentRuntime` de Janus por
sesión principal (misma task de asyncio por sesión, sin lock compartido salvo el que ya
exige consistencia de memoria/persistencia); visibilidad entre sesiones por pull
(`get_task_status`) y memoria compartida, nunca por resumen inyectado; interrupción
configurable por modo de canal (cola FIFO en texto, cancelar y refundir en voz); y un
mecanismo de aviso selectivo (`task_finalize` con regla decidida en código, checklist de
subtareas sin costo de turno, cola de baja prioridad para pedidos internos de
subagentes vía `request_delegation`) pensado explícitamente para que la concurrencia
interna de Janus no dispare un consumo de tokens proporcional a la granularidad del
trabajo delegado. Impacto aplicado también en spec 01 (`TaskChecklistItem`, `required`),
spec 03 (`checklist_json`, `tasks.mark_checklist_item`), spec 06 (evento
`task.subitem_changed`) y spec 12 (aprobación por tipo de acción en GUI automation,
residual relacionado surgido en la misma discusión).

## 10. Política de resolución de errores en cascada entre tareas dependientes — RESUELTA
**Origen:** `05-modelo-de-roles-y-tareas.md`, sección 4.

Se estableció que una tarea puede depender de otra y que el núcleo no debe iniciarla
hasta que la dependencia esté satisfecha, pero no se definió qué ocurre cuando la tarea
de la que depende **falla** en lugar de completarse — si la tarea dependiente se cancela
automáticamente, queda bloqueada indefinidamente, o se reasigna a otro rol/spoke para
reintento.

Las políticas de fallo de `stack/09-politicas-de-fallo.md` se declaran por harness o
spoke y no cubren dependencias entre tareas.

**Resolución, según el usuario:** no es una política estática por tarea (`BLOCK` |
`CANCEL` | `RETRY_REASSIGN` como enum fijo). Es el mismo patrón ya confirmado para el
fallback de capacidades (pregunta 1): Janus, como agente orquestador, decide en
runtime si el fallo de una dependencia es mitigable reintentando o si amerita
discutirse con el usuario — no una tabla codificada de antemano. Ver
`specs/spec-11-core-gateway.md`, requisito 20 (`DependencyFailureTriage`), para el
diseño concreto.

## 11. Tecnología concreta para detección de elementos y síntesis de input en automatización de interfaz gráfica — PARCIALMENTE RESUELTA
**Origen:** `10-automatizacion-de-interfaz-grafica.md`, secciones 3 y 4.

Se fijó el patrón de interacción (mapa de hints estilo Vimium/Vim) y las tres
estrategias de vigencia del mapeo (tiempo real, configuración asistida reutilizable,
detección de invalidación), pero no la tecnología/framework concreto que implementaría
la detección de elementos interactuables (p. ej. vía árboles de accesibilidad del
sistema operativo, visión por computadora sobre una captura de pantalla, u otro medio)
ni la síntesis de input (inyección de eventos de teclado/mouse a nivel de sistema
operativo). Se mencionó, sin comprometerse, que podría existir "un framework mejor"
ya disponible — su evaluación queda pendiente.

**Resuelto:** la implementación se divide entre `crates/gui-automation/` en Rust
(captura de pantalla, inyección de eventos de input a nivel de OS, posible OCR/visión),
expuesto a Python vía PyO3/maturin, y la orquestación de alto nivel en `core-gateway`.
Linux vía X11/Wayland es la prioridad real (`stack/10-gui-automation-y-licencia.md`,
sección 1).

**Residual abierto:** la biblioteca o framework concreto de Rust para detección de
elementos y para inyección de input, diferida a la fase `/spec` de ese componente.

**Propuesta pendiente de confirmar** (`specs/spec-12-gui-automation.md`): detección por
árbol de accesibilidad (`atspi`), captura con `xcap`, input con `enigo` y backends de
ventanas intercambiables según el compositor, con un spike de validación antes de fijar
la API. Se advierte que Wayland no ofrece una API única y que Raspberry Pi OS lo usa por
defecto.

**Confirmación del usuario:** el enfoque general (detección por árbol de
accesibilidad, en vez de visión/OCR como estrategia primaria) queda confirmado. Las
librerías específicas (`atspi`, `xcap`, `enigo`) quedan como candidatas a revisar
cuando se ejecute el spike de la fase 0 de la spec 12, tal como esa spec ya lo trata —
no se fija su elección final todavía.

## 12. Alcance de aplicaciones soportadas de fábrica vía automatización de interfaz gráfica — RESUELTA
**Origen:** `10-automatizacion-de-interfaz-grafica.md`, sección 1.

Se estableció que el mecanismo es genérico y aplicable a cualquier aplicación de
escritorio, no solo a Claude Desktop y Gemini Desktop. Estaba abierto si Janus debía
traer, de fábrica, adaptadores específicos para otras aplicaciones adicionales, o si
solo el mecanismo genérico se libera de fábrica dejando los adaptadores puntuales para
la comunidad/usuario.

**Resolución:** mecanismo genérico de fábrica, más un puñado adicional de adaptadores
de fábrica más allá de Claude Desktop y Gemini Desktop. La lista concreta de qué
aplicaciones adicionales se incluyen queda pendiente como tarea de producto (no de
arquitectura) — se decide al planificar la spec 15 o en una iteración posterior, sin
bloquear el resto del diseño.

## 13. Futuro de Relay dentro de Janus — RESUELTA
**Origen:** `08-mapa-de-componentes-reales.md`, sección 4.

Se identificaron dos rutas posibles — tratar a Relay como un spoke más que aporta una
capacidad ya resuelta, o migrar su lógica para que sea parte nativa del Registro de
Capacidades del núcleo — sin decidir cuál de las dos se seguirá.

**Resolución, según el usuario:** ninguna de las dos rutas tal cual. Relay (el
proyecto personal `claude-toolkit` de gestión de múltiples perfiles de Claude
Desktop) es útil pero está atado a mecanismos específicos de Linux; no se adopta su
código ni se migra su lógica actual. Se conserva su **función** (orquestar múltiples
perfiles/instancias de un mismo harness cuando uno se agota) pero **reescrita desde
cero** para ser dinámica y portable, sin atarse a Linux.

Esa función reescrita vive como un **spoke propio de Janus**: ni spoke externo de
terceros ni lógica del núcleo, sino un adaptador cuyo código vive dentro del monorepo
de Janus y que reemplaza a Relay por completo. En términos del contrato de spoke
(`03-contrato-de-spoke.md`), no es un tipo nuevo — la distinción "propio" vs "externo"
es de propiedad del código del adaptador, no de la naturaleza de la capacidad que
aporta (que sigue siendo tipo 2.1 o 2.4 según el harness que orqueste). Relay como
proyecto (`claude-toolkit`) queda deprecado una vez que este spoke propio lo
reemplace; no hay período de transición donde ambos operen en paralelo por diseño,
más allá del tiempo que tome la reescritura.

**Residual para `/spec`:** diseño concreto del spoke propio (multiplataforma desde el
inicio, no solo Linux) que reemplaza a `claude-toolkit`/Relay. No tiene spec propia
todavía entre las 15 escritas; se agrega como spec nueva o se incorpora a la 15
(adaptadores concretos de spoke) al planificar el kanban.

## 14. Reconocimiento biométrico de voz y cara como señal de identidad — RESUELTA A NIVEL DE ALCANCE, DETALLE DIFERIDO A `/spec`
**Origen:** discusión de la sesión 2026-09-20, a raíz del residual de la pregunta 3
(identidad de remitente por canal).

Surgió al discutir cómo verificar al dueño en canales de voz/hogar (ejemplo del
usuario: un speaker en la cocina). Es una capacidad nueva, sin precedente en
`agents/05-voz.md` (que cubre síntesis y transcripción, STT/TTS, no reconocimiento de
hablante ni reconocimiento facial).

**Alcance confirmado por el usuario:**
- **Sensores:** voz y cámara, ambos soportados; el usuario decide qué dispositivos
  conectar (pueden ser varios, de distintos medios) y en qué canales/ámbitos activar
  cada uno.
- **Relación con las otras señales de identidad (pregunta 3):** totalmente
  configurable por canal — la biometría puede convivir con el desafío `.md`, con el
  identificador de plataforma, con ambas, o operar sola. No hay una regla única de
  "reemplaza" o "complementa"; es una matriz de configuración por canal.
- **Procesamiento:** local, sin nube. Los modelos de reconocimiento corren en el
  hardware del hogar (Raspberry Pi u otro), consistente con el criterio ya fijado en
  `stack/01-contexto-y-lenguajes.md` de bajo consumo y sin dependencias externas
  obligatorias. Esto descarta explícitamente servicios de reconocimiento en la nube
  para esta capacidad, por la naturaleza sensible de datos biométricos.

**Lo que esto NO fija (queda para `/spec` cuando se planifique este componente):**
- Modelo(s) concretos de reconocimiento de voz (speaker verification/identification) y
  de cara (face recognition), y su viabilidad de rendimiento en el hardware objetivo
  (mismo tipo de compuerta de rendimiento que ya se aplicó a Kokoro en la spec 13).
- Dónde y cómo se almacenan los embeddings biométricos de referencia del dueño
  (nunca la señal cruda de voz/imagen persistida más allá de lo necesario para
  generar el embedding), y su protección en reposo.
- Umbral de confianza para aceptar una coincidencia y comportamiento ante
  incertidumbre (¿cae al desafío `.md` si la confianza es baja? ¿bloquea? ¿pregunta?).
- A qué tipo de spoke pertenece esta capacidad en términos del contrato
  (`03-contrato-de-spoke.md`) — probablemente una capacidad propia de Janus expuesta a
  través del flujo de canales (similar en espíritu a la voz de `stack/05` sección 3:
  invocación de Janus, no un harness externo), a confirmar al escribir la spec.
- Sin spec propia todavía; se agrega al planificar el kanban, probablemente
  dependiente de o adyacente a la spec 13 (`libs/voice/`).
