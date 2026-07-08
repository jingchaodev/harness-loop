# Decisions

Record architecture/product decisions here that should not be re-litigated by a future agent.
Each entry should be short: what was decided, why, and when.

## 2026-07-08 — Initial workspace created
- Decision: adopted `agentws` handoff protocol for this repo.
- Why: make the repo safely resumable by multiple coding agents (Claude Code, Codex, Gemini).

## 2026-07-08 — pytest suite ports _selftest; does not replace it yet
- Decision: build `tests/` as a pytest port of `harnessloop/__main__.py::_selftest`, but KEEP `_selftest` intact until all three blocks are ported and green.
- Why: `_selftest` is the zero-dep smoke test users run via the CLI; deleting it mid-port would leave the CLI selftest broken for a fresh clone.
- Also: use /usr/bin/python3 (system 3.12) — a hermes venv shadows `python3` on this host and lacks pytest.
