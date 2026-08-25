#!/usr/bin/env python3
"""Mark a completed Codex review as ready for the Claude inbox."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
REPORTS_DIR = Path("/tmp/codex-reports")
SIGNALS_DIR = Path("/tmp/codex-reports/signals/claude-inbox")


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("request_id")
    parser.add_argument("--verdict", choices=("PASS", "FAIL", "BLOCKED"), required=True)
    args = parser.parse_args()

    if not all(char.isalnum() or char in "-_." for char in args.request_id):
        raise SystemExit("invalid request_id")

    report_path = REPORTS_DIR / f"{args.request_id}.json"
    with report_path.open(encoding="utf-8") as handle:
        report = json.load(handle)
    if report.get("request_id") != args.request_id:
        raise SystemExit("report request_id mismatch")
    if report.get("verdict") != args.verdict:
        raise SystemExit("verdict does not match report")

    atomic_write_json(
        SIGNALS_DIR / f"{args.request_id}.ready",
        {
            "request_id": args.request_id,
            "report_path": str(report_path),
            "signaled_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "verdict": args.verdict,
        },
    )
    print(f"claude signal ready: {SIGNALS_DIR / f'{args.request_id}.ready'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
