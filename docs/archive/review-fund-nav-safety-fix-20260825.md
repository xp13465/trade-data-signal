# #11 场外基金净值全链 codex 外部 review 三件必修修复报告(+第四件恶性循环根治+第五批同款根治 etf_hist/fund_score/etf_score_list)

> 来源:codex 外部 review `/tmp/codex-reports/claude2codex-20260825-001.json`(verdict=FAIL)
> 范围:三件必修(critical ×1 + high ×2)+ 主控补充第四件(upload-fund-nav 恶性循环,今日生产告警实证);medium/low 各项未动,见文末「上报待拍板」
> 实施日期:2026-08-25

## 复现

```bash
# 三件改动自验(py_compile + bash -n):
cd /Users/linhuichen/code/trade
.venv/bin/python -m py_compile scripts/export_fund_nav.py scripts/check_data_integrity.py && bash -n scripts/update_all.sh

# 畸形 case 自验(check_fund_nav 9 case + 原子写中断 3 场景):
.venv/bin/python /tmp/t_fundnav.py          # ALL_PASS=True(临时脚本,内容见本报告§自验)

# 精确 kill 中断自验(半截 .tmp 残留 + 最终文件完好):
.venv/bin/python /tmp/t_kill3.py            # PRECISE_KILL_PASS

# 硬闸门两分支自验(桩命令模拟导出失败/成功):
bash /tmp/t_gate.sh                         # 失败→跳过rsync+upload+CRITICAL告警;成功→正常放行

# 第四件断点续传四场景自验(mock s3_request):
.venv/bin/python /tmp/t_ckpt.py             # T1中断checkpoint落盘 T2续传剔除已传 T3增量 T4指纹漂移重传

# 第五批(用户拍板根治)三段自验: 三链闸门桩测+两脚本原子写中断:
.venv/bin/python /tmp/t_batch3.py           # BATCH3_ALL_PASS
```

输入依赖:`data/public_fund.db fund_daily_nav` 表;数据截止 2026-08-25;关键口径:fund_nav/{code}.json = 每基金全史日净值(nav 升序,count==0 合法空数据放行)。

## 一、critical:update_all.sh 硬闸门(fund_nav 导出失败不再静默续跑)

**原状**:`export_fund_nav.py ... || echo "⚠ 失败(不阻塞主流程)"` 吞掉退出码,后续 `rsync --delete` 与 `upload-fund-nav` 无条件执行——导出半途崩溃时会发布截断/过期净值到 R2 被前端消费。

**修法**(scripts/update_all.sh:190-206):捕获 `$?` 到 `FUND_NAV_RC`;非零→打印【CRITICAL】显式告警(tee 进日志)+跳过 rsync 与 upload;为零→照常 rsync+upload。rsync 的 stderr 从 `/dev/null` 改进日志(不再吞),rsync 自身失败也显式告警。

**实测**:桩命令模拟 exit 1 → rsync_ran=0 upload_ran=0 且 CRITICAL 告警入日志;exit 0 → 两步正常执行。

## 二、high:export_fund_nav.py 原子写(.tmp+fsync+os.replace)

**原状**:L123 `out.write_text(...)` 直接写最终路径,进程 kill/磁盘满留截断 JSON 被部署链消费。

**修法**(新增 `_atomic_write_json`):先写同目录唯一 `.tmp.{pid}`(防并发互踩),flush + os.fsync 落盘后 `os.replace` 为最终文件;异常清理 .tmp 再上抛。配套:import 补 os。

**实测**:
- 正常写→最终文件内容完整;
- os.replace 阶段注入异常→最终文件保持旧版不被污染,.tmp 已清理;
- os.fsync 阶段注入异常→同上;
- **真 SIGKILL 中断**(轮询到 .tmp 写入中途才 kill -9):半截 `.tmp.{pid}` 残留可观测(`{"nav":[[` 开头),最终 JSON 保持旧版完好;部署链 `glob("*.json")` 不匹配 `.json.tmp.*`,残留不会被 upload-fund-nav 误传。

## 三、high:check_data_integrity.check_fund_nav 结构校验增强

**原状**:`d.get("count") == 0` 无条件放行(bool False 也命中)、顶层数组/null 抛 AttributeError 穿透、空数据无契约校验、nav 元素形状不验。

**修法**(在内部 reviewer 已改基础上叠加,**未回退**其「count 缺失仍 FAIL」逻辑):
1. 抽样循环整体 try/except,异常转 FAIL(不再让 checker 自己崩);
2. 顶层必须 dict,否则 FAIL;
3. count==0 分支:count 必须严格 int 且非 bool;nav 必须空数组;code/name/source 缺失或空值→FAIL;date 字段缺失→FAIL;
4. 非空分支:date/count/nav 任一缺失→FAIL(保留原语义);count 类型非 int(bool 含)→FAIL;count≠len(nav)→FAIL;nav 逐元素验 [date(str非空), unit_nav(num), acc_nav(num|null)] 形状;
5. DB↔产物逐位一致段的 `_load_json` 后补 isinstance(d, dict) 守卫(同一顶层数组漏洞点)。

**实测 9 case 全 PASS**(期望 FAIL 的 7 个全部转 FAIL,合法空/非空各 1 个保持 OK):

| case | 内容 | 结果 |
|---|---|---|
| bool_count | `"count": false` | FAIL ✓ |
| count_missing | 缺 count 字段 | FAIL ✓ |
| empty_missing_field | count=0 但缺 code/name/source | FAIL ✓ |
| top_array | 顶层数组 `[1,2,3]` | FAIL ✓ |
| top_null | 顶层 null | FAIL ✓ |
| nav_bad_shape | nav 元素只有 2 列 | FAIL ✓ |
| nav_nonnum | unit_nav 是字符串 "1.0" | FAIL ✓ |
| valid_empty | 合法空数据(code/name/source/date 齐) | OK ✓ |
| valid_nonempty | 合法非空数据 | OK ✓ |

## 四、第四件(主控补充):upload-fund-nav 恶性循环根治

**今日实证链**(日志核对,非推断):
- 06:39 deploy:`upload-fund-nav 超 1800s 未退出，kill pid=90675`(deploy_20260825_0639.log L680)→ state 没写成;
- 17:50 update_all:state 缺失 → 退化「首次/无状态全量 本次待传 26120/26120」,耗时 **5398.9s≈90min**(update_all_20260825_1750.log L1440/L27566;update_all 直跑无超时包装侥幸撑过);
- 18:30 lhb 轮 deploy 并发撞上:`kill pid=97348`(deploy_20260825_1830.log L684)→ 第二封告警。

恶性循环 = **每次被 kill → state 只在全部成功后写 → state 缺失 → 下次全量更慢 → 再被 kill**。

**修法双保险**(选型理由:主控给 b 两选项,不选「放后台续跑」——deploy 未传完就报成功=引入新静默不一致,L44 教训;选拉大超时+checkpoint 续传,失败方向宁多传不漏传语义不变):

1. **checkpoint 分片断点续传**(scripts/upload_r2.py cmd_upload_fund_nav):
   - `_upload_glob` 加零侵入 `on_success(f, rel)` 回调(主线程 as_completed 循环内同步调,其他命令不受影响);
   - 每 PUT 成功记入 done_map,**每 500 只原子落盘一次 checkpoint**(tmp+pid 唯一名+fsync+rename;每只都落盘太贵——26118 次 rename);
   - 重跑时读 checkpoint:**指纹与当前 md5 仍一致的文件视为已传成功剔除**,指纹漂移(导出已重跑内容变了)必重传——正确性语义与原「state 只在全部成功后写」完全等价,checkpoint 只是加速;
   - 失败分支也把已成功部分刷进 checkpoint(state 保持旧值不写);全部成功后写 state + 清理 checkpoint;
   - kill 后最多重传最近 500 只(~10s),不再从头全量 90min。
2. **deploy.sh 超时匹配实际耗时**:upload-fund-nav 通道 1800s → **7200s**(全量实测 5398s 留 ~1.3 倍余量;配合 checkpoint,即使极端再被 kill 也只重传 500 只)。

**实况核对**(主控 c 项):`/Users/linhuichen/code/trade-data/data/.r2_fund_nav_state.json` 存在(1.3MB,count=26120,mode=首次/无状态全量,updated_at=19:47:20)——17:50 全量最终写成,state 当前完整非半截;trade 侧无此文件(正常,状态清单与数据同仓在 trade-data)。`.gitignore` 已补登记 state/tmp/checkpoint 五个路径。

**实测四场景全 PASS**(mock s3_request 不真传):T1 中途失败→exit1+checkpoint 落盘已成功部分;T2 重跑→checkpoint 命中 5 个跳过只实传剩余 7 个;T3 增量→只传变化 1 个;T4 checkpoint 指纹与文件当前 md5 不符→重传不跳过。

## 五、第五批(用户拍板「要根治」):etf_hist/fund_score/etf_score_list 三链同款修复

用户对第四批上报的同类清单拍板:export_etf_hist/export_fund_score 两条链同款问题「要根治」(§23.7 已确认可动)。实施+举一反三多修一条:

1. **update_all.sh 三链硬闸门**(同款结构:捕获退出码→非零打【CRITICAL】入日志+跳过 rsync/upload,零→照常;rsync stderr 全部改进日志不再吞 /dev/null):
   - export_etf_hist 链(L154-167):失败跳过 etf rsync + upload-etf-hist;
   - export_fund_score 链(L188-200):失败跳过 fund_score rsync + upload-fund-score;
   - **export_etf_score_list 链(L143-158,举一反三新增)**:grep 发现与点名两链完全同模式——导出失败被 `|| echo` 吞掉后 rsync + upload-etf-score 照跑,一并加闸门。
2. **export_etf_hist.py**:新增 `_atomic_write_json`(与 export_fund_nav.py 同款),写盘点位替换;
3. **export_fund_score.py**:`_write_json` 内部改原子写(.tmp.{pid}+fsync+os.replace+异常清理),函数签名与调用方零变化。

**自验**(全部实测):
- 桩测三链闸门结构:exit≠0 → skip,exit=0 → pass;
- 两脚本原子写单测:正常写内容完整;os.replace 注入异常后最终文件不被污染+.tmp 已清理;
- 真实小跑冒烟:`--limit 3` etf_hist 产物 JSON 完整可解析(count==len(ohlc))+无 tmp 残留;`--top-n 5` fund_score 正常导出。正常路径零行为变化。
- 冒烟副作用处置(诚实标注):从 trade 树跑脚本 STATIC_DATA_DIR 解析到 trade 侧(cwd 决定,机制同 §9 export 路径陷阱),`--top-n 5` 曾把 trade 侧 fund_score.json/fund_score_top.json 覆盖成 5 行版——已立即从 trade-data 生产源恢复并 md5 终验两侧逐对一致(7775de90…/c4219084…);etf 三文件与生产源逐字节一致无需处理;R2 未受影响(冒烟未跑 upload)。此副作用同时实证了「trade 树手动跑 export 必须显式 REPO」条款的必要性(implementer skill §3.1)。

## §23.3 举一反三·update_all.sh 全量同模式排查清单

全文件 grep「导出/采集 || echo 吞错 + 后续 rsync/upload 照跑」,逐链判定:

| 链路 | 同模式? | 处置 |
|---|---|---|
| export_etf_score_list(L143)+rsync+upload-etf-score | 完全同模式 | ✅ 本批加闸门 |
| export_etf_hist(L154)+rsync+upload-etf-hist | 完全同模式 | ✅ 本批加闸门(用户拍板) |
| export_fund_score(L188)+rsync+upload-fund-score | 完全同模式 | ✅ 本批加闸门(用户拍板) |
| export_fund_nav(L204)+rsync+upload-fund-nav | 同模式 | ✅ 第一批已修 |
| export_alert(L130) / export_alert_analyze(L136) / export_notifications(L172) | **不同**:只写本地 static-site/data/,无紧随的 rsync+upload(靠下次 pipeline deploy 统一推),失败告警已有 | 不加闸门;但 write 直写截断风险仍在,列下方待办 |
| stage0-daily(L179)/compute_all_scores(L186) | 采集/计算类非直接发布,compute 失败后 export_fund_score 会因表无新数据导出旧分(闸门已兜住发布侧) | compute 本身不加闸门(失败有告警+评分闸门兜底) |
| pipeline.sh 四线(core/width/futures/turnover) | 退出码已汇总打印(L97),非吞错模式 | 不动 |
| stock_daily 后台死端 | 设计上不 export 不 push | 不动 |

**遗留上报项**(不在本批范围):
- export_alert/export_alert_analyze/export_notifications/gen_*(gen_etf_index_map/gen_data_pack/gen_daily_brief/gen_schedule_stats)仍是 write_text 直写最终路径——截断风险与本次修复的同根因,但消费路径不同(本地 deploy 推 git vs R2 直传),是否统一改原子写请主控/用户拍板;
- check_data_integrity.py 其余 check_* 函数是否存在同款「顶层数组穿透」,建议 reviewer 巡检。


## medium/low(codex 提出但不在本次必修范围,留档)

- medium public_fund.py:1567 stage0 空结果误判无效反复重采;
- medium check_fund_nav 抽样 5 只覆盖率闸门偏弱(codex 建议 manifest/hash 全量轻校验);
- medium app.js:24730 _fundNavCache 先缓存后验证;
- low 覆盖率统计未复用 _safe_code 映射;low .r2_fund_nav_state.json 未 gitignore+固定 tmp 名;low app.js:24778 涨跌色基准注释与实现不符。
