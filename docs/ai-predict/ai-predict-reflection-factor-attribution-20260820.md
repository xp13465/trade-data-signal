# AI 预测「反思=因子归因回灌」实现说明(TA Reflector 内核,2026-08-20)

> 对应 AQuA 反思机制(与方向锚同轮,AI 预测自升级路线图「后续轮次3」提前落地)。
> 目的:预测猜错方向时,把错**归因到具体误导因子**,且把「该因子近期待规避倾向」**回灌下次 build_prompt 的角色上下文**——补上用户质疑的「只肤浅套用 TradingAgents 多 agent 辩论、没学到 TA 反思内核(Reflector 按 bull/bear/trader/invest_judge/risk_manager 五方 memory 分别 reflect)」。

## 现状(改造前,证据点)
- 反思注入**已存在**(2026-08-17/18 建成):`record_reflections` → `_classify_failure`(规则级失败归因到 `failure_type`=direction_fail/partial/range_imprecise/direction_only)→ `build_reflection_inject`(按命中率三档 reinforce/normal/light/success 注入 `date:失败类型(summary)` 列表 + 语气提示)。
- **确实影响下次预测**(`build_reflection_inject` 注入到 `build_prompt` sys_text L1735 + `build_editor_messages` L1735 系统提示)。
- **缺口**:归因粒度=规则级,只到 `failure_type` + 一句 `expected_gap_summary` 文字(risk_items 依据),**没归因到「哪个具体因子误导了方向」**,也没把「该因子近期表现」回灌下次预测。这是 TA Reflector 的价值内核,此前漏了。

## 改造落地(本次 commit 9a47bae97)
| 文件 | 改动 |
|---|---|
| `scripts/gen_daily_brief.py` | ①新增 `_attribut_factor(db_path,date,pred,failure_type,actual_dir)`:对失败日用 `_compute_direction_anchor`(**与方向锚同源同 DB 只读**)现算当日因子状态,把方向/区间失败归因到 top 误导因子,随样本落盘为 `factor_attribution` 列表。②`_classify_failure` 在样本 dict 追加 `factor_attribution` 字段。③新增 `build_attribut_inject(reflections,date,cfg,history)`:聚合历史失败样本的 `factor_attribution`,统计 top 误导因子 + 连续出错倾向,生成「待规避因子」约束段。④`build_reflection_inject` 在既有注入文本后叠加该约束段(受 yaml 开关栅) |
| `config/daily_brief.yaml` | 新增 `reflection_factor_attribution_enabled: false`(默认关=线上注入文本逐字不变,可 A/B,同 `direction_anchor_enabled` 思路) |
| `README.md` | AI 速递编排受 TradingAgents-CN/原版 TradingAgents 多智能体辩论架构**启发**(多角色辩论收敛),但**预测所用方向锚信号胜率、因子权重为自研 8 年数据挖掘成果,非抄**;致敬 TradingAgents 段保留(§23.1) |

### 归因口径(`_attribut_factor`,只对失败样本,direction_only 无因子可归因)
- 预测看涨 + `nq_open_low`(L3 纳指期货大跌)→ 归因 **L3纳指大跌压制看多**(nq_chg 实时带出;2026-08-18 全席位大幅转多却次日 -2.4 暴跌即此因)。
- 预测看跌 + 当日有 `to_short`(机构仓位转空信号 T)→ 归因 **转空信号被当偏空**(方向锚 T2/T3:转空次日『逆势看涨』,全时段净流出≠偏空,8/14/8/17 验证;top20IC转空+均线多头=84%)。
- 预测看跌 + `to_long` + `ma_bull`(sh 收盘>20日线)→ 归因 **T1顺势看涨/均线多头强规则**(转多 64-66% 白名单)。
- 预测看涨 + `to_long` + 无 L3 压制却实际下跌 → 归因 **T1顺势看涨当日失效**(诚实标注:需连续多日观测是否长期失效)。
- partial → 归因 **板块/中间层失真**(方向对但板块层有误)。

### 回灌注入(`build_attribut_inject`,受 `reflection_factor_attribution_enabled`)
聚合 top3 误导因子(按出现次数),`count>=2` 标「连续多次,建议重点规避」,生成「待规避因子」约束段
(降低该因子权重或以反向结论交叉验证,勿依它单向定论)叠加进 `build_reflection_inject` 注入文本。
与方向锚**互补不互斥**:归因列"某因子当天误导了方向",注入列"该因子近期待规避";两者同源同 DB 只读,共走 `_compute_direction_anchor`。

## 与方向锚咬合(不互斥证据)
- 归因的因子词汇全部取自 `_compute_direction_anchor` 的语义(L3 纳指大涨/转空逆势/T1 顺势/均线多头),与方向锚教学段**同一套语义体系**,注入的是"规避已证误导的因子",方向锚是"正向教正确因子方向",两者不同层不冲突。
- 实测三样本(真实 DB):8/18 pred=up → L3纳指大跌压制看多 ✔(nq_chg=-1.302);8/17 pred=down → 转空信号被当偏空 + T1顺势看涨/均线多头 ✔;8/14 pred=down → 同 8/17 ✔。归因与 8/14/8/17/8/18 方向锚回放结论一致。

## 开关与线上行为
- `reflection_factor_attribution_enabled` 默认 `false`(yaml),`cfg` 无该 key 时 `setdefault(False)`;实测 cfg 无 key 与显式 False 时 `build_reflection_inject` 输出**逐字一致**,off 时不含「待规避因子」段 → 线上注入文本与改造前逐字不变(§23.7 零改动)。
- on 时叠加归因约束段,`review_enabled=false` 或 `REFLECTION_INJECT_ENV=0` 时不注入(继承既有 guard)。

## 测试/口径
- 测试基准=current baseline(memory `test-baseline-v112-anchor`)。
- 动 AI 预测核心(反思环节新增默认关注入层,不改变默认行为)→ 需发版本标记(§5.4⑥),本轮只改后端 prompt 数据层注入,**不改前端公示文案**(purpose-notes.js 无"反思/待规避因子"公示点,已 grep)。版本串由主控 merge 走 main-merge.sh。
- 三档联动(命中率 reinforce/normal/light/success)与既有维度对齐;优秀档(≥90%)不注入失败归因(避免干扰成功模式,同 `build_reflection_inject` 优秀档口径)。

## 落档
- 报告:本文件(`docs/ai-predict-reflection-factor-attribution-20260820.md`)。
- 代码:commit 9a47bae97(scripts/gen_daily_brief.py + config/daily_brief.yaml + README.md)。
- 索引:更新 `docs/ai-predict-self-upgrade-roadmap.md` §四追加本轮实施记录。

## 复现
- 脚本(活脚本,非本目录副本):`scripts/gen_daily_brief.py`。
- 输入依赖:生产只读 DB `trade-data/data/sentiment.db`(futures_position/daily_metric/index_daily)。
- 复现命令(回归归因逻辑,不改写盘):
  ```bash
  cd /Users/linhuichen/code/trade
  source ../trade-data/.env 2>/dev/null || true
  python3 -c "
  import sys; sys.path.insert(0,'.')
  import scripts.gen_daily_brief as g
  db='/Users/linhuichen/code/trade-data/data/sentiment.db'
  for d,pred,ft,act in [('20260817','down','direction_fail','flat'),('20260814','down','direction_fail','up'),('20260818','up','direction_fail','down')]:
      for a in g._attribut_factor(db,d,pred,ft,act):
          print(d, a['factor'], a['dir'])
  "
  ```
- 数据截止:2026-08-20(DB mtime 18:14)。关键口径一句话:归因=对失败日现算方向锚因子,「预测方向 vs 当日因子语义方向」冲突即归因到误导因子,聚合 top 回灌下次预测。
