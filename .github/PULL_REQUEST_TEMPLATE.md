## Summary

- What does this PR add or fix?
- Related Issue (if any): `#`

## Maintainer & Contributor Checklist

- [ ] **Zero external dependencies**: Uses Python 3.10+ stdlib and vanilla HTML/CSS/JS only.
- [ ] **100% Read-Only**: Does not write to agent directories or create Git locks.
- [ ] **Privacy & Redaction**: All new preview/detail fields pass through `redact_sensitive_text()` / `redact_preview()`, and no personal paths or real session data are included.
- [ ] **Bilingual parity (`EN | VI`)**: Any new UI label key is added to both `en` and `vi` in `cobalt_desk/ui/i18n.js`.
- [ ] **Tests pass locally**: `python -m unittest discover -s tests -v` and `node --check cobalt_desk/ui/*.js` pass using isolated `tempfile` fixtures.
