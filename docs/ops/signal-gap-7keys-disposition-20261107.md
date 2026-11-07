# 7 条历史冻结逐键处置结论（2026-11-07）

- 依据：`docs/ops/signal-gap-name-contract-20261107.md`、`/tmp/codex-reports/signal-gap-name-contract-20261107/research-baseline.md`（B1-B4）、云权威库只读实测
- 云上代码 HEAD：`02b7c6a21`
- real freeze：`/home/ubuntu/code/trade-data/data/signal_kelly_etf_freeze.json`，sha256 `0ee460f9bd9a889ae586989d6a814f5212fd5cfae7c63d693087cf76220ef7cd`，28629 keys；本次**未修改**
- accepted：`config/signal_kelly_frozen_missing_accepted.json`（8 条），7 键均不在

## 逐键结论

| 键 | signal_daily | freeze | accepted | 生产 trades | 11-02 deploybak 候选 | 今日 best | 结论 |
|---|---|---|---|---|---|---|---|
| 20261102\|csi_000102\|buy | 存在 1 行 buy | MISSING | 不在 | 0 | 159287 创业板综ETF博时 | 159541 创业板综ETF万家 | 有同日 11-02 候选，非铁证 |
| 20261102\|gz_399365\|buy | 存在 1 行 buy | MISSING | 不在 | 0 | 159073 粮食ETF汇添富 | 159587 粮食ETF广发 | 有同日 11-02 候选，非铁证 |
| 20261104\|csi_000102\|buy | 存在 1 行 buy | MISSING | 不在 | 0 | 无 11-04 快照（best 11-02 为 159287） | 159541 | 不可回放 |
| 20261104\|csi_000330\|buy | 存在 1 行 buy | MISSING | 不在 | 0 | 无 11-04 快照（159901 跨 11-02/今日稳定） | 159901 | 不可回放（仅高置信） |
| 20261104\|csi_000673\|buy | 存在 1 行 buy | MISSING | 不在 | 0 | 无 11-04 快照（159949 稳定） | 159949 | 不可回放（仅高置信） |
| 20261104\|gz_399395\|buy | 存在 1 行 buy | MISSING | 不在 | 0 | 无 11-04 快照（159880 稳定） | 159880 | 不可回放（仅高置信） |
| 20261105\|dax\|buy_special | 存在 1 行 buy_special | MISSING | 不在 | 0 | 无 11-05 快照 | 159561 | 不可回放（且 dax 历史 freeze 全为 513030，新信号冻 current best，语义冲突） |

## 恢复依据与不确定性（诚实标注）

- **2 键候选（20261102\|csi_000102 / gz_399365）**：唯一历史来源是 `data/board_etf_map.json.deploybak`（sha256 `6a98b52b61ff74cb20d9fe1f5fb150d561fef26d108cc8ad5c5a52c251761c1a`，mtime 2026-11-02 21:26:18）。
  - **它不是冻结时刻的精确映射**：`deploy.sh` 的 `.deploybak` 是 build 前备份（cp → `build_board_etf_map.py` → `rm -f`）；11-02 的冻结批次在 16:30/18:30/18:57/21:33，21:26 的 pre-build 快照与 21:33 冻结所用 map 可能不同。
  - 因此结论是「同日高置信候选，非铁证」。若用户要求恢复，须显式拍板接受该不确定性；本记录**未写入 freeze**。
- **5 键**：无 11-04/11-05 的可信 map 快照；用今日映射补造会违反防前视语义（§5.1⑥ / memory `kelly-etf-freeze-lookahead`）。判定**不可回放**，不补造、不整表覆盖、不用今日映射替换。
- 现有防御闸 `_resolve_etf`（`scripts/signal_kelly_backtest.py`）：未冻结 + 无 fallback + `date < latest_signal_date` → 拒绝补冻并记 `_FROZEN_MISSING_EVENTS`。该行为正确，本次未放宽。

## 根因（缺口为何产生）

- `signal_daily` 由 `app/compute/signals.py` 全表 DELETE+INSERT 重算。
- `update_all.sh` 时序：`pipeline.sh` 算信号 → wait → `deploy.sh`（内含 `signal_kelly_backtest` 冻结）→ `check_signals.sh`。
- 部分指数在 17:50 update_all 时数据未就绪 → 信号未检测 → 不在 `signal_daily` → 当晚 backtest 无键可冻。
- backfill（`trade-backfill-evening` 21:00/02:00）补数据后，次日重算才出现信号，但 `date < latest_signal_date`，防御闸拒绝补冻 → 永久缺口。

## 防复发措施（均未实施，待拍板）

1. **backfill 后补算信号 + 补跑冻结回测**：`trade-backfill-evening` 21:00 补完指数数据后，重跑 `app.compute.runner.run()` + `signal_kelly_backtest`（当晚 latest 仍=当日，防御闸放行）。风险：增加 21:00 后一轮回测耗时（约 3-5 分钟），需与 `freeze-orphan-cleanup` 21:50 排时序。
2. **每日 board_etf_map 快照**：deploy 时把 `board_etf_map.json` 复制为带日期快照（如 `data/board_etf_map_YYYYMMDD.json`），为日后缺口恢复保留可信源。风险低（纯只读快照）；只治恢复性，不防缺口。
3. **谨慎放宽防御闸**：仅对「signal_daily 现存 + best ETF 跨近期快照稳定」的历史缺键，允许带审计标记补冻（非默认开启，env 控制 + 快照交叉验证）。风险：可能破坏防前视语义；工作量大；仅作兜底。

## 红线

- 禁止整表/整份旧文件覆盖当前 freeze。
- 禁止用今日 `board_etf_map` 补造 11-04/11-05 历史。
- 任何恢复动作（若未来拍板）必须单独记录依据、影响面与回滚方案。
