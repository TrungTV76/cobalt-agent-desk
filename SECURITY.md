# Security Policy & Privacy Model

## Design Principles

**Cobalt Agent Desk** is designed from the ground up as a **100% local, read-only observability tool**:

1. **Localhost-only binding**: The HTTP/SSE server refuses to bind to any interface other than `127.0.0.1`, `localhost`, or `::1`.
2. **DNS-rebinding & cross-origin protection**: Every request validates `Host`, `Sec-Fetch-Site`, and `Origin` headers, rejecting `"null"` and any non-localhost origin.
3. **Strict Content Security Policy (CSP)**: Main UI pages enforce `script-src 'self'` with zero inline JavaScript (`onclick` or inline `<script>`).
4. **Zero file mutations / zero Git locks**: Session `.jsonl` files are opened strictly read-only (`"rb"`), and the optional Git Worktrees Radar runs `git --no-optional-locks` so active coding agents never encounter `.git/index.lock` contention.
5. **Automatic `O(N)` secret redaction**: Before any prompt, tool command, or error preview leaves the Python process, `cobalt_desk/redaction.py` masks API keys (`sk-ant-`, `sk-proj-`, `sk-or-v1-`, `gsk_`, `ghp_`, `glpat-`, `AKIA`, `ASIA`, `xoxb-`, `sk_live_`, `npm_`, `hf_`), `Bearer`/`Basic` tokens, `Cookie` headers, URL/DSN credentials (`user:pass@host` and `<pat>@host`), sensitive query-string tokens, webhook URLs, `curl -u`, and multi-line PEM private keys, while collapsing OS home paths (`C:\Users\<name>`, `/Users/<name>`, `/home/<name>`) to `~`.

## Screen-Sharing & Screenshot Safety

When running against real local sessions (without `--demo`), your project names, Git branch names, and non-secret file basenames are visible on your local screen:
- Click **`Privacy Mask`** in the top bar before recording or taking screenshots of real work — it replaces workspace names (`workspace-1`, `workspace-2`), feature branch names (`branch-1`), and action details (`[Hidden by Privacy Mask]`) instantly in the browser.
- When sharing product feedback or bug screenshots publicly, prefer launching `python server.py --demo` so 100% synthetic fixtures are used.

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for suspected security vulnerabilities (such as a DNS-rebinding bypass, XSS, path traversal, or high-impact secret-redaction bypass).

Instead, use **GitHub Private Vulnerability Reporting** (`Security -> Report a vulnerability` on this repository) with:
- Minimal reproduction steps or synthetic payload (never include real credentials).
- Operating system and Python version.
