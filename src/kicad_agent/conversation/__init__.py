"""Phase 204 kicad-agent-5q8: Conversation modes — Design/Review/Debug/Optimization/Manufacturing/Teaching.

Six modes that reframe the assistant's behavior. Each mode is a lens on
the same circuit/project. See modes.py for full documentation.
"""
from kicad_agent.conversation.modes import (
    ConversationMode,
    Mode,
    ModeRegistry,
    get_mode,
    select_mode_for_intent,
)

__all__ = [
    "ConversationMode",
    "Mode",
    "ModeRegistry",
    "get_mode",
    "select_mode_for_intent",
]
