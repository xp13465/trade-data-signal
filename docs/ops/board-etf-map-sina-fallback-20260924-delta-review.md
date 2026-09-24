# delta review: 腾讯补名 fail-closed 修复(2026-09-24)

> reviewer 独立复审(不采信 implementer 自测),只审增量。base=原审查@b94337131, feat=fix@6f92e71bc(delta 4 文件 +197/-17)。
> 上一轮 FAIL=board-etf-map-sina-fallback-20260924-review.md 第 2 项(腾讯部分缺失静默截断名)。
> 结论:**PASS**(必改项已修,复现/回归数字全部独立复核通过)+ 0 必改 + 3 可跟进。

## 结论速览
| 项 | 结论 | 证据 |
|---|---|---|
| 1 原 FAIL 修复(腾讯部分缺失 fail-closed) | **PASS** | 独立复现:RuntimeError 且错误含缺失代码;正常路径 2045 只/0 缺失/159915·159948 全称 |
| 2 was_fallback_used() 标志污染 | **PASS(带边界说明)** | 双向往复均正确重置;两源全挂时标志遗留旧值(实测)但 build 中止读不到 |
| 3 新增阈值误杀风险 | **PASS(带跟进)** | 实测余量 etf 185(11%)/lof 60(16.7%);硬编码写死=将来隐雷(跟进) |
| 4 腾讯重试逻辑 | **PASS** | 只重试缺失批次,参数/分片正确;仍缺必抛错;上限 1 次无死循环 |
| 5 _meta.source 消费方 | **PASS** | 前端/机检/生成脚本全仓 grep 无读取 source 值;§22 同步链路不受影响 |
| 6 deploy.sh 文案副作用 | **PASS** | 仅消息文本变,dedup/severe 参数未动;bash -n 通过 |
| 7 新增静默路径复查 | **PASS(带跟进)** | 重试/阈值/标志均不静默;残余 1 页截断静默窗(≤185 只)通过阈值=跟进项 |
| 8 无回归(gen 全链路) | **PASS** | 独立复跑:2045/ok=200/no_track=1845/cyb 16/13 指数命中,与原 review 数字逐位一致 |

---

## 1 原 FAIL 是否真修好 — PASS
独立复现脚本(不采信 implementer 的 /tmp/test_etf_fallback_fixed.py,自写):
- monkeypatch `_tencent_fetch_names` 删 159948/159915 → `_sina_etf_spot_df()` **抛 RuntimeError** `"腾讯补全称缺失 2 只代码(重试后仍缺)，fail-closed 拒用，缺失代码: 159915,159948"`,含缺失代码清单 ✓(重试日志 `⚠ [etf-fallback] 腾讯补全称缺失 2 只(...)重试一次缺失批次` 也在)
- 正常路径实网:2045 只、列=['代码','名称','成交额','最新价']、空名 0、159915=创业板ETF易方达、159948=创业板ETF南方 ✓
- 修复机制正确:按**代码集合**算 missing(非只 len),空串名(`fields[1].strip()` 空)同样记缺失(_etf_spot_fallback.py L145-147);删了永假守卫 `(df["名称"]=="").any()`(L188 起改为 map 后不再 fillna)

## 2 was_fallback_used() 标志污染 — PASS(边界已实测)
- `_LAST_USED_FALLBACK` 在 `fund_etf_spot_df()` 主源成功分支置 False(L217)、兜底成功分支置 True(L225)。
- 实测:A1 兜底→True;A2 主源恢复→False;顺向 B2 兜底→True。**双向往复均正确,无"前次 True 污染下次 source 标签"。**
- 关键前提:build_board_etf_map.py 每个进程只调一次 `fund_etf_spot_df()`(L1420),紧接 L1432 读 `was_fallback_used()` 拼标签,中间无第二次调用(grep 全文件仅此一处)。gen/fetch 是同型单次调用形态且各自独立进程。
- **边界(不拦)**:两源全挂抛错时标志**遗留旧值**(实测:前置 True → 失败后仍 True)。但 build 在异常传播路径中中止,程序到不了 L1432,不会打出错误标签;若未来有"捕获异常后继续读标志"的调用方才会出错。目前无此形态。

## 3 新增阈值误杀风险 — PASS(judgment:余量合理,数字偏保守)
- 实网实测:etf_hq_fund=1685(lower 1500,余量 185=11%)、lof_hq_fund=360(lower 300,余量 60=16.7%)。ETF 宇宙日常几无波动(新上市只增不减),阈值误杀概率低,~10-17% 余量对"翻页截断"有兜底力。
- 判定:**阈值合理**,不会造成"正常情况误判失败→旧版兜底=等于没修"的假修复;同时拦得住整节点/大部分截断。唯一更优做法是连续页校验或"末页长度预期"匹配,见跟进①。
- **硬编码**:`_SINA_NODE_MIN_ROWS` 是模块级 dict 字面量(L62-63),非配置。判语:写死宇宙下限是隐雷——未来若新浪节点语义变化/宇宙收缩(当前只见增),该数需人工记得改;影响低频可接受,不改也放行。
- 成交额 ≤50 只回落 0:实测今日 0 只坏;50/2045=2.4% 阈值为全量 2% 内不 fail-closed 合理。排序影响:成交额=0 → 候选排序 drop 到列尾(consumer: build L1545 `sort_values("成交额",desc)`),有 `⚠ [etf-fallback]` 日志可观测,排序用途下可接受。

## 4 腾讯重试逻辑 — PASS
- 只重试缺失代码(`_tencent_fetch_names(missing)`),函数内部照常按 500/批 分片、0.3s 间停,参数/分片无问题(复用同函数)。
- 重试后仍缺 → raise RuntimeError 含缺失代码清单(L197-200),不静默吞。
- 上限=固定一次(无 while),无死循环风险。
- 细节核验:重试返回的 `retry_names` update 进 full_names、`missing=retry_missing`(L192-195),语义正确无错位。

## 5 _meta.source 消费方 — PASS(独立 grep)
- 前端:lab.js 命中均为 fusion_meta/pair_meta(L1409/3304/4122/4130... 与 board_etf_map 无关);app.js 命中为 `_SIG_TYPE_META`(L6794 信号类型标签,无关);common.js 无命中。**前端不读 board_etf_map 的 _meta**。
- 机检:check_data_integrity.py L225 `k.startswith("_")` 排除 _meta 作指数键、L228 仅"无指数条目"才 fail、L370 只读 `_meta.generated_at`(WARN 展示),**不校验 source 值/格式**;check_r2_consistency.py 无 source 读取。
- 生成方:build L957/1126/1168/1694 `if iid=="_meta": continue` 全跳过;gen 无 _meta 处理。
- §22:字段随产物整体再生+两树+R2 三步同步,仅字符串值变化,无跨文件同值键,同步链路不受影响。中文串 `"新浪+腾讯兜底(东财主源失败, fund_etf_spot_em 不可用) + fundf10 track_index"` 只进 JSON 值,无格式/长度约束。

## 6 deploy.sh 文案 — PASS
- 只改 notify 消息文本 2 行;`--severe --from-prefix "[告警]" --dedup-key board_etf_map_stale --dedup-window 3600` 新旧两行逐字相同(参数未动)。
- 文本含 中文/`+`/`?`/`(`/`<br>`/`:`,全部在 shell 双引号内,无 `$(`/反引号/未转义引号;`$REPO`/`$LOG` 为原意图的变量展开。`bash -n scripts/deploy.sh` 通过。

## 7 新增静默路径复查 — PASS(含 1 低危残余)
| 新代码点 | 是否静默 | 判定 |
|---|---|---|
| 空页重试(attempt=2 仍空 break) | 低频 | 兜底:节点条数下限 fail-closed;HTTP 错误走 raise_for_status 抛错不静默 |
| 节点条数 < 下限 | `RuntimeError` fail-closed | 不静默 ✓ |
| 腾讯缺失→重试→仍缺 | `RuntimeError` 含缺失清单 | 不静默 ✓ |
| 成交额解析 ≤50 回落 0 | `⚠ [etf-fallback]` 日志 | 可观测,可接受(只影响排序尾部) |
| 标志位 | 仅 _meta.source 标签,无消费方 | 无静默影响 |
- **残余静默窗(跟进②)**:单页截断恰过阈值仍静默——etf 失≤2 页(185 只,如 1600 只)仍 ≥1500 通过、lof 失尾页(60 只,300==300 通过),无日志无告警。触发需"同页两次请求均 200 空>(HTTP 错误会 raise fail-closed)",低频;且 14 宽基锚点校验(build L1716-1724)兜住核心指数,只影响非锚点指数候选。不拦 merge,建议补"成功日志带节点明细条数"或连续页校验。

## 8 无回归(gen 全链路独立复跑) — PASS
独立脚本强制主源失败走兜底,OUT 重定向 /tmp(不碰 data/):
- 总 2045 只、ok=200、no_track=1845 —— 与原 review 报告数字**逐位一致**
- cyb(创业板指数)命中 16 只(名单含 创业板ETF南方/易方达/东财/华夏...)
- 159948 ok、159915 ok,名称全称、track=创业板指数,无 "EF" 截断名
- 13 指数全命中(sz_div 主动留空),各指数只数与原 review 一致(hs300 49/sz50 13/csi500 38/csi1000 15/cyb 16/kc50 20/csi_div 1/div_lowvol 10/hsi 8/hstech 15/hscei 5)
- 无其他新回归面:本 delta 未动主源成功路径(try 分支原样 return)、未动其他消费点。

## fix 报告诚实性抽查
自测②③④的断言与数字均独立复核一致(2045/0 缺失/全称/重试动作),无夸大。

---

## 必须修才能 merge
无。

## 可 merge 建议跟进
1. **单页截断静默窗**(§7 残余):`_sina_fetch_node` 成功时打印各节点条数到成功日志(现在只有总条数),或加"已返回页数/节点条数"连续性校验;让 1600/1685 这类截断在日志层可被巡检发现。
2. **节点条数下限硬编码**(§3):`_SINA_NODE_MIN_ROWS` 写死模块内,建议未来随 ETF 宇宙增长/新浪节点变化时改为配置或注释登记"宇宙扩容需重审阈值"。
3. **标志遗留边界**(§2):两源全挂时 flag 不更新(遗留旧值)——加一行在兜底异常路径置 False 或注释防未来调用方误读,防患于未然。

## 复现段
```bash
# 1) 原 FAIL 已修复现(独立):腾讯删 159948/159915 → 抛错且含缺失代码
/Users/linhuichen/code/trade/.venv/bin/python -c "
import sys; sys.path.insert(0,'<worktree>/scripts'); import _etf_spot_fallback as m
orig=m._tencent_fetch_names
def partial(codes):
    names,missing=orig(codes)
    for d in ('159948','159915'): names.pop(d,None); missing.append(d)
    return names,missing
m._tencent_fetch_names=partial
try: m._sina_etf_spot_df()
except RuntimeError as e: print('PASS',str(e)[:80])"
# 2) 正常路径:2045 只/0 空名/159915·159948 全称(<worktree>/scripts import 后 m._sina_etf_spot_df())
# 3) 标志双向:monkeypatch ak.fund_etf_spot_em 抛错→True;恢复成功→False(实测 A2 重置正确)
# 4) gen 全链路:独立脚本 /tmp/delta_gen_indep.py(强制主源失败,OUT=/tmp),2025/12-24 跑:2045/ok=200/cyb16/13 指数
# 5) 阈值余量:两节点实测 1685/360 vs 下限 1500/300(余量 11%/16.7%)
```
