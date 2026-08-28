# sw_801030 断言4 FAIL 根因调研(2026-08-27 晚)

> 触发: 21:07 deploy.sh(trade-data 镜像跑)被 check_universe_alignment.py assertion4 阻断:
> 「应 empty_array(空数组) 却有 1 个ETF: sw_801030」。只读调研,未改任何文件。

## 结论

**定性 = (c):市场新上市化工行业 ETF(158017 化工ETF易方达),builder 正确收录,校验正确阻断;
yaml「空数组」名单里 sw_801030 的"无场内专属 ETF"现状声明过时,该从名单移除。**

三选排除依据:
- (a) builder 漏滤:不成立。build_board_etf_map.py 设计原则即"匹配到就全列出来、匹配不到留空数组"
  (@scripts/build_board_etf_map.py:5-8),它不读 yaml 名单属设计使然(yaml 自定位=「声明现状」,
  @config/universe_rules.yaml 头注);assertion 才是强制层。压制真实存在的化工 ETF 反而错。
- (b) yaml 过时该更新 / (c) 合法扩展校验没跟上:两者是同一事实的正反面,**同一修复动作**。
- 校验器行为正常:33 个 empty_array 声明键中**仅 sw_801030 一键违规**,其余 32 键全合规,
  absent 四类(cgb_/s./g./hk_)零残留——不是系统性漏滤,是单点现状变化。

## 证据链

1. **yaml 声明**: config/universe_rules.yaml「空数组」类别显式列 `- sw_801030    # 基础化工`
   (mode: empty_array;同段另含 sw_801130/801200/801230/801730/801950/801970/801980 等)。
2. **校验逻辑**: scripts/check_universe_alignment.py L183/L193-197 —— empty_array 类 id 必须
   「key 存在且为空数组」,非空即报 FAIL(assertion4,双向断言)。
3. **镜像新 map(trade-data,21:09 deploy 时生成)**: data/board_etf_map.json 里
   `sw_801030 = [{"code":"158017","name":"化工ETF易方达","amount":2.1,"approx":true,
   "match_method":"kw","track_score":null,...}]`(fund_type=etf)。
4. **主树旧 map(今晨 05:01 生成)**: 同键 = `[]`(所以本地看 map 与 deploy 报错不矛盾——
   ROOT 按 `Path(__file__).absolute().parent.parent` 解析到调用目录,deploy 在 trade-data 跑,
   刷新并校验的是镜像那份)。
5. **进入路径**: deploy_20260827_2107.log L323
   `基础化工 158017 化工ETF易方达 (2.1亿) <kw> <score=None>` —— akshare fund_etf_spot_em
   全量行情今晚起包含这只次新 ETF,名称含"化工"命中 TRACK_INDEX_KW 纯关键词层(sw_801030
   include=["化工"],build_board_etf_map.py:35),fundf10 track_index 未覆盖它(score=None/近似匹配)。
6. **全量对账**(33 键 empty_array vs 新旧 map + absent 四类):仅 sw_801030 违规,
   ftse100/kospi/csi_*×17/gz_*×5/sw_ 其余 7 键/thsc_306380 全部仍为 0;cgb_/s./g./hk_ 无残留键。
7. **旁支**: lof_track_index.json 镜像缺失(deploy log L30 降级告警"LOF 不纳入候选")是独立小项,
   与本 FAIL 无因果;主树有 08-12 旧版,镜像从未同步过(两树数据产物层分叉常态,memory 已知)。

## 影响面与不需动的地方

- **回测宇宙零影响**: inclusion_dependency 要求 track_score 非空(@universe_rules.yaml ②),
  158017 score=null → _bt_in_universe=False,不进凯利回测/首页 AI 建议,只影响前端"基础化工"
  组多展示一个 approx 近似候选。signal_kelly_trades/backtest 产物无需重跑。
- **公示无需动**: purpose-notes.js/lab.js/app.js 三文件 grep `sw_801030|基础化工` 均无字面引用
  (公示不逐键列空数组名单,修 yaml 不触发 §21 联动文案改动)。
- **§22 注意**: 镜像新 map(149 键,21:09)与主树旧 map(05:01)已分叉;修复后重跑 deploy 成功时
  export 会把新 map 正常推 R2/static-site,分叉自愈。

## 修复方向建议(一行级,未动手)

1. `config/universe_rules.yaml`:从「空数组」match 清单删除 `- sw_801030    # 基础化工` 行
   (建议原位留注释:`# sw_801030 已移除: 2026-08-27 起 158017 化工ETF易方达上市,kw 收录,score=null 不入样`)。
2. 重跑 deploy.sh → check_universe_alignment 应 PASS → export 把新 map 同步 R2/static-site。
3. (可选顺手项)trade-data 镜像补 `scripts/fetch_lof_track_index.py` 一次或忽略 LOF 降级告警。

## 复现

- 对账命令: `python3 -c "import json;m=json.load(open('/Users/linhuichen/code/trade-data/data/board_etf_map.json'));print(m['sw_801030'])"`
- 校验复现: `python3 scripts/check_universe_alignment.py --repo /Users/linhuichen/code/trade-data`
  (读镜像 data/,应复现 assertion4 FAIL)
- 日志: trade-data/data/logs/deploy_20260827_2107.log(L30/L52/L246/L323/L392/L243-248)
- 数据截止: 2026-08-27 21:09(镜像 map)/05:01(主树 map);口径: empty_array=key 存在且值必须为空数组。
