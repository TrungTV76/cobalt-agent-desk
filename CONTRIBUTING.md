# Contributing to Cobalt Agent Desk

Thank you for helping improve **Cobalt Agent Desk**! Contributions, bug reports, UI polish, and new AI agent adapters are very welcome.

## Core Project Invariants

Please keep these constraints intact in every Pull Request:

1. **Zero external runtime dependencies**: Backend code must use **Python 3.10+ standard library only** (`dependencies = []` in `pyproject.toml`), and frontend code uses plain HTML, CSS, and vanilla JavaScript (no build step required).
2. **100% Read-Only**: Never modify, lock, or touch user session logs or Git indices (`git --no-optional-locks` only).
3. **Strict CSP & XSS safety**: No inline `<script>` blocks or `onclick="..."` attributes in `index.html`. Escape all dynamic strings before inserting HTML, and keep language-invariant codes in Python with display strings in `cobalt_desk/ui/i18n.js` (`en` and `vi` keys must stay 1-to-1).
4. **Isolated tests (`tempfile` only)**: Unit tests in `tests/` must create synthetic fixtures inside `tempfile.TemporaryDirectory()` and must never read real `~/.claude` or `~/.gemini` directories.

## Fork -> Branch -> Pull Request Workflow

1. **Fork** the repository on GitHub and clone your fork locally:
   ```bash
   git clone https://github.com/<your-username>/cobalt-agent-desk.git
   cd cobalt-agent-desk
   ```
2. Create a focused feature or fix branch:
   ```bash
   git checkout -b feat/codex-adapter
   ```
3. Run the local verification checks before committing:
   ```bash
   python -m unittest discover -s tests -v
   node --check cobalt_desk/ui/i18n.js
   node --check cobalt_desk/ui/schematic.js
   node --check cobalt_desk/ui/office.js
   node --check cobalt_desk/ui/app.js
   ```
4. Test interactively in `--demo` mode:
   ```bash
   python server.py --demo --port 18780
   ```
5. Push your branch and open a **Pull Request** against `main`. GitHub Actions CI will automatically run the test suite across **Ubuntu, macOS, and Windows**.

## Adding a New AI Agent Adapter (e.g., Codex CLI, Cursor, Cline, OpenCode, Aider)

Adapters live under `cobalt_desk/adapters/`:

1. Create `cobalt_desk/adapters/<tool>.py` subclassing `BaseAgentAdapter` (`cobalt_desk/adapters/base.py`).
2. Implement `scan(cutoff, now_ts) -> AdapterScanResult` using bounded byte-seeking (`decode_utf8_tail`) and `(mtime_ns, size)` caching so large transcripts stay sub-second.
3. Pass all extracted text previews through `redact_preview()` / `redact_sensitive_text()` (`cobalt_desk/redaction.py`).
4. Emit language-invariant `room_state`, `state_code`, `action_code`, `role`, and `tier` (`cobalt_desk/models.py`).
5. Register the adapter in `AgentScanner` (`cobalt_desk/scanner.py`) and add synthetic `tempfile` tests in `tests/test_cobalt_desk.py`.
