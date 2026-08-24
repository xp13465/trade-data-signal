# 「有跟踪ETF」口径矛盾·终版调研报告(主控落档)

日期:2026-08-24 | 角色:researcher(a8a3043)产出,主控搬运落档 | 关联:P0 反思 CLAUDE.md §23.13(memory has-track-caliber-p0-reflection)

## 〇、定案(实锤)

**后端归类实现 = 违背自家产品文档的实现 bug,其余三方(首页 hover/首页❓帮助文档/凯利区标注)全对。** 统一目标口径 = 用户拍板的「跟踪分<50 或数据不足」= tier∈{none(30-49), null(<30 或 N<30 无分)}。

| 展示位 | 文案说法 | 实际判定逻辑 | 判决 |
|---|---|---|---|
| 首页信号列表筛选档4 | 「track_tier=none/null(暗橙/灰灯，跟踪分<50或数据不足)」 app.js L4860 | `_etfTier`:`if (_t==="none" || _t===null) return 4;` app.js L2562 | 对(基准) |
| 首页❓帮助文档 | 「score 30-49→暗橙灯(none);<30 或 N<30→灰灭灯(null)**同归筛选档4**」 app.js L5214 | 同上 | 对(公式化标准) |
| 凯利区 has_track 卡标注 | desc「track_tier=none (track_score<50…)」 signal_kelly_backtest.py L127→lab.js L8133 渲染 | `etf_quad_map={"strong","related","approx","none"}`,null 不在 map→不入任何卡 L1079/L1144 | **文案对、实现错** |
| X1 键 spec | 「整剔无跟踪档位象限(track_tier=none)」 loss_rules.py L128 | 等值匹配 `(ctx.get("track_tier") or "")=="none"`,null/"" 不命中 L210-213 | 跟随后端实现,需同步扩 |

「<50」最早出处:commit **026b4f26c(2026-08-09**,etf_has_track 档引入当天)——desc 从出生起写 <50、实现从出生起只装 none,**初版实现就漏装**,非后来漂移。

## 一、数据实况(generated_at 2026-08-24 07:08)

- 全量去重成交 **38,199 笔**;tier 分布:related 15,099 / none 8,099 / strong 7,581 / approx 5,557 / **null 1,863(4.9%)**
- 四张 ETF 卡 tier 纯度:strong/related/approx/has_track 各自纯档;**null 的 1,863 笔四卡零归属**(实锤掉卡外)
- null 笔 track_score 全部有值且 <30(max 29.2)=「score<30 极弱」型;「N<30 无分」型因 §23.6 入样依赖本就在宇宙外零成交 → **扩 null 进卡实际新增就是这 1,863 笔**
- null 笔类型:buy_special 967 / buy_aux 462 / buy 303 / buy_backup 131

## 二、改动点清单(方向B:实现对齐标注,首页不动)

1. **signal_kelly_backtest.py L1079**:`etf_quad_map` 加 `None:"has_track"`(dict 支持 None 键,tier 仅五态无脏值);L124-127 etf_has_track desc 改「track_tier=none/null (track_score<50 或数据不足…)」+文件头注释
2. **loss_rules.py**:L127 `track_tier="none"`→`["none","null"]`;L210-213 谓词改多值 in 匹配(`spec_val` list/tuple 归一);仅 X1 用此字段其他键零影响
3. **queries.py L746-763 三态区分(防误伤关键坑)**:top1 tier=None 返 `"null"`,与「概念无ETF」的 "" 区分——否则 X1 含 "" 会误判档5;无 etfs/ts 缺失仍返 ""
4. **lab.js**:L7440 谓词 in 匹配;L7565 ctx 组装三态(trades 直读 null→"null");公示三处(L9138 X1 tooltip/L9300 new15 tooltip/L7323 注释)+ common.js preset 注释 L759-761
5. **重跑范围**:signal_kelly_backtest.py → quadrants.etf_has_track 从 8,099 扩到 ~9,962 去重笔 → backtest+trades 双产物 + §22 三步;凯利区卡 label/desc JSON 驱动自动跟随零前端结构改动
6. 版本联动:建议发中间版本(§5.4⑥)——默认 NEW14 行为不变(X1 默认关),但归类口径+可选档语义+公示数字变

## 三、前置差异数字(裸 K1 口径,⚠局限标注)

- 仅剔 none 选中 1,520 天 → 剔 none+null 选中 1,502 天(**18 天转空仓**,占 1.2%)
- G 模式净利差 **-11,701 元** / H 模式 **-4,429 元**(null 顶替笔全是正贡献,剔了少赚)
- 18 天高度集中:thsc_300008→515030×15天(score25.5)/ bj50→159543×3天(score3.9)/ thsc_309020→159538×2天(score21.9);2020-2026 每年零星 1-6 天
- ⚠局限:未叠 NEW14 黑名单(NEW14 下 none 幸存子层全史仅 17 笔,null 幸存预计更少,真实边际趋近噪声)/每笔固定1万/X1 非默认不影响现网

## 四、机检联动(三个都不撞,实锤)

check_fade_keys_alignment(X1 非默认成员,grep 零命中)/ audit_bug_patterns D2(只对账键名清单,键名不变)/ check_loss_rules_vs_mining 层2(只遍历挖掘键,X1 不在其中)。

## 五、待用户拍板项

**X1 剔除范围是否跟随卡扩围**:①一起扩(口径完全统一,初算少赚~1.2万裸口径)vs ②卡扩 X1 不扩(保收益,留新分叉点)。正式穷举回测(NEW14/+1/+1' 三版 × K1/K2 × A-I × 五窗 × 双费率+替补分解+bootstrap,mine29c §10 同款)在实施 merge 后单派,mine29c 的 new15 宣传数字(+57/-3,550)作废待重算。

## 复现

```bash
# 权威判定逻辑四方对照
sed -n '2560,2564p' static-site/app.js; sed -n '5210,5218p' static-site/app.js
sed -n '124,128p' scripts/signal_kelly_backtest.py; sed -n '1075,1082p' scripts/signal_kelly_backtest.py
sed -n '125,130p' scripts/loss_rules.py; sed -n '208,215p' scripts/loss_rules.py
# null 掉卡外实况
python3 -c "
import json,collections
d=json.load(open('static-site/data/signal_kelly_trades.json'))
c=collections.Counter(t.get('track_tier') for t in d.get('trades',[]) if t.get('track_tier') is None or t.get('track_tier')=='none')
print(dict(c))"  # 以实际 schema 为准,详见进度文件 /tmp/agent-progress-has-track-caliber.md
```

数据截止:main d0bd31856 工作区(2026-08-24);关键口径:v1.1.5 默认=NEW14,X1 为 new15 可选档成员,默认组合行为不受本修复影响。
