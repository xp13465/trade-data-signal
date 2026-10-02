# reviewer 独立审查报告: feat/harden-alerts-20261002(2026-10-02)

分支 `feat/harden-alerts-20261002`(commit `9b8d7374c` + `93f257bb7`),base = main@`887664cdd`。
审查人: reviewer agent(独立,不看实施报告先验,只读不改)。报告评审口径按 role-reviewer §10(trace/verifier + 置信度过滤)。

## 总体判定: PASS(有条件)

- 三条改动面(fapi131 / #132 六处 fail-loud / #151 不改代码决定)均核实成立,未发现必现 bug 或行为回归。
- 「有条件」两点:① #151 证据链有一条表述精度问题(见 F1),不影响最终决定但需知悉;② #132 在「磁盘满且 notify_dedup.json 不可写」的极端场景 dedup 会 fail-open 重发(聚合而非逐封,见 F2),属项目既有「宁多勿漏」容忍范围。

---

## ①【最高优先】#151 证据链: 成立(一条表述需精度修正)

**结论: implementer 推翻主控「假失败」定性的证据链成立,「不改代码、保留强判失败」的决定正确。**

### 证据(trace: 全部本审查人独立验证)
1. **Worker /data/*.json 全部 R2 优先**(非只大 JSON): `worker/headers.js` `dataRewriteHandler`(L176-260)= R2 命中即服务 R2 对象,仅 R2 404/报错才回退 ASSETS。memory `cf-workers-large-json-404-r2-fallback` 的「大 JSON 404 才走 R2」旧结论已在 memory 自述「已过时」(阶段4a 后 /data/ rewrite 全走 R2,本文档复核一致)。
2. **线上实测 ETag 逐位一致**: `curl 'https://ss.fx8.store/data/nextday_plan.json'`(浏览器 UA,裸 curl 会 307)→ HTTP/2 200, `etag: "dafa56937f64d08083df3262acbad05f"`; `curl .../r2/data/nextday_plan.json`(r2ProxyHandler 直读同一 R2 key `data/nextday_plan.json`)→ 同 ETag 同内容(333 字节, date=20260930 / next_trading_day 20261008)。证明主站 `/data/` 实际从 R2 读。
3. **上传管线**: `scripts/nextday_plan_generator.py` L1161-1202 `upload_r2.py upload-data-files nextday_plan.json`(R2 key `data/nextday_plan.json`),失败/超时 → `_severe_alert` + `r2_rc=1`(强判失败,即被保留下来的逻辑)。`check_data_integrity.py` L1953 `_fetch_r2_json("nextday_plan.json")` 把线上 R2 当「生产权威」。
4. **结论链闭合**: R2 上传失败且内容有变化 → 主站服务 R2 旧 key = 线上停滞,deploy/ASSETS 不生效(除非 R2 该 key 404)。

### 表述精度修正(不推翻决定)
- implementer 报告 §1「deploy 只更新 ASSETS,worker 仍优先 R2 → deploy 兜不住」**不完全准确**: `scripts/deploy.sh` L656 的 `upload-all-data` 会把 `static-site/data/*.json`(nextday_plan.json **不在** `_is_all_data_excluded` 名单)全部刷到 R2 `data/` 前缀 —— 即 deploy 也会刷新 R2 里的 nextday_plan。但 deploy 跑在盘后时点(15:35/16:00/17:50/20:35/22:00),而 22:30 生成失败后最近一次 deploy 最早是次日盘后 → **次日早盘(09:30-10:00)执行窗口主站仍是旧计划**。故「deploy 兜不住(及时性)」结论不变,只是措辞应从「不更新 R2」改为「来不及覆盖次日早盘窗口」。

### 「当次未造成影响」与「R2 失败会真影响线上」二者共存,不矛盾
- **当次(09-30 22:30)**: 线上文件内容 == 云上生产仓(md5 逐位一致,台账 #151 取证)——说明 R2 上最终是同内容:要么 PUT 在客户端 300s 看门狗杀进程前已落地(跨境毛刺常现:PUT 成功但响应/keep-alive 悬挂),要么后续某次通道(upload-all-data)幂等刷新。故当次确实「零可见影响」。
- **机制层**: /data/ 读取路径 = R2 优先(证据 1/2),内容变化时 R2 上传失败 = 主站旧计划持续到下一次成功 R2 上传。两者共存的前提正是「线上内容本身只能靠 R2 上传路径到达」—— 若 R2 真不影响线上(走源站),线上内容一致就不需要 R2 上传,与 Worker 代码 + ETag 证据矛盾。
- **结论**: 主控原「假失败」定性错在机制层(以为小 JSON 不经 R2),对当次零影响的现象描述是对的;implementer 修正的是机制层,决定(保留强判失败)正确。

### 附带观察(非本单改动范围)
- `nextday_plan_generator.py` 告警文案写「线上 sss/s 备站可能滞后」,按 R2 优先机制**主站同样滞后**——文案低估影响面。可选优化(另开任务):文案改为「线上主站/备站可能滞后」;或上传后对账(uid GET ETag == PUT ETag,失败重试一次再判失败,不缩减可见性)——与 implementer 报告建议一致。

---

## ② #132 六处 fail-loud: dedup-key 独立无碰撞,24h window 符合惯例,不构成轰炸

### 逐项核实(trace: 每处 helper 命令构造 + 全仓 key 扫描 + 独立自测复现)
- **六个 dedup-key 全部独立,无碰撞**: `r4_state_write_fail` / `data_gap_state_write_fail` / `anomaly_dedup_write_fail` / `feishu_cursor_write_fail` / `healthcheck_state_write_fail` / `agent_inbox_state_write_fail`。全仓 grep 确认六个 key **仅各自文件内使用**(无与其他脚本共用 key 串味)。
- **参数规格一致**: 均 `[sys.executable, notify.py, subject, body, --tier warning, --from-prefix [告警], --dedup-key <独立key>, --dedup-window 86400]`, `subprocess.run(timeout=120)`, 发送异常 catch 后打 stderr 不阻塞主流程。
- **符合既有惯例**: 参照先例 `scripts/retry_failed_metrics.py._notify_count_file_write_fail`(2026-10-01,同样 warning + notify + dedup + DRY_RUN env);86400 窗口与既有 key(`nextday_plan_{T}` 等)同档;notify.py 的 `--tier`/`--dedup-key`/`--dedup-window` CLI 在 main(`887664cdd`)已支持,合并后直接可用。
- **保留真故障判别维度(memory `alert-denoise-keep-fault-discriminator`)**: 数据级故障仍走原通道不升级(六处均只 warning);写失败是本地基础设施故障(权限/磁盘),与数据源故障判定维度分离。✓
- **agent_inbox_watcher**: 全局计数阈值 5,前 4 次仅 log,第 5 次才 notify,发送后复位;常驻 watcher(5s/轮)瞬态抖动不报警。✓
- **R4 无递归风险(重点核查过)**: notify.py 主流程在 `dedup_key == "staticdata_backup_fail"` 时才调 `adr.r4_staticdata_grade`;新 helper 起的子进程 key=`r4_state_write_fail` ≠ 该值 → 子进程不会再次进入 R4 分支 → 无 fork 炸弹。schedule_monitor.sh heredoc 只用 r1/r2/r3 不用 r4,无跨进程同 key 双发。
- **轰炸边界**: 各 key 24h dedup 至多 1 封/天;warning 走 30min 聚合批发(flush_warning_batch 合并成一封)。**唯一 caveat**: 若故障本身 = 磁盘满使 `notify_dedup.json` 不可写 → check_dedup fail-open(不 suppress)每轮重发,但走聚合批 = 每 30min 一封里 N 条重复行,非逐封轰炸;属 notify.py 既有「宁多勿漏」设计语义,可接受(此时正是需要可见性的时候)。

### verifier(独立复现)
- 命令: `/tmp/harden-review/selftest_rev.py`(mock `subprocess.run` 拦截真发 + 文件组件阻断写失败路径,六处逐一触发)
- 结果: **PASS: 六处 fail-loud 全部复现,dedup-key + 86400 + tier=warning 断言全过**(含 watcher 前 4 次不发、第 5 次发、复位后重新计数)。
- 另: `python3 -m py_compile` 7 个改动文件全 PASS;`check_data_gap_alerts.self_test()` 分支版本 rc=0(含 A6-F2 原子写失败断言)。

---

## ③ 自测暴露的两处缺陷修复: 正确,无行为回归

1. **`alert_denoise_rules.py` 顶层补 `import sys` + `from pathlib import Path`**: base 版本仅 `import json`/`from datetime import...`(grep 证实 base 无 sys./Path( 引用);新 helper `_notify_r4_state_write_fail` 用 `sys.stderr` 和 `Path(__file__)` —— 不补则触发即 NameError。修复=纯增 import,对既有函数零影响。✓
2. **`check_data_gap_alerts.py` mkdir 移入 try 内**: 原 mkdir 在 try 外,目录创建失败会逃逸(不再 fail-loud,且可能中断调用方);移入 try 后 mkdir 失败与 dumps/write/replace 失败同路径(stderr + notify)。控制流变化: 原「mkdir 失败 → 异常逃逸」→ 现「mkdir 失败 → fail-loud」,严格向好。self_test 的 A6-F2 断言(写失败保留旧文件 + tmp 不残留)分支版本通过,验证 tmp.unlink(missing_ok=True) 在父目录不存在时仍安全。✓

---

## ④ 报告 §7 同类面清单判据: 站得住;补充 1 处低置信观察项

### 判据本身
「去重/状态/游标/计数文件写失败被静默(无 stderr 无告警)」= 同族 —— 与 #132 修改的六处同型(防静默机制本体的持久化文件写失败)。判据合理,清单各条我独立复核:
- `sensenova-rotate-proxy(_kimi).py _save_cooldown`: 实测 `except Exception: pass` **真静默**(无 stderr/log)。报告判「观察项(非本单)」—— 理由(cooldown 只影响限流频率不丢功能;2026-09-07 事故后设计,写失败 fail-open 属有意为之)站得住,且已上报主控裁量。✓(按 §10.3#5「用户故意保留的行为」口径处理正确)
- `gen_daily_brief.py run_log`: 实测 L2285-2312 `except Exception: pass` 真静默,但属「运行历史日志 append」,失败不影响当日产物 → 「不判」合理。✓
- `check_signals.py FADE 状态写`: 无 except 直抛 = 非静默对照 ✓
- `upload_r2.py marker/_save_state`: 无 try 包覆,失败崩溃可见(非静默对照)✓
- `feishu_ws_listener _mark_autodone/_mark_forwarded`: 只 log → 观察项,已上报 ✓
- `agent_inbox_watcher sweep 清理失败`: 只 log → 清理类非关键状态,不判可接受 ✓

### 补充观察(低置信,约 40,不进 FAIL)
- `feishu_missed_fetch.py` L285-300 **单条消息落盘失败**(inbox 写 jsonl): 只 `log()` + `skipped += 1`,无 notify。但它有 log(非完全静默)、下轮会重拉(消息未持久化,游标未推进则重取),且是数据落盘非去重/状态文件 —— 按判据不算同族。列此仅为完整性,不需本单处理。

---

## ⑤ §23.2 三铁律 / §23.5 落档 / 分级

- **同类错误面清单**: 报告 §7 有清单(六处全修 + 2 类观察项 + 3 类非同族对照),判据和逐条结论我全部复核过(见 ④)。✓
- **逐项自测真跑过**: implementer 声称的「6/6 + 3/3」可复现 —— 我用独立 harness 复现 6/6,用 stub `_api` 复现 fapi131 四态(A pagination 缺失→unknown / B total=0→empty / C total>0 正常翻页 / D total 字段缺失→unknown)全 PASS;`check_data_gap_alerts.self_test()` rc=0;py_compile 7/7。✓
- **fapi131 下游影响面**: `fetch_zt_fallback` 唯一消费方 `app/backfill_lianban.py`(L54 import,L131 调用)。其空 df 处理(记 gap、不写值、禁止猜 0)对 `len(df)==0` 统一处理,与 reason 字符串无关 → 改 reason 不影响下游写库行为。唯一连带: backfill_lianban 注释 L126/L271 描述的「C 类契约异常 → 误报 empty(真0)」已随本次修复不再发生(现报 unknown),注释与代码现状轻微脱节 —— 文档性 nit,不阻塞。
- **§13 前端**: 无前端改动(diff stat 仅 app/collector/fapi_fallback.py + 6 scripts + 报告)。✓
- **§21 公示 / §22 一致性**: 无算法改动(fapi131 是 reason 字符串语义,非评分/权重/分段函数)、无展示位/数据产物改动 → 无公示同步、无三处一致性动作需求。✓
- **改动分级**: fapi131 = **B 级②**(逻辑分支 + 单消费方 backfill_lianban,无轮询/事件引用,有隐藏影响面但单点);#132 六脚本 = **B 级③**(云上定时任务告警行为,广涉及面 → 本次即完整 review)。均非 C 级(不动数据产物/SQL/DB)。
- **对线上告警行为影响**: 正常路径(状态写成功)行为零变化;仅真实写失败时新增独立 warning(24h dedup + 聚合批发 + watcher 阈值5)→ 无误报轰炸、无信号淹没。✓

---

## 低分项已滤
共滤 2 项低分(<80): ① fapi131 reason 字符串与 backfill_lianban 注释轻微脱节(75 分边缘,列入正文 nit);② feishu_missed_fetch 单条消息落盘失败无 notify(40 分,见 ④ 补充观察)。均不构成阻塞。

---

## 复现命令(供实施/主控反查)
```
# 六处 fail-loud 复现(本审查用)
python3 /tmp/harden-review/selftest_rev.py        # mock 拦截真发, 断言 dedup-key/86400/warning
python3 /tmp/harden-review/scripts/check_data_gap_alerts.py --self-test   # 需 sys.path 含 trade/scripts 与 trade
# 线上 ETag 对账(只读)
curl -s -o /dev/null -D - -H 'User-Agent: Mozilla/5.0' 'https://ss.fx8.store/data/nextday_plan.json'   # etag dafa5693...
curl -s -o /dev/null -D - -H 'User-Agent: Mozilla/5.0' 'https://ss.fx8.store/r2/data/nextday_plan.json'  # 同 etag
```
