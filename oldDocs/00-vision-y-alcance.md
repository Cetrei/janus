# 00 — Visión y Alcance de Janus

## Estado del documento
Arquitectura pura. Cero decisiones de lenguaje, framework, librería o formato de
persistencia. Cualquier mención a un componente real (Hermes, OpenClaude, OpenClaw,
Claude Desktop, Gemini Desktop) se hace únicamente para ilustrar un rol arquitectónico,
nunca para fijar una implementación. El mapeo detallado de componentes reales vive en
`08-mapa-de-componentes-reales.md`.

---

## 1. Qué es Janus

Janus es un **sistema operativo personal de agentes**: una capa de software propia,
open source, que se sitúa entre el usuario y un conjunto extensible de herramientas de
IA existentes ("spokes"), y que:

1. Es el **único punto de contacto** del usuario — habla con Janus, nunca directamente
   con un spoke individual.
2. Es el **único punto de contacto entre spokes** — ningún spoke habla nunca con otro
   spoke. Ver Principio Arquitectónico #1 en `01-conceptos-y-vocabulario.md`.
3. **No reimplementa capacidades que un spoke ya resuelve bien** — las conecta,
   traduce y expone bajo un modelo semántico único. Ver Principio Arquitectónico #2
   (no-reinvención) en el mismo documento.
4. Es **extensible por contrato**, no por lista cerrada — un tercero debe poder escribir
   un adaptador nuevo sin modificar el núcleo de Janus, cumpliendo un contrato de
   integración mínimo (mínimamente: hablar MCP y/o gRPC contra Janus).
5. Persiste, de forma transversal a todos los spokes, todo lo que le pertenece al
   usuario y no a una herramienta en particular: sesiones, preferencias, tareas,
   memoria, correo, y el propio registro de qué spoke sirve qué capacidad.
6. Expone su estado interno (sesiones vivas, agentes activos, tareas en cola,
   capacidades registradas, resultados) de forma observable y controlable desde
   afuera, para que una futura GUI (o cualquier otro cliente) pueda construirse sin
   rediseñar el núcleo.

## 2. La analogía de referencia

Janus se piensa como un **Jarvis personal**: una interfaz de más alto nivel,
conversacional y potencialmente por voz, de control total sobre la máquina y sobre los
proyectos del usuario. Cualquier cosa que el usuario pueda hacer manualmente en su
computadora — escribir código, ejecutarlo, revisarlo, depurarlo, desplegarlo a
producción, administrar tareas, redactar o leer correo, gestionar preferencias — Janus
debe poder hacerlo también, delegando el trabajo pesado a los spokes correctos y
haciéndolo, idealmente, más rápido que si el usuario lo hiciera él mismo a mano.

El dominio en el que Janus debe ser **más fuerte que cualquier competencia existente**
es el desarrollo de software: arquitectura, implementación, debugging, DevOps. De ahí
que el sistema de roles (ver `05-modelo-de-roles-y-tareas.md`) trate a estos roles como
ciudadanos de primera clase, no como un caso de uso más entre muchos.

## 3. Motivación de origen (contexto, no requisito)

Janus nace de un problema concreto: el acceso "gratuito" a modelos de razonamiento
fuertes (p. ej. Claude vía cuenta de consumo) está fragmentado en múltiples perfiles sin
API expuesta, mientras que las herramientas que sí editan código de verdad requieren una
API de pago. La primera motivación fue resolver ese fragmentado con un pool de modelos
gratuitos con fallback. Esa motivación sigue siendo válida como caso de uso, pero **ha
dejado de ser el objetivo** — el objetivo es el sistema completo descrito en la sección
1. El pool de modelos gratuitos es una instancia particular del **registro de
capacidades** (`04-modelo-de-capacidades-y-enrutamiento.md`), no un módulo aparte.

## 4. Qué debe soportar Janus (catálogo de capacidades objetivo)

Esta lista es el criterio de completitud funcional del sistema. Cada ítem se desarrolla
en su documento correspondiente; aquí solo se enumeran como alcance:

- **Sesiones** — de trabajo, conversación, o ejecución, con persistencia y capacidad de
  reanudarse.
- **Multi-agente paralelo** — más de un agente/rol trabajando de forma concurrente,
  bajo la supervisión de Janus.
- **Skills, roles y MCPs como piezas intercambiables** — no atadas a un spoke
  específico; el mismo rol puede ejecutarse hoy en un spoke y mañana en otro sin que el
  usuario lo perciba.
- **Mensajería multi-plataforma** — el usuario puede interactuar con Janus desde
  distintos canales (chat, Discord, u otros que se agreguen), enrutados de forma
  centralizada.
- **Conversación por voz fluida (STT↔TTS)** — reconocimiento y síntesis de voz
  integrados como una capacidad más del sistema, usando frameworks propios si ningún
  spoke ya cubre esto de forma completa (ver Principio Arquitectónico #2:
  no-reinvención — esto solo se construye si de verdad no hay spoke que lo resuelva).
- **Persistencia transversal** — preferencias del usuario, tareas, correo, memoria de
  largo plazo; todo esto pertenece a Janus, no a ningún spoke individual (ver
  `06-modelo-de-persistencia-y-estado.md`).
- **Administración de proyectos y asignación de tareas** — Janus como capa de gestión
  que reparte trabajo entre roles/spokes y da seguimiento a su estado.

## 5. Qué NO es Janus

Para evitar ambigüedad por omisión, se deja explícito lo que Janus **no** intenta ser:

- **No es un reemplazo de bajo nivel de ningún spoke.** Janus no reimplementa un editor
  de código con conciencia de AST/LSP si OpenClaude (o equivalente) ya lo hace bien; no
  reimplementa un gateway multi-canal si Hermes (o equivalente) ya lo hace bien. Janus
  conecta, no compite a nivel de capacidad individual.
- **No es una malla de agentes que se comunican entre sí.** Es una estrella pura. Ver
  Principio Arquitectónico #1.
- **No es una GUI.** Este documento y los que le siguen definen arquitectura y
  contratos; una GUI es un cliente futuro y opcional que consume la superficie
  observable de Janus (`07-superficie-para-gui-futura.md`), pero su ausencia hoy no
  bloquea ni condiciona el diseño del núcleo.
- **No es una lista cerrada de integraciones.** El soporte "de fábrica" a Hermes,
  OpenClaude, OpenClaw, Claude Desktop y Gemini Desktop es un punto de partida, no un
  límite. Cualquier spoke que cumpla el contrato de integración (`03-contrato-de-
  spoke.md`) debe poder incorporarse sin tocar el núcleo.
- **No asume un único hub permanente.** Ninguna decisión de arquitectura debe asumir
  que un spoke concreto (p. ej. Hermes) es insustituible. El sistema debe seguir
  funcionando, conceptualmente, si ese spoke se reemplaza por otro que cumpla el mismo
  tipo de contrato.

## 6. Criterios de éxito

Janus cumple su propósito cuando:

1. El usuario nunca necesita saber, para pedir algo, qué spoke concreto lo va a
   ejecutar — solo pide, y Janus resuelve el enrutamiento.
2. Agregar un spoke nuevo (o reemplazar uno existente) no requiere modificar el núcleo
   de Janus ni a los demás spokes — solo requiere que el nuevo spoke (o Janus, del lado
   de la traducción) cumpla el contrato de integración.
3. Ninguna capacidad se reimplementa dentro de Janus si ya existe, resuelta, en algún
   spoke soportado.
4. Toda capacidad registrada (una MCP, una herramienta, un modelo) es utilizable por
   cualquier agente/rol del sistema, sin importar en qué spoke se originó, vía
   delegación a través de Janus.
5. El estado completo del sistema (sesiones, agentes vivos, tareas, capacidades) es
   observable y controlable desde afuera del núcleo, habilitando una GUI futura sin
   rediseño.
6. El usuario puede, en el dominio de desarrollo de software, ejecutar el ciclo
   completo (arquitectura → implementación → debugging → devops) a través de Janus,
   con trazabilidad de qué rol/spoke hizo qué.

## 7. Documentos relacionados

- `01-conceptos-y-vocabulario.md` — vocabulario unificado y Principios Arquitectónicos
  #1 (estrella pura) y #2 (no-reinvención).
- `02-arquitectura-estrella-y-contrato-de-integracion.md` — el modelo central y su
  mecanismo de extensibilidad.
- `03-contrato-de-spoke.md` — qué debe cumplir la traducción de Janus hacia cada tipo de
  spoke.
- `04-modelo-de-capacidades-y-enrutamiento.md` — registro y delegación de capacidades.
- `05-modelo-de-roles-y-tareas.md` — Architect/Implementer/Debugger/Documenter/DevOps.
- `06-modelo-de-persistencia-y-estado.md` — qué pertenece a Janus de forma transversal.
- `07-superficie-para-gui-futura.md` — requisitos de observabilidad/control externo.
- `08-mapa-de-componentes-reales.md` — inventario concreto de spokes de referencia,
  incluyendo Relay.
- `09-preguntas-abiertas.md` — todo lo aún no decidido, explícito.
- `10-automatizacion-de-interfaz-grafica.md` — mecanismo de control de spokes de tipo
  aplicación de escritorio cerrada (Claude Desktop, Gemini Desktop, y otras).
