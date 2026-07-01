"""Run the expectation rules over captured requests; notify + dispatch on NEW findings.

Contract (learned in production, see README "The report contract"):
  * A notification says WHAT specific problem was found (plain-language gloss) and what
    was already improved — never bare violation counts.
  * Known/acknowledged true-positives (cfg.known_issues) are suppressed after first report.
  * Green = silence.
  * A broken sensor must PAGE, not silently shrink the sample (scan errors are findings).
"""
from __future__ import annotations
import gzip
import json
import subprocess
import time
from pathlib import Path

from . import config as _config
from .model import RequestView
from . import rules as _rules


def scan(cfg: dict, window_hours: float = 24.0) -> dict:
    data = Path(cfg["data_dir"])
    cutoff = time.time() - window_hours * 3600
    total, scan_errors = 0, 0
    new_viol, known_viol = [], {}
    known = cfg.get("known_issues", {})
    for p in sorted((data / "bodies").glob("*.json.gz")):
        if p.stat().st_mtime < cutoff:
            continue
        try:
            view = RequestView(gzip.open(p, "rb").read())
            checks = _rules.check(view, cfg)
        except Exception:
            scan_errors += 1
            continue
        total += 1
        for c in checks:
            if c["ok"]:
                continue
            if c["rule"] in known:
                known_viol[c["rule"]] = known_viol.get(c["rule"], 0) + 1
            else:
                new_viol.append({**c, "body": p.name})
    if scan_errors:
        new_viol.append({"rule": "sensor.scan_error", "ok": False,
                         "gloss": "some captured requests failed to parse (sample shrinking)",
                         "detail": f"{scan_errors} bodies unparseable", "body": "-"})
    report = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "bodies": total,
              "scan_errors": scan_errors, "new": new_viol, "known": known_viol}
    with (data / "check-history.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, ensure_ascii=False) + "\n")
    return report


def render(report: dict, cfg: dict, include_improvements: bool = True) -> str:
    lines = []
    if report["new"]:
        lines.append(f"HARNESS CHECK: new findings "
                     f"({report['bodies']} requests, last 24h)")
        seen = set()
        for v in report["new"]:
            if v["rule"] in seen:
                continue
            seen.add(v["rule"])
            n = sum(1 for x in report["new"] if x["rule"] == v["rule"])
            lines.append("")
            lines.append(f"[FAIL] {v['gloss']}  (rule {v['rule']}, x{n})")
            lines.append(f"       {v['detail']}")
    if include_improvements:
        imps = recent_improvements(cfg)
        if imps:
            lines.append("")
            lines.append(f"Recent improvements ({len(imps)} in last 24h):")
            for r in imps[:6]:
                lines.append("")
                lines.append(f"[FIXED] {r.get('area','?')}")
                lines.append(f"        found:    {str(r.get('found',''))[:100]}")
                lines.append(f"        improved: {str(r.get('improved',''))[:100]}")
    return "\n".join(lines)


def recent_improvements(cfg: dict, hours: float = 24.0) -> list[dict]:
    p = Path(cfg["data_dir"]) / cfg.get("ledger", "improvements.jsonl")
    if not p.is_file():
        return []
    out = []
    day_ago = time.time() - hours * 3600
    for l in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(l)
            ts = time.mktime(time.strptime(r["ts"][:16], "%Y-%m-%dT%H:%M"))
            if ts >= day_ago - 12 * 3600:  # generous tz slack
                out.append(r)
        except Exception:
            continue
    return out


def _pipe(cmd: str, text: str) -> bool:
    try:
        r = subprocess.run(cmd, shell=True, input=text.encode("utf-8"),
                           timeout=30, capture_output=True)
        return r.returncode == 0
    except Exception:
        return False


def main(cfg: dict | None = None, mode: str = "detect"):
    """mode=detect: notify+dispatch only on NEW findings (hourly).
    mode=digest: also report recent improvements when green (daily)."""
    cfg = cfg or _config.load()
    report = scan(cfg)
    has_new = bool(report["new"])
    text = render(report, cfg, include_improvements=(mode == "digest"))
    if not text.strip():
        return 0
    if has_new or mode == "digest":
        print(text)
        if cfg.get("notify_cmd"):
            ok = _pipe(cfg["notify_cmd"], text)
            if has_new and not ok:
                # never act internally while the operator wasn't told
                print("[check] notify failed — skipping dispatch; will retry next run")
                return 1
        if has_new and cfg.get("dispatch_cmd"):
            _pipe(cfg["dispatch_cmd"], json.dumps(report, ensure_ascii=False))
    return 0
