# lite-svg perColor 分段色变点「尖角未消 + 区域变色滞后」根因调研(2026-08-17)

> 角色:researcher。只读不改代码,结论+证据,供主控验收与 implementer 实施。

## 一、结论速览
1. **主控假设①(折角只修段尾没修段首)= 确认成立**。`140fe8cee` 的 fix 只新增 `_lwLineDIdxCtx`(static-site/app.js L12345)让上段「到达」色变点时用中心差分(ctxKEnd 借下一色段点);但下段从色变点重新 M 起,段首 p0=p1=色变点(L12364 `_pk=(k>_segK)?k-1:k`,段首取自身),「离开」切线仍是前向差分 → 两侧切线不共线,折角依旧。**实测 fix 前 120.9° → fix 后 114.3°(恐贪 8 个色变点样本),几乎无变化 = 用户「实测没变化」的直接证据**。
2. **新增根因②(颜色切换滞后)= 确认成立**。perColor 分支(L12576-12596)每段从 rs2 画到 `_nxt`=re+1(下一色段首点),但 stroke 用本段旧色 c0 → **色变点 re→re+1 之间那一小段线被旧色覆盖,新色要等下一段从 re+1 起才出现 = 旧色延伸一个点距**。三图 `_lwLineCard`(L13375)series 无 areaOpacity,「区域变色」即指折线分段色切换边界滞后。
3. **根治方案一次改造 `_lwLineDIdxCtx` 可同时消两病**:
   - 段首 p0 跨段借前一色段最后点(`idx[kStart-1]`,相邻时)→ 离开切线=中心差分=与上段到达方向共线(几何实测修复后全部 0.0°,真平滑);
   - 段绘制边界改为「共享端点」:段 i 画到 re(旧色最后点)止,段 i+1 从 re 起用新色 → 颜色在数据点 re 精确切换,不再滞后。
4. **同类清单**:同分支(connectNulls+perColor)共 5 处消费者(恐贪/情绪分/跨市场/过拟合风险分 L1777/信号弹窗 L4670),全被本次调用点覆盖但问题都在;非 connectNulls perColor 分支(L12598-12628,用 `_lwLineD`)同根因但**当前无消费者**(所有 itemColor line 均 connectNulls:true),属隐患一并修;`_etfTrendSVG`(L19650)单色无 perColor,不属同类。

## 二、渲染路径确认(验证点 1)
- 三图全部走 `_lwLineCard`(恐贪 L11099 / 情绪分 L11170 / 跨市场 L11472),liteCfg series(L13387-13391):`{type:"line", smooth:true, connectNulls:true, itemColor:(opts._lwColorFn)||null, ...}`,**smooth 恒 === true、connectNulls 恒 === true**。
- 三图 `_lwColorFn` 均为 5 档色函数(恐贪 L11099-11109 `fgColor`;情绪分 L11170-11180 `asColor`;跨市场 L11463-11472 `cmColor`),非 null → 渲染走 L12560-12596 **connectNulls+perColor 分支**(非 L12598-12628 分支,也非 `_etfTrendSVG`)。
- `_lwLineCard` series **无 areaOpacity**(L13385-13395),即无面积填充,用户「区域变色」= 折线分段色切换边界。
- `_lwSetup`(L13225)cfg 无 zoomStart/zoomEnd → 默认全窗口渲染,色变点角度不受 dataZoom 裁剪影响。

## 三、根因确认 + 几何证据(验证点 2)
Catmull-rom→cubic 控制点公式(全站同算法):`c1=p1+(p2-p0)/6`、`c2=p2-(p3-p1)/6`。

设色变点 P=idx[re+1](re 为旧色段最后一个点,re+1 为下一色段首点),A=idx[re-1],B=idx[re+2]:
- **上段到达 P**(fix 后,ctxKEnd=re+2):p1=idx[re],p3=idx[re+2] → 到达切向 ∝ **(idx[re+2]-idx[re])=中心差分** ✓(fix 前是前向差分 idx[re+1]-idx[re],旧版 139.5° 即此);
- **下段离开 P**(现状):p0=p1=P(L12364 段首 `_pk=k`),p2=idx[re+2] → 离开切向 ∝ **(idx[re+2]-P)=前向差分**;
- 两方向夹角即折角,仅在数据恰共线时为 0°;**段首借 A 后** p0=idx[re-1] → 离开切向 ∝ (idx[re+2]-idx[re])=**与到达方向同一向量,夹角恒 0°(共线 180°)**。

用 overview.json 真实序列复现(脚本 docs/scripts/lite-corner-vertex-geom.py):
```
恐贪指数:  色段99 当前折角 平均111.0° min1.2° max156.8° | 修复段首后 平均0.0°
A股情绪分: 色段103 当前折角 平均36.1°  min0.5° max113.1° | 修复段首后 平均0.0°
跨市场评分: 色段58  当前折角 平均90.0°  min3.1° max165.1° | 修复段首后 平均0.0°
```
恐贪逐色变点 fix 前后对比(「实测没变化」直接证据):
```
色变点@idx  3: 161.0°→156.7° |  6: 170.5°→161.5° | 26: 93.6°→90.9° | 28: 163.2°→160.5°
          77: 169.5°→152.7° | 87: 40.6°→37.7°    | 90: 2.2°→0.9°  | 111: 166.3°→153.1°
平均: fix前 120.9° → fix后 114.3°(样本 n=8,全部变化 <10°)
```
> 注:commit 声称「139.5°→95.0°」的测法与上文口径(全色变点 vs 非单点段)略异,但方向一致:fix 只把到达方向从前向改中心差分,**离开方向没动,折角主体仍在**(90°~165°),肉眼难辨改善。

### 边界情况(修复需覆盖)
- **色变点是首点**(首段 kStart=0):无前一点,段首 p0=自身(现状),首点切线退化无害(echarts smooth 同);
- **色变点是末点**(末段 `_nxt<0`):ctxKEnd 已被 `Math.min(_idx.length-1, re+2)` 钳制,末点到达切线退化无害;
- **跨 null**(idx 差>1):`_lwLineDIdxCtx` L12348-12351 对 `idx[k+1]>idx[k]+1` 走直线分支保留断点语义;段首借 p0 前必须查 `idx[kStart]-idx[kStart-1]===1`,跨 null 则借自己(防平滑跨空);段尾 p3 已有跨 null 钳制(L12351 `_p3c`)。

## 四、颜色滞后验证(主控新补充疑似根因2)
- 逐行推演(L12576-12596):`re` 为颜色 c0 连续段末;`_nxt=re+1`;`_lwLineDIdxCtx(xs,ys,_idx,rs2,(_nxt<0?re:_nxt),...)` 把**下一色段首点 re+1 纳入本段 path 最后一点**;`stroke=c0`。→ **idx[re]→idx[re+1] 线段被旧色 c0 覆盖,而 idx[re+1] 的值属于下一色段**。
- 复现脚本逐段验证:恐贪几乎每段(除末段)`idx[_nxt] 真色 ≠ stroke 色`,例:段59 stroke=#e6a23c 画到 idx93,而 idx93 值 37.87 真色=#4fc3f7;**旧色多画 re→re+1 一个点距,新色从 re+1 之后才出现**。色段数 99/103/58,几乎处处滞后。
- echarts visualMap 对照:echarts 每段线以「段内数据点色」绘制,色变点 re+1 处目标段色即出现,无此滞后 → 与 echarts 观感不一致。

## 五、同类排查清单(验证点 3,§23.2 三铁律③)
| # | 位置 | 分支/引擎 | 是否同根因 | 消费者(影响页面) | 是否需一并修 |
|---|---|---|---|---|---|
| 1 | L12560-12596 + `_lwLineDIdxCtx` L12345 | connectNulls+perColor(本次) | **是**(折角+颜色滞后) | 恐贪 L11099 / 情绪分 L11170 / 跨市场 L11472 / **过拟合风险分 L1777**(`_renderOverfitRisk`,rgColorFn 绿黄红,固定 y 0-100,h160)/ **信号弹窗 L4670**(`_lwSignalLiteCfg`,有 visualMap.pieces 时 _colorFn 非 null) | **必须**,5 处同一分支同一修法 |
| 2 | L12598-12628 | 非 connectNulls perColor,`_lwLineD` L12289 | **同根因**(且 L12611 段边界 i→i+1 无桥接会断线) | **当前无消费者**(所有 itemColor line 均 connectNulls:true;L1668/L1673 itemColor=null 走单色) | 隐患,建议一并修(防未来误用) |
| 3 | L19650 `_etfTrendSVG` | 独立 SVG 引擎,单色 `_stroke`(首尾涨跌红/绿) | **否**(无 perColor 分段) | ETF 走势图 | 不适用 |
| 4 | L12619/L12674 `_lwLineD` | 常规单色 line | 否(无分段色) | 分时/腾落等 | 不适用 |

> 注:L12567-12569 的 `_lwLineDIdx`(connectNulls 但**无** perColor)为单色线,无色变点无折角,不涉。

## 六、根治方案要点(验证点 4,带锚点,不写完整代码)
一次改造 `_lwLineDIdxCtx` + 调用边界,两病同消:

1. **段首跨段借前一点**(改 L12364 `const _pk=(k>_segK)?k-1:k;`):
   ```js
   // 段首 k==kStart 且前一点相邻(跨色段借前一色段最后点) → 中心差分, 与上段到达方向共线(折角→0)
   const _pk = (k > _segK) ? k - 1
     : ((kStart > 0 && idx[kStart] - idx[kStart - 1] === 1) ? kStart - 1 : k);
   ```
2. **段绘制边界改「共享端点」**(改 L12576-12596 段循环:绘制起点与颜色判定起点分离):
   - 首段:绘制 [0, re0],颜色判定 c0=perColor(idx[0]);
   - 后续段 i:绘制起点 = 上一段 re(共享端点,旧色值点),颜色判定起点 = re+1(取 c1=perColor(idx[re+1])),绘制 [prev_re, re_i],stroke=c1;
   - `_lwLineDIdxCtx` 调用参数:kEnd 由 `_nxt(=re+1)` 改为 **`re`**(画到旧色最后点止),ctxKEnd 不变 `Math.min(_idx.length-1, re+2)`;
   - 末位单点(re===rs2Col===len-1 且无共享前序)保留画圆点分支;中间单点段照常画线(从 prev_re 到该单点)。
   - 效果:色变点 re 处旧色线到 re 止、re→re+1 及之后新色,**颜色在数据点 re 精确切换(去向色),不再滞后一个点距**;共享端点保证线连续无断点。
3. **边界**(见第三节):首点 p0 取自身;末点 ctxKEnd 钳制;段首借点前查相邻(跨 null 取自身);跨 null 直线分支保留。
4. **肉眼验收**:色变点两侧切线共线(0° 折角),整条线连续圆润接近 echarts smooth+visualMap;颜色切换正好在色变数据点,无旧色延伸。改造范围仅 connectNulls+perColor 分支(5 处消费者同时生效),`_lwLineDIdx`(单色)/`_lwLineD`(常规)不动;L12598-12628 非 connectNulls perColor 分支建议同步移植「段首借点+共享端点」防未来误用断线。

## 复现
- 生成脚本:`docs/scripts/lite-corner-vertex-geom.py`(复制于调研临时脚本,死脚本副本)
- 输入依赖:`static-site/data/overview.json`(fear_greed_6m/a_sentiment_6m/cross_market_6m 的 value 序列,截至 2026-08-16 数据)
- 重跑命令:`python3 docs/scripts/lite-corner-vertex-geom.py`
- 关键口径:与前端一致 — `_lwLineCard` liteCfg(boundaryGap:true, smooth:true, connectNulls:true, itemColor=5档色函数);catmull-rom→cubic 控制点 `c1=p1+(p2-p0)/6`、`c2=p2-(p3-p1)/6`;y extent 简化(raw min/max);角度=色变点「上段到达切线 vs 下段离开切线」夹角(0°=共线平滑,非 0°=折角)。

## 实施验证(2026-08-17 implementer, a319)
- **可见分段色 line 图(恐贪/情绪分/跨市场)根治已生效并上线**:忠实重演部署逻辑(_lwLineDIdxCtx 段首借前一色段末点中心差分 + 共享端点 + kEnd=re 去向色)对真实 overview.json 序列验证 — 三图色变点折角 0.00°(avg 与 max 均 0.00)、颜色去向色不一致=0、全点覆盖无断点。部署核实:3 域名(ss.fx8.store/sss.sugas.site/s.sugas.site) `app.min.js` md5 与本地构建一致, 均含 `_lwLineDIdxCtx`。
- **第 3 次用户反馈根因判定**:可见图代码已对并已上线(隐私窗口仍"没修好"更可能是**发布/版本时点问题** — 修复 commit 与版本 a318 上线存在窗口; 非代码 bug)。为彻底消除歧义 + 排查同类, 本次:
- **同类补全(§23.2③/§23.3)**:非 connectNulls perColor 分支(原 L12635-12654, 用 `_lwLineD` 逐段独立 M 起, 段边界无桥接断线 + 色变点切线退化尖角, 与 connectNulls 分支同一根因)虽当前无消费者, 已用同法根治(共享端点 `_prevRe` + 段首借点 `_idx` 以 run 首 `_a` 锚 kStart 相对位置 + `_idx` 延伸至 `min(_b,i+2)` 供 ctxKEnd 中心差分; 首段 `_ks=0` 不借/跨 null 不借; 单点色段保留 symbol 圆点)。忠实重演多场景(多色/last 段在 run 尾/offset run 起/单点色段)折角≈0°(≤1e-6)全连续。版本串 a318→a319, sw CACHE_VERSION v6-20260817-a319。
- 全站 _lw perColor 分段色 line 绘制点清单(全覆盖):①connectNulls+perColor 5 消费者(恐贪 L11099/情绪分 L11170/跨市场 L11472/过拟合风险分 L1777/信号弹窗 L4670, a307 已修)②非 connectNulls perColor(无消费者, 本 commit a319 修)。单色 sparkline/KPI/分时/ETF趋势(`_etfTrendSVG`)无分段色不属同类。
- 复现:重演脚本为本次临时验证(折角/去向色逐点核), 结果已核; 几何根因脚本仍用上节 `docs/scripts/lite-corner-vertex-geom.py`。
