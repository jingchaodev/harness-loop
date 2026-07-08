"""Config loading for harness-loop. Pure stdlib, JSON config, env overrides.

Search order for the config file:
  1. $HARNESS_LOOP_CONFIG
  2. ./harness-loop.json
  3. ~/.harness-loop/harness-loop.json
Missing config -> sensible defaults (tap works out of the box; check needs rules).
"""
from __future__ import annotations
import json
import os
from pathlib import Path

DEFAULTS = {
    # --- tap ---
    "upstream": "https://api.anthropic.com",   # any OpenAI-compatible base works too
    "bind": "127.0.0.1:8082",
    "capture_paths": ["/v1/messages", "/v1/chat/completions"],
    "data_dir": "~/.harness-loop",
    "max_bodies": 500,                          # rotation cap for captured request bodies

    # --- request classification (skip non-main-loop requests in checks) ---
    "request_class": {
        "utility_max_messages": 2,              # tiny probes (quota/title/etc.)
        "utility_max_tools": 2,
        "exempt_user_prefixes": []              # e.g. summarizer/suggestion-mode prompts
    },

    # --- turn anchoring ---
    # A substring identifying a REAL inbound user turn (e.g. a channel wrapper tag).
    # null -> the last user message containing a plain text block is the turn start.
    "turn_marker": None,

    # --- the expectation model (see README + examples) ---
    "mechanisms": [],                            # what bytes are YOURS: [{id, pattern, scope, gloss}]
    "rules": [],                                 # what must hold: [{id, mechanism, expect, when, gloss}]
    "known_issues": {},                          # {rule_id: human-readable reason} -> suppressed
    "config_block_needle": None,                 # substring marking the harness-emitted config block

    # --- outputs ---
    "notify_cmd": None,                          # shell cmd; message arrives on stdin
    "dispatch_cmd": None,                        # shell cmd on NEW violations; findings JSON on stdin
    "ledger": "improvements.jsonl",              # repair ledger (relative to data_dir)
    "findings_dir": "./findings",                 # compact failure snapshots from check
}


def load(path: str | None = None) -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    candidates = [path, os.environ.get("HARNESS_LOOP_CONFIG"),
                  "harness-loop.json",
                  str(Path.home() / ".harness-loop" / "harness-loop.json")]
    for c in candidates:
        if c and Path(c).is_file():
            user = json.loads(Path(c).read_text(encoding="utf-8"))
            for k, v in user.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
            cfg["_config_path"] = str(Path(c).resolve())
            break
    cfg["data_dir"] = str(Path(os.path.expanduser(cfg["data_dir"])))
    Path(cfg["data_dir"]).mkdir(parents=True, exist_ok=True)
    (Path(cfg["data_dir"]) / "bodies").mkdir(exist_ok=True)
    return cfg
