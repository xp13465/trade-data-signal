# #91 次日开盘口径默认切换 影响面评估(2026-09-06)

> 结论优先:**pending-index #91 描述已过时**。方案A「默认切次日开盘」核心动作①已由 v1.1.4(2026-08-22, commit 371434fdc)完成并上线。真正缺口 = 方案A「保留当天手动可切」的前端开关(未实施)。报告供用户拍板 Q1-Q3。

## 一、三源核对结论(§23.13)

| 源 | 现状 | 一致? |
|---|---|---|
| UI 文案(lab.js L11051 / app.js L5661-L5662 / purpose-notes.js) | 「v1.1.4 起默认=信号次日开盘」全部已写 | ✓ |
| 代码现状(scripts/signal_kelly_backtest.py L75) | `KELLY_BUY_NEXTDAY = os.environ.get("KELLY_BUY_NEXTDAY", "1")` 默认=1(次日开盘) | ✓ |
| 线上数据(signal_kelly_backtest.json config) | `buy_price_basis = next_day_open`(今日 17:59 盘后已生成) | ✓ |
| 线上成交(signal_kelly_trades.json) | buy_price 已按次日开盘口径(512480 20210607 样本验证:buy_price 2.264883 与次日 open 1.13/当日 close 1.121 gap 换算一致) | ✓ |
| 测试基准(memory v1.1.7 锚点 L23) | 已含「回测默认买入价口径:信号日收盘等价→信号次日开盘价」 | ✓ |

→ 三源一致,默认=次日开盘已生效。#91 08-20 落档时的「未改、默认仍当日收盘」是旧判断。

## 二、真正缺口 = 方案A「保留当天手动可切」

- 前端无口径切换控件(grep buy-basis/toggle/收盘口径 无结果)
- 数据层无 signal_day_close 副本(只有 next_day_open 一份产物,303,840 笔)
- 即:用户无法手动切回「当日收盘」口径看旧基线对比

## 三、需用户拍板(Q1-Q3)

- **Q1**: 「保留当天手动可切」的确切含义 = ①前端加切换控件(默认次日开盘,可切当日收盘对比)? 还是 ②仅回测脚本保留 `KELLY_BUY_NEXTDAY=0` env 开关(已具备,无需前端改动)?
- **Q2**: 若需前端切换控件 → 数据层需双口径产物(next_day_open + signal_day_close 两份),重跑 `KELLY_BUY_NEXTDAY=0` 全量 ≈30.4 万笔(含重复归入),耗时数十分钟级;前端 lab.js 凯利回测区加口径开关 + 双数据加载 + 买入价口径标注列/文案。
- **Q3**: 前端凯利表「买入日」列显示 buy_date=signal_date(信号日),但 buy_price 已次日开盘价——若切当日收盘口径,买入日语义是否也要对齐?

## 四、§5.4 基准 / 版本判定

- 当前基准 v1.1.7 锚点 L23 已含「回测默认买入价口径=次日开盘」,方案A 不改变默认组合本身。
- 若仅新增「当日收盘可选档」(默认仍次日开盘)= 纯新增不影响默认行为,**不发中间版本**(§5.4⑥)。
- 若需双口径产物 → 重跑全量 + §22 三步同步(static-site/data + R2),check_data_integrity 需补 buy_price_basis 校验(现无)。
- §21 公示:双口径切换需 purpose-notes.js + lab.js + app.js 三处补「可选切回当日收盘」说明。
- §23.1 README:若做前端切换控件,README 功能亮点需补一句。

## 五、冲突/约束

- 不动 app.js/index.html(#99 在改,feat/toast-changelog-099);lab.js 可动。
- 2026-09-06 周日休市,随时可跑全量 export+deploy,无盘后时点冲突。

## 复现

- 三源核对:grep `KELLY_BUY_NEXTDAY` scripts/signal_kelly_backtest.py;grep `次日开盘|next_day_open` lab.js/app.js/purpose-notes.js;查线上 signal_kelly_backtest.json `config.buy_price_basis`。
- 样本验证:signal_kelly_trades.json 512480(20210607) buy_price=2.264883 ⟺ 该日次日开盘价。
- 评估 agent:worktree agent-aae2e853f60c0d202,进度文件 /tmp/agent-progress-nextday-open.md。
