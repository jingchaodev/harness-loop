# harness-loop

**A self-improving loop for any LLM-agent harness. Zero dependencies, pure Python stdlib.**

Your agent's behavior is shaped by a growing pile of harness machinery — system prompts,
config files, memory, hooks, injected context, tool schemas. Here is the uncomfortable truth:

> **Every one of those mechanisms compiles into a single artifact: the HTTP request sent to
> the model endpoint.** If you never look at that artifact, "my memory system works" and
> "my hook fires" are guesses, not facts.

harness-loop makes the compiled prompt observable, checks it against *expectations you
declare*, and closes the loop: **detect → notify → dispatch a repair → record → re-verify.**

It works with **any agent** that talks to an LLM HTTP API (Anthropic Messages or
OpenAI-compatible chat), **any notification channel** (a shell command), and **any
scheduler** (two cron lines). No framework buy-in.

```
  your agent ──► tap (logging reverse-proxy) ──► api.anthropic.com / any base URL
                   │
                   ▼ captured request bodies
                 check (expectation rules over the compiled prompt)
                   │ new finding
                   ├──► notify_cmd    (Telegram / Slack / stdout / anything)
                   └──► dispatch_cmd  (e.g. inject a repair task into your live agent)
                              │ agent fixes + appends to improvements ledger
                              ▼
                 watch (ledger → notify within minutes)   next check = automatic re-verify
```

## Quickstart (3 steps, no installs)

```bash
git clone https://github.com/jingchaodev/harness-loop && cd harness-loop
python3 -m harnessloop selftest          # verify the engine (no network needed)

# 1. start the tap and point your agent at it
python3 -m harnessloop tap &             # 127.0.0.1:8082 -> https://api.anthropic.com
export ANTHROPIC_BASE_URL=http://127.0.0.1:8082    # or OPENAI_BASE_URL for OpenAI-compatible
# ...restart your agent. Its requests now flow through the tap, unchanged.

python3 -m harnessloop report            # see what your agent ACTUALLY sends
```

Then declare expectations — copy `examples/harness-loop.example.json` to
`./harness-loop.json`, and describe (a) the **mechanisms** your harness injects (a
distinctive substring each) and (b) the **rules** for when each must be present or absent:

```json
{"mechanisms": [
   {"id": "memory_index", "pattern": "## My memory index", "scope": "config_block",
    "gloss": "memory index reached the model"}],
 "rules": [
   {"id": "R1", "mechanism": "memory_index", "expect": "present",
    "when": {"class": "main"}, "gloss": "memory must be compiled into every main request"}]}
```

```bash
python3 -m harnessloop check             # run the rules over the last 24h of captures
```

Wire the cron lines from `examples/cron.example` and the loop runs itself.

## The loop, stage by stage

| Stage | Who enforces it | Component |
|---|---|---|
| **Sense** — capture every compiled prompt | network topology (base-URL env) | `tap` |
| **Detect** — expectation rules over captures | cron + deterministic code | `check` |
| **Notify** — *what* broke, in plain language | `notify_cmd` (your channel) | `check` |
| **Dispatch** — hand the repair to your agent | `dispatch_cmd` (your mechanism) | `check` |
| **Record** — durable ledger of every fix | the repair contract | `improvements.jsonl` |
| **Notify fix** — within minutes, automatically | cron watcher on the ledger | `watch` |
| **Re-verify** — unfixed issues reappear | next hourly `check` | `check` |

Design stance: **sensing and verification are structural** (topology/cron — cannot be
forgotten); **judgment** (diagnosing, designing the fix) belongs to your agent; **approval
of anything durable/outward stays human**. The agent's weakest layer — remembering — is
sandwiched: work arrives structurally (dispatch) and gets accepted structurally (re-check).

### The report contract

- A notification says **what specific problem was found** (the rule's plain-language
  `gloss`) and **what was already improved** — never bare violation counts.
- Acknowledged true-positives go in `known_issues` — reported once, then suppressed.
- **Green = silence.**
- A broken sensor **pages** (`sensor.scan_error`) instead of silently shrinking the sample.

### The repair contract (what your agent does on dispatch)

1. Locate: inspect the failing captures (`python3 -m harnessloop report`).
2. Classify: *rule-precision bug* (fix the rule) vs *real harness defect* (fix the harness).
3. Fix and verify.
4. Append one line to the improvements ledger:
   `{"ts": "...", "area": "...", "found": "...", "improved": "...", "evidence": "how verified + commit"}`
5. Report. The `watch` cron delivers it to your operator within minutes — and if you skip
   step 4, the missing notification is itself a visible gap.

## Scopes: where a pattern must match (this is the whole game)

Naive full-text matching **will** lie to you. Every scope below exists because the naive
version produced a false result in production on day one:

| Scope | Meaning | Why it exists |
|---|---|---|
| `config_block` | the LAST message carrying your config header | in long-lived resumed sessions, message[0] is a **fossil** — config frozen at session start; fresh config is re-injected at compaction boundaries |
| `turn_start` | the last user message carrying `turn_marker` (+ its follow-up block) | mid-turn continuation requests end with tool_result messages that never carry per-turn injections — anchoring to "last message" false-fails every multi-tool turn |
| `tools` | the request's tool names | tool presence ≠ tool mentioned in conversation |
| `anywhere` | whole request | only for patterns that can't be quoted back at you |

**Self-reference rule:** the moment your conversation *discusses* your own markers (you
will — you're building this thing), short patterns match the discussion, not the mechanism.
Use long distinctive phrases (`config_block_needle` should be a full header line, not a
token), and unique contract strings for unshipped features.

## Gotchas we hit in production (so you don't)

1. **Relay every HTTP method.** Our first tap lacked `HEAD`; the client's startup HEAD
   probe got `501`, it concluded the API was down, and its plugin system silently never
   attached. The agent went deaf and nothing errored. If you write your own tap: every
   method, and log the **response status** per request.
2. **Classify requests before judging them.** The capture stream is heterogeneous: tiny
   quota/title probes, context summarizers, subagents. Judging them by main-loop rules
   produced 25 false violations in our first run (`request_class` handles this).
3. **Fossil sessions are real findings.** Long-lived resumed sessions genuinely run on
   stale config until the next compaction. Do not silence it — classify it as a known
   issue and fix the governance (periodic restarts).
4. **Replay drift needs a tolerance band.** If a rule re-runs a scoring sensor against
   *today's* index to judge *yesterday's* request, boundary scores flip. Gate expectations
   at a stricter threshold than the live mechanism uses.
5. **Gate dispatch on confirmed notification.** Never let the system act internally while
   the operator was not told (our notify exits nonzero on failure → retry, no dispatch).
6. **Escape everything you forward to rich-text channels**, and advance send-markers only
   on confirmed delivery.

## Security posture

- The tap **binds loopback only** by default and forwards `Authorization` headers verbatim
  — never expose it off-box (it warns if you try).
- Captured bodies contain your conversations. They live in `data_dir`, are rotated
  (`max_bodies`), and should be treated like transcripts. Nothing leaves the machine.
- Auth headers are **never logged**.
- `dispatch-tmux.sh` verifies a live agent owns the target pane before `send-keys` —
  injecting into a bare shell would *execute* your directive.

## What this is not

- Not an eval framework (it checks the *compiled prompt*, not answer quality).
- Not observability-as-a-service (no server, no dashboard, no account — files + cron).
- Not a proxy for secrets management or content filtering.

## Layout

```
harnessloop/
  tap.py        the logging reverse-proxy (stdlib http.server + http.client, SSE-safe)
  model.py      provider-agnostic request view + the scoping primitives
  rules.py      mechanisms × expectation rules engine
  check.py      scan captures, apply known-issue suppression, notify + dispatch
  watch.py      improvements-ledger watcher (fix notifications within minutes)
  config.py     JSON config + env, sensible defaults
examples/       config, Telegram/Slack/stdout notifiers, tmux dispatch, cron lines
```

MIT. Born from running three always-on Claude-Code agents through this exact loop; the
gotchas above are our first day's incident log, verbatim.
