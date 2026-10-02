import re

REASONING_COMPLETE = "reasoning.complete"
EXECUTION_RUN_TASK = "execution.run_task"
CHANNEL_DELIVER = "channel.deliver"
GUI_WINDOW_CONTROL = "gui.window.control"
GUI_ELEMENTS_MAP = "gui.elements.map"
GUI_TASK_RUN = "gui.task.run"
VISION_UI_LOCATE = "vision.ui.locate"
VISION_UI_STEP = "vision.ui.step"
VOICE_TTS_SYNTHESIZE = "voice.tts.synthesize"
VOICE_STT_TRANSCRIBE = "voice.stt.transcribe"
MEMORY_RECALL = "memory.recall"

ALL_CAPABILITY_IDS = frozenset(
    {
        REASONING_COMPLETE,
        EXECUTION_RUN_TASK,
        CHANNEL_DELIVER,
        GUI_WINDOW_CONTROL,
        GUI_ELEMENTS_MAP,
        GUI_TASK_RUN,
        VISION_UI_LOCATE,
        VISION_UI_STEP,
        VOICE_TTS_SYNTHESIZE,
        VOICE_STT_TRANSCRIBE,
        MEMORY_RECALL,
    }
)

RESERVED_NAMESPACES = frozenset(
    {"reasoning", "execution", "channel", "gui", "vision", "voice", "memory", "janus"}
)

CAPABILITY_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


def is_valid_capability_id(capability_id: str) -> bool:
    return CAPABILITY_ID_PATTERN.fullmatch(capability_id) is not None


def namespace_of(capability_id: str) -> str:
    if not is_valid_capability_id(capability_id):
        raise ValueError(f"invalid capability id: {capability_id!r}")
    return capability_id.split(".", 1)[0]


def is_reserved_namespace(capability_id: str) -> bool:
    return namespace_of(capability_id) in RESERVED_NAMESPACES
