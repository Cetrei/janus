# 08 — Mapa de Componentes Reales

## Estado del documento
Este es el único documento de `architecture/` que nombra spokes concretos y describe sus
capacidades observadas. Aun así, **no fija implementación de sus adaptadores** — solo
clasifica cada spoke según el modelo de tipos definido en `03-contrato-de-spoke.md` y
señala qué capacidades aportaría al Registro de Capacidades (`04-modelo-de-
capacidades-y-enrutamiento.md`). Ninguna jerarquía entre los spokes externos está
implícita: por el Principio Arquitectónico #1, todos se conectan a Janus de la misma
forma estructural.

**Actualización posterior al tech-stack.** Este documento se escribió antes de fijar el
stack (`stack/`). Allí se decidió que Hermes y OpenClaw no se conectan como spokes
externos sino como **harnesses base**: infraestructura fija de Janus (Hermes extraído
quirúrgicamente como librería interna, OpenClaw forkeado completo como proceso propio),
sin arbitraje dinámico entre ellos. Los demás componentes de este documento (OpenClaude,
Relay, Claude Desktop, Gemini Desktop) siguen siendo spokes externos. Las secciones 1, 3
y 7 reflejan esa decisión; el detalle de implementación vive en
`stack/05-harnesses-hermes-openclaw.md`.

Este documento refleja el estado del conocimiento disponible al momento de escribirlo
(septiembre 2026) y debe tratarse como el más propenso a quedar desactualizado del
conjunto — los demás documentos son estables porque son arquitectura pura; este no.

---

## 1. Hermes

**Estatus en Janus: harness base, no spoke externo.** Se extrae quirúrgicamente del
proyecto upstream (`NousResearch/hermes-agent`) hacia `libs/reasoning-engine/`, como
librería interna de Python. No corre como proceso ni servicio aparte. Qué se trae y qué
no se detalla en `stack/05-harnesses-hermes-openclaw.md`.

**Tipo(s) de spoke (upstream, antes de la extracción):** razonamiento (vía BYOM) +
ejecución (parcial) + canal/gateway multi-canal. En Janus solo se conserva la parte de
razonamiento/ejecución; el gateway multi-canal de Hermes no se extrae, porque los
canales son territorio exclusivo de `channel-gateway`.

**Capacidades relevantes observadas (upstream; no todas se extraen):**
- Gateway multi-canal ya construido: Telegram, Slack, WhatsApp, Discord, voz.
- Orquestador de tareas con persistencia propia (`kanban`).
- Servidor **y** cliente MCP nativos (habla MCP en ambas direcciones).
- Multi-perfil nativo (`hermes profile`).
- BYOM amplio (reportado ~200+ modelos).
- Cron, webhooks, ACP.

**Limitación relevante para el rol de Implementer/Debugger:** no navega codebases ni
hace edición consciente de AST/LSP — es débil como editor de código real en un repo.
Esto significa que, dentro del modelo de roles (documento 05), cuando un rol requiere
edición de código consciente de estructura, esa capacidad debe resolverse delegando a
un spoke de tipo ejecución como OpenClaude.

**Nota de procedencia:** licencia MIT, confirmada compatible con fork, modificación y
redistribución. La política de seguimiento del upstream (revisión mensual filtrada a
nuevos proveedores de modelo y advisories de seguridad) está en
`stack/05-harnesses-hermes-openclaw.md`, sección 4.

## 2. OpenClaude

**Tipo(s) de spoke:** ejecución (principalmente) + razonamiento.

**Capacidades relevantes observadas:**
- "Cirujano de código": repo-map / inteligencia de codebase real, tipo LSP — la
  capacidad de edición de código más fuerte entre los spokes evaluados.
- Servidor headless **gRPC** con streaming bidireccional, pensado para integrarse en
  otras apps, CI/CD, o UIs custom — esta es, en los términos de esta arquitectura, una
  cara nativa que el adaptador de Janus puede consumir directamente como cliente gRPC,
  sin necesitar imitar ningún otro protocolo.
- Tabla amplia de proveedores de modelo: Gemini vía API key, OpenRouter/DeepSeek/Groq/
  Mistral vía path OpenAI-compatible, Ollama local sin key, GitHub Models con
  onboarding integrado, perfiles guardados por proveedor.
- Enrutamiento de modelo por agente/rol ya incorporado (`agentModels` +
  `agentRouting`), con límite de pasos por sub-agente (`maxSteps`) — esto es, dentro de
  OpenClaude mismo, un mecanismo de asignación rol→modelo análogo (pero interno a ese
  spoke) al que Janus implementa a nivel de todo el sistema en el documento 05. Janus
  no necesita duplicar esa lógica interna de OpenClaude; puede tratarla como
  configuración propia de ese spoke y limitarse a asignarle tareas de rol Implementer/
  Debugger a nivel de Janus.

**Limitaciones relevantes:**
- No tiene servidor MCP propio.
- No tiene gateway multi-canal — es un CLI de sesión. Para que el usuario pueda pedirle
  trabajo a OpenClaude desde un canal de mensajería o voz, la solicitud debe entrar por
  un componente de tipo canal (en Janus, `channel-gateway`, el harness base derivado de
  OpenClaw) y ser traducida por Janus hacia el adaptador de OpenClaude — nunca
  conectando ambos componentes entre sí directamente.
- No es multi-agente concurrente entre sesiones aisladas escuchando canales distintos
  simultáneamente (sí tiene sub-agentes/tareas dentro de una sesión, y sesiones en
  background gestionables vía CLI).

**Nota de procedencia (relevante, no descartable):** OpenClaude es, según su propio
README, derivado del código base de Claude Code, sustancialmente modificado. La
licencia MIT del repositorio cubre las modificaciones de sus contribuidores; el código
base derivado de Claude Code permanece bajo la titularidad legal de Anthropic, sin
haber sido liberado oficialmente por Anthropic. Esto no impide su uso, pero es relevante
si Janus (u otro componente del usuario) llegara a extender directamente ese código
base en lugar de consumirlo solo como spoke externo vía su servidor gRPC. Se deja
explícito en `09-preguntas-abiertas.md` si esto condiciona alguna decisión futura.

## 3. OpenClaw

**Estatus en Janus: harness base, no spoke externo.** Se forkea completo en
`packages/channel-gateway-core/` (TypeScript) y corre como proceso propio en
`apps/channel-gateway/`. Su rol en Janus es puro transporte de canales: no decide
personalidad ni razona. Detalle en `stack/05-harnesses-hermes-openclaw.md`.

**Tipo(s) de spoke (upstream):** canal/gateway multi-canal + ejecución de automatización
general.

**Capacidades relevantes observadas:**
- Corre como proceso Node.js daemon de larga vida ("Gateway").
- Soporta múltiples agentes aislados bajo ese mismo proceso, cada uno con memoria y
  permisos separados; permite spawnear agentes dinámicamente desde una conversación.
- Gateway multi-canal (Telegram/Slack/WhatsApp/Discord), similar en superficie a
  Hermes.
- Existe un plugin que envuelve harnesses de código (Claude Code, Codex) como backend
  de ejecución.

**Limitaciones relevantes:**
- Es un asistente personal/automatización de propósito general (notas, recordatorios,
  cron jobs, bots) — no es un editor de código nativo. Cuando ejecuta código, lo hace
  invocando otro harness como subproceso, lo cual, si ese harness requiere una API de
  pago, no resuelve el problema de origen por sí solo (ver documento 00, sección 3).
- Bajo esta arquitectura, OpenClaw **no debe** invocar directamente a OpenClaude (o a
  cualquier otro spoke de ejecución) como subproceso propio dentro de la instalación de
  Janus — eso sería comunicación entre componentes sin pasar por el núcleo y viola el
  Principio Arquitectónico #1. Si se usa OpenClaw como canal dentro de Janus, la
  delegación hacia un spoke de ejecución debe pasar por el núcleo, no por el mecanismo
  interno de plugin de OpenClaw. Esto es una restricción de uso, no una limitación
  técnica de OpenClaw en sí.

**Solapamiento con Hermes (resuelto):** upstream, ambos cubren un tipo de spoke muy
similar (canal/gateway multi-canal con agentes aislados). En Janus no hay solapamiento:
el gateway multi-canal de Hermes no se extrae, los canales son territorio exclusivo de
`channel-gateway`, y entre harnesses base no existe arbitraje dinámico — cada capacidad
de harness base tiene un único dueño declarado en `config/janus.toml`
(`stack/05-harnesses-hermes-openclaw.md` sección 3 y
`stack/07-descubrimiento-y-capacidades.md` sección 1).

## 4. Relay

**Tipo(s) de spoke:** orquestación de roles (capa de razonamiento aplicada a
desarrollo de software) + coordinación multi-perfil.

**Naturaleza:** a diferencia de los tres anteriores, Relay no es un proyecto externo
adoptado — es código propio del usuario, construido antes de Janus, que ya implementa
una versión temprana y más limitada del modelo de roles descrito en el documento 05:
asignación de roles fijos (Architect/Implementer/Debugger/Documenter) a distintos
perfiles de un mismo spoke de razonamiento, con seguimiento básico de disponibilidad
por perfil (marcar un perfil como agotado hasta una fecha, marcarlo disponible de
nuevo, listar perfiles y su disponibilidad).

**Capacidades relevantes observadas:**
- Envía un prompt a otro perfil de un mismo spoke de razón dentro de su propio
  contexto/ventana (análogo a lo que el documento 04 llama delegación de una
  capacidad de razonamiento a un proveedor específico).
- Asigna y quita un rol a un perfil (`set_profile_role` / `clear_profile_role`),
  análogo directo a la asignación rol→spoke del documento 05, pero hoy acotado a
  perfiles de un mismo spoke en lugar de a spokes distintos.
- Rastrea disponibilidad/agotamiento de cuota por perfil (`mark_exhausted` /
  `mark_available` / `get_usage`), análogo directo al criterio de "disponibilidad/
  cuota" del Registro de Capacidades (documento 04, sección 3).
- Puede cerrar la ventana de un perfil específico.

**Relación con Janus:** Relay es, en esencia, un prototipo funcional acotado de dos
piezas que en Janus se generalizan a nivel de todo el sistema: el Registro de
Capacidades (documento 04) y el modelo de Roles (documento 05). Bajo esta
arquitectura, Relay no desaparece necesariamente — puede tratarse como un spoke más
que aporta la capacidad ya resuelta de "despachar un prompt a un perfil específico de
un spoke de razonamiento cerrado", consumida por Janus como una capacidad entre muchas,
en lugar de que el usuario siga operándolo como sistema aparte. Alternativamente,
su lógica puede migrar a ser parte nativa del Registro de Capacidades del núcleo de
Janus — esta decisión se dejaría explícita como pregunta abierta si se retoma en el
futuro.

**Limitación relevante:** Relay opera hoy sobre perfiles de un único tipo de spoke de
razonamiento (múltiples ventanas de una misma aplicación), no sobre múltiples spokes
heterogéneos — esa generalización a heterogeneidad total de spokes es exactamente lo
que el diseño completo de Janus provee y Relay, por sí solo, no.

## 5. Claude Desktop

**Tipo(s) de spoke:** razonamiento.

**Capacidades relevantes observadas:**
- Acceso "gratuito" vía cuenta de consumo (sujeto a límites de mensajes por ventana de
  tiempo), sin exponer una API key utilizable por herramientas externas.
- Cerrado: sin API de extensión pública más allá de ser cliente de MCP.

**Consecuencia para el adaptador:** dado que Claude Desktop no expone un servidor ni
una API que Janus pueda invocar de forma programática convencional, su adaptador se
clasifica como tipo 2.4 ("spoke controlado por automatización de interfaz gráfica",
ver documento 03) — Janus lo opera mediante control de ventana + mapa de elementos
interactuables, mecanismo desarrollado en detalle en
`10-automatizacion-de-interfaz-grafica.md`. Esto reemplaza la ambigüedad que este
documento dejaba abierta en una versión anterior ("mecanismo exacto TBD"): el
mecanismo ya está definido a nivel de arquitectura, aunque su configuración concreta
para la ventana específica de Claude Desktop siga siendo un detalle de implementación.

**Nota de fragmentación (motivación de origen):** el problema de los "9 perfiles" nace
específicamente de esta superficie — múltiples cuentas de consumo sin API expuesta, que
se agotan de forma independiente. Bajo esta arquitectura, cada perfil/cuenta puede
representarse como una capacidad de razonamiento registrada por separado, con su propia
disponibilidad de cuota, resuelta por la política de selección con fallback descrita en
el documento 04 — el usuario deja de tener que cambiar de perfil manualmente porque
Janus lo hace por él a nivel de enrutamiento de capacidades.

## 6. Gemini Desktop

**Tipo(s) de spoke:** razonamiento.

**Capacidades relevantes observadas:**
- Aplicación nativa de Google: lanzada para macOS en abril de 2026, y para Windows el
  10 de septiembre de 2026 (activada con Alt+Space).
- Cerrada, sin API de extensión pública conocida más allá de lo que exponga
  nativamente; no se ha identificado un servidor MCP propio.

**Consecuencia para el adaptador:** misma clasificación que Claude Desktop — spoke de
razonamiento de tipo 2.4, operado vía el mecanismo de automatización de interfaz
gráfica descrito en `10-automatizacion-de-interfaz-grafica.md`.

**Relación con el free tier de Gemini vía API:** es importante no confundir Gemini
Desktop (esta app cerrada) con la API de Gemini, que sí ofrece una cuota gratuita real
y que puede consumirse como una capacidad de razonamiento adicional, registrada de
forma independiente — potencialmente sin necesitar un adaptador de tipo "imitación de
entorno cerrado" en absoluto, si se accede vía su API estándar en lugar de vía la app
de escritorio.

## 7. Tabla resumen de tipos

| Componente        | Estatus en Janus | Razonamiento | Ejecución | Canal / Gateway | GUI automation |
|-------------------|------------------|:---:|:---:|:---:|:---:|
| Hermes            | Harness base (extraído) | ✅ (BYOM) | parcial (sin AST/LSP) | ❌ en Janus (el gateway upstream no se extrae) | ❌ |
| OpenClaude        | Spoke externo | ✅ | ✅ (fuerte, AST/LSP) | ❌ | ❌ |
| OpenClaw          | Harness base (fork) | — (delega a harness) | ✅ (vía subprocesos, fuera del alcance recomendado dentro de Janus) | ✅ | ❌ |
| Relay             | Sin definir (ver `09-preguntas-abiertas.md`, pregunta 13) | ✅ (orquesta perfiles de un spoke) | ❌ | ❌ | ❌ |
| Claude Desktop    | Spoke externo | ✅ | ❌ | ❌ | ✅ (única vía disponible) |
| Gemini Desktop    | Spoke externo | ✅ | ❌ | ❌ | ✅ (única vía disponible) |

Esta tabla es un resumen de conveniencia; la fuente de verdad conceptual es la
clasificación narrativa de cada sección anterior.

## 8. Documentos relacionados
- `03-contrato-de-spoke.md` — el contrato genérico por tipo que cada uno de estos
  adaptadores debe cumplir, incluyendo el tipo 2.4 usado por Claude Desktop y Gemini
  Desktop.
- `04-modelo-de-capacidades-y-enrutamiento.md` — cómo se registran y seleccionan las
  capacidades listadas aquí cuando hay solapamiento, y cómo el prototipo de Relay se
  relaciona con el Registro de Capacidades.
- `10-automatizacion-de-interfaz-grafica.md` — el mecanismo concreto que implementa el
  adaptador de Claude Desktop y Gemini Desktop.
- `09-preguntas-abiertas.md` — procedencia de OpenClaude y futuro de Relay dentro de
  Janus, aún no resueltos.
- `stack/05-harnesses-hermes-openclaw.md` — decisión de tratar a Hermes y OpenClaw como
  harnesses base, y cómo se integra cada uno.
