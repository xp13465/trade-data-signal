# 方向锚「开锚 vs 关锚」严格 7 日线上 A/B harness(B 方案核心)

> 2026-09-01 · 实施落档。目的:用 7 个真实交易日线上数据,验证「方向锚注入文本到底帮不帮 AI 预测方向」,数据说话定去留。配套 harness:`scripts/ab_direction_anchor.py` + `scripts/run_ab_direction_anchor.sh` + launchd `com.trade.ab-direction-anchor`(21:15)。

## 一、背景与要验证的问题

- 方向锚自身回测(n=642,见 [ai-predict-backtest-feasibility-20260831.md](ai-predict-backtest-feasibility-20260831.md) §5.1):lean 方向预测 ≈0.51,纯随机、无显著方向优势。
- 影子模式线上 0/3 单边偏置(见 [ai-predict-shadow-vs-default-hitrate-audit-20260824.md](ai-predict-shadow-vs-default-hitrate-audit-20260824.md)):只出 up/flat。
- 当前 `direction_anchor_enabled: true`(2026-08-28 用户拍板)依据 = 3 样本离线前测,**非严格 A/B**。
- 本 harness 目标:搭「开锚生产 vs 关锚参考」双通道对照,7 个真实交易日命中率对比,为「方向锚去留」提供可操作证据。

## 二、A/B 设计口径

### 双通道对照(唯一变量 = 方向锚注入文本)

| 通道 | 方向锚注入 | 数据来源 | 说明 |
|---|---|---|---|
| 开锚生产 | `direction_anchor_enabled: true` | 生产 `daily_brief_history.json` 同日 `meta.direction`(只读引用) | gen_daily_brief.py 每天 20:40 真实预测照旧,【严禁触碰】 |
| 关锚参考 | `direction_anchor_enabled: false` | harness 每日 21:15 额外调 1 次关锚参考 | 同日期同数据,单 prompt 路径(便宜),落盘 `data/ab_direction_anchor.json` |

### 判定口径

- **关锚参考 direction**:`parse_ai_output` 的 `meta.direction`(区间推导:lo>0→up / hi<0→down / 跨0→flat,与生产 `_derive_direction` 同口径)。
- **开锚生产 direction**:`daily_brief_history.json` 同日 `meta.direction`(与生产同源,§22 一致性)。
- **对账 actual_direction**:`_actual_direction`(与 `gen_daily_brief.HIT_THRESHOLD=0.5` 同口径):下一真实交易日 sh 涨跌幅 >0.5%→up, < -0.5%→down, 否则 flat。
- **命中判定**:两通道均用「区间推导 direction」对次日判命中(`pred == actual_direction`),严格对照,不放松。

### 只读零侵入红线

本 harness 只写 `data/ab_direction_anchor.json`(本地 A/B 记录)+ `docs/ai-predict/out/ab_direction_anchor_7d.json`(对账聚算报告产物)。**严禁触碰**:生产 `daily_brief.json` / `daily_brief_history.json` / 主链 / 通知 / R2 / static-site/data。绝不调 `gen_daily_brief.main()`,只 import 复用 `build_prompt`/`call_deepseek`/`parse_ai_output`/`HIT_THRESHOLD`/`_actual_direction`。

## 三、7 日自动停机制

- 每日生成模式:同日幂等跳过;已满 7 个真实交易日记录 → 不再新调 API,提示跑 `--reconcile --force`。
- 对账聚算 `--reconcile`:幂等回填 actual(已回填跳过),聚算两通道方向命中率。
- 7 日满(`--reconcile --force`):出最终 A/B 结论表,不再新调 API。

## 四、落盘产物

- `data/ab_direction_anchor.json` — 每日 A/B 记录(本地,不进 git)
- `docs/ai-predict/out/ab_direction_anchor_7d.json` — 对账聚算 A/B 结论(§23.5 报告产物,进 git)

## 五、复现

- **脚本路径**:`/Users/linhuichen/code/trade/scripts/ab_direction_anchor.py`(harness 本体)+ `scripts/run_ab_direction_anchor.sh`(wrapper,含交易日判断)
- **输入依赖**:`sentiment.db`(index_daily sh pct,只读 ro)/ `static-site/data` 当日 JSON 快照(`load_data`)/ `daily_brief_history.json`(生产同日 direction,只读)/ `DEEPSEEK_API_KEY`(`.env`),provider 走 `config/daily_brief.yaml`
- **重跑命令**:
  - 每日定时:launchd `com.trade.ab-direction-anchor`(21:15),或 `bash scripts/run_ab_direction_anchor.sh`
  - 手动单日:`python3 scripts/ab_direction_anchor.py --date 20260901`
  - 对账聚算:`python3 scripts/ab_direction_anchor.py --reconcile`
  - 7 日满出最终结论:`python3 scripts/ab_direction_anchor.py --reconcile --force`
  - 0 成本 dry 校验:`python3 scripts/ab_direction_anchor.py --date 20260901 --no-call --dump /tmp/ab_da_test.prompts.json`
- **数据截止**:2026-09-01 开工,7 日样本自 2026-09-01 起逐交易日累积
- **关键口径一句话**:开锚生产 vs 关锚参考双通道方向预测,对下一交易日 sh 实际方向(±0.5% 阈值)判命中,7 日命中率对比定方向锚去留。
