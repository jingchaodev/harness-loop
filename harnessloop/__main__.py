"""harness-loop CLI.

  python3 -m harnessloop tap                 # run the logging proxy (foreground)
  python3 -m harnessloop check [--digest]    # run expectation rules over last 24h captures
  python3 -m harnessloop watch               # push new improvements-ledger entries
  python3 -m harnessloop report [N]          # human view of the last N captured requests
  python3 -m harnessloop selftest            # verify the engine end-to-end, no network
"""
from __future__ import annotations
import gzip
import json
import sys
from pathlib import Path

from . import config as _config


def _report(cfg, n=5):
    data = Path(cfg["data_dir"])
    log = data / "tap-log.jsonl"
    if not log.is_file():
        print("no captures yet — is the tap running and is your agent pointed at it?")
        return 0
    rows = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"{len(rows)} requests captured; last {min(n, len(rows))}:")
    for r in rows[-n:]:
        print(f"  {r['ts']}  {r['method']:6} {r['path'][:44]:44} -> {r.get('status', r.get('relay_error','?'))}"
              f"  msgs={r.get('n_messages','-')} tools={r.get('n_tools','-')}")
    return 0


def _selftest():
    from .model import RequestView
    from . import rules as _rules
    body = {
        "model": "test-model",
        "system": "You are helpful.",
        "tools": [{"name": "send_message"}, {"name": "search"}],
        "messages": [
            {"role": "user", "content": [{"type": "text",
             "text": "<cfg>MY-CONFIG-HEADER v1\nrules...\nMEMORY-INDEX-MARK</cfg>"}]},
            {"role": "assistant", "content": "old turn"},
            {"role": "user", "content": [
                {"type": "text", "text": "<inbound> do the thing </inbound>"},
                {"type": "text", "text": "[injected-hint] maybe use /search"}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1",
                                               "name": "search", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                          "content": "found MEMORY-INDEX-MARK echo"}]},
        ],
    }
    cfg = {
        "config_block_needle": "MY-CONFIG-HEADER v1",
        "turn_marker": "<inbound>",
        "request_class": {"utility_max_messages": 2, "utility_max_tools": 2,
                          "exempt_user_prefixes": []},
        "mechanisms": [
            {"id": "memory_index", "pattern": "MEMORY-INDEX-MARK", "scope": "config_block"},
            {"id": "hint_injection", "pattern": "[injected-hint]", "scope": "turn_start"},
            {"id": "delivery_tool", "pattern": "send_message", "scope": "tools"},
            {"id": "secret_leak", "pattern": "[not-yet-shipped]", "scope": "turn_start"},
        ],
        "rules": [
            {"id": "R1", "mechanism": "memory_index", "expect": "present",
             "when": {"class": "main"}, "gloss": "memory reaches the model"},
            {"id": "R2", "mechanism": "hint_injection", "expect": "present",
             "when": {"bot_session": True}, "gloss": "hook injection attached to the turn"},
            {"id": "R3", "mechanism": "delivery_tool", "expect": "present",
             "when": {"min_messages": 3}, "gloss": "delivery tool present"},
            {"id": "R4", "mechanism": "secret_leak", "expect": "absent",
             "gloss": "unshipped feature stays absent"},
        ],
    }
    view = RequestView(json.dumps(body))
    # scope checks: tool_result ECHO of the memory mark must NOT satisfy config_block scope…
    res = {c["rule"]: c["ok"] for c in _rules.check(view, cfg)}
    expect = {"R1": True, "R2": True, "R3": True, "R4": True}
    # …and the turn-start anchor must find the <inbound> message, not the tool_result.
    assert view.turn_start_index("<inbound>") == 2, "turn-start anchoring broken"
    assert res == expect, f"selftest failed: {res} != {expect}"
    # negative: remove the injection -> R2 must fail
    body["messages"][2]["content"] = [{"type": "text", "text": "<inbound> do the thing </inbound>"}]
    res2 = {c["rule"]: c["ok"] for c in _rules.check(RequestView(json.dumps(body)), cfg)}
    assert res2["R2"] is False, "R2 should fail when injection is missing"
    print("selftest OK — engine, scoping, and turn-start anchoring all behave.")
    return 0


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = args[0]
    if cmd == "selftest":
        return _selftest()
    cfg = _config.load()
    if cmd == "tap":
        from . import tap
        return tap.main(cfg)
    if cmd == "check":
        from . import check
        return check.main(cfg, mode="digest" if "--digest" in args else "detect")
    if cmd == "watch":
        from . import watch
        return watch.main(cfg)
    if cmd == "report":
        n = int(args[1]) if len(args) > 1 and args[1].isdigit() else 5
        return _report(cfg, n)
    print(f"unknown command: {cmd}\n{__doc__}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
