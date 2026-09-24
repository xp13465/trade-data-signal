# review: board_etf_map 生成链路新浪+腾讯兜底(2026-09-24)

> reviewer 独立审查(worktree 隔离),base=origin/main@125faef75,feat=worktree-agent-a299c2abc473eee4c@f294effe0。
> 结论:**FAIL(1 项必改)+ 3 项可跟进**。报告本体=本文档,复现命令见「复现段」。

## 结论速览
| 项 | 结论 | 一句话 |
|---|---|---|
| 1 列口径完整性 | **PASS** | 三消费点+overlap_fetcher 只消费 代码/名称/成交额,兜底全提供 |
| 2 新浪名称截断静默风险 | **FAIL(必改)** | 腾讯部分缺失→静默带截断名继续跑,14 宽基校验兜不住 |
| 3 主源成功路径零回归 | **PASS** | try 分支直接 return,零加工;monkeypatch 测试方法成立 |
| 4 错误处理与可观测性 | **PASS(带跟进)** | 两源全挂抛错+deploy 降级告警生效;告警文案过时 |
| 5 前缀映射完备性 | **PASS** | 实测 2045 只,首位 {1:992,5:1053},规则外 0 只 |
| 6 §21 公示/数据源公示 | **PASS** | 前端公示无写死"东财/akshare"字样;docstring 已同步 |
| 7 §23.3 同类消费点清点 | **PASS** | 全仓 grep 无第 7 处,处置表 6 行全部核实 |
| 8 §5.4⑦ 双实现漂移 | **PASS** | 两份实现重复点一致,职责不同不复用判定成立 |

---

## 第 1 项 列口径完整性 — PASS

逐接入点×逐列对照(实测 + grep):
| 接入点/下游 | 消费列 | 证据 |
|---|---|---|
| build_board_etf_map.py | 代码/名称/成交额 | L1421-1429、L1549-1572、L1631-1632;下游函数 L425-431/L561-566/L719-728/L1297-1301 仅取这三列 |
| gen_etf_index_map.py | 代码/名称/成交额 | L97-101 |
| fetch_etf_track_index.py | 名称/成交额/代码 | L115-125(含 EXCLUDE 关键词过滤+成交额≥100万) |
| app/collector/overlap_fetcher.py | 名称/成交额/代码 | L202/L280-283/L493/L552-553/L616-617(生产路径 df 由 build 传入) |

- `grep '["开盘价"\|["流通市值"\|["数据日期"\|["最新价"]'` 四文件**零命中**。回测链路 F4 的「数据日期」消费点在 signal_kelly_backtest `_fetch_intraday_open_prices`(自备双源兜底),不受本次改动影响。
- 兜底实测返回列 = `['代码','名称','成交额','最新价']`,为消费列的超集。成交额 dtype=int64 无缺失。
- 判断:兜底路径任一接入点不会 KeyError,也不会被 `.get` 静默吞错列。

## 第 2 项 新浪名称截断静默风险 — **FAIL(必须修才能 merge)**

**腾讯整源挂**:`_tencent_fetch_names` 里 `r.raise_for_status()` 抛错→上抛→`fund_etf_spot_df()` 抛 RuntimeError(两源失败)。fail-closed,可接受。

**腾讯部分缺失(本次 FAIL 的核心)**:`_sina_etf_spot_df` L96-99:
```python
full_names = _tencent_fetch_names(codes)
df["名称"] = df["代码"].astype(str).map(full_names).fillna(df["名称"])
if (df["名称"] == "").any():
    n_empty = int((df["名称"] == "").sum())
    raise RuntimeError(...)
```
- `.fillna(df["名称"])` 对腾讯没返回的代码**静默回落新浪简称**;`(df["名称"]=="")` 守卫形同虚设(新浪 name 永非空串,如 "创业板EF"/"创业板")。
- **最小复现**(monkeypatch 掉腾讯返回值,见复现段):删除 159948/159915 的腾讯全称→`_sina_etf_spot_df()` **无异常返回**,159948 名="创业板EF"、159915 名="创业板"。无任何日志/告警。
- **生产影响链**:gen_etf_index_map cyb 规则 include=["创业板ETF","创业板增强"](L60-61)→截断名不命中→etf_index_map 里这两只标 no_track;build_board_etf_map KW 层(L107)同规则不命中→少候选;track_index 层(L272 include "创业板指")会从 fundf10 缓存补回,但展示名=截断名("创业板EF" 上首页)。**14 宽基校验(L1716-1724)只查 `out.get(iid)` 非空,查不出"名字全错但板块非空"**——正是 2026-08-06 board_etf_map 空数组事故的变种新通道(§23.11 绝不静默)。
- 触发概率:腾讯当前 2045/2045 全补,但腾讯有 WAF 风控先例(memory),批量中掉一批是实存风险。
- **修法建议(一行级)**:`if len(full_names) != len(df): raise RuntimeError(f"腾讯全称补齐缺 {len(df)-len(full_names)} 只, fail-closed 拒用")`,或至少对 12 宽基锚点代码逐一校验腾讯名存在。normal 路径实测 0 缺失,任何缺失都该 fail-closed,与本模块"两源都失败抛错"哲学一致。

## 第 3 项 主源成功路径零回归 — PASS

- 代码:try 分支 `df = ak.fund_etf_spot_em(); if df is None or df.empty: raise; return df`——直接返回,**无列重排/类型转换/加工**。
- 自测方法成立:monkeypatch ak.fund_etf_spot_em→假 df,若兜底被触发返回的会是新浪 df 而非假 df,identity 断言能抓出。不是自欺。
- build/gen 仍保留各自 akshare import 的合法用途(build L817 `fund_open_fund_info_em` LOF 净值);fetch 删 import 后无残留 `ak.` 引用。deploy 17:50 走此路径无回归。

## 第 4 项 错误处理与可观测性 — PASS(带跟进)

- 两源全挂:实测 `fund_etf_spot_df()` 抛 `RuntimeError("ETF 实时行情两源均失败: 东财(...); 新浪+腾讯兜底(...)")` → build/gen 非零退出 → deploy.sh L190-215 既有降级(备份恢复旧 map + SKIP_MAP_SYNC)照常生效,收尾告警 L1067-1069 触发。链路完整。
- 兜底触发有明确日志 `⚠ [etf-fallback] 东财主源失败...启用新浪+腾讯兜底` + `✅ 成功:N 只`(实测可见)。不静默。
- **跟进项(可 merge 后改)**:deploy.sh L1069 告警文案写"14 宽基校验未过/akshare 反爬兜底也失败 / 需人工核查数据源(akshare 反爬?)"——现在两源都挂时真实原因是东财+新浪+腾讯三源全挂,文案误导排障方向。应改为"东财+新浪+腾讯行情源均失败"。
- fetch_etf_track_index.py(周日 03:30 周任务):两源全挂抛错非零退出(与改动前行为一致);该脚本无脚本内告警出口、仅写 data/(build 读旧缓存兜底),属既有形态非本次引入;报告"未证实"段已诚实标注。

## 第 5 项 前缀映射完备性 — PASS

- 实网拉新浪 etf_hq_fund+lof_hq_fund 两节点:2045 只,首位分布 `{'1': 992, '5': 1053}`,**规则外(非 5/1)0 只**——`5→sh、1/2/3/4→sz` 规则全覆盖,无静默丢弃。
- 缺口 29 只(519/580 段场外基金,amount=0,新浪无行情)不影响有效匹配:独立重跑 gen_etf_index_map 13 指数全命中、cyb 16 只;12 宽基锚点(510300/510050/159915/588000/159920/513180 等)全在新浪池。
- 空名称 0 只。

## 第 6 项 §21 公示 / 数据源公示 — PASS

- 前端公示(purpose-notes.js / app.js / lab.js)定向 grep:无写死"数据来源:东方财富 / akshare / 东财"字样的 ETF 数据源文案(命中的"数据来源"串均为凯利 G/H/I 档位文档引用,与 ETF 行情无关)。
- §21 算法公示不触发:本次是数据源兜底(仅主源失败才启用),非算法/口径变更;主源成功时数据与旧版逐位一致。
- build/gen 的模块 docstring 已同步标注兜底(好实践)。附带小项:board_etf_map.json 产物 `_meta.source` 仍写"akshare fund_etf_spot_em + fundf10 track_index",兜底日不准确——纯后端调试元数据,前端不展示,可跟进不误导。

## 第 7 项 §23.3 同类消费点清点 — PASS

- worktree 全仓 grep `fund_etf_spot_em`:真调用点仅 2 处 = `signal_kelly_backtest.py:754` + `overlap_fetcher.py:669`(均在 `if __name__=="__main__"` 或自备双源兜底内),余为注释/docstring。**无第 7 处被漏**。
- overlap_fetcher 生产路径核实:df_by_code 只由 build_board_etf_map.py 预计算传入;`match_overlap`/`match_holdings_overlap` 无其他生产调用方。
- nextday_gap_check.py L54 确从 signal_kelly_backtest import `_fetch_intraday_open_prices`、L120 直调——"随迁"成立,兜底已在 signal_kelly_backtest 内部。
- 处置表 6 行全部独立核实成立。

## 第 8 项 §5.4⑦ 双实现漂移 — PASS

重复点对照(新模块 vs signal_kelly_backtest `_fetch_intraday_open_via_http`):
| 重复点 | 新模块 | signal_kelly | 一致? |
|---|---|---|---|
| 前缀映射 | `code[0]=="5"→sh else sz` | `startswith("5")→sh else sz` | 语义一致 |
| 腾讯 host | `qt.gtimg.cn/q=` | `qt.gtimg.cn/q=` | 一致 |
| 新浪 Referer | `finance.sina.com.cn` | `finance.sina.com.cn` | 一致 |
| 字段解析 | tencent `split("~")[1]`=名称 | tencent `split("~")[5]`=今开/`[30]`=时间戳 | 不同字段、同一行格式,不冲突 |
| 批量分片 | 500/批 | 逐只 | 不冲突 |

- 两源均实测解码正确(腾讯 charset=GBK 头在位,新模块 `r.text` 正常;signal_kelly 用 `r.content.decode("gbk",errors="replace")` 更防御)。
- 判定"职责不同不复用"成立:单点今开 dict 逐只 fail-closed vs 全量 DataFrame 名单,形态/字段/语义完全不同;公共部分仅 2-3 行,抽公共反而跨文件耦合。同一只 ETF 两链路不会拿不同结果(实测 159915 两源一致)。
- 低分项(已滤,不进报告):新模块 `r.text` 依赖腾讯 charset 头(当前在位,风险 <80 分);gen 残留 `import akshare` 未用(死 import,<80 分)。

---

## 必须修 vs 可跟进
- **必须修才能 merge**:第 2 项——腾讯部分缺失静默降级截断名,`_sina_etf_spot_df` 补 `len(full_names)!=len(df)` fail-closed 守卫(或宽基锚点名校验)。
- **可 merge 但建议跟进**:①deploy.sh L1069 告警文案改"三源全挂" ②`_meta.source` 兜底日标注 ③新模块 `r.text` 换 `r.content.decode("gbk", errors="replace")` 更防御。

## 复现段
```bash
# 1. 第 2 项 FAIL 最小复现(腾讯部分缺失→静默截断名,无异常):
/Users/linhuichen/code/trade/.venv/bin/python -c "
import sys; sys.path.insert(0,'scripts')
import _etf_spot_fallback as m
orig = m._tencent_fetch_names
def partial(codes):
    d = orig(codes)
    for drop in ('159948','159915'): d.pop(drop, None)
    return d
m._tencent_fetch_names = partial
df = m._sina_etf_spot_df()
print('无异常返回(应为 fail-closed 却静默)', df[df['代码'].isin(['159948','159915'])]['名称'].tolist())
"
# 2. 兜底整链/两源全挂实测:见报告第 3/4 项命令
# 3. 兜底路径 gen 全链路独立复跑(本次 reviewer 已验证):13 指数全命中、cyb 16 只
/Users/linhuichen/code/trade/.venv/bin/python scripts/gen_etf_index_map.py
```

## 审查口径
- 本报告所有结论均为 reviewer 独立实网/实跑验证(新浪 2045 只前缀分布、腾讯 2045/2045 补名、兜底整链 19.5s、两源全挂抛错、gen 全链路复跑),不采信实施 agent 自测报告;gen 复跑数字(ok=200/cyb=16/13 指数全命中)与报告一致=报告数字可复现。
- 低置信(<80)项已滤 2 条,清单见第 8 项末。
