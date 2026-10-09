# W1 · L1 度量层实施报告（2026-10-10）

> 上游依据：`docs/ops/alert-convergence-plan-20261010.md` §2（W1=L1 度量层规格）、
> `docs/ops/alert-system-fullchain-audit-20261009.md` §4/§5（20 条真样本 + 度量缺口）。
> 用户 2026-10-10 已拍板「要拍板的都做」（含 §23.7 冻结面例外授权）。
> 分支 `feat/alert-l1-meter-1010`；本文件所属 commit 见分支 HEAD。

---

## 0. 一句话

把「一天几条告警」从口号变成**可查数字**：notify.py 每次**实际外发**向单点台账
`data/alerts/alert_ledger.jsonl` 追加一行 → 幂等派生 `data/alerts/alert_daily.json`
→ `scripts/alert_meter.py --today/--week/--top` 查询（**跨两树聚合**，输出**一个**数字）。

---

## 1. 出口清单（先证明「是不是单点」）

**结论：notify.py 不是单点外发，而是「1 个消息级出口 + 3 个底层渠道出口」。**
低层网络出口穷举（grep `SMTP_SSL|urlopen`，全 notify.py 仅 3 处）：

| # | 真实网络出口 | 所在函数 | 行 | 覆盖的对外渠道 |
|---|---|---|---|---|
| N1 | `smtplib.SMTP_SSL` | `_send_email`（L975 定义，L1030 调用） | L1030 | 全部邮件 |
| N2 | `urllib.request.urlopen` | `send_telegram`（L480，L538 调用） | L538 | 全部 Telegram |
| N3 | `urllib.request.urlopen` | `_feishu_http_post_json`（L622，L628/L639 调用） | L628/639 | 全部飞书（send_feishu 的唯一底层） |

上层出口（会落到 N1/N2/N3）：

- 消息级（多渠道编排）：`send()` L1082、`send_to()` L1154；
- 经 `send()` 的派生出口：`send_tiered()` L2218、`notify_agent_done()` L1476、
  `flush_warning_batch()` L2007（30min 聚合批发）；
- 旁路出口（**不经** send/send_to，直接调底层）：
  `send_feishu_post_segmented()` L442（→send_feishu）、`_alert_feishu_config_missing()` L806（→_send_email）；
- 跨脚本外部直调（grep `scripts/*.py`）：`send_feishu` ← brief_push / codex_notify_bridge /
  agent_inbox_watcher / feishu_chat_ws(ws_listener) / feishu_chat_hook；`_send_email` ← brief_push；
  `send`/`send_to` ← check_signals / gen_daily_brief / signal_kelly_snapshot / check_nt_signals /
  nextday_plan_generator 等。

**挂钩选择（最小集覆盖全部真实外发，两级设计）**：

1. **消息级**：`send()` / `send_to()` 各记 **1 条**（含 `tier/key/group/merged_count`）；
2. **底层直调**：把 `send_feishu` / `_send_email` / `send_telegram` 三个**模块级名字**替换为
   记账包装（`_ledger_*_dispatch`，`functools.wraps` 保签名/`__name__`，返回原返回值）——
   覆盖上述全部旁路 + 外部直调；
3. **重入守卫**：`threading.local()` 深度计数，`send/send_to` 分发期间深度 >0 ⇒ 包装层
   跳过记账 ⇒ **不双记**（消息级 1 条 = 一次消息，而不是「邮件 1 条 + 飞书 1 条」）。

**已知剩余旁路（诚实标注，非本次范围）**：`scripts/feishu_ws_listener.py` 自带一份
`_feishu_http_post_json`（L131）用于**自己的** API 调用（取 token L170 / `send_receipt` L217，
即「收到」回执类消息），不经 notify ⇒ **不进台账**。它是该脚本自身出口，非告警链路
（告警类消息在 L390/L728 走 `ntf.send_feishu` ⇒ 已覆盖）。若后续要把它纳入，应对齐到
同一台账文件（另开任务，避免本次扩大冻结面）。

**出口穷举官方对照（§18 L50 交叉验证）**：`scripts/tests/_zero_outbound.py` L11-14 的权威
原文「notify 家族的真正外发原语只有三处（notify.py 实查）：send_telegram→urlopen、
`_feishu_http_post_json`→urlopen、`_send_email`→SMTP_SSL」——与本报告 §1 表**逐项一致**（N1/N2/N3），
漏一即漏记 ⇒ 对照 PASS。
补充核实两处易漏点：
(i) 飞书**消息**出口只有 `send_feishu` 一条（`_send_feishu_api` L681 / `_send_feishu_webhook` L755
    的调用点全在 `send_feishu` 函数体内 L954/959/965/970；跨脚本无直调，仅测试 patch 它们）
    ⇒ 包装 `send_feishu` 即覆盖全部飞书消息（`_get_tenant_access_token` L644 只是取 token 的
    鉴权调用，非消息外发）；
(ii) `_feishu_http_post_json` 调用点 3 处 = L663（取 token）/ L716（api）/ L773（webhook），
    无一绕过 `send_feishu`。

---

## 1.1 主控中途纠偏 7 点逐条核对（2026-10-10，独立调研 agent 出口穷举结论）

| # | 纠偏点 | 核对结果 | 处置 |
|---|---|---|---|
| 1 | 「消息级+渠道级双层打点 = 每封记两次」 | **不成立**：有 `threading.local()` 重入深度守卫 —— `send/send_to` 分发期间 depth>0 ⇒ 渠道包装**跳过**记账。机检证据：`test_B1`（email+feishu 都成功 ⇒ 台账**恰好 1 行**）、`test_B3`（send_to+send ⇒ 2 行而非 4 行） | 维持两级设计（理由见 §1.2），无需改 |
| 2 | 最小覆盖集 = {send_feishu, send_telegram, _send_email}；CLI 13 分支汇总处覆盖不全 | **认同**：原设计只包了 send_feishu/_send_email，**已补 `send_telegram`**（`_ledger_telegram_dispatch`）；CLI 13 分支虽走 `send/send_to/send_tiered/flush_warning_batch`，但**全部**最终落到这 3 个原语 ⇒ 渠道包装使其无一漏网 | 已补 TG（`test_B2` 三渠道各 1 条） |
| 3 | 内部旁路 `_alert_feishu_config_missing` 是否走 `_send_email` | **走**（函数体末 `ok = _send_email(...)`）。depth==0 由渠道包装记 1 条；**发现嵌套残留漏记**：`send_feishu` 内 cfg 缺失触发它时 depth>0，渠道包装会跳过 ⇒ 已在该函数内**条件补记**（仅 `_ledger_depth() > 0` 时补，depth==0 不补 ⇒ 零双记） | 已修 + `test_H1/H2` 锁死（1 条 / 2 条） |
| 4 | hook 必须落在各渠道 dry-run 早退**之后** | **等价满足**：记账在**包装层**（调用原函数返回后）执行，且条件含 `and not dry_run`；另原函数 dry-run 早退时返回 False ⇒ 双重保证。三渠道逐一验证 | `test_B4` 扩到四入口（send / send_feishu / _send_email / send_telegram） |
| 5 | 用 `scripts/tests/_zero_outbound.py` L11-14 官方对照表逐项核对 | **逐项一致**（3 原语：urlopen×2 + SMTP_SSL）——详见 §1 末段交叉验证 | 已引用 + 补两处易漏点核实 |
| 6 | 不许碰 notify.py 现存 5 类 suppress 输出措辞（L2183 被 `retry_failed_metrics.py:130` 文本匹配） | **零触碰**：`git diff scripts/notify.py` 的删除行仅 15 行，全为「扩签名加参数」与「渠道调用加 try/finally 缩进」；**无一行是 print/suppress 文案**；台账新增打印一律走 **stderr**（`[notify][ledger] …`），与 stdout 文本匹配消费者正交；`notify_sent.py` 未在本次 diff 内 | 机检证据留档（§5.5） |
| 7 | 定清聚合口径：渠道级「每信道一行」 vs 台账「每封一行 + channels{}」，`alert_daily.json` 怎么还原封数 | **见 §1.2**：本设计**不存在**「一封拆多行」，故 `total` = 封数 = 台账行数（按 group 过滤即告警条数），无需「还原」 | 明文写入口径定义 |

## 1.2 聚合口径定义（回答纠偏点 1/7）

**台账粒度 = 一次「外发事件」一行**，分两类，二者**互斥不重叠**：

| 类型 | 触发 | 行数 | `channels{}` |
|---|---|---|---|
| 编排外发 | `send()` / `send_to()`（含其派生：`send_tiered` / `notify_agent_done` / `flush_warning_batch`） | **1 行 / 封** | 标明哪些信道**真的发出**（如 `{"email":true,"feishu":false}` = 只邮件成功） |
| 旁路直调 | 外部脚本**单独**调 `send_feishu` / `_send_email` / `send_telegram`（如 brief_push 的邮件与飞书是**两次独立外发**） | **1 行 / 信道调用** | 该渠道 true、其余 false |

- **为什么不做「纯渠道级」**（纠偏点 1 的推荐方案）：渠道级流水会把「一次 `send()`」拆成
  2~3 行（email+feishu+tg），要还原「封数」只能按 `(subject, ts 到秒)` 归并 ——
  **同秒同 subject 的两条真独立告警会被误并**，且渠道级拿不到 `tier/key/group`
  （飞书有 chat_key，邮件没有）⇒ 主口径「告警群条数」失真。两级 + 重入守卫同时满足
  「一封一行 + channels{}」的台账 schema 与「零双计」。
- **封数定义（机读口径）**：`total` = 当日台账行数；**告警条数** = `by_group["alert"]`
  （即用户「0~3 条/天」判据的主口径）；`severe` = `by_tier["critical"]`；
  `merged_in_digest` = Σ`merged_count`（L2 摘要层预留，被并入聚合消息的条目数）。
  `--today` 同时打印「全量外发 N 条」（含 report 群功能输出/agent_done）供对账。

## 2. 三条交付物

| # | 交付物 | 落点 | 说明 |
|---|---|---|---|
| 1 | 单点台账 | `scripts/notify.py` → 追加 `data/alerts/alert_ledger.jsonl` | 每行 `{ts,tree,tier,key,subject,channels{email,feishu[,telegram]},source,group[,merged_count]}` |
| 2 | 日计数 | `data/alerts/alert_daily.json` | **幂等重算**（非累加）：`{date,total,by_tier,by_source,by_key,by_group,merged_in_digest,trees}` |
| 3 | 查询面 | `scripts/alert_meter.py` | `--today` / `--week` / `--top N` / `--recount` / `--trees` / `--json` |

**冻结面纪律（§23.7）**：纯增量 —— 未改任何既有函数体/返回值/判定/阈值；台账写入
best-effort（无 flock 失败/OOM/权限错都只打 stderr，**绝不影响发送**，与既有 `_mirror_severe`
同款）；`--dry-run` 不写（与 `latest.md` 同契约）；路径复用既有 env 先例
`Path(os.environ.get("REPO") or REPO)`；多进程并发用 `fcntl.flock` 串行化追加，防交错半行。

**写点挂载**：`send()`/`send_to()` 消息级 1 条；底层三渠道包装
（`send_feishu` / `_send_email` / `send_telegram`，覆盖旁路/外部直调，单渠道 1 条）；
`send_tiered` 透传 `tier`；`flush_warning_batch` 透传 `merged_count`（=被并入摘要的条目数，
供 L2 使用）；`notify_agent_done` 标 `tier=agent_done`；
内部旁路 `_alert_feishu_config_missing`（飞书配置缺失时直发邮件，**独立主题**）在
**嵌套态**（`_ledger_depth() > 0`，渠道包装会被重入守卫跳过）时**条件补记** 1 条防漏，
depth==0 时不补（由渠道包装记，防双记）。

**重算挂点**：`scripts/schedule_monitor.sh` 收尾轮（warning flush 之后）调
`alert_meter.py --recount`，best-effort、失败不阻塞；**避开盘后重任务时点**
15:35/16:00/17:50/20:35/22:00（±2min，§14），命中窗口则本轮跳过（幂等 ⇒ 少跑一轮无副作用）。
**本机制自身绝不告警**（纯打印 + 派生文件）。

---

## 3. 跨两树聚合方案（§22 一致性）

双树分裂（云上运行树 `~/code/trade-data` + 信号树 `~/code/trade-data-signal` 各有独立台账
与 dedup 文件）是审计 **D1 结构性根因**。若只读一棵树 ⇒ 又变成「两个数字」。

`alert_meter.resolve_trees()` 解析顺序：`--trees a:b`（`os.pathsep`）> env
`ALERT_METER_TREES` > 默认 `REPO` + 兄弟树 `trade-data`/`trade-data-signal`（`resolve()` 去重、
缺目录自动跳过）。`--recount` 把**同一聚合结果写入每棵树**的 `alert_daily.json`
（内容逐位一致，机检见 §5）。

**口径分离**：台账含**全部**真实外发（含 report 群功能输出 / agent_done），查询面按 `group`
拆分 —— 主口径「告警群(alert)」与 report/agent_done 分列，防盘中信号等日常功能输出污染
「0~3 条/天」判据；`--today` 同时给「全量外发 N 条」供对账。

---

## 4. 改动前后对照

| 维度 | 改前 | 改后 |
|---|---|---|
| 「今天几条告警」 | 无数据源，只能人工翻 `latest.md` 与邮箱 | `alert_meter.py --today` 一行出数（告警群 / severe 直发 / 摘要并入 / 全量） |
| 单条告警可追溯 | 只有 `latest.md` 文本块 | JSONL 一行一事件（ts/tree/tier/key/subject/channels/source/group） |
| 跨树 | 两棵树各说各话 | 一次聚合出**一个**数字 |
| top talkers | 靠肉眼扫 | `--top N`（近 7 天 key 频次）+ `--today` 附 top8 |
| 与前 7 日比 | 无 | `--today` 尾行给前 7 日均值 + 逐日明细 |
| 既有行为 | — | **零变化**（未改判定/阈值/发送/去重；新增写入 best-effort） |
| 告警噪声 | — | 本次不降噪（W1 只度量；降噪是 W2+） |

---

## 5. 自验证据

### 5.1 今日真实 20 条样本重放（§18 L49 真样本，非人工构造）

样本来源 = 审计 §4 逐条定性表 + §2/§3 的键/源证据；**人工重建 20 条 → 台账重算 20 条**
（逐条对照表见 `scripts/tests/test_alert_meter_l1_20261010.py -s` 输出与
`scripts/tests/repro_alert_meter_l1_20261010.py` §[5]）。

| 口径 | 人工重建 | 台账重算 | 一致 |
|---|---|---|---|
| 总条数 | 20 | 20 | ✅ |
| severe（critical 直发） | 20 | 20 | ✅ |
| 告警群(alert) | 20 | 20 | ✅ |
| 摘要并入 merged_in_digest | 0 | 0 | ✅ |

`by_key`：`failed_units_patrol`=9、`schedule_monitor_alert`=4、其余 7 类各 1（合计 20）。
`by_source`：check_failed_units.py 10 / schedule_monitor.sh 4 / deploy.sh 2 /
upload_r2.py·intraday_snapshot.sh·nextday_gap_check.sh·nextday_gap_check.py 各 1。
双树校验：运行树 19 条 + 信号树（`nextday_gap_check_gen_fail`）1 条 ⇒ 跨树聚合 = 20（单一数字）。

### 5.2 幂等（重算两次逐位一致）

`alert_meter.py --recount --date 2026-10-09 --trees <run>:<sig>` 连跑两次（real samples）：

```
运行树 md5 785f172ce0c6a91d6152741d2c3f6fd6 -> 785f172ce0c6a91d6152741d2c3f6fd6   一致
信号树 md5 785f172ce0c6a91d6152741d2c3f6fd6 -> 785f172ce0c6a91d6152741d2c3f6fd6   一致
两树内容一致（§22）：是
```

`alert_daily.json` 无墙钟时间戳（只有 `date` + 排序后的 `trees`）+ `sort_keys=True`
⇒ 同台账两次重算**逐位一致**。schema 字段：`date/total/by_tier/by_source/by_key/by_group/
merged_in_digest/trees`（pytest `test_D` 断言齐全）。

### 5.3 pytest 全量

```
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/
→ RC=0   623 passed, 2 skipped in 93.69s
```
（含本次新增 `test_alert_meter_l1_20261010.py` **13 例**：A 沙箱正控 / B1~B5 台账打点与
去重守卫 / C 20 条真样本重放 / D 幂等+schema / E 跨树 / F CLI `--trees` / G 回滚开关 /
H1~H2 内部旁路嵌套漏记与零双记。）

### 5.4 冻结面证据（§23.7 + 纠偏点 6：零既有行为变更）

`git diff scripts/notify.py` 删除行共 15 行，逐行核对**全为此三类**（无一是既有打印/判定/文案）：
① `send`/`send_to`/`send_tiered` 签名行加新参数（尾部追加，位置调用不变）；
② `send`/`send_to` 内三条渠道调用**加 try/finally 缩进**（文本原样，仅缩进）；
③ `send_tiered`/`notify_agent_done`/`main` 的 send 调用**加 ledger_* 关键字**。
现存 5 类 suppress 输出措辞（含被 `retry_failed_metrics.py:130` 文本匹配的 L2183 行）
**一行未动**；`notify_sent.py` 及其 12 个调用方**不在本次 diff 内**；新增打印全部走 stderr。
`scripts/schedule_monitor.sh` 为**尾部纯新增** 30 行（+30/-0）。

### 5.5 零真实外发证据（§18 L48）

- 自测全程只写 `pytest tmp` 与 `/tmp/l1-repro`，**绝不碰**生产 `data/alerts/`；
- **沙箱正控先证生效**（`test_A`）：把 `load_email_config` 配齐后直调**真实**
  `_send_email_core`，`SMTP_SSL` 哨兵必然命中（断言 `_OUTBOUND_HITS` 非空 + 返回 False）
  ⇒ 证明哨兵确实能拦住真实发送链路；
- autouse fixture 断言：**除正控用例外，任何用例命中 `smtplib.SMTP_SSL` /
  `urllib.request.urlopen` 哨兵即测试失败**（防假绿）；
- 结论：**本次自测未产生真实邮件 / 飞书 / Telegram 外发**（无任何外发副作用）；
  台账/摘要机制自身也**不告警**（只 stderr 打印 + 派生文件）。

---

## 6. 回滚开关（可逆性）

| 级别 | 操作 | 效果 |
|---|---|---|
| 软开关（不停服务） | env `ALERT_LEDGER_DISABLE=1` | 台账**零写入**（发送等一切行为不变）；`alert_meter` 仍可查询既有台账 |
| 停止重算挂点 | 删 `schedule_monitor.sh` 尾部的 `alert_meter.py --recount` try 块（约 20 行） | 日计数不再刷新（台账不受影响） |
| 完全回滚 | `git revert <本 commit>` | `notify.py` / `schedule_monitor.sh` 恢复原状；`alert_meter.py` 与测试为纯新增文件，留着也无副作用（无人在跑它） |

回滚产物（`data/alerts/alert_ledger.jsonl` / `alert_daily.json`）均为**运行时派生文件、
不入 git**（`data/alerts/` 已 gitignore），删除/重算均无损（台账即事实源）。

---

## 7. 举一反三（§23.3）与同类错误面（§23.2）

- **同模式（外发→记账）还被谁用**：`send_tiered` / `notify_agent_done` / `flush_warning_batch` /
  `send_feishu_post_segmented` / `_alert_feishu_config_missing` + 5 个跨脚本直调方
  （§1 表）—— **逐项覆盖**：全部经消息级或底层包装其中之一记账（重入守卫防双记）。
- **同数据源（告警文本）还有谁在读**：`data/alerts/latest.md`（人读）、`notify_dedup.json`
  （去重状态）、邮箱/飞书群（人读）。本次**不改**这些；台账与之**同点产生**（同一次外发），
  不引入第二个口径。
- **同组件（查询面）展示位**：`--today` / `--week` / `--top`（+`--json`）共用同一 `aggregate()`
  ⇒ 三处数字同源；`--recount` 把同一结果写**每棵树** ⇒ N 展示位一致（§22）。
- **同类错误面清单**（本类型改动的复发面）：①漏挂某个旁路出口（已由 §1 穷举 + B2 直调用例锁死）
  ②双记（已由重入守卫 + B1/B3 锁死）③dry-run 脏写（B4）④全渠道失败误计（B5）⑤跨树漏聚
  （E/F）⑥环境相关不稳定（fixture 固定 `telegram_configured`，消除本机 config 有无差异）
  ⑦`--trees` 多树被当单路径（复现脚本当场踩出，已修 + 测试 F 锁死）
  ⑧**嵌套漏记**（外层编排态下内部旁路 `_alert_feishu_config_missing` 被重入守卫吞掉）
  （已由条件补记 + `test_H1/H2` 锁死）⑨dry-run 只验一部分入口（已扩到 B4 四入口）。

## 8. 其他规范

- **§21 算法公示同步**：本次**未改任何算法/数值/阈值/权重/评分/匹配规则**，无公示点需同步
  （grep `purpose-notes.js` / `app.js` / `lab.js` 无相关文案）。
- **§23.1 README**：本次未引用外部开源项目、无站点重大功能发布（纯运维度量，面向脚本/运维），
  README 无需改动。
- **§22 数据一致性**：`--recount` 写每棵树同一结果；台账为 append-only 事实源；
  查询面三视图同源。注意：`alert_ledger.jsonl` / `alert_daily.json` 是**运行时文件不进 git、
  也不走 static-site/R2 上线链**（非站点展示数据），故不涉及 R2/CF 同步。
- **§14 生产稳定性**：重算挂点避开 15:35/16:00/17:50/20:35/22:00；本改动不含任何推 main /
  写 DB / 追加重任务的动作，`schedule_monitor.sh` 改动为尾部新增 best-effort 子进程。

---

## 9. 复现命令

```bash
# 单测（含 20 条真样本重放，-s 打印逐条对照表）
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_alert_meter_l1_20261010.py -s

# 全量
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/

# CLI 级证据（幂等 md5 + today/week/top + 对照表，全部落 /tmp/l1-repro）
/Users/linhuichen/code/trade/.venv/bin/python scripts/tests/repro_alert_meter_l1_20261010.py --out /tmp/l1-repro

# 生产查询（云上：自动聚合运行树 + 信号树）
python scripts/alert_meter.py --today
python scripts/alert_meter.py --week
python scripts/alert_meter.py --top 20
python scripts/alert_meter.py --recount        # 幂等重算当日 alert_daily.json
```