"""100% synthetic, zero-leak demo environment isolating all 5 data sources."""

from __future__ import annotations

import atexit
import datetime
import json
import os
import pathlib
import tempfile
import time
from typing import Any


def _iso_ago(now_ts: float, sec_ago: float) -> str:
    dt = datetime.datetime.fromtimestamp(now_ts - sec_ago, tz=datetime.timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


class DemoEnvironment:
    """Creates an isolated temporary directory populated with realistic synthetic sessions.

    Isolates ALL 5 sources:
      1. ``claude_projects_dir``
      2. ``claude_agents_dir``
      3. ``claude_sessions_dir`` (with current process PID so `● Open` renders live)
      4. ``antigravity_brain_dir``
      5. ``worktrees`` (synthetic Git worktree radar records — never touches user repos)
    """

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cobalt_desk_demo_")
        self.root = pathlib.Path(self._tmp.name)
        self.claude_projects_dir = self.root / "claude_projects"
        self.claude_agents_dir = self.root / "claude_agents"
        self.claude_sessions_dir = self.root / "claude_sessions"
        self.antigravity_brain_dir = self.root / "antigravity_brain"
        self._hot_files: list[tuple[pathlib.Path, float]] = []
        self._last_keepwarm = 0.0
        self._populate()
        atexit.register(self.cleanup)

    def _write_jsonl(
        self, path: pathlib.Path, records: list[dict[str, Any]], mtime: float
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n"
        path.write_text(body, encoding="utf-8")
        os.utime(path, (mtime, mtime))

    def _populate(self) -> None:
        now = time.time()
        self.claude_projects_dir.mkdir(parents=True, exist_ok=True)
        self.claude_agents_dir.mkdir(parents=True, exist_ok=True)
        self.claude_sessions_dir.mkdir(parents=True, exist_ok=True)
        self.antigravity_brain_dir.mkdir(parents=True, exist_ok=True)

        # 1. Agent catalog definitions
        (self.claude_agents_dir / "security-auditor.md").write_text(
            "---\nname: security-auditor\nmodel: opus\neffort: high\ndescription: Security review gate\n---\n",
            encoding="utf-8",
        )
        (self.claude_agents_dir / "code-implementer.md").write_text(
            "---\nname: code-implementer\nmodel: sonnet\neffort: high\ndescription: Feature implementation worker\n---\n",
            encoding="utf-8",
        )

        # 2. Main Session 1: acme-api (WORKING, live open tab via current PID)
        sid_api = "11111111-aaaa-4444-bbbb-222222222222"
        (self.claude_sessions_dir / f"{os.getpid()}.json").write_text(
            json.dumps({"sessionId": sid_api, "startedAt": int(now * 1000)}),
            encoding="utf-8",
        )
        ppid = os.getppid()
        sid_web = "33333333-cccc-4444-dddd-444444444444"
        if ppid and ppid > 0 and ppid != os.getpid():
            (self.claude_sessions_dir / f"{ppid}.json").write_text(
                json.dumps({"sessionId": sid_web, "startedAt": int(now * 1000)}),
                encoding="utf-8",
            )

        proj_api = self.claude_projects_dir / "-workspace-acme-api"
        main_api = proj_api / f"{sid_api}.jsonl"
        self._write_jsonl(
            main_api,
            [
                {
                    "type": "user",
                    "sessionId": sid_api,
                    "cwd": "/workspace/acme-api",
                    "gitBranch": "feat/oauth-pkce",
                    "timestamp": _iso_ago(now, 300),
                    "message": {
                        "role": "user",
                        "content": "Implement OAuth 2.1 PKCE S256 verifier and dispatch security audit",
                    },
                },
                {
                    "type": "ai-title",
                    "aiTitle": "OAuth 2.1 PKCE S256 verifier & token rotation",
                    "timestamp": _iso_ago(now, 295),
                },
                {
                    "type": "api-request",
                    "timestamp": _iso_ago(now, 12),
                    "params": {
                        "model": "claude-opus-4-6",
                        "output_config": {"effort": "high"},
                    },
                },
                {
                    "type": "assistant",
                    "timestamp": _iso_ago(now, 8),
                    "message": {
                        "role": "assistant",
                        "model": "claude-opus-4-6",
                        "stop_reason": "tool_use",
                        "usage": {
                            "input_tokens": 1240,
                            "cache_creation_input_tokens": 8400,
                            "cache_read_input_tokens": 74500,
                        },
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tu_api_edit_1",
                                "name": "Edit",
                                "input": {"file_path": "/workspace/acme-api/src/auth/pkce.py"},
                            }
                        ],
                    },
                },
            ],
            mtime=now - 8,
        )
        self._hot_files.append((main_api, 8.0))

        # Subagents under acme-api
        sub_api = proj_api / sid_api / "subagents"
        sub_impl = sub_api / "agent-impl000001.jsonl"
        self._write_jsonl(
            sub_impl,
            [
                {
                    "type": "user",
                    "cwd": "/workspace/acme-api",
                    "gitBranch": "feat/oauth-pkce",
                    "timestamp": _iso_ago(now, 90),
                    "message": {
                        "role": "user",
                        "content": "Write unit & replay protection tests for src/auth/pkce.py",
                    },
                },
                {
                    "type": "api-request",
                    "timestamp": _iso_ago(now, 14),
                    "params": {
                        "model": "claude-sonnet-4-6",
                        "output_config": {"effort": "high"},
                    },
                },
                {
                    "type": "assistant",
                    "timestamp": _iso_ago(now, 11),
                    "message": {
                        "role": "assistant",
                        "model": "claude-sonnet-4-6",
                        "stop_reason": "tool_use",
                        "usage": {"input_tokens": 800, "cache_read_input_tokens": 31200},
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tu_impl_w1",
                                "name": "Write",
                                "input": {
                                    "file_path": "/workspace/acme-api/tests/test_pkce_flow.py"
                                },
                            }
                        ],
                    },
                },
            ],
            mtime=now - 11,
        )
        sub_impl.with_suffix(".meta.json").write_text(
            json.dumps(
                {
                    "agentType": "code-implementer",
                    "pickedEffortModel": "claude-opus-4-6",
                    "description": "Write PKCE S256 edge-case & replay unit tests",
                }
            ),
            encoding="utf-8",
        )
        self._hot_files.append((sub_impl, 11.0))

        sub_sec = sub_api / "agent-sec0000002.jsonl"
        self._write_jsonl(
            sub_sec,
            [
                {
                    "type": "user",
                    "cwd": "/workspace/acme-api",
                    "gitBranch": "feat/oauth-pkce",
                    "timestamp": _iso_ago(now, 70),
                    "message": {"role": "user", "content": "Audit JWT signature & state nonce"},
                },
                {
                    "type": "api-request",
                    "timestamp": _iso_ago(now, 16),
                    "params": {"model": "claude-opus-4-6", "output_config": {"effort": "high"}},
                },
                {
                    "type": "assistant",
                    "timestamp": _iso_ago(now, 13),
                    "message": {
                        "role": "assistant",
                        "model": "claude-opus-4-6",
                        "stop_reason": "tool_use",
                        "usage": {"input_tokens": 620, "cache_read_input_tokens": 45300},
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tu_sec_g1",
                                "name": "Grep",
                                "input": {"pattern": "verify_signature|state_nonce"},
                            }
                        ],
                    },
                },
            ],
            mtime=now - 13,
        )
        sub_sec.with_suffix(".meta.json").write_text(
            json.dumps(
                {
                    "agentType": "security-auditor",
                    "pickedEffortModel": "claude-opus-4-6",
                    "description": "Audit JWT signature & CORS headers",
                }
            ),
            encoding="utf-8",
        )
        self._hot_files.append((sub_sec, 13.0))

        # Skill fork /verify (DONE, showcases xhigh + secret redaction!)
        sub_vrf = sub_api / "agent-vrfy000003.jsonl"
        self._write_jsonl(
            sub_vrf,
            [
                {
                    "type": "user",
                    "cwd": "/workspace/acme-api",
                    "gitBranch": "feat/oauth-pkce",
                    "timestamp": _iso_ago(now, 320),
                    "message": {
                        "role": "user",
                        "content": (
                            "Base directory for this skill: /Users/demo/.claude/skills/verify\n"
                            "Arguments: auth DB=postgres://u:DemoSecretPass99@localhost/acme"
                        ),
                    },
                },
                {
                    "type": "api-request",
                    "timestamp": _iso_ago(now, 260),
                    "params": {"model": "claude-sonnet-4-6", "output_config": {"effort": "xhigh"}},
                },
                {
                    "type": "assistant",
                    "timestamp": _iso_ago(now, 240),
                    "message": {
                        "role": "assistant",
                        "model": "claude-sonnet-4-6",
                        "stop_reason": "end_turn",
                        "usage": {"input_tokens": 900, "cache_read_input_tokens": 58100},
                        "content": [
                            {
                                "type": "text",
                                "text": "All 42 unit & integration checks PASS. Zero high-severity issues.",
                            }
                        ],
                    },
                },
            ],
            mtime=now - 240,
        )
        sub_vrf.with_suffix(".meta.json").write_text(
            json.dumps(
                {
                    "agentType": "general-purpose",
                    "pickedEffortModel": "claude-opus-4-6",
                    "finished": True,
                }
            ),
            encoding="utf-8",
        )

        # Tier 4 survey subagents
        sub_exp = sub_api / "agent-expl000004.jsonl"
        self._write_jsonl(
            sub_exp,
            [
                {
                    "type": "user",
                    "cwd": "/workspace/acme-api",
                    "gitBranch": "main",
                    "timestamp": _iso_ago(now, 900),
                    "message": {"role": "user", "content": "Map OpenAPI route handlers"},
                },
                {
                    "type": "api-request",
                    "timestamp": _iso_ago(now, 880),
                    "params": {"model": "claude-haiku-4-5-20251001", "output_config": {"effort": "low"}},
                },
                {
                    "type": "assistant",
                    "timestamp": _iso_ago(now, 860),
                    "message": {
                        "role": "assistant",
                        "model": "claude-haiku-4-5-20251001",
                        "stop_reason": "end_turn",
                        "usage": {"input_tokens": 400, "cache_read_input_tokens": 13600},
                        "content": [{"type": "text", "text": "Indexed 14 OpenAPI route modules."}],
                    },
                },
            ],
            mtime=now - 860,
        )
        sub_exp.with_suffix(".meta.json").write_text(
            json.dumps(
                {
                    "agentType": "Explore",
                    "pickedEffortModel": "claude-opus-4-6",
                    "description": "Map OpenAPI 3.1 route handlers",
                    "finished": True,
                }
            ),
            encoding="utf-8",
        )

        # 3. Main Session 2: acme-web (WAITING on vitest + ERROR subagent e2e-runner)
        proj_web = self.claude_projects_dir / "-workspace-acme-web"
        main_web = proj_web / f"{sid_web}.jsonl"
        self._write_jsonl(
            main_web,
            [
                {
                    "type": "user",
                    "sessionId": sid_web,
                    "cwd": "/workspace/acme-web",
                    "gitBranch": "feat/checkout-v2",
                    "timestamp": _iso_ago(now, 420),
                    "message": {"role": "user", "content": "Run checkout v2 test suite"},
                },
                {
                    "type": "ai-title",
                    "aiTitle": "Checkout v2 idempotency & retry UI",
                    "timestamp": _iso_ago(now, 410),
                },
                {
                    "type": "api-request",
                    "timestamp": _iso_ago(now, 30),
                    "params": {"model": "claude-sonnet-4-6", "output_config": {"effort": "high"}},
                },
                {
                    "type": "assistant",
                    "timestamp": _iso_ago(now, 26),
                    "message": {
                        "role": "assistant",
                        "model": "claude-sonnet-4-6",
                        "stop_reason": "tool_use",
                        "usage": {"input_tokens": 720, "cache_read_input_tokens": 50400},
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tu_web_vitest",
                                "name": "Bash",
                                "input": {
                                    "command": "npx vitest run tests/checkout.spec.ts --reporter=verbose"
                                },
                            }
                        ],
                    },
                },
            ],
            mtime=now - 26,
        )
        self._hot_files.append((main_web, 26.0))

        sub_web = proj_web / sid_web / "subagents"
        sub_e2e = sub_web / "agent-e2er000005.jsonl"
        self._write_jsonl(
            sub_e2e,
            [
                {
                    "type": "user",
                    "cwd": "/workspace/acme-web",
                    "gitBranch": "feat/checkout-v2",
                    "timestamp": _iso_ago(now, 120),
                    "message": {"role": "user", "content": "Run Playwright payment retry flow"},
                },
                {
                    "type": "api-request",
                    "timestamp": _iso_ago(now, 55),
                    "params": {"model": "claude-sonnet-4-6", "output_config": {"effort": "high"}},
                },
                {
                    "type": "assistant",
                    "timestamp": _iso_ago(now, 48),
                    "message": {
                        "role": "assistant",
                        "model": "claude-sonnet-4-6",
                        "stop_reason": "tool_use",
                        "usage": {"input_tokens": 500, "cache_read_input_tokens": 27500},
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tu_e2e_1",
                                "name": "Bash",
                                "input": {"command": "npx playwright test e2e/checkout.spec.ts"},
                            }
                        ],
                    },
                },
                {
                    "type": "user",
                    "timestamp": _iso_ago(now, 40),
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "tu_e2e_1",
                                "is_error": True,
                                "content": "Timeout 15000ms waiting for #pay-btn (AUTH_TOKEN=sk_test_DemoKey9999999999)",
                            }
                        ],
                    },
                },
            ],
            mtime=now - 40,
        )
        sub_e2e.with_suffix(".meta.json").write_text(
            json.dumps(
                {
                    "agentType": "e2e-runner",
                    "pickedEffortModel": "claude-sonnet-4-6",
                    "description": "Playwright E2E payment retry verification",
                }
            ),
            encoding="utf-8",
        )
        self._hot_files.append((sub_e2e, 40.0))

        # 4. Antigravity Conversation on docs-site
        ag_tf = (
            self.antigravity_brain_dir
            / "a4f91c02-7777-4444-8888-999999999999"
            / ".system_generated"
            / "logs"
            / "transcript.jsonl"
        )
        self._write_jsonl(
            ag_tf,
            [
                {
                    "step_index": 0,
                    "type": "USER_INPUT",
                    "status": "DONE",
                    "created_at": _iso_ago(now, 240),
                    "content": "<USER_REQUEST>\nUpdate OpenAPI 3.1 architecture guide in docs-site\n</USER_REQUEST>",
                },
                {
                    "step_index": 1,
                    "type": "PLANNER_RESPONSE",
                    "status": "DONE",
                    "model": "gemini-2.5-pro-high",
                    "input_tokens": 3800,
                    "cache_read_tokens": 35200,
                    "created_at": _iso_ago(now, 195),
                    "tool_calls": [
                        {
                            "name": "edit_file",
                            "arguments": {"Path": "/workspace/docs-site/docs/architecture.md"},
                        }
                    ],
                },
                {
                    "step_index": 2,
                    "type": "PLANNER_RESPONSE",
                    "status": "DONE",
                    "model": "gemini-2.5-pro-high",
                    "input_tokens": 4100,
                    "cache_read_tokens": 35400,
                    "created_at": _iso_ago(now, 180),
                    "content": "Updated docs/architecture.md with PKCE S256 sequence diagrams.",
                },
            ],
            mtime=now - 180,
        )

        self._last_keepwarm = now

    @property
    def worktrees(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "acme-api",
                "branch": "main",
                "default_branch": "main",
                "sha": "9a4c12e",
                "commit_iso": "2026-11-24 12:10:00 +0000",
                "commit_rel": "2 hours ago",
                "subject": "chore: release v1.4.0",
                "dirty_count": 0,
                "ahead": 0,
                "behind": 0,
                "state": "MAIN",
            },
            {
                "name": "acme-api-oauth",
                "branch": "feat/oauth-pkce",
                "default_branch": "main",
                "sha": "3f8b210",
                "commit_iso": "2026-11-24 14:20:00 +0000",
                "commit_rel": "8 minutes ago",
                "subject": "feat(auth): add PKCE S256 challenge verifier",
                "dirty_count": 4,
                "ahead": 2,
                "behind": 0,
                "state": "CODING",
            },
            {
                "name": "acme-web-checkout",
                "branch": "feat/checkout-v2",
                "default_branch": "main",
                "sha": "c71e09d",
                "commit_iso": "2026-11-24 14:12:00 +0000",
                "commit_rel": "16 minutes ago",
                "subject": "test(e2e): add payment retry idempotency spec",
                "dirty_count": 0,
                "ahead": 3,
                "behind": 1,
                "state": "UNMERGED",
            },
        ]

    def keep_warm(self) -> None:
        """Refresh active demo fixture mtimes every ~45s so WORKING cards stay live during evaluation."""
        now = time.time()
        if (now - self._last_keepwarm) < 45.0:
            return
        self._last_keepwarm = now
        for fpath, offset_sec in self._hot_files:
            try:
                if fpath.is_file():
                    mt = now - offset_sec
                    os.utime(fpath, (mt, mt))
            except OSError:
                pass

    def cleanup(self) -> None:
        try:
            self._tmp.cleanup()
        except OSError:
            pass
