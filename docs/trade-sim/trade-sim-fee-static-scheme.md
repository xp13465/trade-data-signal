# trade_sim 费率影响对比:改预生成静态方案(纯静态适配)

> 2026-08-19 实施。接 `docs/trade-sim/trade-sim-fee-config-2026-08-19.md`(费率后端根治)的「费率影响对比」区块前端取数改造:B 级架构改造,把「前端 `fetch('/api/trade_sim_recalc')` 运行时调后端接口」改为「后端发布时预生成多档费率回测静态 JSON,前端读静态」。
> git base: adab0a077(feat/trade-sim-fee-static 分支)。

## 背景与根因

整个项目 = CF 纯静态托管(前端 + 数据 JSON 全在 R2/CF),本机后端从不对外开放给用户。前端原 `fetch('/api/trade_sim_recalc', POST)` 在线上**永远 404**(已实测 ss.fx8.store 所有 /api 都 404,是纯静态的正确行为)。任何需要"运行时后端接口"的费率重算在纯静态下不可行,必须改为发布时预生成。

## 方案核心

**后端(simulate_trade.py)在发布时对每个标的,按 5 个预设档 + 默认档各跑一次回测,产出合并静态 JSON;前端切费率档时读对应标的 `_fee_compare.json` 静态结果,展示"默认 vs 当前档"对比 + 双净值曲线 + 6 项 diff。**

预生成是发布时一次性产物,不是每个用户请求时算(纯静态适配)。

## 改动文件

| 文件 | 改动 |
|---|---|
| `scripts/simulate_trade.py` | 新增 `_FEE_CMP_PRESETS`(5 档费率定义)、`_fee_compare_node`/`_fee_diff`/`_generate_fee_compare`(预生成函数),`main()` 的 `--all` 与单 `--index` 分支都接线调用 `_generate_fee_compare` |
| `static-site/app.js` | `_tradeSimRecalcCompare` 从 POST 接口改为 `fetchJSON` 读预生成静态 JSON;新增 `_feeCompareResolve`(命中/就近映射)/`_feeCompareNearestPreset`/`_feeParamsDist`;`_tradeSimCompareSectionHTML` 增加 custom「近似档」标注;全站"后端重算"文案改"读预生成静态" |
| `static-site/purpose-notes.js` | §21 公示同步:费用影响对比说明改"读预生成静态,无后端接口;自定义档就近映射近近似档" |

## 预生成 JSON 结构

写 `static-site/data/trade_sim/trade_sim_{index_id}_fee_compare.json`,随 deploy.sh 传 R2(`trade_sim_data/` 前缀,与现有 stats/full JSON 同通道):

```json
{
  "generated_at": "2026-08-19 20:16",
  "index_id": "sh",
  "path": "买固定1w(10%)+卖清仓",
  "scenario": "主买+卖",
  "window": "all",
  "default": { "fee_config": {...9字段...}, "summary": {...}, "equity_curve": [...], "net_value": [...] },
  "by_fee": {
    "etf_def":  { "key":"etf_def", "label":"ETF默认", "fee_config":{...}, "summary":{...}, "equity_curve":[...], "net_value":[...], "diff":{ "return_pct_diff":0.0, "annualized_diff":..., "max_drawdown_diff":..., "win_rate_diff":..., "fee_cost_diff":..., "fee_pct_diff":... }, "is_approx": false },
    "zero":     { ... },
    "etf_main": { ... },
    "etf_cheap":{ ... },
    "stock_def":{ ... }
  }
}
```

- **default** = 默认费率(DEFAULT_FEE_CONFIG,印花万5+过户沪深统一万0.1 买卖都收)全历史 × 首位路径 × 首个信号组合回测(与 `compare_fee_configs` 同口径)。
- **by_fee** 每档 = 该档费率同一窗口回测 + 相对默认的 `diff`(6 项)。
- `etf_def` 档 = 默认费率(空配置→DEFAULT_FEE_CONFIG),其 diff 恒为 0(默认 vs 默认)。
- net_value 序列 = equity_curve 相对初始资金倍数(1 起点),供双净值曲线叠加。
- 关键口径:预生成用 **simulate_trade.DEFAULT_FEE_CONFIG 为默认基准**(印花万5+沪深统一),依赖现有 DEFAULT 计算不另造基准;对比取 all 窗口 × 首位路径 × 首个信号组合同 `compare_fee_configs`。

## 前端取数改动

- `_tradeSimRecalcCompare`:读 `https://ss.fx8.store/r2/trade_sim_data/trade_sim_{indexId}_fee_compare.json`(`fetchJSON`,与 `_tradeSimFetchStats` 同 R2 通道),不再 POST 后端接口;错误降级仍走 `feeCompareErr`。
- `_feeCompareResolve`:把预生成 JSON + 当前费率档 `m.feePreset` 解析成前端 `{default, custom, diff}`:
  - 命中预设档(如 `etf_main`)→ 直接取 by_fee 该档(精确);
  - `custom` 档 或 未命中档 → `_feeCompareNearestPreset` 就近映射最接近预设档 + `custom._approx=true`(前端明显标注"近似档")。
- UI 保留:6 项 diff 表 + 双净值曲线 `_tradeSimCompareEquitySVG` + feeCompare/feeCompareErr/feeCompareLoading 三态。
- 费率消耗列(L23699/23847 切费率档实时更新)走前端 replay(`feeRecomputed`)不依赖费率对比接口,不受本次改动影响。

## 自定义档边界

纯静态下自定义费率实时精确重算不可行(无运行时后端接口)。自定义档(custom)**就近映射到最接近的预设档展示 + 明显标注"近似档"**(L1 距离按 佣金万/最低元/滑点千/过户万/印花万 归一),距离为 0(精确等于某预设)时不标"近似档";完全无匹配(数据未预生成)走 `feeCompareErr` 明确提示已预生成 5 档。

## 测试到的标的

本地用 `/Users/linhuichen/code/trade/.venv/bin/python scripts/simulate_trade.py --index / --all` 逻辑测试 2 个标的:

| 标的 | by_fee 档数 | 默认收益 | 结构校验 |
|---|---|---|---|
| sh(上证,ETF替代近似) | 5(zero/etf_def/etf_main/etf_cheap/stock_def) | 53.04% | etf_def diff=0 正确;zero 收益+2.12/cost=0;stock_def 收益-1.24/cost 更高;net_value 1.0→1.53 |
| csi500(中证500,纯指数) | 5 | 22.66% | 结构一致 |

前端解析器 node 单测(custom===etf_main → 不标近似;custom 略高于 etf_def → 标近似档映射 ETF默认),经 brace-matching 函数抽取 + 真实 JSON 渲染 `_tradeSimCompareSectionHTML`:2 polyline(双曲线)+ 7 tr(6 diff 行+表头)+ "读预生成静态"标题 + "近似档"标注,全断言过。

## 复现

- 脚本路径:`scripts/simulate_trade.py`(活入口,融入现有 `--index`/`--all` 生成,非死脚本,不复制副本)
- 输入依赖:`scripts/simulate_trade.py` 的 get_signals(index_id) 信号 + data/board_etf_map.json(ETF 替代) + 同目录 config 常量
- 重跑命令(单标):`.venv/bin/python scripts/simulate_trade.py --index sh`
- 全量:`scripts/simulate_trade.py --all`(发布时/pregen 用,产生 trade_sim_{id}_fee_compare.json)
- 数据部署:`bash scripts/deploy.sh`(trade_sim JSON 走 R2 trade_sim_data/ 前缀)
- 关键口径:`default = simulate_trade.DEFAULT_FEE_CONFIG`(印花万5+过户沪深统一万0.1 买卖都收);对比 = all 窗口 × 首位路径「买固定1w(10%)+卖清仓」× 首个信号组合「主买+卖」;净值序列=equity_curve/init_cap(1 起点)
- 数据截止:2026-08-19 信号最新日

## 不碰范围

凯利 backtest(`signal_kelly_backtest.py` + lab.js `KELLY_FEE_PRESETS` 免印花档)有意保留单独口径,未动;main 分支未推,只 push feat/trade-sim-fee-static。
