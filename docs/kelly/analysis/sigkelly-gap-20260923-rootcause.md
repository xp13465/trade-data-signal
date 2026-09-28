# 信号凯利全信号表「停更 09-22」根因调研报告

**日期**: 2026-09-28
**触发**: 告警降噪调研中发现 `check_data_gap` 连续 4 天发 SEVERE（kelly_stale）
**结论一句话**: **不是流水线故障** —— 09-23 起宇宙内没有新的可入账信号（市场 + 宇宙规则的自然结果），叠加 1 笔被防前视冻结闸永久拒的历史信号 + 1 条孤儿冻结脏数据。

---

## 0. 触发锚点与主控验证

主控逐字验证（云上 `/home/ubuntu/code/trade-data/static-site/data/signal_kelly_trades.json`）：

- `generated_at = 2026-09-28 23:41`（每日重跑，产物每天被重写）
- 结构：**列式存储**，顶层 `fields` 为列名数组，`quadrants[<档>][<评级>]` = 行数组（每行是数组）
- 全 16 档 `max(signal_date)` 无一超过 `20260922`

| 档 | max signal_date | 档 | max signal_date |
|---|---|---|---|
| rating_high | 20260817 | sig_main | 20260918 |
| rating_mid | 20260904 | sig_aux | 20260922 |
| rating_low | 20260922 | sig_special | 20260908 |
| etf_strong | 20260918 | sig_backup | 20260812 |
| etf_related | 20260918 | mkt_a | 20260921 |
| etf_approx | 20260922 | mkt_hk | 20260916 |
| etf_has_track | 20260917 | mkt_global | 20260917 |
| mkt_industry | 20260922 | mkt_concept | 20260918 |

> ⚠️ 由此表得出的初判「产品级停更 6 天」**被本调研证伪**，修正记录见 §9。

---

## 1. 铁证：流水线是活的

**09-28 双档对照（决定性证据）**：

| 档 | 入账规则 | 09-28 数据 |
|---|---|---|
| 主档 NDO | `KELLY_BUY_NEXTDAY=1`（次日开盘价入账） | 无 09-28 行 —— **by design**，09-29 才入账 |
| SDC 档 | `KELLY_BUY_NEXTDAY=0`（当日收盘价） | **已含 20260928 csi_H30199 的 44 行** ✓ |

冻结表实证：`20260928|csi_H30199|buy_aux→159059`（frozen_at 22:24）已冻结。

→ 链路（信号产出 → 冻结 → 入账 → 产物）**逐环节正常**。

---

## 2. 逐日链路（09-22 ~ 09-28）

| 日 | 宇宙内新 buy 信号 | 结果 |
|---|---|---|
| 09-22 | `sw_801110 buy_aux`（家用电器，producer 20:36） | ✅ 入账（冻结 `20260922\|sw_801110\|buy_aux→561120`，44 行）—— **最后入账日** |
| 09-23 | `sz_div buy`（盘中 09:26-15:36 持续，intraday_log 29 条；16:33 冻结 `→159905`） | ❌ 18:49 收盘重算信号「严格消失」→ 0 交易 + **孤儿冻结残留** |
| 09-24 | `cgb_10y_etf buy_aux + buy_special` | ❌ 全命中宇宙排除类别 |
| 09-25/26/27 | — | 非交易日（节假日），仅 deploy 补推 |
| 09-28 | `csi_H30199 buy_aux` | ⏳ 冻结 `→159059`，**09-29 次日入账**（SDC 档已入） |

---

## 3. 各档停滞深浅不一 —— 4 种入样机制的混合物

**不是同一条链路逐段断掉，而是 4 种机制各自生效**。每档停滞日 = 该档**最后一次真实入账信号日**，全部可追溯到具体信号，**无一条是「链路断了没跑」**：

1. **宇宙剪枝（主导）** —— `scripts/signal_kelly_backtest.py:418` `_iid_in_excluded_category()`
   09-22 后新 buy 信号几乎全属排除类别（`universe_rules.yaml:30-111` 的 excluded_categories：`cgb_*` 债类 / `s.*` 情绪 / `g.*` 全球商品 / `hk_*` 港股行业 / 33 个空数组名单），**冻结值也不穿透**。
   - `sig_special` 停 09-08（sw_801780）、`mkt_hk` 停 09-16（hstech）、`mkt_global` 停 09-17（us_spx）—— 该档位 9 月中下旬信号全是 cgb_idx / hk_cshklc 的 buy_special，被剪。

2. **评级门槛** —— `rating_high = 0.75`
   08-12 后宇宙内仅 `csi_930997 @ 08-17`（score 0.761）达标（其余高分如 `g.a_qvix_1000` 0.81 全在排除类别）→ 停 08-17。`rating_mid` 停 09-04（sw_801010，0.584）。

3. **信号频率** —— `buy_backup` 本身稀有
   宇宙内最后一次 08-12（thsc_301079 等；08-17 的 sw_801230 在空数组排除名单内）→ `sig_backup` 停 08-12。

4. **冻结门 + 收盘修正**
   `sig_main` 停 09-18（csi_930050 buy），此后 buy 主信号只剩三者：`sz_div@09-22`（冻结门拒）、`sz_div@09-23`（严格消失）、`hk_*` 港股指（排除类别）。

---

## 4. 「严格消失」机制 —— 不是断因，是观察器

`scripts/check_signals.py:927-952` `detect_fade()`：盘中 `signal_notified` 推送信号 vs 收盘 `signal_daily` 对比，buy 系盘中推而收盘无任何信号 = red 档（L938「严格消失」）→ 写日志 + 邮件。

- 对 `sz_div@09-23` 是**日志层面的见证者**：收盘重算基于最终数据，sz_div RSI 不再上穿 30 → 信号移除，属**正常收盘修正**
- 但暴露**脏数据侧漏**：信号移除后**冻结表孤儿项 `20260923|sz_div|buy→159905` 残留**（16:33 冻结、18:49 信号消失），清理机制缺失 → 与 memory `freeze-key-signal-type-drift` 同族问题

---

## 5. 唯一真问题：`sz_div@09-22` 被防前视冻结闸永久拒

- 该信号 09-22 当天盘中**无**、09-23 09:40 intraday-rerun 也**无**，但**事后延迟回填**进 `signal_daily`
- 回填后 `latest_signal_date`（= `etf_daily MAX(date)`）已 ≥ 09-23
- 撞上 `scripts/signal_kelly_backtest.py:436-440` **冻结分时点漂移防御**（2026-09-18 加）：
  `date < latest_signal_date` 且无冻结值 → **拒绝补冻** + 记 `_FROZEN_MISSING_EVENTS`
- → **永久无法入账**
- `scripts/check_data_gap_alerts.py:822` 每天报「1 个入样买入信号无对应交易」（`_missing_reason="已具备次日价仍无 trade…冻结缺失"`）

---

## 6. 影响面

| 项 | 性质 |
|---|---|
| 首页模拟回测弹窗 / lab 凯利回测交易记录「停更」 | **观感问题**，实际是无新信号，非故障 |
| `check_data_gap` 每天 3 条 SEVERE（kelly_stale / kelly_coverage / depth≥2） | **判定缺陷**：把「今日无宇宙内信号」当故障（09-23~09-28 每天报） |
| 孤儿冻结项 `20260923\|sz_div\|buy→159905` | 脏数据（不碍功能） |
| `sz_div@09-22` 永久缺 1 笔 | 真缺口（1 笔历史） |

---

## 7. 修复建议（拍板项已标注）

1. **`sz_div@09-22` 处理 —— 需用户拍板（§23.7 冻结契约）**
   - ① **接受缺口 + 降噪**：`check_data_gap` 对「冻结缺失但次日价已齐」这类历史回填信号豁免 / 降 WARN —— **推荐**
   - ② 人工补冻结键 `20260922|sz_div|buy→159905`：会破坏 09-18 防前视冻结闸的设计前提
2. **孤儿冻结清理**：补「冻结键对应 `signal_daily` 已无此信号事件」的清理 / 告警机制；建议先排查冻结表同类残留存量（对齐 `freeze-key-signal-type-drift` 治理）
3. **`csi_H30199@09-28`**：无需修复，09-29 主档自然入账（SDC 档已含）
4. **排除类别信号刷屏**（10 年国债 ETF 天天 buy_aux）：设计内（UI 已标「未入回测宇宙」）。可选：展示位加「近 N 日宇宙外信号」标注

---

## 8. 复现段

```bash
# ① 产物 max signal_date（列式取值）
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'python3 -c "
import json
p=\"/home/ubuntu/code/trade-data/static-site/data/signal_kelly_trades.json\"
d=json.load(open(p)); F=d[\"fields\"]; i=F.index(\"signal_date\")
for name,v in d[\"quadrants\"].items():
    ds={str(r[i]) for rows in v.values() if isinstance(rows,list) for r in rows if isinstance(r,list) and len(r)>i}
    if ds: print(f\"  {name:25s} max={max(ds)}\")
"'

# ② SDC 档对照（当日收盘价规则，验证链路活着）
#    signal_kelly_trades_sdc.json generated_at 23:41，09-28 行 44 条

# ③ 冻结表三键核对
#    20260922|sw_801110|buy_aux→561120（成功入账）
#    20260923|sz_div|buy→159905（孤儿，信号已消失）
#    20260928|csi_H30199|buy_aux→159059（待 09-29 入账）

# ④ 代码锚点
sed -n '415,445p' scripts/signal_kelly_backtest.py   # L418 宇宙剪枝 / L436-440 冻结分时点漂移防御
sed -n '927,952p' scripts/check_signals.py           # L938 严格消失
sed -n '815,830p' scripts/check_data_gap_alerts.py   # L822 冻结缺失告警
```

### 证据源清单

云上 `sentiment.db` signal_daily 全量 buy 系信号枚举 + score 分布（08-12~09-28 逐日追溯）· `signal_intraday_log` 盘中时序（09-23 sz_div 29 条 buy；09-22 无）· 冻结表 `signal_kelly_etf_freeze.json`（28218 键，三键逐日核对）· update_all 日志时间线（18:49 收盘重跑 / 16:32 deploy / 09-23 09:40 intraday-rerun）· `universe_rules.yaml` 排除类别逐类核对 · SDC vs NDO 双档对照 · 线上 R2 curl 产物与云上 static-site 一致性（generated_at 23:41 同一版）

---

## 9. 方法论修正记录（§5.1④ 诚实标注）

**主控初判「P0 级产品停更 6 天」被本调研证伪。**

- **错因**：从「`max_signal_date` 停在 09-22」**直接跳到结论**，没往下查一步「这 6 天到底有没有值得记的信号」
- **正确路径**：观察到「产物天天重跑但数据不新」后，第二步应查 **SDC/NDO 双档对照**（不同入账规则），一步即可区分「引擎坏」vs「没信号」
- **教训对齐**：§5.1④ 数据说话不主观臆断 · §23.13 三源核对 · memory `requirement-research-bias-verify-first`
