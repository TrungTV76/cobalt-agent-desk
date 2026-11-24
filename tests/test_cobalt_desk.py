"""Isolated cross-platform unit, security, and contract test suite for Cobalt Agent Desk.

100% self-contained via `tempfile` — never touches real `~/.claude` or `~/.gemini` directories.
"""

from __future__ import annotations

import http.client
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cobalt_desk import APP_ID  # noqa: E402
from cobalt_desk.adapters.antigravity import (  # noqa: E402
    AntigravityAdapter,
    infer_project_from_paths,
)
from cobalt_desk.adapters.claude import (  # noqa: E402
    ClaudeAdapter,
    _parse_linux_proc_state,
    is_pid_alive,
)
from cobalt_desk.demo_fixtures import DemoEnvironment  # noqa: E402
from cobalt_desk.git_radar import GitWorktreeRadar, detect_default_branch  # noqa: E402
from cobalt_desk.models import (  # noqa: E402
    classify_tier,
    extract_clean_basename,
    normalize_model_and_effort,
    short_project_from_slug,
)
from cobalt_desk.redaction import (  # noqa: E402
    collapse_home_path,
    decode_utf8_tail,
    redact_preview,
    redact_sensitive_text,
)
from cobalt_desk.scanner import AgentScanner  # noqa: E402
from cobalt_desk.server import DeskHTTPServer, DeskState, safe_resolve_under  # noqa: E402


class RedactionAndPrivacyTests(unittest.TestCase):
    def test_01_redaction_covers_tokens_urls_pem_curl_queries_and_preserves_benign_keys(self) -> None:
        raw = (
            "PGPASSWORD=mySecret99 ANTHROPIC_API_KEY=sk-ant-api03-sec888888 "
            "OPENAI_API_KEY=sk-proj-OpenAiSecret999999 SVC=sk-svcacct-SvcSecret999999 "
            "OPENROUTER=sk-or-v1-RouterSecret123456789 GROQ=gsk_GroqSecretKey1234567890 "
            "GITHUB_TOKEN=ghp_tokSecret777777 GITLAB=glpat-GitLabSecret12345 "
            "AWS1=AKIAIOSFODNN7EXAMPLE AWS2=ASIAIOSFODNN7EXAMPLE "
            "SLACK=xoxb-1234567890-abcdef123456 STRIPE=sk_live_StripeSecret123456 "
            "NPM=npm_NpmSecretToken123456789 HF=hf_HuggingFaceToken1234567 "
            "git clone https://ghp_UrlPatWithoutColon99@github.com/acme/api.git "
            "psql postgresql://acme_user:DbPass!23@127.0.0.1:5432/acme "
            "curl -u admin:CurlBasicSecret99 https://api.example.com/v1?token=QueryTok888&X-Amz-Signature=Sig777 "
            "https://hooks.slack.com/services/T00000000/B00000000/SlackWebhookSecret99 "
            "-H 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c' "
            "bare_jwt=eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyIjoiYWxpY2UifQ.SignaturePart123456 "
            "-H 'Cookie: sid=topsecret123; csrf=xyz' "
            '{"client_secret": "jsonSec111", "sort_key": "mtime"} '
            "sort_key=mtime primary_key=1 foreign_key=2 role_key=security bypass=true"
        )
        redacted = redact_sensitive_text(raw)
        for leaked in (
            "mySecret99",
            "sk-ant-api03-sec888888",
            "sk-proj-OpenAiSecret999999",
            "sk-svcacct-SvcSecret999999",
            "sk-or-v1-RouterSecret123456789",
            "gsk_GroqSecretKey1234567890",
            "ghp_tokSecret777777",
            "glpat-GitLabSecret12345",
            "AKIAIOSFODNN7EXAMPLE",
            "ASIAIOSFODNN7EXAMPLE",
            "xoxb-1234567890-abcdef123456",
            "sk_live_StripeSecret123456",
            "npm_NpmSecretToken123456789",
            "hf_HuggingFaceToken1234567",
            "ghp_UrlPatWithoutColon99",
            "DbPass!23",
            "CurlBasicSecret99",
            "QueryTok888",
            "Sig777",
            "SlackWebhookSecret99",
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
            "SignaturePart123456",
            "topsecret123",
            "jsonSec111",
        ):
            self.assertNotIn(leaked, redacted, f"Leaked secret in redacted text: {leaked}")

        for benign in ("sort_key=mtime", "primary_key=1", "foreign_key=2", "role_key=security", "bypass=true"):
            self.assertIn(benign, redacted)

        # Regression guard against catastrophic backtracking (ReDoS) on unclosed JSON quotes + backslashes
        t0 = time.perf_counter()
        evil = '{"token": "' + ("\\" * 4000)
        _ = redact_sensitive_text(evil)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.assertLess(elapsed_ms, 80.0, f"JSON_KV_RE took {elapsed_ms:.1f}ms (ReDoS regression!)")

    def test_02_multiline_pem_truncated_preview_and_home_collapse(self) -> None:
        pem_text = (
            "Loaded key:\n"
            "-----BEGIN OPENSSH PRIVATE KEY-----\n"
            "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n"
            "QyNTUxOQAAACD1234567890SECRETBASE64BODY==\n"
        )
        prev = redact_preview(pem_text, max_len=140)
        self.assertNotIn("b3BlbnNzaC1rZXktdjE", prev)
        self.assertNotIn("SECRETBASE64BODY", prev)
        self.assertIn("REDACTED", prev)

        collapsed = collapse_home_path(
            r"python C:\Users\alice\work\acme-api\run.py && ls /Users/bob/code/app /home/charlie/dev"
        )
        self.assertNotIn("alice", collapsed)
        self.assertNotIn("bob", collapsed)
        self.assertNotIn("charlie", collapsed)
        self.assertIn("~", collapsed)

    def test_03_utf8_tail_decoder_drops_split_multibyte_head(self) -> None:
        sample = ("Hello · Tiếng Việt chuẩn UTF-8 🚀\n" * 8).encode("utf-8")
        # Slice right inside a multi-byte character
        cut = sample[7:]
        decoded = decode_utf8_tail(cut, truncated_head=True)
        self.assertNotIn("\ufffd", decoded)
        self.assertIn("Tiếng Việt", decoded)


class ModelAndPortabilityTests(unittest.TestCase):
    def test_04_model_normalization_handles_dates_bedrock_vertex_and_synthetic(self) -> None:
        self.assertEqual(
            normalize_model_and_effort("claude-sonnet-4-5-20250929", "high"),
            ("sonnet-4-5", "Sonnet 4.5", "high", "Sonnet 4.5 · high"),
        )
        self.assertEqual(
            normalize_model_and_effort("claude-3-7-sonnet-20250219", None),
            ("sonnet-3-7", "Sonnet 3.7", "default", "Sonnet 3.7 · default"),
        )
        self.assertEqual(
            normalize_model_and_effort("us.anthropic.claude-opus-4-1-20250805-v1:0", "xhigh"),
            ("opus-4-1", "Opus 4.1", "xhigh", "Opus 4.1 · xhigh"),
        )
        self.assertEqual(
            normalize_model_and_effort("claude-haiku-4-5@20251001", "low"),
            ("haiku-4-5", "Haiku 4.5", "low", "Haiku 4.5 · low"),
        )
        self.assertEqual(
            normalize_model_and_effort("<synthetic>", None, source="claude"),
            ("", "unknown", "default", "unknown · default"),
        )
        self.assertEqual(
            normalize_model_and_effort("gemini-2.5-pro-high", None, source="antigravity"),
            ("gemini-2.5-pro", "Gemini 2.5 Pro", "high", "Gemini 2.5 Pro · high"),
        )

    def test_05_cross_platform_basename_and_hyphenated_project_slugs(self) -> None:
        self.assertEqual(extract_clean_basename(r"C:\Users\alice\repos\acme-api"), "acme-api")
        self.assertEqual(extract_clean_basename("/Users/alice/work/acme-web/"), "acme-web")
        self.assertEqual(short_project_from_slug("c--Users-alice-projects-acme-api"), "acme-api")
        self.assertEqual(short_project_from_slug("-Users-alice-work-my-saas-web"), "my-saas-web")
        self.assertEqual(short_project_from_slug("-home-bob-dev-open-router-sdk"), "open-router-sdk")

    def test_06_pid_liveness_eperm_and_linux_proc_stat_with_parens(self) -> None:
        self.assertTrue(is_pid_alive(os.getpid()))
        self.assertFalse(is_pid_alive(0))
        self.assertFalse(is_pid_alive(-10))
        self.assertFalse(is_pid_alive(99999999))

        # Process name containing spaces and nested parentheses in /proc/<pid>/stat
        self.assertEqual(_parse_linux_proc_state("4321 (claude (worker)) Z 1 4321 4321"), "Z")
        self.assertEqual(_parse_linux_proc_state("4321 (node main) S 1 4321 4321"), "S")

        with tempfile.TemporaryDirectory() as td:
            proc_root = pathlib.Path(td)
            pid_dir = proc_root / str(os.getpid())
            pid_dir.mkdir(parents=True)
            (pid_dir / "stat").write_text(f"{os.getpid()} (claude (sub)) Z 1 1 1\n", encoding="utf-8")
            with mock.patch("cobalt_desk.adapters.claude.os.kill", return_value=None):
                self.assertFalse(is_pid_alive(os.getpid(), proc_root=proc_root))
                (pid_dir / "stat").write_text(f"{os.getpid()} (claude (sub)) S 1 1 1\n", encoding="utf-8")
                self.assertTrue(is_pid_alive(os.getpid(), proc_root=proc_root))

            # EPERM must return False (PID recycled to another user's process)
            with mock.patch("cobalt_desk.adapters.claude.os.kill", side_effect=PermissionError):
                self.assertFalse(is_pid_alive(12345, proc_root=proc_root))


class AdapterAndScannerTests(unittest.TestCase):
    def test_07_claude_256kb_seek_stophook_skill_memory_tier_and_2h_parent_window(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            proj_dir = root / "projects" / "-workspace-acme-api"
            agents_dir = root / "agents"
            sess_dir = root / "sessions"
            ag_dir = root / "brain"
            for d in (proj_dir, agents_dir, sess_dir, ag_dir):
                d.mkdir(parents=True)

            now_ts = 1_760_000_000.0
            sid = "aaaa1111-2222-3333-4444-555566667777"
            main_f = proj_dir / f"{sid}.jsonl"

            # Parent session is 5 hours old (> 2h window!), with >80KB padding after api-request
            huge_text = "x" * 90000
            main_f.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "user",
                                "sessionId": sid,
                                "cwd": "/workspace/acme-api",
                                "gitBranch": "feat/core",
                                "message": {"role": "user", "content": "Orchestrate build"},
                            }
                        ),
                        json.dumps(
                            {
                                "type": "api-request",
                                "params": {"model": "claude-opus-4-6", "output_config": {"effort": "high"}},
                            }
                        ),
                        json.dumps(
                            {
                                "type": "assistant",
                                "message": {
                                    "role": "assistant",
                                    "model": "<synthetic>",
                                    "stop_reason": "end_turn",
                                    "usage": {
                                        "input_tokens": 500,
                                        "cache_creation_input_tokens": 1500,
                                        "cache_read_input_tokens": 48000,
                                    },
                                    "content": [{"type": "text", "text": huge_text}],
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            os.utime(main_f, (now_ts - 18000, now_ts - 18000))  # 5 hours ago

            sub_dir = proj_dir / sid / "subagents"
            sub_dir.mkdir(parents=True)

            # 1. Stop-hook mid-session subagent (active 30s ago -> MUST appear in 2h window!)
            sh_f = sub_dir / "agent-stophook01.jsonl"
            sh_f.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "assistant",
                                "message": {
                                    "role": "assistant",
                                    "model": "claude-sonnet-4-6",
                                    "stop_reason": "end_turn",
                                    "content": [{"type": "text", "text": "Intermediate stop hook"}],
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "api-request",
                                "params": {"model": "claude-sonnet-4-6", "output_config": {"effort": "high"}},
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            sh_f.with_suffix(".meta.json").write_text(
                json.dumps({"agentType": "code-implementer", "pickedEffortModel": "claude-opus-4-6"}),
                encoding="utf-8",
            )
            os.utime(sh_f, (now_ts - 30, now_ts - 30))

            # 2. Skill fork /verify with >20KB SKILL.md header + secret in Arguments
            skill_f = sub_dir / "agent-verifyfk02.jsonl"
            skill_prompt = (
                "Base directory for this skill: /Users/alice/.claude/skills/verify\n"
                + ("# Skill body\n" * 1800)
                + "\nArguments: check auth API_KEY=SuperVerifySecret888"
            )
            skill_f.write_text(
                "\n".join(
                    [
                        json.dumps({"type": "user", "message": {"role": "user", "content": skill_prompt}}),
                        json.dumps(
                            {
                                "type": "api-request",
                                "params": {"model": "claude-sonnet-4-6", "output_config": {"effort": "xhigh"}},
                            }
                        ),
                        json.dumps(
                            {
                                "type": "assistant",
                                "message": {
                                    "role": "assistant",
                                    "model": "claude-sonnet-4-6",
                                    "stop_reason": "end_turn",
                                    "content": [{"type": "text", "text": "Verification passed"}],
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            skill_f.with_suffix(".meta.json").write_text(
                json.dumps({"agentType": "general-purpose", "pickedEffortModel": "claude-opus-4-6"}),
                encoding="utf-8",
            )
            os.utime(skill_f, (now_ts - 140, now_ts - 140))

            # 3. Auto-dream memory consolidation writing MEMORY.md stays in T4
            mem_tier = classify_tier(
                "claude_subagent",
                "general-purpose",
                description="Background memory consolidation",
                saw_write_tool=True,
            )
            self.assertEqual(mem_tier, "T4_SURVEY_RUNNER")

            scanner = AgentScanner(
                claude_projects_dir=root / "projects",
                antigravity_brain_dir=ag_dir,
                claude_agents_dir=agents_dir,
                claude_sessions_dir=sess_dir,
            )
            snap_2h = scanner.scan(scope="all", window_hours=2.0, now=now_ts)
            by_id = {a["id"]: a for a in snap_2h["agents"]}

            # Both active subagents AND their 5h-old parent session are preserved in 2h window!
            self.assertIn(f"cc:{sid[:12]}", by_id)
            parent_ag = by_id[f"cc:{sid[:12]}"]
            self.assertEqual(parent_ag["model_effort_key"], "Opus 4.6 · high")
            self.assertEqual(parent_ag["context_tokens"], 50000)

            sh_ag = by_id["sub:stophook01"]
            self.assertFalse(sh_ag["is_finished"])
            self.assertEqual(sh_ag["model_effort_key"], "Sonnet 4.6 · high")
            self.assertEqual(sh_ag["parent_effort_model"], "opus-4-6")

            vf_ag = by_id["sub:verifyfk02"]
            self.assertEqual(vf_ag["name"], "/verify")
            self.assertEqual(vf_ag["name_kind"], "skill")
            self.assertEqual(vf_ag["tier"], "T3_REVIEWER_GATE")
            self.assertEqual(vf_ag["model_effort_key"], "Sonnet 4.6 · xhigh")
            self.assertTrue(vf_ag["is_finished"])
            self.assertNotIn("SuperVerifySecret888", vf_ag["status_text"])

    def test_08_antigravity_project_inference_never_leaks_username(self) -> None:
        fake_home = pathlib.Path("/Users/secretuser")
        paths = [
            "/Users/secretuser/.gemini/antigravity/brain/1234/plan.md",
            "/Users/secretuser/projects/payment-gateway/src/charge.py",
            "/Users/secretuser/projects/payment-gateway/tests/test_charge.py",
        ]
        self.assertEqual(infer_project_from_paths(paths, home_dir=fake_home), "payment-gateway")
        self.assertEqual(
            infer_project_from_paths(["/Users/secretuser/.gemini/antigravity/brain/1/a.md"], home_dir=fake_home),
            "Antigravity",
        )

    @unittest.skipUnless(shutil.which("git"), "git CLI required")
    def test_09_git_worktree_radar_master_branch_no_locks_and_redacts_subject(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = pathlib.Path(td)
            repo = base / "sample-repo"
            repo.mkdir()
            subprocess.run(["git", "-C", str(repo), "init", "-b", "master"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-m", "init TOKEN=SuperGitCommitSecret123"],
                check=True,
                capture_output=True,
            )

            wt2 = base / "sample-repo-feat"
            subprocess.run(
                ["git", "-C", str(repo), "worktree", "add", "-b", "feat/ui", str(wt2)],
                check=True,
                capture_output=True,
            )
            (wt2 / "dirty.txt").write_text("wip\n", encoding="utf-8")

            self.assertEqual(detect_default_branch(repo), "master")
            radar = GitWorktreeRadar(repo_dir=repo)
            wts = radar.get_worktrees(force=True)
            self.assertEqual(len(wts), 2)
            by_name = {w["name"]: w for w in wts}
            self.assertEqual(by_name["sample-repo"]["state"], "MAIN")
            self.assertNotIn("SuperGitCommitSecret123", by_name["sample-repo"]["subject"])
            self.assertNotIn("path", by_name["sample-repo"])
            self.assertEqual(by_name["sample-repo-feat"]["state"], "CODING")
            self.assertEqual(by_name["sample-repo-feat"]["dirty_count"], 1)
            self.assertFalse((repo / ".git" / "index.lock").exists())


class ServerSecurityAndUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.demo_env = DemoEnvironment()
        cls.state = DeskState(demo_env=cls.demo_env)
        cls.httpd = DeskHTTPServer(("127.0.0.1", 0), cls.state)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown_event.set()
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2.0)
        cls.demo_env.cleanup()

    def _req(self, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", path, headers=headers or {})
            resp = conn.getresponse()
            hdrs = {k.lower(): v for k, v in resp.getheaders()}
            return resp.status, hdrs, resp.read()
        finally:
            conn.close()

    def test_10_security_headers_dns_rebinding_origin_csp_and_traversal(self) -> None:
        # Valid root HTML with strict script-src 'self' (no unsafe-inline)
        code, hdrs, body = self._req("/")
        self.assertEqual(code, 200)
        csp = hdrs.get("content-security-policy", "")
        self.assertIn("script-src 'self';", csp)
        self.assertNotIn("script-src 'self' 'unsafe-inline'", csp)
        html_txt = body.decode("utf-8")
        self.assertNotRegex(html_txt, r"(?i)\bonclick\s*=")

        # Host header check (DNS rebinding guard)
        c_host, _, _ = self._req("/api/health", headers={"Host": "attacker.invalid"})
        self.assertEqual(c_host, 403)

        # Origin header checks
        c_orig_bad, _, _ = self._req("/api/agents", headers={"Origin": "https://evil.example"})
        self.assertEqual(c_orig_bad, 403)
        c_orig_null, _, _ = self._req("/api/agents", headers={"Origin": "null"})
        self.assertEqual(c_orig_null, 403)
        c_orig_ok, _, _ = self._req("/api/agents", headers={"Origin": f"http://127.0.0.1:{self.port}"})
        self.assertEqual(c_orig_ok, 200)

        # Sec-Fetch-Site check
        c_sfs, _, _ = self._req("/api/agents", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(c_sfs, 403)

        # Path traversal guard
        c_trav, _, _ = self._req("/assets/../../pyproject.toml")
        self.assertEqual(c_trav, 403)
        self.assertIsNone(safe_resolve_under(REPO_ROOT / "cobalt_desk" / "ui", "../server.py"))

        # Favicon CSP
        f_code, f_hdrs, f_body = self._req("/favicon.ico")
        self.assertEqual(f_code, 200)
        self.assertIn("default-src 'none'", f_hdrs.get("content-security-policy", ""))
        self.assertIn(b"<svg", f_body)

    def test_11_demo_endpoints_project_scope_and_sse_stream(self) -> None:
        h_code, _, h_body = self._req("/api/health")
        self.assertEqual(h_code, 200)
        h_json = json.loads(h_body.decode("utf-8"))
        self.assertEqual(h_json["app"], APP_ID)
        self.assertTrue(h_json["demo"])
        self.assertNotIn("root", h_json)

        a_code, _, a_body = self._req("/api/agents?scope=project:acme-api")
        self.assertEqual(a_code, 200)
        a_json = json.loads(a_body.decode("utf-8"))
        self.assertGreaterEqual(a_json["summary"]["total"], 4)
        self.assertTrue(all(x["project"] == "acme-api" for x in a_json["agents"]))
        self.assertNotIn("DemoSecretPass99", a_body.decode("utf-8"))
        self.assertNotIn("DemoKey9999999999", a_body.decode("utf-8"))

        w_code, _, w_body = self._req("/api/worktrees")
        self.assertEqual(w_code, 200)
        w_json = json.loads(w_body.decode("utf-8"))
        self.assertTrue(w_json["enabled"])
        self.assertEqual(len(w_json["worktrees"]), 3)

        # SSE stream initial handshake
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", "/api/stream/agents?scope=all&window_hours=24")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            self.assertIn("text/event-stream", resp.getheader("Content-Type", ""))
            first_line = resp.fp.readline().decode("utf-8")
            self.assertEqual(first_line, ": connected\n")
        finally:
            conn.close()

    def test_12_dom_ids_and_bilingual_i18n_key_parity(self) -> None:
        ui_dir = REPO_ROOT / "cobalt_desk" / "ui"
        html = (ui_dir / "index.html").read_text(encoding="utf-8")
        html_ids = set(re.findall(r'\bid="([^"]+)"', html))

        for js_name in ("app.js", "office.js"):
            js_txt = (ui_dir / js_name).read_text(encoding="utf-8")
            referenced_ids = set(re.findall(r'getElementById\("([^"]+)"\)', js_txt))
            missing = referenced_ids - html_ids
            self.assertFalse(missing, f"{js_name} references missing DOM IDs: {missing}")

        i18n_txt = (ui_dir / "i18n.js").read_text(encoding="utf-8")
        en_block = i18n_txt.split("en: {", 1)[1].split("\n    vi: {", 1)[0]
        vi_block = i18n_txt.split("vi: {", 1)[1].split("\n  };\n", 1)[0]
        en_keys = set(re.findall(r"^\s{6}([A-Za-z0-9_]+)\s*:", en_block, flags=re.MULTILINE))
        vi_keys = set(re.findall(r"^\s{6}([A-Za-z0-9_]+)\s*:", vi_block, flags=re.MULTILINE))
        self.assertEqual(en_keys, vi_keys, f"EN/VI key mismatch: {en_keys ^ vi_keys}")

        html_i18n_keys = set(re.findall(r'data-i18n(?:-placeholder)?="([^"]+)"', html))
        missing_i18n = html_i18n_keys - en_keys
        self.assertFalse(missing_i18n, f"index.html references missing i18n keys: {missing_i18n}")


if __name__ == "__main__":
    unittest.main()
