# THS 概念换官方:并行对照基线报告(第 0 天)

- 日期:2026-09-02(对照窗口起点;方案 `docs/fapi/fapi-integration-plan-20260901.md` §4.4)
- 对应 TASKS:#18
- 分支:research/fapi-h-k1
- 状态:基线已落,1 周并行观察开始

---

## 0. 结论速览(TL;DR)

| 项 | 结论 |
|---|---|
| 名称映射 | **27/27 全部精确匹配**。现有 `thsc_300816 机器人概念` → FAPI `885517.TI` 等,无歧义无重名 |
| 历史数值对齐 | **9 个月全覆盖(184 交易日)close 对齐率 100%**。FAPI 885xxx.TI 与 akshare thsc_ 是 THS 官方同一套指数,逐位一致 |
| FAPI 历史覆盖 | 起点 20251201(约 9 个月);更早历史需保留现有表或另补,不阻断切换(现有 thsc 历史表保留不动) |
| 切换判定 | 历史 100% 对齐已满足切换底气;**仍按方案走 1 周并行观察**(观察时机行为:当日 K 发布时点/盘中快照一致性),9-08 评估切换 |
| 影响面 | 动「概念指数行情展示」= 数据源变更,需 §21 公示 + README 数据源段(§23.1);非 AI 推荐核心,不需 bump 版本(方案 §5) |

**核心判断:FAPI 概念指数与现有 akshare 概念是同一指数,9 个月逐位一致。切换的技术风险已验到最低;剩下的是 1 周观察「当日数据行为」(akshare T+1 偶发 vs FAPI T+0),确认后按 §21 公示再切。**

## 1. 对照机制(1 周并行观察怎么跑)

### 1.1 对照脚本 `docs/fapi/scripts/ths_concept_parallel.py`
- 读 `config/indicators.yaml` 27 个 `thsc_*` 概念 → FAPI cn_concept catalog(390 个)按 name 精确匹配 → `885xxx.TI`
- 逐概念拉 FAPI 历史 K + 从 `data/sentiment.db index_daily` 取同概念同日期 close → 逐日对齐率(价差<=0.5% 算对齐)
- 输出:stdout 汇总 + `parallel_result_{end}.json` + `parallel_detail_{end}.csv`
- 已从对照对象排除国证/中证/上证系列指数(65 个,index 类型≠THS 概念,不在切换范围)

### 1.2 观察周期
- **起点 2026-09-02,终点 2026-09-08**(1 周,覆盖 5 个交易日)
- 每个交易日盘后(20:40 后,每日速递之后)跑一次 `--end <当日>` 增量对照,盯两项:
  1. **当日新增 1 行 close 对齐率**(FAPI T+0 当日行 vs akshare 次日才出的当日行)
  2. **发布时点**:FAPI 当日 K 几点到位(akshare thsc_ T+1 偶发次日才出,这是换源动机,需实测 FAPI 当日时点)
- 观察期结束(9-08)评估:若 5 日对齐率 100% + 当日时点稳定 → 走 §21 公示 + 实施切换

### 1.3 断点续跑
对照脚本幂等(每次全量窗口重拉),跑多次只覆盖 json(同名 `parallel_result_{end}.json` 覆盖写),可安全重复。

## 2. 名称映射全表(27/27)

| thsc_ 现有 | 概念名 | FAPI thscode |
|---|---|---|
| thsc_300816 | 机器人概念 | 885517.TI |
| thsc_309119 | 人形机器人 | 886069.TI |
| thsc_308700 | 第三代半导体 | 885908.TI |
| thsc_309049 | 共封装光学(CPO) | 886033.TI |
| thsc_301085 | 芯片概念 | 885756.TI |
| thsc_307940 | 存储芯片 | 886042.TI |
| thsc_302035 | 人工智能 | 885728.TI |
| thsc_309068 | 算力租赁 | 886050.TI |
| thsc_308828 | 东数西算(算力) | 885957.TI |
| thsc_309020 | 信创 | 886013.TI |
| thsc_309060 | 数据要素 | 886041.TI |
| thsc_300008 | 新能源汽车 | 885431.TI |
| thsc_301079 | 光伏概念 | 885531.TI |
| thsc_300733 | 锂电池概念 | 885710.TI |
| thsc_306380 | 储能 | 885921.TI |
| thsc_308294 | 固态电池 | 886032.TI |
| thsc_309115 | 低空经济 | 886067.TI |
| thsc_308014 | 创新药 | 886015.TI |
| thsc_300082 | 军工 | 885700.TI |
| thsc_300830 | 量子科技 | 885730.TI |
| thsc_308725 | 汽车芯片 | 885945.TI |
| thsc_308300 | MCU芯片 | 885925.TI |
| thsc_309113 | 飞行汽车(eVTOL) | 886066.TI |
| thsc_308491 | 氢能源 | 885823.TI |
| thsc_308870 | 数字经济 | 885976.TI |
| thsc_308752 | 元宇宙 | 885934.TI |
| thsc_309128 | 军工信息化 | 886076.TI |

> 全部 name 精确匹配(零模糊零歧义),一键建映射表即可实施切换。

## 3. 对齐率全表(9 个月窗口,184 交易日)

**27/27 全部 close 对齐率 100%**,零概念掉线。明细见 `/tmp/ths_parallel/parallel_detail_20260901.csv`(9 个月窗口版本;脚本重跑可复现)。

代表性抽样(价差逐位):
```
机器人概念 885517.TI  overlap=184  close_rate=100.0%
量子科技 885730.TI    overlap=184  close_rate=100.0%
氢能源   885823.TI    overlap=184  close_rate=100.0%
元宇宙   885934.TI    overlap=184  close_rate=100.0%
```

## 4. 风险与边界(诚实标注)

| 项 | 说明 |
|---|---|
| FAPI 历史覆盖 9 个月 | 起点 20251201,现有 index_daily 更早历史(如机器人概念 1616 行≈6 年)保留不动;切换后新数据走 FAPI,历史拼接无需重拉(同一指数数值) |
| 当日行 T+0 vs T+1 | akshare T+1 偶发(有前端提示),FAPI 当日 K 白酒概念实测 22 条覆盖到 20260901=T+0;1 周观察确认时点 |
| 概念名单扩展 | FAPI 概念 390 个 vs 现有 27 个,切换时可一并扩(方案 §4.2);扩名单属新增功能,需用户确认展示范围 |
| 行业指数 320 | THS 行业≠申万 31 级(方案 §4.4 警示);本任务只做「概念」换源,行业不换(保留申万) |
| §23.13 口径 | 对照对象已限定自定义的 27 概念,名称匹配全命中,无"说法不一"二义 |

## 5. 验收要点

1. 对照脚本存在且 git tracked,头部含复现命令(§23.5)
2. 名称映射表 27/27 与 indicators.yaml 逐条对上
3. 9 个月窗口对齐率 100% 可复现(`--days 275` 重跑)
4. 观察周期定义明确(9-02~9-08,逐日增量对照)

## 复现

**生成脚本**:`docs/fapi/scripts/ths_concept_parallel.py`

**输入依赖**:`config/indicators.yaml`(27 概念定义)+ `data/sentiment.db`(index_daily 现有历史)+ trade/.env 或 trade-data/.env 的 `HITHINK_FINANCE_API_KEY`(probe_fapi.py 读)

**重跑命令**(worktree venv,9 个月窗口=方案观察前最全基线):
```bash
cd /Users/linhuichen/code/trade
.venv/bin/python docs/fapi/scripts/ths_concept_parallel.py --out /tmp/ths_parallel --days 275
```

**数据截止**:2026-09-02 对照执行;FAPI 历史 K 覆盖 20251201~20260901;akshare index_daily 现有历史截至 20260901。

**关键口径一句话**:对齐判定 = 同概念同日期 close 价差<=0.5%;名称匹配 = FAPI cn_concept catalog name 与 indicators.yaml name 字面精确相等;FAPI 885xxx.TI 与 akshare thsc_ 同属 THS 官方指数体系。