"""Pytest port of the rules-engine portion of `harnessloop selftest`.

Covers RequestView turn-start anchoring + rules.check() positive and negative paths.
Extracted from harnessloop/__main__.py::_selftest so cases run granularly under pytest.

TODO(next): port the remaining two _selftest blocks into their own modules —
  * tests/test_init_claude_code.py  (H1: init-claude-code config generation)
  * tests/test_failure_snapshots.py (H5: check.scan writes failure snapshots)
"""
from __future__ import annotations

import json

from harnessloop.model import RequestView
from harnessloop import rules as _rules


def _body():
    return {
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


def _cfg():
    return {
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


def test_turn_start_anchors_to_inbound_not_tool_result():
    view = RequestView(json.dumps(_body()))
    # The tool_result echo of MEMORY-INDEX-MARK must not steal the turn-start anchor.
    assert view.turn_start_index("<inbound>") == 2


def test_all_rules_pass_on_healthy_request():
    view = RequestView(json.dumps(_body()))
    res = {c["rule"]: c["ok"] for c in _rules.check(view, _cfg())}
    assert res == {"R1": True, "R2": True, "R3": True, "R4": True}


def test_missing_injection_fails_r2():
    body = _body()
    body["messages"][2]["content"] = [
        {"type": "text", "text": "<inbound> do the thing </inbound>"}]
    res = {c["rule"]: c["ok"] for c in _rules.check(RequestView(json.dumps(body)), _cfg())}
    assert res["R2"] is False


def test_config_block_scope_ignores_tool_result_echo():
    # memory_index is scoped to config_block; the tool_result echo must not satisfy it
    # via the wrong scope. R1 stays True only because the real config block carries it.
    body = _body()
    # strip the mark out of the config block, leave only the tool_result echo
    body["messages"][0]["content"][0]["text"] = "<cfg>MY-CONFIG-HEADER v1\nrules...</cfg>"
    res = {c["rule"]: c["ok"] for c in _rules.check(RequestView(json.dumps(body)), _cfg())}
    assert res["R1"] is False
