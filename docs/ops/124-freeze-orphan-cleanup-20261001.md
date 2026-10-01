# #124 孤儿冻结清理机制(2026-10-01)

> 实施任务:#124 孤儿冻结清理机制缺失。2026-10-01 用户拍板「假期窗口把问题都修好」。
> 来源报告:`docs/kelly/analysis/sigkelly-gap-20260923-rootcause.md` §4。
> 同族 memory:`freeze-key-signal-type-drift` / `kelly-etf-freeze-lookahead`。

## 结论一句话

**孤儿冻结 26 条(冻结表 28258 键中),不是每天新增、是零散历史遗留但仍在产生;清理机制已实现为独立脚本(dry-run 默认 + 15 天冷却期 + 备份回退),3 类反例实测全 PASS,不会误删「暂时查不到、事后会回来」的键。**

---

## 1. 现象与根因(来源报告 §4)

- 09-23 `sz_div` 盘中 09:26-15:36 持续推 buy(signal_intraday_log 29 条),16:33 冻结 `→159905`;18:49 收盘重算信号「严格消失」(signal_daily 无任何 sz_div 事件,`check_signals.py:938` `detect_fade` red 档)→ **冻结表孤儿项残留,清理机制缺失**。
- 影响:孤儿键在 signal_daily 无事件,**回测从 signal_daily 读信号,永远查不到孤儿键** → 不影响任何回测结果,纯脏数据残留。

## 2. 第一步:存量实测(云上权威数据,2026-10-01 只读拉取)

数据源:
- 冻结表:`/home/ubuntu/code/trade-data/data/signal_kelly_etf_freeze.json`(28258 键)
- signal_daily:云上 sentiment.db 全量导出(71372 行,date|index_id|signal)

判据(锚冻结键本身构成,不用字段顺手存在):
- **正常**:`(date,index_id,signal)` 在 signal_daily 精确命中 → 28228
- **漂移(不可清)**:`(date,index_id)` 在 signal_daily 有事件但变体不同(`_freeze_fallback` 兜底依赖,memory `freeze-key-signal-type-drift`)→ **4**
  - `20260721|sw_801080|buy`(现值 buy_aux)/ `20260914|csi_399976|buy_aux`(现值 buy)/ `20260918|sz_div|buy`(现值 buy_aux)/ `20260929|csi_399976|buy_aux`(现值 buy)
- **孤儿候选(该日该指数在 signal_daily 完全无事件)**:**26**
  - 冷却期内(冻结 date 距今 <15 天,不可清)→ **5**:`20260917|sz_div|buy_aux`、`20260918|gz_399396|buy_aux`、`20260918|sw_801960|buy_aux`、`20260923|sz_div|buy`(报告实例)、`20260930|gz_399395|buy`
  - **可清(已过冷却期)→ 21**

孤儿分布:
- 按信号类型:`buy` 11 / `buy_aux` 10 / `buy_special` 5
- 日期范围:20260710 ~ 20260930,跨 3 个月共 26 条 → **不是每天新增**;但 9 月有 14 条、最新 09-30 仍在产生 → **不是纯一次性历史遗留,需机制治理**
- 盘中核对(signal_intraday_log 08-10 起):08-10 之后孤儿几乎全部盘中真实出现过(如 09-23 sz_div buy×29、09-30 gz_399395 buy×28、09-03/04/08 buy_special×31)→ 属「盘中真实信号 → 收盘重算修正消失」,收盘重算是最终权威,这类不会回来
- **「事后回填」真实实例已确认**:云上 signal_daily **已含 `20260922|sz_div|buy`**(09-22 盘中无、事后延迟回填,memory 先例)→ 这正是清理机制要防的「暂时查不到、事后回来」场景

## 3. 第二步:清理机制设计

红线:冻结表是防前视闸(memory `kelly-etf-freeze-lookahead`)——清理**绝不能**把「该冻结但暂时查不到」的键删掉。判错 = 破坏防前视 = 回测结论全废。

**三层防误删设计**:

1. **判据锚冻结键构成**:孤儿 = `(date,index_id)` 在 signal_daily **完全无任何事件**(严格)才候选;漂移变体(有任一事件)不算孤儿
2. **冷却期 15 天**:冻结键 date 距今 <15 天,即使 signal_daily 暂时查无也**不清**——等待收盘写入/事后延迟回填窗口。已覆盖已知回填先例(09-22 sz_div 滞后约数天)
3. **dry-run 默认 + --commit 才删 + 备份 + 审计日志**

实现:`scripts/signal_kelly_freeze_cleanup.py`(新增独立脚本,**不改** `signal_kelly_backtest.py` / `check_signals.py` / 冻结写入链路,§23.7 冻结契约:零影响面)

```
用法:
  python3 scripts/signal_kelly_freeze_cleanup.py --freeze <冻结表> --signals <signal_daily三字段导出>   # dry-run
  python3 scripts/signal_kelly_freeze_cleanup.py --freeze <冻结表> --signals <...> --commit              # 真删(备份+原子写+审计)
  python3 scripts/signal_kelly_freeze_cleanup.py --freeze <冻结表> --db <sentiment.db> --commit          # 或直连 DB
参数: --cooldown-days N(默认 15)
```

删除动作:`shutil.copy2` 备份到 `signal_kelly_etf_freeze.json.bak-<ts>` → `util_atomic.atomic_write_json` 原子写(与冻结写入链路同公共模块)→ 审计日志 `data/freeze_cleanup_audit.log`。

## 4. 反例实测(任务成败判据)

构造 3 类「暂时查不到、但事后会回来」场景,dry-run 断言**不被列入可清孤儿**:

| 反例 | 场景 | 结果 |
|---|---|---|
| 1-盘中 | 冻结键 date=今天,盘中跑(signal_daily 还未写入)→ 应落冷却期;收盘回填后精确命中 | **PASS** |
| 2-事后延迟回填 | `20260922|sz_div|buy` 真实先例:构造「回填前」signal_daily(剔除该行)+ 冻结键已存在 → 冷却期保护;回填后(signal_daily 含该行)精确命中 | **PASS** |
| 3-信号类型漂移 | 冻结 `buy`、signal_daily 现值 `buy_aux` → 落漂移区,不可清 | **PASS** |

**→ 反例全 PASS:清理机制不会误删「暂时查不到、事后会回来」的键。**

残余风险(如实标注):若某键「冻结后 >15 天才回填」且回填前被清,回测遇该信号会撞冻结分时点防御闸(`signal_kelly_backtest.py:436-440`)拒绝补冻 → 交易跳过。但:①孤儿键在 signal_daily 无事件,回测本来就不会遇到它(不影响当前任何回测结果)②15 天已覆盖已知回填滞后先例 ③备份可回退,风险可控。

## 5. dry-run 结果(当前存量会清几条)

```
冻结表总键 28258
  正常: 28228 / 漂移(不可清): 4 / 冷却期内(不可清): 5 / 可清孤儿: 21
```

**按当前存量 dry-run 会清 21 条**(均为 2026-09-16 及更早冻结、signal_daily 该日该指数已完全无事件,过冷却期);09-23/09-30 两条最新孤儿在冷却期内**保留**(等回填窗口)。

commit 实测(临时副本):删 21 → 28237 键,备份生成,幂等(再跑可清孤儿=0)。

## 6. 回退办法

- 每次 `--commit` 前自动备份 `signal_kelly_etf_freeze.json.bak-<ts>`(同目录)
- 回退:`cp signal_kelly_etf_freeze.json.bak-<ts> signal_kelly_etf_freeze.json`(或 mv)
- 审计日志 `data/freeze_cleanup_audit.log` 记录每次删除明细 + 备份路径

## 7. 同类错误面清单(§23.2 修 bug 三铁律 + §23.3 举一反三)

同「孤儿残留无清理」链路的同类物逐一排查:

| 链路物 | 是否有孤儿/清理 | 处置 |
|---|---|---|
| `signal_kelly_etf_freeze.json` | 孤儿残留 26 条,清理机制缺失 | **本任务根治** |
| `signal_notified.json` / `subscriptions_notified.json` | 已有 7 天自动清理(`check_signals.py:217/369`) | 无问题 |
| `signal_intraday_log` | 全量过程日志(append 不覆盖),非孤儿概念,量小(9770 行) | 无问题 |
| `signal_daily` | DELETE+INSERT 覆盖只存最终态,无孤儿 | 无问题 |
| 冻结键读取侧 `_freeze_fallback` | 漂移键(B 类)不删,孤儿键回测永不查询 | 闭环,无影响 |
| `signal_kelly_etf_freeze.json.bak-refreeze-20260918`(云上) | 历史备份(09-18 重冻结),非孤儿,且云上只读 | 保留(回退资产),报告说明 |
| `simulate_trade.py _pick_first_etf`(L186/L300) | 防前视同类待修(memory `kelly-etf-freeze-lookahead`「同类待修」),但不产生冻结表孤儿、不持久化冻结键 | 不在本任务范围,README 注记 |

## 8. 挂载建议(未执行,云上只读)

- 脚本已在 `scripts/signal_kelly_freeze_cleanup.py`,默认 dry-run。
- 云上挂载建议(主控/用户拍板后):独立 systemd timer,**盘后**(收盘 signal_daily 定稿后,如 21:00+)每日 `--signals` 从云上 sentiment.db 导出+ `--commit`;首次可手动 dry-run 确认后 `--commit`。
- 本任务**未写云上任何文件**(云上全只读),脚本上线流程走常规 feat 分支 + main-merge。

## 9. 复现段

```
# 1. 云上只读拉取权威数据
scp ubuntu@122.51.111.173:/home/ubuntu/code/trade-data/data/signal_kelly_etf_freeze.json /tmp/freeze_cloud.json
ssh ubuntu@122.51.111.173 "python3 -c \"import sqlite3;[open('/tmp/sd.txt','a').write('|'.join(r)+'\n') for r in sqlite3.connect('/home/ubuntu/code/trade-data/data/sentiment.db').execute('SELECT date,index_id,signal FROM signal_daily')]\""
scp ubuntu@122.51.111.173:/tmp/sd.txt /tmp/signal_daily_cloud.txt

# 2. dry-run(当前存量)
python3 scripts/signal_kelly_freeze_cleanup.py --freeze /tmp/freeze_cloud.json --signals /tmp/signal_daily_cloud.txt
# => 总键 28258, 正常 28228, 漂移 4, 冷却期 5, 可清孤儿 21

# 3. 反例实测
python3 /tmp/counterexample_test.py  # 3 类反例全 PASS(测试脚本在报告同 commit 的 docs/ops/ 不保留,可重建)
```

四件套:本报告 + 清理脚本 `scripts/signal_kelly_freeze_cleanup.py` + 本报告(含 dry-run/反例复现)+ commit。

## 关联

- 来源报告 `docs/kelly/analysis/sigkelly-gap-20260923-rootcause.md` §4「严格消失」机制 + §7 修复建议 2
- memory `freeze-key-signal-type-drift` / `kelly-etf-freeze-lookahead` / `data-source-switch-field-filter-blindspot`
- pending-features-index #124
