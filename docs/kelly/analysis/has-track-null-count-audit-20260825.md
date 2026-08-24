# 进度:null 1,863/38,199 数字口径审计完成(researcher 只读复核,2026-08-24)

## 定论一句话
「null 1,863(38,199 全量去重成交,4.9%)」= trades JSON 全象限×9模式行按 **(signal_date,index_id,signal,sell_date)** 合并去重的「跨模式伪成交笔」口径 + 数据版本微差;非成交基笔、非卡计数,线上任何展示位都核不到。「8,099→9,962」同错(真实卡值 1,604→1,982)。公示应改用成交基笔口径 **1,604→1,982(+378)**。

## 1. 来源定位(38,199 / 1,863)
- 排除 mine29c 工作区:docs/kelly/analysis/scripts/sim_window_loss_mining_20260822/data/{mine29*,mine30*}.json 全文 grep 1863/38199/8099/15099/5557/7581 零命中(mine29 报告里的 "+1,863" 是 2026 年净利改善值,纯巧合)。
- 排除进度文件:/tmp/agent-progress-has-track-caliber.md 仅一行摘要无数。
- 实锤来源=trades JSON 的 sell_date 合并去重口径。复现命令:
```bash
python3 -c "
import json,collections
d=json.load(open('static-site/data/signal_kelly_trades.json'))
F=d['fields']; I={f:k for k,f in enumerate(F)}; iT=I['track_tier']
rows=[r for modes in d['quadrants'].values() for rr in modes.values() for r in rr]
seen={}
for r in rows: seen.setdefault((r[I['signal_date']],r[I['index_id']],r[I['signal']],r[I['sell_date']]), r[iT])
print(len(seen), dict(collections.Counter(seen.values())))"
# 现版(07:08)= 38,344 {'related':15181,'none':8121,'strong':7598,'approx':5578,None:1866}
```
- 与方案文档数字对齐证据(null 子项逐位):
  - 该口径 null **全部有 track_score 且 max=29.2** ↔ 文档「null 笔 track_score 全部有值且<30(max 29.2)」逐位一致
  - 该口径 null 按 sig = {buy_special 967 / buy 304 / buy_backup 132 / buy_aux 463} ↔ 文档「967/462/303/131」:967 逐位一致,其余差 1~3
  - 总数三版本实测:38,344(08-24 07:08 现版)/38,334(/tmp/live_trades.json 08-22 05:10)/38,303(/tmp/kelly_trades_base_asof.json 08-22 09:27);文档 38,199 落在同族 ±0.4% 版本微差带内,null 1,863 落在实测区间 1,859~1,866 内
- 为什么 ~5 倍放大:9 模式中 A/B/C/D 同为 hold_days=10,未触止盈时卖出日相同→4 行并 1;E/F/G/H/I 卖出日各异。平均每信号事件产出 ~5.03 个唯一 (sell_date) 键(38,344/7,619=5.03),机制性放大,不是真实成交次数。
- ⚠ researcher 未落盘统计脚本(方案文档复现段仅示意代码+"以实际 schema 为准"),精确到个位的 38,199 无法逐位复原(违反 §23.5 复现闭环);但口径家族归属已被 null 三重特征钉死。

## 2. 口径对照表(主仓库 static-site/data,generated_at 2026-08-24 07:08)
| 口径 | 去重键/定义 | 总数 | null | 单位 |
|---|---|---|---|---|
| A trades 全行 | quadrant×mode×事件 一行 | 270,882 | 10,206 | 模式×事件行 |
| B 成交基笔(事件级) | (signal_date,index_id,signal) | 7,619 | 378 | 信号事件 |
| C sell_date 合并伪笔(=38,199 同族) | (sd,iid,sig,sell_date) | 38,344 | 1,866 | 跨模式合并行 |
| D signal_daily buy4 全量 | DB 主键 (date,index_id,signal) | 41,960 | — | DB 信号行 |
| E 入样宇宙·当前 map 重算 | D − 宇宙外 − NO_MAP 6,790 − NO_SCORED 96 | 28,036 | 1,355(仅 44 个有分 max25.7) | 信号事件(would-be) |
| F 冻结表 signal_kelly_etf_freeze.json | key=date\|iid\|sig(L205) | 28,120 | 1,308 | 固化信号事件 |
| G 凯利卡计数 backtest.json | etf_has_track.periods.all.*.n=n len(trades)(L873) | 1,604(九模式同值) | 0(null 不入卡) | 每模式成交笔 |

代码锚点(scripts/signal_kelly_backtest.py):
- L80 BUY_SIGNALS=("buy","buy_aux","buy_special","buy_backup");L1026-1029 buy_rows=signal_daily buy4 全查(41,960)
- L369-385 _build_best_etf:每指数取 track_score 最高候选为 top1,tier 缺省"none";无有分候选→不入 best(事件被 skip)
- L1078-1079 etf_quad_map={"strong","related","approx","none"}四键,**None 不在 map→null 事件不入 etf_* 象限(bug 本体)**
- L1081-1146 主循环:_resolve_etf(L1090,冻结优先)→无评级 skip→九模式 _backtest_one(L1125-1133)→同一 trade 行同时归 rating/etf/sig/mkt 四维象限(L1140-1146)
- L873 n=len(trades);L1216-1227 periods 按 buy_date>=cutoff 过滤;L1194-1197 TRADE_FIELDS 列式导出(trades JSON 每行是数组非 dict)

## 3. 三问定论
1. **1,863/38,199=另一口径(C 族伪笔)+版本微差**,不是错数但是**错配**:被当成"成交笔/卡计数"写进扩卡预告。真实增量=null 事件 378 笔进卡。
2. **公示用成交基笔口径:has_track 卡 1,604→1,982(+378)**。理由:①与线上产物(backtest.json/trades JSON)逐位可复现 ②与 lab.js 凯利区渲染同源(读同一批 JSON,L10547 四卡分组)③用户可在 UI 直接核对;C 口径(38k/1,863)UI 无处核对,且随版本漂移。
3. **+378 含义=track_tier 为 null 的信号事件数(成交基笔)**,非天数、非模式×周期聚合;backtest.json etf_has_track 九模式 all 周期 n 全部 1,604→1,982(n 与模式无关,因每事件每模式恰一行)。

## 4. X1 命中 795→978(+183) 口径
- 来源=/tmp/agent-progress-has-track-fix.md STEP3 自验第7条:「K1 层重放(python 复刻 NEW14 键集判 has_track G 行):X1 命中笔数全史 795(none 幸存)→978(none+null 幸存),null 新增+183」
- 单位=**G 模式成交笔(K1 重放层)**:NEW14 其他键先滤,幸存的 etf_has_track G 行中被 X1 剔除的笔数;未含补位/cap/费率(进度文件已自注⚠,正式穷举回测待单派)
- 涉及模式=仅抽 G 行自验;loss_rules.py L127 X1 spec 本身无 mode 限制(track_tier="none" 等值),前端 lab.js L7440 谓词作用于全模式选中池
- 合理性旁证:幸存率 795/1,604≈49.6% vs 新增 183/378≈48.4%,两独立子集幸存率几乎一致,符合均匀过滤预期,数字自洽

## 5. 附带核实
- 实施方 5 口径中「signal 级 (index_id,signal)=664」:本机复算唯一 (index_id,signal) 组合=424(664 疑为其另加了字段或用 worktree 输入差异;不影响主线,该口径本就与扩卡无关)
- worktree agent-a15372251073728bb 重跑产物(15:10)验证:事件去重仍 7,619(None 378)与主仓库逐位一致(修复只改归类不改成交行✓);新卡值 1,982✓;C 口径 38,344/None 1,866✓
