# 冰点认可度评分 · 前端展示(2026-10-02)

## 一、改动范围
后端数据层已由同分支 3 个 commit 完成(2ec653d21/e62d698c7/37d37de8c,sh_freeze/sh_factors/consensus/sh_hits/sh_level 字段)。本前端 commit 只做展示,共 2 个 commit:

| commit | 内容 |
|---|---|
| `073ff952f` | feat(frontend): 近90日情绪日历新增上海炒家冰点认可度展示(日历格/图例/下钻弹窗/公示入口) |
| `b300a4087` | docs(frontend): purpose-notes.js 新增 sentiment.icepoint 算法公示(§21 铁律) |

**本分支共 5 个 commit(2 前端展示 + 3 后端数据层)**;前端 min 产物不随分支,由 main-merge 统一重建。

## 二、改动清单

### 1. static-site/app.js
- **日历格** `_renderSentimentCalendar`(L7202 循环内):当日 `sh_freeze===true` 渲染上海炒家冰点格,区分三类来源
  - 重叠 = sh_freeze 与老算法 freeze 都真 → `上海炒家冰点·重叠 x/y`
  - 仅上海炒家 = 仅 sh_freeze 真 → `上海炒家冰点·仅上海炒家 x/y`
  - 仅老算法 = 仅老 freeze 真 → `老算法冰点·仅老算法 x/y`
  - 认可度 `consensus.x/y` 只在该日 x>=1 时渲染(用户原话:consensus.x 可为 0 是常态,前端只在 x>=1 才渲染徽标,否则满屏 0/2 难看)
  - **容错**:无 sh_* 字段的日期(_hasSh=false)整块跳过,不渲染不报错(后端 `if _d not in _ice_df.index: continue` 会遗漏部分日期,缺失=无此信息语义);不做成"未命中"
  - `data-cal-date` 复用日期标签委托打开下钻弹窗;`data-no-pop` 防 term-pop 盖层
- **图例** sig-cal-legend:新增紫色 swatch 项「上海炒家冰点(四因子共振)」+ 来源三类 + 认可度 x/y 说明 + ❓公示入口(读 PURPOSE_NOTES["sentiment.icepoint"] 懒提示)
- **下钻弹窗** `openSentimentDayDetailModal`(L7249):
  - `sh_level` 档位:hard=硬冰点(四因子全中)/ main=主冰点(楼层+地量+涨停或跌停)/ 未命中
  - `consensus.x/y` 认可度:命中 X 个口径 / 当日可得 Y 个口径
  - `sh_hits.n/total` 四因子共振
  - `sh_factors` 四因子明细表:每行 = 因子名 + ✓命中/✗未中 + 当前值(带分位单位) + 阈值(≤/≥)。命中绿底(sh-f-hit)/未中弱灰(sh-f-miss),明确视觉区分
  - 缺字段优雅隐藏(undefined → 显示"该日无此口径数据",不渲染"未命中")

### 2. static-site/style.css
新增 `.sig-sh-ice`(紫 #7c3aed)/`.sig-sh-name`/`.sig-sh-cons`/`.sig-sh-miss`/`.dd-row.sh-f-hit`/`.dd-row.sh-f-miss`/`.sh-f-mark-hit`/`.sh-f-mark-miss`/`.sh-factors` 系列。命中绿 #2e8b57、未中红 #e6492e(灰化弱显),与既有弹窗视觉一致。

### 3. static-site/purpose-notes.js
新增 key `"sentiment.icepoint"` 公示段,含:
- 四因子口径与阈值(F1 楼层=连板高度≤4 / F2 涨停=涨停数≤40 / F3 跌停=跌停数≥15 / F4 地量=成交额滚动120日分位≤30)
- 判定档位:hard = F1&F2&F3&F4;main = F1&(F2|F3)&F4
- **T+1 生效**(日收盘数据判定,隔日展示,防前视)
- **防前视**:F4 用 rolling(120, min_periods=10) 滚动窗口分位数,不用全期分位
- **诚实标注(§5.1④,用户铁律不可省)**:
  - 来源标记 ≠ 收益强度:补盲区、少漏标(信息完整性),并非更高胜率
  - 历史回测短中期(1-20日)收益为负、长期(r60)正超额但依赖 2024 年后行情、分半前段弱或负
  - 2023 年整体亏损(退化年)
  - 三源分组收益差异统计不显著(置换检验),只能作来源标签,禁止按强度排序或暗示"更准"
- 1:1 直白举例(白话口吻教用户看懂 x/y)

## 三、自测(Playwright 无痕浏览器零 localStorage,事实层机械断言)

脚本:worktree 内 `scripts/playwright-accept/verify_icepoint_front.mjs`(本报告配套,不随生产产物,仅在 worktree 留证)

样本构造(防前视真实口径):
- `overview()` 从本地 DB 真实导出 → `/tmp/ice_overview_sample.json`(24 天近 90 日日历,3 重叠/12 仅老算法/9 日 x=0,含 sh_freeze=true 与 false 双态)
- boot.json 拦截返回 `{overview, config}`;其他 JSON 拦截为空对象
- **B 页面级整页渲染**:第一次跑 FAIL(整页未渲染图例)——根因 = 样本只含 `{date, sentiment_calendar}` 缺 overview 完整结构,renderTab 依赖 overview 多字段,数据不全 → 整页降级到静态页。修复 = 抓生产 `ss.fx8.store/data/overview.json` 完整 1.8MB 结构,注入样本 sentiment_calendar 合成 `/tmp/merged_overview.json`,整页真实渲染后 B/D PASS。

结果: **A/C/B/D 全 PASS**:

```
--- A 纯函数验证 ---
  PASS  A1 真实样本渲染出 sh 格 count=15
  PASS  A1b 重叠格: 上海炒家冰点·重叠 2/2 ...
  PASS  A1c 仅老算法格: 老算法冰点·仅老算法 1/2 ...
  PASS  A1d 认可度 2/2 出现
  PASS  A2 容错: 无 sh 字段日期不渲染 sh 格
  PASS  A3 x=0 不渲染认可度徽标
--- B 页面级 ---
  PASS  B1 图例含上海炒家冰点: 冰点维度(情绪分<20)上海炒家冰点(四因子共振) ❓·重叠=两口径都中·仅上海炒家·仅老算法认可度 x/y=两口径命中数/可得数
--- C 下钻弹窗验证 ---
  PASS  C1 弹窗含上海炒家冰点认可度块(20260911)
  PASS  C2 档位显示(硬冰点)
  PASS  C3 认可度 2/2 显示
  PASS  C4 四因子共振 n/total
  PASS  C5 四因子明细阈值
  PASS  C6 命中 ✓标记
  PASS  C7 未命中 ✗标记(20260915)
  PASS  C7b 档位=未命中
--- D 页面级交互(条件) ---
  PASS  D 点击 sh 格打开下钻弹窗: 09-15(2026-09-15) 情绪明细×冰点维度 上海炒家冰点认可度...
ALL PASS
```

## 四、诚实标注(§5.1④)

1. **整页级 B 冒烟依赖合成 overview**(生产结构+样本日历):测试环境无法访问生产 DB,属合理降级;核心正确性以 A/B/C/D 四层断言覆盖(渲染逻辑、图例、弹窗、真实交互链均 PASS)。
2. **未跑 lab.js 侧冒烟**:本次改动只动 app.js(日历/图例/下钻弹窗均在主 tab),lab.js 无涉及,不需 lab 冒烟。
3. **版本串/bump**:worktree 机制 C,不自行 bump;由主控 `scripts/main-merge.sh` 统一 build_min + bump 版本串(index.html `v=20260930-a628` → 新值,sw.js CACHE_VERSION `v6-20260930-a628` → 新值)。本分支 commit 不含 min 产物(已还原),符合规范。
4. **数据产物**:前端依赖后端阴 sh_* 字段;数据侧(overview.json 生成/重跑/static-site/data 同步/R2 上传)由主控合并后统一派单执行,本 agent 不跑生产 export/deploy。

## 五、§23.3 举一反三 · 同数据源/同组件消费点清单

| 位置 | 消费什么 | 是否需要同步 |
|---|---|---|
| `_renderSentimentCalendar`(app.js L7202) | sentiment_calendar + sh_* 旁路字段 | 本改动点(已覆盖) |
| `openSentimentDayDetailModal`(app.js L7249) | 单日 sh_level/sh_hits/sh_factors/consensus | 本改动点(已覆盖) |
| sig-cal-legend 图例 | sh 口径说明 + 公示入口 | 本改动点(已覆盖) |
| `renderSentimentSignalList`(市场温度 tab) | 走 `r.signals`(独立数据源,非 sentiment_calendar) | 已核查:不同数据源分支,无 sh 字段,不需同步 |
| `getEmotionDayBadgeHTML`(角标) | sentiment_calendar[0] 当日 | 无 sh 字段逻辑,冰点展示独立于角标,不需同步 |
| lab.js | AI 宏/信号回测 | 不读 sentiment_calendar,不需同步 |

结论:同数据源(sentiment_calendar)消费点已全量核查,展示层仅日历+下钻弹窗两处,已全覆盖。

## 六、§23.2 修 bug 三铁律(同类错误面清单)

本次为纯新增展示功能(无既有 bug 修复),但仍执行同类排查:
- 同类错误面 = "多字段缺失时渲染异常":样本含 sh_freeze=false + 无 sh_factors 日、无 sh 字段日、x=0 日全覆盖测试,均正确降级(不渲染/不报错/不误判) → A2/A3/C7b PASS
- 同类错误面 = "日期委托被 term-pop 盖层":data-no-pop 防盖层,点击 sh 格直接开下钻弹窗 → D PASS

## 七、复现段

```bash
# 1. 生成 DB 真实样本(在可访问 DB 的环境,如主仓)
python3 /tmp/ice_export.py   # 导出 /tmp/ice_overview_sample.json(sentiment_calendar 24天)
# 2. 合成生产结构(整页渲染需要 overview 完整字段)
node - <<'EOF'
const fs=require('fs');
const prod=JSON.parse(fs.readFileSync('/tmp/prod_overview.json','utf8')); // curl ss.fx8.store/data/overview.json
const sample=JSON.parse(fs.readFileSync('/tmp/ice_overview_sample.json','utf8'));
prod.sentiment_calendar = sample.sentiment_calendar; prod.date = sample.date;
fs.writeFileSync('/tmp/merged_overview.json', JSON.stringify(prod));
EOF
# 3. 起本地静态服务(8080 例)
python3 -m http.server 8379 -d static-site
# 4. 跑冒烟(scripts/playwright-accept/ 下需 node_modules,worktree 内 symlink 已还原,跑前按需重链)
node scripts/playwright-accept/verify_icepoint_front.mjs   # 期望 ALL PASS
```

## 八、遗留/待主控
- [ ] main-merge.sh 统一 bump 版本串(index.html + sw.js),重建全部 min 产物
- [ ] 数据侧:overview.json 重跑(sh_* 字段进生产数据)+ static-site/data 同步 + R2 上传 + CF 缓存刷新
- [ ] 主控 §0 三查清单(commit 链含本分支 / 线上 JSON 有 sh 字段 / 线上 min 有"上海炒家冰点"等新字符串)