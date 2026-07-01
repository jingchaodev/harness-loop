"""Ledger watcher: push every NEW improvements.jsonl entry through notify_cmd (~cron */5).

Why this exists: "fix silently and forget to tell anyone" is the failure mode of autonomous
repair. Coupling notification to the LEDGER (not to the agent's memory) makes it structural:
no ledger entry -> no notification -> a visible gap. Marker advances ONLY on confirmed send.

Ledger entry shape (one JSON object per line):
    {"ts": "2026-07-01T21:55Z", "area": "tap",
     "found": "what specifically was wrong",
     "improved": "what was changed",
     "evidence": "how it was verified + commit hash"}
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

from . import config as _config


def main(cfg: dict | None = None):
    cfg = cfg or _config.load()
    data = Path(cfg["data_dir"])
    ledger = data / cfg.get("ledger", "improvements.jsonl")
    mark = data / ".ledger-notified-count"
    if not ledger.is_file():
        return 0
    total = len(ledger.read_text(encoding="utf-8").splitlines())
    try:
        seen = int(mark.read_text().strip())
    except Exception:
        seen = 0
    if total <= seen:
        return 0

    cards, bad = [], 0
    for l in ledger.read_text(encoding="utf-8").splitlines()[seen:]:
        try:
            r = json.loads(l)
        except Exception:
            bad += 1
            continue
        cards.append(f"REPAIR: {r.get('area','?')}\n"
                     f"  found:    {str(r.get('found',''))[:160]}\n"
                     f"  improved: {str(r.get('improved',''))[:160]}\n"
                     f"  evidence: {str(r.get('evidence',''))[:100]}")
    if bad:  # malformed lines must be VISIBLE, not silently marked as seen
        cards.append(f"WARNING: {bad} ledger line(s) unparseable — check {ledger}")
    text = "\n\n".join(cards[:5])
    if not text:
        mark.write_text(str(total))
        return 0
    print(text)
    cmd = cfg.get("notify_cmd")
    if cmd:
        try:
            r = subprocess.run(cmd, shell=True, input=text.encode("utf-8"),
                               timeout=30, capture_output=True)
            if r.returncode != 0:
                return 1  # marker NOT advanced -> retry next run
        except Exception:
            return 1
    mark.write_text(str(total))
    return 0
