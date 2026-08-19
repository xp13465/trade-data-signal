# 模拟回测(trade_sim)费率可配后端根治调查

> 2026-08-19 实施落地。用户拍板必做(A 后端根治),TASKS L605-644「模拟回测费率可配置」块 + L626-630「全量重生」。本报告只讲**后端**部分(费率面板/持久化/对比区块前端另派)。

## 背景:两个 bug 根治

`scripts/simulate_trade.py` 模拟回测原费率逻辑(2026-07-28 加入)有两处与 2024 A 股现行标准不符:

| # | bug | 旧逻辑 | 2024 现行标准(用户拍板) |
|---|---|---|---|
| 1 | **漏印花税** | 卖出只扣 佣金+过户费,**无印花税** → 收益虚高 | 印花税 **0.05%(万5)** 卖出单边收(2023.8.28 减半后现行) |
| 2 | **过户费只沪市ETF** | `_is_sh_etf` 仅 51/58 开头沪市 ETF 收 0.001%(万0.1),深市 ETF 与纯指数不收 | 过户费 **沪深两市统一 0.001%(万0.1)** 买卖都收(2024 现行) |

滑点固定百分比(千1)原逻辑已存在(模块级 `SLIPPAGE=0.001`),本次纳入 fee_config 可配(仍用固定百分比模式,不用波动率模型)。

## 方案(核心 = 费率抽成 9 字段 fee_config 字典)

费率从模块级常量(`COMMISSION_RATE/SLIPPAGE/MIN_COMMISSION/TRANSFER_FEE_RATE_SH`)升级为 **`DEFAULT_FEE_CONFIG` 字典(9 字段,TASKS L637)**:

```python
DEFAULT_FEE_CONFIG = {
    'buy_commission':  0.0003,  # 买佣金万3
    'sell_commission': 0.0003,  # 卖佣金万3
    'stamp_tax':       0.0005,  # 印花税万5(卖出单边收,2023.8.28现行)
    'transfer_fee':    0.00001, # 过户费万0.1 = 0.001%,买卖都收
    'transfer_fee_mode':'hs_unified',  # sh/sz/hs_unified(默认沪深统一)
    'slippage':        0.001,   # 滑点千1(固定百分比)
    'slippage_mode':   'fixed', # 固定百分比(不用波动率模型)
    'slippage_sigma':  0.0,     # 波动率滑点sigma(fixed未用,预留)
    'min_commission':  5.0,     # 单笔最低佣金5元
}
```

`_normalize_fee_config()` 校验/补全(fee_config=None 用默认;非法 transfer_fee_mode/slippage_mode 抛 ValueError)。

### 改动点
- `_buy_with_fees(budget, close, etf_code, fee_config=None)`:佣金+过户费,**买入不收印花税**;过户费按 `transfer_fee_mode` 判定(_transfer_applies)。
- `_sell_with_fees(...)`:佣金+过户费+**印花税(卖出收)**;返回加第 6 元素 `stamp_tax`。
- `_transfer_applies(etf_code, mode)`:sh=仅沪市ETF/51\*/58\*, sz=仅深市ETF/15\*/16\*, hs_unified=所有 ETF(纯指数 None 仍不收)。
- `_build_result(...)` 加 `total_fees/total_turnover` 关键字参数,summary 新增 **`fee_cost`(累计费用元)+ `fee_pct`(费率占比=费用/双向成交额)**。
- 3 条模拟路径 `simulate_fixed_1w / simulate_all_in / simulate_sell_all` 加 `fee_config=None` 参数并累计 `total_fees/total_turnover`。
- **核心可调用函数 `_run_trade_sim_inner(index_id, fee_config=None)`**:5窗口×3路径×11信号组合全跑一遍,返回 `(stats_json, full_data)`,供 /api/trade_sim_recalc 与全量默认生成共用(单次可注入自定义费率)。
- `_generate_json` 改为调 `_run_trade_sim_inner` 的薄壳,写入 stats/full JSON。
- **费率对比函数 `compare_fee_configs(index_id, custom_fee_config)`**:默认 vs 自定义 双回测,输出 `default/custom` 各含 `fee_config+summary+equity_curve+net_value(相对初始资金倍数,1起点,供双曲线叠加)` + `diff`(收益/年化/回撤/胜率/费率成本/费率占比 六项差值)。
- **stats JSON 兼容字段**:保留旧 top-level `commission_rate/slippage/min_commission/transfer_fee_rate_sh` + 新增 `stamp_duty_rate` + 9 字段 `fee_config`(旧前端 app.js L24431-24433 读 `sd.slippage/sd.transfer_fee_rate_sh`,不破)。
- **FastAPI 路由 `/api/trade_sim_recalc`(app/main.py)**:POST body `{index_id, fee_config(可缺省)}`,调 `compare_fee_configs`,内存缓存 5 分钟(同 key 命中)+ 限流 10 次/分(超限 429);404 无数据。
  - `_trade_sim_module()` 用 **`.absolute()`(不 resolve 符号链接)** 定位 scripts/simulate_trade.py,保证 `from app.db import get_conn` 落回 cwd 侧(trade-data)读主库,非 trade 侧滞后镜像(§1/export-syspath-rootcause)。

## 验证(自测)

| 项 | 结果 |
|---|---|
| 印花税卖出万5 | 卖 1 万级出 stamp≈4.995,总扣=佣金5+过户0.1+印花5=10.09 ✓ |
| 过户费沪深统一 | 默认 hs_unified 沪市(510300)/深市(159919)ETF 买/卖都收 0.00001;**纯指数(None)不收** ✓ |
| 过户费 3 模式 | sh=仅沪/51\*/58\*, sz=仅深/15\*/16\*, hs=沪深都收 ✓ |
| 含印花税拖累收益 | A/B 同信号:含印花 return 53.04% fee 865.58 vs 无印花 53.34% fee 571.68 → 印花正确压低 0.3pp、加 ~294元 ✓ |
| compare_fee_configs | 返回 default/custom(+diff 六项+双 net_value)结构完整 ✓ |
| app/main.py 路由 | 空 index→400,无数据→404,第11次/分→429,同 key 缓存命中(模块仅调 1 次)✓ |
| 全量重生 | 167 成功/37 跳过(无数据)/1 失败;334 JSON 已 rsync+upload_r2(334/334) ✓ |
| 线上 R2 | curl ssd.fx8.store/trade_sim_data/trade_sim_sh_stats.json 含 `stamp_duty_rate=0.0005`+`fee_config`+`transfer_fee_mode=hs_unified` ✓ |

## 已知问题(§23.7⑤ 上报待用户拍板,未擅自修)

`g.cn_us_spread` 索引重生成失败:`type complex doesn't define __round__ method`。
- **根因**:`_build_result` 年化公式 `((final_total/TOTAL_CAPITAL) ** (1/years))`,该"中美利差"指数价格可为负值 → 负 base 的分数次幂返回 `complex`,`round(complex)` 崩。
- **证据**:`get_signals('g.cn_us_spread')` 正常(111 条,last 2026-08-18);**原版 origin/main 同一个 `_generate_json` 也崩**(同错误,`git show origin/main` 实跑复现);该索引此前从无 trade_sim JSON 输出(旧目录无此文件)。
- **结论**:本次费率根治**未引入**(fee 计算不产生 complex),是既有年化公式对负值价格指数的缺陷。**未擅自修**(§23.7⑤:发现 bug 完整证明链问用户确认)。若用户决定修,方案=年化口径对 negative ratio 兜底(如返回 0 或 `None`)。

## 复现

- 生成脚本:活变更在 `scripts/simulate_trade.py`(被 /api/trade_sim_recalc + update_lab.sh 引用,故不复制副本,报告只写指向)。
- 输入依赖:`trade-data/data/sentiment.db`(信号+index_daily)、`trade-data/data/board_etf_map.json`(ETF 映射)、`trade-data/static-site/data/global-all.json`(仅 g.* 商品)。
- 重跑命令(全量默认费率重生,**必须 cwd=trade-data** 使 app.db 读主库):
  ```bash
  cd /Users/linhuichen/code/trade-data
  /Users/linhuichen/code/trade-data/.venv/bin/python scripts/simulate_trade.py --all
  # 同步到 trade（update_lab.sh L272 同款模式）:
  rsync -a /Users/linhuichen/code/trade-data/static-site/data/trade_sim/ /Users/linhuichen/code/trade/static-site/data/trade_sim/
  cp /Users/linhuichen/code/trade-data/static-site/data/trade_sim_indices.json /Users/linhuichen/code/trade/static-site/data/trade_sim_indices.json
  # R2 上传（trade_sim_data/ 前缀）:
  REPO=/Users/linhuichen/code/trade-data /Users/linhuichen/code/trade-data/.venv/bin/python scripts/upload_r2.py upload-trade-sim-json
  ```
- 数据截止:信号 last_date=2026-08-19(上线日),sh 全史窗口 signal_last_date=2026-07-21(该指数无更新数据)。
- 关键口径一句话:买=佣金(买佣金,最低5)+过户费(按 transfer_fee_mode,买卖都收,默认 hs_unified 万0.1);卖=佣金(卖佣金,最低5)+过户费+**印花税万5**;滑点=固定千1(买入价×1.001 升高/卖出价×0.999 降低);费率成本 fee_cost=所有交易佣金+过户费+印花税之和,费率占比 fee_pct=fee_cost/双向成交额。
- 默认费率影响:全史窗口"买1万卖清仓/主买+卖"现 fee_pct≈0.074%(含印花税),收益较无印花税低 ~0.3pp。

## 落档(§23.5)
- 报告本体:本文件 `docs/trade-sim/trade-sim-fee-config-2026-08-19.md`
- 生成脚本:活脚本 `scripts/simulate_trade.py`(报告只写指向,不复制)
- 配套 commit:本报告与 simulate_trade.py / app/main.py 改动同 commit
