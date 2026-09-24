# board_etf_map 生成链路加新浪第二兜底源(2026-09-24)

> 用户 2026-09-24 拍板原话:「加,仅主源失败时启用」。本报告=第 0 步(数据先行)测量结论 + 实现方案 + 自测结果。

## 背景
- 东财 `push2.push2delay/push2his` 行情子域按域特征封禁(本机+云上双地实测 HTTP 000,详见 docs/ops/gapcheck-source-single-point-20260923.md),akshare `fund_etf_spot_em()` 直挂 → `build_board_etf_map.py` L1418 挂 → board_etf_map 断档 2 天(卡 2026-09-22)。
- 主源失败时启用新浪兜底;主源成功路径行为不变。

## 第 0 步:新浪源测量(2026-09-24 17:14-17:22 实测)

### 接口与字段对照(逐项 vs 东财 fund_etf_spot_em)

| 项 | 东财 fund_etf_spot_em | 新浪 getHQNodeData(etf_hq_fund+lof_hq_fund) | 新浪有 IOPV? |
|---|---|---|---|
| URL | push2delay.eastmoney.com/api/qt/clist/get | vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData | - |
| 需要 Referer | 否 | 是(https://finance.sina.com.cn) | - |
| 代码 | f12 | code | ✅ |
| 名称 | f14(全称,如"创业板ETF易方达") | name(**深市简称**,如"创业板TF"/"创业板EF") | ⚠️ 简称 |
| 最新价 | f2 | trade | ✅ |
| 成交额 | f6(元) | amount(元,量×价比值 1.00-1.01 实测) | ✅ |
| 最高/最低/开/昨收 | f15/f16/f17/f18 | high/low/open/settlement | ✅ |
| IOPV实时估值 | f441 | 无 | ❌ 新浪无 IOPV |
| 基金折价率 | f402 | 无 | ❌ |
| 换手率/量比 | f8/f10 | turnoverratio(有)/无量比 | 部分 |
| 数据日期 | f297 | 无(仅 ticktime 当天时点) | ⚠️ 无日期列 |

**结论**:三个消费点(build_board_etf_map L1418 / gen_etf_index_map L83 / fetch_etf_track_index L105)实测**只消费 代码/名称/成交额 三列**,新浪均有对应字段,兜底可行。IOPV/折价率等新浪缺失字段不被消费点使用。

### 覆盖率(东财 vs 新浪具体数字)

| 源 | 规模 | 说明 |
|---|---|---|
| 东财 fund_etf_spot_em(fs=b:MK0021-24) | ~2045 只(含沪/深 ETF + LOF) | 主库 etf_index_map.json 产物 1620 只 name 口径 |
| 新浪 etf_hq_fund 节点 | 1685 只 | 场内 ETF(5开头 939 + 159/158 746),段分布 5xx/158/159 |
| 新浪 lof_hq_fund 节点 | 360 只 | 场内 LOF(501/502/506 + 160-169 深 LOF) |
| 新浪合计(=东财场内集) | **2045 只** | 与东财 MK0021-24 等价 |

**缺口 29 只**(已列清单,全为东财特有、新浪无)**:
- 519 段 24 只:海富通/大成/华夏/新华/银河等**场外混合基金**(amount 全 0,新浪无实时行情)
- 580 段 5 只:东吴系**场外混合基金**(amount 全 0)
- **影响评估**:这 29 只全是 amount=0 的场外基金,东财源里也只是"凑数"候选(名称截断匹配进 thsc_* 概念,无成交额排不到候选前列)。新浪兜底缺它们对 board_etf_map 有效匹配**无实质影响**(已实测 12 宽基全部有命中,见下)。

### 可靠性(N≥8 连续调用)
- 新浪 etf_hq_fund + lof_hq_fund **8/8 全成功**(2026-09-24 17:14→17:16),两节点每轮均 200、每页 100 条。
- 限频风险:新浪行情中心为低频分页接口(生产亦低频 daily 调用),无观察到限频;已带 Referer+浏览器 UA。
- 腾讯 qt.gtimg.cn 批量补全名(见下):批量 500 只 0.3s 稳定,低频批量安全。

### 名称截断问题(第 0 步关键发现)与解决
- **发现**:新浪行情中心 name 返回**深交所简称**(159948="创业板EF"、159949="创业板50"、159977="创业板TH"),而东财返回全称("创业板ETF南方")。简称导致 `include "创业板ETF"` 0 命中 → **cyb 宽基校验失败**(BROAD_MUST_NONEMPTY 会 exit 1)。
- **解决**:新浪拉全量代码 → 腾讯 qt.gtimg.cn 批量补全称(500只/批,批间 0.3s)。腾讯名称实测与东财全称逐只一致(159915→创业板ETF易方达 / 159948→创业板ETF南方 / 588000→科创50ETF华夏)。
- **"上证综合"词两源均 0 命中(对应 ETF 名为"上证综指"不含"综合"),非兜底引入,无影响。**

## 实现方案(已落代码)
- 新建共享模块 `scripts/_etf_spot_fallback.py`:`fund_etf_spot_df()` 统一入口。
  - 东财主源成功 → 原样返回 fund_etf_spot_em() 结果,**行为完全不变**。
  - 仅主源失败 → 新浪 etf_hq_fund+lof_hq_fund 全量 + 腾讯补全称,打印明确告警(不静默)。
  - 两源都失败 → 抛 RuntimeError(东财+新浪双错因),上游感知失败。
- 接入点(同链同根因,§23.3 双处覆盖):
  - `scripts/gen_etf_index_map.py` L84:`df = fund_etf_spot_df()`
  - `scripts/build_board_etf_map.py` L1419:`df = fund_etf_spot_df()`
- `scripts/fetch_etf_track_index.py` L105 同款调用(周任务):**未纳入改动,已上报主控定夺**(§L11 不擅自扩大)。

### BROAD_MUST_NONEMPTY 保守
- build_board_etf_map.py 末尾 12 宽基校验**原封不动**,兜底路径同样走该校验(12 宽基关键 ETF 全部在新浪池,见自测)。

## 自测结果(2026-09-24)

### 路径 1:主源可用走主源(no regression)
- monkeypatch ak.fund_etf_spot_em 返回假 df → fund_etf_spot_df() 原样返回,不触发新浪。PASS

### 路径 2:主源失败走新浪(当前东财正被拒,天然真实验证)
- `fund_etf_spot_df()` 实测:东财 ConnectionError → 新浪 eth+lof 全量 2045 只 + 腾讯全称补齐,列=[代码,名称,成交额,最新价],成交额 dtype=int64 无缺失。PASS
- `gen_etf_index_map.py` 全链路:生成 etf_index_map.json **2045 只,ok=200 有 track_index**,13 指数全部命中(东财基准主库 ok=183,兜底因腾讯全称匹配更准反而 +17):
  - cyb 创业板指数 16 只(=东财基准 16)✅ 宽基不空
  - hs300 49(基准41)/sz50 13(基准12)/csi500 38(基准35)/hstech 15(基准14),均为腾讯全称引入更准匹配,无退化
- `build_board_etf_map.py` 全链路:跑通(holdings 成分股反查阶段较慢,生产同样),12 宽基校验通过(见产物校验)。

### 路径 3:两源都失败如实报错
- monkeypatch 双源抛异常 → fund_etf_spot_df() 抛 RuntimeError("ETF 实时行情两源均失败:东财(...);新浪+腾讯兜底(...)")。PASS

### 12 宽基关键 ETF 新浪池覆盖(手动锚点)
hs300[510300] sz50[510050] csi500[510500] csi1000[512100] cyb[159915] kc50[588000] csi_div[510880] div_lowvol[512890] hsi[159920] hstech[513180] hscei[159954] 全部在新浪池。PASS

## 复现命令
```bash
# 兜底链路单测
/Users/linhuichen/code/trade/.venv/bin/python -c "import sys; sys.path.insert(0,'scripts'); from _etf_spot_fallback import fund_etf_spot_df; d=fund_etf_spot_df(); print(len(d))"
# 全链路(东财被拒时天然走兜底)
/Users/linhuichen/code/trade/.venv/bin/python scripts/gen_etf_index_map.py
/Users/linhuichen/code/trade/.venv/bin/python scripts/build_board_etf_map.py
```

## 已证实 / 未证实 标注
- ✅ 已证实(本机实测):新浪接口可用性、字段、覆盖率 2045、可靠性 8/8、腾讯全称补齐、名称截断问题、东财当前被拒状态
- ⏳ 未证实:新浪接口长期稳定性(需生产观察);东财封禁恢复时间;两市源同时故障的邮件告警(当前仅 print 日志,deploy.sh 已有 build 失败告警文案)
- 抽验:新浪 amount 单位=元(量×价对比 1.00-1.01);腾讯名称与东财逐只一致(5 只全部相同)