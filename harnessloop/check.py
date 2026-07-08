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
import hashlib
import json
import subprocess
import time
from pathlib import Path

from . import config as _config
from .model import RequestView
from . import rules as _rules


def _tap_metadata(data: Path) -> dict:
    log = data / "tap-log.jsonl"
    out = {}
    if not log.is_file():
        return out
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        body_file = r.get("body_file")
        if body_file:
            out[Path(body_file).name] = r
    return out


def _snapshot_path(findings_dir: Path, rule_id: str, body_name: str, raw: bytes) -> Path:
    safe_rule = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in rule_id)[:80]
    safe_body = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in body_name)[:80]
    digest = hashlib.sha256(raw + rule_id.encode("utf-8")).hexdigest()[:10]
    return findings_dir / f"{safe_rule}-{safe_body}-{digest}.json"


def _write_failure_snapshot(cfg: dict, body_path: Path, raw: bytes, view: RequestView,
                            check_result: dict, meta: dict | None = None):
    findings_dir = Path(cfg.get("findings_dir") or "./findings")
    findings_dir.mkdir(parents=True, exist_ok=True)
    mechanism = check_result.get("mechanism", {})
    matched = bool(check_result.get("matched"))
    expectation = check_result.get("expectation", "present")
    region = str(check_result.get("region", ""))
    request_ts = (meta or {}).get("ts") or time.strftime("%Y-%m-%dT%H:%M:%S%z",
                                                       time.localtime(body_path.stat().st_mtime))
    snapshot = {
        "rule_id": check_result.get("rule"),
        "expectation": expectation,
        "mechanism": {
            "id": mechanism.get("id"),
            "pattern": mechanism.get("pattern", ""),
            "scope": mechanism.get("scope", "anywhere"),
        },
        "matched": matched,
        "status": "matched" if matched else "missing",
        "request": {
            "timestamp": request_ts,
            "model": view.model,
            "body": body_path.name,
            "body_bytes": len(raw),
        },
        "region": {
            "first_200_chars": region[:200],
        },
    }
    p = _snapshot_path(findings_dir, str(check_result.get("rule", "rule")), body_path.name, raw)
    if p.exists():
        return str(p)  # same failure already snapshotted — don't churn the dir
    p.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(p)


def scan(cfg: dict, window_hours: float = 24.0) -> dict:
    data = Path(cfg["data_dir"])
    cutoff = time.time() - window_hours * 3600
    total, scan_errors = 0, 0
    new_viol, known_viol = [], {}
    known = cfg.get("known_issues", {})
    tap_meta = _tap_metadata(data)
    for p in sorted((data / "bodies").glob("*.json.gz")):
        if p.stat().st_mtime < cutoff:
            continue
        try:
            raw = gzip.open(p, "rb").read()
            view = RequestView(raw)
            checks = _rules.check(view, cfg)
        except Exception:
            scan_errors += 1
            continue
        total += 1
        for c in checks:
            if c["ok"]:
                continue
            if c["rule"] in known:
                # acknowledged issues: count only — no snapshot, or a cron'd check
                # would re-write the same failure artifact on every scan
                known_viol[c["rule"]] = known_viol.get(c["rule"], 0) + 1
                continue
            c = {**c, "snapshot": _write_failure_snapshot(cfg, p, raw, view, c,
                                                            tap_meta.get(p.name))}
            public = {k: v for k, v in c.items() if k != "region"}
            new_viol.append({**public, "body": p.name})
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
