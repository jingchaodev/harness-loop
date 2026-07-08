# Agent Workspace State

## Project goal
Make harness-loop safely resumable by multiple coding agents.

## Current phase
planning

## Do not redo
- (none yet)

<!-- agentws:generated:start -->
## Active task
pytest-port: Port harnessloop _selftest into a proper pytest suite

## Current status
Adopted agentws. tests/test_rules.py landed: 4 tests (RequestView anchoring + rules.check pos/neg). pytest-port subtask 'rules-engine' done.

## Last known good state
branch `main`, last test: passed

## Recent changes
Tracked edits (this task):
- No tracked edits recorded.
Untracked (new/scratch):
- none

## Next best action
Write tests/test_init_claude_code.py (H1 config generation from a fake ~/.claude tree) — next pytest-port subtask.

## Blockers / open questions
- none

## Verification
- Last test command: python3 -m pytest tests/ -q
- Last test result: passed
<!-- agentws:generated:end -->
