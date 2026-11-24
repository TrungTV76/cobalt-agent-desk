# Changelog

All notable changes to **Cobalt Agent Desk** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-24

### Added
- **Zero-dependency local server (`127.0.0.1:18780`)** using Python 3.10+ standard library HTTP + Server-Sent Events (SSE).
- **Multi-agent adapters (`cobalt_desk/adapters/`)**:
  - **Claude Code adapter**: Discovers main sessions, subagents, and `/skill` forks; extracts ground-truth `model` and `effort` from `api-request` records (adaptive `64KB -> 256KB` tail seek, ignoring parent `pickedEffortModel` and `<synthetic>`); detects live open tabs across Windows (`OpenProcess`) and macOS/Linux (`os.kill` + `/proc/<pid>/stat` + `startedAt`).
  - **Antigravity adapter**: Indexes recent conversation transcripts, context token usage, and step status without NTFS directory mtime blindness.
- **5 grouping modes & 4 operational tiers**: Role Tier (`T1` Orchestrator, `T2` Implementer, `T3` Reviewer/Gate, `T4` Survey/Background), Model & Effort, Function, Session Tree, and Flat view, with Lazy DOM rendering for collapsed groups.
- **Built-in privacy & security**: Comprehensive `O(N)` secret redaction (API keys, Bearer/Basic headers, URL tokens, multi-line PEM private keys, `curl -u`, query tokens, webhooks), `Privacy Mask` UI toggle for safe screen-sharing, strict `Host` / `Origin` / `Sec-Fetch-Site` validation, and `script-src 'self'` CSP.
- **Optional Git Worktrees Radar (`--repo`)**: Read-only parallel inspection via `git --no-optional-locks` (never creates `index.lock`) with automatic default branch detection (`main` / `master`).
- **Synthetic `--demo` mode**: Fully isolated 5-source temporary environment (`acme-api`, `acme-web`, `docs-site`) for instant zero-data evaluation.
- **Bilingual UI (`EN | VI`) & Cobalt Grid + C3 theme**: Architectural warm-paper light mode and high-contrast dark mode, `/` quick filter, and `uvx` / `pipx` zero-install CLI entry points.
