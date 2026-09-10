# 盘中增量表格"板块不见了"诊断报告(2026-09-10)

## 现象
用户实测信号凯利回测 tab → 全信号卡 → 交易记录弹窗的**盘中增量表格板块直接不见了**(新前端 common.min.js 含 kelly-intraday-view 已上线)。

## 判定(结论先行)
**这是"换日设计行为",不是渲染 bug,不是缓存问题,无需改代码。**

每个交易日盘中增量表只在「产物对应开盘日 == 今日」时渲染;跨日空窗(今日盘中补跑 9:40 前)按设计整块隐藏,9:40 补跑后自动恢复。

## 复现实验(Playwright 无痕, 线上 ss.fx8.store/lab.html)
### 1. 真实日期(2026-09-10 09:16, 9:40 补跑未触发)
```json
{
  "dateStr": "Thu Sep 10 2026 09:16:19 GMT+0800",
  "hasView": false,               // #kelly-intraday-view 不存在
  "docHasIntradayText": false,    // 全文档无"盘中增量回测/盘中价"文字
  "pageErrors": []                // 零 JS 错误
}
```
→ 与用户看到的"板块直接不见了"完全一致,且无渲染报错。

### 2. mock Date = 2026-09-09(与产物 next_open_date 同日, 同代码)
```json
{
  "viewExists": 1,
  "viewNote": "📊 盘中增量回测 · 上一交易日(9/8)信号已用今日开盘价按 A 卖出模式 · s06降亏 · K=1 过滤后 1/4 笔 · 标注=盘中价(今日真实开盘定价,非最终收盘口径)",
  "tblRows": 1,
  "rect": { "h": 148, "sh": 148, "sw": 1100, "cw": 1100 },
  "scrollbarY": false,
  "pageErrors": []
}
```
→ 渲染链路正常:表格渲染、无滚动条(60 行场景下按需展开)、无 JS 错误。

## 根因
### 代码定位(static-site/common.js)
```js
L1480:  var sameDay = meta.next_open_date === _todayS();
L1481:  if (!sameDay) return "";               // 换日 → 不渲染(全量版已接管)
```
- `_todayS()` 返回当前日期 YYYYMMDD;`meta.next_open_date` = 产物里「信号日 T 的 T+1 开盘日」。
- 9/10 早上(9:40 补跑前):线上产物仍是 9/9 的(`intraday.next_open_date=20260909`, 9/8 信号 × 9/9 开盘价入账),而今日 = 20260910 → `sameDay=false` → 整块 `return ""`。
- 注释明确「换日 → 不渲染(全量版已接管)」= 设计本意,与设计文档 §6 用户拍板一致。

### 数据产物语义(static-site/data/signal_kelly_trades_intraday.json)
```
mode = intraday, rerun_date = 20260908 (信号日), next_open_date = 20260909 (入账/开盘日)
price_basis = next_day_open_akshare_spot (9/8信号 × 9/9真实开盘价)
generated_at = 2026-09-09 22:40
```

## 自动恢复
- launchd `com.trade.kelly-intraday-rerun` 09:40 定时在位(9/10 会照常触发)。
- 9:40 补跑成功后生成 `next_open_date=20260910` 新产物 → 前端 `sameDay=true` → 板块自动恢复渲染。
- 因此"看不见"只出现在每交易日 0:00–9:40 空窗(昨日盘中表在今日全量版接管后按设计隐藏,今日盘中表尚未生成)。

## 次要观察(不阻塞本判定,供主控留意)
9/9 产物 mtime / generated_at 均为 **22:40**,但 9/9 09:40 补跑日志记录产物为 **49209 bytes / 200 行**;现文件为 **41737 bytes**。即 9/9 晚间产物被重写过,但语义仍正确(`next_open_date=20260909` 未变)。重写来源未定位(9/9 22:10–22:50 无 kelly_intraday 相关日志)。建议留意是否有重复生成路径(§23.5 产物单一事实源),避免两套口径互相覆盖。

## 给用户的选项(若要增强,需用户拍板,按 §23.7 冻结契约)
当前设计下盘中表每交易日 0:00–9:40 隐藏。若希望空窗期也有占位提示(如"本轮盘中增量 9:40 生成")或保留昨日盘中表的历史降级视图,需改前端逻辑(common.js L1480-1481 + _bannerHtml),属动已上线功能,须用户确认后再实施。

## 复现
- 探针脚本(报告同目录 scripts/, 死脚本): `scripts/probe_intraday_view_missing.mjs`(真实日期验证隐藏)、`scripts/probe_intraday_view_sameday.mjs`(mock Date 验证同日渲染)
- 数据依赖: 线上 https://ss.fx8.store/lab.html + https://ss.fx8.store/data/signal_kelly_trades_intraday.json(next_open_date=20260909)
- 重跑命令: `cd docs/kelly/analysis/scripts && node probe_intraday_view_missing.mjs` ; `node probe_intraday_view_sameday.mjs`(脚本内已写死 mock 2026-09-09,不用传参)
- 数据截止: 2026-09-10 09:20(盘中)
- 关键口径: 盘中增量表仅当 `intraday.next_open_date == 今日(YYYYMMDD)` 渲染,换日整块隐藏,9:40 补跑后自动恢复
