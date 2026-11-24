"""Read-only adapter for Claude Code main sessions, subagents, and skill forks."""

from __future__ import annotations

import ctypes
import json
import os
import pathlib
import re
import threading
import time
from typing import Any

from cobalt_desk.adapters.base import AdapterScanResult, BaseAgentAdapter
from cobalt_desk.models import (
    LONG_RUNNING_CMD_RE,
    ROLE_GLYPHS,
    TIER_ORDER,
    WRITE_TOOLS,
    classify_tier,
    extract_clean_basename,
    map_agent_role,
    normalize_model_and_effort,
    parse_iso_ts,
    short_project_from_slug,
    short_tool_badge,
    shorten_model_name,
    summarize_tool_call,
)
from cobalt_desk.redaction import decode_utf8_tail, redact_preview, redact_sensitive_text

MAX_CACHE_ENTRIES = 1024
CATALOG_TTL_SEC = 60.0
LIVE_SESSIONS_TTL_SEC = 3.0

SKILL_DIR_RE = re.compile(
    r"Base directory for this skill:\s*[^\r\n]*?[\\/]skills[\\/]([A-Za-z0-9._-]+)",
    re.IGNORECASE,
)
SKILL_ARGS_RE = re.compile(r"\bArguments\s*:\s*(.+)", re.IGNORECASE | re.DOTALL)
PROMPT_REPO_RE = re.compile(
    r"\b(?:Repo|Worktree|Workspace)\s*:\s*[`'\"]?([A-Za-z]:[\\/][^\s`'\";,)]+|/[^\s`'\";,)]+)",
    re.IGNORECASE,
)
PROMPT_BRANCH_RE = re.compile(
    r"\bbranch\s+[`'\"]?([A-Za-z0-9._-]+/[A-Za-z0-9._/-]+|main|master|develop)[`'\"]?",
    re.IGNORECASE,
)
ROOT_FM_KV_RE = re.compile(r"^([a-zA-Z_]+):\s*(.+?)\s*$")


def _put_bounded(cache: dict[str, Any], key: str, value: Any) -> None:
    if key in cache:
        cache.pop(key, None)
    elif len(cache) >= MAX_CACHE_ENTRIES:
        oldest_key = next(iter(cache))
        cache.pop(oldest_key, None)
    cache[key] = value


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_ulong), ("dwHighDateTime", ctypes.c_ulong)]


def _check_windows_pid(pid: int, expected_started_ms: int | None = None) -> bool:
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong(0)
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            if not (ok and exit_code.value == STILL_ACTIVE):
                return False
            if expected_started_ms and expected_started_ms > 0:
                creation = _FILETIME()
                exit_t = _FILETIME()
                kern_t = _FILETIME()
                user_t = _FILETIME()
                if kernel32.GetProcessTimes(
                    handle,
                    ctypes.byref(creation),
                    ctypes.byref(exit_t),
                    ctypes.byref(kern_t),
                    ctypes.byref(user_t),
                ):
                    raw_100ns = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
                    # Windows FILETIME epoch (1601-01-01) -> Unix epoch (1970-01-01) in ms
                    proc_start_ms = (raw_100ns // 10000) - 11644473600000
                    # Reject if the OS process started >60s AFTER the session file's recorded start (PID reuse)
                    if proc_start_ms > (expected_started_ms + 60000):
                        return False
            return True
        finally:
            kernel32.CloseHandle(handle)
    except (OSError, AttributeError, ValueError):
        return False


def _parse_linux_proc_state(stat_content: str) -> str:
    """Safely extract single-char process state after `(comm)` even if comm has spaces/parens."""
    rparen = stat_content.rfind(")")
    if rparen == -1:
        return ""
    after = stat_content[rparen + 1 :].lstrip()
    return after[0] if after else ""


def is_pid_alive(
    pid: int,
    expected_started_ms: int | None = None,
    proc_root: pathlib.Path | None = None,
) -> bool:
    """Cross-platform read-only check whether a local agent PID is still alive.

    - Windows: Win32 ``OpenProcess(0x1000)`` + ``GetExitCodeProcess == STILL_ACTIVE`` + start-time guard.
    - POSIX (macOS / Linux): ``os.kill(pid, 0)`` where ``PermissionError`` returns ``False``
      (owned by another user due to PID reuse), plus ``/proc/<pid>/stat`` zombie/dead check on Linux.
    """
    if pid <= 0:
        return False
    if os.name == "nt" and proc_root is None:
        return _check_windows_pid(pid, expected_started_ms=expected_started_ms)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Session belongs to current user; EPERM means PID was recycled to another user's process
        return False
    except OSError:
        return False

    p_root = proc_root if proc_root is not None else pathlib.Path("/proc")
    stat_file = p_root / str(pid) / "stat"
    if stat_file.is_file():
        try:
            stat_txt = stat_file.read_text(encoding="utf-8", errors="replace")
            st_char = _parse_linux_proc_state(stat_txt)
            if st_char in ("Z", "X", "x"):
                return False
        except OSError:
            pass

    return True


def infer_effective_worktree(
    prompt_project: str,
    prompt_branch: str,
    touched_paths: list[str],
    fallback_project: str,
    fallback_branch: str,
) -> tuple[str, str]:
    """Infer subagent's real target worktree & branch when explicitly overridden in prompt."""
    eff_proj = prompt_project or fallback_project
    eff_branch = prompt_branch or fallback_branch
    if not prompt_project and touched_paths:
        counts: dict[str, int] = {}
        for raw_p in touched_paths:
            norm = raw_p.strip().replace("\\", "/")
            # Match absolute paths with at least 2 segments before filename
            parts = [seg for seg in norm.split("/") if seg and ":" not in seg]
            if len(parts) >= 3 and parts[0].lower() not in ("users", "home", "tmp", "var", "etc"):
                cand = parts[-2]
                if cand not in ("src", "tests", "lib", "app", "docs", "scripts", "ui"):
                    counts[cand] = counts.get(cand, 0) + 1
        if counts:
            best_proj, hits = max(counts.items(), key=lambda kv: kv[1])
            if hits >= 2:
                eff_proj = best_proj
    return eff_proj, eff_branch


class ClaudeAdapter(BaseAgentAdapter):
    """Discovers Claude Code main sessions, subagents, and skill forks."""

    source_group = "claude"

    def __init__(
        self,
        projects_dir: pathlib.Path,
        agents_dir: pathlib.Path,
        sessions_dir: pathlib.Path,
        active_threshold_sec: float = 120.0,
    ) -> None:
        self.projects_dir = projects_dir
        self.agents_dir = agents_dir
        self.sessions_dir = sessions_dir
        self.active_threshold_sec = active_threshold_sec
        self._lock = threading.Lock()
        self._head_cache: dict[str, dict[str, Any]] = {}
        self._tail_cache: dict[str, tuple[int, int, dict[str, Any]]] = {}
        self._meta_cache: dict[str, tuple[int, dict[str, Any]]] = {}
        self._catalog_ts = 0.0
        self._catalog_cache: dict[str, dict[str, str]] = {}
        self._live_sess_ts = 0.0
        self._live_sess_cache: set[str] = set()

    def load_agent_catalog(self) -> dict[str, dict[str, str]]:
        """Parse root-level YAML frontmatter from ~/.claude/agents/*.md (ignoring nested keys)."""
        mono_now = time.monotonic()
        with self._lock:
            if (mono_now - self._catalog_ts) < CATALOG_TTL_SEC and self._catalog_cache:
                return self._catalog_cache

        catalog: dict[str, dict[str, str]] = {}
        if self.agents_dir.is_dir():
            try:
                for entry in os.scandir(self.agents_dir):
                    if not entry.is_file() or not entry.name.endswith(".md"):
                        continue
                    try:
                        text = pathlib.Path(entry.path).read_text(encoding="utf-8", errors="replace")[:4096]
                    except OSError:
                        continue
                    lines = text.splitlines()
                    if not lines or lines[0].strip() != "---":
                        continue
                    info: dict[str, str] = {}
                    for ln in lines[1:40]:
                        if ln.strip() == "---":
                            break
                        if ln.startswith((" ", "\t")):
                            continue
                        m = ROOT_FM_KV_RE.match(ln)
                        if m:
                            k = m.group(1).lower()
                            v = m.group(2).strip().strip("\"'")
                            if k in ("name", "model", "effort", "description"):
                                info[k] = v
                    key_name = info.get("name") or pathlib.Path(entry.name).stem
                    if key_name:
                        catalog[key_name.lower()] = info
            except OSError:
                pass

        with self._lock:
            self._catalog_cache = catalog
            self._catalog_ts = time.monotonic()
        return catalog

    def load_live_sessions(self) -> set[str]:
        """Read ~/.claude/sessions/[0-9]*.json + cross-platform PID liveness check."""
        mono_now = time.monotonic()
        with self._lock:
            if (mono_now - self._live_sess_ts) < LIVE_SESSIONS_TTL_SEC:
                return set(self._live_sess_cache)

        live_ids: set[str] = set()
        if self.sessions_dir.is_dir():
            try:
                for entry in os.scandir(self.sessions_dir):
                    if not entry.is_file() or not entry.name.endswith(".json"):
                        continue
                    stem = entry.name[:-5]
                    if not stem.isdigit():
                        continue
                    pid = int(stem)
                    try:
                        data = json.loads(
                            pathlib.Path(entry.path).read_text(encoding="utf-8", errors="replace")
                        )
                    except (OSError, ValueError):
                        continue
                    sid = str(data.get("sessionId") or data.get("session_id") or "").strip()
                    raw_started = data.get("startedAt")
                    started_ms = int(raw_started) if isinstance(raw_started, (int, float)) else None
                    if sid and is_pid_alive(pid, expected_started_ms=started_ms):
                        live_ids.add(sid)
            except OSError:
                pass

        with self._lock:
            self._live_sess_cache = live_ids
            self._live_sess_ts = time.monotonic()
        return set(live_ids)

    def _read_head(self, fpath: pathlib.Path) -> dict[str, Any]:
        key = str(fpath)
        with self._lock:
            if key in self._head_cache:
                return self._head_cache[key]

        meta: dict[str, Any] = {
            "cwd": "",
            "gitBranch": "",
            "sessionId": "",
            "slug": "",
            "skill_name": "",
            "skill_args": "",
            "first_prompt": "",
            "prompt_project": "",
            "prompt_branch": "",
        }
        try:
            with fpath.open("rb") as fh:
                line0_raw = fh.readline(131072)
                lines_head = [line0_raw.decode("utf-8", errors="replace")]
                rest_loaded = False
                idx = 0
                while idx < len(lines_head):
                    ln = lines_head[idx].strip()
                    idx += 1
                    if ln.startswith("{"):
                        try:
                            obj = json.loads(ln)
                        except ValueError:
                            obj = None
                        if isinstance(obj, dict):
                            if obj.get("cwd") and not meta["cwd"]:
                                meta["cwd"] = str(obj["cwd"])
                            if obj.get("gitBranch") and not meta["gitBranch"]:
                                meta["gitBranch"] = str(obj["gitBranch"])
                            if obj.get("sessionId") and not meta["sessionId"]:
                                meta["sessionId"] = str(obj["sessionId"])
                            if obj.get("slug") and not meta["slug"]:
                                meta["slug"] = str(obj["slug"])

                            if obj.get("type") == "user" and not meta["first_prompt"]:
                                msg = obj.get("message")
                                raw_c = msg.get("content") if isinstance(msg, dict) else None
                                prompt_txt = ""
                                if isinstance(raw_c, str):
                                    prompt_txt = raw_c
                                elif isinstance(raw_c, list):
                                    parts = [
                                        str(b.get("text", ""))
                                        for b in raw_c
                                        if isinstance(b, dict) and b.get("text")
                                    ]
                                    prompt_txt = "\n".join(parts)

                                if prompt_txt:
                                    sm = SKILL_DIR_RE.search(prompt_txt[:4000])
                                    if sm:
                                        meta["skill_name"] = sm.group(1).strip()
                                        am = SKILL_ARGS_RE.search(prompt_txt)
                                        if am:
                                            meta["skill_args"] = redact_preview(am.group(1), 130)
                                    meta["first_prompt"] = redact_preview(prompt_txt[:1200], 140)
                                    rm = PROMPT_REPO_RE.search(prompt_txt[:4000])
                                    if rm:
                                        meta["prompt_project"] = extract_clean_basename(rm.group(1))
                                    bm = PROMPT_BRANCH_RE.search(prompt_txt[:4000])
                                    if bm:
                                        meta["prompt_branch"] = bm.group(1)

                    if meta["cwd"] and meta["gitBranch"] and meta["first_prompt"]:
                        break
                    if not rest_loaded and idx >= len(lines_head):
                        rest_loaded = True
                        rest_raw = fh.read(16384)
                        if rest_raw:
                            lines_head.extend(
                                rest_raw.decode("utf-8", errors="replace").splitlines()[:15]
                            )
        except OSError:
            pass

        with self._lock:
            _put_bounded(self._head_cache, key, meta)
        return meta

    def _parse_tail_window(
        self, fpath: pathlib.Path, size: int, mtime: float, tail_bytes: int
    ) -> tuple[dict[str, Any], int]:
        parsed: dict[str, Any] = {
            "model": "",
            "api_model": "",
            "api_effort": "",
            "query_source": "",
            "context_tokens": 0,
            "saw_write_tool": False,
            "ai_title": "",
            "branch": "",
            "cwd": "",
            "last_tool": "",
            "last_action_code": "ready",
            "last_action_detail": "",
            "last_event_ts": mtime,
            "last_was_error": False,
            "last_tool_is_long_cmd": False,
            "pending_tool_ids": [],
            "last_conv_stop_reason": "",
            "touched_paths": [],
            "events": [],
        }
        conv_msg_count = 0
        pending_ids: set[str] = set()
        touched_paths: list[str] = []

        with fpath.open("rb") as fh:
            truncated = size > tail_bytes
            if truncated:
                fh.seek(size - tail_bytes)
                raw = fh.read(tail_bytes)
                text = decode_utf8_tail(raw, truncated_head=True)
            else:
                raw = fh.read()
                text = raw.decode("utf-8", errors="replace")

        lines = text.splitlines()
        if truncated and lines:
            lines = lines[1:]

        events: list[dict[str, Any]] = []
        for ln in lines:
            ln = ln.strip()
            if not ln.startswith("{"):
                continue
            if (
                '"assistant"' not in ln
                and '"user"' not in ln
                and '"api-request"' not in ln
                and '"ai-title"' not in ln
            ):
                continue
            try:
                obj = json.loads(ln)
            except ValueError:
                continue

            if obj.get("gitBranch"):
                parsed["branch"] = str(obj["gitBranch"])
            if obj.get("cwd"):
                parsed["cwd"] = str(obj["cwd"])

            rec_type = obj.get("type")
            rec_ts = parse_iso_ts(obj.get("timestamp"), mtime)

            if rec_type == "ai-title" and obj.get("aiTitle"):
                parsed["ai_title"] = redact_sensitive_text(str(obj["aiTitle"]))[:100]
                continue

            if rec_type == "api-request":
                params = obj.get("params")
                if isinstance(params, dict):
                    pm = str(params.get("model") or "").strip()
                    if pm and pm.lower() != "<synthetic>":
                        parsed["api_model"] = pm
                    out_cfg = params.get("output_config")
                    if isinstance(out_cfg, dict) and out_cfg.get("effort"):
                        parsed["api_effort"] = str(out_cfg["effort"]).strip().lower()
                if obj.get("querySource"):
                    parsed["query_source"] = str(obj["querySource"]).strip()
                parsed["last_conv_stop_reason"] = "api_in_flight"
                parsed["last_event_ts"] = rec_ts
                continue

            msg = obj.get("message")
            if not isinstance(msg, dict):
                continue
            raw_msg_model = str(msg.get("model") or "").strip()
            if raw_msg_model and raw_msg_model.lower() != "<synthetic>":
                parsed["model"] = raw_msg_model

            usage = msg.get("usage")
            if isinstance(usage, dict):
                ctx_tot = (
                    int(usage.get("input_tokens") or 0)
                    + int(usage.get("cache_creation_input_tokens") or 0)
                    + int(usage.get("cache_read_input_tokens") or 0)
                )
                if ctx_tot > 0:
                    parsed["context_tokens"] = ctx_tot

            content = msg.get("content")
            if rec_type == "assistant":
                conv_msg_count += 1
                stop_reason = str(msg.get("stop_reason") or "")
                if isinstance(content, list):
                    saw_tool = False
                    text_preview = ""
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type")
                        if btype == "tool_use":
                            saw_tool = True
                            tname = str(block.get("name") or "Tool")
                            if tname.lower() in WRITE_TOOLS:
                                parsed["saw_write_tool"] = True
                            t_inp = block.get("input")
                            tid = str(block.get("id") or f"anon_{len(events)}")
                            pending_ids.add(tid)
                            if isinstance(t_inp, dict):
                                for pk in ("file_path", "path"):
                                    if t_inp.get(pk):
                                        touched_paths.append(str(t_inp[pk])[:200])
                            act_code, safe_tool, detail = summarize_tool_call(tname, t_inp)
                            parsed["last_tool"] = safe_tool
                            parsed["last_action_code"] = act_code
                            parsed["last_action_detail"] = detail
                            parsed["last_event_ts"] = rec_ts
                            parsed["last_was_error"] = False
                            parsed["last_tool_is_long_cmd"] = (
                                safe_tool.lower() == "bash" and bool(LONG_RUNNING_CMD_RE.search(detail))
                            )
                            events.append(
                                {
                                    "ts": rec_ts,
                                    "kind": "tool",
                                    "action_code": act_code,
                                    "tool": safe_tool,
                                    "detail": detail,
                                    "is_error": False,
                                }
                            )
                        elif btype == "text" and isinstance(block.get("text"), str) and not text_preview:
                            text_preview = redact_preview(block["text"], 130)

                    if saw_tool:
                        parsed["last_conv_stop_reason"] = "tool_use"
                    else:
                        if stop_reason in ("end_turn", "stop_sequence", "max_tokens"):
                            pending_ids.clear()
                            parsed["last_conv_stop_reason"] = stop_reason
                        if text_preview:
                            parsed["last_action_code"] = "reply"
                            parsed["last_action_detail"] = text_preview
                            parsed["last_event_ts"] = rec_ts
                            parsed["last_was_error"] = False
                            parsed["last_tool_is_long_cmd"] = False
                            events.append(
                                {
                                    "ts": rec_ts,
                                    "kind": "reply",
                                    "action_code": "reply",
                                    "tool": "",
                                    "detail": text_preview,
                                    "is_error": False,
                                }
                            )

            elif rec_type == "user":
                conv_msg_count += 1
                if isinstance(content, str):
                    pending_ids.clear()
                    is_intr = "request interrupted" in content.lower()
                    parsed["last_conv_stop_reason"] = "interrupted" if is_intr else "user_prompt"
                    parsed["last_was_error"] = False
                    if not is_intr and content.strip():
                        parsed["last_action_code"] = "user_prompt"
                        parsed["last_action_detail"] = redact_preview(content, 130)
                        parsed["last_event_ts"] = rec_ts
                elif isinstance(content, list):
                    saw_tool_result = False
                    saw_interrupt = False
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type")
                        if btype == "tool_result":
                            saw_tool_result = True
                            tid = str(block.get("tool_use_id") or "")
                            if tid:
                                pending_ids.discard(tid)
                            else:
                                pending_ids.clear()

                            raw_res = block.get("content")
                            res_full = ""
                            if isinstance(raw_res, str):
                                res_full = raw_res
                            elif isinstance(raw_res, list):
                                res_full = " ".join(
                                    str(x.get("text", ""))
                                    for x in raw_res
                                    if isinstance(x, dict) and x.get("text")
                                )

                            if "request interrupted" in res_full.lower():
                                saw_interrupt = True
                                parsed["last_was_error"] = False
                            elif bool(block.get("is_error")):
                                clean_err = redact_preview(res_full, 130)
                                parsed["last_was_error"] = True
                                parsed["last_action_code"] = "tool_error"
                                parsed["last_action_detail"] = clean_err or "Tool error"
                                parsed["last_event_ts"] = rec_ts
                                events.append(
                                    {
                                        "ts": rec_ts,
                                        "kind": "error",
                                        "action_code": "tool_error",
                                        "tool": parsed["last_tool"],
                                        "detail": clean_err or "Tool error",
                                        "is_error": True,
                                    }
                                )
                            else:
                                parsed["last_was_error"] = False
                        elif btype == "text" and isinstance(block.get("text"), str):
                            if "request interrupted" in block["text"].lower():
                                saw_interrupt = True

                    if saw_interrupt or not saw_tool_result:
                        pending_ids.clear()
                        parsed["last_conv_stop_reason"] = (
                            "interrupted" if saw_interrupt else "user_prompt"
                        )
                    elif not pending_ids:
                        parsed["last_conv_stop_reason"] = "tool_result_received"

        parsed["pending_tool_ids"] = sorted(pending_ids)
        parsed["touched_paths"] = touched_paths[-12:]
        parsed["events"] = events[-30:]
        return parsed, conv_msg_count

    def _read_tail(
        self, fpath: pathlib.Path, mtime_ns: int, size: int, mtime: float
    ) -> dict[str, Any]:
        key = str(fpath)
        with self._lock:
            cached = self._tail_cache.get(key)
            if cached and cached[0] == mtime_ns and cached[1] == size:
                return cached[2]

        fallback: dict[str, Any] = {
            "model": "",
            "api_model": "",
            "api_effort": "",
            "query_source": "",
            "context_tokens": 0,
            "saw_write_tool": False,
            "ai_title": "",
            "branch": "",
            "cwd": "",
            "last_tool": "",
            "last_action_code": "ready",
            "last_action_detail": "",
            "last_event_ts": mtime,
            "last_was_error": False,
            "last_tool_is_long_cmd": False,
            "pending_tool_ids": [],
            "last_conv_stop_reason": "",
            "touched_paths": [],
            "events": [],
        }
        try:
            parsed, msg_cnt = self._parse_tail_window(fpath, size, mtime, 65536)
            if (msg_cnt < 3 or not parsed["api_model"]) and size > 65536:
                parsed, _ = self._parse_tail_window(fpath, size, mtime, 262144)
        except OSError:
            parsed = fallback

        with self._lock:
            _put_bounded(self._tail_cache, key, (mtime_ns, size, parsed))
        return parsed

    def scan(self, cutoff: float, now_ts: float) -> AdapterScanResult:
        res = AdapterScanResult()
        if not self.projects_dir.is_dir():
            return res

        agent_catalog = self.load_agent_catalog()
        live_sids = self.load_live_sessions()

        try:
            proj_entries = [e for e in os.scandir(self.projects_dir) if e.is_dir()]
        except OSError:
            return res

        for pe in proj_entries:
            pdir = pathlib.Path(pe.path)
            proj_slug = pe.name
            try:
                all_main = [
                    (fe.stat(), pathlib.Path(fe.path))
                    for fe in os.scandir(pdir)
                    if fe.is_file() and fe.name.endswith(".jsonl")
                ]
            except OSError:
                continue

            res.older_session_count += sum(1 for st, _ in all_main if st.st_mtime < cutoff)
            all_main.sort(key=lambda pair: pair[0].st_mtime, reverse=True)

            # Inspect top 18 sessions per project so active subagents under an older waiting parent are never dropped
            for st, mf in all_main[:18]:
                full_sid = mf.stem
                sub_dir = pdir / full_sid / "subagents"
                sub_entries: list[tuple[os.stat_result, pathlib.Path]] = []
                meta_stats: dict[str, tuple[int, pathlib.Path]] = {}

                if sub_dir.is_dir():
                    try:
                        for se in os.scandir(sub_dir):
                            if not se.is_file():
                                continue
                            if se.name.startswith("agent-") and se.name.endswith(".jsonl"):
                                try:
                                    sst_item = se.stat()
                                    if sst_item.st_mtime >= cutoff:
                                        sub_entries.append((sst_item, pathlib.Path(se.path)))
                                except OSError:
                                    pass
                            elif se.name.startswith("agent-") and se.name.endswith(".meta.json"):
                                try:
                                    stem_key = se.name[: -len(".meta.json")]
                                    meta_stats[stem_key] = (se.stat().st_mtime_ns, pathlib.Path(se.path))
                                except OSError:
                                    pass
                    except OSError:
                        sub_entries = []

                if st.st_mtime < cutoff and not sub_entries:
                    continue

                head = self._read_head(mf)
                tail = self._read_tail(mf, st.st_mtime_ns, st.st_size, st.st_mtime)
                tab_open = full_sid in live_sids

                cwd = tail["cwd"] or head["cwd"]
                proj_name = (
                    extract_clean_basename(cwd) if cwd else short_project_from_slug(proj_slug)
                )
                branch = redact_sensitive_text(tail["branch"] or head["gitBranch"])
                age_sec = max(0.0, now_ts - st.st_mtime)
                has_pending_tool = bool(tail["pending_tool_ids"])
                ended_cleanly = (not has_pending_tool) and tail["last_conv_stop_reason"] in (
                    "end_turn",
                    "stop_sequence",
                    "interrupted",
                )

                if tail["last_was_error"] and age_sec <= 900:
                    room_state = "ERROR"
                    state_code = "tool_error"
                    badge_tool = short_tool_badge(tail["last_tool"], "")
                elif has_pending_tool and tail["last_tool_is_long_cmd"] and age_sec <= 7200:
                    room_state = "WAITING"
                    state_code = "waiting_long_cmd"
                    badge_tool = short_tool_badge(tail["last_tool"], "Bash")
                elif has_pending_tool and age_sec <= 600:
                    room_state = "WORKING"
                    state_code = "running_tool"
                    badge_tool = short_tool_badge(tail["last_tool"], "Tool")
                elif ended_cleanly and age_sec > 20:
                    room_state = "IDLE"
                    state_code = "idle"
                    badge_tool = ""
                elif age_sec <= self.active_threshold_sec:
                    if tail["last_tool_is_long_cmd"]:
                        room_state = "WAITING"
                        state_code = "waiting_long_cmd"
                        badge_tool = short_tool_badge(tail["last_tool"], "Bash")
                    elif tail["last_tool"]:
                        room_state = "WORKING"
                        state_code = "running_tool"
                        badge_tool = short_tool_badge(tail["last_tool"], "Tool")
                    else:
                        room_state = "WORKING"
                        state_code = "running_thinking"
                        badge_tool = ""
                else:
                    room_state = "IDLE"
                    state_code = "idle"
                    badge_tool = ""

                agent_id = f"cc:{full_sid[:12]}"
                ai_title = (
                    tail["ai_title"]
                    if tail["ai_title"] and tail["ai_title"].lower() != "resume most recent session"
                    else ""
                )
                m_short, m_family, m_effort, me_key = normalize_model_and_effort(
                    tail["api_model"] or tail["model"],
                    tail["api_effort"],
                    source="claude",
                )
                tier_id = classify_tier("claude_main", "claude_main")
                role_key = "claude_main"
                glyph_meta = ROLE_GLYPHS[role_key]

                ag_obj = {
                    "id": agent_id,
                    "name": proj_name,
                    "name_kind": "main_session",
                    "subtitle": ai_title,
                    "action_code": tail["last_action_code"],
                    "role": role_key,
                    "role_short": glyph_meta["short"],
                    "role_glyph": glyph_meta["glyph"],
                    "function_key": "claude_main",
                    "tier": tier_id,
                    "tier_order": TIER_ORDER[tier_id],
                    "source": "claude_main",
                    "project": proj_name,
                    "branch": branch,
                    "model": m_short,
                    "model_family": m_family,
                    "effort": m_effort,
                    "model_effort_key": me_key,
                    "parent_effort_model": "",
                    "parent_session_id": full_sid,
                    "parent_project": proj_name,
                    "parent_sid_short": full_sid[:8],
                    "tab_open": tab_open,
                    "context_tokens": tail["context_tokens"],
                    "spawn_depth": 0,
                    "room_state": room_state,
                    "state_code": state_code,
                    "badge_tool": badge_tool,
                    "is_finished": False,
                    "current_tool": tail["last_tool"],
                    "status_text": tail["last_action_detail"],
                    "last_ts": st.st_mtime,
                    "file_size": st.st_size,
                    "age_sec": round(age_sec, 1),
                }

                if st.st_mtime >= cutoff or sub_entries:
                    res.agents.append(ag_obj)
                    res.file_index[agent_id] = {"adapter": "claude", "path": mf, "meta": ag_obj}
                    for ev in tail["events"][-8:]:
                        res.events.append(
                            {
                                **ev,
                                "agent_id": agent_id,
                                "agent_name": proj_name,
                                "name_kind": "main_session",
                                "role": role_key,
                                "role_short": glyph_meta["short"],
                                "project": proj_name,
                                "source": "claude_main",
                            }
                        )

                sub_entries.sort(key=lambda pair: pair[0].st_mtime, reverse=True)
                for sst, sf in sub_entries[:64]:
                    smeta: dict[str, Any] = {}
                    m_info = meta_stats.get(sf.stem)
                    if m_info is not None:
                        m_ns, meta_file = m_info
                        m_cache_key = str(meta_file)
                        with self._lock:
                            m_cached = self._meta_cache.get(m_cache_key)
                        if m_cached is not None and m_cached[0] == m_ns:
                            smeta = m_cached[1]
                        else:
                            try:
                                smeta = json.loads(
                                    meta_file.read_text(encoding="utf-8", errors="replace")
                                )
                            except (OSError, ValueError):
                                smeta = {}
                            with self._lock:
                                _put_bounded(self._meta_cache, m_cache_key, (m_ns, smeta))

                    shead = self._read_head(sf)
                    stail = self._read_tail(sf, sst.st_mtime_ns, sst.st_size, sst.st_mtime)
                    s_age = max(0.0, now_ts - sst.st_mtime)
                    s_type = str(smeta.get("agentType") or "subagent")
                    s_desc = redact_preview(str(smeta.get("description") or ""), 120)
                    skill_name = shead["skill_name"]
                    skill_args = shead["skill_args"]
                    cat_entry = agent_catalog.get(s_type.lower(), {})

                    # Ground truth model & effort: api-request -> assistant -> meta.model -> catalog (NEVER pickedEffortModel)
                    raw_s_model = (
                        stail["api_model"]
                        or stail["model"]
                        or str(smeta.get("model") or "")
                        or cat_entry.get("model", "")
                    )
                    raw_s_effort = (
                        stail["api_effort"]
                        or str(smeta.get("effort") or "")
                        or cat_entry.get("effort", "")
                    )
                    s_model, s_model_family, s_effort, s_me_key = normalize_model_and_effort(
                        raw_s_model,
                        raw_s_effort,
                        source="claude",
                    )
                    parent_effort_model = shorten_model_name(
                        str(smeta.get("pickedEffortModel") or "")
                    )

                    eff_proj, eff_branch = infer_effective_worktree(
                        shead["prompt_project"],
                        shead["prompt_branch"],
                        stail["touched_paths"],
                        proj_name,
                        stail["branch"] or branch,
                    )
                    eff_branch = redact_sensitive_text(eff_branch)

                    # Stop-hook safe completion rule
                    raw_pending = bool(stail["pending_tool_ids"])
                    meta_fin = smeta.get("finished")
                    s_finished = bool(meta_fin is True) or (
                        meta_fin is None
                        and not raw_pending
                        and stail["last_conv_stop_reason"] == "end_turn"
                        and s_age > 90.0
                    )
                    s_pending = raw_pending and not s_finished

                    s_role = map_agent_role(s_type, "claude_subagent", skill_name=skill_name)
                    s_glyph = ROLE_GLYPHS[s_role]
                    s_tier = classify_tier(
                        "claude_subagent",
                        s_type,
                        skill_name=skill_name,
                        description=s_desc or shead["first_prompt"],
                        saw_write_tool=stail["saw_write_tool"],
                    )

                    if skill_name:
                        sub_name = f"/{skill_name}"
                        name_kind = "skill"
                        func_key = f"skill:{skill_name.lower()}"
                        sub_subtitle = skill_args or s_desc
                    else:
                        sub_name = s_type
                        name_kind = "subagent"
                        func_key = s_type.lower() if s_type else "subagent"
                        sub_subtitle = s_desc

                    if stail["last_was_error"] and not s_finished and s_age <= 900:
                        s_state = "ERROR"
                        s_code = "tool_error"
                        s_badge_tool = short_tool_badge(stail["last_tool"], "")
                    elif not s_finished and s_pending and stail["last_tool_is_long_cmd"] and s_age <= 7200:
                        s_state = "WAITING"
                        s_code = "waiting_long_cmd"
                        s_badge_tool = short_tool_badge(stail["last_tool"], "Bash")
                    elif not s_finished and (s_age <= self.active_threshold_sec or (s_pending and s_age <= 600)):
                        s_state = "WORKING"
                        s_code = "running_tool" if stail["last_tool"] else "running_thinking"
                        s_badge_tool = short_tool_badge(stail["last_tool"], "")
                    elif s_finished:
                        s_state = "IDLE"
                        s_code = "done"
                        s_badge_tool = ""
                    else:
                        s_state = "IDLE"
                        s_code = "idle"
                        s_badge_tool = ""

                    sub_id = f"sub:{sf.stem[-10:]}"
                    sub_obj = {
                        "id": sub_id,
                        "name": sub_name,
                        "name_kind": name_kind,
                        "subtitle": sub_subtitle,
                        "action_code": stail["last_action_code"],
                        "role": s_role,
                        "role_short": s_glyph["short"],
                        "role_glyph": s_glyph["glyph"],
                        "function_key": func_key,
                        "tier": s_tier,
                        "tier_order": TIER_ORDER[s_tier],
                        "source": "claude_subagent",
                        "project": eff_proj,
                        "branch": eff_branch,
                        "model": s_model,
                        "model_family": s_model_family,
                        "effort": s_effort,
                        "model_effort_key": s_me_key,
                        "parent_effort_model": parent_effort_model,
                        "parent_session_id": full_sid,
                        "parent_project": proj_name,
                        "parent_sid_short": full_sid[:8],
                        "tab_open": tab_open,
                        "context_tokens": stail["context_tokens"],
                        "spawn_depth": int(smeta.get("spawnDepth") or 1),
                        "room_state": s_state,
                        "state_code": s_code,
                        "badge_tool": s_badge_tool,
                        "is_finished": s_finished,
                        "current_tool": stail["last_tool"],
                        "status_text": sub_subtitle or stail["last_action_detail"],
                        "last_ts": sst.st_mtime,
                        "file_size": sst.st_size,
                        "age_sec": round(s_age, 1),
                    }
                    res.agents.append(sub_obj)
                    res.file_index[sub_id] = {"adapter": "claude", "path": sf, "meta": sub_obj}

                    for ev in stail["events"][-4:]:
                        res.events.append(
                            {
                                **ev,
                                "agent_id": sub_id,
                                "agent_name": sub_name,
                                "name_kind": name_kind,
                                "role": s_role,
                                "role_short": s_glyph["short"],
                                "project": eff_proj,
                                "source": "claude_subagent",
                            }
                        )

        return res

    def get_timeline(self, index_entry: dict[str, Any]) -> list[dict[str, Any]]:
        fpath: pathlib.Path = index_entry["path"]
        if not fpath.is_file():
            return []
        try:
            st = fpath.stat()
            parsed = self._read_tail(fpath, st.st_mtime_ns, st.st_size, st.st_mtime)
            return list(reversed(parsed["events"]))[:30]
        except OSError:
            return []
