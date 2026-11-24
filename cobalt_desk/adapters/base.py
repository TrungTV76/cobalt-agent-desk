"""Base adapter contract for plugging new AI coding tools into Cobalt Agent Desk.

To contribute support for a new tool (e.g., Codex CLI, Cursor, Cline, OpenCode, Aider):
1. Subclass ``BaseAgentAdapter`` in ``cobalt_desk/adapters/<tool_name>.py``.
2. Implement ``scan(cutoff, now_ts)`` (100% read-only; never lock or mutate session files)
   and ``get_timeline(entry)`` for the slide-over detail drawer.
3. Register the adapter in ``AgentScanner`` (``cobalt_desk/scanner.py``).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AdapterScanResult:
    """Normalized read-only discovery batch returned by an adapter."""

    agents: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    file_index: dict[str, dict[str, Any]] = field(default_factory=dict)
    older_session_count: int = 0


class BaseAgentAdapter(abc.ABC):
    """Read-only adapter interface for local AI agent session logs."""

    source_group: str = "generic"

    @abc.abstractmethod
    def scan(self, cutoff: float, now_ts: float) -> AdapterScanResult:
        """Return agents active since ``cutoff`` without modifying any file on disk."""

    @abc.abstractmethod
    def get_timeline(self, index_entry: dict[str, Any]) -> list[dict[str, Any]]:
        """Return up to 30 newest redacted timeline events for a single agent."""
