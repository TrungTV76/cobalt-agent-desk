"""Read-only adapter for Google Antigravity conversation transcripts."""

from __future__ import annotations

import json
import os
import pathlib
import re
import threading
import time
from typing import Any

from cobalt_desk.adapters.base import AdapterScanResult, BaseAgentAdapter
from cobalt_desk.models import (
    ROLE_GLYPHS,
    TIER_ORDER,
    classify_tier,
    normalize_model_and_effort,
    parse_iso_ts,
    short_tool_badge,
    summarize_tool_call,
)
from cobalt_desk.redaction import decode_utf8_tail, redact_preview

MAX_CACHE_ENTRIES = 512
BRAIN_INDEX_TTL_SEC = 30.0

IGNORED_PATH_SEGMENTS: frozenset[str] = frozenset(
    {
        "users",
        "home",
        "appdata",
        "local",
        "roaming",
        "library",
        "application support",
        "tmp",
        "temp",
        "var",
        "opt",
        "etc",
        "usr",
        "mnt",
        "c",
        "d",
        "e",
        "src",
        "lib",
        "app",
        "tests",
        "test",
        "docs",
        "scripts",
        "ui",
        "public",
        "assets",
        "components",
        "pages",
        "node_modules",
        "scratch",
        "brain",
        "antigravity",
        "builtin",
        "skills",
        "projects",
        "repos",
        "work",
        "code",
        "dev",
        "workspace",
        "workspaces",
        "git",
        "oss",
        "tools",
    }
)
ABS_PATH_TOKEN_RE = re.compile(
    r"(?:[A-Za-z]:[\\/][A-Za-z0-9._\-\\/]+|/(?:Users|home|workspace|workspaces|projects|repos|srv)/[A-Za-z0-9._\-/]+)"
)


def _put_bounded(cache: dict[str, Any], key: str, value: Any) -> None:
    if key in cache:
        cache.pop(key, None)
    elif len(cache) >= MAX_CACHE_ENTRIES:
        oldest_key = next(iter(cache))
        cache.pop(oldest_key, None)
    cache[key] = value


def _extract_user_prompt_preview(raw_text: str) -> str:
    txt = raw_text
    if "<USER_REQUEST>" in txt:
        txt = txt.split("<USER_REQUEST>", 1)[1].split("</USER_REQUEST>", 1)[0]
    for ln in txt.splitlines():
        s = ln.strip()
        if s and not s.startswith(("Comments on artifact", "The user has approved", "<")):
            return redact_preview(s, 80)
    return ""


def infer_project_from_paths(
    file_paths: list[str], home_dir: pathlib.Path | None = None
) -> str:
    """Infer clean workspace/repository folder name from tool file paths without leaking OS usernames."""
    home_name = ""
    try:
        home_name = (home_dir or pathlib.Path.home()).name.lower()
    except OSError:
        pass

    counts: dict[str, int] = {}
    for raw in file_paths:
        if not raw:
            continue
        candidates = [raw] if ("\n" not in raw and len(raw) < 260) else [
            m.group(0) for m in ABS_PATH_TOKEN_RE.finditer(raw)
        ]
        for cand in candidates:
            norm = cand.strip().replace("\\", "/")
            if "/.gemini/" in norm.lower() or "/.claude/" in norm.lower():
                continue
            if ":" not in norm and not norm.startswith("/"):
                continue
            segs = [
                s
                for s in norm.split("/")
                if s and not s.endswith(":") and not s.startswith(".")
            ]
            if len(segs) < 2:
                continue
            # Drop trailing filename if it looks like a file
            dirs = segs[:-1] if "." in segs[-1] else segs
            # Strip leading Users/<username> or home/<username>
            if len(dirs) >= 2 and dirs[0].lower() in ("users", "home"):
                dirs = dirs[2:]
            for d in dirs:
                d_low = d.lower()
                if (
                    d_low in IGNORED_PATH_SEGMENTS
                    or d_low == home_name
                    or len(d) < 2
                    or re.fullmatch(r"[0-9a-f-]{16,}", d_low)
                ):
                    continue
                counts[d] = counts.get(d, 0) + 1
                break

    if counts:
        return max(counts.items(), key=lambda kv: kv[1])[0]
    return "Antigravity"


class AntigravityAdapter(BaseAgentAdapter):
    """Discovers Google Antigravity IDE / App conversation sessions."""

    source_group = "antigravity"

    def __init__(
        self,
        brain_dir: pathlib.Path,
        active_threshold_sec: float = 120.0,
    ) -> None:
        self.brain_dir = brain_dir
        self.active_threshold_sec = active_threshold_sec
        self._lock = threading.Lock()
        self._head_cache: dict[str, dict[str, Any]] = {}
        self._tail_cache: dict[str, tuple[int, int, dict[str, Any]]] = {}
        self._brain_index_ts = 0.0
        self._brain_known_dirs: set[str] = set()
        self._brain_top_files: list[pathlib.Path] = []
        self._older_cached = 0

    def _read_head(self, fpath: pathlib.Path) -> dict[str, Any]:
        key = f"ag_head::{fpath}"
        with self._lock:
            if key in self._head_cache:
                return self._head_cache[key]
        meta: dict[str, Any] = {"first_prompt": "", "head_paths": []}
        try:
            with fpath.open("rb") as fh:
                raw = fh.read(12288)
            txt = raw.decode("utf-8", errors="replace")
            paths: list[str] = []
            for ln in txt.splitlines()[:15]:
                ln = ln.strip()
                if not ln.startswith("{"):
                    continue
                try:
                    obj = json.loads(ln)
                except ValueError:
                    continue
                content_s = str(obj.get("content") or "")
                if obj.get("type") == "USER_INPUT" and content_s and not meta["first_prompt"]:
                    meta["first_prompt"] = _extract_user_prompt_preview(content_s)
                for tc in obj.get("tool_calls") or []:
                    if isinstance(tc, dict):
                        targs = tc.get("arguments") or tc.get("args") or {}
                        if isinstance(targs, dict):
                            for k, v in targs.items():
                                if isinstance(v, str) and k in ("Path", "path", "file_path", "Cwd"):
                                    paths.append(v[:240])
            meta["head_paths"] = paths[:12]
        except OSError:
            pass
        with self._lock:
            _put_bounded(self._head_cache, key, meta)
        return meta

    def _read_tail(
        self, fpath: pathlib.Path, mtime_ns: int, size: int, mtime: float
    ) -> dict[str, Any]:
        key = str(fpath)
        with self._lock:
            cached = self._tail_cache.get(key)
            if cached and cached[0] == mtime_ns and cached[1] == size:
                return cached[2]

        head_meta = self._read_head(fpath)
        tail_bytes = 65536
        parsed: dict[str, Any] = {
            "model": "",
            "context_tokens": 0,
            "last_tool": "",
            "last_action_code": "ready",
            "last_action_detail": "",
            "last_event_ts": mtime,
            "last_was_error": False,
            "last_step_type": "",
            "last_step_status": "",
            "last_step_has_tools": False,
            "title": "",
            "project": "Antigravity",
            "events": [],
        }

        brain_dir = fpath.parents[2]
        file_signals: list[str] = list(head_meta.get("head_paths", []))
        try:
            md_files = [
                (e.stat().st_mtime, pathlib.Path(e.path))
                for e in os.scandir(brain_dir)
                if e.is_file() and e.name.lower().endswith(".md")
            ]
            md_files.sort(key=lambda pair: pair[0], reverse=True)
            for _mt, cf in md_files[:2]:
                try:
                    lines_md = cf.read_text(encoding="utf-8", errors="replace").splitlines()[:10]
                    if not parsed["title"] and lines_md:
                        first_hdr = next((x for x in lines_md if x.strip()), "")
                        parsed["title"] = redact_preview(first_hdr.lstrip("# ").strip(), 80)
                except OSError:
                    pass
        except OSError:
            pass

        if not parsed["title"] and head_meta.get("first_prompt"):
            parsed["title"] = head_meta["first_prompt"]

        try:
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
                try:
                    obj = json.loads(ln)
                except ValueError:
                    continue

                stype = str(obj.get("type") or "")
                status = str(obj.get("status") or "")
                rec_ts = parse_iso_ts(obj.get("created_at"), mtime)
                tcalls = obj.get("tool_calls") or []
                has_tools = isinstance(tcalls, list) and len(tcalls) > 0

                if stype == "PLANNER_RESPONSE":
                    ag_m = str(obj.get("model") or "").strip()
                    if ag_m:
                        parsed["model"] = ag_m
                    ag_ctx = int(obj.get("input_tokens") or 0) + int(
                        obj.get("cache_read_tokens") or 0
                    )
                    if ag_ctx > 0:
                        parsed["context_tokens"] = ag_ctx

                parsed["last_step_type"] = stype
                parsed["last_step_status"] = status
                parsed["last_step_has_tools"] = has_tools

                if has_tools:
                    for tc in tcalls:
                        if not isinstance(tc, dict):
                            continue
                        tname = str(tc.get("name") or "tool")
                        targs = tc.get("arguments") or tc.get("args") or {}
                        if isinstance(targs, dict):
                            for k, av in targs.items():
                                if isinstance(av, str) and k in ("Path", "path", "file_path", "Cwd"):
                                    file_signals.append(av[:240])
                        act_code, safe_tool, detail = summarize_tool_call(tname, targs)
                        parsed["last_tool"] = safe_tool
                        parsed["last_action_code"] = "tool_error" if status == "ERROR" else act_code
                        parsed["last_action_detail"] = detail
                        parsed["last_event_ts"] = rec_ts
                        parsed["last_was_error"] = status == "ERROR"
                        events.append(
                            {
                                "ts": rec_ts,
                                "kind": "error" if status == "ERROR" else "tool",
                                "action_code": "tool_error" if status == "ERROR" else act_code,
                                "tool": safe_tool,
                                "detail": detail,
                                "is_error": status == "ERROR",
                            }
                        )
                elif stype == "USER_INPUT":
                    u_prev = _extract_user_prompt_preview(str(obj.get("content") or ""))
                    parsed["last_tool"] = ""
                    parsed["last_action_code"] = "thinking"
                    parsed["last_action_detail"] = u_prev
                    parsed["last_event_ts"] = rec_ts
                    parsed["last_was_error"] = False
                elif stype == "GENERIC" and status == "ERROR":
                    clean_err = redact_preview(str(obj.get("content") or ""), 130)
                    parsed["last_was_error"] = True
                    parsed["last_action_code"] = "tool_error"
                    parsed["last_action_detail"] = clean_err or "Step ERROR"
                    parsed["last_event_ts"] = rec_ts
                    events.append(
                        {
                            "ts": rec_ts,
                            "kind": "error",
                            "action_code": "tool_error",
                            "tool": parsed["last_tool"],
                            "detail": clean_err or "Step ERROR",
                            "is_error": True,
                        }
                    )
                elif stype == "PLANNER_RESPONSE" and obj.get("content"):
                    clean = redact_preview(str(obj["content"]), 130)
                    parsed["last_action_code"] = "reply"
                    parsed["last_action_detail"] = clean
                    parsed["last_event_ts"] = rec_ts
                    parsed["last_was_error"] = status == "ERROR"
                    events.append(
                        {
                            "ts": rec_ts,
                            "kind": "reply",
                            "action_code": "reply",
                            "tool": "",
                            "detail": clean,
                            "is_error": status == "ERROR",
                        }
                    )
            parsed["events"] = events[-30:]
        except OSError:
            pass

        parsed["project"] = infer_project_from_paths(file_signals)
        with self._lock:
            _put_bounded(self._tail_cache, key, (mtime_ns, size, parsed))
        return parsed

    def _get_recent_transcripts(
        self, cutoff: float, now_ts: float
    ) -> tuple[list[tuple[float, pathlib.Path]], int]:
        if not self.brain_dir.is_dir():
            return [], 0

        with self._lock:
            need_full = (
                (now_ts - self._brain_index_ts) >= BRAIN_INDEX_TTL_SEC or not self._brain_top_files
            )
            known_dirs = set(self._brain_known_dirs)
            cached_top = list(self._brain_top_files)

        if need_full:
            all_found: list[tuple[float, pathlib.Path]] = []
            seen_names: set[str] = set()
            dir_entries: list[tuple[float, pathlib.Path]] = []
            try:
                for entry in os.scandir(self.brain_dir):
                    if not entry.is_dir():
                        continue
                    seen_names.add(entry.name)
                    try:
                        dir_entries.append((entry.stat().st_mtime, pathlib.Path(entry.path)))
                    except OSError:
                        continue
            except OSError:
                return [], 0

            dir_entries.sort(key=lambda pair: pair[0], reverse=True)
            for _dmt, bpath in dir_entries[:80]:
                tf = bpath / ".system_generated" / "logs" / "transcript.jsonl"
                try:
                    st = tf.stat()
                    all_found.append((st.st_mtime, tf))
                except OSError:
                    continue

            all_found.sort(key=lambda pair: pair[0], reverse=True)
            older = sum(1 for mt, _ in all_found if mt < cutoff)
            top_paths = [fp for _mt, fp in all_found[:36]]
            with self._lock:
                self._brain_index_ts = now_ts
                self._brain_known_dirs = seen_names
                self._brain_top_files = top_paths
                self._older_cached = older
            return [(mt, fp) for mt, fp in all_found if mt >= cutoff][:10], older

        candidates: dict[str, tuple[float, pathlib.Path]] = {}
        new_dirs: set[str] = set()
        try:
            for entry in os.scandir(self.brain_dir):
                if entry.is_dir() and entry.name not in known_dirs:
                    new_dirs.add(entry.name)
                    tf = pathlib.Path(entry.path) / ".system_generated" / "logs" / "transcript.jsonl"
                    try:
                        st = tf.stat()
                        candidates[str(tf)] = (st.st_mtime, tf)
                    except OSError:
                        pass
        except OSError:
            pass

        for tf in cached_top:
            try:
                st = tf.stat()
                candidates[str(tf)] = (st.st_mtime, tf)
            except OSError:
                continue

        if new_dirs:
            with self._lock:
                self._brain_known_dirs.update(new_dirs)
                self._brain_top_files = [
                    fp
                    for _mt, fp in sorted(candidates.values(), key=lambda p: p[0], reverse=True)[:36]
                ]

        recent = [pair for pair in candidates.values() if pair[0] >= cutoff]
        recent.sort(key=lambda pair: pair[0], reverse=True)
        return recent[:10], self._older_cached

    def scan(self, cutoff: float, now_ts: float) -> AdapterScanResult:
        res = AdapterScanResult()
        candidates, older_cnt = self._get_recent_transcripts(cutoff, now_ts)
        res.older_session_count = older_cnt

        for _mt, af in candidates:
            try:
                ast = af.stat()
            except OSError:
                continue
            atail = self._read_tail(af, ast.st_mtime_ns, ast.st_size, ast.st_mtime)
            a_age = max(0.0, now_ts - ast.st_mtime)
            cid_full = af.parents[2].name
            cid_short = cid_full[:8]
            ag_done_turn = (
                atail["last_step_type"] == "PLANNER_RESPONSE"
                and atail["last_step_status"] == "DONE"
                and not atail["last_step_has_tools"]
            )

            if atail["last_was_error"] and a_age <= 900:
                a_state = "ERROR"
                a_code = "step_error"
                a_badge_tool = short_tool_badge(atail["last_tool"], "")
            elif ag_done_turn and a_age > 20:
                a_state = "IDLE"
                a_code = "idle"
                a_badge_tool = ""
            elif a_age <= self.active_threshold_sec:
                a_state = "WORKING"
                a_code = "running_tool" if atail["last_tool"] else "running_thinking"
                a_badge_tool = short_tool_badge(atail["last_tool"], "")
            else:
                a_state = "IDLE"
                a_code = "idle"
                a_badge_tool = ""

            ag_proj = atail["project"] or "Antigravity"
            ag_m_short, ag_m_family, ag_effort, ag_me_key = normalize_model_and_effort(
                atail["model"],
                None,
                source="antigravity",
            )
            ag_tier = classify_tier("antigravity", "antigravity")
            ag_id = f"agy:{cid_short}"
            glyph_meta = ROLE_GLYPHS["antigravity"]
            ag_name = f"Antigravity · {cid_short}"

            ag_obj = {
                "id": ag_id,
                "name": ag_name,
                "name_kind": "antigravity",
                "subtitle": atail["title"],
                "action_code": atail["last_action_code"],
                "role": "antigravity",
                "role_short": glyph_meta["short"],
                "role_glyph": glyph_meta["glyph"],
                "function_key": "antigravity",
                "tier": ag_tier,
                "tier_order": TIER_ORDER[ag_tier],
                "source": "antigravity",
                "project": ag_proj,
                "branch": "",
                "model": ag_m_short,
                "model_family": ag_m_family,
                "effort": ag_effort,
                "model_effort_key": ag_me_key,
                "parent_effort_model": "",
                "parent_session_id": cid_full,
                "parent_project": ag_proj,
                "parent_sid_short": cid_short,
                "tab_open": a_age <= 300.0,
                "context_tokens": atail["context_tokens"],
                "spawn_depth": 0,
                "room_state": a_state,
                "state_code": a_code,
                "badge_tool": a_badge_tool,
                "is_finished": False,
                "current_tool": atail["last_tool"],
                "status_text": atail["last_action_detail"] or atail["title"],
                "last_ts": ast.st_mtime,
                "file_size": ast.st_size,
                "age_sec": round(a_age, 1),
            }
            res.agents.append(ag_obj)
            res.file_index[ag_id] = {"adapter": "antigravity", "path": af, "meta": ag_obj}

            for ev in atail["events"][-5:]:
                res.events.append(
                    {
                        **ev,
                        "agent_id": ag_id,
                        "agent_name": ag_name,
                        "name_kind": "antigravity",
                        "role": "antigravity",
                        "role_short": glyph_meta["short"],
                        "project": ag_proj,
                        "source": "antigravity",
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
