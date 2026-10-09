# #240② failed-unit 判定「方向感知」精修(2026-10-09)

> 关联:#240(集合签名判定, commit `821df123f` 对称 changed + `57148888b` F1/F2 复审)、
> 全链路审计 `docs/ops/alert-system-fullchain-audit-20261009.md` §2-D3 / §3-F3 / §6-L3a / §6-L4 / §6-L5。
> 定位:审计「三个最大收敛杠杆」之 #1(今日 9/20 条 = 45%)。用户已授权精修已上线逻辑(非回滚)。

---

## 0. 一句话结论

`failed_units_daily_judge` 的 `changed` 是**对称判定**(不区分方向):集合**新增** failed unit(真信号)与集合
**缩小**(unit 被清零 = 恢复进展)被一视同仁「立即报」。本次拆为 **`added`(新增 → 立即报)** /
**`shrunk`(只有移除 → 静默)** / **`added-jitter`(同集合 24h 二次 added → 静默)**,状态文件加
`prev_signature` + `items`。**用今日真实巡检集合序列仿真:unit 巡检 9 条 → 2 条**(预期 1~2,达标);
真故障判别维度(新增立即报 / #196③ 连续 3 天升 critical / 跨日首报)**全部保留**。

**抖动静默边界(防误读为「无限吞」)**:同集合 `added-jitter` 静默后,跨日**下一轮 `daily-first` 即补报**
(延迟 ≤ 1 轮 = 15min);**任何成员变化 → 立即 `added` 报**;持续未清 → 第 3 天走 #196③ `critical` 独立通道。
即:同组成故障至多 24h 报 1 次 + 每日首报兜底,真故障一封不少。详见 §2.1。

---

## 1. 病灶复现(§18 L50 static-only, 云上只读)

### 1.1 病灶代码(#240 原始语义)

改造前 `scripts/alert_denoise_rules.py:111-127`:

```python
def failed_units_daily_judge(state, signature, today_str):
    if not signature:
        return False, "empty"
    if state.signature != signature:          # ← 对称: 变就一定报, 不看方向
        return True, "changed"
    if state.last_alert_date != today_str:
        return True, "daily-first"
    return False, "same-set-same-day"
```

**方向缺口(核心)**:方向信息在**汇总整串**层面丢失。失败集合 `{a,b}` → `{a}`(缩小)在整串比较下
=`"云上 failed unit: a, b"` 消失 + `"云上 failed unit: a"` 出现 —— 表现为「换新」而非「移除」。
⇒ 若只在整串签名上判方向,缩小会被误判成 added(方向判定失效)。**故方向判定必须下沉到细粒度成员**
(`failed_units_identity`: failed unit 名逐个 + 巡检者存活异常逐条)。

### 1.2 生产实证(云上 122.51.111.173, 只读)

- **状态文件仍是旧 4 字段格式**(说明 20:15 那次**缩小告警**确实落了盘):
  `~/code/trade-data/data/failed_units_patrol_sig.json` =
  `{"signature":"6992d0745f8b","last_alert_date":"2026-10-09","updated_at":"2026-10-09 20:15:06"}`
- **今日 failed-unit 集合逐轮单调缩小**(`schedule_monitor_launchd.log` 逐轮 `CHECK_FAILED_UNITS_FAIL` 重建):

| 变更时点 | 成员数 | 变更方向(相对上一轮) |
|---|---|---|
| 00:00 | 7 | (日初) |
| 08:15 | 6 | 移除 r2-consistency |
| 09:30 | 7 | 移除 kelly-intraday-rerun;新增 nextday-gap-check、r2-consistency |
| 16:15 | 6 | 移除 public-fund-daily |
| 16:30 | 7 | 新增 public-fund-daily(与 09:30 同集合) |
| 16:45 | 6 | 移除 public-fund-daily |
| 18:00 | 5 | 移除 fapi-daily |
| 18:15 | 4 | 移除 lhb-backfill |
| 20:00 | 2 | 移除 etf-national-team、futures-backfill |

- **时点口径(与 §8 统一)**:本表「变更时点」= `schedule_monitor_launchd.log` 记录的**集合变更(判定输入)
  时刻**;审计/notify 侧记录的**实际发送时刻**与之相差约 1 个 tick(§8),两者是对**同一批**集合变更的
  两种时点口径,方向与条数结论一致(勿因两处时点错位误判不一致)。
- **结论**:今日共 9 个判定时点 = **6 次纯「缩小」(恢复进展)** + 1 次真新增(09:30)+ 1 次 re-add 抖动
  (16:30)+ 1 次跨日首报(00:00);旧判据对每次变更都「立即报」。
  与审计 §2-D3 / §3-F3 完全一致(审计:17:00/18:15/18:30/20:15 四条为纯缩小触发)。**复现成立**,
  未发现与审计不符的情形。

---

## 2. 改动(三个文件)

### 2.1 `scripts/alert_denoise_rules.py`

- 新增常量 `FAILED_UNITS_ADDED_JITTER_WINDOW = timedelta(hours=24)`。
- 新增 `failed_units_identity(failed_units, watchman_problems=None) -> list`:方向判定用**细粒度成员集**
  (去重保序);docstring 说明为何不能用汇总整串(见 §1.1)。
- `failed_units_daily_judge(state, signature, items, today_str, now=None)` 改为方向感知:

| reason | 触发 | 动作 |
|---|---|---|
| `added` | 当前成员集 − 上一轮成员集 **非空** | **立即报** |
| `added-jitter` | 有 added 且当前签名 == 上次已报签名 且 <24h | 静默(抖动) |
| `shrunk` | 仅移除(无新增) | 静默(刷新观测,不动已报基准) |
| `daily-first` | 集合无变化 且 上次已报日期 ≠ 今日 | 立即报(跨日首报) |
| `same-set-same-day` | 集合无变化 且 今日已报 | 静默 |
| `changed` | **仅迁移期**:状态无 `items`(旧格式)且签名有变 | 立即报(fail-open,不吞真故障) |
| `empty` | 无异常 | —— |

- **`added-jitter` 静默的边界(写全,防误读「无限吞」)**:① 同日同组成重复 —— 旧代码本就
  `same-set-same-day` 静默,非本次新增(对比基线未变差);② 跨日 jitter 静默后,**下一轮 `daily-first`
  立即补报**(延迟上限 1 轮 = 15min);③ **任何成员变化 → 立即 `added` 报**;④ 持续未清 → 第 3 天走
  #196③ `consecutive_days` 升 `critical` 独立通道。净效果 = 同组成故障至多 24h 报 1 次 + 每日首报兜底。
- `failed_units_signature(items)` 不变(仍按传入项排序 md5);调用方仍以 `problems`(汇总串)计算,故
  **旧状态文件签名在内容不变时仍匹配** → 迁移期**仅在签名不变时**不额外报(签名有变 / 集合缩小走
  fail-open `changed` 报一次,见 §6)。

### 2.2 `scripts/check_failed_units.py`

- `_write_sig_state(...)` 状态 schema 扩展为
  `{signature(最近已报, sent-only), prev_signature(上一轮观测), items(上一轮成员), last_alert_date,
  last_added_signature, last_added_at, updated_at}`(仍 tmp+replace 原子写)。
  - `sent=False`(静默轮):**只刷新观测字段**(prev_signature/items),**不动** signature/last_alert_date
    —— 否则缩小静默轮会抹掉「上次已报集合」,破坏当日去重与抖动判定。
  - `sent=True 且 reason∈{added, changed}`:记 `last_added_*`(抖动基准;迁移期 `changed`=新集合首报,
    同样需作基准,否则首次告警后同集合二次 added 无基准可比 —— 见 §4 测试 bug 记录)。
- `main()`:新增 `_prev_state` 读取、`_identity` 细粒度成员计算、**健康轮记「集合已空」观测**
  (否则清空后同 unit 重现会被误判 shrunk 而漏报)、判定改传 `_identity`。
- 静默分支写观测 + 打印 `reason=`;发送成功写状态;发送失败**不写**(保留 F1 语义,下轮重试)。
- 文件头 docstring 补「② 精修(方向感知)」说明。

### 2.3 `scripts/tests/test_240_alert_denoise_batch2_20261009.py`

- `test_02` 重写为新 API,覆盖:empty / 旧格式迁移(changed/daily-first/same-set) / added / shrunk /
  same-set-same-day / daily-first / **add 优先于 remove** / added-jitter(24h 内) / added-jitter(超 24h 不抑制)。
- 新增 `test_02f`(added→报 / shrunk→静默 / 异集合新增→报;校验 items+prev_signature 落盘)。
- 新增 `test_02g`(抖动抑制;健康轮记 items=[];清空后子集重现→报)。
- `_MIN_ASSERTIONS` 保持 58(断言数只增)。

---

## 3. 验收对照表(§6-L5: 用今日真实样本, 不臆断)

**方法**:把 §1.2 的今日真实集合变更序列喂给**改造前**与**改造后**判定(纯函数仿真,
`scripts/tests/repro_240_direction_aware_20261009.py`, static-only),同一状态流转规则对比。非臆断。

| 时点 | 成员数 | 改造前 reason → 动作 | 改造后 reason → 动作 |
|---|---|---|---|
| 00:00 | 7 | daily-first → **报** | daily-first → **报**(跨日首报,保留) |
| 08:15 | 6 | changed → 报 | **shrunk → 静默** |
| 09:30 | 7 | changed → 报 | **added → 报**(新增 nextday-gap/r2,保留) |
| 16:15 | 6 | changed → 报 | **shrunk → 静默** |
| 16:30 | 7 | changed → 报 | **added-jitter → 静默**(与 09:30 同集合,24h 内) |
| 16:45 | 6 | changed → 报 | **shrunk → 静默** |
| 18:00 | 5 | changed → 报 | **shrunk → 静默** |
| 18:15 | 4 | changed → 报 | **shrunk → 静默** |
| 20:00 | 2 | changed → 报 | **shrunk → 静默** |
| **合计** | | **9 条** | **2 条** |

- **unit 巡检 9 → 2**(预期 1~2,达标)。降下的 7 条中:6 条纯「缩小=恢复进展」(与审计 §3-F3 一致),
  1 条 re-add 抖动(16:30,同集合 24h 内二次 added)。
- **真故障判别维度保留**:
  ① 新增 failed unit 立即报(09:30 命中,照发);
  ② 09:30 的新增若持续未清 → #196③ 连续 3 天**原样**升 critical(状态 `failed_units_patrol_state.json`
     今日 consecutive_days=2,机制未动);
  ③ 跨日首报照发(00:00)。
- **口径诚实标注**:今日 08:15/09:30/16:30 三行日志为 7 成员集合,末位成员在日志中**被字节截断**
  (`...,tra`);已按集合语义与 `.service` 全集复原为 `r2-consistency`,`tra` 为 `trade-r2-consistency.service`
  截断形态。截断不影响方向分类(该成员在两次出现的相对位置不变)。

---

## 4. 测试(红前绿后)

- **改造前**(`git show HEAD:scripts/alert_denoise_rules.py` 还原)跑新测试文件:
  `4 failed, 26 passed` —— 恰为 4 个方向感知用例(`test_02` / `test_02b` / `test_02f` / `test_02g`)在
  对称逻辑下**失败**(如 `②精修 缩小应静默, rc=1 n=1`),证明新测试确有判别力(非「假绿」)。
  ⚠️ **口径标注(勿误读为「只有 4 条红」)**:此 `4/26` 是**外科式还原**口径(只还原
  `alert_denoise_rules.py` 单文件、保留新 `check_failed_units.py` 与新 API);若按**全量还原父版**
  (连 `check_failed_units.py` 一并还原)跑,独立审查者实测 = **7 failed / 23 passed**(多出 `test_99` 因
  `_MIN_ASSERTIONS` 守卫 52<58 整文件 fail)。两口径红数不同(4 vs 7),但均证明新测试有判别力。
- **改造后**:`30 passed in 0.45s`。
- **相关全量**(240 + 196 + alert_denoise + alertchain_hardening + 181 fetchnews):
  `132 passed in 2.41s`(基线即此 5 文件全绿,本改动零回归)。
- **实施期抓到的一个真 bug(自测抓到,已修)**:`test_02g` 初版抖动未抑制 —— 因首轮(first observation,
  空状态)走**迁移期 legacy 路径**返回 `changed`(非 `added`),导致 `last_added_signature` 从未落基准。
  修=`_write_sig_state` 在 `reason∈{"added","changed"}` 时都记 `last_added_*`。**这正是「同集合二次 added
  无基准可比」的真实形态**,已在代码注释中固化防重犯。

---

## 5. 影响面 / 举一反三(§23.3)

**扫同模式「对称判定(不辨方向)」的兄弟点**:

| 兄弟点 | 是否同病 | 处置 |
|---|---|---|
| `check_data_gap_alerts.py` | **否(正面参照)** | 早已方向感知:accum_nav「当日新增缺价 / 历史回归 / 恢复」三分支(恢复不报) |
| `cloud_unit_patrol.sh` 配置漂移 | 否 | 对称比较,但**两向都是人工决策类漂移**(加/删字段均需人看),非「恢复进展」,对称正确 |
| `check_fade_keys_alignment.py` / `check_loss_rules_vs_mining.py` | 否 | CI 键集/口径闸门,两向差集**都是真不一致、都必须修**,对称是设计(且面向 deploy 阻断,非用户告警) |
| `gen_daily_brief.py` 状态切换 | 否 | 已在计算方向(牛/熊转向) |
| `overfit_monitor.py` risk 判定 | 否 | risk_climbing 已方向感知 |
| `signal_kelly_snapshot._polluted_ratio` | 否 | abs 比值,方向无关是语义要求 |
| R1/R4/R7 降噪规则 | 否 | 已有「已恢复/已追上」方向分支 |

**结论**:全仓**无第二处**「方向盲的集合变更 → 用户可见告警」同类病灶;本次修复面即唯一病灶点。
**相关展示位**:告警正文集合顺序、`data/failed_units_patrol_sig.json` 状态 schema、
`data/failed_units_patrol_state.json`(#196③ 升级计数)——三者语义均未改变(状态文件字段为**纯新增**,
旧字段语义保留),下游(notify.py #196③ 以 dedup-key 精确接线)**一字未动**。

---

## 6. 回归与回滚

- **回滚**:本改动为纯函数判定 + 状态文件新增字段;回滚 = `git revert` 本 commit,状态文件字段向前兼容
  (旧代码忽略未知字段)。**不影响** R1-R7 / #196 / #241 任意机制。
- **迁移**:线上状态文件为旧格式(无 `items`)→ 首轮走 `changed`(fail-open 报一次),随后自动补齐
  `items`/`prev_signature`,进入方向感知。**除迁移期 fail-open 首轮外不产生额外告警**:线上为旧格式
  (无 `items`)状态时,若集合**缩小**,会走 legacy `changed` 分支多发 **1 条 fail-open changed**(设计如此,
  宁多报不吞真故障);其后进入方向感知即不再额外发。签名 basis 与旧代码一致。

## 7. 复现命令(全部只读/离线)

```bash
# 单测(红前绿后)
.venv/bin/python -m pytest scripts/tests/test_240_alert_denoise_batch2_20261009.py -q
# 相关全量
.venv/bin/python -m pytest scripts/tests/test_240_*_20261009.py scripts/tests/test_196_*_20261005.py \
  scripts/tests/test_alert_denoise_20261001.py scripts/tests/test_alertchain_hardening_20261003.py \
  scripts/tests/test_181_fetchnews_denoise_20261007.py -q
# 真实样本对照仿真 (static-only)
.venv/bin/python scripts/tests/repro_240_direction_aware_20261009.py
# 云上病灶复现 (只读)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cat ~/code/trade-data/data/failed_units_patrol_sig.json'
```

## 8. 诚实标注(§5.1④)

- 本次为**判定层精修**,未新增度量(审计 §6-L1 台账)与摘要合并(§6-L2),故「缩小」是**静默**而非
  「入当日摘要」—— 与审计 L3a 允许的两种口径之一一致(静默)。若后续上 L2 摘要层,`shrunk` 可一行改接摘要。
- 对照表基于**判定层纯函数仿真**(复刻 `_write_sig_state` 状态流转),非端到端重放;生产实际发送时刻
  还受 notify 通道与轮次相位影响(故审计实测消息时刻与集合变更时刻差 1 个 tick),但**条数结论一致**。
- 今日 9 条 unit 巡检中,**04:30/10:45 两条由旧码(6h 窗逐轮重报同一内容)产生**;**13:00 一条不是旧
  6h 窗,而是 12:52 部署后首轮的迁移期 `changed`(状态缺失 → fail-open 报一次)** —— 与
  `scripts/alert_denoise_rules.py` docstring 自载「12:52 部署后 7 连发」
  (13:00/16:30/16:45/17:00/18:15/18:30/20:15)一致。本对照表按「同一批集合变更序列」统一口径给 9→2。