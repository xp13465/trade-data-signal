# 告警系统性收敛「建议实施方案」(2026-10-10,用户拍板「要拍板的都做」)

> 依据:`docs/ops/alert-system-fullchain-audit-20261009.md`(全链审计,20 条真实样本逐条定性 / 5 层收敛方案 / 三杠杆)
> 用户验收标准:**告警群即时消息 一天 0~3 条**
> 本方案作者:主控(2026-10-10)。改动一律走「派单 → 独立审 → `main-merge.sh` → §0 生产实证」。

## 0. 一句话

先把「一天几条」变成**唯一权威数字**(否则"0~3"永远验收不了、历次降噪永远判不了满意不满意),再逐波把判别错的判对。
**降噪铁律(业界同款)**:首报必达 / critical 永不入预算 / 新 key 永远直发 / 被合并条目**必须**出现在摘要且注明被合并条数 —— 静默的**只允许**是「同一事实的当日重复」。

## 1. 分波推进总览

| 波 | 内容 | 性质 | 状态 |
|---|---|---|---|
| **W1** | **L1 度量层**(台账 + 日计数 + 查询面) | 用户已拍板(**碰 `notify.py` 冻结面**,纯新增) | 本波实施 |
| **W2** | **L3d / #241 Pattern B 3 处**(rc 判据卡在 dedup 静默分支) | 用户已拍板(碰冻结面输出契约) | 本波实施(W1 之后,串行) |
| **W3** | **#241B 前端通知与邮件送达解耦** | 用户已拍板 | 本波实施(W2 契约之后) |
| W4+ | L3c / L3e / L2 / L5 | **会改已发布行为 ⇒ 需用户单独点头** | 建议队列(见 §7) |

**串行约束**:W1 与 W2 **都改 `notify.py`** ⇒ 必须串行(防两处实现漂移);W3 与之不同文件,但要**先复用 W2 的判据契约**。

## 2. W1 — L1 度量层(第一优先级:让「一天几条」变成可查数字)

### 现状缺口(审计 §5 实测)
`latest.md` 是 cap50 滚动流水、`notify_dedup.json`/`alert_state.json` 是 per-key 时间戳(无日计数,键还会被覆盖)、`warning_buffer.jsonl` 发完即清、恢复消息**连痕迹都没有** ⇒ 「一天几条」**没有任何单一权威数字**,必须拼 ≥5 个来源才能近似 —— 这就是"0~3 条/天"无法验收的根因。

### 改动 3 件(同一分支,同一作者上下文)
1. **单点台账 `data/alerts/alert_ledger.jsonl`**
   - 写点 = **3 个渠道函数** `send_feishu`/`send_telegram`/`_send_email`（CLI 13 个分支 + 10 个库直调脚本的共同必经点）；原述通用汇总处覆盖不全。
   - 每封**实际外发**追加一行:`{ts, tree(REPO), tier, key(dedup_key 或 subject 哈希), subject, channels{email,feishu}, source(sys.argv[0] / NOTIFY_SOURCE)}`。
   - **冻结面处理(§23.7)**:纯新增追加写、**零现有行为变更**;best-effort(写失败不阻塞发送,同 `_mirror_severe` 模式);路径解析**沿用该文件既有 3 处 env 先例** `Path(os.environ.get("REPO") or REPO)`(L2227/2267/2317)—— 是既有模式的推广,**不是新发明**;`--dry-run` **不写台账**(同 #184 的 latest.md 约定)。
   - **出口穷举(防漏记)**:开工先列 `notify.py` 全部真实外发出口并确认是否单点;若不止一处,**选能覆盖全部真实外发的最小集合**,出口清单随报告落档(不许只挂一处就声称全量)。
2. **日计数产物 `data/alerts/alert_daily.json`**
   - `{date, by_tier, by_source, by_key, total, merged_in_digest}`;由台账**幂等重算**(**不是**累加 ⇒ 无状态漂移风险)。
   - 重算挂点:monitor 每轮末尾或 23:30 收尾轮(避开 15:35/16:00/17:50/20:35/22:00 盘后时点)。
3. **查询面 `scripts/alert_meter.py --today / --week / --top`**
   - 输出「今日 X 条(severe Y / 摘要并入 Z)+ top talkers + 与前 7 日均值对比」。
   - **关键:必须跨两树聚合** —— 双树分裂(审计 D1)是结构性根因,若不跨树会**又变成两个数字**,违反 §22 一致性铁律。

### 验收口径
- 用**今日真实 20 条样本重放**:给「手工重建 20 条 / 台账重算 X 条」**逐条对照表**(沿用 #240 惯例,不许臆断)。
- 全量 `pytest -q scripts/tests/`(仓库 `.venv`,禁 `/usr/local/bin/python3`,禁管道吞退出码)+ 确切 passed/failed 数。
- **零真实外发**:自测前必须先打桩沙箱(§18 L48),并**先证沙箱判定生效**。

## 3. W2 — L3d / #241 Pattern B 3 处(与 #241 合并为一个项,不重开)

### 病灶
`check_monitor_heartbeat.py` / `nextday_gap_check.py` / `nextday_plan_generator.py` 用「`rc` 判 notify 是否真发出」;而 `notify.py` 的 **CLI 13 个分支恒 `return 0`,rc 无判别力** ⇒ 包装层**无法区分「真发出」与「被去重抑制」**,只能在「弱化 fail-safe(有丢告警风险)」与「不动」之间二选一。
**订正（证伪, 2026-10-10 调研）**：原述「dedup 抑制分支静默 `return 0`（不打任何输出）」与代码事实不符 —— 抑制路径**有 stderr 输出（7 处）**；真正病灶 = **CLI 13 个分支恒 `return 0`，rc 无判别力**；故改走**路线 B（不动冻结面）**，判据改为读抑制行的 stderr 输出（`scripts/notify_sent.py:notify_state` 三态）。

### 推荐改法(加法,不弱化判别维度)
给冻结面加**一行机器可读输出**(例:`[notify] dedup-suppressed key=<k>`),让判据升级为**三态**:

| 态 | 判据 | 包装层动作 |
|---|---|---|
| 真发出 | 既有 `notify_sent()` 命中 | 成功,不重试 |
| **被抑制** | 新增抑制标记命中 | **成功且已知**,不重试、不报错(这正是当前 fail-safe 想表达却表达不出的语义) |
| 全渠道失败 | 已有 #241 Pattern A 契约 | 不落签 ⇒ 下轮重试 |

### 前置穷举(必须先做,防新输出行破坏既有解析)
列出**所有解析 `notify.py` stdout/stderr 的调用方**,给出「新增这一行会不会破坏它」的逐项判定。

## 4. W3 — #241B 前端通知与邮件送达解耦

### 病灶
`detect_intraday_anomaly.py` 的 `anomaly_notified.json` 门控挂在**邮件送达之后**;而该文件是**前端浏览器通知的唯一数据源** ⇒ 邮件通道一挂,前端通知也静默丢失(两条链路被错误耦合)。

### 方向
- 门控与「是否已**产出并写入** `anomaly_notified.json`」(= 前端取数源头)对齐;
- 邮件送达**单独记账**(复用 W2 的三态判据);
- 先只读调研摸清现状与最小改动面(含与 W2 契约的关系),再实施。

## 5. 不变式(每一波都必须自验包含)
1. **首报必达**:每 key 当日首报永远直发。
2. **critical 永不入预算/摘要**。
3. **新 key 永远直发**。
4. 任何被合并的条目**必须出现在摘要里**并注明「被合并 N 条」。
5. 台账/摘要机制**自身绝不告警**(防元噪声)。
6. 各层独立 env / 常量开关,**单层可回滚**,不影响 R1-R7 / #196 / #240 / #241 既有机制。
7. 所有"降噪"结论必须给**同一真实样本的前后判定对照表**(数据说话,§5.1②)。

## 6. 风险与对策
| 风险 | 对策 |
|---|---|
| 过度收敛吞掉新故障 | 不变式 1-4 + 每周 review top-talkers 抽查"被吞条目是否都出现在摘要" |
| 双树导致数字不唯一 | W1 查询面**强制跨树聚合**;W4 的 L3e 单树化是治本 |
| 冻结面改动引入回归 | 纯新增/加法、best-effort、`--dry-run` 不写;独立审 + 全量 pytest + §0 生产实证 |
| 新输出行破坏既有解析 | W2 前置「输出消费者穷举」逐项判定 |
| 切换瞬间窗口重启致短期重复增多一次 | L3e 等单树化改动放**低时段**切换 + 切换日观察 |

## 7. 建议队列(W4+,会改已发布行为 ⇒ **需用户单独拍板**)
- **L3c**:`fetch_news` r2-skip 自愈瞬态降 `--tier warning`(保留"锁持续忙仍升级"判别维度)。
- **L3e**:双树收口 —— 推广 `Path(os.environ.get("REPO") or REPO)` 到 `DEDUP_FILE`/`ALERTS_DIR`,状态单树化(治 D1 根因)。
- **L2**:预算 + 摘要层 —— 泛化既有 `r5_congestion_process` 先例,按类别日预算;超预算并入当日摘要;恢复消息**必须出现**(治 D5「恢复被 6h 窗吞掉 ⇒ 告警无闭环信号」)。
- **L5**:预算验收 —— 连续 7 天 **P50 ≤3 且 P90 ≤5**;每周 review top-talkers + 被吞条目找回核对。

## 8. 复现命令(全部只读)
```bash
grep -n "os.environ.get(\"REPO\")" scripts/notify.py            # env 先例 3 处(L2227/2267/2317)
grep -n "DEDUP_FILE\|ALERTS_FILE\|WARNING_DEDUP_STATE_FILE" scripts/notify.py
sed -n '111,127p' scripts/alert_denoise_rules.py               # failed_units_daily_judge(已被 #240② 精修)
sed -n '513,568p' scripts/alert_denoise_rules.py               # R5 拥堵日汇总(收敛先例)
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/
```

## 9. 权威参照(外部,防闭门造车 §5.1)
本项目设计取向与业界一致:**首报必达**(聚合不得吞掉首条可行动告警)、**告警预算/错误预算**、**去重→依赖抑制→分级路由→摘要**、**每条告警须可行动(否则即噪音)**。
- Google SRE actionable-alert checklist(SRE 读书笔记):https://www.cnblogs.com/liqinglucky/p/18773074/SRE
- 告警聚合/分组配置要点(first-wait、group interval、repeat interval、「上线前用历史告警演练确认关键告警仍第一时间送达」):https://www.renrendaima.com/article/26047.html
- 告警降噪与智能分组(AIOps 实践):https://blog.csdn.net/weixin_38171602/article/details/166887906
- 告警疲劳:SLO/错误预算与可行动性:https://sensu.io/blog/alert-fatigue-in-sre-and-devops

## 10. 诚实标注
- 本方案是**设计**,数字收益(如 unit 巡检 9→2)已由 #240② 生产样本验证;其余各层的收益为**基于今日 20 条真实样本的推算**,未实施前不算既成事实。
- W1 是本方案唯一"不直接减今日条数"的一层,但它是其余各层**可验收的前提**。