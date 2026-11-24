"""Fast O(N) secret redaction, home-path masking, and UTF-8 safe tail decoding."""

from __future__ import annotations

import pathlib
import re

# Benign structural/programming *_KEY identifiers that must NOT be masked as secrets
BENIGN_KEY_SUFFIXES: tuple[str, ...] = (
    "SORT_KEY",
    "CACHE_KEY",
    "ROLE_KEY",
    "PRIMARY_KEY",
    "FOREIGN_KEY",
    "UNIQUE_KEY",
    "PARTITION_KEY",
    "GROUP_KEY",
    "ORDER_KEY",
    "INDEX_KEY",
    "MAP_KEY",
    "DICT_KEY",
    "HASH_KEY",
    "LOOKUP_KEY",
    "CONFIG_KEY",
    "SETTING_KEY",
    "STATE_KEY",
    "ITEM_KEY",
    "ROW_KEY",
    "COL_KEY",
    "FIELD_KEY",
    "PROP_KEY",
    "ATTR_KEY",
    "EVENT_KEY",
    "TAB_KEY",
    "NAV_KEY",
    "VIEW_KEY",
    "QUERY_KEY",
    "PARAM_KEY",
    "HEADER_KEY",
    "PATH_KEY",
    "ROUTING_KEY",
    "SHARD_KEY",
    "HOT_KEY",
    "META_KEY",
    "DEDUP_KEY",
    "CANDIDATE_KEY",
    "SURROGATE_KEY",
    "NATURAL_KEY",
    "COMPOSITE_KEY",
)

EXACT_SECRET_KEYS: frozenset[str] = frozenset(
    {
        "PASSWORD",
        "PASSWD",
        "PGPASSWORD",
        "DB_PASS",
        "SECRET",
        "TOKEN",
        "API_KEY",
        "APIKEY",
        "PRIVATE_KEY",
        "ACCESS_KEY",
        "SECRET_KEY",
        "SIGNING_KEY",
        "CLIENT_SECRET",
        "ACCESS_TOKEN",
        "REFRESH_TOKEN",
        "AUTH_TOKEN",
        "ID_TOKEN",
        "SESSION_SECRET",
        "WEBHOOK_SECRET",
    }
)

SECRET_KEY_SUFFIXES: tuple[str, ...] = (
    "_PASSWORD",
    "_PASSWD",
    "_SECRET",
    "_TOKEN",
    "_PAT",
    "_API_KEY",
    "_APIKEY",
    "_PRIVATE_KEY",
    "_ACCESS_KEY",
    "_SECRET_KEY",
    "_SIGNING_KEY",
    "_DB_PASS",
    "_PG_PASS",
    "_SQL_PASS",
    "_REDIS_PASS",
    "_SMTP_PASS",
    "_ADMIN_PASS",
    "_USER_PASS",
    "_ROOT_PASS",
    "_AUTH_PASS",
)

KV_ASSIGN_RE = re.compile(
    r"((?<![A-Za-z0-9_-])[A-Za-z0-9_-]{2,64})(\s*[=:]\s*)"
    r"(\\\"(?:[^\\\"]|\\\\)*\\\"|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s&;,|'\"`\\]+)"
)
ENV_SUBSCRIPT_RE = re.compile(
    r"(\b(?:environ|env|putenv)\s*(?:\[|\()\s*([\"'])([A-Za-z0-9_-]{2,64})\2\s*\]?\s*(?:=\s*|,\s*))"
    r"(\\\"(?:[^\\\"]|\\\\)*\\\"|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,)\]]+)",
    re.IGNORECASE,
)
JSON_KV_RE = re.compile(
    r'(?:"([A-Za-z0-9_-]{2,64})"(\s*:\s*)"(?:\\.|[^"\\])*"|'
    r"'([A-Za-z0-9_-]{2,64})'(\s*:\s*)'(?:\\.|[^'\\])*')"
)

STATIC_REDACT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Multi-line or truncated PEM private key blocks (matches even without closing END tag)
    (
        re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*"),
        "-----BEGIN PRIVATE KEY----- [REDACTED]",
    ),
    # HTTP Cookie / Set-Cookie headers
    (
        re.compile(
            r"(\b(?:Set-Cookie|Cookie)\s*:\s*)(?:\"[^\"]*\"|'[^']*'|[^\r\n\"']+)",
            re.IGNORECASE,
        ),
        r"\1***",
    ),
    # Authorization headers
    (
        re.compile(
            r"(\bAuthorization\s*:\s*(?:Bearer|Basic|Digest|Token)\s+)[A-Za-z0-9\-._~+/]+=*",
            re.IGNORECASE,
        ),
        r"\1***",
    ),
    (
        re.compile(r"(\bBearer\s+)[A-Za-z0-9\-._~+/]{8,}=*", re.IGNORECASE),
        r"\1***",
    ),
    # CLI credential flags (--password, --token, --api-key, --secret, --user, curl -u)
    (
        re.compile(
            r"(--(?:password|passwd|token|api-key|apikey|secret|client-secret)(?:\s+|=))(?:\"[^\"]*\"|'[^']*'|[^\s&;,|]+)",
            re.IGNORECASE,
        ),
        r"\1***",
    ),
    (
        re.compile(
            r"((?:^|\s)(?:-u|--user)(?:\s+|=))(?:\"[^\"]*\"|'[^']*'|[^\s&;,|]+:[^\s&;,|]+)",
        ),
        r"\1***",
    ),
    # DSN / URL with user:password@host
    (
        re.compile(
            r"((?:postgres(?:ql)?|mysql|mariadb|mssql|oracle|mongodb(?:\+srv)?|rediss?|amqps?|https?)(?:\+[a-z0-9_]+)?://[^:/\s@'\"]*:)([^@\s/'\"]+)(@)",
            re.IGNORECASE,
        ),
        r"\1***\3",
    ),
    # HTTPS URL with single token before @host (e.g. https://<pat>@github.com/org/repo.git)
    (
        re.compile(
            r"(https?://)([A-Za-z0-9._~+\-]{6,})(@[A-Za-z0-9.\-]+)",
            re.IGNORECASE,
        ),
        r"\1***\3",
    ),
    # Sensitive URL query-string parameters (?token=, &sig=, &X-Amz-Signature=, &code=, etc.)
    (
        re.compile(
            r"([?&](?:token|access_token|refresh_token|auth_token|id_token|api_key|apikey|secret|client_secret|password|sig|signature|x-amz-signature|x-amz-credential|x-amz-security-token|code)=)([^&\s\"'#]+)",
            re.IGNORECASE,
        ),
        r"\1***",
    ),
    # Slack & Discord incoming webhook URLs
    (
        re.compile(r"(https://hooks\.slack\.com/services/)[A-Za-z0-9/_-]+", re.IGNORECASE),
        r"\1***",
    ),
    (
        re.compile(
            r"(https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/[0-9]+/)[A-Za-z0-9_-]+",
            re.IGNORECASE,
        ),
        r"\1***",
    ),
    # Well-known API key, cloud, package registry, and AI provider prefixes
    (
        re.compile(
            r"\b(?:"
            r"sk-ant-[A-Za-z0-9\-_]{8,}|"
            r"sk-proj-[A-Za-z0-9\-_]{8,}|"
            r"sk-svcacct-[A-Za-z0-9\-_]{8,}|"
            r"sk-or-v1-[A-Za-z0-9\-_]{12,}|"
            r"sk-[A-Za-z0-9]{12,}T3BlbkFJ[A-Za-z0-9]{8,}|"
            r"gsk_[A-Za-z0-9]{16,}|"
            r"gh[pousr]_[A-Za-z0-9_]{8,}|"
            r"github_pat_[A-Za-z0-9_]{12,}|"
            r"glpat-[A-Za-z0-9\-_]{10,}|"
            r"AIza[0-9A-Za-z\-_]{20,}|"
            r"(?:AKIA|ASIA)[0-9A-Z]{16}|"
            r"xox[baprs]-[0-9A-Za-z\-]{10,}|"
            r"(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{12,}|"
            r"npm_[A-Za-z0-9]{16,}|"
            r"pypi-[A-Za-z0-9\-_]{20,}|"
            r"hf_[A-Za-z0-9]{16,}|"
            r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
            r")\b"
        ),
        "***",
    ),
)

GENERIC_HOME_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]Users[\\/][A-Za-z0-9._-]+|(?<![A-Za-z0-9._-])/(?:Users|home)/[A-Za-z0-9._-]+)"
)


def decode_utf8_tail(raw: bytes, truncated_head: bool = False) -> str:
    """Safely decode a byte slice taken from the tail of a UTF-8 file without U+FFFD artifacts."""
    if not raw:
        return ""
    start = 0
    if truncated_head:
        while start < min(4, len(raw)) and (raw[start] & 0xC0) == 0x80:
            start += 1
        nl = raw.find(b"\n", start, min(len(raw), start + 240))
        if nl != -1 and (len(raw) - nl) > 64:
            start = nl + 1
    return raw[start:].decode("utf-8", errors="replace")


def _is_secret_identifier(raw_key: str) -> bool:
    norm = raw_key.strip().upper().replace("-", "_")
    if norm in EXACT_SECRET_KEYS:
        return True
    if norm.endswith(SECRET_KEY_SUFFIXES):
        return True
    if norm.endswith("_KEY") and not norm.endswith(BENIGN_KEY_SUFFIXES):
        return True
    return False


def _redact_kv_cb(match: re.Match[str]) -> str:
    key = match.group(1)
    if _is_secret_identifier(key):
        return f"{key}{match.group(2)}***"
    return match.group(0)


def _redact_json_kv_cb(match: re.Match[str]) -> str:
    if match.group(1) is not None:
        key, sep = match.group(1), match.group(2)
        if _is_secret_identifier(key):
            return f'"{key}"{sep}"***"'
        return match.group(0)
    key, sep = match.group(3), match.group(4)
    if _is_secret_identifier(key):
        return f"'{key}'{sep}'***'"
    return match.group(0)


def _redact_env_sub_cb(match: re.Match[str]) -> str:
    prefix, key = match.group(1), match.group(3)
    if _is_secret_identifier(key):
        return f'{prefix}"***"'
    return match.group(0)


def collapse_home_path(text: str, home_dir: pathlib.Path | None = None) -> str:
    """Replace OS user home directories with `~` so screenshots do not expose usernames."""
    if not text:
        return ""
    out = text
    try:
        h = (home_dir or pathlib.Path.home()).resolve()
        h_posix = h.as_posix().rstrip("/")
        h_win = str(h).rstrip("\\/")
        for candidate in (h_win, h_posix):
            if candidate and len(candidate) > 3:
                out = re.sub(re.escape(candidate), "~", out, flags=re.IGNORECASE)
    except OSError:
        pass
    return GENERIC_HOME_PATH_RE.sub("~", out)


def redact_sensitive_text(text: str) -> str:
    """Mask passwords, API keys, bearer/basic tokens, cookies, PEM keys, and DSN credentials."""
    if not text:
        return ""
    out = text
    for rx, repl in STATIC_REDACT_PATTERNS:
        out = rx.sub(repl, out)
    out = ENV_SUBSCRIPT_RE.sub(_redact_env_sub_cb, out)
    out = JSON_KV_RE.sub(_redact_json_kv_cb, out)
    out = KV_ASSIGN_RE.sub(_redact_kv_cb, out)
    return out


def redact_preview(raw_text: str, max_len: int = 140) -> str:
    """Redact on a bounded 4KB window BEFORE line slicing so multiline PEM/secrets never leak."""
    stripped = raw_text.strip()
    if not stripped:
        return ""
    bounded = stripped[:4096]
    redacted = collapse_home_path(redact_sensitive_text(bounded))
    lines = [ln.strip() for ln in redacted.splitlines() if ln.strip()][:2]
    return " ".join(lines)[:max_len]
