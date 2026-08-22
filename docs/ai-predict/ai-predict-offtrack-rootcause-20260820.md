# AI 每日预测「越错越离谱」根因调研报告(2026-08-20)

> 调研 agent 产出,只读不改,证据全可复核。主控验收用。
> 一句话结论:**不是"AI 变笨",是「关键前置信号(聪明钱/期货逆向)喂了但语义没教对 + 学习闭环(反思/辩论)没把历史正确信息沉淀进下次」**。三个机制缺环叠加,叠加 8/14~8/19 极端波动行情放大观感。

## 根因(结论)

### ① 可确证的机制根因(有数据/代码证据)
1. **中信期货逆向信号被 AI 系统性忽略(最核心)**
   - 数据源存在且已注入(fund 域含 `futures_acc_trend`/`inst_ih_trend`,含中信/机构top20/国泰君安),但 prompt 只写了一句"逆向=相反"(gen_daily_brief.py L588),**没有任何"逆向指标要反着用"的语义教学** → 模型把"中信转空/净流出"当偏空依据,实际逆向应看涨。
   - 实证(static-site/data/futures.json citic_ih_detail 8月逐日):
     - 8/10 中信多+6068 → 8/11 跌-0.82(逆向对),AI 预测 flat
     - 8/14 中信空-213 → 8/17 涨+1.41(逆向对),**AI 预测 down(方向全反)**
     - 8/17 中信空-564 → 8/18 +0.19(逆向对),AI 猜 up 区间 0.3~0.8 实际 0.19
     - 8/18 中信多+4858 → 8/19 跌-2.40(逆向对),AI 猜 down 方向对但区间 -0.8~-0.3 vs 实际 -2.4(差3倍)
   - 8/14 预测的 risk 依据原文(见 history meta):"中信期货 d5_chg=-6.6% 资金面偏空" → **把逆向信号当偏空解读,这是 8/14 猜跌实际大涨的直接原因**。
2. **reflections 反思只记录"错了",没提炼"归因变量"**
   - 注入格式(build_reflection_inject L2731-2755)只拼接 `date:failure_type(expected_gap_summary)`,是"失败描述"不是"下次考虑变量"。
   - 更糟:8/14 的归因(expected_gap_summary)把"中信期货d5_chg=-6.6% 资金面偏空"写进"预测依据"——**归因本身学错了**(逆向偏多被记为偏空),注入给下次预测等于固化错误认知。
   - 用户怀疑点1 坐实:闭环只到"知道错了",没到"知道为什么错→下次带上修正变量"。
3. **debate 多空辩论正确声量没胜出**
   - 8/14 debate 记录(history meta.debate):bull 论据含"龙虎榜机构净买5.22亿、通信净流入117.7亿、创业板领涨、汪汪队入场L4 84.6" ;bear 论据含"机构前20净关注转空、中信期货d5_chg=-6.6%、主力净流出202.92亿"。
   - 结果主编选 down(bear侧)——因为 bear 侧引用了**被误读的中信信号**,模型无"聪明钱逆向"先验,把资金面流出当强看跌。
   - 用户怀疑"正确声量未胜出"坐实:bull 论据在,但权重/先验不足,且唯一能扭转方向的"中信逆向"被 bear 侧错误征用。

### ② 疑似但需更多样本的
- **区间系统性低估极端波动**:8/18 猜 -0.8~-0.3 实际 -2.4;range 宽度硬限 hi-lo≤0.5%(RANGE_MAX_WIDTH=0.5, L1647)+ "越窄越显真本事"提示词,可能让 AI 在极端日不敢给宽区间。8/19 猜 -1.5~-1.0(给宽了)仍低估。方向对区间差3倍,是"正常方差 + 极端日 + 窄区间约束"混合,需更长样本看是否系统性偏窄。
- **跨周末预测**(8/14 周五预测 8/17 周一):周末消息面不可预知,8/17 新闻归档有催化。这是固有难度,但中信逆向信号在 8/14 收盘时已知,不构成"不可见"。

### ③ 正常方差非 bug(明确标注)
- **8/18 北证50 猜涨+1.5~+2.0 实际 -4.9%**:8/18 当日北证50 +2.67%(index_daily 实证),AI 追涨;8/19 全市场暴跌(sh -2.4/cyb -6.26/kc50 -6.89/bj50 -4.9)是极端日反转,属边界情形。
- **8/19 的 hit=null**:今天 8/20 12:59,尚未到 20:40 回填,正常未回填,非 bug。
- **reflections 只有 6 条 vs history 8 条**:8/18 缺失是 walk-forward 时间隔离(record_reflections `bvia >= today` 跳过,bvia=8/19,8/20 才落盘);8/19 未回填。非 bug,是设计。

## 证据(可复核点)

| # | 结论 | 证据位置 | 数据值 |
|---|---|---|---|
| 1 | stats 0.0% 是"三层全中"口径,非方向命中率 | gen_daily_brief.py `_history_stats` L2173-2192 | 严格口径仅"含区间+三层全中"计中;8/11/12/13 老条目 direction=true 但无 range → 计分母不计中;n=7 hit=0 |
| 2 | reflections 用方向命中口径 | gen_daily_brief.py `_recompute_reflection_stats` L2600-2617 | 60-69 档 n=5 hit=3 hit_rate=0.6 |
| 3 | 中信逆向信号存在 | static-site/data/futures.json citic_ih_detail | dominant_dir=逆向 follow_ratio=33.3 accuracy=66.7%;8月5/8天逆向判对 |
| 4 | AI 在逆向判对日连续错 | history 8条 meta.direction vs futures.json | 8/10/8/14/8/17 AI 方向错(中信逆向均对);8/18 方向对区间差3倍 |
| 5 | 8/14 把逆向当偏空 | history 8/14 meta.risk_items + docs/ai-predict-self-growth.md L108 | "中信期货 d5_chg=-6.6% 资金面偏空" |
| 6 | 反思注入是描述非变量 | gen_daily_brief.py `build_reflection_inject` L2731-2755 | `date:failure_type(expected_gap_summary)` 拼接 |
| 7 | debate bull/bear 都有 | history 8/14 meta.debate | bull含龙虎榜净买5.22亿;bear含中信d5_chg=-6.6% |
| 8 | 8/18 北证50 当日+2.67% | index_daily (trade-data/sentiment.db) | 20260818 bj50=+2.6717 |
| 9 | range 宽度硬限 | gen_daily_brief.py L1647 RANGE_MAX_WIDTH=0.5 | hi-lo≤0.5,正负方向;flat≤0.2 |
| 10 | 8/18 reflections 缺失=时间隔离 | gen_daily_brief.py `record_reflections` L2641 | `if bvia >= today: continue` |

## 诚实标注(样本局限)

- **样本仅 8 条(7 条已回填)**,统计意义有限。0.0% 是"三层全中=0",**不是方向全错**;宽松方向口径 4/7≈57%。
- "中信逆向被忽略"有 5/8 天数据支撑,但模型内部推理不可见,**因果关系无法完全证明**(是"没喂对语义"还是"喂了模型不学"需 A/B 验证)。
- 8/18 极端日(电子-7.26%)区间必偏,**这部分是正常方差,不是 AI 退化**;但"猜小跌实际跳水"的幅度低估方向,疑似区间约束+逆向忽略叠加。
- reflections 归因"学错"(8/14 把逆向当偏空)是**最隐蔽的问题**:错误归因注入=固化错误,比不注入更糟。

## 待验证(下一步该测什么)

1. **A/B 实验:prompt 加"中信逆向反用"指引**(如"中信期货 dominant_dir=逆向时,加多→次日倾向看跌,加空→次日倾向看涨"),对照 7 天方向命中率。这是最直接可验证"语义没教对"的实验。
2. **reflections 注入升级**:从"失败描述"改为"提炼归因变量"(如"中信逆向信号在 8/14 被判偏空导致误判,下次注意逆向反用"),验证是否改善。
3. **debate 票决逻辑**:bull/bear 谁该胜出的加权规则(是否给"聪明钱信号"更高权重),用 8/14/8/17 两猜反样本反推权重。
4. **区间校准**:极端日(单日板块±5%+)时是否放宽区间宽度上限,或对 confidence 降档。
5. **跨周末专项**:8/14 周五→8/17 周一这类跨周末预测,是否单独标注低置信。
6. **8/20 20:40 回填后**:验证 8/19 预测(down -1.5~-1.0)对 8/20 实际,补第 8 个回填样本。

## 复现

- **数据文件**:`/Users/linhuichen/code/trade/static-site/data/daily_brief_history.json`(8条)、`/Users/linhuichen/code/trade/static-site/data/daily_brief.json`(当日)、`/Users/linhuichen/code/trade/static-site/data/futures.json`(中信/机构/国泰席位)、`/Users/linhuichen/code/trade/static-site/data/futures_acc_trend.json`(逆向序列)、`/Users/linhuichen/code/trade/data/daily_brief_reflections.json`(6条失败反思)、`/Users/linhuichen/code/trade/data/brief_reflections_injected.json`(3天注入归档)
- **关键代码**:`/Users/linhuichen/code/trade/scripts/gen_daily_brief.py`
  - `_history_stats` L2173-2192(严格口径 stats)
  - `backfill_hits` L1943-2100(次日回填三层判定)
  - `_classify_failure` L2490-2597(失败归因,8/14 逆向误读源头)
  - `record_reflections` L2620-2660(时间隔离)
  - `build_reflection_inject` L2694-2757(注入=失败描述非变量)
  - `split_domains` L1323-1389(fund 域含期货数据)
  - `build_editor_messages` L1496-1603(主编 sys_text,只 L588 一句"逆向=相反")
  - `RANGE_MAX_WIDTH` L1647(区间宽度硬限 0.5)
- **命令**:
  ```bash
  # 预测历史+stats
  python3 -c "import json;d=json.load(open('static-site/data/daily_brief_history.json'));print(d['stats']);[print(i['date'],i['meta']['direction'],i['meta'].get('range'),i['meta']['hit']) for i in d['items']]"
  # 中信逆向信号逐日
  python3 -c "import json;f=json.load(open('static-site/data/futures.json'));[print(x['date'],x['citic_dir'],x['total_chg'],x['next_return'],x['correct']) for x in f['citic_ih_detail']['details']]"
  # 8/18 北证50 当日(证明追涨)
  python3 -c "import sqlite3;c=sqlite3.connect('file:/Users/linhuichen/code/trade-data/data/sentiment.db?mode=ro',uri=True);print(c.execute(\"SELECT date,index_id,pct_change FROM index_daily WHERE date='20260818' AND index_id='bj50'\").fetchall())"
  ```
- **数据截止**:2026-08-20 12:59(盘中);8/19 预测待 8/20 20:40 回填
- **关键口径**:预测=基于 date 收盘数据,预测**次日**;hit 判定=三层全中(大盘区间+中间层7+板块);stats 严格口径=仅含区间且三层全中计中;reflections=方向命中口径
