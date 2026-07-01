#!/bin/bash
# Repair dispatch example: inject a repair directive into a live agent session via tmux.
# Findings JSON arrives on stdin. SAFETY: verify a live agent process owns the pane first —
# send-keys into a bare shell would EXECUTE your directive as a shell command.
SESSION="${AGENT_TMUX_SESSION:-main}"
FINDINGS=$(cat)
SIG=$(echo "$FINDINGS" | python3 -c "import sys,json,hashlib; d=json.load(sys.stdin); print(hashlib.sha256('|'.join(sorted({v['rule'] for v in d['new']})).encode()).hexdigest()[:12])")
MARK="/tmp/harness-loop-dispatched-$(date +%Y%m%d)-${SIG}"
[ -f "$MARK" ] && exit 0                      # one dispatch per signature per day
PANE=$(tmux list-panes -t "$SESSION" -F '#{pane_pid}' 2>/dev/null | head -1)
AGENT=$(pgrep -P "${PANE:-0}" 2>/dev/null | head -1)
[ -n "$AGENT" ] || exit 0                     # agent dead -> notification only
tmux send-keys -t "$SESSION" "harness-loop found new violations (sig ${SIG}). Repair contract: 1) run 'python3 -m harnessloop report 10' + inspect captures; 2) classify: rule-precision bug vs real harness defect; 3) fix + verify; 4) append to the improvements ledger; 5) report what was found and what you changed." Enter
touch "$MARK"
