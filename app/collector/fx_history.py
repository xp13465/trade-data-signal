"""Offline candidate import only. Does not fetch, activate, notify or use app.db.

python -m app.collector.fx_history snapshot.txt --source-url <DAY_URL> \
    --fetched-at 2026-11-11T10:00:00+08:00 --output /tmp/fx-stage.sqlite
"""
import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from ..fx_contract import parse_day_candidate, stage_day_history


def import_snapshot(snapshot, output, *, source_url, fetched_at):
    snapshot, output = Path(snapshot), Path(output)
    if output.is_symlink():
        raise ValueError("staging DB cannot be a symlink")
    parsed = parse_day_candidate(snapshot.read_text(), source_url=source_url, fetched_at=fetched_at)
    if not output.exists():
        # Exclusive create prevents accidentally creating/opening a live application DB.
        with output.open("xb"):
            pass
        conn = sqlite3.connect(output)
        conn.executescript("""
          CREATE TABLE fx_staging_info(kind TEXT);
          INSERT INTO fx_staging_info VALUES('HC18_candidate_only_v1');
          CREATE TABLE daily_metric(date TEXT,metric_id TEXT,value REAL,source TEXT,updated_at TEXT,PRIMARY KEY(date,metric_id));
        """)
    else:
        conn = sqlite3.connect(f"file:{output.absolute()}?mode=rw", uri=True)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables != {"fx_staging_info", "daily_metric"} or conn.execute("SELECT kind FROM fx_staging_info").fetchall() != [("HC18_candidate_only_v1",)]:
            raise ValueError("refusing non-staging database")
        return {**stage_day_history(conn, parsed["rows"]), "excluded_dates": parsed["excluded_dates"]}
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="USD/CNH 离线隔离导入，不启用指标")
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--fetched-at", required=True)
    args = parser.parse_args()
    print(json.dumps(import_snapshot(args.snapshot, args.output, source_url=args.source_url,
                                    fetched_at=datetime.fromisoformat(args.fetched_at)), ensure_ascii=False))


if __name__ == "__main__":
    main()
