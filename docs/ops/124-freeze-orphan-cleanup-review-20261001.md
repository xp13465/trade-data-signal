# #124 孤儿冻结清理机制 独立审查报告(2026-10-01)

> 审查对象:commit `e7afc040e`(feat 分支 `worktree-agent-a48220c2c1f4f8dfa`,已 push origin,未 merge)
> 审查者:reviewer(独立,全只读,未改任何代码/分支)
> 审查类型:B/C 级广涉及面(数据产物 + 防前视红线)全量审查

## 结论:**PASS-with-caveat**

三层防误删(判据锚/漂移豁免/15 天冷却)在代码里**真实成立**,存量数字全部对上,3 类反例含红线场景(09-22 事后延迟回填)独立复现全 PASS,§23.7 零契约冲击,备份/回退路径实测可用。caveat 均为「挂载云上 timer 前须用户拍板」项,不阻塞本分支 merge,但**上线挂载前必须回到本文 caveat 段复核**。

---

## 证据点

### ① 脚本逻辑正确性(核心) — PASS

| 断言 | 验证方式 | 结果 |
|---|---|---|
| 判据锚=冻结键构成 `date\|index_id\|signal` | `signal_kelly_backtest.py:231-233` `_signal_key` = `f"{date}|{iid}|{sig}"`,与脚本 `split("|")` 逐字一致 | ✓ |
| 漂移豁免((date,index) 有任一变体不可清) | 4 条真实漂移键逐一核 signal_daily:sw_801080 buy→现buy_aux / csi_399976 buy_aux→现buy ×2 / sz_div buy→现buy_aux,变体全部存在 | ✓ |
| 漂移键正是 `_freeze_fallback` 依赖 | `signal_kelly_backtest.py:268-280` `_freeze_fallback` 按 (date,iid) 兜底取最高变体(2026-09-22 根治),豁免正确,删了会破坏防前视兜底 | ✓ |
| 冷却期边界 | 代码 `days < cooldown_days`→冷却、`>=`→孤儿。实测 09-16(距今15天)可清、09-17(14天)冷却,边界一致 | ✓ |
| 无参默认跑一次写都不做 | 本机无冻结表→"冻结表不存在" exit 1;有表无 `--db/--signals`→exit 1。双保险 | ✓ |
| **反例1 盘中**(date=今天) | 构造 `20261001|sh|buy` → 落冷却期 | ✓ |
| **反例2 事后延迟回填**(红线) | 剔除 `20260922|sz_div|buy` 行 + 冻结表加该键 → 落冷却期保护;带该行 → 精确命中 normal(28228→28229),冷却恢复 5 | ✓ |
| **反例3 漂移** | 真实数据 4 条全豁免 | ✓ |
| 备份先于删除 | 代码顺序 copy2 → del → atomic_write;实测备份生成(5.8MB)、回退 `cp .bak` 还原 28258 键 | ✓ |
| 原子写与冻结写入链路一致 | `signal_kelly_backtest.py:305` 与清理脚本同用 `atomic_write_json(path, data, separators=(",", ":"))`,同模块同参数 | ✓ |
| 幂等 | commit 后 28258→28237,再跑 dry-run 可清=0 | ✓ |

### ② §23.7 冻结契约零冲击 — PASS

- diff 仅 3 文件(新脚本 + 报告 + 台账),未动 `signal_kelly_backtest.py` / `check_signals.py` / 冻结写入链路。
- 新脚本仅 import `util_atomic`(公共原子写模块),无导入信号链路的副作用。
- 冻结读取侧 `_freeze_fallback` / `_load_etf_freeze` 均未改。

### ③ §25 备份回退 — PASS

见 ① 表「备份先于删除 / 回退」两行实测。审计日志记录每次 DEL + 备份路径(实测生成)。

### ④ §15 回归影响面 — PASS

- `grep -rn signal_kelly_freeze_cleanup` 全仓(排除 worktree):**零引用** → 不会被 deploy / update_all / 定时链意外调用。
- `deploy.sh` 只显式调用指定脚本(`gen_etf_index_map.py`/`build_board_etf_map.py` 等),非 `scripts/*.py` 通配遍历。
- 云上 `systemctl list-timers | grep freeze|cleanup` = 无 timer,`/etc/systemd/system` 无单元文件 → 报告 §8「挂载建议未执行」如实,未被偷偷挂载。
- 默认无参跑不删东西(见 ①)。

### ⑤ 数据校验 — PASS

- 本地重跑 dry-run(云上权威数据):**总 28258 = 28228 正常 + 4 漂移 + 5 冷却 + 21 可清**,与报告逐字对上。
- 云上:冻结表 28258 键 / signal_daily 71372 行 / `20260922|sz_div|buy` 真实存在(回填先例)。
- 抽样:3 个可清孤儿(date,index)在 signal_daily **0 事件**;5 个冷却键 **0 事件**(正确保留);格式非 3 段键 0 个(总数闭合)。
- 孤儿类型分布核对:可清 buy 9 + 冷却 buy 2 = 11 / 可清 buy_aux 7 + 冷却 buy_aux 3 = 10 / buy_special 5 → 报告「buy 11 / buy_aux 10 / buy_special 5」成立。
- 孤儿产生源语义一致:`check_signals.py:938` detect_fade「严格消失=盘中推 (X,buy*) 收盘 signal_daily 无 X 任何信号」与清理判据「(date,index) 完全无任何事件」同义;孤儿为「盘中真实信号 → 收盘 store() DELETE+INSERT 全量重建消失」,抽查 09-15 gz_399395 盘中 31 条、09-16 sw_801120 盘中 6 条证实「盘中真实出现过」。
- 「信号类型漂移不可清」判据可靠(依据 _freeze_fallback 兜底逻辑,见 ①)。

### ⑥ 同类错误面清单(报告 §7)独立核 — PASS

| 链路物 | 独立核实结果 |
|---|---|
| signal_notified / subscriptions_notified | `check_signals.py:216-217 save_signal_notified` 7 天自动清理,注释确认 | ✓ |
| signal_intraday_log | 云上实测 9770 行,append 过程日志,无孤儿概念 | ✓ |
| signal_daily | `app/compute/signals.py:1449 store()` DELETE+INSERT 全量重建只存最终态,无孤儿 | ✓ |
| _freeze_fallback | 漂移键豁免不删,孤儿键回测永不查询(回测只遍历 signal_daily) | ✓ |
| simulate_trade `_pick_first_etf` | 报告如实标注「防前视同类待修,不在本任务范围,README 注记」,未冒领 | ✓ |

### ⑦ 台账 #124 状态 — PASS(§23.12-1)

worktree 台账 L214 状态列已从「待办」更新为「实施完成 → review 中(2026-10-01,报告+脚本)」,与 commit message 及实际相符。主仓仍是「待办」(未 merge,属正常)。

---

## Caveat(挂载前须用户/主控拍板,不阻塞本分支 merge)

1. **残余风险(报告 §4 已如实标注,认可但需拍板)**:若某键「冻结后 >15 天才回填」且回填前被清 → 回测撞 `signal_kelly_backtest.py:436-440` 冻结分时点防御闸拒绝补冻,该信号交易跳过。缓解已成立(①不影响当前任何回测——孤儿键在 signal_daily 无事件,回测本来就遇不到②15 天覆盖已知 09-22 回填先例③备份可回退),但 signal_daily 无 created_at(`app/queries.py:1205` 注释确认),回填窗口无法精确探测。**挂载云上 timer 前建议**:a) 首轮手动 dry-run 确认 b) 视先例滞后最长间隔决定是否加大冷却期(如 30 天)c) 保留备份文件至少一个冷却周期。若直接以 15 天挂 cron,属可接受但非零风险,须用户知悉。
2. **脚本 docstring 措辞误导(低分项,<80 但值得修)**:docstring 写「云上部署为独立 systemd timer(不侵入 update_all 链)」读起来像已部署事实,报告 §8 明确「挂载建议(未执行,云上只读)」,云上实测也确认无 timer。建议 docstring 改为「建议部署」以免未来误读为已上线。
3. **时区一致性**:冷却期用 `datetime.now()`(本机时区);本地 mac 与云上均为 CST(+8,`timedatectl` 实测),当前一致。若未来在 UTC 机器上跑会差 1 天边界,可考虑传 `today=` 显式参数(备选项,非阻塞)。

## 低分项滤除说明

另 3 个低分项(<80)已滤:①docstring 措辞(已升级放入 caveat 2)②`classify` 格式异常键静默 skip 不计数(实测 0 个,总数闭合,无实际影响)③脚本不支持 `--today` 显式日期(测试友好性,非正确性)。

## 复现段

```
# 数据拉取(云上只读)
scp ubuntu@122.51.111.173:/home/ubuntu/code/trade-data/data/signal_kelly_etf_freeze.json /tmp/rev_freeze.json
ssh ubuntu@122.51.111.173 "python3 -c \"import sqlite3;[print('|'.join(r)) for r in sqlite3.connect('/home/ubuntu/code/trade-data/data/sentiment.db').execute('SELECT date,index_id,signal FROM signal_daily')]\"" > /tmp/rev_sd.txt
# dry-run 核对
python3 <worktree>/scripts/signal_kelly_freeze_cleanup.py --freeze /tmp/rev_freeze.json --signals /tmp/rev_sd.txt
# 反例2(红线)复现:剔除回填行 + 冻结表加键
grep -v '^20260922|sz_div|buy$' /tmp/rev_sd.txt > /tmp/rev_sd_nofill.txt
# commit 幂等/备份/回退:临时副本 --commit → 再跑可清=0, cp .bak 还原
```

## 关联

- 实施报告 `docs/ops/124-freeze-orphan-cleanup-20261001.md`(主仓未 merge 前在 worktree)
- 台账 `docs/pending-features-index.md` #124(worktree 版已更新状态)
