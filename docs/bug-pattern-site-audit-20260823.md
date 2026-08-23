# 全站同类 bug 模式排查报告（2026-08-23，四连 bug 举一反三 · §23.2③ 全站版）

> 排查范围：main@801de1632，static-site 非 min js 共 10 文件（app.js/lab.js/common.js/purpose-notes.js/sw.js/i18n.js/inline-init.js/qr.js/kelly-reports-content.js/kelly-review-notes.js）+ app/ 55 py + scripts/ 74 py。
> 排除 *.min.js / node_modules / data / docs。种子 4 连 bug 本身不重复展开，只给「现状确认」；范围是六大模式的更广家族。
> 机检脚本：`scripts/bug-pattern-audit-20260823/audit_bug_patterns.py`（可一键复跑，见文末「## 复现」）。

## 结论总览

| 级别 | 数量 | 一句话 |
|---|---|---|
| **P0**（会卡死/泄漏/静默错数据的活雷） | **0** | 种子两处自递归已修；A/B/C 三族全站走读未发现同级别活雷 |
| **P1**（潜在雷/同类错误面） | **4** | schema 漂移仍在 main + 完整性校验盲区 31 产物 + daily_brief 告警明细丢失同款未同步 + 告警通道自身静默 |
| **P2**（观察） | **6** | 见各族表 |

---

## A 族：监听器泄漏 —— 全闭合，P2×2 观察

覆盖方式：grep 全量锚点（addEventListener/onclick=/attachEvent），对 app.js 55 处 + lab.js 13 处 + common.js 2 处 document/window 级监听**逐一走读**判定挂载路径是否可重复执行；removeEventListener 全站仅 2 处（app.js:7166 pin-changed 自清理、app.js:28819 onboarding onKey done 清理），其余全靠「单次守卫」约定——逐处核对了守卫存在性。

| 编号 | 位置 | 判定 | 证据 |
|---|---|---|---|
| A-OK | 弹窗 Escape 系列 20 处 | 安全 | 全部 `isFirst`/`if(!modal)` 单次创建守卫（app.js:2981/3713/4712/5171/6909/22523/23614/19591 等）；`_signalChartModalEl` 类 `if(modal) return modal`（app.js:7567/27370） |
| A-OK | 轮询类 visibilitychange | 安全 | `_intradayVisBound`/`_overviewVisBound`/`_gtVisBound` 单次守卫（app.js:10459/10703/12521） |
| A-OK | hoverpop 关闭委托 5 组 | 安全 | `document._freqPopDocBound`/`_etfPopDocBound`/`_sigKellyWmDocBound`/`_sigKellyGuideDocBound`/`_aiPoscapRateDocBound` 守卫（app.js:20880/21122、lab.js:10568/10604、common.js:590） |
| A-OK | init 系列 | 安全 | 启动序列 requestIdleCallback 内一次调用（app.js:28896-28907）；L19279 resize 传同名函数引用 `_pfResizeHandler` 浏览器自动去重 |
| **P2-A1** | echarts.init 无守卫 30 处 | 观察 | app.js:312/1574/1699/6354/10136 等 30 处 init 前 6 行内无 `getInstanceByDom/dispose`，粗筛清单见机检脚本；走读确认均处「每次渲染重建容器」路径，DOM 移除后实例可 GC，未见泄漏形态。风险在「未来同 DOM 复用渲染」时会踩 echarts 重复 init 警告+旧实例残留 |

onclick= 属性赋值 53+127 处为覆盖语义不累积，不逐条列。元素级监听随 innerHTML 重写销毁 GC，不算泄漏。

## B 族：定时器泄漏/自递归 —— 全闭合

| 检查项 | 结果 | 证据 |
|---|---|---|
| setInterval（全站仅 2 个真实实例） | 安全 | `_refreshDebugTimer`（app.js:10853 先 clear 再设）、`_notifyCheckTimer`（app.js:11325 防重启动守卫+11331 stop） |
| setTimeout 链式自调度 | 安全 | 全站仅 market-open tick 一处自递归（app.js:10969），先清 `_marketOpenCheckTimer` 再排下次，与 intraday/overview 轮询同治理模式（`_stopIntradayRefresh` app.js:10466） |
| requestAnimationFrame 循环 | 安全 | 16 处全一次性；唯一条件重试 app.js:21589 `if(!tryScroll()) rAF(tryScroll)` 仅重试单帧有终止 |
| IntersectionObserver/ResizeObserver | 安全 | 局部 observer 每次渲染重建（app.js:21231 回调内 unobserve）；模块级单例有 disconnect（app.js:6970/21807）；回调不改自身观察目标 |

诚实标注：78 处 setTimeout 未逐处走读（多为一次性延时/防抖），用「setTimeout(tick|loop|poll…) 自递归」启发式 grep 兜底，仅命中上述已治理点。

## C 族：缓存/容器无界 —— P2×1

覆盖方式：grep 模块级 `let/const/var _x = new Map()/Set()/[]` 全量列出（app.js 16 处 + lab.js 3 处），逐个追 set/delete/clear 生命周期。

| 编号 | 位置 | 判定 | 证据 |
|---|---|---|---|
| OK | `_ntSparkMeta` | 有界治理范本 | size>300 时清理无 DOM 对应项（app.js:14283-14286）；`_ntSparkPending` 用后即 delete |
| OK | `_indexNavSpies`/`_lwRenderers` | 有清理 | 渲染前 disconnect+清空（app.js:21622-21623）；`_lwRenderers` 遍历删除已分离 container（app.js:15602-15604） |
| OK | lab 凯利计算缓存三件 | 有清理点 | `_kellyClearComputeCaches`（lab.js:7350）在 trades.json 重载时 clear（8097/8102）；键=同一批 trade 对象引用，会话内有界 |
| OK | 其余 Map 键为枚举型 | 有界 | `_simPartsCache`(范围枚举)/`_batchMinuteCache`(品种数~110)/`_emotionIndexCurveCache`/`_indDetail`(指数 id 枚举) |
| **P2-C1** | `_resultCache`（app.js:6421） | 观察 | fetchJSON 结果缓存只进不出：TTL 仅用于命中判断（app.js:6457），永不 delete/clear；url 含动态 `?v=`（app.js:6881 `alert_analyze_${iid}.json?v=${v}`）。单页会话内 url 集合有限（~110 iid），风险=SPA 长期常开+cache-bust 值变化时缓涨。建议：size 超 500 做 LRU 淘汰 |

DOM 追加型：insertAdjacentHTML 250 处中粗筛 12 处无前置清理，逐一走读均属「一次性弹窗构建/卡片新建」路径，无循环追加累积。

## D 族：schema/清单漂移 —— P1×2，P2×2（种子现状确认 1 条）

| 编号 | 位置 | 模式 | 证据 | 建议 |
|---|---|---|---|---|
| **P1-D1**（种子#2 现状确认） | scripts/overfit_monitor.py:328 | 列清单字面量 vs 权威常量漂移 | `FIELD` 21 列硬编码 vs `signal_kelly_backtest.py TRADE_FIELDS` 24 列，缺 `market_tier/market_tier_all/market_tier_cyb`（插在 market_state 与 rating 之间，IDX 错位）→ by_grade 按错位列取值。**main@801de1632 上仍是 21 列字面量，尚未修**。机检 DIFF 可复跑：`python3 scripts/bug-pattern-audit-20260823/audit_bug_patterns.py` 输出 `[D1]` | 删字面量，改 `from signal_kelly_backtest import TRADE_FIELDS`（或读产物自带 `fields` 数组建 IDX），并加「len(FIELD)==len(fields)」启动断言 |
| **P1-D2** | static-site/export.py（39 个 json 名）vs scripts/check_data_integrity.py（17 个） | 导出面 vs 校验面漂移 | 31 个导出产物无完整性校验：public_fund_* 12 件、futures.json、metrics.json、signal_stats.json、signal_kelly_trades.json、summary_history.json、new_high_low.json、ma_alignment.json 等（全清单见机检输出 UNCOVERED 段）。新数据类别「生成了没导出/导出了没上线」静默缺失正是 memory E16 场景，现有 check 覆盖不到 | check_data_integrity 增加「export_manifest.json 清单 ⟺ R2/线上在位」全量断言，新类别自动纳入不再逐个手加 |
| P2-D3 | 20 新键清单四处字面量 | RECENT_KEYS 同款结构 | 后端单源 scripts/loss_rules.py `NEW_KEYS_PROD`(20)；前端 common.js:730-735 `_KELLY_FADE_T1_KEYS`(20)、app.js:2639 映射(20)、lab.js:7418 映射(20)。本次实测四方全对齐（机检 [D2] PASS）；但 `check_loss_rules_vs_mining.py` 只查后端 vs 挖掘权威，**前端清单无自动对账**，第 21 键加入时靠人记 | 把机检脚本 D2 段搬进 check_loss_rules_vs_mining.py，前后端一起断言 |
| P2-D4 | greedy15 双端 step 差异 | 前后端双实现固有结构 | common.js:690 前端 spec 含 price_bin 步骤(q/bpb)，queries.py:899 后端注释「step5/9/14 依赖 price_bin 信号级降级不参与」——已知设计非 bug，靠 test_queries_regression.py replay 守护。37 legacy 键（common.js:644 `_KELLY_FADE_LEGACY_SPECS`）同理双实现 | 观察即可；任何 legacy 键改动必须双端同 commit + replay 对齐（既有约定） |

补充：trades.json 列索引消费方全站仅 overfit_monitor.py 一处按 IDX 取列（grep `IDX[` 全仓），bond 脚本独立产物、queries.py 不按索引读——D1 修一处即根治。

## E 族：静默失败 —— P1×2

覆盖方式：except-pass 43 处全量定位+生产链路 14 处走读；requests timeout 全量机检（多行调用括号配平后判）= **0 缺失**；subprocess 全量扫 returncode 处理 = 全部有处理或故意容错；定时入口脚本 __main__ 均为裸 main() 异常会非零退出。

| 编号 | 位置 | 模式 | 证据 | 建议 |
|---|---|---|---|---|
| **P1-E1** | scripts/gen_daily_brief.py:2877-2878 | 上传输出只看汇总行，告警明细被丢（fetch_news 同款，§23.2③ 同类错误面） | `if r.returncode == 0 and out: print(f"[R2] {out.splitlines()[-1]}")` ——upload_r2 purge_cache 失败不中断整体 rc=0（scripts/upload_r2.py cmd_upload_data_files 注释「purge_cache 失败不中断」），stdout 里的 `⚠ Cache purge 部分失败…批次明细行` 被 `splitlines()[-1]` 吃掉。同款问题 fetch_news.py:713-716 已在 801de1632 修复（打全部 ⚠/✗ 行），gen_daily_brief 未同步 | 照 fetch_news 修法抄：warn_lines 过滤打印全部 ⚠/✗ 行 |
| **P1-E2** | app/collector/runner.py:36-44 | 告警通道自身失败静默（监控盲区新点，memory monitor-blindspot-exit0 未记） | 采集告警调 notify.py 子进程 `stdout=DEVNULL, stderr=DEVNULL` + `except Exception: pass`（注释「通知失败不阻塞采集」）→ 告警发不出时零痕迹，恰在最需要告警的时刻失聪 | notify 子进程失败时往采集日志文件写一行 ERROR（log 扫描层可兜），DEVNULL 改 capture 后落日志 |
| P2-E3 | scripts/fetch_news.py:731-732 | 同步失败仅打印不 exit 非 0 | `except Exception as e: print("⚠ …不阻塞,盘后 gen_daily_brief 20:40 兜底")` ——launchd exit-code 视角看不到 news 同步失败；有 20:40 兜底+print 痕迹，降级 P2 | 同步失败时可选 `sys.exit(3)` 区分码或保持现状（已有兜底链） |
| OK | 其余 except-pass | 缓存/可选数据回退模式 | stock_daily.py:148（codes 缓存坏则重拉）、aggregate_shadow.py:82/102、build_board_etf_map.py:1267（滞回状态读失败回退空）等，失败均有合理默认值非静默错数据 |

## F 族：共享持久化键多写方 —— P2×1

全量表（机检产出，W=setItem 写方数，跨文件=CROSS-PAGE）：

| 键 | W/R | 读写方 | 判定 |
|---|---|---|---|
| tds_poscap | W4/R4 CROSS-PAGE | app.js:2473/2476/3878/3882 + lab.js:7702/7708/8738 + common.js:496 | **有意设计**：首页 AI仓位建议 ↔ lab 凯利区共享 cap 开关/K 档，注释明说「同键同语义 §22 联动」（app.js:2471、lab.js:7698）。非联动嫌疑 |
| tds_kelly_fade_mode | W2/R1 | lab.js:10001（下拉切换）/10012（重置回落 p8）→ 8726 读 | 同页同语义两写，正常；main 上 sim 弹窗 fade 模式**无独立持久化键**（sim 只存费率 `tds_simbt_fee_config` app.js:3552，fade 模式会话态），与 hotfix 分支正在加的独立化方向一致 |
| tds_home_fade / tds_overfit_fade / tds_home_bull_aux_backup_stop | 各 W1/R1 | app.js:2285/2509、2033/2043、2298/2493 | 三键各自独立读写，无跨区联动 |
| navStickyOff_ts | W2/R5 CROSS-PAGE | app.js:24063/28509 + inline-init.js:32 | 设计如此（导航吸顶开关 storage 跨标签同步+FOUC 前置读取） |
| compliance_mode / etf_buy_expanded / lab_aiscore_buy_expanded | 各 W2 | 同文件同函数两分支 | 正常（切换两分支各写一次） |
| 其余 21 键 | W1/R1 | 单写单读 | 无多写方风险 |

| 编号 | 位置 | 模式 | 建议 |
|---|---|---|---|
| **P2-F1** | lab.js:7708 `_kellySetSharedPosCap(on,k)` 默认 `k: k || 3` | 默认档与全局默认 K=1（#BC 主推）不一致；现存 5 处调用全显式传 k 不可达，未来新调用漏传 k 会把跨页共享键写成 k=3 | 改 `k: k || 1` 对齐全局默认 |

## 种子四连现状确认（不计入新发现）

1. 微任务链自递归两处：feat/ui-fade-mode-fix@7ea4f8272 已修，main 未合（main 的 app.js sim 弹窗/lab.js:8674 仍是旧链，merge 后以该分支为准）。
2. overfit FIELD 21 列漂移：**main 上仍在**（见 P1-D1）。
3. purge 重试：801de1632 已在 main。
4. fade mode 键独立化：hotfix 分支进行中；main 上实测三键独立+sim 无持久化键，无现存联动。

## 维度覆盖自检（诚实标注）

| 族 | 覆盖方式 | 不到位处 |
|---|---|---|
| A 监听器 | 70 处 doc/win 级逐一走读；onclick=/元素级全量分类 | 元素级 235+127 处靠 GC 语义免检，未逐处验证容器确被 innerHTML 重建 |
| B 定时器 | setInterval/rAF/observer 全量；自递归启发式 grep | 78 处 setTimeout 未逐处走读（启发式兜底） |
| C 缓存 | 模块级容器 18 处全量追生命周期；追加型 250 处粗筛+12 处走读 | 闭包内局部缓存未穷举（不入模块态不跨调用） |
| D 清单 | 机检三组对账+人工核对消费方 | export/check 名单提取基于字符串匹配，个别动态拼名可能漏计（方向只会更多未覆盖，不减轻结论） |
| E 静默 | requests/subprocess 机检全量；except-pass 生产链 14 处走读 | 206 处 bare/Exception except 未逐一走读（抽样式） |
| F 存储键 | 机检全量映射表+嫌疑键走读 | 无（全量） |

## 复现

```bash
# 机检三项(D1/D2/D3 对账 + E1 requests timeout 扫描 + F 全量存储键映射表), 有 DIFF 退出码 1:
python3 scripts/bug-pattern-audit-20260823/audit_bug_patterns.py

# 人工走读辅助命令(本次实际使用):
grep -nE "(document|window|document\.body)\.addEventListener\(" static-site/app.js   # A族 doc/win 级监听定位
grep -c 'removeEventListener' static-site/*.js                                       # A族 显式解绑仅 2 处
grep -n 'setInterval' static-site/app.js static-site/lab.js static-site/common.js    # B族 interval 全量
grep -nE '^(let|const|var) _[A-Za-z0-9_]+ ?= ?(new Map\(\)|new Set\(\)|\[\])' static-site/app.js   # C族模块级容器
grep -rn -A1 'except.*:$' app/ scripts/ --include='*.py' | grep -B1 'pass'           # E族 except-pass 定位
```

- 数据版本：main@801de1632（2026-08-23），纯静态源码扫描，无 DB/网络依赖。
- 关键口径一句话：机检只做「清单 vs 清单」静态对账与模式 grep；活雷判定（是否真泄漏/真静默）来自逐处人工走读，两者在报告中分开标注。
