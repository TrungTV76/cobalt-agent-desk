"""Multi-adapter AgentScanner orchestrator with scope/project filtering and SSE fingerprinting."""

from __future__ import annotations

import pathlib
import threading
import time
from typing import Any, Callable

from cobalt_desk.adapters.antigravity import AntigravityAdapter
from cobalt_desk.adapters.base import BaseAgentAdapter
from cobalt_desk.adapters.claude import ClaudeAdapter
from cobalt_desk.models import TIER_ORDER


class AgentScanner:
    """Fast, read-only orchestrator across registered local agent adapters."""

    def __init__(
        self,
        claude_projects_dir: pathlib.Path | None = None,
        antigravity_brain_dir: pathlib.Path | None = None,
        claude_agents_dir: pathlib.Path | None = None,
        claude_sessions_dir: pathlib.Path | None = None,
        active_threshold_sec: float = 120.0,
        demo_mode: bool = False,
        pre_scan_hook: Callable[[], None] | None = None,
    ) -> None:
        home = pathlib.Path.home()
        self.claude_projects_dir = (
            claude_projects_dir.resolve()
            if claude_projects_dir is not None
            else (home / ".claude" / "projects")
        )
        self.antigravity_brain_dir = (
            antigravity_brain_dir.resolve()
            if antigravity_brain_dir is not None
            else (home / ".gemini" / "antigravity" / "brain")
        )
        self.claude_agents_dir = (
            claude_agents_dir.resolve()
            if claude_agents_dir is not None
            else (home / ".claude" / "agents")
        )
        self.claude_sessions_dir = (
            claude_sessions_dir.resolve()
            if claude_sessions_dir is not None
            else (home / ".claude" / "sessions")
        )
        self.demo_mode = demo_mode
        self._pre_scan_hook = pre_scan_hook
        self._lock = threading.Lock()
        self._agent_file_index: dict[str, dict[str, Any]] = {}

        self.claude_adapter = ClaudeAdapter(
            projects_dir=self.claude_projects_dir,
            agents_dir=self.claude_agents_dir,
            sessions_dir=self.claude_sessions_dir,
            active_threshold_sec=active_threshold_sec,
        )
        self.antigravity_adapter = AntigravityAdapter(
            brain_dir=self.antigravity_brain_dir,
            active_threshold_sec=active_threshold_sec,
        )
        self.adapters: dict[str, BaseAgentAdapter] = {
            "claude": self.claude_adapter,
            "antigravity": self.antigravity_adapter,
        }

    @staticmethod
    def _matches_scope(agent: dict[str, Any], scope: str) -> bool:
        if scope in ("", "all"):
            return True
        if scope == "claude":
            return agent["source"] in ("claude_main", "claude_subagent")
        if scope == "antigravity":
            return agent["source"] == "antigravity"
        if scope.startswith("project:"):
            target_proj = scope[len("project:") :].strip().lower()
            return str(agent.get("project") or "").lower() == target_proj
        return True

    def scan(
        self,
        scope: str = "all",
        window_hours: float = 24.0,
        now: float | None = None,
    ) -> dict[str, Any]:
        _fp, snapshot = self.scan_with_fingerprint(scope=scope, window_hours=window_hours, now=now)
        return snapshot

    def scan_with_fingerprint(
        self,
        scope: str = "all",
        window_hours: float = 24.0,
        now: float | None = None,
    ) -> tuple[str, dict[str, Any]]:
        if self._pre_scan_hook is not None and now is None:
            self._pre_scan_hook()

        now_ts = time.time() if now is None else now
        cutoff = now_ts - max(0.5, window_hours) * 3600.0

        all_agents: list[dict[str, Any]] = []
        all_events: list[dict[str, Any]] = []
        merged_index: dict[str, dict[str, Any]] = {}
        older_count = 0

        for adapter in self.adapters.values():
            batch = adapter.scan(cutoff=cutoff, now_ts=now_ts)
            all_agents.extend(batch.agents)
            all_events.extend(batch.events)
            merged_index.update(batch.file_index)
            older_count += batch.older_session_count

        with self._lock:
            self._agent_file_index = merged_index

        projects = sorted({str(a["project"]) for a in all_agents if a.get("project")})
        filtered_agents = [a for a in all_agents if self._matches_scope(a, scope)]
        state_rank = {"ERROR": 0, "WORKING": 1, "WAITING": 2, "IDLE": 3}
        filtered_agents.sort(key=lambda a: (state_rank.get(a["room_state"], 9), -a["last_ts"]))

        returned_agents = filtered_agents[:160]
        allowed_ids = {a["id"] for a in returned_agents}
        filtered_events = [e for e in all_events if e["agent_id"] in allowed_ids]
        filtered_events.sort(key=lambda e: -e["ts"])

        summary = {
            "total": len(returned_agents),
            "total_discovered": len(filtered_agents),
            "older_session_count": older_count,
            "working": sum(1 for a in returned_agents if a["room_state"] == "WORKING"),
            "waiting": sum(1 for a in returned_agents if a["room_state"] == "WAITING"),
            "error": sum(1 for a in returned_agents if a["room_state"] == "ERROR"),
            "idle": sum(1 for a in returned_agents if a["room_state"] == "IDLE"),
            "projects": projects,
        }

        tier_buckets: dict[str, dict[str, Any]] = {}
        me_buckets: dict[str, dict[str, Any]] = {}
        fn_buckets: dict[str, dict[str, Any]] = {}
        for a in returned_agents:
            st_key = a["room_state"].lower()
            t_id = a["tier"]
            tb = tier_buckets.setdefault(
                t_id,
                {
                    "key": t_id,
                    "order": TIER_ORDER.get(t_id, 9),
                    "total": 0,
                    "working": 0,
                    "waiting": 0,
                    "error": 0,
                    "idle": 0,
                },
            )
            tb["total"] += 1
            if st_key in tb:
                tb[st_key] += 1

            mek = a["model_effort_key"]
            mb = me_buckets.setdefault(
                mek,
                {
                    "key": mek,
                    "model_family": a["model_family"],
                    "effort": a["effort"],
                    "total": 0,
                    "working": 0,
                    "waiting": 0,
                    "error": 0,
                    "idle": 0,
                },
            )
            mb["total"] += 1
            if st_key in mb:
                mb[st_key] += 1

            fk = a["function_key"]
            fb = fn_buckets.setdefault(
                fk,
                {
                    "key": fk,
                    "tier": t_id,
                    "total": 0,
                    "working": 0,
                    "waiting": 0,
                    "error": 0,
                    "idle": 0,
                },
            )
            fb["total"] += 1
            if st_key in fb:
                fb[st_key] += 1

        group_summaries = {
            "by_tier": sorted(tier_buckets.values(), key=lambda x: x["order"]),
            "by_model_effort": sorted(
                me_buckets.values(),
                key=lambda x: (-(x["error"] + x["working"] + x["waiting"]), -x["total"], x["key"]),
            ),
            "by_function": sorted(
                fn_buckets.values(),
                key=lambda x: (-(x["error"] + x["working"] + x["waiting"]), -x["total"], x["key"]),
            ),
        }

        fp_parts = [
            f"{a['id']}:{a['room_state']}:{a['state_code']}:{int(a['last_ts'] * 1000)}:"
            f"{a.get('file_size', 0)}:{a['current_tool']}:{a['model_effort_key']}:"
            f"{int(bool(a.get('tab_open')))}:{int(bool(a.get('is_finished')))}:{a['status_text'][:36]}"
            for a in returned_agents
        ]
        fp = "|".join(fp_parts)

        return fp, {
            "demo": self.demo_mode,
            "scope": scope,
            "window_hours": window_hours,
            "server_time": now_ts,
            "summary": summary,
            "group_summaries": group_summaries,
            "agents": returned_agents,
            "events": filtered_events[:60],
        }

    def get_agent_detail(self, agent_id: str) -> tuple[int, dict[str, Any]]:
        with self._lock:
            entry = self._agent_file_index.get(agent_id)
        if not entry:
            self.scan(scope="all", window_hours=168.0)
            with self._lock:
                entry = self._agent_file_index.get(agent_id)
        if not entry:
            return 404, {"error_code": "agent_not_found", "error": f"Agent not found: {agent_id}"}

        adapter_key = str(entry.get("adapter") or "")
        adapter = self.adapters.get(adapter_key)
        timeline = adapter.get_timeline(entry) if adapter else []
        return 200, {"agent": dict(entry["meta"]), "timeline": timeline[:30]}
