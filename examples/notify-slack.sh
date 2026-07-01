#!/bin/bash
# Slack notifier. Env: SLACK_WEBHOOK_URL. Message arrives on stdin.
TEXT=$(python3 -c 'import json,sys; print(json.dumps({"text": sys.stdin.read()}))')
curl -s --max-time 15 -X POST -H 'Content-type: application/json' \
  --data "$TEXT" "$SLACK_WEBHOOK_URL" | grep -q ok
