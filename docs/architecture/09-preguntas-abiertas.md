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

## 1. Política de prioridad entre criterios de selección de spoke — PARCIALMENTE RESUELTA
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
sujeta a una política de aprobación configurable (`ask_everytime`, `allow_always` y
variantes), global con override por agente (`agents/06-cambio-dinamico-de-modelo.md`).

**Residual abierto:** el orden de prioridad entre los tres criterios cuando entran en
conflicto para capacidades que no son cambio de proveedor de modelo, y si esa prioridad
es global o configurable por capacidad/rol.

## 2. Mecanismo concreto de captura y consulta de memoria de largo plazo — PARCIALMENTE RESUELTA
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

**Residual abierto:** qué dispara la escritura de una entrada en memoria (captura
automática por la infraestructura vs. decisión explícita del agente).
`agents/02-memoria.md` no lo fija.

## 3. Mecanismo de autenticación/autorización para control externo — PARCIALMENTE RESUELTA
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

**Residual abierto:** cómo se verifica que quien emite una orden de control a través de
un canal de mensajería o de voz es el usuario legítimo. Los tokens cubren el acceso de
componentes y spokes al Core de Traducción, no la identidad del remitente en el canal.

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

## 5. Procedencia de OpenClaude y su efecto en decisiones de extensión propia — ABIERTA
**Origen:** `08-mapa-de-componentes-reales.md`, sección 2.

Se documentó que OpenClaude deriva del código base de Claude Code (no liberado
oficialmente por Anthropic), consumido por Janus únicamente como spoke externo vía su
servidor gRPC. Queda abierto si en algún momento se considera extender directamente ese
código base (en lugar de solo consumirlo como spoke), y si esa decisión tendría
implicaciones legales que no aplican al modelo actual de "solo consumo vía protocolo
externo".

`stack/` y `agents/` no tratan a OpenClaude; la pregunta sigue en pie sin cambios.

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

**Residual abierto:** dónde vive el código propio de voz. `stack/05` lo describe como
"librería propia a definir", y no figura en el layout del monorepo
(`stack/02-monorepo.md`) ni en las specs pendientes de `TODO.md`.

## 9. Modelo de multi-tenencia / multi-usuario — ABIERTA
**No se ha discutido en ningún documento anterior.**

Toda la arquitectura descrita asume un único usuario dueño del sistema. No se ha
evaluado si Janus debe contemplar, incluso a nivel de diseño futuro, más de un usuario
compartiendo una misma instancia (con sesiones, preferencias y memoria aisladas entre
sí), lo cual tendría implicaciones en el modelo de persistencia (documento 06) y en el
de autenticación (pregunta 3 de este documento).

`stack/01-contexto-y-lenguajes.md` fija el contexto de despliegue actual como el de una
sola persona en un solo host. Eso acota la versión actual, pero no evalúa un futuro
multi-usuario.

## 10. Política de resolución de errores en cascada entre tareas dependientes — ABIERTA
**Origen:** `05-modelo-de-roles-y-tareas.md`, sección 4.

Se estableció que una tarea puede depender de otra y que el núcleo no debe iniciarla
hasta que la dependencia esté satisfecha, pero no se definió qué ocurre cuando la tarea
de la que depende **falla** en lugar de completarse — si la tarea dependiente se cancela
automáticamente, queda bloqueada indefinidamente, o se reasigna a otro rol/spoke para
reintento.

Las políticas de fallo de `stack/09-politicas-de-fallo.md` se declaran por harness o
spoke y no cubren dependencias entre tareas.

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

## 12. Alcance de aplicaciones soportadas de fábrica vía automatización de interfaz gráfica — ABIERTA
**Origen:** `10-automatizacion-de-interfaz-grafica.md`, sección 1.

Se estableció que el mecanismo es genérico y aplicable a cualquier aplicación de
escritorio, no solo a Claude Desktop y Gemini Desktop. No se decidió si Janus debe
traer, de fábrica, adaptadores específicos (en el sentido de la sección 5 de ese
documento) para otras aplicaciones adicionales, o si el mecanismo genérico de
plataforma se libera de fábrica y los adaptadores específicos por aplicación quedan
como responsabilidad de la comunidad/usuario, en línea con el contrato de integración
abierto del documento 02.

## 13. Futuro de Relay dentro de Janus — ABIERTA
**Origen:** `08-mapa-de-componentes-reales.md`, sección 4.

Se identificaron dos rutas posibles — tratar a Relay como un spoke más que aporta una
capacidad ya resuelta, o migrar su lógica para que sea parte nativa del Registro de
Capacidades del núcleo — sin decidir cuál de las dos se seguirá, ni si Relay continúa
operándose de forma independiente durante una transición.
