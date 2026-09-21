# Agentes — Modelo de agente

Este conjunto de documentos (`agents/`) define el **modelo de agentes**: qué es un agente
de Janus, cómo se compone, cómo se persiste, cómo se le asignan herramientas y voz, cómo
se orquesta y cómo compite por recursos de concurrencia. A diferencia de `architecture/`
(arquitectura pura, sin decisiones de implementación) y de `stack/` (stack de
infraestructura: lenguajes, monorepo, persistencia), `agents/` define el modelo de
agentes. Es la resolución completa del punto 1.1 dejado pendiente en `TODO.md`.

Asume y extiende, sin repetirlas, las decisiones ya fijadas en:
- `architecture/05-modelo-de-roles-y-tareas.md` (Architect/Implementer/Debugger/
  Documenter/DevOps como roles de referencia).
- `architecture/06-modelo-de-persistencia-y-estado.md` (persistencia transversal).
- `stack/05-harnesses-hermes-openclaw.md` (Hermes extraído como `libs/reasoning-engine/`,
  OpenClaw forkeado como `channel-gateway`, división de responsabilidades voz/canales/
  razonamiento).

---

## 1. Qué es un agente de Janus

Un agente de Janus es una **entidad especializada en cierta tarea que actúa como una
"persona aparte"**, a la que se le puede delegar trabajo y que puede operar en
paralelo con otros agentes. Los roles de `architecture/05-modelo-de-roles-y-tareas.md`
(Architect, Implementer, Debugger, Documenter, DevOps) son ejemplos concretos de
agentes; el conjunto de agentes no está cerrado a esa lista — el usuario puede definir
agentes personalizados adicionales.

**Janus mismo es un agente**, con el rol distintivo de "líder": es quien orquesta,
delega, y decide. Esto significa que el diagrama de capas del sistema es:

```
Infraestructura (Core de Traducción, Registro de Capacidades, Persistencia)
        ↓
Agentes (N configuraciones — una de ellas es "Janus", el resto son subagentes)
        ↓
Motor de razonamiento compartido (libs/reasoning-engine/, ex-Hermes)
```

La infraestructura no tiene personalidad ni identidad — es el sustrato sobre el que
corren las configuraciones de agente. "Janus-el-agente-líder" no es lo mismo que "el
Core de Traducción"; es una configuración más, con su propia voz y su propio prompt,
que además tiene un privilegio único: acceso a la tool de orquestación
(`agents/04-orquestacion-y-sesiones.md`).

## 2. Composición: Ejecución vs Cosmética (OOP, composición no herencia)

Todo agente se modela separando dos responsabilidades que nunca se mezclan:

```python
class AgentCore(ABC):
    """Ejecución: modelo, instrucciones, reglas, skills, toolset asignado."""
    model_provider: ModelProviderRef
    system_prompt: str
    rules: list[Rule]
    skills: list[SkillRef]
    toolset: list[ToolRef]        # ensamblado por Janus, ver agents/04-orquestacion-y-sesiones.md

class AgentPersona:
    """Cosmética: voz, personalidad, tono. No es un contrato de comportamiento,
    es composición pura — no implementa AgentCore ni lo extiende."""
    voice_provider: VoiceProviderRef
    tone: str
    personality_prompt: str | None

class Agent:
    """Un agente completo: composición de ambas partes."""
    core: AgentCore
    persona: AgentPersona
    name: str
```

`AgentCore` es `ABC` porque distintos tipos de agente (razonamiento de código, agente
de voz pura, futuros tipos) pueden implementar la ejecución de forma distinta, pero
todos cumplen el mismo contrato. `AgentPersona` no necesita ese contrato — es
configuración de datos, no comportamiento polimórfico.

---

## Documentos relacionados
- `architecture/00-vision-y-alcance.md` — visión general; `agents/` concreta el objetivo
  de "Jarvis personal" y "multi-agente paralelo" enumerado en su sección 4.
- `architecture/05-modelo-de-roles-y-tareas.md` — los roles ahí definidos son la
  instancia concreta del concepto de "agente" definido aquí.
- `stack/05-harnesses-hermes-openclaw.md` — el motor de razonamiento extraído sobre el
  que corren los agentes.
- `agents/02-memoria.md`, `agents/03-skills-y-config.md`,
  `agents/04-orquestacion-y-sesiones.md`, `agents/05-voz.md` — cómo se completa el
  modelo de agente.
