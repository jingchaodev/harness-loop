"""Provider-agnostic view over a captured LLM request body.

Supports the two dominant wire formats without external deps:
  * Anthropic Messages API: {model, system, messages[], tools[]}
  * OpenAI-compatible chat: {model, messages[{role:system|user|assistant}], tools[]}

Everything downstream (rules, scopes) works on this normalized view, so the loop makes
no assumption about which vendor or agent framework produced the request.
"""
from __future__ import annotations
import json


class RequestView:
    def __init__(self, body: bytes | str | dict):
        if isinstance(body, (bytes, str)):
            self.raw = json.loads(body)
        else:
            self.raw = body
        self.messages = self.raw.get("messages", []) or []
        self.model = self.raw.get("model", "")
        self.tools = self.raw.get("tools", []) or []

    # ---- normalized accessors -----------------------------------------------------------
    @property
    def system_text(self) -> str:
        s = self.raw.get("system")
        if isinstance(s, str):
            return s
        if isinstance(s, list):  # anthropic block array
            return " ".join(b.get("text", "") for b in s if isinstance(b, dict))
        # openai-style: system role messages
        return " ".join(self._msg_text(m) for m in self.messages if m.get("role") == "system")

    @property
    def tool_names(self) -> list[str]:
        out = []
        for t in self.tools:
            if isinstance(t, dict):
                out.append(t.get("name") or (t.get("function") or {}).get("name") or "")
        return out

    @staticmethod
    def _msg_text(m: dict) -> str:
        c = m.get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return " ".join(b.get("text", "") for b in c
                            if isinstance(b, dict) and b.get("type") == "text")
        return ""

    def msg_json(self, msgs) -> str:
        return json.dumps(msgs, ensure_ascii=False)

    # ---- scopes (the hard-won anchoring primitives; see README "Gotchas") ---------------
    def scope_anywhere(self) -> str:
        return json.dumps(self.raw, ensure_ascii=False)

    def scope_tools(self) -> str:
        return json.dumps(self.tool_names, ensure_ascii=False)

    def scope_config_block(self, needle: str | None) -> str:
        """The CURRENTLY-EFFECTIVE harness config block.

        In long-lived resumed sessions messages[0] is a FOSSIL (config frozen at session
        start); fresh config is re-injected at compaction boundaries. So: the LAST message
        containing `needle` (a distinctive phrase from your harness-emitted config header).
        Use a FULL phrase, not a short token — short tokens match conversation echoes of
        your own tooling (self-reference)."""
        if needle:
            n = json.dumps(needle, ensure_ascii=False)[1:-1]  # JSON-escaped form
            for m in reversed(self.messages):
                s = self.msg_json([m])
                if n in s:
                    return s
        return self.msg_json(self.messages[:2])

    def turn_start_index(self, turn_marker: str | None):
        """The TURN-START user message. Mid-turn continuation requests end with tool_result
        user messages that never carry per-turn injections — anchoring to 'last user message'
        false-fails every multi-tool turn."""
        for i in range(len(self.messages) - 1, -1, -1):
            m = self.messages[i]
            if m.get("role") != "user":
                continue
            txt = self._msg_text(m)
            if turn_marker:
                if turn_marker in txt:
                    return i
            elif txt.strip():
                return i
        return None

    def scope_turn_start(self, turn_marker: str | None) -> str:
        i = self.turn_start_index(turn_marker)
        if i is None:
            return ""
        return self.msg_json(self.messages[i:i + 2])  # + follow-up block where hook output attaches

    def turn_text(self, turn_marker: str | None) -> str:
        i = self.turn_start_index(turn_marker)
        return self._msg_text(self.messages[i]) if i is not None else ""

    # ---- request classification ----------------------------------------------------------
    def request_class(self, rc: dict) -> str:
        """'utility' (probes/summarizers — exempt from main-loop rules) or 'main'."""
        if (len(self.messages) <= rc.get("utility_max_messages", 2)
                and len(self.tools) <= rc.get("utility_max_tools", 2)):
            return "utility"
        last_user = next((self._msg_text(m) for m in reversed(self.messages)
                          if m.get("role") == "user"), "")
        for pref in rc.get("exempt_user_prefixes", []):
            if last_user.startswith(pref):
                return "utility"
        return "main"
