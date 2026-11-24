"""Language-invariant models, 4-tier classification, and generic model/effort normalization."""

from __future__ import annotations

import datetime
import pathlib
import re
from typing import Any

from cobalt_desk.redaction import collapse_home_path, redact_sensitive_text

TIER_ORDER: dict[str, int] = {
    "T1_ORCHESTRATOR": 1,
    "T2_IMPLEMENTER": 2,
    "T3_REVIEWER_GATE": 3,
    "T4_SURVEY_RUNNER": 4,
}

ROLE_GLYPHS: dict[str, dict[str, str]] = {
    "claude_main": {"short": "MAIN", "glyph": "▣"},
    "implementer": {"short": "IMPL", "glyph": "⊞"},
    "security": {"short": "SEC", "glyph": "⛨"},
    "database": {"short": "DB", "glyph": "⌸"},
    "python": {"short": "PY", "glyph": "◈"},
    "typescript": {"short": "TS", "glyph": "◫"},
    "verifier": {"short": "VER", "glyph": "☑"},
    "skill_verify": {"short": "VRFY", "glyph": "◎"},
    "planner": {"short": "PLAN", "glyph": "◩"},
    "explore": {"short": "EXP", "glyph": "◎"},
    "surveyor": {"short": "SURV", "glyph": "◌"},
    "general": {"short": "SUB", "glyph": "◇"},
    "antigravity": {"short": "AGY", "glyph": "✦"},
}

WRITE_TOOLS: frozenset[str] = frozenset(
    {"edit", "edit_file", "multiedit", "write", "write_file", "notebookedit"}
)

LONG_RUNNING_CMD_RE = re.compile(
    r"\b(pytest|vitest|playwright|jest|cargo\s+test|go\s+test|"
    r"npm\s+(?:run\s+)?(?:test|build)|pnpm\s+(?:test|build)|yarn\s+(?:test|build)|"
    r"gh\s+run\s+watch|alembic|docker\s+(?:compose|build))\b",
    re.IGNORECASE,
)

EFFORT_SUFFIX_RE = re.compile(
    r"-(xhigh|high|medium|low|max|minimal|thinking)$",
    re.IGNORECASE,
)
PROVIDER_PREFIX_RE = re.compile(
    r"^(?:(?:us|eu|ap|global|apac)\.)?(?:anthropic|google|openai|meta)\.|"
    r"^(?:publishers/[^/]+/)?models/",
    re.IGNORECASE,
)
BEDROCK_AND_DATE_SUFFIX_RE = re.compile(
    r"(?:[-@]\d{8})?(?:-v\d+:\d+)?$",
    re.IGNORECASE,
)
CLAUDE_FAM_VER_RE = re.compile(
    r"^claude-(opus|sonnet|haiku)-(\d+(?:[-.]\d+)?)$",
    re.IGNORECASE,
)
CLAUDE_VER_FAM_RE = re.compile(
    r"^claude-(\d+(?:[-.]\d+)?)-(opus|sonnet|haiku)$",
    re.IGNORECASE,
)
CLAUDE_GENERIC_RE = re.compile(
    r"^claude-([a-z]+)-(\d+(?:[-.]\d+)?)$",
    re.IGNORECASE,
)
GEMINI_VER_VAR_RE = re.compile(
    r"^gemini-(\d+(?:\.\d+)?)-([a-z0-9-]+)$",
    re.IGNORECASE,
)
HOME_SLUG_PREFIX_RE = re.compile(
    r"^(?:[a-zA-Z]--Users-[^-]+-|-Users-[^-]+-|-home-[^-]+-)",
    re.IGNORECASE,
)
CONTAINER_SLUG_PREFIX_RE = re.compile(
    r"^(?:projects|repos|work|code|dev|src|workspace|workspaces|git|oss|tools)-",
    re.IGNORECASE,
)


def parse_iso_ts(raw_ts: Any, fallback: float) -> float:
    if not isinstance(raw_ts, str) or not raw_ts:
        return fallback
    try:
        cleaned = raw_ts.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(cleaned).timestamp()
    except ValueError:
        return fallback


def extract_clean_basename(raw_path: str) -> str:
    """Cross-platform basename supporting both Windows `\\` and POSIX `/` paths on any OS."""
    if not raw_path:
        return ""
    norm = raw_path.strip().replace("\\", "/").rstrip("/")
    if not norm:
        return ""
    return pathlib.PurePosixPath(norm).name


def short_project_from_slug(slug: str) -> str:
    """Extract clean repository name from Claude Code directory slug without breaking hyphens."""
    cleaned = slug.strip()
    if not cleaned:
        return "project"
    cleaned = HOME_SLUG_PREFIX_RE.sub("", cleaned)
    cleaned = CONTAINER_SLUG_PREFIX_RE.sub("", cleaned)
    cleaned = cleaned.strip("-")
    if "." in cleaned and len(cleaned.rsplit(".", 1)[-1]) >= 12:
        cleaned = cleaned.rsplit(".", 1)[0]
    return cleaned or slug.strip("-") or "project"


def map_agent_role(agent_type: str | None, source: str, skill_name: str = "") -> str:
    if source == "antigravity":
        return "antigravity"
    if skill_name:
        sk_low = skill_name.lower()
        if any(k in sk_low for k in ("verify", "review", "audit")):
            return "skill_verify"
        return "general"
    low = (agent_type or "").lower()
    if not low:
        return "claude_main"
    if any(k in low for k in ("implementer", "e2e-runner", "build-error", "refactor", "tdd", "coder")):
        return "implementer"
    if "verifier" in low or "verify" in low:
        return "verifier"
    if "security" in low or "sec-" in low or low.endswith("-sec"):
        return "security"
    if "database" in low or "db-" in low or "sql" in low:
        return "database"
    if "typescript" in low or "ts-" in low or "frontend" in low:
        return "typescript"
    if "python" in low or "code-reviewer" in low:
        return "python"
    if "surveyor" in low:
        return "surveyor"
    if any(k in low for k in ("planner", "architect", "chief-of-staff", "coordinator")):
        return "planner"
    if any(k in low for k in ("explore", "research", "guide")):
        return "explore"
    return "general"


def classify_tier(
    source: str,
    agent_type: str,
    skill_name: str = "",
    description: str = "",
    saw_write_tool: bool = False,
) -> str:
    """Classify an agent into one of the 4 language-invariant operational tier IDs."""
    if source in ("claude_main", "antigravity"):
        return "T1_ORCHESTRATOR"

    low = (agent_type or "").lower()
    desc_low = (description or "").lower()
    sk_low = (skill_name or "").lower()

    # Keep background memory consolidation in Tier 4 even if it writes memory files
    if "memory consolidation" in desc_low or "auto-dream" in desc_low:
        return "T4_SURVEY_RUNNER"

    if sk_low:
        if any(k in sk_low for k in ("verify", "review", "audit", "security")):
            return "T3_REVIEWER_GATE"
        if any(k in sk_low for k in ("plan", "architect", "grill")):
            return "T1_ORCHESTRATOR"
        return "T2_IMPLEMENTER" if saw_write_tool else "T4_SURVEY_RUNNER"

    if any(k in low for k in ("planner", "architect", "chief-of-staff", "coordinator")):
        return "T1_ORCHESTRATOR"

    if any(k in low for k in ("verifier", "reviewer", "auditor", "evaluator", "security")):
        return "T3_REVIEWER_GATE"

    if any(
        k in low
        for k in (
            "implementer",
            "e2e-runner",
            "build-error",
            "refactor",
            "doc-updater",
            "tdd",
            "generator",
        )
    ):
        return "T2_IMPLEMENTER"

    if any(k in low for k in ("explore", "surveyor", "guide", "researcher", "analyst")):
        return "T4_SURVEY_RUNNER"

    if low == "general-purpose" and saw_write_tool:
        return "T2_IMPLEMENTER"

    return "T4_SURVEY_RUNNER"


def normalize_model_and_effort(
    raw_model: str | None,
    raw_effort: str | None = None,
    source: str = "claude",
) -> tuple[str, str, str, str]:
    """Return (short_model, model_family, normalized_effort, model_effort_key).

    Strips provider regions (Bedrock/Vertex), date stamps (-20250929 / @20250929),
    version suffixes (-v1:0), and <synthetic>, using language-invariant keys.
    """
    m = (raw_model or "").strip()
    if m.lower() == "<synthetic>":
        m = ""
    eff = (raw_effort or "").strip().lower()

    if not m:
        eff_n = eff or "default"
        if source == "antigravity":
            return "antigravity", "Antigravity", eff_n, f"Antigravity · {eff_n}"
        return "", "unknown", eff_n, f"unknown · {eff_n}"

    work = PROVIDER_PREFIX_RE.sub("", m)
    work = BEDROCK_AND_DATE_SUFFIX_RE.sub("", work)

    sm = EFFORT_SUFFIX_RE.search(work)
    if sm:
        if not eff:
            eff = sm.group(1).lower()
        work = work[: sm.start()]

    # Second pass in case effort was before/after date stamp
    work = BEDROCK_AND_DATE_SUFFIX_RE.sub("", work).strip("-_.")
    low = work.lower()

    if low in ("sonnet", "opus", "haiku"):
        cap = low.capitalize()
        short_m, family = f"{low} (alias)", f"{cap} (alias)"
    elif m1 := CLAUDE_FAM_VER_RE.match(low):
        fam, ver = m1.group(1), m1.group(2).replace("-", ".")
        short_m, family = f"{fam}-{ver.replace('.', '-')}", f"{fam.capitalize()} {ver}"
    elif m2 := CLAUDE_VER_FAM_RE.match(low):
        ver, fam = m2.group(1).replace("-", "."), m2.group(2)
        short_m, family = f"{fam}-{ver.replace('.', '-')}", f"{fam.capitalize()} {ver}"
    elif m3 := CLAUDE_GENERIC_RE.match(low):
        fam, ver = m3.group(1), m3.group(2).replace("-", ".")
        short_m, family = f"{fam}-{ver.replace('.', '-')}", f"{fam.capitalize()} {ver}"
    elif mg := GEMINI_VER_VAR_RE.match(low):
        ver = mg.group(1)
        variant_raw = re.sub(r"-tiered$", "", mg.group(2))
        variant_title = " ".join(p.capitalize() for p in variant_raw.split("-") if p)
        short_m = f"gemini-{ver}-{variant_raw}"[:26]
        family = f"Gemini {ver} {variant_title}".strip()
    else:
        cleaned = re.sub(r"^(?:claude-|gemini-)", "", work, flags=re.IGNORECASE)[:26]
        short_m, family = cleaned, cleaned

    eff_norm = eff or "default"
    me_key = f"{family} · {eff_norm}"
    return short_m, family, eff_norm, me_key


def shorten_model_name(model: str | None) -> str:
    if not model:
        return ""
    s, _, _, _ = normalize_model_and_effort(model)
    return s


def summarize_tool_call(tool_name: str, tool_input: Any) -> tuple[str, str, str]:
    """Return language-invariant (action_code, safe_tool_name, redacted_short_detail)."""
    inp = tool_input if isinstance(tool_input, dict) else {}
    safe_tool = (tool_name or "Tool").strip()
    t_low = safe_tool.lower()

    if t_low in ("bash", "run_command"):
        cmd = str(inp.get("command") or inp.get("CommandLine") or "").strip()[:800]
        cmd_one = " ".join(cmd.splitlines())
        detail = collapse_home_path(redact_sensitive_text(cmd_one))[:140]
        return "run_command", safe_tool, detail

    if t_low in ("edit", "edit_file", "multiedit", "write", "write_file", "notebookedit"):
        fp = str(inp.get("file_path") or inp.get("Path") or inp.get("path") or "").strip()
        short_fp = extract_clean_basename(fp) if fp else ""
        code = "write_file" if "write" in t_low else "edit_file"
        return code, safe_tool, collapse_home_path(redact_sensitive_text(short_fp or fp))[:120]

    if t_low in ("read", "read_file"):
        fp = str(inp.get("file_path") or inp.get("Path") or inp.get("path") or "").strip()
        short_fp = extract_clean_basename(fp) if fp else ""
        return "read_file", safe_tool, collapse_home_path(redact_sensitive_text(short_fp or fp))[:120]

    if t_low in ("grep", "glob", "search_web", "find_by_name"):
        pat = str(inp.get("pattern") or inp.get("query") or inp.get("Pattern") or "").strip()
        return "search", safe_tool, redact_sensitive_text(pat)[:120]

    if t_low in ("agent", "task", "invoke_subagent"):
        desc = str(inp.get("description") or inp.get("Role") or inp.get("subagent_type") or "").strip()
        return "spawn_agent", safe_tool, redact_sensitive_text(desc)[:120]

    if t_low in ("todowrite", "todo_write", "update_steps"):
        return "todo_write", safe_tool, "TodoWrite"

    for key in ("description", "path", "Path", "file_path", "url", "query", "toolSummary"):
        if key in inp and inp[key]:
            val = collapse_home_path(redact_sensitive_text(str(inp[key])))[:120]
            return "call_tool", safe_tool, val
    return "call_tool", safe_tool, ""


def short_tool_badge(tool: str | None, fallback: str = "") -> str:
    t = (tool or fallback).strip()
    return (t[:13] + "…") if len(t) > 14 else t
