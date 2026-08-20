#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 预测「方向锚」离线回放 A/B 验证脚本（2026-08-20,AI 预测升级第一步,只读零侵入）

目的
----
在不动生产逻辑的前提下，用历史误判日(20260814/20260817/20260818)构造 data 域，
复用 gen_daily_brief 改造后的 build_prompt/build_editor_messages/call_deepseek/parse_ai_output，
喂给模型，只打印 direction/range，验证「方向锚」语义教学是否把旧 AI 猜反的方向修正。

关键设计（对齐 docs/ai-predict-offline-ab-frontvalidate-20260820.md 方案A 零侵入）
- 只 import gen_daily_brief 复用其函数，不调用其 main()，绝不触发 write_outputs/notify/R2
  /history 追加/backfill_hits —— 绝不覆盖生产 daily_brief.json（障碍② 绕过）。
- --direction-anchor off（默认）→ build_prompt 与线上开关关时逐字一致（线上基准对照）；
  --direction-anchor on → 注入方向锚语义（A/B 对照组）。
- 障碍①（inst_ih_trend/futures_acc_trend_tail 读当前 futures.json 不随 date 变）：
  data 域中这两个 JSON 侧字段是当日快照（非严格回放），已诚实标注局限；方向锚因子本身
  (futures_position/daily_metric/index_daily) 全按 date 从 DB 取，是严格回放的。
- known_bias(compute_known_bias 用当前全量 history) 严格回放应截断到回放日，本脚本
  简化为关闭 review 注入开关(cfg review_enabled=false)或由使用者自行比较语气，已在 §诚实标注列出。

输入依赖
- sentiment.db（futures_position/futures_accuracy/daily_metric/index_daily，只读 ro 连接）
- 信号/数据域构建默认走 gen_daily_brief.load_data（读 static-site/data 当日 JSON 快照，
  属局限①）。cwd 建议 trade-data/（uvicorn/cwd 口径），本脚本通过 REPO env 定位。
- deepseek API key（.env,DEEPSEEK_API_KEY），走 config/daily_brief.yaml provider。

用法/复现命令
  # 单 prompt A/B(便宜,推荐首轮;3 样本 × 开/关 = 6 次调用)
  python3 scripts/replay_direction_anchor.py --date 20260814 --direction-anchor off
  python3 scripts/replay_direction_anchor.py --date 20260814 --direction-anchor on
  # 多角色主编链路(贵,3 样本 × 6 角色 × 开/关 ≈ 36 次调用,默认不跑,须显式 --multi)
  # --no-call 只构建 prompt 落盘 /tmp,不调 API(0 成本,dry 校验 + 看方向锚语义是否进 sys_text)
  python3 scripts/replay_direction_anchor.py --date 20260818 --direction-anchor on --no-call --dump /tmp/da_20260818_on.prompts.json

诚实标注
- 3 样本统计意义有限=方向性前测非严格 A/B（严格 A/B 需真实交易日跑 7 天）。
- 8/18 是 T 因子失效样本（全席位大幅转多却次日 -2.4 暴跌），回放核心看点=模型是否用
  L3 纳指大跌(nq_chg=-1.302)压住 T1 转多看涨 → 应输出 down（见 offline-ab 报告 §③）。
- JSON 侧字段（inst_ih_trend 等）为当日快照，非严格历史回放；方向锚因子为严格按 date 回放。
- known_bias 当前实现读全量 history，严格回放需截断，本脚本以 review 开关降级处理。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent  # scripts/ 的父目录 = trade/
# 把 repo 根 + scripts/ 都进 sys.path，import gen_daily_brief（gen 内自己 sys.path.insert ../scripts）
sys.path.insert(0, str(REPO_ROOT))


def _pick_repo() -> Path:
    """定位数据源树（REPO env 优先，与 gen_daily_brief.pick_repo 同口径）。"""
    env_repo = os.environ.get("REPO")
    if env_repo and Path(env_repo).exists():
        return Path(env_repo)
    return REPO_ROOT


def main() -> int:
    ap = argparse.ArgumentParser(description="AI预测「方向锚」离线回放 A/B(只读零侵入)")
    ap.add_argument("--date", required=True, help="信号日 YYYYMMDD(如 20260814/20260817/20260818)")
    ap.add_argument("--direction-anchor", choices=["on", "off"], default="off",
                    help="on=注入方向锚语义,off=线上基准对照(逐字一致)")
    ap.add_argument("--no-call", action="store_true",
                    help="不调 API,只构建 prompt 并落盘 /tmp(0 成本,dry 校验)")
    ap.add_argument("--dump", help="构建的 messages 落盘到该 JSON 文件(用于 diff 对照/审阅)")
    ap.add_argument("--multi", action="store_true",
                    help="走多角色主编链路(build_editor_messages);默认走单 prompt build_prompt(便宜)")
    args = ap.parse_args()

    import gen_daily_brief  # noqa: 复用改造后的 build_prompt/build_editor_messages/call_deepseek/parse_ai_output

    # ── 引擎:不改生产 main，手动构造 cfg + data + 复用 prompt 构建 ──
    cfg = gen_daily_brief.load_config()
    cfg["direction_anchor_enabled"] = (args.direction_anchor == "on")
    # 严格回放视角:known_bias 当前实现读全量 history，会含回放日之后信息；
    # 回放统一关 review 注入，避免泄漏(见诚实标注)。
    cfg["review_enabled"] = False
    repo = _pick_repo()
    static_dir = repo / "static-site" / "data"
    db_path = gen_daily_brief.pick_db(repo)
    date = args.date

    def log(msg: str) -> None:
        print(f"[replay_direction_anchor] {msg}")

    log(f"repo={repo} date={date} db={db_path.name} direction_anchor={args.direction_anchor}")
    log("⚠️ 绝不写盘/不通知/不上传(只读回放)")

    # ① 按 date 构造 data 域(复用 load_data；JSON 侧字段为当日快照,方向锚因子按 date 严格取)
    data = gen_daily_brief.load_data(static_dir, db_path, date)

    # ② 构建 prompt(单 prompt 或多角色主编链路)
    if args.multi:
        # 多角色链路:先跑各角色(需 4+2 次 API；--no-call 时跳过,只 dump 主编 sys_text 占位)
        if args.no_call:
            log("--multi --no-call:跳过角色调用,仅 dump 主编 sys_text 语义(方向锚进入主编规则段)")
            messages = gen_daily_brief.build_editor_messages({}, None, date, cfg, data=data)
        else:
            log("多角色链路需逐角色调 API(3样本×6角色×开/关≈36次),昂贵;推荐 --no-call 或单prompt")
            return 2
    else:
        messages = gen_daily_brief.build_prompt(date, data, cfg, known_bias="")

    if args.dump:
        Path(args.dump).write_text(
            json.dumps(messages, ensure_ascii=False, indent=1), encoding="utf-8")
        sys_text = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
        if "方向锚" in sys_text:
            log(f"✅ 方向锚注入确认(dump={args.dump},sys_text 含『方向锚』)")
        else:
            log(f"⚪ 方向锚未注入(direction_anchor={args.direction_anchor},dump={args.dump})")

    if args.no_call:
        log("--no-call：0 成本 dry 校验完成，未调 API、未写任何生产文件。")
        return 0

    # ③ 调 deepseek(只打印 direction/range，不写盘)
    log("调用 call_deepseek...(官方高峰 9-12/14-18 不可用,请 18:00 后或方舟跑)")
    t0 = time.time()
    raw = gen_daily_brief.call_deepseek(messages, cfg, log)
    elapsed = round(time.time() - t0, 1)
    if not raw:
        log(f"❌ AI 调用失败({args.date})，见 DEEPSEEK_API_KEY/provider 配置")
        return 1
    parsed = gen_daily_brief.parse_ai_output(raw, data, date)
    if not parsed or parsed.get("range_status") == "range_missing_invalid":
        log(f"❌ 解析失败/区间降级({args.date})")
        return 1
    meta = parsed.get("meta") or parsed
    print("\n" + "=" * 60)
    print(f"回放日期: {args.date}  direction_anchor={args.direction_anchor}  耗时{elapsed}s")
    print(f"  direction: {meta.get('direction')}   range: {parsed.get('range')}")
    print(f"  confidence: {meta.get('confidence')}  {meta.get('confidence_reason') or ''}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
