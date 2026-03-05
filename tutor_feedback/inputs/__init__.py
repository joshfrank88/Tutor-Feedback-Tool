"""Input adapters for different sources (paste, future: MCP/Granola)."""

from tutor_feedback.inputs.base import SessionInput
from tutor_feedback.inputs.paste_input import paste_to_session_input

__all__ = ["SessionInput", "paste_to_session_input"]
