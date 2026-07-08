"""The expectation engine: "given this request, these harness behaviors must be visible."

A MECHANISM is something your harness injects, with a deterministic footprint:
    {"id": "memory_index", "pattern": "## My memory index",
     "scope": "config_block" | "turn_start" | "tools" | "anywhere",
     "gloss": "memory index reached the model"}

A RULE says what must hold, and when:
    {"id": "R1", "mechanism": "memory_index", "expect": "present",
     "when": {"class": "main", "min_messages": 3, "bot_session": true},
     "gloss": "memory must be compiled into every main-loop request"}

expect: "present" | "absent"  (absent = shadow guarantees: "this must NOT ship yet")
when (all optional, AND-ed): class ("main"), min_messages (int), bot_session (bool —
    the turn-start message carries `turn_marker`), mechanism_present (id — gate one
    rule on another mechanism's presence).

Scope choice is the whole game — see README "Gotchas". Short patterns match your own
conversation ECHOES of your tooling (self-reference); scoping to the config block /
turn start region is what makes detection honest.
"""
from __future__ import annotations
from .model import RequestView


def _scope_cache(view: RequestView, cfg: dict):
    needle = cfg.get("config_block_needle")
    marker = cfg.get("turn_marker")
    scopes = {}

    def scope_text(name: str) -> str:
        if name not in scopes:
            if name == "config_block":
                scopes[name] = view.scope_config_block(needle)
            elif name == "turn_start":
                scopes[name] = view.scope_turn_start(marker)
            elif name == "tools":
                scopes[name] = view.scope_tools()
            else:
                scopes[name] = view.scope_anywhere()
        return scopes[name]

    return scope_text


def mechanism_presence(view: RequestView, mechanisms: list[dict], cfg: dict) -> dict:
    scope_text = _scope_cache(view, cfg)
    return {m["id"]: (m["pattern"] in scope_text(m.get("scope", "anywhere")))
            for m in mechanisms}


def check(view: RequestView, cfg: dict) -> list[dict]:
    """Evaluate all rules against one request. Returns [{rule, ok, gloss, detail, ...}]."""
    rc = cfg.get("request_class", {})
    req_class = view.request_class(rc)
    mechanisms = cfg.get("mechanisms", [])
    mech_by_id = {m.get("id"): m for m in mechanisms}
    scope_text = _scope_cache(view, cfg)
    presence = mechanism_presence(view, mechanisms, cfg)
    marker = cfg.get("turn_marker")
    bot_session = view.turn_start_index(marker) is not None if marker else None

    results = []
    for r in cfg.get("rules", []):
        when = r.get("when", {})
        if when.get("class") and req_class != when["class"]:
            continue
        if when.get("min_messages") and len(view.messages) < when["min_messages"]:
            continue
        if when.get("bot_session") is not None and marker:
            if bool(bot_session) != bool(when["bot_session"]):
                continue
        if when.get("mechanism_present") and not presence.get(when["mechanism_present"]):
            continue
        mech = r.get("mechanism")
        want = (r.get("expect", "present") == "present")
        expectation = "present" if want else "absent"
        if mech not in presence:
            results.append({"rule": r["id"], "ok": False,
                            "gloss": r.get("gloss", r["id"]),
                            "detail": f"rule references unknown mechanism '{mech}'",
                            "expectation": expectation,
                            "matched": False,
                            "mechanism": {"id": mech, "pattern": "", "scope": "anywhere"},
                            "region": ""})
            continue
        m = mech_by_id[mech]
        got = presence[mech]
        scope = m.get("scope", "anywhere")
        results.append({"rule": r["id"], "ok": got == want,
                        "gloss": r.get("gloss", r["id"]),
                        "detail": f"{mech} {'present' if got else 'absent'} "
                                  f"(expected {expectation})",
                        "expectation": expectation,
                        "matched": got,
                        "mechanism": {"id": mech, "pattern": m.get("pattern", ""),
                                      "scope": scope},
                        "region": scope_text(scope)})
    return results
