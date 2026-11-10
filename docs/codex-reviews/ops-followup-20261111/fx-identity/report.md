> 原始取证目录：`/tmp/codex-reports/ops-followup-20261111/fx-identity`，另有只读私有归档。下文原始响应、完整 JSON、merge-tree 和 fixture 引用均指该证据目录；仓库仅保存审计正文与脱敏结果。

HC18 补充核查：FX 来源身份（只读交接）

核查完成；当前 HC18/usdcnh 品种契约验收为 **BLOCKED**。固定基线 `f35437a699d199076b5654dcde58780be89ee6b4`；核查时间 2026-11-11T07:21:37.692794+08:00。只在本目录写证据与报告。

**[P1] FX-ID-01：新浪在岸 CNY 被写入名为离岸 CNH 的指标。**

已确认的不是符号拼写推断，而是供应商产品绑定：

| 供应商产品 | 页面代码绑定 | 接口名称 | 本次返回的源时间 |
|---|---|---|---|
| [新浪 USDCNY](https://finance.sina.com.cn/money/forex/hq/USDCNY.shtml) | `_symbol="fx_susdcny"` | 在岸人民币 | 2026-11-11 03:00:00 |
| [新浪 USDCNH](https://finance.sina.com.cn/money/forex/hq/USDCNH.shtml) | `_symbol="fx_susdcnh"` | 离岸人民币（香港） | 2026-11-11 07:19:23 |
| [东财 USDCNH](https://quote.eastmoney.com/forex/USDCNH.html) | `quotecode="133.USDCNH"` | 美元兑离岸人民币 | `f86=1794352769`，换算北京时间 2026-11-11 07:19:29 |

[Sina 公共行情响应](https://hq.sinajs.cn/list=fx_susdcny,fx_susdcnh,USDCNY,USDCNH)采集于北京时间 07:19:30，原始日期/时间字段没有时区偏移，表中前两行保持原样。CNY `[3]=[8]=6.6805000000`；CNH `[3]=6.676300`、`[8]=6.676400`。这些数值仅作快照，不作为身份依据。[东财响应](https://push2delay.eastmoney.com/api/qt/stock/get?secid=133.USDCNH&fields=f57,f58,f59,f43,f60,f86,f170)明确返回 `f57=USDCNH`、`f58=美元兑离岸人民币`、`f59=4`、`f43=66760`（6.6760）。

固定源码的调用链：`intraday_snapshot.py:162 FX_CODE` → `:633` 请求 → `:569` 只匹配 `hq_str_fx_susdcny` → `:590` 保留源名称但不验证 → `:1668 upsert_metric(today,"usdcnh",price,source="intraday")`。配置 `config/indicators.yaml:96` 和 UI `static-site/app.js:1313,21316,21328` 均称离岸；跑马灯 `:16356` 则使用供应商明确为 CNH 的 `133.USDCNH`。这些是不同品种口径，不能因为价格相近就视为同源。

`docs/global-ticker-free-source-research.md:21,36` 的“差 0.005 ✓”和“显示在岸但实为离岸”不足以支撑该映射，且与当前第一方产品页、代码绑定及响应标签相矛盾。以上都是既存问题；本轮不是 diff review，也未重新证明任何买卖方向。

**解析器的直接相关风险。** [新浪产品页加载的脚本](https://n.sinaimg.cn/finance/forex_n/getData_20241021.js?v=20241021) 第 15–16 行使用 `d[8]` 为展示价、`d[3]` 为 `spj`；产品页模板第 56 行把 `spj` 标为“昨收”。仓库 `intraday_snapshot.py:585,588` 使用相反映射。这是已确认的页面契约不一致，但本轮不认证完整字段协议，也不外推已有信号受影响程度。单改 `FX_CODE` 仍会被 `:569` 的旧前缀过滤，并且 `:595` 返回旧 code；不能当作完整修复。

**仍未确定的范围。**

- HC18 实际应使用离岸 CNH 即期、在岸 CNY 即期，还是明确命名的中行折算价代理指标，需要产品负责人决定。当前代码混用了三种口径。
- 产品身份已确认；上游报价机构/交易场所、可成交价或指示价、完整字段定义、日收盘时点和可用性保证尚未认证。CNY 响应 `[13]` 明示“此行情由新浪财经计算得出”，不能进一步宣称是某交易场所的成交价。
- 当前页面不能追溯证明每一条历史报价；本轮未下载历史序列。也未决定正确契约下原 sell 会否消失。前轮 Codex 已完成的 887 条 BOC + 1 条盘中记录、单位修正后仍 sell 的实验仅作为既有上下文，没有重跑。
- 时间戳不同；收取时间不能替代源时间，价格接近不能证明同一品种。东财 `forex/USDCNY.html` 的浏览结果重定向至中间价 `USDCNYC`；其搜索 API 也返回 `120.USDCNYC`，不得据 URL 拼写推成在岸即期。

**供 Claude 评审的近期止损方案（未执行）。**

1. 把 HC18/usdcnh 的方向性贡献作为数据契约未验证处理，显示不可用/待核查；不要强制改买、改中性或捏造替代值。父任务需检查实际消费者与已持久化信号，不能假设一个 `enabled` 配置就覆盖所有路径。
2. 隔离 CNY 写入 CNH 指标，并防止 BOC/回退路径继续生成混合序列。仅停后续写入不足以撤销已经生成的结果。
3. 原样保留 DB 和证据，不做历史除以 100、不把旧序列重命名为正确历史，也不把新的 CNH 即期拼到 BOC 历史上。正确标识的东财 CNH 跑马灯保持独立。

**解除阻断所需产品契约。** 负责人先选定品种及规范名称；再确定每 1 USD 或每 100 USD 的单位、bid/ask/mid/last/折算价类型、交易日/时区/日收盘时点、供应商代码与名称白名单、时效与缺失策略、来源溯源。日线与盘中必须同契约；历史重建、阈值校准和重新启用 HC18 应由父任务在隔离序列验证后决定。若选择 Sina CNH，需连同解析前缀、返回 code 和价字段一起核对，以错品种、过期时间、最新价不等于昨收的样本验收。

**检查与复现。** 本次按用户明确指定的补充任务执行。固定 SHA 源码及 UI 文案只读核查；供应商页面、原始响应、HTTP 头、SHA-256 和抓取时间均保存在本目录 `*.meta.json`、`*.raw`、`*.txt` 中，清单在 `report.json.primary_source_evidence`。

```sh
curl -fsSL --max-time 20 -e 'https://finance.sina.com.cn/' 'https://hq.sinajs.cn/list=fx_susdcny,fx_susdcnh,USDCNY,USDCNH' | iconv -f GB18030 -t UTF-8
curl -fsSL --max-time 20 'https://finance.sina.com.cn/money/forex/hq/USDCNY.shtml' | iconv -f GB18030 -t UTF-8 | rg '<title>|var _symbol|it.spj'
curl -fsSL --max-time 20 'https://finance.sina.com.cn/money/forex/hq/USDCNH.shtml' | iconv -f GB18030 -t UTF-8 | rg '<title>|var _symbol|it.spj'
curl -fsSL --max-time 20 'https://n.sinaimg.cn/finance/forex_n/getData_20241021.js?v=20241021' | rg '_data.price|_data.spj|_data.updownCount'
curl -fsSL --max-time 20 -e 'https://quote.eastmoney.com/' 'https://push2delay.eastmoney.com/api/qt/stock/get?secid=133.USDCNH&fields=f57,f58,f59,f43,f60,f86,f170'
```

初次 urllib 遇到本机证书链校验错误，随后系统 curl 正常 TLS 校验成功，没有关闭证书校验。未运行完整应用、信号生成、单元归一化实验、浏览器渲染或 fastcheck；未读取/改写 DB；未修改源码、Git 或运行态；未调用通知、publish、ACK、回传脚本或子代理。结论交 Claude 复核和处置。

## 父任务补核

固定 f35437a 的 `app/compute/signals.py:778–781,1430–1440` 使用固定 `GLOBAL_METRIC_IDS` 循环读取 usdcnh；`app/collector/intraday_snapshot.py:1648–1669` 的盘中写入不检查 YAML enabled。仅把 config/indicators.yaml 的 enabled 改 false 不能覆盖这两条路径。还须核对既存 signal_daily 的消费端和已导出信号；本轮未替换线上结果。

从固定源码 AST 只提取 `_parse_sina_fx` 做纯函数验证：当前 CNY 响应可解析；单独 CNH 响应被旧前缀拒绝；区分 `[3]=7.1/[8]=7.2` 的合成样本返回 price=7.1/pre_close=7.2，与供应商页面展示合同相反。3 个预期反例均复现，不等于修复后测试 PASS；不执行 collector 或数据库写入。原始记录见私有归档 `fx-parser-parent.json`。
