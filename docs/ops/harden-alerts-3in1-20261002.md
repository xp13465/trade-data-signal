# harden-alerts 三合一:告警/异常处理健壮性加固(2026-10-02)

分支 `feat/harden-alerts-20261002`,三个任务一次收口:
1. **#151**:nextday_plan R2 镜像上传失败不判整个任务失败 —— **核实后结论反转,未改代码,上报主控**
2. **fapi_fallback:131**:pagination 缺失误报 `empty(真0)` → 区分 `unknown`
3. **#132 六处同族静默点**:异常被吞 → fail-loud(参照 `scripts/large_json_excludes.py` 拒绝写回风格)

---

## 1. #151 nextday_plan R2 上传失败:核实结论 = 有真实影响,不降级,不改

任务要求先核实 `upload_r2.py upload-data-files` 对主站是否有影响;若核实结果相反(确实会让线上停滞),**停下上报主控,不要改**。

**核实结论:确实会让线上停滞。**

证据链:
- `worker/headers.js` dataRewriteHandler 对 ALL `/data/*.json` **R2 优先**:若 R2 有旧 key,deploy 只更新 ASSETS、R2 里仍有旧版时,worker 读 R2 旧版,线上主站**不更新**。
- 实测:线上 `ss.fx8.store/data/nextday_plan.json` 的 ETag 与 `sslss/R2 /r2/data/nextday_plan.json` 一致(均为 `dafa5693...`),证明主站当前就从 R2 读。
- nextday_plan.json 落 `dataCacheTtl=3600s`(LOW_FREQ)edge cache。

所以 #151 若按「超时/失败只 log+降级」处理,结果 = R2 上传失败时线上一直显示旧版计划,deploy 兜底其实**兜不住**(deploy 只更新 ASSETS,worker 仍优先 R2)。当前 `_severe_alert + r2_rc=1 → 整个任务 rc=1` 的强判失败是**正确防御**,不是误伤。

**决定:不改代码,原逻辑保留。** 建议后续(另开任务)优化方向:上传后对账校验(uid GET 返回 ETag == PUT ETag),失败重试一次再判失败——不缩减可见性。

## 2. fapi_fallback:131 pagination 缺失 ≠ 真 0

- 文件:`app/collector/fapi_fallback.py` `fetch_zt_fallback`
- 改前:`total = int(pag.get("total") or 0)` → 服务端缺 `pagination`/`total` 字段时 total=0,reason 报 `fapi xxx empty(真0) date=...`(语义误导:以为真无数据,实际是不知道)
- 改后:
  - `pagination` 缺失或 `total` 为 None → **直接返回空 df,reason=`fapi {r} unknown(pagination missing) date=...`**(语义=fetch 到响应但没有分页信息 = 字段缺失)
  - `total == 0` → **reason=`fapi {r} empty(真0) date=...`**(服务端明确 total=0,休市日/真 0 池)
  - `total > 0` → 走原翻页逻辑不动
- **未改任何取数逻辑**:翻页/末页兜底 batch<200/MAX_PAGES 全保留
- 下游 `app/backfill_lianban.py` L121-131 已注释记录 C 类契约异常(缺 pagination → 误报 empty),改后 reason 字符串可分辨、告警不再掩盖「服务端响应异常」类故障

自测(三态):
- A pagination 缺失 → `unknown(pagination missing)` PASS
- B total=0 → `empty(真0)` PASS
- C total>0 无 pages → 正常返回 1 行,不误判 unknown PASS

## 3. #132 六处同族静默点 → fail-loud

统一模式:状态/去重/游标等**防静默机制的持久化文件**写失败时,不再只 `except: pass` 或只打 stderr,而是**调 notify.py 发独立 warning(dedup key + 24h window)**。
参照 `scripts/retry_failed_metrics.py` 的 `_notify_count_file_write_fail` 先例。

⚠️ 均不升级 severe:写失败是本地基础设施故障(权限/磁盘),数据级故障仍走原严重通道,**不制造「可容忍抖动升级成告警」**;独立 warning + dedup 24h = 同一根因最多 1 封/天,不刷屏。

| # | 文件/位置 | 改前静默行为 | 改后行为 | 为何不算制造噪音 |
|---|---|---|---|---|
| ① | `scripts/alert_denoise_rules.py` R4 状态写(L246 附近) | `except Exception: pass`? 原为仅打日志,连续天数丢失时 SEVERE 阈值(连续≥2天)永远到不了 = **防静默机制本体静默** | stderr 打「状态落盘失败(连续天数计数可能丢失)」+ notify warning `r4_state_write_fail`(dedup 24h) | 只有连续天数计数真的写失败才发 1 封/天;正常心跳追平路径不触 | 
| ② | `scripts/check_data_gap_alerts.py` `_save_state_atomic` | 写失败打日志后静默返回,dedup 状态丢失 → 同告警每轮重复轰炸;基线状态丢失 → 缺口误报 | 追加独立 warning `data_gap_state_write_fail`(dedup 24h);mkdir 移入 try 内一并 fail-loud | 写失败本身就是故障(权限/磁盘),24h 内最多 1 封,不会跟业务告警重复 |
| ③ | `scripts/detect_intraday_anomaly.py` 去重写(L242-250) | 写失败静默,当日 dedup 失效 → 盘中异动每 30min 轮重复发 | stderr「写去重文件失败(异动告警将重复轰炸)」+ notify warning `anomaly_dedup_write_fail`(dedup 24h) | 24h 内最多 1 封;否则是 8~13 封重复盘中异动,更吵 |
| ④ | `scripts/feishu_missed_fetch.py` `_save_cursor` | 游标写失败只 log,下次从旧位置重拉 → 重复补拉/漏补 | log + notify warning `feishu_cursor_write_fail`(dedup 24h) | 补拉游标是最多一天一次的低频任务,1 封/天不扰;漏补飞书消息才是真损失 |
| ⑤ | `scripts/sensenova-proxy-healthcheck.py` `_save_state` | 状态写失败只 stderr,dedup 状态丢失 → fired 每次轮当「未 firing」反复告警 | stderr + notify warning `healthcheck_state_write_fail`(dedup 24h) | 5min 一轮,写失败会导致 288 封/天重复告警,1 封/天是降噪不是噪音 |
| ⑥ | `scripts/agent_inbox_watcher.py` 6 处插桩(touch_heartbeat/bump_retry/_touch_failed/failed_marker/sync_git_refs ready/_write_blocked) | 写失败只 log,去重/重试状态丢失 → codex 请求无限重试烧额度/同请求重复处理,无可见性 | **计数达 5 次**才发 notify warning `agent_inbox_state_write_fail`(dedup 24h) + stderr 每跳 | 常驻 watcher 5s 一轮,单次瞬态抖动不报警;持续写失败(真正故障)最多 1 封/天 |

### 各 helper 规格
- 均走 `subprocess.run([sys.executable, notify.py, subject, body, --tier warning, --from-prefix [告警], --dedup-key <独立key>, --dedup-window 86400], timeout 120)`
- notify 发送本身失败(网络/超时)时打 stderr 不阻塞主流程(告警通道故障不再叠加)
- `agent_inbox_watcher._notify_state_write_fail` 内 `import subprocess`(模块级不 import,防 watcher 启动额外开销)

## 4. 自测(6 处 fail-loud + fapi131)

- `python3 -m py_compile` 7 个改动文件全部 PASS
- 6 处 fail-loud 自测:`/tmp/selftest_harden132.py` —— mock `subprocess.run` 拦截真发,强制只读目录触发写失败,**6/6 PASS**,各点断言 dedup-key 出现在 notify 命令参数中
  - 自测暴露 2 个真实缺陷并已修:
    1. `alert_denoise_rules.py` 模块顶层缺 `import sys`/`import Path`(原 L181 也引用 `sys.stderr`,触发即 NameError)→ 补顶层 import
    2. `check_data_gap_alerts.py` `_save_state_atomic` 的 `mkdir` 在 try 外,目录创建失败会逃逸未 fail-loud → mkdir 移入 try 内
- fapi131 三态自测 `/tmp/selftest_fapi131.py`:**3/3 PASS**

## 5. 复现
- fail-loud 六处复现:把对应状态文件父目录 chmod 000 → 跑脚本 → 预期 stderr 醒目标记 + notify 收到 dedup-key 告警
- fapi131:对 `fetch_zt_fallback` 注入无 pagination 响应 → reason 含 `unknown(pagination missing)`

## 6. commit 划分
- commit 1(fapi):`app/collector/fapi_fallback.py` —— fapi131
- commit 2(#132):6 个 scripts 文件 —— 六处 fail-loud
- #151 未改代码,无 commit

## 7. 同类错误面清单(grep 全仓 + 抽查)

判定标准:**「去重/状态/游标/计数文件写失败被静默(无 stderr 无告警)」** = 同族静默点。

| 位置 | 现状 | 判定 |
|---|---|---|
| `sensenova-rotate-proxy.py` / `sensenova-rotate-proxy-kimi.py` `_save_cooldown` | docstring 明写「写失败静默不阻断」,cooldown 写失败不报 | **观察项(非本单)**:2026-09-07 事故后设计;cooldown 只是冷却状态,写失败只影响限流频率不丢功能;若要 fail-loud 需逐点评估,另开任务 |
| `gen_daily_brief.py` L2285-2310 run_log | `except Exception: pass`(运行日志 append 失败) | **不判**:日志类非关键状态,写失败不影响当日结果 |
| `check_signals.py` L264 FADE 状态写 | FADE_NOTIFIED_PATH 写失败直接抛(无 except) | **非静默对照**:已 fail-loud,无同族 |
| `upload_r2.py` 多处 | 上传失败走 `_save_state` 失败标记区(非静默),marker 写失败有 stderr | **非静默对照** |
| `feishu_ws_listener.py` `_mark_autodone` L371 / `_mark_forwarded` L538 | 去重 jsonl 写失败只 log | **观察项**:与 feishu 补拉联动,listener 是另一个任务域;低频影响(重启后才重拉),已在 feishu_missed_fetch 侧 fail-loud,listener 侧可后续对齐 |
| `agent_inbox_watcher.py` sweep 清理失败 / transition OSError | 只 log | **不判**:清理类非关键状态,保留原样 |

结论:六处点名静默点全修;另有 2 处「观察项」(rotate-proxy cooldown ×2、feishu listener autodone/forwarded)——未在本单扩大改动范围(超出点名范围,且需逐点评估是否值得 fail-loud),**上报主控**裁量是否另派任务。

## 8. 影响面与回归
- 不在取数链路改动(fapi131 明确要求不改取数逻辑;仅 reason 字符串区分未知/真0 两种出口)
- 不在前端/数据产物(#132 全部是 scripts 告警/状态文件路径,无 static-site 产物、无 R2 上传、无页面展示)
- 无 §21 算法公示点、无 §22 数据一致性展示位、无 §23.1 README 需求(未引用外部项目)
- 定时任务:每天运行 bake 链 script 脚本(19:00 后 / 24h / 30min),非盘中实时写盘路径;不动交易数据