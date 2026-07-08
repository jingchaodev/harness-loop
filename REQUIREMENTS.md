# Requirements — mined from the ecosystem (2026-07-08)

Sources: GitHub issues of anthropics/claude-code, langfuse/langfuse, BerriAI/litellm,
Helicone/helicone + HN. Mined by a cross-vendor worker (GPT-5.5/codex), citations
spot-verified (5/5 real and on-topic). Bar for building: observed ≥2× in the wild,
checkable from the captured request, fits the zero-dep passive-tap design.

**The dominant validated theme:** "config/memory/hooks believed active but never reached the
request — with no warning." That IS this tool's thesis; the ecosystem is full of exactly the
silent failures the expectation engine exists to catch.

## Ship next

| id | Requirement | Evidence |
|----|-------------|----------|
| H1 | **Loaded-context manifest rules**: first-class expectation templates for the common Claude Code silent failures — "project settings loaded", "hooks present", "CLAUDE.md section X present", "memory index present" — shipped as a copyable example config, since cwd-related silent drops are the #1 recurring bug class. | claude-code#74023 (subdir launch drops ALL project settings), #36793, #48053, #58815 |
| H2 | **Hook-liveness canary**: declared hooks vs observed hook side-effects per request window; one invalid config entry silently disables ALL hooks today. | claude-code#75081, #74942, #69970 |
| H3 | **Parent/child request diffing**: verify persona/memory/hook instructions propagate into SUB-AGENT calls (they often don't). | claude-code#64244 |
| H4 | **Request envelope integrity**: record full body + byte counts (with redaction controls) — proxies today truncate bodies and omit sizes, hiding prompt-shape failures; also pre/post-proxy diffing to catch silent metadata clobbering. | litellm#25461, #25361, #24945 |
| H5 | **Failure snapshots**: when a rule fails, capture request metadata + the matched rule + the exact missing/present mechanism in one artifact (the "UI shows nothing useful" complaint, inverted). | litellm#25361 |

## Positioning confirmations (no build needed)

- Span-level observability tools miss the real outbound compiled prompt (langfuse#11505 — outer
  spans hide internal loop calls; #11756 — reconstructed conversations drift from reality). The
  tap's "capture the actual HTTP request" design is the differentiator — say it louder in README.
- Passive, zero-SDK, base-url-swap adoption is what users ask for (Helicone#209, HN 41646314).
  Never add required instrumentation.

## Intake

Re-run the mining quarterly (cross-vendor worker, same spec). False-positive/negative issues
from users feed the expectation-rule library.
