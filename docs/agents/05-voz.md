# Agentes — Voz

Proveedor intercambiable por agente, con defaults propios.

## 1. Defaults de fábrica

Janus trae, de fábrica, proveedores propios de síntesis (TTS) y reconocimiento (STT)
de voz, elegidos por ser gratuitos, ligeros, y viables en el hardware objetivo
(Raspberry Pi incluido, ver `stack/01-contexto-y-lenguajes.md`):

- **TTS por defecto: Kokoro** (82M parámetros, licencia Apache-2.0). Corre en CPU sin
  necesidad de GPU, consenso claro en benchmarks 2026 como la opción "gratuita y
  ligera" de referencia. Limitación conocida: fuerte en inglés, expresividad/control
  de emoción más limitado que alternativas de mayor peso.
- **STT por defecto: Whisper** (o su variante liviana `faster-whisper`, ya usada en el
  propio ecosistema de Hermes según lo verificado en la discusión de tech-stack).

## 2. Intercambiabilidad por agente — mismo patrón que routing de modelo

El proveedor de TTS/STT **no está fijo a nivel de sistema** — es un campo de
`AgentPersona`, configurable por agente individual, con el mismo patrón de
intercambiabilidad ya definido para el routing de modelos de razonamiento
(`stack/05-harnesses-hermes-openclaw.md`, sección 3). Un agente puntual puede usar un
proveedor distinto al default si el caso lo amerita (ejemplo discutido: ElevenLabs o
Fish Speech para un agente que necesite mayor expresividad emocional, si hay GPU
disponible y se acepta el costo/peso correspondiente).

Este campo (`voice_provider` en `AgentPersona`) es de hot-reload simple
(`agents/03-skills-y-config.md`, sección 4): cambiar la voz de un agente no compromete
su identidad de ejecución ni requiere reiniciar su sesión de razonamiento.

---

## Documentos relacionados
- `stack/01-contexto-y-lenguajes.md` — el hardware objetivo (Raspberry Pi) que motiva
  los defaults.
- `stack/05-harnesses-hermes-openclaw.md` — la división de responsabilidades que asigna
  la voz a Janus y no a Hermes.
- `agents/01-modelo-de-agente.md` — `AgentPersona` y su campo `voice_provider`.
- `agents/03-skills-y-config.md` — hot-reload simple para los campos cosméticos.
