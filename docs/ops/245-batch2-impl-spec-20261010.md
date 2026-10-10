# #245 批2 实施规格(L2 预算+摘要层 / L3c / B4-3 收口 / W1 遗留)

- 日期:2026-10-10(调研 agent 只读产出,供 implementer 直接照做)
- 性质:规格文档,**未改任何代码、未 commit、未云上写**;全部行号 = 2026-10-10 现码实测(方案/设计文引用行号多处已漂移,以本文件为准;每处给「符号锚 + 行号」双锚,行号漂移时以符号锚为准)
- 依据:方案 `docs/ops/alert-convergence-plan-20261010.md` §7/§5/§6/§8 + B4-3 设计 `docs/ops/1009-real-faults-rootcause-design-20261009.md` §B4-3 + 优先级/排序 `docs/ops/245-alert-w4-priority-20261010.md` §2/§3/§7 + 10-08 全量 triage `docs/ops/alert-triage-1008-20261008.md`
- 前置已完成(不在本批实施范围):① L3e REPO env 单树化(notify.py L97,云上 `e18174caa` 生效);② 过渡窗口 dedup 历史合并(10-10 13:25 apply / 14:05 dry-run added=0,见 `docs/ops/245-l3e-switch-closeout-20261010.md`;代码树 52 键已被运行树 64 键保守覆盖)

## 0. 范围、顺序、不变式与口径决策

### 0.1 批2 = 4 件

| # | 件 | 触面 | 依赖 |
|---|---|---|---|
| 1 | **L2 预算+摘要层**(核心,本文 §1) | notify.py(send gate + digest buffer/flush)+ adr(类别函数)+ schedule_monitor.sh(行级预算 + 恢复闭环) | W1 台账(已上线);建议最后做 |
| 2 | L3c r2-skip 自愈类降 tier(§2) | schedule_monitor.sh 单块 | 无 |
| 3 | B4-3 收口(§3) | nextday_gap_check.py/.sh + schedule_monitor.sh exit/关键词块 + adr 常量 | 无 |
| 4 | W1 遗留 NOTIFY_SOURCE(§4) | repo_paths.sh 一处 + 13 个 py 各一行 | 无 |

建议实施顺序:§4(独立最简)→ §3(独立)→ §2(独立)→ §1(核心,依赖前者全部在位)。每件可独立发版/单独回滚。

### 0.2 不变式(plan §5,实施必须逐条保)

- ① 首报必达:每**类别**当日首报永远直发(口径决策见 0.3)
- ② critical 永不入预算(升级档 send_tiered(critical) 全程 exempt)
- ③ 新 key 永远直发(操作化=未映射类别的 key 永远直发)
- ④ 被合并条目必须出现在摘要且注明「被合并 N 条」
- ⑤ 台账机制自身绝不告警
- ⑥ 各层独立 env 开关可回滚:新增 `ALERT_BUDGET_DISABLE=1`(L2 总开关)、`ALERT_DIGEST_DISABLE=1`(摘要 flush 开关);回滚=置 1,零代码回改
- ⑦ 真实样本前后对照表(用 10-09 或 10-10 真实台账数据做改造前→改造后逐条判定表,见 §6 验收)

### 0.3 口径决策(必须主控确认,§23.13)

1. **「每 key 首报直发」→「每类别当日首报直发」**:plan §5 字面「每 key 当日首报永远直发」与「类别日预算」冲突(严格按 key 则预算近乎失效——10-08 unit 三条是三个不同 key)。本规格操作化为:**类别内当日首条直发,第 2+ 条吸收进摘要**(条目在摘要中可见,注明原因);**未映射类别的 key(=category_of 返回 None)永远直发**(覆盖「新 key 永远直发」)。
2. **L5 验收口径(事件日是否纳入 P90)**:plan 原文「连续 7 天 P50≤3 且 P90≤5」。按本规格 7 类预算首版重放 10-08(多根因并发事件日)≈13~14 条(7 类各 1 + 杂项 9 条豁免 - 类内省 3);若验收把事件日纳入 P90,则首版即启用 §1.3 加强档(task_family 吸收,重放≈8~9);若不纳入(验收只看常态日),首版 7 类档位即可。**推荐:先按全量口径排(即首版带加强档),上线后第 1 周 L5 实测数据定档**——但此项=拍板项,由主控/用户定。
3. 摘要时点 23:25 与 dedup 窗口关系:摘要消息自身**不占**任何 dedup key(幂等靠 buffer 精确清理 + last_sent_day 标记);恢复补列走摘要通道时**绕过** `schedule_monitor_recovery` 6h 窗(见 §1.7)——即 6h 窗只 pacing 直发通道,不吞条目本身。

## 1. L2 预算+摘要层(核心)

### 1.1 设计总览(数据流)

```
单发通道(wrapper/in-process 直发)           monitor 批次通道(多行聚合)
  notify.py send(severe=True, group=alert)     schedule_monitor.sh 组装 alerts[] 前
        │                                          │
        ▼                                          ▼
  ┌──────────────── gate(§1.4)─────────────┐  ┌── adr.alert_budget_process(§1.6)──┐
  │ category_of(key,subject) → cat          │  │ category_of_line(行文本) → cat     │
  │ 读台账当日 category 直发数(§1.2)        │  │ 读同一台账计数(单一数字)           │
  │ 未超预算/未映射 → 直发(现行为)          │  │ 未超 → 保留在批次; 超 → 吸收       │
  │ 超预算 → append digest buffer(§1.5)    │  │ 吸收行 → notify --defer-digest     │
  └─────────────────────────────────────────┘  └────────────────────────────────────┘
        │ digest buffer(data/alerts/alert_digest.jsonl)     │
        ▼                                                    ▼
  每日 23:25(-ish)monitor 尾部 --flush-digest → 1 条 [告警·摘要](severe=False, tier=digest, merged_count=N)
  + 恢复闭环 D5:被 6h 窗吞掉的恢复 → monitor_recovery|pending → 窗口过期直发 or 当日摘要补列(§1.7)
```

关键机制取向:① **计数单一事实源 = W1 台账**(`data/alerts/alert_ledger.jsonl`,group=alert、非 digest 行按 ts 当日计数)——跨通道统一数字,与 alert_meter 展示口径一致(§22);② **buffer/锁/幂等机械全部复用 warning 先例**(`_append_jsonl`/`_stable_rid`/`flushlock` 全生命周期锁/`_parse_buffer_lines`/精确清理);③ gate 挂 send() 入口,覆盖 CLI + in-process 全部直发路径。

### 1.2 类别维度定义(基于现有告警系统)

现系统可用的区分维度只有:dedup key(各调用方自定义字符串)、tier(critical/warning/info 语义分级)、group(alert/report/…)、source(W1 发出者)。**类别 = 新增语义映射 `category_of(key, subject)`,放 `scripts/alert_denoise_rules.py`(纯函数,可单测)**;理由:tier 太粗(全部 SEVERE 都是 critical)、group 只有 alert 一个、source 是发出者不是根因类。

映射表(首版,key 优先、subject 兜底;均 case-sensitive 子串/前缀判):

| 类别 | 判据(key 子串/前缀, 或 subject 兜底) | 10-08 直发样本(triage §2 表) |
|---|---|---|
| `unit` | key 含 `unit_patrol` / `failed_units` / `cloud_unit_patrol` | #3 #5 #14(3 条→1) |
| `r2` | key 前缀 `r2_` 或含 `r2_pipeline_congestion` | #17(1 条) |
| `data_gap` | key 含 `data_gap` 或 subject 含 `[数据缺口]` | #15(1 条) |
| `gap_check` | key ∈ {`nextday_gap_check_fail`,`nextday_gap_check_gen_fail`} 或 subject 含 `伪跳空` | 0 条(历史有) |
| `deploy` | key 前缀 `deploy_` | #1 #6(2 条→1) |
| `fund_nav` | key 前缀 `fund_nav` | #9(1 条) |
| `kelly` | key 含 `kelly` | #2(1 条) |
| (未映射) | 其余 | #4 #7 #8 #10 #11 #12 #13 #16 等 9 条豁免 |

**category_of_line(line)**(monitor 侧,同文件):strip `"SEVERE: "` 前缀后——先 `r5_is_r2_congestion_line`(L555-574,复用现文本判据)→ `r2`;含 `[数据缺口]` → `data_gap`;含 `nextday_gap_check`/`伪跳空` → `gap_check`;task 前缀(first token)含 `unit_patrol`/`failed_units` → `unit`;含 `deploy` → `deploy`;其余 → None。

### 1.3 日预算档位(先拍值 + 上线后调)

| 类别 | 预算(当日直发上限) | 依据 |
|---|---|---|
| unit / r2 / data_gap / gap_check / deploy / fund_nav / kelly | **各 1/日** | 10-08 事实:unit 3 条、deploy 2 条非首条均为同因复报;其余类天然 1;gap_check 经 §3 统一键后天然 1 |
| 未映射 | exempt(不限) | 保守:首版只咬「已识别的重复族」,宁多发不吞 |

- **预期效果**:稳态日 0~1 条(见 alert_meter 前 7 日均值);10-08 式事件日重放 ≈13~14(首版)或 ≈8~9(加强档,见下)。**参数为初值,上线第 1 周用 L5 数据(alert_meter P50/P90)调**——调参动作清单:①加类别(把 10-08 型豁免项中重复出现的族补进表)②降预算(仍>1?)③启用加强档。
- **加强档(可选,拍板项 0.3-2)**:对 monitor 批次行加 `task_family` 吸收(每 task 1 条/日,monitor 侧独有,不上单点 gate)——10-08 重放吃掉 #11+#13(etf 同任务两条)等,进一步 ≈8~9。缓上与否见拍板。
- ⚠️ 诚实标注:上述数字为按 10-08 单日样本推演,非实测;plan §7 的「6~7 条/事件日」为更激进推演(吸收面更宽),以 L5 实测为准。

### 1.4 notify.py 单点 gate(核心改点)

**现状锚**:`send()` 定义 L1111-1180(签名 L1111-1118);恢复清零块 L1149-1153;`if severe:` L1154;ledger depth L1158;返回 L1180。main() 通用路径:check_dedup L2536-2537、send 调用 L2539-2544、汇总打印 L2545-2552、update_dedup L2555-2556。

**改法**:
1. `send()` 签名(L1111-1118)加一个 kwarg:`budget_exempt: bool = False`。
2. 新增模块级常量(插 L249 `WARNING_FLUSH_LOCK_FILE` 后;并在文件头 W1 注释块后加 L2 注释段):
   - `ALERT_DIGEST_FILE = ALERTS_DIR / "alert_digest.jsonl"`
   - `ALERT_DIGEST_LOCK_FILE = ALERTS_DIR / "alert_digest.flushlock"`
   - `ALERT_DIGEST_STATE_FILE = ALERTS_DIR / "alert_digest_state.json"`(存 `{"last_sent_day": "YYYY-MM-DD"}`)
   - `ALERT_DIGEST_HM = "23:25"`
3. gate 插入点:`send()` 内**恢复清零块(L1149-1153)之后、`if severe:`(L1154)之前**;判定伪码(实现照抄语义,细节变量名 implementer 定):

```python
if (severe and not dry_run and not budget_exempt
        and os.environ.get("ALERT_BUDGET_DISABLE") != "1"):
    _cat = adr.category_of(ledger_key, subject)          # None=未映射 → 直发
    if _cat:
        _n = _budget_today_count(_cat)                   # 读台账当日 group=alert 非 digest 行, 见下
        if _n >= adr.ALERT_BUDGET.get(_cat, 1):
            if _absorb_to_digest(subject, body, key=ledger_key, category=_cat,
                                 source=source, from_prefix=from_prefix):
                print(f"[notify][budget] 并入当日摘要 key={ledger_key or '<subject>'} "
                      f"category={_cat} (今日 {_cat} 直发 {_n}/{adr.ALERT_BUDGET[_cat]})",
                      file=sys.stderr)
                return {"email": False, "telegram": False, "feishu": False, "digested": True}
            # append 失败 → fail-open 落直发(宁多发不吞, 不 return)
```

4. 辅助函数(notify.py 内新私有):
   - `_budget_today_count(cat) -> int`:读 `_ledger_path()`(L125-127),逐行 `json.loads`(坏行 try/except 跳过=fail-open),条件:`ts` 前缀== `datetime.now().strftime("%Y-%m-%d")` 且 `group=="alert"` 且 `tier!="digest"` 且 `adr.category_of(row.get("key"), row.get("subject"))==cat` → 计数。文件不存在 → 0(自然直发=现状)。性能:几十行/次,无需缓存。
   - `_absorb_to_digest(...) -> bool`:①当日 buffer 已有同 (day,key) 条目(`_parse_buffer_lines` 过滤)→ 直接 return True(幂等,不重复 append);②`_append_jsonl(ALERT_DIGEST_FILE, rec)`(复用 L1560 附近;rec={ts,rid,day,key,category,subject,body(截 3000 同 defer_warning),from_prefix,source,reason:"over_budget"});③异常 return False。
5. `main()` 适配(通用路径 L2539-2544 之后):
   ```python
   if results.get("digested"):
       return 0        # gate 已打 [notify][budget] 行; 不打印"已发出"、不 update_dedup、不 write_alert
   ```
   插在 L2545(`ok = ...`)之前。逐条后果:不占 dedup 窗(幂等靠 buffer (day,key));不写 latest.md(未外发消息不该在最新告警页);返回 0(调用方 rc 恒 0 契约不变)。
6. **exempt 路径**:`send_tiered()`(L2247-2284)的 critical 分支(`send(severe=True, ...)`,L2519 附近同款)传 `budget_exempt=True` —— 覆盖「critical 永不入预算」+「升级档必达」+「RG 恢复/手动触发」;warning/info 分支不经过 send(severe=True),天然无影响。**其余 send(severe=True) 调用不传**(gate 生效):这正是 10-08 unit/deploy/r2 等收敛源。
7. 与 in-process 调用方(upload_r2.py / signal_kelly_snapshot.py 等直调 send(severe=True))自动生效——**不需要**每个调用方改;其返回 dict 多出 `"digested"` 键:现有调用方若遍历 results 判 ok,`digested` 会被计入 ok=[] 之外……注意:`ok = [ch for ch,v in results.items() if v]` 形态会把 `"digested"` 当渠道!所以除 main() 外,若 in-process 调用方做 ok 判定,须以 `results.get("digested")` 先行判断或只取 email/telegram/feishu 三键——**实施时 grep 全部 `send(` 调用点的 ok 判定形态同步适配**(已知:main L2545、flush 内部 `_tier_send_ok` 读三键、signal_kelly_snapshot 读三键;其余 grep 核)。

**行为变化逐条(§23.7 用)**:
- 类别内第 2+ 条 SEVERE:不再邮件/飞书/latest.md/dedup 窗;**新变化** = 当日稍后(≤23:25 后首次 flush)一条摘要含它;台账多一行 tier=digest(merged_count=N),该 SEVERE 自身**不落台账**(未外发不记,与 W1 口径一致)。
- 类别内首条、未映射 key、critical/升级档、dry_run、台账缺失、`ALERT_BUDGET_DISABLE=1`:行为**逐字节=现状**。
- 调用方可见差异:`send()` 返回新增 `"digested": True` 分支;CLI stderr 多一行 `[notify][budget] ...`。

### 1.5 digest buffer 与 flush(摘要层机械)

**复用模板**:warning 先例全链——`_append_jsonl` L1560、`_stable_rid` L2009、`_parse_buffer_lines` L2021、`flush_warning_batch` L2036-2064 → `_flush_warning_batch_locked` L2066+(snapshot → 判定 → send → 精确清理,全程持有 flushlock);send 调用模板 L2150-2153:`send(subject, body, severe=False, dry_run=dry_run, from_prefix=prefix, feishu_group="alert", ledger_tier="warning", merged_count=n)`。

**改法**:
1. `flush_digest(dry_run=False)`(新函数,结构 mirror flush_warning_batch):
   - 抢 `ALERT_DIGEST_LOCK_FILE` 全生命周期锁(同 L2066+ 模式;抢不到=另一 flusher 在处理,return 0 静默)。
   - snapshot:读全部条目,分 `due`(day==today)与 `stale`(day<today,隔日兜底)。
   - 触发条件任一:`stale 非空`;或 `now >= ALERT_DIGEST_HM(23:25)` 且 `due 非空` 且 state 的 `last_sent_day != today`(当日只发一封;防 23:25 后连续轮次重复发)。
   - 不满足 → 原样保留条目 return 0。
   - 满足 → 组装 1 条消息:
     - subject:`[告警·摘要] 当日合并 {N} 条 ({cat1} {a}/{cat2} {b}/...) {MM-DD HH:MM}`(stale 混入时 N 含前日遗留,正文标注)
     - body:intro 行(「以下 {N} 条告警未即时直发,已并入本摘要(超日预算);条目仍可追溯:台账 data/alerts/alert_ledger.jsonl / 监控日志」)+ 每条一行 `[HH:MM][category] key — subject(原因)`(原因取 rec.reason;含恢复补列条目时标注 `[恢复补列]`)
   - send 调参(逐字对标 L2150-2153 模板):`send(subject, body, severe=False, dry_run=dry_run, from_prefix="[告警·摘要]", feishu_group="alert", ledger_tier="digest", ledger_key="alert_digest", merged_count=N)`
   - 成功(真实发出)→ 按 `_stable_rid` 精确清理已发条目 + 写 state `{"last_sent_day": today}`(**清理与 state 只在发送成功后做**;发送失败=条目全保留,下轮/次日重试——「绝不丢条目」与 warning flush 同契约)。失败 → 打印 `[notify][digest] flush 未发出, 条目保留 N 条` 到 stderr,return 0(不阻塞 monitor)。
   - `dry_run` → 只打印不发送不清理。
   - `ALERT_DIGEST_DISABLE=1` → 直接 return 0(flush 全停;注意:gate 吸收仍然发生 → 条目积压但不外发 = 需要置 `ALERT_BUDGET_DISABLE=1` 才是完整回滚,文档写明两开关关系)。
2. 新 CLI `--flush-digest`(mirror `--flush-warnings` 分支 L2354-2358):argparse 加 `--flush-digest` action=store_true;分支调 `flush_digest(dry_run=args.dry_run)`,打印结果,return 0。
3. 新 CLI `--defer-digest`(monitor 行级吸收 + 恢复补列用):argparse 加 `--defer-digest`(store_true)+ `--digest-category CAT`(str);分支在 `--flush-digest` 分支旁:**主体 = bash 同款 `--tier` 分支之前的独立分支**;语义=把 positional subject/body 直接 `_absorb_to_digest`(单独解析,含当日 (day,key) 幂等);成功打印 `[notify][digest] 已并入摘要 buffer` return 0,append 失败打印 `[notify][digest] 并入失败` return 1(调用方据此回批,见 §1.6)。dry_run → 只打印 return 0。

**行为变化**:纯新增 CLI 与文件;现有 `--flush-warnings`/`--tier`/通用路径零改动(分支顺序放在 flush-warnings 分支之后即可,互不遮挡)。

### 1.6 monitor 通道:批次行级预算(alert_budget_process)

**现状锚**:r5 聚合调用 L2829-2833(`_orig_has_alerts = bool(alerts)` L2829;`alerts, _r5_summary = adr.r5_congestion_process(alert_state, alerts, NOW)` L2830;append L2831-2832;`save_alert_state` L2833);批次发送 L2834-2868(notify_sent 判定 + `_rollback_transition` L2864-2868);`elif _orig_has_alerts:` L2869-2870。

**背景**:批次消息整条 subject=`[告警] {N}项计划任务异常` 类别未映射 → 单点 gate 不会碰它;批次内的**行**(每行一个独立异常)才是吸收对象。

**改法**:
1. `adr.alert_budget_process(alert_state, alerts, now, repo, day=None) -> (kept, absorbed)`(新函数;**不写 alert_state**——计数实时读台账,无需状态键):
   - `counts = adr.ledger_day_direct_counts(repo, day)`(新辅助:同 §1.4 计数逻辑,shared 单一实现;台账读不到 → 全 0=全部直发 fail-open)。
   - 逐行:`cat = adr.category_of_line(line)`;None → kept;`counts[cat] < ALERT_BUDGET[cat]` → kept 并 `counts[cat]+=1`(同轮乐观增量 → 同轮第 2 条同类行吸收,镜像「首条直发」);否则 → absorbed(条目 `{"line": line, "category": cat, "key": <derive:行首 task 名 + 行 hash 前 8, 仅用于摘要展示/幂等>, "ts": now}`)。
   - 加强档(拍板后启用):`task_family` 预算(每 task 1/日)作为第二层——同类判完之后,对 kept 行再按 task 分组,超 task 预算的行转入 absorbed。
   - 返回 `(kept, absorbed)`;`_orig_has_alerts` 语义:调用后重新算 `_post_has_alerts = bool(alerts)`(kept),`elif _orig_has_alerts:` L2869 条件改用 `_post_has_alerts`(原语义=「本轮原有过告警但已被聚合接管」,吸收后若 kept 空且 absorbed 非空也要走到该日志分支——implementer 按注释语义改写,行为变化仅日志)。
2. monitor 调用点改 L2829-2832:
   ```python
   _orig_has_alerts = bool(alerts)
   alerts, _absorbed = adr.alert_budget_process(alert_state, alerts, NOW, REPO)
   for _ent in _absorbed:                      # fail-open: defer 失败 → 回批直发
       _r_dg = subprocess.run(
           [sys.executable, str(REPO / "scripts" / "notify.py"),
            _ent["line"][:300], _ent["line"],
            "--defer-digest", "--digest-category", _ent["category"]],
           capture_output=True, text=True, timeout=30, check=False)
       if _r_dg.returncode != 0:
           alerts.append(_ent["line"])
           print(f"[warn] digest defer 失败, 回批直发: {_ent['line'][:80]}", file=sys.stderr)
       else:
           print(f"[budget-absorb] {_ent['category']} 并入当日摘要: {_ent['line'][:80]}")
   ```
   (defer 调用在 save_alert_state **之后**、批次发送 **之前**;absorbed 行从批次剔除 → 批次 subject 的 N=len(alerts) 自然重算。)
3. r5 函数**保留不删**(测试 `scripts/tests/test_alert_denoise_20261001.py` L277-310 引用);monitor 不再调用它 → 在其 docstring 加一行「#245 批2 起由 alert_budget_process 取代(超集);本函数保留供历史测试」。`R2_CONGESTION_SUMMARY_KEY_PREFIX` 的恢复循环 skip(L1837)保留(旧状态键残留兼容)。
4. **摘要 flush 触发**:monitor 尾部、flush-warnings 块(L2978-2987)之后、alert_meter recount(L2989)之前,插同构调用:
   ```python
   try:
       _r_dig = subprocess.run([sys.executable, str(REPO / "scripts" / "notify.py"), "--flush-digest"],
                               capture_output=True, text=True, timeout=120, check=False)
       if _r_dig.returncode != 0 or "未发出" in (_r_dig.stdout + _r_dig.stderr):
           print(f"[warn] digest flush: {(_r_dig.stdout + _r_dig.stderr).strip()[:200]}", file=sys.stderr)
   except Exception as e:
       print(f"[warn] digest flush 异常: {e}", file=sys.stderr)
   ```
   (flush 自身按 §1.5 门控:非 23:25 且无 stale → 静默 no-op,每轮调用安全。)

**行为变化逐条**:
- 批次内类别第 2+ 行:从「随批次邮件/飞书即时发」变成「当日 23:25 摘要出现(或次日 stale 兜底)」;批次消息条数 N 变小。
- 类别首行、未映射行:照旧随批次即时发。
- defer 失败:回批直发(=现状+一行 warn 日志),绝不静默丢条目。
- 摘要消息自身:new = 每日 1 条(23:25 后首轮),进告警群、台账 tier=digest。

### 1.7 恢复闭环 D5:「恢复消息必须出现」

**现状锚**:恢复循环收集 L1834-1897(recoveries append L1875-1884 附近,受 `_recovery_cooldown_ok` L353-362 + RECOVERY_COOLDOWN=6h L370 门控);恢复发送块 L2874-2915(r2_ 过滤 L2883;subject L2888-2892;`subprocess.run` L2903-2915 **无 capture、fire-and-forget**,`--dedup-key schedule_monitor_recovery --dedup-window 21600` L2912)。**病灶(D5,10-09 实证)**:窗口内第二条不同任务的恢复被同 key 6h 窗吞掉(age=11683s 实吞),且 fire-and-forget 无法感知吞没。

**改法(保留 6h 窗作 pacing,但「被吞必有补列」)**:
1. 恢复发送块 L2903-2915 改:`capture_output=True, text=True, timeout=60`;用 `notify_sent`/`notify_state`(monitor 已 L83 `from notify_sent import notify_sent`——再 import `notify_state` 同模块)判三态:
   - `sent` → 清 `monitor_recovery|pending`(若之前积压已随本次带出——本次发送内容=recoveries+pending)。
   - `suppressed`(6h 窗吞)或 `failed`(发送失败)→ 本批 recoveries **并入 alert_state 新键 `monitor_recovery|pending`**(结构 `{"status":"pending_hold","items":[{task,keyword,first_seen}...]}`;事项按 (task,keyword) 去重,已存在不重复)。
2. 发送条件 L2884 改:`if recoveries or _pending:`(pending 每轮随下次恢复发送重试;6h 窗过期后自然带出直发)。发送正文=recoveries+pending 合成;若含 pending 补列,尾加一行「(其中 M 条为早前恢复补列)」。
3. **恢复循环 skip 链**(L1837 区):`if _key.startswith(adr.MERGE_PREFIX) or _key.startswith(adr.R2_CONGESTION_SUMMARY_KEY_PREFIX) or _key.startswith("monitor_recovery|"): continue` —— 防 pending 键被恢复循环误判「未 seen=已消失」翻转/误发。实施时再 grep `alert_state` 全部遍历点确认无其他消费(`purge`/cleanup 各函数)。
4. **当日摘要补列兜底**:monitor 尾部 digest flush 调用前,若 `monitor_recovery|pending` 非空 → 逐条 `notify.py <[恢复] {task} …> <body> --defer-digest --digest-category recovery`;成功 → 从 pending 清该条;失败 → 保留(下轮再试)。摘要正文含 `[恢复补列]` 标注。
5. 结果链:窗口内被吞 → pending → (a) 窗口过期后随恢复直发,或 (b) 当日 23:25 摘要补列出线,或 (c) 摘要发送失败 → 条目保留在 buffer → 次日 stale flush 必出。**三级保证「恢复必出现」,绝无静默吞**(W2:gate 的恢复类消息类别未映射,不受预算影响)。

**已核实**:r2_ 恢复仍被 L2883 静默(自愈类,保持不动);`monitor_recovery|pending` 只在 monitor 内读写(单一写入者),无跨进程锁需求;`save_alert_state` 原子写已有。

### 1.8 W2 契约登记(硬交互)

`scripts/notify_sent.py` `_SUPPRESS_SIGNATURES`(L91-104,现有 7 条=行首锚+行内标记二元组)必须同构追加:
- `[notify][budget] 并入当日摘要`(gate 吸收行)→ `notify_state` 判 `suppressed`(成功且已知,勿判 failed 触发调用方重试)。
- 可选(同构,防后续调试):`[notify][digest] 已并入摘要 buffer`。
**不登记 = 9 个调用方**(check_failed_units/check_s06_freshness/nextday_plan_generator/overfit_monitor/sensenova-proxy-healthcheck/check_data_gap_alerts/nextday_gap_check.py L378/fund_nav/signal_kelly_backtest 等)**会把「被吸收」误判为「未发出」→ notify_rc=1 → 包装层/兜底链路重复告警**(W2 病灶复发)。

### 1.9 测试与负控(§1)

新测试 `scripts/tests/test_245_l2_budget_digest_20261010.py`(pytest,`.venv/bin/python -m pytest scripts/tests/test_245_l2_budget_digest_20261010.py`;mock 渠道=monkeypatch `_send_email`/`send_feishu`/`send_telegram` 为假函数,临时 REPO env 指 tmp_path):
1. category_of / category_of_line 表驱动(台账 10-08 全部 key/subject 样本入表)。
2. gate:预算耗尽的类别第 2 条 → `digested=True`、渠道函数零调用、buffer 一行、`[notify][budget]` 行在 stderr;首条/未映射/exempt(severe=False)/dry_run/台账缺失 → 直发。
3. `_absorb_to_digest` 同日同 key 幂等(buffer 只 1 行)。
4. flush_digest:23:25 前 no-op;23:25 后 1 条 send(参数字段逐字断言 = §1.5 模板);成功后条目清理 + `last_sent_day` written;send 假失败 → 条目保留;二次 flush 同日不重发;stale 次日补发。
5. main() `digested` 早退:不 update_dedup、不 write_alert。
6. `notify_state("[notify][budget] ...")` == "suppressed"(W2 登记生效)。
7. alert_budget_process:7 类表驱动(kept/absorbed 分布);同轮第 2 行同类吸收;defer 失败回批(模拟 returncode 1)。
8. 恢复闭环:模拟 suppressed → pending 写入 → 下轮 body 含补列;digest defer 成功 → pending 清;`monitor_recovery|` skip 断言(恢复循环不误判)。
9. **机检**:`grep -c "digested" scripts/*.py` 核对所有 send() 返回消费点已适配(fail 条件:任何 `results.items()` ok 判定未排除 digested 键)。
**负控(必须全绿,并入 §6 总表)**:首条直发 / 新(未映射)key 直发 / critical+升级档直发 / dry_run 直发 / 台账坏行不崩(fail-open 直发) / defer 失败回批 / 摘要跨日 stale 必出 / 恢复三级链路必出。

## 2. L3c:r2-skip 自愈类任务降 tier(保升级)

**现状锚**(全部已核):常量 `R2_SKIP_CONTINUOUS_THRESHOLD = 3` L619、`R2_SKIP_OBS_WINDOW` L629;r2-skip 块 L1095-1186——计数 L1095-1127,达阈值判定 L1131,告警 key L1136-1137,首告警分支 L1139-1152(`alerts.append(SEVERE...)` L1141-1144 + `alert_state[...]={status active,...}` L1145-1152),已告警 suppress 分支 L1153-1159,未达阈值 prints L1160-1171,纯滞留 L1172-1176,**else 清链=真恢复入口 L1177-1186(不得动)**。warning 先例:_check_resource L1744-1755(`--tier warning --dedup-key … --dedup-window 21600`,capture_output, timeout=30, check=False)。

**标的核实**:`gen_daily_brief` / `fetch_news` 均有 `r2_skip_count` 产出(gen_schedule_stats.py `EXTRA_MARKER_SCANS` L162 起两任务条目 + L1080-1082「无日志分支也补 r2_skip_count」;monitor 侧消费即 L1095)——L3c 标的成立。

**改法**:
1. 常量(插 L619 后):
   - `R2_SKIP_TRANSIENT_TASKS = ("gen_daily_brief", "fetch_news")`(自愈类:上传锁忙多为让路,盘中 30min 一轮,先降 tier)
   - `R2_SKIP_ESCALATE_ROUNDS = 6`(连续 ≥6 轮 ≈90min 仍锁忙 → 升级直发;1.5x~2x 于现阈值 3,与 EXTRA_ROUND_INCOMPLETE 的 1.5~1.7x 裕量口径同族)
2. 分支改造(L1139-1159 区间);伪码(状态机三态,保状态机械与恢复闭环不变):
```python
if _r2_exist is None or _r2_exist.get("status") != "active":
    _is_transient = s["task"] in R2_SKIP_TRANSIENT_TASKS
    if _is_transient and _r2_n < R2_SKIP_ESCALATE_ROUNDS:
        # L3c: 自愈类先 warning(入 30min 聚合缓冲, ≤30~45min 批发; 非静默)
        subprocess.run([sys.executable, str(REPO/"scripts"/"notify.py"),
            f"[告警] {s['task']} R2 上传锁连续 {_r2_n} 轮跳过(自愈类, 延迟提示)",
            (现 L1141-1144 文本 + "(自愈类任务先入聚合; 连续 ≥{R2_SKIP_ESCALATE_ROUNDS} 轮将升级直发)"),
            "--tier", "warning",
            "--dedup-key", f"{s['task']}|r2_skip_warn", "--dedup-window", "21600",
            "--from-prefix", "[告警]"],
            capture_output=True, text=True, timeout=30, check=False)
        print(f"[r2-skip-warn] {s['task']} 连续{_r2_n}轮, 已入 warning 聚合(未达升级阈值)")
        alert_state[_r2_alert_key] = {现 L1145-1152 同构 + "tier": "warning"}
    else:
        # 非自愈类=现行为; 自愈类跨过升级阈值也走这里(=升级必达)
        alerts.append(现 L1141-1144 文本 (+ 自愈类升级时追 "已连续 {_r2_n} 轮, 超升级阈值"))
        alert_state[_r2_alert_key] = {现 L1145-1152 同构 + "tier": "severe"}
else:
    # 已 active 分支内加升级逃逸: 曾 warning、本次 _r2_n >= R2_SKIP_ESCALATE_ROUNDS 且 tier != "severe"
    #   → 走上方 SEVERE append + 状态升级 tier="severe"(否则照旧 L1156-1159 suppress 刷新)
```
   要点:① 升级判定必须**检查 `_r2_exist.get("tier") != "severe"` 逃逸已 active 分支**,否则 warning 期状态 active 会永久挡住升级;② 升级 **不换 key**(state 机 spin 在值内改 tier;`seen_keys_this_run.add(L1137)` 照旧)→ 恢复闭环单键单恢复,无新 key/zhuang 恢复噪音;③ else 清链分支 L1177-1186 一字不动(恢复入口)。
3. 行为变化逐条(§23.7):
   - gen_daily_brief / fetch_news 连续 3~5 轮锁忙:消息从「即时 SEVERE(邮件+飞书+latest.md,tier=critical)」→「warning 入缓冲 → ≤30~45min 聚合批 1 条邮件+飞书 alert 群,tier=warning」。
   - 连续 ≥6 轮(≈90min)未解除:SEVERE 直发一次(升级必达,不受 warning 窗/指纹影响——alerts.append 走批次)。
   - 非自愈类任务(其余全部):逐字节=现状。
   - 恢复邮件:同键同机械(链清 → [恢复]),零变化。
4. **诚实标注**:`flush_warning_batch` 无「自愈则取消」——已入缓冲的条目即使随后自愈也会照发(首版收益=延迟 ≤30~45min + 多条合 1 + 4h 同源指纹窗抑制;取消机制不在本批,避免动 freeze 面),priority doc §2.1 已同款标注。
5. 测试负控:① n=3 时 warning defer 被调用(`-tier warning` 参数逐字断言)、state tier=warning、无 SEVERE append;② n=6 → SEVERE 一次且 tier 翻 severe;③ n=6 后 n=7 → suppress 不重发;④ 非 transient 任务 n=3 → 现 SEVERE 直发零变化;⑤ 链清 → [恢复] 照发;⑥ warning 发送子进程失败(rc!=0)→ 不影响 state(下轮重试语义同 warning 先例)。

## 3. B4-3 收口(三层兜底保留,只去重复段)

设计全文 `docs/ops/1009-real-faults-rootcause-design-20261009.md` §B4-3;行号已按现码重核(设计文 L731-732/L668-706 已漂移)。过渡窗口 dedup 历史合并=**已完成**(closeout 有档,不再实施)。

### 3.1 L2:py/sh 统一 dedup key(推荐 `nextday_gap_check_fail`)

**现状锚**:`nextday_gap_check.py` `_severe_alert` L66-80——cmd L69-72:`[PY, str(SCRIPT_DIR/"notify.py"), subject, body, "--severe", "--from-prefix","[告警]", "--alert-issue",…, "--dedup-key", "nextday_gap_check_gen_fail", "--dedup-window", "3600"]`(L72 键);调用点 L200/L409。`nextday_gap_check.sh` notify 块 L64-73:L69 键已是 `nextday_gap_check_fail`;L66 文案含「本条为包装层兜底重复告警(不同 dedup key 不互吞)」。
**改法**:py L72 键字符串改 `"nextday_gap_check_fail"`(sh L69 不动);sh L66 文案改为「…本条为包装层兜底(py 同 dedup key:py 已发时本条被抑制;py 未发时本条兜底),需人工核查。」
**行为变化**:py 先发(L200 检测) → sh 6s 内同键窗内 suppress(mail 0 发,档 1 封);py 崩/未发(窗未占) → sh 照发(兜底保留);失败方向=不断层。旧键 `nextday_gap_check_gen_fail` 退役,其 dedup 历史无迁移需求(退役键不再被查)。
**测试**:① 模拟 py 已发(sh 手动触发)→ sh 段 [notify] suppress 输出、0 新邮件;② 模拟 py 崩溃 → sh 照发;③ 两条路径键字符串机检一致(grep 断言)。

### 3.2 L3:monitor 双段豁免(复刻 r7/196 先例)

**现状锚**:exit!=0 块 L688-793——`exit_code` 唯一定义 L688(与关键词块同一 for 循环作用域);dedup_key `{task}|exit!=0|{code}` L704;现有 elif 链:R3 L719-728、R7② L736-745、#196② L753-762(`adr.wrapper_channel_alerted(REPO, last_run_str, adr.PATROL_DRIFT_DEDUP_KEY)`)、else L763-793。关键词块:`if s.get("log_anomaly"):` L797 起(dedup_key L802-805, seen add L807, stale L808-816, severity 分叉 L825+)。
**改法**:
1. **adr 新常量**(常量区 L42-111,建议 L62 `PATROL_DRIFT_DEDUP_KEY` 旁):`NEXTDAY_GAP_DEDUP_KEY = "nextday_gap_check_fail"`。
2. **exit 段新 elif**(插 L762 #196 elif 之后、L763 else 之前,逐字复刻 #196② 模板):
```python
elif s.get("task") == "nextday_gap_check" and adr.wrapper_channel_alerted(
        REPO, last_run_str, adr.NEXTDAY_GAP_DEDUP_KEY):
    _ex_ngc = alert_state.get(dedup_key)
    if _ex_ngc is not None and _ex_ngc.get("status") == "active":
        _ex_ngc["last_alerted"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[r8-nextday-gap-suppress] nextday_gap_check exit={exit_code} 但包装器"
          f"通道已为本次运行(last_run={last_run_str})发过告警, monitor 汇总去重")
```
(seen add 已在 L705 无条件完成,无需补;wrapper_channel_alerted 判据=读 `{repo}/data/notify_dedup.json` 的 `nextday_gap_check_fail.last_alerted >= last_run[:16]`,解析失败 fail-open False=L754 同款。)
3. **关键词段跳过**(L797 后、L798 keyword 取数前):
```python
if s["task"] == "nextday_gap_check" and isinstance(exit_code, int) and exit_code != 0:
    print(f"[r8-nextday-gap-suppress] nextday_gap_check log异常关键词但 exit={exit_code}!=0, "
          f"exit 段负责告警, 关键词段去重不复述")
    # 仍 add seen(异常仍在, 防恢复循环误判消失); 不 append
    continue  # 或缩进包裹, implementer 按块结构调整
```
   语义:exit!=0 时关键词段静默(交 exit 段);exit==0 但 log 有异常(吞异常)→ 关键词段照报(真信号保留)。
   注意:跳过时仍应把关键词 dedup_key 加入 seen_keys_this_run(防既有 active keyword key 被误判消失);而 exit 段的 dedup_key 已 L705 add ✓。
**行为变化**:py+sh 任一已发 → monitor exit 段/关键词段均复述 0 封(py 先发时 monitor 全程沉默,1 封);py+sh 都没发(如两脚本同时被杀)→ exit 段判 False 照发(反例保证);**净效果=三层兜底保留、只去重复段**。
**测试**:① wrapper 已发(构造 notify_dedup.json)→ exit 段 suppress、关键词段 skip、无 alerts append;② wrapper 未发 → exit 段 SEVERE 照发;③ exit=0+log 异常 → 关键词段照报;④ `wrapper_channel_alerted` 文件缺失 → False fail-open;⑤ 10-09/10-10 真实样本重放(如有)。

## 4. W1 遗留:NOTIFY_SOURCE 注入(台账 source 字段)

**现状归因**:`_record_ledger` L146-193,source 优先级 L168-169 = 显式 > `NOTIFY_SOURCE` env > `Path(sys.argv[0]).name`;**经 notify.py CLI 触发的子进程 source 恒为 "notify.py"**(argv[0] 是 notify.py),失去调用者身份。修复目标=CLI 家族全部标注真实触发脚本。

**注入点决策(已核 repo_paths.sh 全文)**:
- **sh 侧单点**:`scripts/lib/repo_paths.sh` `resolve_repo()` 内、env 优先块(L73-76)之后加:
```bash
  # #245 批2 W1 溯源: 给本脚本及其全部子/孙进程留下"谁触发的"标记(notify.py 台账 source)。
  # env 优先(外层已注入不覆盖); 本行是 lib「绝不 export」契约的唯一例外(见头注释更新)。
  export NOTIFY_SOURCE="${NOTIFY_SOURCE:-$(basename -- "${caller:-$0}")}"
```
- **契约更新**(lib 头注释 L26-33 契约段追加一行):「唯一例外:NOTIFY_SOURCE — 本 lib 赋值并 export(其用途即跨进程溯源;REPO/GIT_REPO 的 export 语义不受影响)。」
- **覆盖率**:全量核过——**32 个调 notify.py 的 .sh 全部已 source 本 lib**(逐个核过名单:backfill_metrics/backup_db/brief_push_wrapper/check_data_gap_alerts/check_r2_consistency/cloud_unit_patrol(+selftest)/deploy/fund_nav_upload_async/gold_night/intraday_snapshot/kelly_intraday_rerun/monitor_72h/nextday_gap_check/nextday_plan/on_skip_notify/overfit_monitor/push_schedule_stats/r2_upload_async/r2_upload_skip_notify/run_daily_brief/s06_snapshot/schedule_monitor/self_heal/staticdata_backup_async/staticdata_sync/turnover_backfill(+skip_notify)/update_all/update_lab/uptime_check/verify_backup),一处注入全覆盖,无遗漏 sh;monitor 内嵌 Python 调 notify 的子进程也自动继承(notify_source=schedule_monitor.sh)。
- **py 侧兜底**(由 systemd 直接调、自带 notify.py 子进程调用的 py;13 个,各加一行**放各自 `import os` 之后/顶部**):
  `os.environ.setdefault("NOTIFY_SOURCE", os.path.basename(__file__))`
  清单(每个都真核过含 notify.py 子进程调用):
  `agent_inbox_watcher.py`(L88)/`check_data_gap_alerts.py`(L1478/L1536)/`check_failed_units.py`(L270)/`check_preupload_backup.py`(L164)/`check_s06_freshness.py`(L134)/`feishu_missed_fetch.py`(L123)/`gen_daily_brief.py`(L3037)/`sensenova-proxy-healthcheck.py`(L124)/`signal_kelly_backtest.py`(L332)/`nextday_gap_check.py`(L69/L378)/`nextday_plan_generator.py`(L111/L1244)/`overfit_monitor.py`(grep 调用行)/`retry_failed_metrics.py`(L116)
  语义:被 lib-sh 包裹时外层已设 → setdefault 不覆盖(source=sh 任务名);独立执行时取 py 名;两态都可区分。
- **in-process 调用方零改动**:agent_inbox_watcher 等 import notify 直调 send 的,argv[0]=自身 ✓ 已正确;显式 `source=` 参数优先级最高,不受影响。
**验证**:① 本地 `bash -c 'source scripts/lib/repo_paths.sh; resolve_repo scripts/deploy.sh; echo "$NOTIFY_SOURCE"'` → `deploy.sh`;② 嵌套:`NOTIFY_SOURCE=outer.sh` 已设 → 仍 `outer.sh`(env 优先);③ 云上上线后在台账观察 1-2 天:`source=="notify.py"` 行占比应→0,非空率 100%;④ 回归:确认注入后未改变任何现有 env 变量可见性(只多 NOTIFY_SOURCE 一个)。
**注意(诚实标注)**:warning 批(flush_warning_batch)发送时 source 归因=flusher 进程环境(schedule_monitor.sh),非 prime 入队者(defer_warning payload 无 source 字段,不在本批改);handler 恢复批同理沿用发送进程 env。

## 5. 改点总表(文件:行号 → 改动;行号=10-10 基准)

| # | 文件:行 | 改动 | 件 |
|---|---|---|---|
| 1 | scripts/alert_denoise_rules.py 常量区 L42-111(候选插点 L62 旁) | 新增:`ALERT_BUDGET = {unit:1,r2:1,data_gap:1,gap_check:1,deploy:1,fund_nav:1,kelly:1}`、`NEXTDAY_GAP_DEDUP_KEY="nextday_gap_check_fail"` | L2/L3/B4-3 |
| 2 | adr 新增函数(放 wrapper_channel_alerted 附近) | `category_of(key,subject)`、`category_of_line(line)`、`ledger_day_direct_counts(repo,day)`、`alert_budget_process(alert_state,alerts,now,repo)` | L2 |
| 3 | adr `r5_congestion_process` L577-624 | 不删;docstring 加「#245 批2 起 monitor 侧由 alert_budget_process 取代」 | L2 |
| 4 | scripts/notify.py 常量区 L249 后 | `ALERT_DIGEST_FILE`/`ALERT_DIGEST_LOCK_FILE`/`ALERT_DIGEST_STATE_FILE`/`ALERT_DIGEST_HM` | L2 |
| 5 | notify.py `send()` L1111-1118 | 加 kwarg `budget_exempt=False` | L2 |
| 6 | notify.py `send()` L1149-1154 之间 | gate(类别+台账计数+吸收/直发),打印 `[notify][budget]` | L2 |
| 7 | notify.py 新私有函数 | `_budget_today_count`、`_absorb_to_digest`(复用 `_append_jsonl` L1560/_parse_buffer_lines L2021/_stable_rid L2009) | L2 |
| 8 | notify.py `flush_digest()` 新函数(放 flush_warning_batch L2036 附近) + argparse(插 L2354-2358 旁) | `--flush-digest` / `--defer-digest` / `--digest-category`;send 参数模板=L2150-2153 同构(ledger_tier="digest") | L2 |
| 9 | notify.py main() L2539-2544 后 | `if results.get("digested"): return 0`(插 L2545 前) | L2 |
| 10 | notify.py send_tiered critical 分支 L2519 附近 | `budget_exempt=True` | L2 |
| 11 | notify.py main() L2302-2310 区底层导入 | `import subprocess` 已有否?`flush_digest` 复用现有;无则加 | L2 |
| 12 | notify_sent.py `_SUPPRESS_SIGNATURES` L91-104 | 追加 `[notify][budget]` 等新抑制行(§1.8) | L2 |
| 13 | schedule_monitor.sh 常量区 L619 后 | `R2_SKIP_TRANSIENT_TASKS`/`R2_SKIP_ESCALATE_ROUNDS=6` | L3c |
| 14 | schedule_monitor.sh r2-skip 块 L1139-1159 | 三态改造(§2) | L3c |
| 15 | schedule_monitor.sh exit!=0 块 L762-763 之间 | 新 elif `nextday_gap_check` + wrapper_channel_alerted(§3.2) | B4-3 |
| 16 | schedule_monitor.sh 关键词块 L797 后 | `nextday_gap_check` 且 exit!=0 → skip(仍 add seen)(§3.2) | B4-3 |
| 17 | schedule_monitor.sh L2829-2832 | 替换为 alert_budget_process + defer 循环(§1.6) | L2 |
| 18 | schedule_monitor.sh L2884-2915 恢复块 | capture + notify_state 三态 + pending(§1.7) | L2 |
| 19 | schedule_monitor.sh 恢复循环 L1837 | skip 链加 `monitor_recovery\|`(§1.7) | L2 |
| 20 | schedule_monitor.sh L2978-2987 后 | digest 补列 defer + `--flush-digest` 调用(§1.6/1.7) | L2 |
| 21 | scripts/nextday_gap_check.py L72 | 键 `nextday_gap_check_gen_fail`→`nextday_gap_check_fail` | B4-3 |
| 22 | scripts/nextday_gap_check.sh L66 | 文案改口径(§3.1) | B4-3 |
| 23 | scripts/lib/repo_paths.sh L73-76 后 + 头注释 L26-33 | NOTIFY_SOURCE export(唯一例外)+ 契约更新 | W1 |
| 24 | 13 个 py(§4 清单) | `os.environ.setdefault("NOTIFY_SOURCE", os.path.basename(__file__))` | W1 |
| 25 | scripts/tests/test_245_l2_budget_digest_20261010.py | 新增(§1.9);同步更新 test_alert_denoise_20261001.py(若 r5 调用点变化) | L2 |

发版纪律(§5.4⑥/§14/§23.7):本批不动「AI 推荐/降亏过滤」默认组合 → **不升基准版本、不 bump 前端**;但改了告警冻结面行为 → ①实施前须确认用户在 #245 批2 的单独点头(priority doc 已标「会改已发布行为 ⇒ 需用户单独点头」;主控核实拍板状态);②public 仓库 push 避盘后时点;③上线后 3 天观察台账:非 notify.py source 占比、digest 条数、恢复补列是否出线。

## 6. 「真故障仍会报」负控清单(总,实施自验+reviewer 复核共用)

| # | 负控 | 断言 | 归属 |
|---|---|---|---|
| N1 | 类别当日首条 | 空台账/计数 0 → 直发(非吸收) | L2 |
| N2 | 未映射 key | category_of=None → 直发(未知新通道首报不吞) | L2 |
| N3 | critical/升级档 | send_tiered(critical)/196 升级豁免 → 直发 | L2 |
| N4 | 吸收失败 fail-open | buffer append 异常 → 直发 | L2 |
| N5 | 台账坏行 | JSON 坏行跳过、计数不崩 | L2 |
| N6 | defer 失败回批 | monitor defer rc!=0 → 行回批直发 + warn 日志 | L2 |
| N7 | 摘要必出 | 23:25 后首轮 1 条;发送失败条目保留;跨日 stale 必出 | L2 |
| N8 | 恢复必出(D5) | suppressed/failed → pending → (窗口过直发 / 当日摘要补列 / 次日 stale)三路必出 | L2 |
| N9 | dry_run 只读 | dry_run 不写台账/buffer/dedup/lastet | L2 |
| N10 | L3c 升级 | 连续 ≥6 轮 → SEVERE 一次(逃逸 warning-active 状态) | L3c |
| N11 | L3c 非标的零变化 | 非 transient 任务行为逐字节=现状 | L3c |
| N12 | B4-3 三层兜底 | py 发→sh 抑制;py 崩→sh 发;两者都没→monitor exit 段发 | B4-3 |
| N13 | B4-3 关键词段 | exit==0+log 异常 → 照报(不误吞) | B4-3 |
| N14 | W1 覆盖 | NOTIFY_SOURCE 注入后台账 source 非 notify.py(上线观察) | W1 |
| N15 | 总开关回滚 | `ALERT_BUDGET_DISABLE=1` → 全链回现状(逐字节) | L2 |

## 7. 诚实标注与拍板项

**拍板项(实施前需主控/用户确认)**:
1. §0.3-1 口径:每类别首报(替代每 key 字面) —— 建议按本规格。
2. §0.3-2 L5 口径:事件日是否纳入 P90 + 是否首版带 task_family 加强档 —— 数字推演已在 §1.3;建议首版保守+第 1 周 L5 数据定档。
3. #245 批2 用户单独点头状态(priority doc 要求)。

**诚实标注(已知边界,不隐瞒)**:
- 预算值/预期条数为 10-08 单日样本推演,非实测;plan §7「6~7 条/事件日」为更宽吸收面推演;终值以 L5 实测为准。
- 摘要时点 23:25 之后的吸收条目:当日已发摘要后新增的 → 次日 stale flush 带出(有延迟,不丢);已列 §1.5。
- L3c 首版=延迟+聚合+指纹窗,无「自愈则取消」(§2-4)。
- warning 批 source 归因=flusher 环境(§4 末)。
- digest 消息计入告警群 1 条(L5 口径「摘要算 1 条」;merged_count 在台账供 alert_meter 显示并入数,tier=digest 不计 direct)。
- `alert_meter.py` L272-290(cmd_week 目前仅均值)加 P50/P90/`--budget` 属 L5 件,已并入 priority doc 排序(不在批2 四件内,建议紧随批2 上线以便调档)。

**已完成前置(不再实施,防重复开发)**:L3e 单树化(notify.py L97 已 env 优先,云上生效);过渡 dedup 历史合并(closeout 有档,两树终态=运行树保守覆盖)。

