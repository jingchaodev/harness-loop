#!/bin/bash
# Telegram notifier. Env: TG_BOT_TOKEN, TG_CHAT_ID. Message arrives on stdin.
TEXT=$(cat)
RESP=$(curl -s --max-time 15 -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${TG_CHAT_ID}" --data-urlencode "text=${TEXT}")
echo "$RESP" | grep -q '"ok":true'   # nonzero exit => harness-loop retries next run
