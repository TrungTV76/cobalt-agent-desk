"""Built-in read-only agent adapters."""

from __future__ import annotations

from cobalt_desk.adapters.antigravity import AntigravityAdapter
from cobalt_desk.adapters.base import AdapterScanResult, BaseAgentAdapter
from cobalt_desk.adapters.claude import ClaudeAdapter, is_pid_alive

__all__ = [
    "AdapterScanResult",
    "AntigravityAdapter",
    "BaseAgentAdapter",
    "ClaudeAdapter",
    "is_pid_alive",
]
