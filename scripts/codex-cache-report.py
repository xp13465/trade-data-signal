# -*- coding: utf-8 -*-
"""Codex 会话 token 缓存命中率诊断(适配 codex-cli 0.153.4 rollout schema)。

用法:
  python3 scripts/codex-cache-report.py                     # 分析最新 rollout
  python3 scripts/codex-cache-report.py /abs/rollout-*.jsonl # 指定线程

口径: 命中率 = cached_input_tokens / input_tokens(单次采样 last_token_usage)。
健康线: 除冷启动前 1~2 次外 hit 稳定 >=90%。
"""
import glob, os, json, sys


def find_rollouts():
    return glob.glob(os.path.expanduser("~/.codex/sessions/**/rollout-*.jsonl"), recursive=True)


def parse(path):
    """返回 [(ts, input_tokens, cached_input_tokens)]，只取 token_count 的 last_token_usage。"""
    recs = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if '"cached_input_tokens"' not in line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            p = o.get("payload", {})
            if p.get("type") != "token_count":
                continue
            u = (p.get("info", {}) or {}).get("last_token_usage", {})
            if not isinstance(u, dict) or "input_tokens" not in u:
                continue
            recs.append((o.get("timestamp", ""), u.get("input_tokens", 0), u.get("cached_input_tokens", 0)))
    return recs


def report(path):
    recs = parse(path)
    if not recs:
        print("no usage records"); return
    ti = sum(r[1] for r in recs)
    tc = sum(r[2] for r in recs)
    print(f"file: {os.path.basename(path)}")
    print(f"calls={len(recs)}  input={ti:,}  cached={tc:,}")
    print(f"OVERALL HIT = {tc/ti*100:.2f}%")
    for i, r in enumerate(recs):
        hit = r[2] / r[1] * 100 if r[1] else 0
        flag = "  <-- cold" if hit < 30 else ""
        print(f"  #{i:>3} {r[0][:16]} hit={hit:5.1f}%{flag}")
    cold = sum(1 for r in recs if (r[2] / r[1] * 100 if r[1] else 0) < 30)
    print(f"cold(<30%): {cold}/{len(recs)}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        report(sys.argv[1])
    else:
        files = find_rollouts()
        if not files:
            print("no rollout files"); sys.exit(1)
        report(max(files, key=os.path.getmtime))
